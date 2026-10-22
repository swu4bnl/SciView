"""Pixel-fill contracts shared by scripts and the Qt mask editor."""

import numpy as np
import pytest
from matplotlib.path import Path

from sciview.masking.drawing import (
    paint_brush_segment, paint_circle, paint_disk, paint_line,
    paint_polygon, paint_rectangle,
)


@pytest.mark.parametrize("value", [True, False])
def test_disk_circle_and_rectangle_preserve_integer_pixel_footprints(value):
    rows, cols = np.indices((9, 12))
    initial = np.full(rows.shape, not value, dtype=bool)
    for painter, arguments, footprint in [
        (paint_disk, ((3, 4), 0), (rows == 3) & (cols == 4)),
        (paint_circle, ((3, 4), (3, 4)), (rows == 3) & (cols == 4)),
        (paint_brush_segment, ((3, 4), (3, 4), 0), (rows == 3) & (cols == 4)),
        (paint_line, ((3, 4), (3, 4), 0), (rows == 3) & (cols == 4)),
        (paint_disk, ((0, 1), 3), rows ** 2 + (cols - 1) ** 2 <= 9),
        (paint_circle, ((3, 4), (5, 6)), (rows - 3) ** 2 + (cols - 4) ** 2 <= 9),
        (paint_rectangle, ((5, 6), (2, 3)), (rows >= 2) & (rows <= 5) & (cols >= 3) & (cols <= 6)),
    ]:
        result = initial.copy()
        painter(result, *arguments, value)
        expected = initial.copy()
        expected[footprint] = value
        np.testing.assert_array_equal(result, expected)


@pytest.mark.parametrize("end", [(7, 9), (7, 2), (1, 9), (1, 2), (4, 2)])
def test_brush_interpolation_keeps_connected_clipped_disks(end):
    result = np.zeros((9, 12), dtype=bool)
    start = (4, 2)
    paint_brush_segment(result, start, end, 2, True)
    steps = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
    rows, cols = np.indices(result.shape)
    expected = np.zeros_like(result)
    for index in range(steps + 1):
        fraction = index / max(1, steps)
        row = int(start[0] + fraction * (end[0] - start[0]))
        col = int(start[1] + fraction * (end[1] - start[1]))
        expected |= (rows - row) ** 2 + (cols - col) ** 2 <= 4
    np.testing.assert_array_equal(result, expected)


def test_line_preserves_bresenham_centers_in_both_directions():
    centers = [(1, 1), (2, 2), (2, 3), (3, 4), (3, 5), (4, 6)]
    rows, cols = np.indices((6, 8))
    expected = np.zeros(rows.shape, dtype=bool)
    for row, col in centers:
        expected |= (rows - row) ** 2 + (cols - col) ** 2 <= 1
    for start, end in [(centers[0], centers[-1]), (centers[-1], centers[0])]:
        result = np.zeros_like(expected)
        paint_line(result, start, end, 1, True)
        np.testing.assert_array_equal(result, expected)


@pytest.mark.parametrize("points", [
    [(0, 0), (0, 11), (8, 11), (8, 0)],
    [(2, 3), (6, 9), (6, 4)],
    [(2, 3), (6, 4), (6, 9)],
    [(2, 3), (6, 9), (2, 9), (6, 3)],
])
def test_polygon_preserves_established_pixel_boundary_rule(points):
    result = np.zeros((9, 12), dtype=bool)
    paint_polygon(result, points, True)
    rows, cols = np.indices(result.shape)
    vertices = [(col, row) for row, col in [*points, points[0]]]
    expected = Path(vertices, closed=True).contains_points(
        np.column_stack((cols.ravel(), rows.ravel())), radius=0.5,
    ).reshape(result.shape)
    np.testing.assert_array_equal(result, expected)


def test_painting_entirely_outside_image_leaves_mask_unchanged():
    result = np.zeros((9, 12), dtype=bool)
    paint_disk(result, (-10, 0), 1, True)
    paint_disk(result, (0, 15), 1, True)
    paint_rectangle(result, (-10, -9), (-5, -4), True)
    assert not result.any()
