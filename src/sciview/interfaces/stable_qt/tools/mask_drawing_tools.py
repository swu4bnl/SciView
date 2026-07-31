"""
Mask Drawing Tools

Provides interactive drawing tools for mask creation and editing.
MaskDrawingSession coordinates PyQtGraph pointer events while tools focus on
previewing or mutating boolean mask arrays.
"""

import numpy as np
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Callable

from sciview.masking.operations import watershed_fill_mask
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array
from sciview.interfaces.stable_qt.viewer_config import MASK_DRAWING_DEFAULTS


def _draw_disk(mask_layer: np.ndarray, center_row: int, center_col: int, radius: int, draw_value: bool) -> None:
    """Draw a filled disk into a boolean mask layer."""
    height, width = mask_layer.shape
    safe_radius = max(1, int(radius))
    y_coords, x_coords = np.ogrid[-safe_radius : safe_radius + 1, -safe_radius : safe_radius + 1]
    mask_circle = (x_coords**2 + y_coords**2 <= safe_radius**2)

    y_min = max(0, center_row - safe_radius)
    y_max = min(height, center_row + safe_radius + 1)
    x_min = max(0, center_col - safe_radius)
    x_max = min(width, center_col + safe_radius + 1)

    circle_y_min = y_min - (center_row - safe_radius)
    circle_y_max = circle_y_min + (y_max - y_min)
    circle_x_min = x_min - (center_col - safe_radius)
    circle_x_max = circle_x_min + (x_max - x_min)

    valid_circle = mask_circle[circle_y_min:circle_y_max, circle_x_min:circle_x_max]
    if draw_value:
        mask_layer[y_min:y_max, x_min:x_max][valid_circle] = 1
    else:
        mask_layer[y_min:y_max, x_min:x_max][valid_circle] = 0


class DrawingTool(ABC):
    """Base class for PyQtGraph-driven mask drawing tools.

    The viewer/session owns mouse events. Tools only maintain the minimum drawing
    state needed to preview or mutate a boolean mask layer.
    """
    
    def __init__(self, name: str):
        self.name = name
        self.brush_size = int(MASK_DRAWING_DEFAULTS["brush_size"])
        self.draw_value = True  # True = add (mask), False = remove (unmask)
        self.is_active = False  # Track if tool is in drawing state
        
        # Drawing state (inherited by all tools)
        self.is_dragging = False
        self.last_draw_point = None
        self.parent_app = None
        self.get_image_data = None
    
    def configure(self, canvas, ax, parent_app, image_data_getter=None):
        """Configure optional app references retained for tab compatibility."""
        self.parent_app = parent_app
        self.get_image_data = image_data_getter
    
    def set_image_data_getter(self, getter: Callable):
        """Set function to retrieve current image data"""
        self.get_image_data = getter

    def begin(self, point: Tuple[int, int]) -> None:
        self.is_dragging = True
        self.is_active = True
        self.last_draw_point = point
        self.start(point)

    def move(self, point: Tuple[int, int]) -> None:
        self.last_draw_point = point

    def end(self) -> None:
        self.is_dragging = False
    
    @abstractmethod
    def start(self, point: Tuple[int, int]):
        """Called when mouse is pressed - starts the drawing action"""
        pass
    
    @abstractmethod
    def preview(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        """Generate a preview of what would be drawn without modifying original"""
        pass
    
    @abstractmethod
    def finalize(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        """
        Finalize the drawing action.
        
        Args:
            mask_layer: Current mask layer
            current_point: Final mouse position
        
        Returns:
            Updated mask layer with drawing applied
        """
        pass
    
    def reset(self):
        """Reset tool state between drawings"""
        self.is_active = False
        self.is_dragging = False
        self.last_draw_point = None


class MaskDrawingSession:
    """Coordinate mask drawing events, previews, and layer mutation."""

    def __init__(
        self,
        *,
        is_enabled: Callable[[], bool],
        get_tool: Callable[[], DrawingTool | None],
        get_image_data: Callable[[], object],
        get_active_layer: Callable[[bool], object | None],
        get_active_layer_index: Callable[[bool], int | None],
        get_layers: Callable[[], list],
        get_combine_method: Callable[[], str],
        set_combined_mask: Callable[[np.ndarray], None],
        update_combined_mask: Callable[[], None],
        update_plot: Callable[[], None],
        set_drawing_enabled: Callable[[bool], None],
        should_auto_disable: Callable[[], bool],
        get_brush_size: Callable[[], int],
        get_draw_value: Callable[[], bool],
    ) -> None:
        self.is_enabled = is_enabled
        self.get_tool = get_tool
        self.get_image_data = get_image_data
        self.get_active_layer = get_active_layer
        self.get_active_layer_index = get_active_layer_index
        self.get_layers = get_layers
        self.get_combine_method = get_combine_method
        self.set_combined_mask = set_combined_mask
        self.update_combined_mask = update_combined_mask
        self.update_plot = update_plot
        self.set_drawing_enabled = set_drawing_enabled
        self.should_auto_disable = should_auto_disable
        self.get_brush_size = get_brush_size
        self.get_draw_value = get_draw_value
        self.preview_mask: np.ndarray | None = None

    def handle_press(self, event) -> None:
        tool = self.get_tool()
        if not self.is_enabled() or tool is None:
            return
        point = self._event_point(event, require_inside=True)
        if point is None:
            return
        self._sync_tool(tool)
        tool.begin(point)
        if isinstance(tool, BrushDrawingTool):
            self._draw_brush_stroke(point, tool)
        else:
            self._show_preview(point, tool)

    def handle_motion(self, event) -> None:
        tool = self.get_tool()
        if not self.is_enabled() or tool is None:
            return
        self._sync_tool(tool)
        if not (tool.is_dragging and tool.is_active):
            return
        point = self._event_point(event, require_inside=True)
        if point is None:
            return
        if isinstance(tool, BrushDrawingTool):
            self._draw_brush_stroke(point, tool)
        else:
            tool.move(point)
            self._show_preview(point, tool)

    def handle_release(self, event) -> None:
        tool = self.get_tool()
        if tool is None or not tool.is_dragging:
            return

        if tool.is_active:
            try:
                point = self._event_point(event, require_inside=True) or tool.last_draw_point
                if point is None:
                    return
                if not isinstance(tool, BrushDrawingTool):
                    current_layer = self.get_active_layer(True)
                    if current_layer is None:
                        return
                    current_layer.data = tool.finalize(current_layer.data, point)
                self.update_combined_mask()
                self.update_plot()
            finally:
                self.preview_mask = None
                tool.end()
                tool.reset()

        if self.should_auto_disable():
            self.set_drawing_enabled(False)

    def _sync_tool(self, tool: DrawingTool) -> None:
        tool.brush_size = self.get_brush_size()
        tool.draw_value = self.get_draw_value()

    def _draw_brush_stroke(self, point: tuple[int, int], tool: DrawingTool) -> None:
        current_layer = self.get_active_layer(True)
        if current_layer is None:
            return
        current_layer.data = tool.finalize(current_layer.data, point)
        tool.move(point)
        layer_index = self.get_active_layer_index(False)
        if layer_index is not None:
            self._show_layer_preview(layer_index, current_layer.data)

    def _show_preview(self, point: tuple[int, int], tool: DrawingTool) -> None:
        layer_index = self.get_active_layer_index(True)
        if layer_index is None:
            return
        layers = self.get_layers()
        current_layer = layers[layer_index]
        preview_data = tool.preview(current_layer.data, point)
        self._show_layer_preview(layer_index, preview_data)

    def _show_layer_preview(self, layer_index: int, preview_data: np.ndarray) -> None:
        temp_combined = self._compose_preview(self.get_layers(), layer_index, preview_data)
        preview_mask = temp_combined.astype(bool, copy=False)
        self.set_combined_mask(preview_mask)
        self.preview_mask = preview_mask
        self.update_plot()

    def _compose_preview(self, layers, layer_index: int, preview_data: np.ndarray) -> np.ndarray:
        visible_layers = [layer for layer in layers if layer.visible]
        if not visible_layers:
            return preview_data.astype(bool, copy=False)
        if len(visible_layers) == 1 and layers[layer_index].visible:
            return preview_data.astype(bool, copy=False)
        if self.get_combine_method() == "OR":
            temp_combined = np.zeros_like(preview_data, dtype=bool)
            for idx, layer in enumerate(layers):
                if not layer.visible:
                    continue
                layer_data = preview_data if idx == layer_index else layer.data
                temp_combined = np.logical_or(temp_combined, layer_data)
            return temp_combined

        temp_combined = None
        for idx, layer in enumerate(layers):
            if not layer.visible:
                continue
            layer_data = preview_data if idx == layer_index else layer.data
            temp_combined = layer_data.astype(bool, copy=False) if temp_combined is None else np.logical_and(temp_combined, layer_data)
        return preview_data.astype(bool, copy=False) if temp_combined is None else temp_combined

    @staticmethod
    def _event_point(event, *, require_inside: bool) -> tuple[int, int] | None:
        if require_inside and hasattr(event, 'inside_image') and not bool(event.inside_image):
            return None
        x = getattr(event, 'x', getattr(event, 'xdata', None))
        y = getattr(event, 'y', getattr(event, 'ydata', None))
        if x is None or y is None:
            return None
        try:
            return int(y), int(x)
        except (TypeError, ValueError):
            return None


class BrushDrawingTool(DrawingTool):
    """Freehand brush drawing tool - draws immediately on mouse move"""
    
    def __init__(self):
        super().__init__("Brush")
        self.last_point = None
    
    def start(self, point: Tuple[int, int]):
        """Start brush drawing"""
        self.is_active = True
        self.last_point = point
    
    def preview(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        """For brush, preview is the same as finalize - show immediate feedback"""
        return self.finalize(mask_layer.copy(), current_point)
    
    def finalize(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        """Draw brush stroke with line interpolation"""
        if current_point is None:
            return mask_layer
        
        row, col = current_point
        brush_size = self.brush_size
        height, width = mask_layer.shape
        
        # Draw circle at current point
        y_coords, x_coords = np.ogrid[-brush_size:brush_size+1, -brush_size:brush_size+1]
        mask_circle = (x_coords**2 + y_coords**2 <= brush_size**2)
        
        # Line interpolation if previous point exists
        if self.last_point:
            prev_row, prev_col = self.last_point
            # Simple line interpolation
            steps = max(abs(row - prev_row), abs(col - prev_col))
            if steps > 0:
                for i in range(steps + 1):
                    t = i / max(steps, 1)
                    interp_row = int(prev_row + t * (row - prev_row))
                    interp_col = int(prev_col + t * (col - prev_col))
                    self._draw_circle(mask_layer, interp_row, interp_col, brush_size)
                self.last_point = current_point
                return mask_layer
        
        # Draw at current point
        self._draw_circle(mask_layer, row, col, brush_size)
        self.last_point = current_point
        return mask_layer
    
    def _draw_circle(self, mask_layer: np.ndarray, center_row: int, center_col: int, radius: int):
        """Draw a circle on the mask layer"""
        _draw_disk(mask_layer, center_row, center_col, radius, self.draw_value)
    
    def reset(self):
        """Reset brush state"""
        super().reset()
        self.last_point = None


class LineDrawingTool(DrawingTool):
    """Straight line drawing tool - click to start, drag to preview, release to finalize"""
    
    def __init__(self):
        super().__init__("Line")
        self.start_point = None
    
    def start(self, point: Tuple[int, int]):
        """Set the starting point for the line"""
        self.is_active = True
        self.start_point = point
    
    def preview(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        """Show preview of line without modifying original"""
        if self.start_point is None or current_point is None:
            return mask_layer
        
        # Create a copy to show preview
        preview = mask_layer.copy()
        return self._draw_line(preview, self.start_point, current_point)
    
    def finalize(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        """Apply the final line to the mask"""
        if self.start_point is None or current_point is None:
            return mask_layer
        
        result = self._draw_line(mask_layer, self.start_point, current_point)
        self.reset()
        return result
    
    def _draw_line(self, mask_layer: np.ndarray, start: Tuple[int, int], 
                   end: Tuple[int, int]) -> np.ndarray:
        """Draw a line from start to end point"""
        start_row, start_col = start
        end_row, end_col = end
        
        # Bresenham's line algorithm
        points = self._bresenham_line(start_row, start_col, end_row, end_col)
        
        for row, col in points:
            self._draw_circle(mask_layer, row, col, self.brush_size)
        
        return mask_layer
    
    def _draw_circle(self, mask_layer: np.ndarray, center_row: int, center_col: int, radius: int):
        """Draw a circle on the mask layer"""
        _draw_disk(mask_layer, center_row, center_col, radius, self.draw_value)
    
    @staticmethod
    def _bresenham_line(x0: int, y0: int, x1: int, y1: int):
        """Generate points along a line using Bresenham's algorithm"""
        points = []
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        
        x, y = x0, y0
        while True:
            points.append((x, y))
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
        
        return points
    
    def reset(self):
        """Reset line state"""
        super().reset()
        self.start_point = None


class RectangleDrawingTool(DrawingTool):
    """Rectangular box drawing tool - click to start, drag to preview, release to finalize"""
    
    def __init__(self):
        super().__init__("Rectangle")
        self.start_point = None
    
    def start(self, point: Tuple[int, int]):
        """Set the starting corner for the rectangle"""
        self.is_active = True
        self.start_point = point
    
    def preview(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        """Show preview of rectangle without modifying original"""
        if self.start_point is None or current_point is None:
            return mask_layer
        
        # Create a copy to show preview
        preview = mask_layer.copy()
        return self._draw_rectangle(preview, self.start_point, current_point)
    
    def finalize(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        """Apply the final rectangle to the mask"""
        if self.start_point is None or current_point is None:
            return mask_layer
        
        result = self._draw_rectangle(mask_layer, self.start_point, current_point)
        self.reset()
        return result
    
    def _draw_rectangle(self, mask_layer: np.ndarray, start: Tuple[int, int], 
                       end: Tuple[int, int]) -> np.ndarray:
        """Draw a filled rectangle from start to end point"""
        start_row, start_col = start
        end_row, end_col = end
        
        # Calculate rectangle bounds
        row_min = min(start_row, end_row)
        row_max = max(start_row, end_row)
        col_min = min(start_col, end_col)
        col_max = max(start_col, end_col)
        
        height, width = mask_layer.shape
        row_min = max(0, row_min)
        row_max = min(height, row_max + 1)
        col_min = max(0, col_min)
        col_max = min(width, col_max + 1)
        
        if self.draw_value:
            mask_layer[row_min:row_max, col_min:col_max] = 1
        else:
            mask_layer[row_min:row_max, col_min:col_max] = 0
        
        return mask_layer
    
    def reset(self):
        """Reset rectangle state"""
        super().reset()
        self.start_point = None


class CircleDrawingTool(DrawingTool):
    """Filled circle drawing tool using press as center and drag as radius."""

    def __init__(self):
        super().__init__("Circle")
        self.start_point = None

    def start(self, point: Tuple[int, int]):
        self.is_active = True
        self.start_point = point

    def preview(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        if self.start_point is None or current_point is None:
            return mask_layer
        preview = mask_layer.copy()
        return self._draw_circle(preview, self.start_point, current_point)

    def finalize(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        if self.start_point is None or current_point is None:
            return mask_layer
        result = self._draw_circle(mask_layer, self.start_point, current_point)
        self.reset()
        return result

    def _draw_circle(self, mask_layer: np.ndarray, start: Tuple[int, int], end: Tuple[int, int]) -> np.ndarray:
        center_row, center_col = start
        end_row, end_col = end
        radius = int(round(np.hypot(end_row - center_row, end_col - center_col)))
        _draw_disk(mask_layer, center_row, center_col, max(1, radius), self.draw_value)
        return mask_layer

    def reset(self):
        super().reset()
        self.start_point = None


class WatershedFillTool(DrawingTool):
    """Seeded fill tool that grows a region until image edges stop it."""

    def __init__(self):
        super().__init__("Watershed Fill")
        self.seed_point = None

    def start(self, point: Tuple[int, int]):
        self.is_active = True
        self.seed_point = point

    def preview(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        if self.seed_point is None:
            return mask_layer
        preview = mask_layer.copy()
        return self._apply_fill(preview, self.seed_point)

    def finalize(self, mask_layer: np.ndarray, current_point: Tuple[int, int]) -> np.ndarray:
        if self.seed_point is None:
            return mask_layer
        result = self._apply_fill(mask_layer, self.seed_point)
        self.reset()
        return result

    def _apply_fill(self, mask_layer: np.ndarray, seed_point: Tuple[int, int]) -> np.ndarray:
        if not self.get_image_data:
            return mask_layer

        image_data = self.get_image_data()
        image_2d, is_valid, _ = validate_and_prepare_image_array(image_data)
        if not is_valid:
            return mask_layer

        fill_mask = watershed_fill_mask(
            image_2d,
            seed_point=seed_point,
            seed_radius=max(1, int(self.brush_size // 2)),
        )
        if self.draw_value:
            mask_layer[fill_mask] = 1
        else:
            mask_layer[fill_mask] = 0
        return mask_layer

    def reset(self):
        super().reset()
        self.seed_point = None
