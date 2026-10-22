"""Native Qt mask gesture previews with a single pixel-mask commit per edit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import math

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtWidgets import QGraphicsPathItem, QGraphicsRectItem

from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array
from sciview.interfaces.stable_qt.widgets.image_viewer import ImagePointerEvent, ImageViewer
from sciview.interfaces.stable_qt.tools.drawing_interaction import DrawingGesture
from sciview.masking.drawing import (
    Pixel, paint_brush_segment, paint_circle,
    paint_line, paint_polygon, paint_rectangle,
)
from sciview.masking.layers import MaskLayer
from sciview.masking.operations import watershed_fill_mask
from sciview.settings.viewer_config import MASK_DRAWING_DEFAULTS, VIEWER_COLORS

logger = logging.getLogger(__name__)


class DrawingTool:
    """Gesture state; pixel painting is delegated to the neutral masking backend."""

    def __init__(self, name: str):
        self.name = name
        self.brush_size = int(MASK_DRAWING_DEFAULTS["brush_size"])
        self.draw_value = True
        self.gesture = DrawingGesture()

    @property
    def kind(self) -> str:
        return self.name.lower().replace(" ", "_")

    @staticmethod
    def qt_point(point: Pixel) -> QPointF:
        return QPointF(point[1] + 0.5, point[0] + 0.5)

    @staticmethod
    def pixel(point: QPointF) -> Pixel:
        return int(point.y()), int(point.x())

    @property
    def is_active(self) -> bool:
        return self.gesture.active

    @property
    def start_point(self) -> Pixel | None:
        return self.pixel(self.gesture.points[0]) if self.gesture.active else None

    @property
    def last_draw_point(self) -> Pixel | None:
        return self.pixel(self.gesture.current) if self.gesture.current is not None else None

    def begin(self, point: Pixel) -> None:
        self.gesture.press(self.kind, self.qt_point(point))

    def reset(self) -> None:
        self.gesture.cancel()


class BrushDrawingTool(DrawingTool):
    def __init__(self):
        super().__init__("Brush")


class LineDrawingTool(DrawingTool):
    def __init__(self):
        super().__init__("Line")


class RectangleDrawingTool(DrawingTool):
    def __init__(self):
        super().__init__("Rectangle")


class CircleDrawingTool(DrawingTool):
    def __init__(self):
        super().__init__("Circle")


class PolygonDrawingTool(DrawingTool):
    def __init__(self):
        super().__init__("Polygon")

    @property
    def vertices(self) -> list[Pixel]:
        return [self.pixel(point) for point in self.gesture.points]

    def add_vertex(self, point: Pixel) -> None:
        self.gesture.press("polygon", self.qt_point(point))


class WatershedFillTool(DrawingTool):
    def __init__(self):
        super().__init__("Smart Fill")


@dataclass(frozen=True)
class _BrushSample:
    point: Pixel
    radius: int
    value: bool


class MaskDrawingSession:
    """Keep pointer motion in Qt; compose and publish masks only after a commit."""

    def __init__(
        self,
        *,
        is_enabled: Callable[[], bool],
        get_tool: Callable[[], DrawingTool | None],
        get_active_layer: Callable[[], MaskLayer | None],
        get_layers: Callable[[], list[MaskLayer]],
        get_viewer: Callable[[], ImageViewer],
        get_image_data: Callable[[], np.ndarray | None],
        set_drawing_enabled: Callable[[bool], None],
        should_auto_disable: Callable[[], bool],
        get_brush_size: Callable[[], int],
        get_draw_value: Callable[[], bool],
        on_edit_finished: Callable[[int, np.ndarray, np.ndarray], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        self.is_enabled = is_enabled
        self.get_tool = get_tool
        self.get_active_layer = get_active_layer
        self.get_layers = get_layers
        self.get_viewer = get_viewer
        self.get_image_data = get_image_data
        self.set_drawing_enabled = set_drawing_enabled
        self.should_auto_disable = should_auto_disable
        self.get_brush_size = get_brush_size
        self.get_draw_value = get_draw_value
        self.on_edit_finished = on_edit_finished
        self.on_error = on_error
        self._edit_layer: MaskLayer | None = None
        self._edit_tool: DrawingTool | None = None
        self._samples: list[_BrushSample] = []
        self._preview: QGraphicsRectItem | None = None
        self._shape_item: QGraphicsPathItem | None = None
        self._stroke_item: QGraphicsPathItem | None = None
        self._stroke_gesture = DrawingGesture()
        self._stroke_style: tuple[int, bool] | None = None

    @staticmethod
    def _qt_point(point: Pixel) -> QPointF:
        return DrawingTool.qt_point(point)

    def _sync_tool(self, tool: DrawingTool) -> None:
        tool.brush_size = max(1, self.get_brush_size())
        tool.draw_value = self.get_draw_value()

    def _begin_edit(self, layer: MaskLayer, tool: DrawingTool) -> None:
        self._edit_layer = layer
        self._edit_tool = tool
        height, width = layer.data.shape
        self._preview = QGraphicsRectItem(0, 0, width, height)
        self._preview.setPen(pg.mkPen(None))
        self._preview.setBrush(pg.mkBrush(None))
        self._preview.setFlag(QGraphicsRectItem.ItemClipsChildrenToShape, True)
        self._preview.setAcceptedMouseButtons(Qt.NoButton)
        self._preview.setZValue(30)
        self._preview.setOpacity(0.5)
        self.get_viewer().set_overlay_item(
            "mask-drawing-preview", self._preview,
            group="mask-drawing-preview", ignore_bounds=True,
        )

    def _edit_target(self) -> tuple[int, MaskLayer] | None:
        layer = self._edit_layer
        if layer is None or not layer.visible or self.get_active_layer() is not layer:
            return None
        if self.get_tool() is not self._edit_tool:
            return None
        for index, candidate in enumerate(self.get_layers()):
            if candidate is layer:
                return index, layer
        return None

    def handle_press(self, event: ImagePointerEvent) -> None:
        if event.button != Qt.LeftButton or not self.is_enabled():
            return
        tool = self.get_tool()
        if tool is None:
            return
        if self._edit_layer is not None and self._edit_target() is None:
            self.cancel_current_edit()
        layer = self.get_active_layer()
        if layer is None or not layer.visible:
            return
        point = self._event_point(event, tool, layer.data.shape)
        if point is None:
            return
        self._sync_tool(tool)
        if not isinstance(tool, PolygonDrawingTool) or not tool.vertices:
            self.cancel_current_edit()
            self._begin_edit(layer, tool)
        if isinstance(tool, PolygonDrawingTool):
            tool.add_vertex(point)
        else:
            tool.begin(point)
        if isinstance(tool, BrushDrawingTool):
            self._append_brush_sample(point, tool)
        else:
            self._show_shape(tool)

    def handle_motion(self, event: ImagePointerEvent) -> None:
        tool = self._edit_tool
        if not self.is_enabled() or tool is None:
            return
        target = self._edit_target()
        if target is None:
            self.cancel_current_edit()
            return
        point = self._event_point(event, tool, target[1].data.shape)
        if point is None:
            return
        self._sync_tool(tool)
        tool.gesture.move(self._qt_point(point))
        if isinstance(tool, BrushDrawingTool):
            self._append_brush_sample(point, tool)
        else:
            self._show_shape(tool)

    def handle_release(self, event: ImagePointerEvent) -> None:
        tool = self._edit_tool
        if event.button != Qt.LeftButton or tool is None or isinstance(tool, PolygonDrawingTool):
            return
        target = self._edit_target()
        if target is None or not self.is_enabled():
            self.cancel_current_edit()
            return
        point = self._event_point(event, tool, target[1].data.shape) or tool.last_draw_point
        if point is None:
            self.cancel_current_edit()
            return
        self._sync_tool(tool)
        if not tool.gesture.release(self._qt_point(point)):
            self.cancel_current_edit()
            return
        if isinstance(tool, BrushDrawingTool):
            self._append_brush_sample(point, tool)
        self._commit(point)

    def handle_double_click(self, event: ImagePointerEvent) -> bool:
        tool = self._edit_tool
        if event.button != Qt.LeftButton or not isinstance(tool, PolygonDrawingTool):
            return False
        target = self._edit_target()
        if target is None or not self.is_enabled():
            self.cancel_current_edit()
            return False
        point = self._event_point(event, tool, target[1].data.shape)
        if point is None:
            return False
        if tool.gesture.finish_polygon(self._qt_point(point)):
            return self.finish_polygon()
        return False

    def _append_brush_sample(self, point: Pixel, tool: DrawingTool) -> None:
        sample = _BrushSample(point, tool.brush_size, tool.draw_value)
        if self._samples and sample == self._samples[-1]:
            return
        previous = self._samples[-1].point if self._samples else point
        self._samples.append(sample)
        style = (sample.radius, sample.value)
        if self._stroke_item is None or style != self._stroke_style:
            self._stroke_gesture.press("brush", self._qt_point(previous))
            self._stroke_item = QGraphicsPathItem(self._preview)
            self._stroke_item.setAcceptedMouseButtons(Qt.NoButton)
            pen = pg.mkPen(self._preview_color(sample.value), width=sample.radius * 2, cosmetic=False)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            self._stroke_item.setPen(pen)
            self._stroke_style = style
        self._stroke_gesture.move(self._qt_point(point))
        if previous == point:
            dot = QGraphicsPathItem(self._preview)
            dot.setPath(self._stroke_gesture.path(sample.radius * 2, filled=True))
            dot.setPen(pg.mkPen(None))
            dot.setBrush(pg.mkBrush(self._preview_color(sample.value)))
            dot.setAcceptedMouseButtons(Qt.NoButton)
        if len(self._stroke_gesture.points) > 1:
            self._stroke_item.setPath(self._stroke_gesture.path(sample.radius * 2))

    @staticmethod
    def _preview_color(value: bool) -> str:
        return VIEWER_COLORS.mask_preview if value else VIEWER_COLORS.default_point

    def _show_shape(self, tool: DrawingTool) -> None:
        path = tool.gesture.path(tool.brush_size * 2, filled=True, pixel_mask=True)
        if self._shape_item is None:
            self._shape_item = QGraphicsPathItem(self._preview)
            self._shape_item.setAcceptedMouseButtons(Qt.NoButton)
            self._shape_item.setPen(pg.mkPen(None))
        self._shape_item.setBrush(pg.mkBrush(self._preview_color(tool.draw_value)))
        self._shape_item.setPath(path)

    def finish_polygon(self) -> bool:
        tool = self._edit_tool
        if not isinstance(tool, PolygonDrawingTool) or not tool.gesture.finish_polygon():
            return False
        if not self.is_enabled() or self._edit_target() is None:
            self.cancel_current_edit()
            return False
        self._sync_tool(tool)
        return self._commit(tool.vertices[-1])

    def _commit(self, point: Pixel) -> bool:
        target = self._edit_target()
        tool = self._edit_tool
        if target is None or tool is None:
            self.cancel_current_edit()
            return False
        index, layer = target
        before = layer.data
        after = before.copy()
        try:
            if isinstance(tool, BrushDrawingTool):
                previous = self._samples[0].point
                for sample in self._samples:
                    paint_brush_segment(after, previous, sample.point, sample.radius, sample.value)
                    previous = sample.point
            elif isinstance(tool, PolygonDrawingTool):
                paint_polygon(after, tool.vertices, tool.draw_value)
            elif tool.start_point is not None:
                start = tool.start_point
                if isinstance(tool, RectangleDrawingTool):
                    paint_rectangle(after, start, point, tool.draw_value)
                elif isinstance(tool, CircleDrawingTool):
                    paint_circle(after, start, point, tool.draw_value)
                elif isinstance(tool, LineDrawingTool):
                    paint_line(after, start, point, tool.brush_size, tool.draw_value)
                elif isinstance(tool, WatershedFillTool):
                    image, valid, error = validate_and_prepare_image_array(self.get_image_data())
                    if not valid:
                        raise ValueError(error)
                    fill = watershed_fill_mask(
                        image, seed_point=start, seed_radius=max(1, tool.brush_size // 2),
                    )
                    after[fill] = tool.draw_value
        except (ValueError, TypeError, RuntimeError) as error:
            logger.exception("Could not commit mask drawing")
            self.on_error(error)
            return False
        finally:
            self.cancel_current_edit()
        if not np.array_equal(before, after):
            layer.data = after
            self.on_edit_finished(index, before, after)
        if self.should_auto_disable():
            self.set_drawing_enabled(False)
        return True

    def cancel_current_edit(self) -> None:
        if self._edit_tool is not None:
            self._edit_tool.reset()
        if self._preview is not None:
            self.get_viewer().remove_overlay("mask-drawing-preview")
        self._edit_tool = None
        self._edit_layer = None
        self._preview = None
        self._shape_item = None
        self._stroke_item = None
        self._stroke_gesture.cancel()
        self._stroke_style = None
        self._samples.clear()

    @staticmethod
    def _event_point(event: ImagePointerEvent, tool: DrawingTool, shape: tuple[int, ...]) -> Pixel | None:
        if not event.inside_canvas or not (math.isfinite(event.x) and math.isfinite(event.y)):
            return None
        if isinstance(tool, WatershedFillTool) and not event.inside_image:
            return None
        height, width = shape
        return max(0, min(height - 1, int(event.y))), max(0, min(width - 1, int(event.x)))
