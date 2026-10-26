import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
)

import pyqtgraph as pg

from sciview.interfaces.stable_qt.widgets.image_viewer import ImageViewer
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


def test_scalar_viewer_preserves_scientific_data_across_display_and_frame_changes(viewer):
    image = np.arange(3 * 5, dtype=float).reshape(3, 5)

    viewer.set_image(image)

    assert viewer.source_array is image
    assert viewer.get_raw_value_at(0.0, 0.0) == image[0, 0]
    assert viewer.get_raw_value_at(4.2, 2.0) == image[2, 4]
    assert viewer.get_raw_value_at(-1.0, 0.0) is None
    assert viewer.get_raw_value_at(0.0, np.nan) is None
    viewer.set_view_range(((1.0, 3.0), (0.5, 2.5)))
    preserved_range = viewer.get_view_range()
    viewer.set_levels(-2.0, 10.0)
    viewer.set_colormap("viridis")
    assert viewer.source_array is image
    assert viewer.display_array is image
    assert viewer.display_levels == (-2.0, 10.0)
    assert viewer.get_view_range()[0] == pytest.approx(preserved_range[0])
    assert viewer.get_view_range()[1] == pytest.approx(preserved_range[1])

    replacement = image + 100.0
    viewer.set_image(replacement)
    x_range, y_range = viewer.get_view_range()
    assert x_range == pytest.approx(preserved_range[0])
    assert y_range == pytest.approx(preserved_range[1])
    assert viewer.get_raw_value_at(1.0, 1.0) == replacement[1, 1]
    viewer.set_image(np.arange(4 * 6, dtype=float).reshape(4, 6))
    x_range, y_range = viewer.get_view_range()
    assert x_range[0] <= 0.0
    assert x_range[1] >= 6.0
    assert y_range[0] <= 0.0
    assert y_range[1] >= 4.0
    image = np.array([[0.0, -5.0, 1.0], [10.0, np.nan, np.inf], [100.0, 5.0, 2.0]])
    viewer.set_image(image)
    viewer.set_levels(0.0, 100.0)

    viewer.set_scale("log")

    display = viewer.display_array
    assert viewer.source_array is image
    assert display is not image
    assert viewer.display_levels == pytest.approx((0.0, 2.0))
    np.testing.assert_allclose(display, [[0, 0, 0], [1, 0, 0], [2, np.log10(5), np.log10(2)]])

    viewer.clear_image("No image loaded")

    assert viewer.source_array is None
    assert viewer.display_array is None
    assert viewer.display_levels is None


def test_color_and_scalar_frame_transitions_preserve_channels_and_colormap(viewer):
    scalar = np.arange(6, dtype=float).reshape(2, 3)
    viewer.set_image(scalar)
    viewer.set_colormap("viridis")
    expected_image = viewer._image_item.getPixmap().toImage()
    for channels in (3, 4):
        image = np.zeros((3, 4, channels), dtype=np.ubyte)
        image[..., 0] = 255
        image[..., 1] = np.arange(4, dtype=np.ubyte)
        viewer.set_color_image(image)
        assert viewer.source_array is image
        assert viewer.display_array is image
        assert viewer.get_raw_value_at(1.0, 0.0).tolist() == [255, 1, 0] + [0] * (channels - 3)
        viewer.set_image(scalar)
        viewer.set_colormap("viridis")
        assert viewer._image_item.getPixmap().toImage() == expected_image


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


def select_exploration_task(tab, task):
    if task == "browse":
        mode = tab.session_manager.collection.comparison_mode
        if mode != ComparisonMode.FLICKER:
            tab.comparison_buttons[mode.value].click()
    else:
        tab.comparison_buttons[task].click()


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


def test_folder_polling_only_rebuilds_and_publishes_when_contents_change(qapp, tmp_path):
    published = []

    class Parent(DummyParentApp):
        def publish_shared_file_list(self, paths, **_kwargs):
            published.append(list(paths))

    tab = ImageBrowserApp(Parent())
    try:
        (tmp_path / "first.tif").touch()
        (tmp_path / "sub").mkdir()
        tab.folder_path_input.setText(str(tmp_path))
        tab._refresh_folder_browser(force=True)
        first_item = tab.folder_files_list.item(1)
        assert published[-1] == [str(tmp_path / "first.tif")]
        publish_count = len(published)

        tab._auto_refresh_folder_browser()
        assert len(published) == publish_count
        assert tab.folder_files_list.item(1) is first_item

        (tmp_path / "second.tif").touch()
        tab._auto_refresh_folder_browser()
        assert published[-1] == [
            str(tmp_path / "first.tif"),
            str(tmp_path / "second.tif"),
        ]
        assert [
            tab.folder_files_list.item(row).text()
            for row in range(tab.folder_files_list.count())
        ] == ["sub", "first.tif", "second.tif"]
    finally:
        tab.close()


def test_browser_pin_compare_and_export_workflow(qapp, tmp_path, monkeypatch):
    from PIL import Image

    import tabs.image_browser_tab as browser_module

    requests = []

    def choose_output(_parent, _title, **kwargs):
        requests.append(kwargs)
        return str(tmp_path / "difference"), ""

    monkeypatch.setattr(browser_module, "choose_path", choose_output)
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
        tab.pattern_input.setText("*.tif*")
        tab._refresh_folder_browser(force=True)
        qapp.processEvents()
        item = tab.folder_files_list.item(0)
        item_rect = tab.folder_files_list.visualItemRect(item)
        QTest.mouseClick(
            tab.folder_files_list.viewport(),
            Qt.LeftButton,
            pos=QPoint(item_rect.left() + 10, item_rect.center().y()),
        )
        assert tab.session_manager.collection.pinned_path == reference_path
        tab.folder_files_list.setCurrentRow(1)
        tab.image_viewer.set_view_range(((0.5, 2.5), (0.5, 2.5)))
        preserved_range = tab.image_viewer.get_view_range()

        select_exploration_task(tab, "difference")
        assert np.array_equal(tab.image_viewer.source_array, reference - current)
        # Auto runs on mode entry: diverging map and symmetric robust limits.
        assert tab.image_viewer.display_levels == pytest.approx((-5.0, 5.0))
        assert tab.image_viewer._colormap_name == "coolwarm"
        shared_cmap = tab.display_settings["cmap"]
        current_range = tab.image_viewer.get_view_range()
        assert current_range[0] == pytest.approx(preserved_range[0])
        assert current_range[1] == pytest.approx(preserved_range[1])

        select_exploration_task(tab, "opacity")
        tab.comparison_parameter_slider.setValue(25)
        assert tab.image_viewer.source_array is current
        assert tab.image_viewer._comparison_reference_item.opacity() == pytest.approx(0.75)
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
        assert tab.display_settings["cmap"] == shared_cmap
        tab.image_viewer._histogram.setLevels(5.0, 18.0)
        assert tab.session_manager.collection.comparison_displays[
            ComparisonMode.OPACITY
        ].levels == pytest.approx((5.0, 18.0))
        assert tuple(tab.image_viewer._comparison_reference_item.getLevels()) == pytest.approx(
            (5.0, 18.0)
        )

        select_exploration_task(tab, "add")
        np.testing.assert_array_equal(tab.image_viewer.source_array, reference + current)
        tab.comparison_parameter_slider.setValue(25)
        np.testing.assert_array_equal(
            tab.image_viewer.source_array,
            reference + current * 0.25,
        )

        select_exploration_task(tab, "split")
        assert np.array_equal(
            tab.image_viewer.source_array,
            np.concatenate((reference[:, :2], current[:, 2:]), axis=1),
        )
        divider = tab.image_viewer._overlays["comparison-divider"][0]
        divider.setValue(1.0)
        assert tab.session_manager.collection.split_fraction == pytest.approx(0.25)
        assert np.array_equal(
            tab.image_viewer.source_array,
            np.concatenate((reference[:, :1], current[:, 1:]), axis=1),
        )
        # Dragging must keep the same line item, or the mouse grab is lost.
        assert tab.image_viewer._overlays["comparison-divider"][0] is divider

        select_exploration_task(tab, "difference")
        tab.cmap_selector.setCurrentText("RdYlBu")
        tab.vmin_input.setText("-2")
        tab.vmin_input.editingFinished.emit()
        assert tab.image_viewer.display_levels == pytest.approx((-2.0, 2.0))
        tab.image_viewer._histogram.setLevels(-1.0, 3.0)
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
        tab.save_calculated_button.click()
        assert requests[0]["start_dir"] == str(tmp_path)
        with Image.open(tmp_path / "difference.tiff") as image:
            np.testing.assert_allclose(np.asarray(image), reference - 0.5 * current)
            assert "A - B*0.50" in image.tag_v2[270]
        assert any(
            tab.folder_files_list.item(row).data(Qt.UserRole) == str(tmp_path / "difference.tiff")
            for row in range(tab.folder_files_list.count())
        )

        # Browse returns to hold-to-compare and clears the calculation.
        select_exploration_task(tab, "browse")
        assert tab.image_viewer.source_array is reference

        incompatible = np.ones((3, 4), dtype=float)
        incompatible_path = str(tmp_path / "c-incompatible.tif")
        (tmp_path / "c-incompatible.tif").touch()
        tab.session_manager.add_image(incompatible, incompatible_path)
        tab._refresh_folder_browser(force=True)
        tab.folder_files_list.setCurrentRow(2)
        select_exploration_task(tab, "difference")
        assert tab.image_viewer.source_array is incompatible
        assert "matching two-dimensional shapes" in tab.parent_app.last_status
        assert tab.image_viewer._colormap_name == shared_cmap

        for index in range(6):
            tab.session_manager.add_image(
                np.full((4, 4), index, dtype=float),
                f"extra-{index}.tif",
            )
        assert tab.session_manager.get_pinned_image()["data"] is reference

        select_exploration_task(tab, "browse")
        other_folder = tmp_path / "other-folder"
        other_folder.mkdir()
        tab.folder_path_input.setText(str(other_folder))
        tab._refresh_folder_browser(force=True)
        pinned_row = next(
            row
            for row in range(tab.folder_files_list.count())
            if tab.folder_files_list.item(row).data(Qt.UserRole) == reference_path
        )
        pinned_item = tab.folder_files_list.item(pinned_row)
        assert tab.session_manager.get_pinned_image()["data"] is reference
        rect = tab.folder_files_list.visualItemRect(pinned_item)
        QTest.mouseClick(
            tab.folder_files_list.viewport(),
            Qt.LeftButton,
            pos=rect.topLeft() + QPointF(10, rect.height() / 2).toPoint(),
        )
        assert tab.session_manager.collection.pinned_path is None
    finally:
        tab.close()


def test_cross_tab_image_and_display_settings_follow_shared_state(qapp):
    from main import SciAnaApp
    from tabs.calibration_tab import CalibrationApp

    app = SciAnaApp()
    source = DummyImageTab()
    calibration_tab = CalibrationApp(app)
    other_tab = CalibrationApp(app)
    try:
        app.add_tab(source, "Source")
        app.add_tab(calibration_tab, "Calibration")
        app.add_tab(other_tab, "Other")
        app.tab_widget.setCurrentWidget(source)

        image = np.arange(5 * 7, dtype=float).reshape(5, 7)
        app.publish_shared_image(image, source_tab=source)

        assert calibration_tab.image_data is image
        assert calibration_tab.image_viewer.source_array is None

        app.tab_widget.setCurrentWidget(calibration_tab)

        assert calibration_tab.image_viewer.source_array is image
        assert calibration_tab.image_viewer.display_array is image

        app.tab_widget.setCurrentWidget(source)
        image_b = np.full((5, 7), 2.0, dtype=float)
        app.publish_shared_image(image_b, source_tab=source)
        assert calibration_tab.image_viewer.source_array is image

        app.tab_widget.setCurrentWidget(calibration_tab)

        assert calibration_tab.image_data is image_b
        assert calibration_tab.image_viewer.source_array is image_b
        calibration_tab.update_display_settings(vmin=3.0, vmax=123.0, cmap="viridis")
        assert app.display_settings["vmin"] == 3.0
        assert app.display_settings["vmax"] == 123.0
        assert app.display_settings["cmap"] == "viridis"
        other_tab.sync_display_controls()
        assert other_tab.vmin_input.text() == "3.0"
        assert other_tab.vmax_input.text() == "123.0"
        assert other_tab.cmap_selector.currentText() == "viridis"
    finally:
        app.close()


class DummyImageTab(QWidget):
    def __init__(self):
        super().__init__()
        self.image_data = None

    def update_plot(self):
        pass
