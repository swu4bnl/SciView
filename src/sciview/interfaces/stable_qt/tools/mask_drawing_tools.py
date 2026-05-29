"""
Mask Drawing Tools

Provides interactive drawing tools for mask creation and editing.
Tools handle both drawing logic and event coordination with automatic edge detection.
Each tool can be used independently: tool.on_press(), tool.on_motion(), tool.on_release()
"""

import numpy as np
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Callable
from PyQt5.QtGui import QCursor
from PyQt5.QtCore import Qt

from sciview.masking.operations import watershed_fill_mask
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array


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
    """
    Base class for interactive drawing tools with full event handling.
    
    Manages:
    - Drawing state (is_dragging, last_draw_point, pointer tracking)
    - Zone-based corner detection for out-of-canvas drawing
    - Event flow (press → motion → release)
    - Preview/finalize pattern for non-destructive editing
    
    Derived tools only need to implement:
    - start(point): Initialize drawing
    - preview(layer, point): Show non-destructive preview
    - finalize(layer, point): Apply drawing to layer
    """
    
    def __init__(self, name: str):
        self.name = name
        self.brush_size = 5
        self.draw_value = True  # True = add (mask), False = remove (unmask)
        self.is_active = False  # Track if tool is in drawing state
        
        # Drawing state (inherited by all tools)
        self.is_dragging = False
        self.last_draw_point = None
        self.pointer_left_canvas = False
        self.pointer_exit_edge = None
        
        # Zone-based corner detection configuration
        self.corner_zone_ratio = 0.15  # 15% corners per side
        
        # Optional callbacks
        self.canvas = None
        self.ax = None
        self.parent_app = None
        self.get_image_data = None
    
    def configure(self, canvas, ax, parent_app, image_data_getter=None):
        """Configure the tool with canvas and app references"""
        self.canvas = canvas
        self.ax = ax
        self.parent_app = parent_app
        self.get_image_data = image_data_getter
    
    def set_image_data_getter(self, getter: Callable):
        """Set function to retrieve current image data"""
        self.get_image_data = getter
    
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
    
    # ===== Event Handlers (can be overridden by derived classes) =====
    
    def on_press(self, event):
        """Handle mouse press event - derived classes can override for custom behavior"""
        if not event.inaxes or event.inaxes != self.ax:
            return
        
        self.is_dragging = True
        self.is_active = True
        
        if event.xdata is not None and event.ydata is not None:
            try:
                x, y = int(event.xdata), int(event.ydata)
                point = (y, x)  # (row, col) format for consistency
                self.last_draw_point = point
                self.start(point)
            except (TypeError, ValueError):
                pass
    
    def on_motion(self, event):
        """Handle mouse motion - derived classes can override for custom behavior"""
        if not event.inaxes or event.inaxes != self.ax:
            # Pointer left canvas - detect closest corner/edge
            if self.is_dragging and self.last_draw_point is not None:
                self.pointer_left_canvas = True
                self._detect_exit_edge()
            
            if self.canvas:
                self.canvas.setCursor(QCursor(Qt.CrossCursor))
            return
        
        # Pointer inside canvas
        self.pointer_left_canvas = False
        self.pointer_exit_edge = None
        
        if self.canvas:
            self.canvas.setCursor(QCursor(Qt.CrossCursor))
        
        # Track last valid point
        if event.xdata is not None and event.ydata is not None:
            try:
                x, y = int(event.xdata), int(event.ydata)
                self.last_draw_point = (y, x)
            except (TypeError, ValueError):
                pass
    
    def on_release(self, event):
        """Handle mouse release - derived classes can override for custom behavior"""
        was_dragging = self.is_dragging
        self.is_dragging = False
        
        # Reset state
        self.pointer_left_canvas = False
        self.pointer_exit_edge = None
        
        if self.canvas:
            self.canvas.setCursor(QCursor(Qt.ArrowCursor))
    
    def reset(self):
        """Reset tool state between drawings"""
        self.is_active = False
        self.is_dragging = False
        self.last_draw_point = None
        self.pointer_left_canvas = False
        self.pointer_exit_edge = None
    
    # ===== Edge Detection (shared by all tools) =====
    
    def _detect_exit_edge(self):
        """Detect which corner/edge pointer exited based on zone detection"""
        if self.last_draw_point is None or not self.get_image_data:
            return
        
        try:
            image_data = self.get_image_data()
            image_2d, is_valid, _ = validate_and_prepare_image_array(image_data)
            if not is_valid:
                return
            
            last_y, last_x = self.last_draw_point
            img_height, img_width = image_2d.shape[:2]
            
            # Define zones using configurable ratio
            zone_x = img_width * self.corner_zone_ratio
            zone_y = img_height * self.corner_zone_ratio
            
            x_zone = 0 if last_x < zone_x else (1 if last_x < img_width - zone_x else 2)
            y_zone = 0 if last_y < zone_y else (1 if last_y < img_height - zone_y else 2)
            
            # Build candidate endpoints with zone-based preference ordering
            candidates = self._build_candidates(x_zone, y_zone, last_x, last_y, img_width, img_height)
            
            # Pick first (preferred) candidate
            if candidates:
                self.pointer_exit_edge = candidates[0][0]
        except:
            pass
    
    def _build_candidates(self, x_zone, y_zone, last_x, last_y, img_width, img_height):
        """Build preferred endpoint candidates based on zones"""
        candidates = []
        
        if y_zone == 0:  # Top zones
            if x_zone == 0:  # Top-left
                candidates = [
                    (4, 0, 0),
                    (0, 0, last_y),
                    (2, last_x, 0),
                ]
            elif x_zone == 1:  # Top-center
                candidates = [
                    (2, last_x, 0),
                    (4, 0, 0),
                    (5, img_width - 1, 0),
                ]
            else:  # Top-right
                candidates = [
                    (5, img_width - 1, 0),
                    (1, img_width - 1, last_y),
                    (2, last_x, 0),
                ]
        elif y_zone == 1:  # Middle zones
            if x_zone == 0:  # Left edge
                candidates = [
                    (0, 0, last_y),
                    (4, 0, 0),
                    (6, 0, img_height - 1),
                ]
            elif x_zone == 1:  # Center (prefer closest corner)
                candidates = [
                    (4, 0, 0),
                    (5, img_width - 1, 0),
                    (6, 0, img_height - 1),
                    (7, img_width - 1, img_height - 1),
                    (0, 0, last_y),
                    (1, img_width - 1, last_y),
                    (2, last_x, 0),
                    (3, last_x, img_height - 1),
                ]
            else:  # Right edge
                candidates = [
                    (1, img_width - 1, last_y),
                    (5, img_width - 1, 0),
                    (7, img_width - 1, img_height - 1),
                ]
        else:  # Bottom zones
            if x_zone == 0:  # Bottom-left
                candidates = [
                    (6, 0, img_height - 1),
                    (0, 0, last_y),
                    (3, last_x, img_height - 1),
                ]
            elif x_zone == 1:  # Bottom-center
                candidates = [
                    (3, last_x, img_height - 1),
                    (6, 0, img_height - 1),
                    (7, img_width - 1, img_height - 1),
                ]
            else:  # Bottom-right
                candidates = [
                    (7, img_width - 1, img_height - 1),
                    (1, img_width - 1, last_y),
                    (3, last_x, img_height - 1),
                ]
        
        return candidates
    
    def get_endpoint_for_edge(self, edge_code, last_x, last_y, img_width, img_height):
        """
        Get (x, y) endpoint for a given edge code.
        
        Edge codes:
        - 0=left, 1=right, 2=top, 3=bottom
        - 4=top-left, 5=top-right, 6=bottom-left, 7=bottom-right
        """
        zone_to_endpoint = {
            0: (0, last_y),
            1: (img_width - 1, last_y),
            2: (last_x, 0),
            3: (last_x, img_height - 1),
            4: (0, 0),
            5: (img_width - 1, 0),
            6: (0, img_height - 1),
            7: (img_width - 1, img_height - 1),
        }
        return zone_to_endpoint.get(edge_code, (last_x, last_y))


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
