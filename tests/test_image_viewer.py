import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from matplotlib.figure import Figure
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication, QPushButton, QSizePolicy, QToolButton, QWidget

import pyqtgraph as pg

from sciview.interfaces.theme.app_style import AppStyle
from sciview.interfaces.stable_qt.widgets.image_viewer import ImageViewer
from sciview.interfaces.stable_qt.tools.mask_drawing_tools import (
    BrushDrawingTool,
    MaskDrawingSession,
    PolygonDrawingTool,
    compose_mask_layers,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def viewer(qapp):
    widget = ImageViewer()
    yield widget
    widget.close()


def test_matplotlib_figure_theme_styles_all_text(monkeypatch):
    text_color = QColor("#f1f3f5")
    monkeypatch.setattr(
        AppStyle,
        "theme_colors",
        classmethod(
            lambda cls: {
                "text": text_color,
                "base": QColor("#202124"),
                "window": QColor("#17181a"),
                "grid": QColor("#5f6368"),
            }
        ),
    )

    figure = Figure()
    axis = figure.subplots()
    axis.plot([0, 1], [0, 1], label="Profile")
    axis.set_xlabel("Q")
    axis.set_ylabel("Intensity")
    axis.set_title("Reduction")
    legend = axis.legend()
    colorbar = figure.colorbar(axis.imshow([[0, 1], [1, 0]]), ax=axis)

    AppStyle.apply_matplotlib_figure_theme(figure)

    expected = text_color.name()
    assert axis.xaxis.label.get_color() == expected
    assert axis.yaxis.label.get_color() == expected
    assert axis.title.get_color() == expected
    assert all(label.get_color() == expected for label in axis.get_xticklabels())
    assert all(label.get_color() == expected for label in legend.get_texts())
    assert all(label.get_color() == expected for label in colorbar.ax.get_yticklabels())


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
    assert viewer._pan_button.isEnabled()
    assert viewer._zoom_button.isEnabled()
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


def test_mask_theme_refresh_updates_custom_visuals_without_losing_state(qapp, monkeypatch):
    from tabs.mask_tab import MaskApp, MaskLayer

    colors = {
        "window": QColor("#f5f5f5"),
        "base": QColor("#ffffff"),
        "text": QColor("#202020"),
        "muted": QColor("#707070"),
        "grid": QColor("#b0b0b0"),
        "accent": QColor("#0067c0"),
        "border": QColor("#909090"),
        "control_bg": QColor("#ffffff"),
        "control_hover": QColor("#e8e8e8"),
        "checked_fg": QColor("#ffffff"),
        "icon": QColor("#202020"),
    }
    monkeypatch.setattr(AppStyle, "theme_colors", classmethod(lambda cls, app=None: colors))

    tab = MaskApp(DummyParentApp())
    try:
        layer_panel = tab.layer_list.parentWidget()
        sidebar_layout = layer_panel.parentWidget().layout()
        assert layer_panel.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
        assert tab.layer_list.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
        assert sidebar_layout.stretch(sidebar_layout.indexOf(layer_panel)) == 1

        image = np.arange(16, dtype=float).reshape(4, 4)
        tab.image_data = image
        tab.mask_layers.append(MaskLayer(image > 8, name="Threshold"))
        tab._update_layer_list()
        tab.threshold_low_spin.setValue(3.0)
        tab.threshold_high_spin.setValue(12.0)
        tab.refresh_theme()

        light_item = tab.layer_list.item(tab._list_row_for_layer(0))
        light_row = tab.layer_list.itemWidget(light_item)
        light_icon = light_row.findChild(QToolButton).icon().pixmap(20, 20).toImage()

        colors.update({
            "window": QColor("#202124"),
            "base": QColor("#17181a"),
            "text": QColor("#f1f3f5"),
            "muted": QColor("#b0b4b8"),
            "grid": QColor("#5f6368"),
            "accent": QColor("#63b3ff"),
            "border": QColor("#666a70"),
            "control_bg": QColor("#2b2d30"),
            "control_hover": QColor("#3a3d41"),
            "icon": QColor("#f1f3f5"),
        })
        tab.refresh_theme()

        dark_item = tab.layer_list.item(tab._list_row_for_layer(0))
        dark_row = tab.layer_list.itemWidget(dark_item)
        dark_icon = dark_row.findChild(QToolButton).icon().pixmap(20, 20).toImage()
        assert light_icon != dark_icon
        assert colors["accent"].name() in dark_row.styleSheet()
        assert tab.threshold_plot.backgroundBrush().color() == colors["base"]
        assert tab.threshold_low_spin.value() == 3.0
        assert tab.threshold_high_spin.value() == 12.0
        assert tab._get_active_layer_index() == 0
        assert colors["control_bg"].name() in tab.tool_buttons["Brush"].property("baseStyleSheet")

        selected_color = "#d12f7a"
        tab._set_overlay_color(selected_color)
        AppStyle.refresh_runtime_theme(qapp)
        assert tab.overlay_color == selected_color
        swatch = tab.layer_color_button.icon().pixmap(tab.layer_color_button.iconSize()).toImage()
        assert swatch.pixelColor(swatch.width() // 2, swatch.height() // 2) == QColor(selected_color)
        assert selected_color not in tab.layer_color_button.styleSheet()
    finally:
        tab.close()


def test_color_swatch_does_not_modify_unrelated_styles(qapp):
    sibling = QPushButton("Unrelated")
    sibling.setStyleSheet("padding: 3px;")
    swatch = QPushButton()
    swatch.setIcon(AppStyle.color_swatch_icon("#112233"))
    app_stylesheet = qapp.styleSheet()
    sibling_stylesheet = sibling.styleSheet()
    try:
        swatch.setIcon(AppStyle.color_swatch_icon("#abcdef"))

        assert qapp.styleSheet() == app_stylesheet
        assert sibling.styleSheet() == sibling_stylesheet
        assert "#abcdef" not in swatch.styleSheet()
    finally:
        swatch.close()
        sibling.close()


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
    try:
        assert not hasattr(tab, 'drawing_mode_check')
        assert not tab.drawing_mode
        assert not tab.image_viewer._interaction_locked
        assert not tab.image_viewer._pan_button.isHidden()
        assert not tab.image_viewer._zoom_button.isHidden()
        assert not tab.image_viewer._home_button.isHidden()
        assert not tab.image_viewer.toolbar_icon("pan").isNull()
        assert not tab.image_viewer.toolbar_icon("zoom").isNull()
        assert not tab.image_viewer.toolbar_icon("home").isNull()
        with pytest.raises(ValueError, match="Unsupported viewer toolbar action"):
            tab.image_viewer.toolbar_icon("unknown")
        assert tab.image_viewer._pan_button.isChecked()
        assert tab.navigation_buttons["pan"].isChecked()
        for button in [*tab.navigation_buttons.values(), *tab.tool_buttons.values()]:
            assert button.width() == button.height()

        tab.tool_buttons["Brush"].click()

        assert not tab.drawing_mode
        assert not tab.image_viewer._interaction_locked

        tab._add_empty_layer()
        tab.tool_buttons["Brush"].click()

        assert tab.drawing_mode
        assert tab.image_viewer._interaction_locked
        assert tab.tool_buttons["Brush"].isChecked()
        assert not tab.image_viewer._pan_button.isChecked()
        assert not tab.navigation_buttons["pan"].isChecked()

        tab.image_viewer._zoom_button.click()

        assert not tab.drawing_mode
        assert not tab.image_viewer._interaction_locked
        assert tab.image_viewer._zoom_button.isChecked()
        assert tab.navigation_buttons["zoom"].isChecked()

        tab.navigation_buttons["pan"].click()

        assert tab.image_viewer._pan_button.isChecked()
        assert tab.navigation_buttons["pan"].isChecked()

        tab.tool_buttons["Brush"].click()

        tab.tool_buttons["Brush"].click()

        assert not tab.drawing_mode
        assert not tab.image_viewer._interaction_locked
        assert not tab.tool_buttons["Brush"].isChecked()
        assert tab.image_viewer._pan_button.isChecked()
        assert tab.navigation_buttons["pan"].isChecked()
    finally:
        tab.close()


class DummyMaskLayer:
    def __init__(self, data, visible=True, combine_mode="OR"):
        self.data = np.asarray(data, dtype=bool)
        self.visible = visible
        self.combine_mode = combine_mode


def test_mask_layers_compose_in_order_with_incoming_operators():
    layers = [
        DummyMaskLayer([[True, True], [False, False]]),
        DummyMaskLayer([[True, False], [True, False]], combine_mode="AND"),
        DummyMaskLayer([[False, False], [False, True]], combine_mode="OR"),
    ]

    result = compose_mask_layers(layers)

    np.testing.assert_array_equal(result, [[True, False], [False, True]])


def test_mask_tab_threshold_modes_and_layer_edit_guards(qapp):
    from tabs.mask_tab import MaskApp

    tab = MaskApp(DummyParentApp())
    tab.image_data = np.arange(9, dtype=float).reshape(3, 3)
    try:
        tab.threshold_region.setRegion((2.0, 5.0))

        tab.threshold_mode_combo.setCurrentText("Below")
        np.testing.assert_array_equal(tab._make_threshold_mask(), tab.image_data <= 5.0)
        assert "threshold-preview" in tab.image_viewer._overlays
        tab.threshold_mode_combo.setCurrentText("Range")
        np.testing.assert_array_equal(
            tab._make_threshold_mask(),
            (tab.image_data >= 2.0) & (tab.image_data <= 5.0),
        )
        tab.threshold_mode_combo.setCurrentText("Above")
        np.testing.assert_array_equal(tab._make_threshold_mask(), tab.image_data >= 2.0)

        tab.threshold_low_spin.setValue(2.0)
        tab.threshold_high_spin.setValue(5.0)
        tab.threshold_log_x_check.setChecked(True)
        plot_low, plot_high = tab.threshold_region.getRegion()
        assert plot_low == pytest.approx(np.log10(2.0))
        assert plot_high == pytest.approx(np.log10(5.0))
        np.testing.assert_array_equal(tab._make_threshold_mask(), tab.image_data >= 2.0)

        tab.threshold_log_x_check.setChecked(False)
        tab.threshold_low_spin.blockSignals(True)
        tab.threshold_high_spin.blockSignals(True)
        tab.threshold_low_spin.setValue(7.0)
        tab.threshold_high_spin.setValue(3.0)
        tab.threshold_low_spin.blockSignals(False)
        tab.threshold_high_spin.blockSignals(False)
        tab.threshold_mode_combo.setCurrentText("Range")
        tab._normalize_threshold_spins()
        assert tab.threshold_low_spin.value() == 3.0
        assert tab.threshold_high_spin.value() == 7.0
        np.testing.assert_array_equal(
            tab._make_threshold_mask(),
            (tab.image_data >= 3.0) & (tab.image_data <= 7.0),
        )

        tab._add_empty_layer()
        tab.mask_layers[0].visible = False
        tab.tool_buttons["Brush"].click()
        assert not tab.drawing_mode
    finally:
        tab.close()


def test_mask_session_restore_migrates_legacy_combine_method(qapp, monkeypatch):
    from tabs import mask_tab

    arrays = {
        "first.npy": np.array([[True, True], [False, False]]),
        "second.npy": np.array([[True, False], [True, False]]),
    }
    monkeypatch.setattr(mask_tab.session_cache, "load_array", arrays.get)
    tab = mask_tab.MaskApp(DummyParentApp())
    try:
        tab.restore_session_state({
            "combine_method": "AND",
            "layers": [
                {"name": "First", "file": "first.npy"},
                {"name": "Second", "file": "second.npy", "combine_mode": "OR"},
            ],
        })

        assert tab.mask_layers[0].combine_mode == "AND"
        assert tab.mask_layers[1].combine_mode == "OR"
    finally:
        tab.close()


def test_mask_tab_renders_visible_layers_and_refinement_is_undoable(qapp):
    from tabs.mask_tab import MaskApp, MaskLayer

    tab = MaskApp(DummyParentApp())
    tab.image_data = np.zeros((5, 5), dtype=float)
    full = np.ones((5, 5), dtype=bool)
    hidden = np.eye(5, dtype=bool)
    tab.mask_layers = [
        MaskLayer(full.copy(), "Visible"),
        MaskLayer(hidden, "Hidden", visible=False),
    ]
    try:
        tab._update_layer_list()
        tab.layer_list.setCurrentRow(0)
        tab.update_plot()

        assert "combined-mask" in tab.image_viewer._overlays
        assert "mask-layer-0" not in tab.image_viewer._overlays
        assert "mask-layer-1" not in tab.image_viewer._overlays
        assert "threshold-preview" not in tab.image_viewer._overlays

        connector = tab.layer_list.itemWidget(tab.layer_list.item(1))
        operator_button = connector.findChild(QPushButton)
        assert operator_button.text() == "OR"
        assert "∪ Union" in operator_button.toolTip()
        operator_button.click()
        assert tab.mask_layers[1].combine_mode == "AND"
        connector = tab.layer_list.itemWidget(tab.layer_list.item(1))
        operator_button = connector.findChild(QPushButton)
        assert operator_button.text() == "AND"
        assert "∩ Intersection" in operator_button.toolTip()

        tab._refine_active_layer("shrink")
        assert np.count_nonzero(tab.mask_layers[0].data) < 25
        tab.undo_stack.undo()
        np.testing.assert_array_equal(tab.mask_layers[0].data, full)
        tab.undo_stack.redo()
        assert np.count_nonzero(tab.mask_layers[0].data) < 25
    finally:
        tab.close()


def test_mask_drawing_session_composes_preview_for_visible_layers():
    layers = [
        DummyMaskLayer([[False, True], [False, False]]),
        DummyMaskLayer([[False, False], [True, False]]),
        DummyMaskLayer([[True, True], [True, True]], visible=False),
    ]
    previews = []
    session = MaskDrawingSession(
        is_enabled=lambda: True,
        get_tool=lambda: None,
        get_active_layer=lambda: None,
        get_active_layer_index=lambda: None,
        get_layers=lambda: layers,
        set_combined_mask=lambda mask: previews.append(mask.copy()),
        update_combined_mask=lambda: None,
        update_plot=lambda: None,
        set_drawing_enabled=lambda enabled: None,
        should_auto_disable=lambda: False,
        get_brush_size=lambda: 1,
        get_draw_value=lambda: True,
        on_edit_finished=lambda index, before, after: None,
    )

    preview = np.array([[False, False], [False, True]])
    session._show_layer_preview(0, preview)

    expected = np.array([[False, False], [True, True]])
    np.testing.assert_array_equal(previews[-1], expected)


def test_polygon_uses_all_clicked_vertices():
    tool = PolygonDrawingTool()
    tool.vertices = [(1, 1), (1, 4), (4, 1)]

    result = tool.finish(np.zeros((6, 6), dtype=bool))

    assert result[2, 2]


class DummyPointerEvent:
    def __init__(self, x, y, inside_image=True):
        self.x = x
        self.y = y
        self.inside_image = inside_image


def test_polygon_session_commits_to_layer_where_edit_began():
    layers = [
        DummyMaskLayer(np.zeros((6, 6), dtype=bool)),
        DummyMaskLayer(np.zeros((6, 6), dtype=bool)),
    ]
    active_index = [0]
    edits = []
    tool = PolygonDrawingTool()
    session = MaskDrawingSession(
        is_enabled=lambda: True,
        get_tool=lambda: tool,
        get_active_layer=lambda: layers[active_index[0]],
        get_active_layer_index=lambda: active_index[0],
        get_layers=lambda: layers,
        set_combined_mask=lambda mask: None,
        update_combined_mask=lambda: None,
        update_plot=lambda: None,
        set_drawing_enabled=lambda enabled: None,
        should_auto_disable=lambda: False,
        get_brush_size=lambda: 1,
        get_draw_value=lambda: True,
        on_edit_finished=lambda index, before, after: edits.append((index, before, after)),
    )

    session.handle_press(DummyPointerEvent(1, 1))
    active_index[0] = 1
    session.handle_press(DummyPointerEvent(4, 1))
    session.handle_press(DummyPointerEvent(1, 4))

    assert session.finish_polygon()
    assert layers[0].data[2, 2]
    assert not layers[1].data.any()
    assert edits[0][0] == 0


def test_mask_tab_cancels_polygon_when_switching_modes(qapp):
    from tabs.mask_tab import MaskApp

    tab = MaskApp(DummyParentApp())
    tab.image_data = np.zeros((6, 6), dtype=float)
    try:
        tab._add_empty_layer()
        tab.tool_buttons["Polygon"].click()
        for x, y in [(1, 1), (4, 1), (1, 4)]:
            tab.drawing_session.handle_press(DummyPointerEvent(x, y))
        assert tab.drawing_session._edit_layer is tab.mask_layers[0]
        assert tab._preview_mask is not None

        tab.tool_buttons["Line"].click()

        assert tab.drawing_session._edit_layer is None
        assert not tab.drawing_tools["Polygon"].vertices
        assert tab._preview_mask is None

        tab.tool_buttons["Polygon"].click()
        tab.drawing_session.handle_press(DummyPointerEvent(1, 1))
        tab.image_viewer._zoom_button.click()

        assert not tab.drawing_mode
        assert tab.drawing_session._edit_layer is None
        assert not tab.drawing_tools["Polygon"].vertices
        assert tab._preview_mask is None
    finally:
        tab.close()


def test_brush_session_uses_preview_refresh_until_release():
    layer = DummyMaskLayer(np.zeros((8, 8), dtype=bool))
    tool = BrushDrawingTool()
    calls = {"preview": 0, "final": 0}
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
        on_edit_finished=lambda index, before, after: None,
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