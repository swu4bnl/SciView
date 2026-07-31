"""Configuration values for stable Qt image viewing and mask drawing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ViewerColors:
    background: str = "w"
    message: tuple[int, int, int] = (180, 180, 180)
    default_point: str = "#00ffff"
    default_line: str = "#ffffff"
    default_circle: str = "#ff0000"
    default_crosshair: str = "#ff0000"
    default_mask: str = "#ef4444"


@dataclass(frozen=True)
class ViewerBehavior:
    aspect_ratio: float = 1.0
    circle_sample_points: int = 240
    default_point_size: float = 8.0
    default_line_width: float = 1.5


@dataclass(frozen=True)
class ViewerToolbarAction:
    key: str
    label: str
    tooltip: str


VIEWER_COLORS = ViewerColors()
VIEWER_BEHAVIOR = ViewerBehavior()

SUPPORTED_IMAGE_COLORMAPS = ("gray", "viridis", "plasma", "inferno", "jet")
SUPPORTED_IMAGE_SCALES = ("linear", "log")

VIEWER_TOOLBAR_ACTIONS = (
    ViewerToolbarAction("pan", "Pan", "Pan image: drag with the left mouse button."),
    ViewerToolbarAction("zoom", "Zoom", "Rectangular zoom: drag a box with the left mouse button."),
    ViewerToolbarAction("home", "Home", "Reset the image view to the full detector frame."),
    ViewerToolbarAction("save", "Save", "Save the rendered view with the current colormap and overlays."),
)

MASK_TOOL_NAMES = ("Brush", "Line", "Rectangle", "Circle", "Watershed Fill")
MASK_DRAWING_DEFAULTS = {
    "brush_size": 5,
    "corner_zone_ratio": 0.15,
}