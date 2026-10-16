import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QListWidgetItem,
    QWidget,
)

import pyqtgraph as pg

from sciview.interfaces.stable_qt.widgets.image_viewer import ImageViewer
from sciview.interfaces.stable_qt.tools.mask_drawing_tools import (
    BrushDrawingTool,
    MaskDrawingSession,
    RectangleDrawingTool,
    WatershedFillTool,
)
from sciview.masking.layers import MaskLayer, compose_mask_layers
from tabs.image_browser_tab import ImageBrowserApp, ImageSessionManager


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def viewer(qapp):
    widget = ImageViewer()
    yield widget
    widget.close()


def test_image_browser_keeps_previous_folder_files_in_batch(tmp_path):
    current = tmp_path / "current.tif"
    kept = tmp_path / "kept.tif"
    current.touch()
    kept.touch()
    browser = ImageBrowserApp.__new__(ImageBrowserApp)
    browser._folder_browser_paths = [str(current)]
    browser._added_folder_paths = [str(kept)]

    assert browser.get_current_file_list() == [str(current), str(kept)]


def test_image_session_cache_load_does_not_repeat_session_notification():
    session = ImageSessionManager()
    notifications = []
    session.add_callback(lambda manager: notifications.append(manager.current_index))
    session.add_image_reference("image.tif")

    image = session.get_current_image(
        load_data=True,
        loader_callback=lambda path, metadata: np.zeros((2, 2)),
    )

    assert image["data"].shape == (2, 2)
    assert notifications == [0]


def test_image_session_selection_does_not_republish_file_list():
    browser = ImageBrowserApp.__new__(ImageBrowserApp)
    browser.is_batch_loading = False
    published = []
    displayed = []
    browser._publish_shared_file_list = lambda: published.append(True)
    browser._update_display = lambda: displayed.append(True)

    browser._on_session_changed(None)

    assert published == []
    assert displayed == [True]


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


class DummyImageTab(QWidget):
    def __init__(self):
        super().__init__()
        self.image_data = None
        self.update_count = 0

    def update_plot(self):
        self.update_count += 1


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
