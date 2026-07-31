"""PyQtGraph-backed detector image viewer for the stable Qt interface."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PyQt5.QtCore import QEvent, QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

import pyqtgraph as pg
import pyqtgraph.exporters

from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array
from sciview.interfaces.theme.app_style import AppStyle
from sciview.settings.viewer_config import (
    ARTIST_IMAGE_COLORMAPS,
    ARTIST_IMAGE_PALETTES,
    SUPPORTED_IMAGE_COLORMAPS,
    SUPPORTED_IMAGE_SCALES,
    VIEWER_BEHAVIOR,
    VIEWER_COLORS,
    VIEWER_TOOL_ICON_FILES,
    VIEWER_TOOLBAR_ACTIONS,
)


pg.setConfigOptions(imageAxisOrder="row-major")


@dataclass(frozen=True)
class ImagePointerEvent:
    """Image-coordinate mouse event passed from the viewer to tab tools."""

    x: float
    y: float
    button: object
    modifiers: object
    inside_image: bool


class ImageViewer(QWidget):
    """Display detector images using PyQtGraph while preserving SciView coordinates.

    Detector coordinates are ``x = array column`` and ``y = array row`` with the
    origin at the upper-left. For logarithmic display, non-positive and non-finite
    values are rendered at the lowest valid positive display level; the source
    image array is never modified.
    """

    cursor_moved = pyqtSignal(float, float, object)
    view_changed = pyqtSignal(object)
    levels_changed = pyqtSignal(float, float)
    colormap_changed = pyqtSignal(str)
    mouse_pressed = pyqtSignal(object)
    mouse_moved = pyqtSignal(object)
    mouse_released = pyqtSignal(object)

    _SUPPORTED_COLORMAPS = set(SUPPORTED_IMAGE_COLORMAPS) | set(ARTIST_IMAGE_COLORMAPS)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_array: np.ndarray | None = None
        self._display_array: np.ndarray | None = None
        self._display_levels: tuple[float, float] | None = None
        self._levels: tuple[float | None, float | None] = (None, None)
        self._scale = "linear"
        self._colormap_name = SUPPORTED_IMAGE_COLORMAPS[0]
        self._overlays: dict[str, tuple[Any, str | None]] = {}
        self._interaction_locked = False
        self._updating_histogram = False

        self._graphics = pg.GraphicsLayoutWidget()
        self._graphics.setBackground(VIEWER_COLORS.background)
        self._plot_item = self._graphics.addPlot(row=0, col=0)
        self._plot_item.setAspectLocked(True, ratio=VIEWER_BEHAVIOR.aspect_ratio)
        self._plot_item.invertY(True)
        self._plot_item.setMenuEnabled(False)
        self._plot_item.showAxis("left")
        self._plot_item.showAxis("bottom")
        self._plot_item.setLabel("bottom", "x", units="px")
        self._plot_item.setLabel("left", "y", units="px")
        self._view_box = self._plot_item.getViewBox()
        self._view_box.setBackgroundColor(VIEWER_COLORS.background)
        self._view_box.setMouseMode(pg.ViewBox.PanMode)
        self._view_box.sigRangeChanged.connect(self._emit_view_changed)

        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._plot_item.addItem(self._image_item)
        self._image_item.setVisible(False)

        self._histogram = pg.HistogramLUTItem(image=self._image_item)
        self._histogram.setMinimumWidth(100)
        self._histogram.sigLevelsChanged.connect(self._on_histogram_levels_changed)
        self._graphics.addItem(self._histogram, row=0, col=1)

        self._message_item = pg.TextItem(text="", color=VIEWER_COLORS.message, anchor=(0.5, 0.5))
        self._plot_item.addItem(self._message_item)
        self._message_item.setVisible(False)

        self._graphics.scene().sigMouseMoved.connect(self._on_scene_mouse_moved)
        self._graphics.viewport().installEventFilter(self)

        toolbar_actions = {action.key: action for action in VIEWER_TOOLBAR_ACTIONS}
        self._pan_button = self._make_tool_button(toolbar_actions["pan"], self._load_toolbar_icon("pan"))
        self._zoom_button = self._make_tool_button(toolbar_actions["zoom"], self._load_toolbar_icon("zoom"))
        self._home_button = self._make_tool_button(toolbar_actions["home"], self._load_toolbar_icon("home"))
        self._auto_levels_button = self._make_tool_button(toolbar_actions["auto"], self._load_toolbar_icon("auto"))
        self._copy_button = self._make_tool_button(toolbar_actions["copy"], self._load_toolbar_icon("copy"))
        self._save_button = self._make_tool_button(toolbar_actions["save"], self._load_toolbar_icon("save"))
        self._palette_info_label = QLabel("")
        self._palette_info_label.setVisible(False)
        self._palette_info_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._palette_info_label.setStyleSheet("color: #4b5563; padding-left: 6px;")
        self._pan_button.setCheckable(True)
        self._zoom_button.setCheckable(True)
        self._pan_button.setChecked(True)
        self._pan_button.clicked.connect(self._activate_pan_mode)
        self._zoom_button.clicked.connect(self._activate_zoom_mode)
        self._home_button.clicked.connect(self.reset_view)
        self._auto_levels_button.clicked.connect(self._on_auto_levels_clicked)
        self._copy_button.clicked.connect(self.copy_rendered_view_to_clipboard)
        self._save_button.clicked.connect(self._choose_export_path)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(2)
        toolbar.addWidget(self._pan_button)
        toolbar.addWidget(self._zoom_button)
        toolbar.addWidget(self._home_button)
        toolbar.addWidget(self._auto_levels_button)
        toolbar.addWidget(self._copy_button)
        toolbar.addWidget(self._save_button)
        toolbar.addWidget(self._palette_info_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._graphics)
        layout.addLayout(toolbar)

        self.set_colormap(self._colormap_name)

    @property
    def source_array(self) -> np.ndarray | None:
        return self._source_array

    @property
    def display_array(self) -> np.ndarray | None:
        return self._display_array

    @property
    def display_levels(self) -> tuple[float, float] | None:
        return self._display_levels

    def set_image(self, image: Any, *, preserve_view: bool = True) -> None:
        array, is_valid, error_msg = validate_and_prepare_image_array(image, use_converter=True)
        if not is_valid:
            self.clear_image(error_msg)
            return

        old_shape = self._source_array.shape if self._source_array is not None else None
        old_range = self.get_view_range() if preserve_view and old_shape == array.shape else None
        self._source_array = array
        self._message_item.setVisible(False)
        self._image_item.setVisible(True)
        self._refresh_display_image()

        if old_range is not None:
            self.set_view_range(old_range)
        else:
            self.reset_view()

    def set_color_image(self, image: Any, *, preserve_view: bool = True) -> None:
        array = np.asarray(image)
        if array.ndim != 3 or array.shape[2] not in (3, 4):
            self.clear_image("Color image must be RGB or RGBA")
            return

        old_shape = self._source_array.shape if self._source_array is not None else None
        old_range = self.get_view_range() if preserve_view and old_shape == array.shape[:2] else None
        if array.dtype != np.ubyte:
            if np.issubdtype(array.dtype, np.floating) and np.nanmax(array) <= 1.0:
                array = np.clip(array, 0.0, 1.0) * 255.0
            array = np.clip(array, 0, 255).astype(np.ubyte)

        self._source_array = array
        self._display_array = array
        self._display_levels = None
        self._message_item.setVisible(False)
        self._image_item.setLookupTable(None)
        self._image_item.setVisible(True)
        self._image_item.setImage(array, autoLevels=False)

        if old_range is not None:
            self.set_view_range(old_range)
        else:
            self.reset_view()

    def clear_image(self, message: str | None = None) -> None:
        self._source_array = None
        self._display_array = None
        self._display_levels = None
        self._image_item.clear()
        self._image_item.setVisible(False)
        self._message_item.setText(message or "")
        self._message_item.setPos(0.5, 0.5)
        self._message_item.setVisible(bool(message))

    def set_levels(self, vmin: float | None, vmax: float | None) -> None:
        self._levels = (self._finite_or_none(vmin), self._finite_or_none(vmax))
        self._refresh_display_image(preserve_view=True)

    def auto_levels(self) -> tuple[float, float] | None:
        """Set robust color limits from the current 2D source image."""
        if self._source_array is None or self._source_array.ndim != 2:
            return None

        image = np.asarray(self._source_array, dtype=float)
        if self._scale == "log":
            values = image[np.isfinite(image) & (image > 0)]
        else:
            values = image[np.isfinite(image)]
        if values.size == 0:
            return None

        low_pct, high_pct = VIEWER_BEHAVIOR.auto_level_percentiles
        vmin, vmax = np.percentile(values, [low_pct, high_pct])
        vmin = float(vmin)
        vmax = float(vmax)
        if not (np.isfinite(vmin) and np.isfinite(vmax)):
            return None
        if vmax <= vmin:
            vmin = float(np.min(values))
            vmax = float(np.max(values))
        if vmax <= vmin:
            delta = max(abs(vmin) * 0.01, 1.0)
            vmin -= delta
            vmax += delta

        self._levels = (vmin, vmax)
        self._refresh_display_image(preserve_view=True)
        self.levels_changed.emit(vmin, vmax)
        return vmin, vmax

    def apply_next_artist_palette(self) -> str | None:
        """Apply a random hidden artist palette and return its colormap key."""
        if not ARTIST_IMAGE_PALETTES:
            return None

        candidates = [palette for palette in ARTIST_IMAGE_PALETTES if palette.key != self._colormap_name]
        palette = random.choice(candidates or list(ARTIST_IMAGE_PALETTES))
        self.set_colormap(palette.key)
        self.colormap_changed.emit(palette.key)
        return palette.key

    def set_colormap(self, name: str) -> None:
        if name not in self._SUPPORTED_COLORMAPS:
            raise ValueError(f"Unsupported colormap: {name}")
        self._colormap_name = name
        lut = self._artist_palette_lut(name) if name in ARTIST_IMAGE_COLORMAPS else self._matplotlib_lut(name)
        self._image_item.setLookupTable(lut)
        self._update_palette_info_label(name)
        try:
            self._histogram.gradient.setColorMap(pg.ColorMap(np.linspace(0.0, 1.0, lut.shape[0]), lut))
        except Exception:
            pass

    def set_scale(self, scale: str) -> None:
        if scale not in SUPPORTED_IMAGE_SCALES:
            raise ValueError(f"Unsupported image scale: {scale}")
        self._scale = scale
        self._refresh_display_image(preserve_view=True)

    def set_title(self, title: str) -> None:
        self._plot_item.setTitle(title)

    def set_interaction_locked(self, locked: bool) -> None:
        """Lock pan/zoom handling while preserving pointer signals for tools."""
        self._interaction_locked = bool(locked)
        self._view_box.setMouseEnabled(x=not locked, y=not locked)
        self._pan_button.setEnabled(not locked)
        self._zoom_button.setEnabled(not locked)
        if locked:
            self._pan_button.setChecked(False)
            self._zoom_button.setChecked(False)
        elif self._view_box.state.get("mouseMode") == pg.ViewBox.RectMode:
            self._zoom_button.setChecked(True)
        else:
            self._pan_button.setChecked(True)

    def _on_auto_levels_clicked(self) -> None:
        if QApplication.keyboardModifiers() & Qt.AltModifier:
            self.apply_next_artist_palette()
        self.auto_levels()

    def _update_palette_info_label(self, name: str) -> None:
        palette = ARTIST_IMAGE_COLORMAPS.get(name)
        if palette is None:
            self._palette_info_label.clear()
            self._palette_info_label.setVisible(False)
            return

        text = f"{palette.artist} - {palette.artwork}"
        self._palette_info_label.setText(text)
        self._palette_info_label.setToolTip(f"{palette.source}: {text}")
        self._palette_info_label.setVisible(True)

    def reset_view(self) -> None:
        if self._source_array is None:
            self._view_box.autoRange(padding=0.0)
            return
        height, width = self._source_array.shape[:2]
        self._view_box.setRange(xRange=(0, width), yRange=(0, height), padding=0.0)

    def get_view_range(self) -> tuple[tuple[float, float], tuple[float, float]]:
        x_range, y_range = self._view_box.viewRange()
        return (tuple(float(value) for value in x_range), tuple(float(value) for value in y_range))

    def set_view_range(self, view_range: object) -> None:
        x_range, y_range = view_range  # type: ignore[misc]
        self._view_box.setRange(xRange=x_range, yRange=y_range, padding=0.0)

    def get_raw_value_at(self, x: float, y: float) -> object | None:
        if self._source_array is None or not (np.isfinite(x) and np.isfinite(y)):
            return None
        row = int(y)
        column = int(x)
        height, width = self._source_array.shape[:2]
        if 0 <= column < width and 0 <= row < height:
            return self._source_array[row, column]
        return None

    def set_overlay_item(self, overlay_id: str, item: Any, *, group: str | None = None, visible: bool = True) -> None:
        self.remove_overlay(overlay_id)
        self._plot_item.addItem(item)
        item.setVisible(visible)
        self._overlays[overlay_id] = (item, group)

    def add_points(
        self,
        overlay_id: str,
        x: list[float] | tuple[float, ...] | np.ndarray,
        y: list[float] | tuple[float, ...] | np.ndarray,
        *,
        group: str | None = None,
        color: str = VIEWER_COLORS.default_point,
        size: float = VIEWER_BEHAVIOR.default_point_size,
        symbol: str = "o",
        pen: str | None = None,
    ) -> Any:
        item = pg.ScatterPlotItem(
            x=np.asarray(x, dtype=float),
            y=np.asarray(y, dtype=float),
            pen=pg.mkPen(pen or color, width=1.5),
            brush=pg.mkBrush(color),
            size=size,
            symbol=symbol,
        )
        item.setZValue(20)
        self.set_overlay_item(overlay_id, item, group=group)
        return item

    def add_circle(
        self,
        overlay_id: str,
        center_x: float,
        center_y: float,
        radius: float,
        *,
        group: str | None = None,
        color: str = VIEWER_COLORS.default_circle,
        width: float = VIEWER_BEHAVIOR.default_line_width,
        points: int = VIEWER_BEHAVIOR.circle_sample_points,
    ) -> Any:
        theta = np.linspace(0.0, 2.0 * np.pi, points)
        x = float(center_x) + float(radius) * np.cos(theta)
        y = float(center_y) + float(radius) * np.sin(theta)
        item = pg.PlotDataItem(x, y, pen=pg.mkPen(color, width=width))
        item.setZValue(15)
        self.set_overlay_item(overlay_id, item, group=group)
        return item

    def add_polyline(
        self,
        overlay_id: str,
        x: list[float] | tuple[float, ...] | np.ndarray,
        y: list[float] | tuple[float, ...] | np.ndarray,
        *,
        group: str | None = None,
        color: str = VIEWER_COLORS.default_line,
        width: float = VIEWER_BEHAVIOR.default_line_width,
    ) -> Any:
        item = pg.PlotDataItem(np.asarray(x, dtype=float), np.asarray(y, dtype=float), pen=pg.mkPen(color, width=width))
        item.setZValue(15)
        self.set_overlay_item(overlay_id, item, group=group)
        return item

    def add_text(
        self,
        overlay_id: str,
        x: float,
        y: float,
        text: str,
        *,
        group: str | None = None,
        color: str = VIEWER_COLORS.default_line,
        anchor: tuple[float, float] = (0.5, 0.5),
    ) -> Any:
        item = pg.TextItem(text=text, color=color, anchor=anchor)
        item.setPos(float(x), float(y))
        item.setZValue(25)
        self.set_overlay_item(overlay_id, item, group=group)
        return item

    def add_crosshair(
        self,
        overlay_id: str,
        center_x: float,
        center_y: float,
        *,
        group: str | None = None,
        color: str = VIEWER_COLORS.default_crosshair,
        width: float = 1.0,
    ) -> tuple[Any, Any, Any]:
        if self._source_array is None:
            return ()
        height, width_px = self._source_array.shape[:2]
        horizontal = pg.PlotDataItem([0, width_px], [center_y, center_y], pen=pg.mkPen(color, width=width))
        vertical = pg.PlotDataItem([center_x, center_x], [0, height], pen=pg.mkPen(color, width=width))
        center = pg.PlotDataItem(
            [center_x - 3, center_x + 3, np.nan, center_x, center_x],
            [center_y, center_y, np.nan, center_y - 3, center_y + 3],
            pen=pg.mkPen(color, width=2.0),
        )
        for suffix, item in (("h", horizontal), ("v", vertical), ("center", center)):
            item.setZValue(15)
            self.set_overlay_item(f"{overlay_id}:{suffix}", item, group=group)
        return horizontal, vertical, center

    def add_mask_overlay(
        self,
        overlay_id: str,
        mask: np.ndarray,
        *,
        group: str | None = None,
        color: str = VIEWER_COLORS.default_mask,
        alpha: float = 0.5,
    ) -> Any:
        rgba = self._rgba_mask(mask, color, alpha)
        existing = self._overlays.get(overlay_id)
        if existing is not None and isinstance(existing[0], pg.ImageItem):
            existing[0].setImage(rgba, autoLevels=False)
            existing[0].setVisible(True)
            return existing[0]

        item = pg.ImageItem(rgba, axisOrder="row-major")
        item.setZValue(5)
        self.set_overlay_item(overlay_id, item, group=group)
        return item

    def set_overlay_visible(self, overlay_id: str, visible: bool) -> None:
        item = self._overlays[overlay_id][0]
        item.setVisible(visible)

    def remove_overlay(self, overlay_id: str) -> None:
        overlay = self._overlays.pop(overlay_id, None)
        if overlay is not None:
            self._plot_item.removeItem(overlay[0])

    def clear_overlays(self, group: str | None = None) -> None:
        overlay_ids = [
            overlay_id
            for overlay_id, (_, overlay_group) in self._overlays.items()
            if group is None or overlay_group == group
        ]
        for overlay_id in overlay_ids:
            self.remove_overlay(overlay_id)

    def export_rendered_view(self, path: str | Path) -> None:
        exporter = pg.exporters.ImageExporter(self._plot_item)
        exporter.export(str(path))

    def copy_rendered_view_to_clipboard(self) -> bool:
        pixmap = self._graphics.grab()
        if pixmap.isNull():
            return False
        QApplication.clipboard().setPixmap(pixmap)
        return True

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self._graphics.viewport() and event.type() in {
            QEvent.MouseButtonPress,
            QEvent.MouseMove,
            QEvent.MouseButtonRelease,
        }:
            pointer_event = self._pointer_event_from_viewport_pos(event.pos(), event.button(), event.modifiers())
            if event.type() == QEvent.MouseButtonPress:
                self.mouse_pressed.emit(pointer_event)
            elif event.type() == QEvent.MouseMove:
                self.mouse_moved.emit(pointer_event)
            elif event.type() == QEvent.MouseButtonRelease:
                self.mouse_released.emit(pointer_event)
            if self._interaction_locked:
                return True
        if watched is self._graphics.viewport() and event.type() == QEvent.Wheel and self._interaction_locked:
            return True
        return super().eventFilter(watched, event)

    def _refresh_display_image(self, *, preserve_view: bool = False) -> None:
        if self._source_array is None:
            return
        old_range = self.get_view_range() if preserve_view else None
        if self._scale == "log":
            self._display_array, self._display_levels = self._log_display_image(self._source_array, *self._levels)
        else:
            self._display_array = self._source_array
            self._display_levels = self._linear_levels(*self._levels)

        image_kwargs: dict[str, Any] = {"autoLevels": self._display_levels is None}
        if self._display_levels is not None:
            image_kwargs["levels"] = self._display_levels
        self._image_item.setImage(self._display_array, **image_kwargs)
        if self._display_levels is not None:
            self._updating_histogram = True
            try:
                self._histogram.setLevels(*self._display_levels)
            finally:
                self._updating_histogram = False
        if old_range is not None:
            self.set_view_range(old_range)

    def _on_histogram_levels_changed(self) -> None:
        if self._updating_histogram:
            return
        try:
            display_min, display_max = self._histogram.getLevels()
        except Exception:
            return
        if not (np.isfinite(display_min) and np.isfinite(display_max) and display_max > display_min):
            return

        if self._scale == "log":
            raw_min = float(10.0**display_min)
            raw_max = float(10.0**display_max)
        else:
            raw_min = float(display_min)
            raw_max = float(display_max)
        self._levels = (raw_min, raw_max)
        self._display_levels = (float(display_min), float(display_max))
        self.levels_changed.emit(raw_min, raw_max)

    def _pointer_event_from_viewport_pos(self, pos: QPointF, button: object, modifiers: object) -> ImagePointerEvent:
        scene_pos = self._graphics.mapToScene(pos)
        view_pos = self._view_box.mapSceneToView(scene_pos)
        x = float(view_pos.x())
        y = float(view_pos.y())
        inside = self._is_inside_image(x, y)
        return ImagePointerEvent(x=x, y=y, button=button, modifiers=modifiers, inside_image=inside)

    def _on_scene_mouse_moved(self, scene_pos: QPointF) -> None:
        if self._source_array is None:
            return
        view_pos = self._view_box.mapSceneToView(scene_pos)
        x = float(view_pos.x())
        y = float(view_pos.y())
        value = self.get_raw_value_at(x, y)
        self.cursor_moved.emit(x, y, value)

    def _emit_view_changed(self, *_args: object) -> None:
        self.view_changed.emit(self.get_view_range())

    def _is_inside_image(self, x: float, y: float) -> bool:
        if self._source_array is None or not (np.isfinite(x) and np.isfinite(y)):
            return False
        height, width = self._source_array.shape[:2]
        return 0 <= x < width and 0 <= y < height

    def _activate_pan_mode(self) -> None:
        self._view_box.setMouseMode(pg.ViewBox.PanMode)
        self._pan_button.setChecked(True)
        self._zoom_button.setChecked(False)

    def _activate_zoom_mode(self) -> None:
        self._view_box.setMouseMode(pg.ViewBox.RectMode)
        self._pan_button.setChecked(False)
        self._zoom_button.setChecked(True)

    def _choose_export_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save displayed image",
            "",
            "PNG Images (*.png);;All Files (*)",
        )
        if path:
            self.export_rendered_view(path)

    def _load_toolbar_icon(self, key: str) -> QIcon:
        icon_filename = VIEWER_TOOL_ICON_FILES.get(key)
        if not icon_filename:
            return QIcon()
        workspace_root = Path(__file__).resolve().parents[5]
        return AppStyle.load_icon(workspace_root, icon_filename)

    @staticmethod
    def _make_tool_button(action: Any, icon: QIcon) -> QToolButton:
        button = QToolButton()
        if icon.isNull():
            button.setText(action.label)
        else:
            button.setIcon(icon)
            button.setIconSize(AppStyle.tab_icon_size())
        button.setToolTip(action.tooltip)
        button.setAutoRaise(True)
        button.setFixedSize(AppStyle.toolbar_symbol_button_size())
        return button

    @staticmethod
    def _finite_or_none(value: float | None) -> float | None:
        if value is None:
            return None
        value = float(value)
        return value if np.isfinite(value) else None

    @staticmethod
    def _linear_levels(vmin: float | None, vmax: float | None) -> tuple[float, float] | None:
        if vmin is None or vmax is None or vmax <= vmin:
            return None
        return (float(vmin), float(vmax))

    @staticmethod
    def _log_display_image(
        image: np.ndarray,
        vmin: float | None,
        vmax: float | None,
    ) -> tuple[np.ndarray, tuple[float, float] | None]:
        finite_positive = image[np.isfinite(image) & (image > 0)]
        if finite_positive.size == 0:
            return np.zeros(image.shape, dtype=float), None

        min_positive = float(np.min(finite_positive))
        max_positive = float(np.max(finite_positive))
        safe_vmin = float(vmin) if vmin is not None and vmin > 0 else min_positive
        safe_vmax = float(vmax) if vmax is not None and vmax > safe_vmin else max_positive
        if safe_vmax <= safe_vmin:
            safe_vmax = max_positive
        if safe_vmax <= safe_vmin:
            safe_vmax = safe_vmin * 10.0

        floor_value = np.log10(safe_vmin)
        display = np.full(image.shape, floor_value, dtype=float)
        valid = np.isfinite(image) & (image > 0)
        display[valid] = np.log10(image[valid])
        return display, (floor_value, np.log10(safe_vmax))

    @staticmethod
    def _matplotlib_lut(name: str) -> np.ndarray:
        import matplotlib as mpl

        colormap = mpl.colormaps[name]
        return (colormap(np.linspace(0.0, 1.0, 256))[:, :3] * 255).astype(np.ubyte)

    @staticmethod
    def _artist_palette_lut(name: str) -> np.ndarray:
        import matplotlib.colors as mcolors

        palette = ARTIST_IMAGE_COLORMAPS[name]
        colors = ImageViewer._ordered_artist_colors(palette.colors)
        colormap = mcolors.LinearSegmentedColormap.from_list(name, colors, N=256)
        return (colormap(np.linspace(0.0, 1.0, 256))[:, :3] * 255).astype(np.ubyte)

    @staticmethod
    def _ordered_artist_colors(colors: tuple[str, ...]) -> tuple[str, ...]:
        import colorsys
        import matplotlib.colors as mcolors

        def sort_key(color: str) -> tuple[float, float, float]:
            red, green, blue = mcolors.to_rgb(color)
            hue, saturation, _lightness = colorsys.rgb_to_hls(red, green, blue)
            return (ImageViewer._relative_luminance((red, green, blue)), hue, saturation)

        return tuple(sorted(colors, key=sort_key))

    @staticmethod
    def _relative_luminance(rgb: tuple[float, float, float]) -> float:
        red, green, blue = rgb
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    @staticmethod
    def _rgba_mask(mask: np.ndarray, color: str, alpha: float) -> np.ndarray:
        import matplotlib.colors as mcolors

        r, g, b = mcolors.to_rgb(color)
        rgba = np.zeros((*mask.shape, 4), dtype=np.ubyte)
        mask_bool = np.asarray(mask, dtype=bool)
        rgba[mask_bool, 0] = int(r * 255)
        rgba[mask_bool, 1] = int(g * 255)
        rgba[mask_bool, 2] = int(b * 255)
        rgba[mask_bool, 3] = int(np.clip(float(alpha), 0.0, 1.0) * 255)
        return rgba