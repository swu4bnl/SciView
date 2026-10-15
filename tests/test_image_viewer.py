import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QLabel, QListWidgetItem, QWidget

import pyqtgraph as pg

from sciview.interfaces.stable_qt.widgets.image_viewer import ImageViewer
from sciview.interfaces.stable_qt.tools.mask_drawing_tools import (
    BrushDrawingTool,
    MaskDrawingSession,
    RectangleDrawingTool,
    WatershedFillTool,
)
from sciview.masking.layers import MaskLayer, compose_mask_layers


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
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


def test_viewer_toolbar_shows_action_labels(viewer):
    labels = {
        key: cell.findChild(QLabel).text()
        for key, cell in viewer._toolbar_cells.items()
    }

    assert labels == {
        "pan": "Pan",
        "zoom": "Zoom",
        "beam_center": "Beam Center",
        "mask": "Mask",
        "home": "Home",
        "auto": "Auto",
        "copy": "Copy",
        "save": "Save",
    }


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


def test_color_image_preserves_rgb_channels(viewer):
    image = np.zeros((3, 4, 3), dtype=np.ubyte)
    image[..., 0] = 255
    image[..., 1] = np.arange(4, dtype=np.ubyte)

    viewer.set_color_image(image)

    assert viewer.source_array is image
    assert viewer.display_array is image
    assert viewer.source_array.shape == (3, 4, 3)
    assert viewer.get_raw_value_at(1.0, 0.0).tolist() == [255, 1, 0]


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

    def publish_shared_image(self, image_data, image_path=None, source_tab=None):
        self.image_data = image_data
        self.image_path = image_path
        self.image_source_tab = source_tab

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


def test_folder_row_reopens_after_session_navigation(qapp, tmp_path):
    from tabs.image_browser_tab import ImageBrowserApp

    tab = ImageBrowserApp(DummyParentApp())
    try:
        tab.session_manager.callbacks.clear()
        notifications = []
        tab.session_manager.add_callback(lambda manager: notifications.append(manager.current_index))

        first_path = str(tmp_path / "first.tif")
        second_path = str(tmp_path / "second.tif")
        first_item = QListWidgetItem("first.tif")
        first_item.setData(Qt.UserRole, first_path)
        second_item = QListWidgetItem("second.tif")
        second_item.setData(Qt.UserRole, second_path)
        tab.folder_files_list.addItem(first_item)
        tab.folder_files_list.addItem(second_item)

        tab.folder_files_list.setCurrentItem(first_item)
        tab.session_manager.add_image_reference(second_path)
        tab.folder_files_list.setCurrentItem(second_item)
        notification_count = len(notifications)

        tab.folder_files_list.itemClicked.emit(second_item)
        assert len(notifications) == notification_count

        tab.folder_files_list.itemClicked.emit(first_item)
        assert tab.session_manager.current_index == 0
        assert notifications[-1] == 0
    finally:
        tab.close()


def test_shared_image_panel_uses_canvas_filename_without_redundant_header(qapp, tmp_path):
    from tabs.calibration_tab import CalibrationApp

    parent = DummyParentApp()
    parent.image_path = str(tmp_path / "detector-frame.tif")
    parent.image_data = np.ones((4, 6), dtype=float)
    tab = CalibrationApp(parent)
    try:
        tab.update_plot(parent.image_data)

        assert not tab.filename_label.isVisible()
        assert tab.image_viewer._plot_item.titleLabel.text == "detector-frame.tif"
    finally:
        tab.close()


@pytest.mark.experimental
def test_tiled_local_image_title_does_not_reuse_shared_filename(qapp):
    from tabs.tiled_browser_tab import TiledBrowserTab

    parent = DummyParentApp()
    parent.image_path = "old-shared-image.tif"
    tab = TiledBrowserTab(parent)
    try:
        scan = SimpleNamespace(scan_id=42, sample_name="sample", sample_savename="")
        image_ref = SimpleNamespace(source_uri="tiled://scan/42/detector")
        tab._apply_loaded_image((scan, "detector", np.ones((4, 6)), image_ref))

        assert tab.image_viewer._plot_item.titleLabel.text == "Scan 42 - detector"
    finally:
        tab.close()


def test_clear_session_icon_has_accessible_name(qapp):
    from main import SciAnaApp

    app = SciAnaApp()
    try:
        assert app.clear_session_button.accessibleName() == "Clear saved session"
    finally:
        app.close()


@pytest.mark.parametrize(
    "module_name,class_name",
    [
        ("tabs.reduction_tab", "ReductionTab"),
        ("tabs.transform_tab", "TransformTab"),
    ],
)
def test_processing_result_reset_disables_export(qapp, module_name, class_name):
    module = __import__(module_name, fromlist=[class_name])
    tab_class = getattr(module, class_name)
    tab = tab_class(DummyParentApp())
    try:
        tab._set_current_result(object())
        assert tab.export_button.isEnabled()

        tab.update_plot(None)

        assert tab._current_result is None
        assert not tab.export_button.isEnabled()
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


def test_switching_to_shared_state_tab_uses_activation_hook(qapp):
    from main import SciAnaApp

    app = SciAnaApp()
    source = DummyImageTab()
    active = DummySharedStateTab()
    try:
        app.add_tab(source, "Source")
        app.add_tab(active, "Active")
        app.tab_widget.setCurrentWidget(source)

        image = np.ones((3, 3), dtype=float)
        app.publish_shared_image(image, source_tab=source)

        app.tab_widget.setCurrentWidget(active)
        assert active.activation_count == 1

        app.calibration = object()
        app.tab_widget.setCurrentWidget(source)
        app.tab_widget.setCurrentWidget(active)

        assert active.activation_count == 2
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


def test_switching_to_nonblank_tab_rerenders_when_shared_image_changes(qapp):
    from main import SciAnaApp
    from tabs.calibration_tab import CalibrationApp

    app = SciAnaApp()
    source = DummyImageTab()
    calibration_tab = CalibrationApp(app)
    try:
        app.add_tab(source, "Source")
        app.add_tab(calibration_tab, "Calibration")
        app.tab_widget.setCurrentWidget(source)

        image_a = np.ones((5, 7), dtype=float)
        app.publish_shared_image(image_a, source_tab=source)
        app.tab_widget.setCurrentWidget(calibration_tab)
        assert calibration_tab.image_viewer.source_array is image_a

        app.tab_widget.setCurrentWidget(source)
        image_b = np.full((5, 7), 2.0, dtype=float)
        app.publish_shared_image(image_b, source_tab=source)
        assert calibration_tab.image_viewer.source_array is image_a

        app.tab_widget.setCurrentWidget(calibration_tab)

        assert calibration_tab.image_data is image_b
        assert calibration_tab.image_viewer.source_array is image_b
    finally:
        app.close()


def test_display_settings_publish_does_not_update_inactive_tabs(qapp):
    from main import SciAnaApp

    app = SciAnaApp()
    active = DummyDisplayTab()
    inactive = DummyDisplayTab()
    try:
        app.add_tab(active, "Active")
        app.add_tab(inactive, "Inactive")
        app.tab_widget.setCurrentWidget(active)
        active.apply_count = 0
        inactive.apply_count = 0

        app.publish_shared_display_settings({
            'vmin': 4.0,
            'vmax': 44.0,
            'cmap': 'viridis',
            'scale': 'linear',
        }, source_tab=active)

        assert app.display_settings['vmin'] == 4.0
        assert active.apply_count == 0
        assert inactive.apply_count == 0
    finally:
        app.close()


def test_leaving_auto_publish_tab_publishes_current_image(qapp):
    from main import SciAnaApp

    app = SciAnaApp()
    image = np.arange(3 * 3, dtype=float).reshape(3, 3)
    browser = DummyAutoPublishTab(app, image)
    target = DummyImageTab()
    try:
        app.add_tab(browser, "Browser")
        app.add_tab(target, "Target")
        app.tab_widget.setCurrentWidget(browser)

        assert app.image_data is None

        app.tab_widget.setCurrentWidget(target)

        assert browser.publish_count == 1
        assert app.image_data is image
        assert target.image_data is image
        assert target.update_count == 1
    finally:
        app.close()


@pytest.mark.experimental
def test_browser_tabs_do_not_expose_manual_sync_buttons(qapp):
    from tabs.image_browser_tab import ImageBrowserApp
    from tabs.tiled_browser_tab import TiledBrowserTab

    parent = DummyParentApp()
    image_browser = ImageBrowserApp(parent)
    tiled_browser = TiledBrowserTab(parent)
    try:
        assert not hasattr(image_browser, "sync_button")
        assert not hasattr(tiled_browser, "sync_button")
    finally:
        image_browser.close()
        tiled_browser.close()


@pytest.mark.experimental
def test_tiled_browser_auto_publish_uses_shared_image_api(qapp):
    from tabs.tiled_browser_tab import TiledBrowserTab

    parent = DummyParentApp()
    tab = TiledBrowserTab.__new__(TiledBrowserTab)
    image = np.arange(4, dtype=float).reshape(2, 2)
    converted_image = object()
    tab.parent_app = parent
    tab.current_frame_array = image
    tab.current_scan = SimpleNamespace(scan_id=42)
    tab.current_image_source = "tiled://scan/42"
    tab.create_data2d_object = lambda image_array, file_path: converted_image

    assert tab.auto_publish_current_image()
    assert parent.image_data is converted_image
    assert parent.image_path == "tiled://scan/42"
    assert parent.image_source_tab is tab


class DummyImageTab(QWidget):
    def __init__(self):
        super().__init__()
        self.image_data = None
        self.update_count = 0

    def update_plot(self):
        self.update_count += 1


class DummySharedStateTab(DummyImageTab):
    def __init__(self):
        super().__init__()
        self.activation_count = 0
        self.image_viewer = None

    def on_shared_state_activated(self):
        self.activation_count += 1


class DummyDisplayTab(QWidget):
    def __init__(self):
        super().__init__()
        self.apply_count = 0

    def apply_shared_display_settings(self, settings):
        self.apply_count += 1


class DummyAutoPublishTab(QWidget):
    def __init__(self, app, image):
        super().__init__()
        self.app = app
        self.image = image
        self.publish_count = 0

    def auto_publish_current_image(self):
        self.publish_count += 1
        self.app.publish_shared_image(self.image, source_tab=self)
        return True


def test_mask_tool_buttons_toggle_canvas_lock(qapp):
    from tabs.mask_tab import MaskApp

    tab = MaskApp(DummyParentApp())
    tab.image_data = np.zeros((6, 6), dtype=float)
    tab.mask_layers.append(MaskLayer(np.zeros((6, 6), dtype=bool), name="Test layer"))
    tab._update_layer_list()
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


def test_clear_layers_undo_restores_order_combined_mask_and_export(qapp):
    from tabs.mask_tab import MaskApp

    tab = MaskApp(DummyParentApp())
    first = MaskLayer([[True, False], [False, False]], name="First")
    second = MaskLayer([[False, True], [False, False]], name="Second")
    tab.mask_layers.extend([first, second])
    tab._update_layer_list()
    expected_mask = tab.combined_mask.copy()
    try:
        assert tab.export_combined_button.isEnabled()

        tab._clear_all_layers()

        assert tab.mask_layers == []
        assert tab.combined_mask is None
        assert not tab.export_combined_button.isEnabled()

        tab.undo_stack.undo()

        assert tab.mask_layers == [first, second]
        np.testing.assert_array_equal(tab.combined_mask, expected_mask)
        assert tab.export_combined_button.isEnabled()
    finally:
        tab.close()


def test_mask_drawing_session_composes_preview_for_visible_layers():
    layers = [
        MaskLayer([[False, True], [False, False]]),
        MaskLayer([[False, False], [True, False]]),
        MaskLayer([[True, True], [True, True]], visible=False),
    ]

    preview = np.array([[False, False], [False, True]])
    combined = compose_mask_layers(layers, replacement=(0, preview))

    expected = np.array([[False, False], [True, True]])
    np.testing.assert_array_equal(combined, expected)


class DummyPointerEvent:
    def __init__(self, x, y, inside_image=True, inside_canvas=True):
        self.x = x
        self.y = y
        self.inside_image = inside_image
        self.inside_canvas = inside_canvas


def _drawing_session(tool, layer):
    return MaskDrawingSession(
        is_enabled=lambda: True,
        get_tool=lambda: tool,
        get_active_layer=lambda: layer,
        get_active_layer_index=lambda: 0,
        get_layers=lambda: [layer],
        set_combined_mask=lambda mask: None,
        update_combined_mask=lambda: None,
        update_plot=lambda: None,
        set_drawing_enabled=lambda enabled: None,
        should_auto_disable=lambda: False,
        get_brush_size=lambda: 1,
        get_draw_value=lambda: True,
        on_edit_finished=lambda *_args: None,
    )


def test_rectangle_clamps_plot_points_to_image_corners():
    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    tool = RectangleDrawingTool()
    session = _drawing_session(tool, layer)

    session.handle_press(DummyPointerEvent(-10, -10, inside_image=False))
    session.handle_motion(DummyPointerEvent(20, 20, inside_image=False))
    session.handle_release(DummyPointerEvent(20, 20, inside_image=False))

    assert layer.data.all()


def test_drawing_ignores_press_outside_plot_canvas():
    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    tool = RectangleDrawingTool()
    session = _drawing_session(tool, layer)

    session.handle_press(DummyPointerEvent(-10, -10, inside_image=False, inside_canvas=False))

    assert not tool.is_active
    assert not layer.data.any()


def test_brush_clamps_active_stroke_to_image_edge():
    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    tool = BrushDrawingTool()
    session = _drawing_session(tool, layer)

    session.handle_press(DummyPointerEvent(1, 1))
    session.handle_motion(DummyPointerEvent(20, 1, inside_image=False))
    session.handle_release(DummyPointerEvent(20, 1, inside_image=False))

    assert layer.data[1, -1]


def test_smart_fill_rejects_seed_outside_image():
    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    tool = WatershedFillTool()
    session = _drawing_session(tool, layer)

    session.handle_press(DummyPointerEvent(-1, -1, inside_image=False))

    assert not tool.is_active
    assert not layer.data.any()


def test_brush_session_uses_preview_refresh_until_release():
    layer = MaskLayer(np.zeros((8, 8), dtype=bool))
    tool = BrushDrawingTool()
    calls = {"preview": 0, "final": 0, "edit": 0}
    preview_masks = []

    session = MaskDrawingSession(
        is_enabled=lambda: True,
        get_tool=lambda: tool,
        get_active_layer=lambda: layer,
        get_active_layer_index=lambda: 0,
        get_layers=lambda: [layer],
        set_combined_mask=lambda mask: preview_masks.append(mask.copy()),
        update_combined_mask=lambda: calls.__setitem__("final", calls["final"] + 1),
        update_plot=lambda: calls.__setitem__("preview", calls["preview"] + 1),
        set_drawing_enabled=lambda enabled: None,
        should_auto_disable=lambda: False,
        get_brush_size=lambda: 1,
        get_draw_value=lambda: True,
        on_edit_finished=lambda *_args: calls.__setitem__("edit", calls["edit"] + 1),
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
    assert calls["edit"] == 1


@pytest.mark.experimental
def test_tiled_device_login_reports_code_and_configures_auth(monkeypatch):
    from sciview.sources import tiled_client

    class Response:
        status_code = 200
        text = ""

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    verification = {
        "verification_uri": "https://login.example/device",
        "user_code": "ABCD-EFGH",
        "device_code": "device-token",
        "expires_in": 60,
        "interval": 0,
    }
    responses = iter([
        Response(verification),
        Response({"error": "slow_down"}),
        Response({"access_token": "token"}),
    ])
    responses_list = list(responses)
    responses_list[1].status_code = 400
    responses = iter(responses_list)
    http_client = SimpleNamespace(post=lambda *args, **kwargs: next(responses))
    provider = SimpleNamespace(
        mode="external",
        links={
            "auth_endpoint": "https://login.example/code",
            "client_id": "sciview",
            "token_endpoint": "https://login.example/token",
        },
        extra_scopes=[],
    )
    configured = []
    context = SimpleNamespace(
        server_info=SimpleNamespace(authentication=SimpleNamespace(providers=[provider])),
        http_client=http_client,
        configure_auth=lambda tokens, remember_me: configured.append((tokens, remember_me)),
    )
    authorizations = []
    sleeps = []
    monkeypatch.setattr(tiled_client.time, "sleep", sleeps.append)

    tiled_client.TiledClientManager._device_login(
        context,
        authorizations.append,
    )

    assert authorizations[0].user_code == "ABCD-EFGH"
    assert authorizations[0].verification_uri == "https://login.example/device"
    assert configured == [({"access_token": "token"}, True)]
    assert sleeps == [0.0, 5.0]


@pytest.mark.experimental
def test_tiled_client_honors_interactive_fallback(monkeypatch):
    from sciview.sources import tiled_client

    authenticated = []

    class Context:
        authenticated = False

        @classmethod
        def from_any_uri(cls, uri, timeout=None):
            return cls(), []

        def use_cached_tokens(self):
            return False

        def authenticate(self, remember_me):
            authenticated.append(remember_me)
            self.authenticated = True

    monkeypatch.setitem(
        tiled_client.TILED_PROFILES,
        "test-login",
        {"uri": "https://example.invalid", "requires_login": True},
    )
    monkeypatch.setattr(tiled_client, "Context", Context)
    monkeypatch.setattr(
        tiled_client,
        "from_context",
        lambda context, node_path_parts: SimpleNamespace(metadata={}, context=context),
    )

    manager = tiled_client.TiledClientManager()
    client = manager.get_or_create_client("test-login", interactive_fallback=True)
    assert client is not None
    assert authenticated == [True]

    manager = tiled_client.TiledClientManager()
    assert manager.get_or_create_client("test-login", interactive_fallback=False) is None


@pytest.mark.experimental
def test_tiled_live_monitor_uses_bluesky_stream_manager(monkeypatch):
    from sciview.sources import tiled_stream
    from sciview.sources.tiled_source import TiledScanSummary

    callbacks = []

    class Subscription:
        disconnected = False

        def disconnect(self):
            self.disconnected = True

    subscription = Subscription()
    catalog = {"run-uid": object()}

    def subscribe(container, callback, **options):
        assert container is catalog
        assert options == {"streams": {"primary": None}, "start": None}
        callbacks.append(callback)
        return subscription

    monkeypatch.setattr(tiled_stream, "subscribe_to_streams", subscribe)
    monkeypatch.setattr(
        tiled_stream,
        "_summary_from_run",
        lambda run, profile_name: TiledScanSummary(uid="run-uid", scan_id=42),
    )
    events = []
    monitor = tiled_stream.TiledLiveMonitor("test", catalog=catalog)

    monitor.start(events.append)
    callbacks[0](SimpleNamespace(run_uid="run-uid", stream_name="primary"))
    callbacks[0](SimpleNamespace(run_uid="run-uid", stream_name="primary"))
    monitor.stop()

    assert [event.event_type for event in events] == [
        "started",
        "child_created",
        "new_data",
        "stopped",
    ]
    assert events[1].scan.scan_id == 42
    assert subscription.disconnected


@pytest.mark.experimental
def test_tiled_authorization_dialog_copies_code_and_opens_browser(qapp, monkeypatch):
    from sciview.sources.tiled_client import TiledDeviceAuthorization
    from tabs.tiled_browser_tab import _TiledAuthorizationDialog

    authorization = TiledDeviceAuthorization(
        "https://login.example/device",
        "ABCD-EFGH",
        600,
    )
    opened = []
    monkeypatch.setattr(
        "tabs.tiled_browser_tab.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )
    dialog = _TiledAuthorizationDialog(authorization)
    try:
        dialog._copy_code()
        dialog._open_browser()

        assert qapp.clipboard().text() == "ABCD-EFGH"
        assert opened == ["https://login.example/device"]
        assert dialog.code_input.isReadOnly()
    finally:
        dialog.close()