"""Pixel footprints and transactional editing in the Qt mask workflow."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from matplotlib.path import Path
from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from sciview.interfaces.stable_qt.tools.mask_drawing_tools import (
    BrushDrawingTool, MaskDrawingSession, RectangleDrawingTool, WatershedFillTool,
)
from sciview.interfaces.stable_qt.widgets.image_viewer import ImagePointerEvent, ImageViewer
from sciview.masking.drawing import (
    paint_brush_segment, paint_circle, paint_disk, paint_line,
    paint_polygon, paint_rectangle,
)
from sciview.masking.layers import MaskLayer, compose_mask_layers
from test_image_viewer import DummyParentApp


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def viewer(qapp):
    widget = ImageViewer()
    yield widget
    widget.close()


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


def test_clear_layers_undo_restores_order_and_combined_mask(qapp):
    from tabs.mask_tab import MaskApp

    tab = MaskApp(DummyParentApp())
    first = MaskLayer([[True, False], [False, False]], name="First")
    second = MaskLayer([[False, True], [False, False]], name="Second")
    tab.mask_layers.extend([first, second])
    tab._update_layer_list()
    expected_mask = tab.combined_mask.copy()
    tab.show()
    qapp.processEvents()
    try:
        tab._clear_all_layers()
        assert tab.mask_layers == []
        assert tab.combined_mask is None
        viewport = tab.image_viewer._graphics.viewport()
        viewport.setFocus()
        QTest.keyClick(viewport, Qt.Key_Z, Qt.ControlModifier)
        assert tab.mask_layers == [first, second]
        np.testing.assert_array_equal(tab.combined_mask, expected_mask)
    finally:
        tab.close()
        tab.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_mask_layer_composition_replaces_only_visible_target():
    layers = [
        MaskLayer([[False, True], [False, False]]),
        MaskLayer([[False, False], [True, False]]),
        MaskLayer([[True, True], [True, True]], visible=False),
    ]
    preview = np.array([[False, False], [False, True]])
    combined = compose_mask_layers(layers, replacement=(0, preview))
    np.testing.assert_array_equal(combined, [[False, False], [True, True]])


def pointer(x, y, inside_image=True, inside_canvas=True):
    return ImagePointerEvent(x, y, Qt.LeftButton, Qt.NoModifier, inside_image, inside_canvas)


def drawing_session(tool, layer, viewer):
    return MaskDrawingSession(
        is_enabled=lambda: True,
        get_tool=lambda: tool,
        get_active_layer=lambda: layer,
        get_layers=lambda: [layer],
        get_viewer=lambda: viewer,
        get_image_data=lambda: viewer.source_array,
        set_drawing_enabled=lambda enabled: None,
        should_auto_disable=lambda: False,
        get_brush_size=lambda: 1,
        get_draw_value=lambda: True,
        on_edit_finished=lambda *_args: None,
        on_error=lambda error: pytest.fail(str(error)),
    )


def test_mask_drawing_respects_canvas_and_image_boundaries(viewer):
    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    session = drawing_session(RectangleDrawingTool(), layer, viewer)
    session.handle_press(pointer(-10, -10, inside_image=False, inside_canvas=False))
    assert not layer.data.any()
    session.handle_press(pointer(-10, -10, inside_image=False))
    session.handle_motion(pointer(20, 20, inside_image=False))
    session.handle_release(pointer(20, 20, inside_image=False))
    assert layer.data.all()

    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    session = drawing_session(BrushDrawingTool(), layer, viewer)
    session.handle_press(pointer(1, 1))
    session.handle_motion(pointer(20, 1, inside_image=False))
    session.handle_release(pointer(20, 1, inside_image=False))
    assert layer.data[1, -1]

    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    session = drawing_session(WatershedFillTool(), layer, viewer)
    session.handle_press(pointer(-1, -1, inside_image=False))
    assert not layer.data.any()


def test_mask_gestures_commit_atomically_with_undo_redo(qapp):
    from tabs.mask_tab import MaskApp

    published = []
    parent = DummyParentApp()
    parent.publish_shared_mask = lambda mask, **_kwargs: published.append(mask.copy())
    tab = MaskApp(parent)
    tab.image_data = np.arange(16 * 18, dtype=float).reshape(16, 18)
    tab.update_plot()
    tab._update_tool_brush_size(1)
    try:
        for tool_name in ("Brush", "Eraser", "Line", "Rectangle", "Circle", "Polygon", "Smart Fill"):
            initial = np.full((16, 18), tool_name == "Eraser", dtype=bool)
            layer = MaskLayer(initial.copy())
            tab.mask_layers[:] = [layer]
            tab._update_layer_list()
            tab.undo_stack.clear()
            tab.tool_buttons[tool_name].click()
            published.clear()
            session = tab.drawing_session
            session.handle_press(pointer(2, 3))
            for point in [(4, 4), (6, 6), (9, 8)]:
                session.handle_motion(pointer(*point))
            if tool_name == "Polygon":
                session.handle_release(pointer(9, 8))
                session.handle_press(pointer(9, 8))
                session.handle_press(pointer(9, 3))
            np.testing.assert_array_equal(layer.data, initial, err_msg=tool_name)
            np.testing.assert_array_equal(tab.combined_mask, initial, err_msg=tool_name)
            assert published == [], tool_name
            assert tab.undo_stack.count() == 0, tool_name
            if tool_name == "Polygon":
                assert session.finish_polygon()
            else:
                session.handle_release(pointer(9, 8))
            assert len(published) == tab.undo_stack.count() == 1, tool_name
            after = layer.data.copy()
            assert np.any(after != initial), tool_name
            tab.undo_stack.undo()
            np.testing.assert_array_equal(layer.data, initial, err_msg=tool_name)
            tab.undo_stack.redo()
            np.testing.assert_array_equal(layer.data, after, err_msg=tool_name)
    finally:
        tab.close()


def test_mask_brush_keeps_alt_effect_per_segment_and_commits_release_endpoint(viewer):
    layer = MaskLayer(np.zeros((16, 16), dtype=bool))
    session = drawing_session(BrushDrawingTool(), layer, viewer)
    session.handle_press(pointer(2, 3))
    session.handle_motion(pointer(8, 3))
    session.get_draw_value = lambda: False
    session.handle_motion(pointer(8, 7))
    session.handle_release(pointer(12, 7))
    expected = np.zeros_like(layer.data)
    paint_brush_segment(expected, (3, 2), (3, 2), 0, True)
    paint_brush_segment(expected, (3, 2), (3, 8), 0, True)
    paint_brush_segment(expected, (3, 8), (7, 8), 0, False)
    paint_brush_segment(expected, (7, 8), (7, 12), 0, False)
    np.testing.assert_array_equal(layer.data, expected)


def test_release_outside_canvas_commits_last_accepted_point_and_ignores_right_click(viewer):
    layer = MaskLayer(np.zeros((16, 16), dtype=bool))
    session = drawing_session(RectangleDrawingTool(), layer, viewer)
    right_click = ImagePointerEvent(1, 1, Qt.RightButton, Qt.NoModifier, True, True)
    session.handle_press(right_click)
    session.handle_press(pointer(2, 3))
    session.handle_motion(pointer(6, 7))
    session.handle_motion(pointer(99, 99, False, False))
    session.handle_release(pointer(99, 99, False, False))
    expected = np.zeros_like(layer.data)
    expected[3:8, 2:7] = True
    np.testing.assert_array_equal(layer.data, expected)


def test_pending_mask_edit_cannot_mutate_a_different_selected_layer(viewer):
    layer = MaskLayer(np.zeros((16, 16), dtype=bool))
    session = drawing_session(BrushDrawingTool(), layer, viewer)
    session.handle_press(pointer(2, 3))
    session.handle_motion(pointer(6, 7))
    session.get_active_layer = lambda: MaskLayer(np.ones((16, 16), dtype=bool))
    session.handle_release(pointer(8, 8))
    assert not layer.data.any()


@pytest.mark.parametrize("mode", ["OR", "AND"])
def test_mask_commit_publishes_only_the_completed_layer_composition(qapp, mode):
    from tabs.mask_tab import MaskApp

    parent = DummyParentApp()
    published = []
    parent.publish_shared_mask = lambda mask, **_kwargs: published.append(mask.copy())
    tab = MaskApp(parent)
    first = np.zeros((10, 12), dtype=bool)
    first[2:9, 3:10] = True
    layer = MaskLayer(np.zeros_like(first), combine_mode=mode)
    tab.mask_layers.extend([MaskLayer(first), layer, MaskLayer(np.ones_like(first), visible=False)])
    tab._update_layer_list()
    tab.layer_list.setCurrentRow(tab._list_row_for_layer(1))
    tab.tool_buttons["Rectangle"].click()
    published.clear()
    try:
        tab.drawing_session.handle_press(pointer(2, 1))
        tab.drawing_session.handle_motion(pointer(6, 5))
        assert published == []
        tab.drawing_session.handle_release(pointer(6, 5))
        expected_layer = np.zeros_like(first)
        expected_layer[1:6, 2:7] = True
        expected = (first | expected_layer) if mode == "OR" else (first & expected_layer)
        np.testing.assert_array_equal(layer.data, expected_layer)
        np.testing.assert_array_equal(tab.combined_mask, expected)
        assert len(published) == 1
        np.testing.assert_array_equal(published[0], expected)
    finally:
        tab.close()


def test_failed_fill_keeps_original_mask_and_reports_the_error(viewer, monkeypatch):
    import sciview.interfaces.stable_qt.tools.mask_drawing_tools as drawing

    viewer.set_image(np.ones((8, 8)))
    layer = MaskLayer(np.zeros((8, 8), dtype=bool))
    errors = []
    session = drawing_session(WatershedFillTool(), layer, viewer)
    session.on_error = errors.append

    def failed_fill(*_args, **_kwargs):
        raise ValueError("Invalid fill input")

    monkeypatch.setattr(drawing, "watershed_fill_mask", failed_fill)
    session.handle_press(pointer(3, 3))
    session.handle_release(pointer(3, 3))
    assert not layer.data.any()
    assert len(errors) == 1
    assert "Invalid fill input" in str(errors[0])
    assert "mask-drawing-preview" not in viewer._overlays


def test_real_mask_pointer_workflow_commits_or_cancels_safely(qapp):
    from tabs.mask_tab import MaskApp

    tab = MaskApp(DummyParentApp())
    tab.resize(1280, 800)
    tab.show()
    viewer = tab.image_viewer
    viewport = viewer._graphics.viewport()

    def position(x, y):
        return viewer._graphics.mapFromScene(viewer._view_box.mapViewToScene(QPointF(x, y)))

    try:
        for cancel in (None, "escape", "image", "layer", "tool"):
            tab.image_data = np.ones((20, 30))
            tab.update_plot()
            layer = MaskLayer(np.zeros((20, 30), dtype=bool))
            tab.mask_layers[:] = [layer]
            tab._update_layer_list()
            tab.undo_stack.clear()
            tab.tool_buttons["Rectangle"].click()
            qapp.processEvents()
            QTest.mousePress(viewport, Qt.LeftButton, pos=position(3, 4))
            QTest.mouseMove(viewport, position(9, 10))
            assert not layer.data.any(), cancel
            if cancel == "escape":
                QTest.keyClick(viewport, Qt.Key_Escape)
            elif cancel == "image":
                tab.image_data = np.full((20, 30), 2.0)
                tab.update_plot()
            elif cancel == "layer":
                tab._set_layer_visibility(0, False)
            elif cancel == "tool":
                tab.tool_buttons["Brush"].click()
            QTest.mouseRelease(viewport, Qt.LeftButton, pos=position(9, 10))
            assert bool(layer.data.any()) == (cancel is None), cancel
            assert tab.undo_stack.count() == (1 if cancel is None else 0), cancel
    finally:
        tab.close()
        tab.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
