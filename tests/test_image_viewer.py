import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication, QWidget

import pyqtgraph as pg

from sciview.interfaces.stable_qt.widgets.image_viewer import ImageViewer
from sciview.interfaces.stable_qt.tools.mask_drawing_tools import BrushDrawingTool, MaskDrawingSession


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def viewer(qapp):
    widget = ImageViewer()
    yield widget
    widget.close()


def test_numpy_image_uses_row_column_coordinates(viewer):
    image = np.arange(3 * 5, dtype=float).reshape(3, 5)

    viewer.set_image(image)

    assert viewer.source_array is image
    assert viewer.display_array is image
    assert viewer.get_raw_value_at(0.0, 0.0) == image[0, 0]
    assert viewer.get_raw_value_at(4.2, 2.0) == image[2, 4]
    assert viewer.get_raw_value_at(-1.0, 0.0) is None
    assert viewer.get_raw_value_at(0.0, np.nan) is None


def test_same_shape_replacement_preserves_view_range(viewer):
    image = np.arange(3 * 5, dtype=float).reshape(3, 5)
    replacement = image + 100.0
    viewer.set_image(image)
    viewer.set_view_range(((1.0, 3.0), (0.5, 2.5)))
    preserved_range = viewer.get_view_range()

    viewer.set_image(replacement)

    x_range, y_range = viewer.get_view_range()
    assert x_range == pytest.approx(preserved_range[0])
    assert y_range == pytest.approx(preserved_range[1])
    assert viewer.get_raw_value_at(1.0, 1.0) == replacement[1, 1]


def test_different_shape_replacement_resets_view_range(viewer):
    viewer.set_image(np.arange(3 * 5, dtype=float).reshape(3, 5))
    viewer.set_view_range(((1.0, 3.0), (0.5, 2.5)))

    viewer.set_image(np.arange(4 * 6, dtype=float).reshape(4, 6))

    x_range, y_range = viewer.get_view_range()
    assert x_range[0] <= 0.0
    assert x_range[1] >= 6.0
    assert y_range[0] <= 0.0
    assert y_range[1] >= 4.0


def test_viewer_uses_white_background_and_locked_aspect(viewer):
    assert viewer._graphics.backgroundBrush().color().name() == "#ffffff"
    assert viewer._view_box.state["aspectLocked"] == 1.0


def test_viewer_interaction_lock_disables_pan_zoom_controls(viewer):
    viewer.set_interaction_locked(True)

    assert viewer._interaction_locked
    assert not viewer._pan_button.isEnabled()
    assert not viewer._zoom_button.isEnabled()
    assert not viewer._pan_button.isChecked()
    assert not viewer._zoom_button.isChecked()

    viewer.set_interaction_locked(False)

    assert not viewer._interaction_locked
    assert viewer._pan_button.isEnabled()
    assert viewer._zoom_button.isEnabled()


def test_linear_levels_and_colormap_do_not_change_source_or_view(viewer):
    image = np.arange(3 * 5, dtype=float).reshape(3, 5)
    viewer.set_image(image)
    viewer.set_view_range(((1.0, 3.0), (0.5, 2.5)))
    preserved_range = viewer.get_view_range()

    viewer.set_levels(-2.0, 10.0)
    viewer.set_colormap("viridis")

    assert viewer.source_array is image
    assert viewer.display_array is image
    assert viewer.display_levels == (-2.0, 10.0)
    assert viewer.get_view_range()[0] == pytest.approx(preserved_range[0])
    assert viewer.get_view_range()[1] == pytest.approx(preserved_range[1])


def test_log_display_is_display_only_and_handles_non_positive_values(viewer):
    image = np.array([[0.0, -5.0, 1.0], [10.0, np.nan, np.inf], [100.0, 5.0, 2.0]])
    viewer.set_image(image)
    viewer.set_levels(0.0, 100.0)

    viewer.set_scale("log")

    display = viewer.display_array
    assert viewer.source_array is image
    assert display is not image
    assert viewer.display_levels == pytest.approx((0.0, 2.0))
    assert display[0, 0] == pytest.approx(0.0)
    assert display[0, 1] == pytest.approx(0.0)
    assert display[0, 2] == pytest.approx(0.0)
    assert display[1, 0] == pytest.approx(1.0)
    assert display[1, 1] == pytest.approx(0.0)
    assert display[1, 2] == pytest.approx(0.0)
    assert display[2, 0] == pytest.approx(2.0)


def test_clear_image_records_empty_state(viewer):
    viewer.set_image(np.arange(3 * 5, dtype=float).reshape(3, 5))

    viewer.clear_image("No image loaded")

    assert viewer.source_array is None
    assert viewer.display_array is None
    assert viewer.display_levels is None


def test_overlay_lifecycle(viewer):
    viewer.set_image(np.arange(3 * 5, dtype=float).reshape(3, 5))
    point = pg.ScatterPlotItem([1.0], [1.0])

    viewer.set_overlay_item("beam-center", point, group="calibration")
    assert point.isVisible()

    viewer.set_overlay_visible("beam-center", False)
    assert not point.isVisible()

    viewer.clear_overlays(group="calibration")
    with pytest.raises(KeyError):
        viewer.set_overlay_visible("beam-center", True)


class DummyParentApp:
    image_data = None

    def __init__(self):
        self.display_settings = {
            'vmin': -2,
            'vmax': 1000,
            'cmap': 'gray',
            'scale': 'linear'
        }
        self.display_publish_count = 0

    def show_status(self, message):
        self.last_status = message

    def update_all_displays(self):
        pass

    def publish_shared_display_settings(self, settings, source_tab=None):
        self.display_settings.update(settings)
        self.display_publish_count += 1

    def publish_shared_info_text(self, text, source_tab=None):
        self.last_info_text = text

    def publish_shared_calibration(self, calibration, source_tab=None):
        self.last_calibration = calibration

    def get_shared_calibration(self, *args, **kwargs):
        return None

    def get_shared_mask(self, *args, **kwargs):
        return None


@pytest.mark.parametrize(
    "module_name,class_name",
    [
        ("tabs.image_browser_tab", "ImageBrowserApp"),
        ("tabs.calibration_tab", "CalibrationApp"),
        ("tabs.mask_tab", "MaskApp"),
        ("tabs.reduction_tab", "ReductionTab"),
        ("tabs.protocol_preview_tab", "ProtocolPreviewApp"),
    ],
)
def test_migrated_image_tabs_construct_with_image_viewer(qapp, module_name, class_name):
    module = __import__(module_name, fromlist=[class_name])
    tab_class = getattr(module, class_name)

    tab = tab_class(DummyParentApp())
    try:
        assert isinstance(tab.image_viewer, ImageViewer)
    finally:
        tab.close()


def test_viewer_shows_axes_and_histogram_controls(viewer):
    image = np.arange(4 * 6, dtype=float).reshape(4, 6)

    viewer.set_image(image)
    viewer.set_levels(1.0, 20.0)

    assert viewer._plot_item.getAxis("left").isVisible()
    assert viewer._plot_item.getAxis("bottom").isVisible()
    assert viewer._histogram.imageItem() is viewer._image_item
    assert viewer._histogram.getLevels() == pytest.approx((1.0, 20.0))


def test_base_tabs_share_display_settings_from_controls(qapp):
    from tabs.calibration_tab import CalibrationApp

    parent = DummyParentApp()
    first = CalibrationApp(parent)
    second = CalibrationApp(parent)
    try:
        assert first.display_settings is parent.display_settings
        assert second.display_settings is parent.display_settings

        first.update_display_settings(vmin=3.0, vmax=123.0, cmap="viridis")
        second.sync_display_controls()

        assert parent.display_settings["vmin"] == 3.0
        assert parent.display_settings["vmax"] == 123.0
        assert parent.display_settings["cmap"] == "viridis"
        assert second.vmin_input.text() == "3.0"
        assert second.vmax_input.text() == "123.0"
        assert second.cmap_selector.currentText() == "viridis"
    finally:
        first.close()
        second.close()


def test_shared_display_settings_update_existing_viewers_without_full_redraw(qapp):
    from tabs.calibration_tab import CalibrationApp

    parent = DummyParentApp()
    tab = CalibrationApp(parent)
    redraw_count = {"value": 0}
    try:
        tab.update_plot = lambda *args, **kwargs: redraw_count.__setitem__("value", redraw_count["value"] + 1)
        tab.image_viewer.set_image(np.arange(4 * 4, dtype=float).reshape(4, 4))

        tab.apply_shared_display_settings({
            'vmin': 2.0,
            'vmax': 12.0,
            'cmap': 'plasma',
            'scale': 'linear',
        })

        assert redraw_count["value"] == 0
        assert tab.image_viewer.display_levels == (2.0, 12.0)
        assert tab.vmin_input.text() == "2.0"
        assert tab.vmax_input.text() == "12.0"
        assert tab.cmap_selector.currentText() == "plasma"
    finally:
        tab.close()


def test_shared_image_sync_only_renders_current_tab(qapp):
    from main import SciAnaApp

    app = SciAnaApp()
    source = DummyImageTab()
    active = DummyImageTab()
    inactive = DummyImageTab()
    try:
        app.add_tab(source, "Source")
        app.add_tab(active, "Active")
        app.add_tab(inactive, "Inactive")
        app.tab_widget.setCurrentWidget(active)

        image = np.ones((3, 3), dtype=float)
        app.publish_shared_image(image, source_tab=source)

        assert active.image_data is image
        assert inactive.image_data is image
        assert active.update_count == 1
        assert inactive.update_count == 0
    finally:
        app.close()


def test_switching_to_synced_tab_renders_shared_image(qapp):
    from main import SciAnaApp

    app = SciAnaApp()
    source = DummyImageTab()
    active = DummyImageTab()
    inactive = DummyImageTab()
    try:
        app.add_tab(source, "Source")
        app.add_tab(active, "Active")
        app.add_tab(inactive, "Inactive")
        app.tab_widget.setCurrentWidget(active)

        image = np.ones((3, 3), dtype=float)
        app.publish_shared_image(image, source_tab=source)
        assert inactive.update_count == 0

        app.tab_widget.setCurrentWidget(inactive)

        assert inactive.image_data is image
        assert inactive.update_count == 1
    finally:
        app.close()


def test_switching_to_real_image_tab_loads_blank_viewer(qapp):
    from main import SciAnaApp
    from tabs.calibration_tab import CalibrationApp

    app = SciAnaApp()
    source = DummyImageTab()
    calibration_tab = CalibrationApp(app)
    try:
        app.add_tab(source, "Source")
        app.add_tab(calibration_tab, "Calibration")
        app.tab_widget.setCurrentWidget(source)

        image = np.arange(5 * 7, dtype=float).reshape(5, 7)
        app.publish_shared_image(image, source_tab=source)

        assert calibration_tab.image_data is image
        assert calibration_tab.image_viewer.source_array is None

        app.tab_widget.setCurrentWidget(calibration_tab)

        assert calibration_tab.image_viewer.source_array is image
        assert calibration_tab.image_viewer.display_array is image
    finally:
        app.close()


class DummyImageTab(QWidget):
    def __init__(self):
        super().__init__()
        self.image_data = None
        self.update_count = 0

    def update_plot(self):
        self.update_count += 1


def test_mask_tool_buttons_toggle_canvas_lock(qapp):
    from tabs.mask_tab import MaskApp

    tab = MaskApp(DummyParentApp())
    tab.image_data = np.zeros((6, 6), dtype=float)
    try:
        assert not hasattr(tab, 'drawing_mode_check')
        assert not tab.drawing_mode
        assert not tab.image_viewer._interaction_locked

        tab.tool_buttons["Brush"].click()

        assert tab.drawing_mode
        assert tab.image_viewer._interaction_locked
        assert tab.tool_buttons["Brush"].isChecked()

        tab.tool_buttons["Brush"].click()

        assert not tab.drawing_mode
        assert not tab.image_viewer._interaction_locked
        assert not tab.tool_buttons["Brush"].isChecked()
    finally:
        tab.close()


class DummyMaskLayer:
    def __init__(self, data, visible=True):
        self.data = np.asarray(data, dtype=bool)
        self.visible = visible


def test_mask_drawing_session_composes_preview_for_visible_layers():
    layers = [
        DummyMaskLayer([[False, True], [False, False]]),
        DummyMaskLayer([[False, False], [True, False]]),
        DummyMaskLayer([[True, True], [True, True]], visible=False),
    ]
    session = MaskDrawingSession(
        is_enabled=lambda: True,
        get_tool=lambda: None,
        get_image_data=lambda: None,
        get_active_layer=lambda create: None,
        get_active_layer_index=lambda create: None,
        get_layers=lambda: layers,
        get_combine_method=lambda: "OR",
        set_combined_mask=lambda mask: None,
        update_combined_mask=lambda: None,
        update_plot=lambda: None,
        set_drawing_enabled=lambda enabled: None,
        should_auto_disable=lambda: False,
        get_brush_size=lambda: 1,
        get_draw_value=lambda: True,
    )

    preview = np.array([[False, False], [False, True]])
    combined = session._compose_preview(layers, 0, preview)

    expected = np.array([[False, False], [True, True]])
    np.testing.assert_array_equal(combined, expected)


class DummyPointerEvent:
    def __init__(self, x, y, inside_image=True):
        self.x = x
        self.y = y
        self.inside_image = inside_image


def test_brush_session_uses_preview_refresh_until_release():
    layer = DummyMaskLayer(np.zeros((8, 8), dtype=bool))
    tool = BrushDrawingTool()
    calls = {"preview": 0, "final": 0}
    preview_masks = []

    session = MaskDrawingSession(
        is_enabled=lambda: True,
        get_tool=lambda: tool,
        get_image_data=lambda: np.zeros((8, 8), dtype=float),
        get_active_layer=lambda create: layer,
        get_active_layer_index=lambda create: 0,
        get_layers=lambda: [layer],
        get_combine_method=lambda: "OR",
        set_combined_mask=lambda mask: preview_masks.append(mask.copy()),
        update_combined_mask=lambda: calls.__setitem__("final", calls["final"] + 1),
        update_plot=lambda: calls.__setitem__("preview", calls["preview"] + 1),
        set_drawing_enabled=lambda enabled: None,
        should_auto_disable=lambda: False,
        get_brush_size=lambda: 1,
        get_draw_value=lambda: True,
    )

    session.handle_press(DummyPointerEvent(1, 1))
    session.handle_motion(DummyPointerEvent(2, 1))
    session.handle_motion(DummyPointerEvent(3, 1))

    assert calls["preview"] == 3
    assert calls["final"] == 0
    assert layer.data[1, 1]
    assert layer.data[1, 3]
    assert preview_masks[-1][1, 3]

    session.handle_release(DummyPointerEvent(3, 1))

    assert calls["final"] == 1