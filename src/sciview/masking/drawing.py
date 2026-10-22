"""Pixel-accurate mask painting, independent of the interactive preview."""

from collections.abc import Sequence

import numpy as np

Pixel = tuple[int, int]


def paint_disk(mask: np.ndarray, center: Pixel, radius: int, value: bool) -> None:
    """Paint a clipped integer-radius disk at a (row, column) pixel."""
    row, col = center
    radius = max(1, int(radius))
    height, width = mask.shape
    y_min, y_max = max(0, row - radius), min(height, row + radius + 1)
    x_min, x_max = max(0, col - radius), min(width, col + radius + 1)
    if y_min >= y_max or x_min >= x_max:
        return
    yy, xx = np.ogrid[y_min:y_max, x_min:x_max]
    mask[y_min:y_max, x_min:x_max][(yy - row) ** 2 + (xx - col) ** 2 <= radius ** 2] = value


def paint_brush_segment(mask: np.ndarray, start: Pixel, end: Pixel, radius: int, value: bool) -> None:
    """Paint the existing interpolated brush footprint between pointer samples."""
    steps = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
    if steps == 0:
        paint_disk(mask, end, radius, value)
        return
    for index in range(steps + 1):
        fraction = index / steps
        point = (
            int(start[0] + fraction * (end[0] - start[0])),
            int(start[1] + fraction * (end[1] - start[1])),
        )
        paint_disk(mask, point, radius, value)


def paint_line(mask: np.ndarray, start: Pixel, end: Pixel, radius: int, value: bool) -> None:
    """Paint a disk-expanded Bresenham line, preserving the mask line footprint."""
    row, col = start
    end_row, end_col = end
    delta_row, delta_col = abs(end_row - row), abs(end_col - col)
    step_row = 1 if row < end_row else -1
    step_col = 1 if col < end_col else -1
    error = delta_row - delta_col
    while True:
        paint_disk(mask, (row, col), radius, value)
        if (row, col) == end:
            break
        twice_error = 2 * error
        if twice_error > -delta_col:
            error -= delta_col
            row += step_row
        if twice_error < delta_row:
            error += delta_row
            col += step_col


def paint_rectangle(mask: np.ndarray, start: Pixel, end: Pixel, value: bool) -> None:
    """Paint a filled rectangle including both selected corner pixels."""
    row_min, row_max = sorted((start[0], end[0]))
    col_min, col_max = sorted((start[1], end[1]))
    row_end = max(0, min(mask.shape[0], row_max + 1))
    col_end = max(0, min(mask.shape[1], col_max + 1))
    mask[max(0, row_min):row_end, max(0, col_min):col_end] = value


def paint_circle(mask: np.ndarray, center: Pixel, end: Pixel, value: bool) -> None:
    """Paint the rounded integer radius used by the mask circle tool."""
    radius = int(round(np.hypot(end[0] - center[0], end[1] - center[1])))
    paint_disk(mask, center, radius, value)


def paint_polygon(mask: np.ndarray, points: Sequence[Pixel], value: bool) -> None:
    """Rasterize a polygon once, retaining the established pixel-boundary rule."""
    from matplotlib.path import Path

    if len(points) < 3:
        return
    # Path is used only for final pixel inclusion, never as a GUI backend.
    rows, cols = np.indices(mask.shape)
    vertices = np.asarray([(col, row) for row, col in points], dtype=float)
    vertices = np.vstack((vertices, vertices[0]))
    inside = Path(vertices, closed=True).contains_points(
        np.column_stack((cols.ravel(), rows.ravel())), radius=0.5,
    ).reshape(rows.shape)
    mask[inside] = value
