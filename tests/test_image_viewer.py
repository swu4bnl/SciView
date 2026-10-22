import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
)

import pyqtgraph as pg

from sciview.interfaces.stable_qt.widgets.image_viewer import ImagePointerEvent, ImageViewer
from sciview.interfaces.stable_qt.tools.mask_drawing_tools import (
    BrushDrawingTool,
    MaskDrawingSession,
    RectangleDrawingTool,
    WatershedFillTool,
)
from sciview.masking.layers import MaskLayer, compose_mask_layers
from sciview.core.image_collection import ComparisonMode
from tabs.image_browser_tab import ImageBrowserApp


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


@pytest.mark.parametrize("channels", [3, 4])
def test_colormap_restored_after_color_image(viewer, channels):
    scalar = np.arange(6, dtype=float).reshape(2, 3)
    viewer.set_image(scalar)
    viewer.set_colormap("viridis")
    expected_image = viewer._image_item.getPixmap().toImage()
    viewer.set_color_image(np.zeros((2, 3, channels), dtype=np.uint8))
    viewer.set_image(scalar)
    viewer.set_colormap("viridis")
    assert viewer._image_item.getPixmap().toImage() == expected_image
    assert viewer.source_array is scalar


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


def test_viewer_elides_middle_of_long_title(viewer):
    viewer.resize(360, 240)
    viewer.show()
    QApplication.processEvents()
    viewer.set_title(
        "This is a very long viewer title with a middle section to hide."
    )

    title = viewer._plot_item.titleLabel.text

    assert title.startswith("This")
    assert title.endswith("hide.")
    assert len(title) < len(viewer._title_text)


def test_viewer_shows_explicit_title_rows_with_room_for_each(viewer):
    viewer.resize(900, 240)
    viewer.show()
    QApplication.processEvents()
    viewer.set_title("pinned <scan>.tif\n+ selected.tif × 0.50")

    title_label = viewer._plot_item.titleLabel

    assert title_label.text.split("<br>") == [
        "pinned &lt;scan&gt;.tif",
        "+ selected.tif × 0.50",
    ]
    assert title_label.maximumHeight() > 30

    viewer.set_title("Selected: one.tif")
    assert title_label.maximumHeight() == 30


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

    def show_status(self, message):
        self.last_status = message

    def update_all_displays(self):
        pass

    def publish_shared_display_settings(self, settings, source_tab=None):
        self.display_settings.update(settings)

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


def test_folder_row_reopens_after_session_navigation(qapp, tmp_path):
    from tabs.image_browser_tab import ImageBrowserApp

    tab = ImageBrowserApp(DummyParentApp())
    try:
        first_path = str(tmp_path / "first.tif")
        second_path = str(tmp_path / "second.tif")
        from PyQt5.QtWidgets import QListWidgetItem

        first_item = QListWidgetItem("first.tif")
        first_item.setData(Qt.UserRole, first_path)
        second_item = QListWidgetItem("second.tif")
        second_item.setData(Qt.UserRole, second_path)
        tab.folder_files_list.addItem(first_item)
        tab.folder_files_list.addItem(second_item)

        tab.folder_files_list.setCurrentItem(first_item)
        tab.session_manager.add_image_reference(second_path)
        tab.folder_files_list.setCurrentItem(second_item)

        tab.folder_files_list.itemClicked.emit(first_item)
        assert tab.session_manager.current_index == 0
    finally:
        tab.close()


def test_image_browser_pin_compare_modes_preserve_view_and_validate(qapp, tmp_path):
    tab = ImageBrowserApp(DummyParentApp())
    tab.show()
    reference = np.arange(16, dtype=float).reshape(4, 4)
    current = reference + 4.0
    reference_path = str(tmp_path / "a-reference.tif")
    current_path = str(tmp_path / "b-current.tif")
    (tmp_path / "a-reference.tif").touch()
    (tmp_path / "b-current.tif").touch()
    try:
        tab.session_manager.add_image(reference, reference_path)
        tab.session_manager.add_image(current, current_path)
        tab.folder_path_input.setText(str(tmp_path))
        tab.pattern_input.setText("*.tif")
        tab._refresh_folder_browser(force=True)
        qapp.processEvents()
        assert tab.image_viewer._title_text == "Selected: b-current.tif"
        assert "B" not in tab.image_viewer._title_text
        item = tab.folder_files_list.item(0)
        item_rect = tab.folder_files_list.visualItemRect(item)
        QTest.mouseClick(
            tab.folder_files_list.viewport(),
            Qt.LeftButton,
            Qt.ControlModifier,
            pos=QPoint(item_rect.left() + 100, item_rect.center().y()),
        )
        assert tab.session_manager.collection.pinned_path == reference_path
        tab.folder_files_list.setCurrentRow(1)
        assert not tab.comparison_buttons["difference"].isHidden()
        tab.image_viewer.set_view_range(((0.5, 2.5), (0.5, 2.5)))
        preserved_range = tab.image_viewer.get_view_range()

        tab.comparison_buttons["difference"].click()
        assert np.array_equal(tab.image_viewer.source_array, reference - current)
        assert tab.image_viewer._title_text == "a-reference.tif\n− b-current.tif × 1.00"
        assert tab.comparison_parameter_slider.isVisible()
        assert "comparison-label-a" not in tab.image_viewer._overlays
        # Auto runs on mode entry: diverging map and symmetric robust limits.
        assert tab.image_viewer.display_levels == pytest.approx((-5.0, 5.0))
        assert tab.image_viewer._colormap_name == "coolwarm"
        assert tab.cmap_selector.currentText() == "coolwarm"
        assert tab.vmin_input.text() == "-5"
        assert not tab.img_scale_combo.isEnabled()
        shared_cmap = tab.display_settings["cmap"]
        current_range = tab.image_viewer.get_view_range()
        assert current_range[0] == pytest.approx(preserved_range[0])
        assert current_range[1] == pytest.approx(preserved_range[1])

        tab.comparison_buttons["opacity"].click()
        tab.comparison_parameter_slider.setValue(25)
        assert tab.image_viewer.source_array is current
        assert tab.image_viewer._comparison_reference_item.opacity() == pytest.approx(0.75)
        assert tab.comparison_parameter_label.text() == "A 75% · B 25%"
        assert (
            tab.image_viewer._title_text
            == "a-reference.tif · 75%\n→ b-current.tif · 25%"
        )
        assert "→" in tab.comparison_buttons["opacity"].text()
        assert not hasattr(tab.image_viewer, "_comparison_reference_histogram")
        assert tab.img_scale_combo.isEnabled()
        viewport = tab.image_viewer._graphics.viewport()
        image_position = tab.image_viewer.image_to_widget(QPointF(1.0, 1.0)).toPoint()
        wheel_position = viewport.mapFrom(tab.image_viewer, image_position)
        wheel_event = QWheelEvent(
            QPointF(wheel_position),
            QPointF(viewport.mapToGlobal(wheel_position)),
            QPoint(),
            QPoint(0, 120),
            120,
            Qt.Vertical,
            Qt.NoButton,
            Qt.ShiftModifier,
        )
        QApplication.sendEvent(viewport, wheel_event)
        assert tab.comparison_parameter_slider.value() == 30
        tab.cmap_selector.setCurrentText("magma")
        overlay_display = tab.session_manager.collection.comparison_displays[
            ComparisonMode.OPACITY
        ]
        assert overlay_display.colormap == "magma"
        assert tab.image_viewer._colormap_name == "magma"
        assert tab.display_settings["cmap"] == shared_cmap
        tab.image_viewer._histogram.setLevels(5.0, 18.0)
        assert tab.session_manager.collection.comparison_displays[
            ComparisonMode.OPACITY
        ].levels == pytest.approx((5.0, 18.0))
        assert tuple(tab.image_viewer._comparison_reference_item.getLevels()) == pytest.approx(
            (5.0, 18.0)
        )
        assert tab.display_settings["vmin"] == -2

        tab.comparison_buttons["add"].click()
        assert tab.comparison_parameter_slider.isVisible()
        assert tab.session_manager.collection.add_b_percentage == 100
        np.testing.assert_array_equal(tab.image_viewer.source_array, reference + current)
        tab.comparison_parameter_slider.setValue(25)
        np.testing.assert_array_equal(
            tab.image_viewer.source_array,
            reference + current * 0.25,
        )
        assert "25%" in tab.comparison_parameter_label.text()
        assert (
            tab.image_viewer._title_text
            == "a-reference.tif\n+ b-current.tif × 0.25"
        )
        assert tab.image_viewer._plot_item.titleLabel.text.count("<br>") == 1
        assert tab.display_settings["vmin"] == -2

        tab.comparison_buttons["split"].click()
        assert np.array_equal(
            tab.image_viewer.source_array,
            np.concatenate((reference[:, :2], current[:, 2:]), axis=1),
        )
        assert "comparison-label-a" in tab.image_viewer._overlays
        assert "comparison-label-b" in tab.image_viewer._overlays
        divider = tab.image_viewer._overlays["comparison-divider"][0]
        divider.setValue(1.0)
        assert tab.session_manager.collection.split_fraction == pytest.approx(0.25)
        assert np.array_equal(
            tab.image_viewer.source_array,
            np.concatenate((reference[:, :1], current[:, 1:]), axis=1),
        )
        # Dragging must keep the same line item, or the mouse grab is lost.
        assert tab.image_viewer._overlays["comparison-divider"][0] is divider
        assert divider.scene() is not None
        divider.setValue(3.0)
        assert tab.session_manager.collection.split_fraction == pytest.approx(0.75)
        assert tab.image_viewer._overlays["comparison-divider"][0] is divider

        tab.comparison_buttons["difference"].click()
        tab.cmap_selector.setCurrentText("RdYlBu")
        tab.vmin_input.setText("-2")
        tab.vmin_input.editingFinished.emit()
        assert tab.image_viewer.source_array is not current
        assert tab.image_viewer.display_levels == pytest.approx((-2.0, 2.0))
        assert tab.vmax_input.text() == "2"
        tab.image_viewer._histogram.setLevels(-1.0, 3.0)
        difference_display = tab.session_manager.collection.comparison_displays[
            ComparisonMode.DIFFERENCE
        ]
        assert difference_display.levels == pytest.approx((-3.0, 3.0))
        assert tab.image_viewer.display_levels == pytest.approx((-3.0, 3.0))
        tab.image_viewer._auto_levels_button.click()
        assert tab.image_viewer.display_levels == pytest.approx((-5.0, 5.0))
        assert tab.image_viewer._colormap_name == "RdYlBu"
        assert tab.display_settings["vmin"] == -2
        assert tab.display_settings["cmap"] == shared_cmap
        tab.comparison_parameter_slider.setValue(50)
        np.testing.assert_array_equal(
            tab.image_viewer.source_array,
            reference - current * 0.5,
        )
        assert "50%" in tab.comparison_parameter_label.text()
        assert tab.image_viewer._title_text == "a-reference.tif\n− b-current.tif × 0.50"

        assert "flicker" not in tab.comparison_buttons
        # Clicking the active operation again returns to hold-to-compare.
        tab.comparison_buttons["difference"].click()
        assert not tab.comparison_buttons["difference"].isChecked()
        assert tab.image_viewer.source_array is reference
        assert tab.image_viewer._title_text == "Pinned: a-reference.tif"
        assert tab.comparison_parameter_label.text() == "Hold a file to show it"
        assert tab.comparison_parameter_slider.isHidden()
        assert "comparison-label-a" not in tab.image_viewer._overlays

        list_viewport = tab.folder_files_list.viewport()
        current_rect = tab.folder_files_list.visualItemRect(
            tab.folder_files_list.item(1)
        )
        row_position = QPoint(current_rect.left() + 100, current_rect.center().y())
        QTest.mousePress(list_viewport, Qt.LeftButton, pos=row_position)
        assert tab.image_viewer.source_array is current
        assert tab.image_viewer._title_text == "Selected: b-current.tif"
        QTest.mouseRelease(list_viewport, Qt.LeftButton, pos=row_position)
        assert tab.image_viewer.source_array is reference
        assert tab.folder_files_list.currentRow() == 1
        assert tab.session_manager.collection.current_reference.path == current_path

        QTest.keyPress(tab.folder_files_list, Qt.Key_Space)
        assert tab.image_viewer.source_array is current
        QTest.keyRelease(tab.folder_files_list, Qt.Key_Space)
        assert tab.image_viewer.source_array is reference

        # The held file stays selected, so operations apply to it after release.
        tab.comparison_buttons["split"].click()
        assert np.array_equal(
            tab.image_viewer.source_array,
            np.concatenate((reference[:, :3], current[:, 3:]), axis=1),
        )
        tab.comparison_buttons["split"].click()
        assert tab.image_viewer.source_array is reference

        tab.folder_play_button.click()
        assert tab.folder_play_timer.isActive()
        tab._update_display()
        assert tab.image_viewer.source_array is current
        tab.folder_play_button.click()
        assert tab.image_viewer.source_array is reference

        incompatible = np.ones((3, 4), dtype=float)
        incompatible_path = str(tmp_path / "c-incompatible.tif")
        (tmp_path / "c-incompatible.tif").touch()
        tab.session_manager.add_image(incompatible, incompatible_path)
        tab._refresh_folder_browser(force=True)
        tab.folder_files_list.setCurrentRow(2)
        tab.comparison_buttons["difference"].click()
        assert tab.image_viewer.source_array is incompatible
        assert "matching two-dimensional shapes" in tab.parent_app.last_status
        assert tab.cmap_selector.currentText() == shared_cmap
        assert tab.image_viewer._colormap_name == shared_cmap
        assert tab.img_scale_combo.isEnabled()

        for index in range(6):
            tab.session_manager.add_image(
                np.full((4, 4), index, dtype=float),
                f"extra-{index}.tif",
            )
        assert tab.session_manager.get_pinned_image()["data"] is reference
    finally:
        tab.close()


def test_image_browser_pin_marker_survives_folder_navigation(qapp, tmp_path):
    tab = ImageBrowserApp(DummyParentApp())
    tab.show()
    folder_a = tmp_path / "first"
    folder_b = tmp_path / "second"
    folder_a.mkdir()
    folder_b.mkdir()
    reference_path = folder_a / "reference.tif"
    current_path = folder_b / "current.tif"
    reference_path.touch()
    current_path.touch()
    try:
        tab.session_manager.add_image(
            np.ones((4, 4)),
            str(reference_path),
        )
        tab.folder_path_input.setText(str(folder_a))
        tab.pattern_input.setText("*.tif")
        tab._refresh_folder_browser(force=True)
        qapp.processEvents()
        item = tab.folder_files_list.item(0)
        item_rect = tab.folder_files_list.visualItemRect(item)
        QTest.mouseClick(
            tab.folder_files_list.viewport(),
            Qt.LeftButton,
            pos=QPoint(item_rect.left() + 10, item_rect.center().y()),
        )

        tab.folder_path_input.setText(str(folder_b))
        tab._refresh_folder_browser(force=True)

        pinned_row = next(
            row
            for row in range(tab.folder_files_list.count())
            if tab.folder_files_list.item(row).data(Qt.UserRole) == str(reference_path)
        )
        pinned_item = tab.folder_files_list.item(pinned_row)
        assert pinned_item.text() == "reference.tif"
        assert pinned_item.icon().cacheKey() == tab._pin_icon.cacheKey()
        current_item = next(
            tab.folder_files_list.item(row)
            for row in range(tab.folder_files_list.count())
            if tab.folder_files_list.item(row).data(Qt.UserRole) == str(current_path)
        )
        assert current_item.icon().cacheKey() == tab._file_icon.cacheKey()
        current_rect = tab.folder_files_list.visualItemRect(current_item)
        QTest.mouseMove(
            tab.folder_files_list.viewport(),
            QPoint(current_rect.left() + 10, current_rect.center().y()),
        )
        assert current_item.icon().cacheKey() == tab._pin_preview_icon.cacheKey()
        assert tab.folder_files_list.viewport().cursor().shape() == Qt.PointingHandCursor
        QTest.mouseMove(
            tab.folder_files_list.viewport(),
            QPoint(current_rect.right() - 5, current_rect.center().y()),
        )
        assert current_item.icon().cacheKey() == tab._file_icon.cacheKey()
        assert "Pinned reference A" in pinned_item.toolTip()
        assert "Ctrl-click" in pinned_item.toolTip()
        assert tab.session_manager.collection.pinned_path == str(reference_path)

        rect = tab.folder_files_list.visualItemRect(pinned_item)
        QTest.mouseClick(
            tab.folder_files_list.viewport(),
            Qt.LeftButton,
            pos=rect.topLeft() + QPointF(10, rect.height() / 2).toPoint(),
        )
        assert tab.session_manager.collection.pinned_path is None
    finally:
        tab.close()


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

    def update_plot(self):
        pass


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

    expected = np.array([[False, False], [True, True]])
    np.testing.assert_array_equal(combined, expected)


def DummyPointerEvent(x, y, inside_image=True, inside_canvas=True):
    return ImagePointerEvent(x, y, Qt.LeftButton, Qt.NoModifier, inside_image, inside_canvas)


def _drawing_session(tool, layer, viewer):
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


def test_rectangle_clamps_plot_points_to_image_corners(viewer):
    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    tool = RectangleDrawingTool()
    session = _drawing_session(tool, layer, viewer)

    session.handle_press(DummyPointerEvent(-10, -10, inside_image=False))
    session.handle_motion(DummyPointerEvent(20, 20, inside_image=False))
    session.handle_release(DummyPointerEvent(20, 20, inside_image=False))

    assert layer.data.all()


def test_drawing_ignores_press_outside_plot_canvas(viewer):
    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    tool = RectangleDrawingTool()
    session = _drawing_session(tool, layer, viewer)

    session.handle_press(DummyPointerEvent(-10, -10, inside_image=False, inside_canvas=False))

    assert not layer.data.any()


def test_brush_clamps_active_stroke_to_image_edge(viewer):
    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    tool = BrushDrawingTool()
    session = _drawing_session(tool, layer, viewer)

    session.handle_press(DummyPointerEvent(1, 1))
    session.handle_motion(DummyPointerEvent(20, 1, inside_image=False))
    session.handle_release(DummyPointerEvent(20, 1, inside_image=False))

    assert layer.data[1, -1]


def test_smart_fill_rejects_seed_outside_image(viewer):
    layer = MaskLayer(np.zeros((4, 6), dtype=bool))
    tool = WatershedFillTool()
    session = _drawing_session(tool, layer, viewer)

    session.handle_press(DummyPointerEvent(-1, -1, inside_image=False))

    assert not layer.data.any()


@pytest.mark.parametrize("tool_name", ["Brush", "Eraser", "Line", "Rectangle", "Circle", "Polygon", "Smart Fill"])
def test_mask_gestures_defer_pixels_publication_and_history_until_commit(qapp, tool_name):
    from tabs.mask_tab import MaskApp

    published = []
    parent = DummyParentApp()
    parent.publish_shared_mask = lambda mask, **_kwargs: published.append(mask.copy())
    tab = MaskApp(parent)
    tab.image_data = np.arange(16 * 18, dtype=float).reshape(16, 18)
    tab.update_plot()
    initial = np.full((16, 18), tool_name == "Eraser", dtype=bool)
    layer = MaskLayer(initial.copy())
    tab.mask_layers.append(layer)
    tab._update_layer_list()
    tab._update_tool_brush_size(1)
    tab.tool_buttons[tool_name].click()
    published.clear()
    session = tab.drawing_session
    try:
        session.handle_press(DummyPointerEvent(2, 3))
        for point in [(4, 4), (6, 6), (9, 8)]:
            session.handle_motion(DummyPointerEvent(*point))
        if tool_name == "Polygon":
            session.handle_release(DummyPointerEvent(9, 8))
            session.handle_press(DummyPointerEvent(9, 8))
            session.handle_press(DummyPointerEvent(9, 3))
        np.testing.assert_array_equal(layer.data, initial)
        np.testing.assert_array_equal(tab.combined_mask, initial)
        assert published == []
        assert tab.undo_stack.count() == 0
        if tool_name == "Polygon":
            assert session.finish_polygon()
        else:
            session.handle_release(DummyPointerEvent(9, 8))
        assert len(published) == tab.undo_stack.count() == 1
        after = layer.data.copy()
        assert np.any(after != initial)
        tab.undo_stack.undo()
        np.testing.assert_array_equal(layer.data, initial)
        tab.undo_stack.redo()
        np.testing.assert_array_equal(layer.data, after)
    finally:
        tab.close()


def test_mask_brush_keeps_alt_effect_per_segment_and_commits_release_endpoint(viewer):
    from sciview.masking.drawing import paint_brush_segment

    layer = MaskLayer(np.zeros((16, 16), dtype=bool))
    session = _drawing_session(BrushDrawingTool(), layer, viewer)
    session.handle_press(DummyPointerEvent(2, 3))
    session.handle_motion(DummyPointerEvent(8, 3))
    session.get_draw_value = lambda: False
    session.handle_motion(DummyPointerEvent(8, 7))
    session.handle_release(DummyPointerEvent(12, 7))
    expected = np.zeros_like(layer.data)
    paint_brush_segment(expected, (3, 2), (3, 2), 0, True)
    paint_brush_segment(expected, (3, 2), (3, 8), 0, True)
    paint_brush_segment(expected, (3, 8), (7, 8), 0, False)
    paint_brush_segment(expected, (7, 8), (7, 12), 0, False)
    np.testing.assert_array_equal(layer.data, expected)


def test_release_outside_canvas_commits_last_accepted_point_and_ignores_right_click(viewer):
    layer = MaskLayer(np.zeros((16, 16), dtype=bool))
    session = _drawing_session(RectangleDrawingTool(), layer, viewer)
    right_click = ImagePointerEvent(1, 1, Qt.RightButton, Qt.NoModifier, True, True)
    session.handle_press(right_click)
    session.handle_press(DummyPointerEvent(2, 3))
    session.handle_motion(DummyPointerEvent(6, 7))
    session.handle_motion(DummyPointerEvent(99, 99, False, False))
    session.handle_release(DummyPointerEvent(99, 99, False, False))
    expected = np.zeros_like(layer.data)
    expected[3:8, 2:7] = True
    np.testing.assert_array_equal(layer.data, expected)


def test_pending_mask_edit_cannot_mutate_a_different_selected_layer(viewer):
    layer = MaskLayer(np.zeros((16, 16), dtype=bool))
    session = _drawing_session(BrushDrawingTool(), layer, viewer)
    session.handle_press(DummyPointerEvent(2, 3))
    session.handle_motion(DummyPointerEvent(6, 7))
    session.get_active_layer = lambda: MaskLayer(np.ones((16, 16), dtype=bool))
    session.handle_release(DummyPointerEvent(8, 8))
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
        tab.drawing_session.handle_press(DummyPointerEvent(2, 1))
        tab.drawing_session.handle_motion(DummyPointerEvent(6, 5))
        assert published == []
        tab.drawing_session.handle_release(DummyPointerEvent(6, 5))
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
    session = _drawing_session(WatershedFillTool(), layer, viewer)
    session.on_error = errors.append

    def failed_fill(*_args, **_kwargs):
        raise ValueError("Invalid fill input")

    monkeypatch.setattr(drawing, "watershed_fill_mask", failed_fill)
    session.handle_press(DummyPointerEvent(3, 3))
    session.handle_release(DummyPointerEvent(3, 3))
    assert not layer.data.any()
    assert len(errors) == 1
    assert "Invalid fill input" in str(errors[0])
    assert "mask-drawing-preview" not in viewer._overlays


@pytest.mark.parametrize("cancel", [None, "escape", "image", "layer", "tool"])
def test_real_mask_pointer_gesture_commit_and_cancellation(qapp, cancel):
    from tabs.mask_tab import MaskApp

    tab = MaskApp(DummyParentApp())
    tab.resize(1280, 800)
    tab.image_data = np.ones((20, 30))
    tab.update_plot()
    layer = MaskLayer(np.zeros((20, 30), dtype=bool))
    tab.mask_layers.append(layer)
    tab._update_layer_list()
    tab.tool_buttons["Rectangle"].click()
    tab.show()
    qapp.processEvents()
    viewer = tab.image_viewer
    viewport = viewer._graphics.viewport()

    def position(x, y):
        return viewer._graphics.mapFromScene(viewer._view_box.mapViewToScene(QPointF(x, y)))

    try:
        QTest.mousePress(viewport, Qt.LeftButton, pos=position(3, 4))
        QTest.mouseMove(viewport, position(9, 10))
        assert not layer.data.any()
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
        if cancel is None:
            assert layer.data[6, 6]
            assert tab.undo_stack.count() == 1
        else:
            assert not layer.data.any()
            assert tab.undo_stack.count() == 0
    finally:
        tab.close()
        tab.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_colormap_selector_items_preview_gradients(qapp):
    from PyQt5.QtGui import QLinearGradient

    tab = ImageBrowserApp(DummyParentApp())
    try:
        index = tab.cmap_selector.findText("viridis")
        brush = tab.cmap_selector.itemData(index, Qt.BackgroundRole)
        assert isinstance(brush.gradient(), QLinearGradient)
        assert len(brush.gradient().stops()) > 2
        assert tab.cmap_selector.itemData(index, Qt.ForegroundRole) is not None
    finally:
        tab.close()
