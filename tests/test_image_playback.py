import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt, QTimer
from PyQt5.QtGui import QImage, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QWidget

from sciview.interfaces.theme.app_style import AppStyle
from sciview.interfaces.stable_qt.widgets.image_viewer import ImagePointerEvent
from tabs.image_browser_tab import ImageBrowserApp, ImageLoadWorker
from test_image_viewer import DummyParentApp, select_exploration_task


@pytest.fixture
def browser():
    app = QApplication.instance() or QApplication([])
    AppStyle.apply_bundled_fonts(app)
    parent = DummyParentApp()
    parent._workspace_root = Path(__file__).resolve().parents[1]
    tab = ImageBrowserApp(parent)
    tab.resize(1100, 700)
    tab.show()
    tab.folder_auto_refresh_button.setChecked(False)
    yield tab, app
    tab.close()


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def read_editor_value(page, script):
    value = []
    page.runJavaScript(script, value.append)
    wait_until(lambda: bool(value))
    return value[0]


def click_row(tab, row, modifiers=Qt.NoModifier, offset=100):
    """Click away from the leading pin icon, so the row selects rather than pins."""
    rect = tab.folder_files_list.visualItemRect(tab.folder_files_list.item(row))
    QTest.mouseClick(
        tab.folder_files_list.viewport(), Qt.LeftButton, modifiers,
        QPoint(rect.left() + offset, rect.center().y()),
    )


def add_files(tab, tmp_path, count):
    paths = [tmp_path / f"{index}.tif" for index in range(count)]
    tab.is_batch_loading = True
    for index, path in enumerate(paths):
        path.touch()
        tab.session_manager.add_image(np.full((4, 4), index, dtype=float), str(path))
    tab.is_batch_loading = False
    tab.folder_path_input.setText(str(tmp_path))
    tab._refresh_folder_browser(force=True)
    return paths


def test_multiselection_selection_order_tracks_clicks_and_folder_changes(browser, tmp_path):
    tab, app = browser
    paths = add_files(tab, tmp_path, 5)
    (tmp_path / "subfolder").mkdir()
    tab._refresh_folder_browser(force=True)
    app.processEvents()
    # Row 0 is the subfolder; file rows start at 1, so row (1 + index) is paths[index].

    click_row(tab, 1)
    click_row(tab, 3, Qt.ControlModifier, offset=10)
    selected = (str(paths[0]), str(paths[2]))
    assert tab.session_manager.collection.selected_paths == selected
    assert tab.session_manager.collection.pinned_path is None
    assert tab.folder_timeline.maximum() == 1

    click_row(tab, 1)
    click_row(tab, 3, Qt.ShiftModifier)
    baseline = tuple(str(p) for p in paths[0:3])
    assert tab.session_manager.collection.selected_paths == baseline

    # Native rubber-band selection, without a file-drag operation taking over.
    viewport = tab.folder_files_list.viewport()
    start = QPoint(viewport.width() - 5, viewport.height() - 5)
    target = tab.folder_files_list.visualItemRect(tab.folder_files_list.item(1)).center()
    QTest.mousePress(viewport, Qt.LeftButton, pos=start)
    QApplication.sendEvent(
        viewport,
        QMouseEvent(QEvent.MouseMove, QPointF(target), Qt.NoButton, Qt.LeftButton, Qt.NoModifier),
    )
    QTest.mouseRelease(viewport, Qt.LeftButton, pos=target)
    assert len(tab.session_manager.collection.selected_paths) >= 2
    assert tab.session_manager.collection.pinned_path is None

    click_row(tab, 1)
    click_row(tab, 3, Qt.ShiftModifier)
    assert tab.session_manager.collection.selected_paths == baseline

    (tmp_path / "new.tif").touch()
    tab._auto_refresh_folder_browser()
    assert tab.session_manager.collection.selected_paths == baseline

    tab.folder_sort_combo.setCurrentIndex(1)  # Descending display order.
    assert tab.session_manager.collection.selected_paths == tuple(reversed(baseline))
    tab.folder_sort_combo.setCurrentIndex(0)
    assert tab.session_manager.collection.selected_paths == baseline

    paths[2].unlink()
    tab._auto_refresh_folder_browser()
    assert tab.session_manager.collection.selected_paths == (str(paths[0]), str(paths[1]))

    paths[1].unlink()
    tab._auto_refresh_folder_browser()
    assert tab.session_manager.collection.selected_paths == (str(paths[0]),)
    assert len(tab._folder_sequence_paths()) > 1  # Single selection falls back to the folder.


def test_keyboard_navigation_moves_through_selection_and_pauses_playback(browser, tmp_path):
    tab, app = browser
    paths = add_files(tab, tmp_path, 5)
    app.processEvents()

    click_row(tab, 0)
    click_row(tab, 2, Qt.ControlModifier, offset=10)
    selected = (str(paths[0]), str(paths[2]))

    QTest.keyClick(tab.folder_timeline, Qt.Key_Up)
    assert tab.session_manager.collection.current_reference.path == selected[0]
    assert tab.session_manager.collection.selected_paths == selected

    for key, expected in (
        (Qt.Key_Up, selected[0]),
        (Qt.Key_Down, selected[1]),
        (Qt.Key_Down, selected[1]),
        (Qt.Key_Up, selected[0]),
    ):
        QTest.keyClick(tab.folder_files_list, key)
        assert tab.session_manager.collection.current_reference.path == expected
        assert tab.session_manager.collection.selected_paths == selected
        assert len(tab.folder_files_list.selectedItems()) == 2

    tab.folder_play_button.click()
    assert tab.folder_play_timer.isActive()
    QTest.keyClick(tab.folder_files_list, Qt.Key_Down)
    assert not tab.folder_play_timer.isActive()
    assert tab.session_manager.collection.current_reference.path == selected[1]


def test_playback_transport_advances_speed_and_loops(browser, tmp_path):
    tab, app = browser
    paths = add_files(tab, tmp_path, 3)
    app.processEvents()
    click_row(tab, 0)
    click_row(tab, 2, Qt.ControlModifier, offset=10)
    selected = (str(paths[0]), str(paths[2]))
    assert tab.session_manager.collection.selected_paths == selected

    tab.folder_play_button.click()
    interval = tab.folder_play_timer.interval()
    tab.folder_playback_speed_button.click()
    assert tab.folder_play_timer.interval() != interval

    tab._advance_folder_playback()
    assert tab.session_manager.collection.current_reference.path == selected[1]
    tab._advance_folder_playback()
    assert not tab.folder_play_timer.isActive()  # Reached the end without looping.

    tab.folder_loop_button.setChecked(True)
    tab.folder_play_button.click()
    tab._advance_folder_playback()
    assert tab.session_manager.collection.current_reference.path == selected[0]

    # Disable looping so the real QTimer below settles instead of cycling forever.
    tab.folder_loop_button.setChecked(False)
    tab.folder_play_timer.setInterval(5)
    wait_until(lambda: not tab.folder_play_timer.isActive())
    assert tab.session_manager.collection.current_reference.path == selected[1]

    tab._seek_folder_sequence(0)
    tab.folder_play_button.click()
    paths[2].unlink()
    tab._auto_refresh_folder_browser()
    assert not tab.folder_play_timer.isActive()
    assert tab.session_manager.collection.selected_paths == (str(paths[0]),)


def test_lazy_playback_coalesces_requests_reuses_cache_and_reports_errors(browser, tmp_path, monkeypatch):
    tab, _ = browser
    paths = [tmp_path / f"{index}.tif" for index in range(4)]
    for path in paths:
        path.touch()
    started = threading.Event()
    release = threading.Event()
    reads = []
    ui_thread = threading.get_ident()
    tab.session_manager.cache_manager.cache_limit = 2

    def load(_worker, path):
        assert threading.get_ident() != ui_thread
        index = paths.index(Path(path))
        reads.append(index)
        if index == 0 and not release.is_set():
            started.set()
            assert release.wait(5)
        if index == 3:
            raise OSError("Unreadable test image")
        return np.full((4, 4), index, dtype=float)

    monkeypatch.setattr(ImageLoadWorker, "_load_image_file", load)
    tab.folder_path_input.setText(str(tmp_path))
    tab._refresh_folder_browser(force=True)
    try:
        tab.folder_files_list.setCurrentRow(0)
        wait_until(started.is_set)
        tab.folder_play_button.click()
        tab._advance_folder_playback()
        assert tab.session_manager.collection.current_reference.path == str(paths[0])
        tab.folder_timeline.setValue(1)
        tab.folder_timeline.setValue(2)
        assert not tab.folder_play_timer.isActive()
        release.set()
        wait_until(lambda: tab._browser_load_worker is None)
        assert reads == [0, 2]
        np.testing.assert_array_equal(tab.image_viewer.source_array, np.full((4, 4), 2))
        tab.folder_timeline.setValue(0)
        np.testing.assert_array_equal(tab.image_viewer.source_array, np.zeros((4, 4)))
        assert reads == [0, 2]
        tab.folder_timeline.setValue(1)
        assert not tab.image_viewer.isEnabled()
        wait_until(lambda: tab._browser_load_worker is None)
        assert tab.image_viewer.isEnabled()
        assert len(tab.session_manager.cache_manager.data_cache) == 2
        tab.folder_timeline.setValue(2)
        wait_until(lambda: tab._browser_load_worker is None)
        assert reads == [0, 2, 1, 2]  # Frame 2 was evicted and reloaded on demand.
        tab.folder_play_button.click()
        tab._advance_folder_playback()
        wait_until(lambda: tab._browser_load_worker is None)
        assert not tab.folder_play_timer.isActive()
        assert "Unreadable test image" in tab.parent_app.last_status
        assert reads == [0, 2, 1, 2, 3]
    finally:
        release.set()


def test_shutdown_keeps_inflight_reads_alive_without_blocking_ui(tmp_path, monkeypatch):
    from main import SciAnaApp
    from sciview.session import session_cache

    app = QApplication.instance() or QApplication([])
    AppStyle.apply_bundled_fonts(app)
    monkeypatch.setattr(SciAnaApp, "_setup_resource_monitor", lambda self: None)
    monkeypatch.setattr(session_cache, "clear_scratch", lambda: None)
    saved = []
    monkeypatch.setattr(SciAnaApp, "save_session_state", lambda self: saved.append(True))
    window = SciAnaApp()
    tab = ImageBrowserApp(window)
    tab.folder_auto_refresh_button.setChecked(False)
    window.add_tab(tab, "Images", icon_key="image_browser")
    window.show()
    started = threading.Event()
    release = threading.Event()

    def load(_worker, _path):
        started.set()
        assert release.wait(5)
        return np.ones((4, 4))

    monkeypatch.setattr(ImageLoadWorker, "_load_image_file", load)
    path = tmp_path / "slow.tif"
    path.touch()
    tab.folder_path_input.setText(str(tmp_path))
    tab._refresh_folder_browser(force=True)
    tab.folder_files_list.setCurrentRow(0)
    wait_until(started.is_set)
    worker = tab._browser_load_worker
    finished = []
    worker.finished.connect(lambda: finished.append(True))
    watchdog = threading.Timer(2, release.set)
    watchdog.start()
    try:
        assert not window.close()
        assert not release.is_set()
        assert window.isVisible()
        assert not saved
        assert worker.parent() is app
        # Replacing/deleting the tab must not destroy its still-running thread.
        window.tab_widget.removeTab(0)
        window.tab_widget.insertTab(0, QWidget(), "Replacement")
        tab.deleteLater()
        QCoreApplication.sendPostedEvents(tab, QEvent.DeferredDelete)
        assert worker.isRunning()
        release.set()
        wait_until(lambda: bool(finished) and not window.isVisible())
        assert saved == [True]
    finally:
        watchdog.cancel()
        release.set()
        wait_until(lambda: bool(finished))
        window.close()


def test_pinned_playback_preserves_calculation_selection_and_rejects_incompatible_frames(browser, tmp_path):
    tab, _ = browser
    arrays = [np.full((4, 4), value, dtype=float) for value in (10, 2, 4)]
    paths = [tmp_path / f"{index}.tif" for index in range(3)]
    tab.is_batch_loading = True
    for path, array in zip(paths, arrays):
        path.touch()
        tab.session_manager.add_image(array, str(path))
    tab.is_batch_loading = False
    tab.folder_path_input.setText(str(tmp_path))
    tab._refresh_folder_browser(force=True)
    tab.folder_files_list.setCurrentRow(0)
    tab._toggle_selected_pinned_image()
    tab.folder_files_list.setCurrentRow(1)
    assert tab.folder_files_list.item(0).data(Qt.UserRole + 2)
    assert not tab.folder_files_list.item(1).data(Qt.UserRole + 2)

    tab.folder_files_list.item(2).setSelected(True)
    select_exploration_task(tab, "difference")
    tab.comparison_parameter_slider.setValue(50)
    selected = tab.session_manager.collection.selected_paths
    np.testing.assert_array_equal(tab.image_viewer.source_array, arrays[0] - arrays[1] * 0.5)
    assert tab.folder_files_list.item(1).data(Qt.UserRole + 2)

    tab.folder_play_button.click()
    tab._advance_folder_playback()
    tab.folder_play_button.click()
    np.testing.assert_array_equal(tab.image_viewer.source_array, arrays[0] - arrays[2] * 0.5)
    assert tab.folder_files_list.item(2).data(Qt.UserRole + 2)
    assert not tab.folder_files_list.item(1).data(Qt.UserRole + 2)
    assert tab.session_manager.collection.selected_paths == selected
    assert tab.session_manager.collection.pinned_path == str(paths[0])

    tab.folder_play_button.click()
    tab.comparison_parameter_slider.setValue(60)
    assert not tab.folder_play_timer.isActive()
    np.testing.assert_array_equal(tab.image_viewer.source_array, arrays[0] - arrays[2] * 0.6)
    assert tab.session_manager.collection.selected_paths == selected
    tab.comparison_parameter_slider.setValue(50)

    tab.session_manager.add_image(np.ones((3, 4)), str(tmp_path / "bad.tif"))
    (tmp_path / "bad.tif").touch()
    tab._refresh_folder_browser(force=True)
    tab.folder_files_list.item(3).setSelected(True)
    tab._seek_folder_sequence(1)
    tab.folder_play_button.click()
    previous = tab.image_viewer.source_array
    tab._advance_folder_playback()
    assert not tab.folder_play_timer.isActive()
    assert tab.image_viewer.source_array is previous
    assert "matching two-dimensional shapes" in tab.parent_app.last_status


def test_file_hold_restores_flicker_after_playback_and_preserves_multiselection(browser, tmp_path):
    tab, app = browser
    arrays = [np.full((4, 4), value, dtype=float) for value in (10, 2, 4)]
    tab.is_batch_loading = True
    for index, array in enumerate(arrays):
        path = tmp_path / f"{index}.tif"
        path.touch()
        tab.session_manager.add_image(array, str(path))
    tab.is_batch_loading = False
    tab.folder_path_input.setText(str(tmp_path))
    tab._refresh_folder_browser(force=True)
    tab.folder_files_list.setCurrentRow(0)
    tab._toggle_selected_pinned_image()
    tab.folder_files_list.setCurrentRow(1)
    tab.folder_files_list.item(2).setSelected(True)
    assert tab.image_viewer.source_array is arrays[0]
    selected = tab.session_manager.collection.selected_paths
    tab._seek_folder_sequence(0)
    assert tab.image_viewer.source_array is arrays[1]
    tab.folder_play_button.click()
    tab.folder_play_button.click()
    assert tab.image_viewer.source_array is arrays[1]
    QTest.keyPress(tab.folder_files_list, Qt.Key_Space)
    assert tab.image_viewer.source_array is arrays[1]
    QTest.keyRelease(tab.folder_files_list, Qt.Key_Space)
    assert tab.image_viewer.source_array is arrays[0]
    assert tab.session_manager.collection.selected_paths == selected

    tab.folder_play_button.click()
    app.processEvents()
    rect = tab.folder_files_list.visualItemRect(tab.folder_files_list.item(2))
    position = QPoint(rect.left() + 100, rect.center().y())
    QTest.mousePress(tab.folder_files_list.viewport(), Qt.LeftButton, pos=position)
    assert not tab.folder_play_timer.isActive()
    assert tab.image_viewer.source_array is arrays[2]
    QTest.mouseRelease(tab.folder_files_list.viewport(), Qt.LeftButton, pos=position)
    assert tab.image_viewer.source_array is arrays[0]
    assert tab.folder_files_list.currentRow() == 2


def test_annotations_survive_playback_without_changing_images_masks_or_exports(browser, tmp_path):
    tab, app = browser
    published = []
    tab.parent_app = SimpleNamespace(
        calibration=None,
        image_data=None,
        show_status=lambda _message: None,
        publish_shared_image=lambda image, **kwargs: published.append((image, kwargs)),
        publish_shared_mask=lambda *args, **kwargs: pytest.fail("Annotations published a mask"),
    )
    tab.scianalysis_available = False
    image = np.arange(600, dtype=float).reshape(20, 30)
    replacement = image[:12, :18] + 100
    for filename, array in (("first.tif", image), ("second.tif", replacement)):
        path = tmp_path / filename
        path.touch()
        tab.session_manager.add_image(array, str(path))
    tab.folder_path_input.setText(str(tmp_path))
    tab._refresh_folder_browser(force=True)
    tab.folder_files_list.setCurrentRow(0)
    marks = tab.annotations
    mask_item = tab.image_viewer.add_mask_overlay("processing-mask", image < 5)
    mask_before = mask_item.image.copy()

    def pointer(x, y):
        return ImagePointerEvent(x, y, Qt.LeftButton, Qt.NoModifier, True, True)

    try:
        marks.select_tool("rectangle")
        marks.handle_press(pointer(3, 4))
        marks.handle_release(pointer(9, 10))
        assert len(marks.items) == 1
        np.testing.assert_array_equal(mask_item.image, mask_before)
        tab.folder_play_button.click()
        marks.select_tool("polygon")
        marks.handle_press(pointer(3, 4))
        marks.handle_press(pointer(9, 10))
        tab.folder_play_timer.timeout.emit()
        app.processEvents()
        assert tab.folder_play_timer.isActive()
        assert len(marks.items) == 1
        marks.handle_press(pointer(12, 4))
        assert marks.finish_polygon()
        items = list(marks.items)
        assert len(items) == 2
        assert tab.image_viewer.source_array is replacement
        assert tab._sync_to_parent(show_status=False)
        assert published[-1][0] is replacement
        assert "annotations" not in published[-1][1]
        assert "annotations" not in tab.get_session_state()
        np.testing.assert_array_equal(image, np.arange(600).reshape(20, 30))
        np.testing.assert_array_equal(replacement, image[:12, :18] + 100)
        tab.session_manager.clear_session()
        assert not marks.layer.isVisible()
        assert marks.items == items
    finally:
        tab.folder_play_timer.stop()
        marks.undo_stack.clear()


def test_selected_images_to_waterfall_preserves_context_and_updates_from_settings(tmp_path, monkeypatch):
    from PIL import Image

    import sciview.processing.waterfall as waterfall
    from main import SciAnaApp
    from sciview.processing.reduction import ReductionBackend, ReductionResult
    from sciview.session import session_cache
    from tabs.reduction_tab import ReductionTab
    from tabs.results_tab import ResultsTab

    app = QApplication.instance() or QApplication([])
    AppStyle.apply_bundled_fonts(app)
    monkeypatch.setattr(SciAnaApp, "_setup_resource_monitor", lambda self: None)
    monkeypatch.setattr(SciAnaApp, "save_session_state", lambda self: None)
    monkeypatch.setattr(session_cache, "clear_scratch", lambda: None)
    window = SciAnaApp()
    browser = ImageBrowserApp(window)
    browser.folder_auto_refresh_button.setChecked(False)
    window.add_tab(browser, "Browser", icon_key="image_browser")
    calibration_tab = QWidget()
    window.add_tab(calibration_tab, "Calibration", icon_key="calibration")
    reduction = ReductionTab(window)
    reduction.auto_update_check.setChecked(False)
    window.add_tab(reduction, "Reduction", icon_key="reduction")
    results = ResultsTab(window)
    window.add_tab(results, "Notebook", icon_key="results")
    assert not results.update_button.isVisible()
    assert results.workspace.currentWidget() is results.notebook_workspace
    window.show()
    arrays = [np.full((16, 16), value, dtype=np.float32) for value in (10, 20, 30)]
    paths = [tmp_path / f"sample_{index}.tif" for index in range(3)]
    browser.is_batch_loading = True
    for path, array in zip(paths, arrays):
        Image.fromarray(array).save(path)
        browser.session_manager.add_image(array, str(path))
    browser.is_batch_loading = False
    browser.folder_path_input.setText(str(tmp_path))
    browser._refresh_folder_browser(force=True)
    browser.folder_files_list.setCurrentRow(0)
    browser.folder_files_list.item(2).setSelected(True)
    selected = browser.session_manager.collection.selected_paths
    browser._toggle_selected_pinned_image()
    pinned = browser.session_manager.collection.pinned_reference
    release = threading.Event()
    started = threading.Event()
    calls = []

    class Detector:
        def __init__(self, path):
            with Image.open(path) as image:
                self.data = np.asarray(image)

    monkeypatch.setattr(waterfall, "_load_scianalysis_classes", lambda: (object, Detector, object))

    def reduce_image(_backend, request):
        from sciview.processing.scientific_labels import reduction_axis_labels

        calls.append((request.metadata["source_path"], request.bins_relative, request.calibration.x0))
        if not started.is_set():
            started.set()
            assert release.wait(5)
        return ReductionResult(
            request.operation, np.array([0.1, 0.2]), np.full(2, request.image.mean()),
            *reduction_axis_labels(request.operation), {"source": "scianalysis"},
        )

    monkeypatch.setattr(ReductionBackend, "run", reduce_image)
    try:
        browser.waterfall_button.click()
        assert window.tab_widget.currentWidget() is results
        assert results._worker is None
        results.fix_button.click()
        assert window.tab_widget.currentWidget() is calibration_tab
        calibration = SimpleNamespace(
            width=16, height=16, wavelength_A=1.0, pixel_size_um=172, distance_m=1.0,
            x0=8.0, y0=8.0, clear_maps=lambda: None, get_q_per_pixel=lambda: 0.01,
        )
        window.publish_shared_calibration(calibration)
        window.show_processing_tab("results")
        assert results.update_button.isEnabled()
        results.update_button.click()
        wait_until(started.is_set)
        assert results._worker.isRunning()
        assert not results.update_button.isVisible()
        calibration.x0 = 7
        window.publish_shared_calibration(calibration)
        assert results._settings_changed
        release.set()
        wait_until(lambda: results._worker is None)
        assert [curve.path for curve in results._run.curves] == list(selected)
        assert [call[2] for call in calls] == [8, 8]
        np.testing.assert_array_equal(results._run.curves[1].result.y, [30, 30])
        wait_until(lambda: results.notebook.editor_ready and len(results.notebook.document.objects) == 1)
        assert results.workspace.currentWidget() is results.notebook_workspace
        generated_key = next(iter(results.notebook.document.objects))
        assert results.notebook.document.objects[generated_key].sources == list(selected)
        assert results.notebook.document.objects[generated_key].provenance["calibration"]["beam_x"] == 8
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            "Array.from(document.querySelectorAll('[data-figure-label]')).map(label => label.textContent)",
        ) == ["q (Å⁻¹)", "I(q) (a.u.)"])
        # Exercise the retained native rendering/annotation machinery independently of insertion.
        results._show_workspace_page(results.explorer)
        assert results.update_button.isVisible()
        assert results.curve_appearance.isHidden()
        window.resize(1280, 800)
        hover_position = results.view_box.mapViewToScene(QPointF(0.15, 31))
        results._hover_plot([hover_position])
        assert results._hovered_curve_index == 1
        assert results.curve_list.currentItem() is None
        assert results._items[1].data(Qt.BackgroundRole).style() != Qt.NoBrush
        results._hover_source_item(results._items[0])
        assert results._hovered_curve_index == 0
        assert results.curve_list.currentItem() is None
        results._set_hovered_curve(None)
        assert results.spacing_slider.value() == 100
        np.testing.assert_array_equal(results._lines[1].getData()[1], [31, 31])
        results._tool_buttons["home"].click()
        app.processEvents()
        results._tool_buttons["mark"].click()
        position = results.canvas.mapFromScene(results.view_box.mapViewToScene(QPointF(0.15, 31)))
        QTest.mouseClick(results.canvas.viewport(), Qt.LeftButton, pos=position)
        assert len(results._marks) == 1
        assert results.curve_list.currentItem() is results._items[1]
        assert results.curve_appearance.isVisible()
        assert "I=30" in results._marks[0].label.toPlainText()
        results.spacing_slider.setValue(200)
        np.testing.assert_array_equal(results._marks[0].dot.getData()[1], [32])
        assert "I=30" in results._marks[0].label.toPlainText()
        results.view_box.setRange(xRange=(0.12, 0.18), yRange=(15, 60), padding=0)
        zoomed = results.view_box.viewRange()
        results.spacing_slider.setValue(250)
        results.curve_gain_slider.setValue(150)
        np.testing.assert_allclose(results.view_box.viewRange(), zoomed)
        results.palette.setCurrentText("plasma")
        np.testing.assert_allclose(results.view_box.viewRange(), zoomed)
        item = results._items[1]
        item.setCheckState(Qt.Unchecked)
        assert not results._lines[1].isVisible()
        assert not results._marks[0].dot.isVisible()
        np.testing.assert_array_equal(results._run.curves[1].result.y, [30, 30])
        results.curve_list.setCurrentItem(item)
        results.source_button.click()
        assert window.tab_widget.currentWidget() is browser
        assert browser.session_manager.collection.current_reference.path == str(paths[2])
        assert browser.session_manager.collection.selected_paths == selected
        assert browser.session_manager.collection.pinned_reference == pinned

        window.show_processing_tab("results")
        wait_until(lambda: results.notebook.editor_ready)
        assert read_editor_value(
            results.notebook.page,
            "document.querySelector('#outline-toggle').getAttribute('aria-expanded')",
        ) == "false"
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            "document.querySelector('.milkdown-top-bar [data-format-command=\"bold\"]') !== null",
        ))
        key = generated_key
        results._compose_notebook()
        assert key in results.notebook.document.objects
        assert results.workspace.currentWidget() is results.notebook_workspace
        assert read_editor_value(
            results.notebook.page,
            "document.querySelector('#app-name').textContent",
        ) == "SciView Notebook"
        QTest.qWait(100)
        editor_target = results.notebook.view.focusProxy() or results.notebook.view
        results.notebook.page.runJavaScript(
            "document.querySelector('.milkdown-top-bar [data-format-command=\"bold\"]').closest('button').dispatchEvent("
            "new PointerEvent('pointerdown', {bubbles: true, cancelable: true}))",
        )
        QTest.qWait(50)
        QTest.keyClicks(editor_target, "Peak shifts with temperature.")
        wait_until(lambda: "Peak shifts" in results.notebook.document.markdown)
        assert "**Peak shifts with temperature.**" in results.notebook.snapshot_markdown()
        results.notebook.page.runJavaScript(
            "document.querySelector('.milkdown-top-bar [data-format-command=\"bold\"]').closest('button').dispatchEvent("
            "new PointerEvent('pointerdown', {bubbles: true, cancelable: true}))",
        )
        results.notebook.insert_latest_requested.emit()
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            "document.querySelectorAll('.plot-card').length === 2",
        ))
        second_key = next(
            plot_id for plot_id in results.notebook.document.objects if plot_id != key
        )
        QTest.keyClicks(editor_target, "Interpretation continues.")
        wait_until(lambda: "Interpretation continues" in results.notebook.document.markdown)
        inserted_markdown = results.notebook.snapshot_markdown()
        assert inserted_markdown.index("Peak shifts") < inserted_markdown.index(
            f"sciview:{second_key}"
        ) < inserted_markdown.index("Interpretation continues")
        local_image = (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
            "QVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
        )
        results.notebook.document.markdown += (
            "\n\n## Observations\n\n- [x] Calibrated\n\n| Sample | Temperature |\n| --- | --- |\n| A | 300 K |\n\n"
            "Inline math $I(q) = q^2$.\n\n```python\nprint(intensity.max())\n```\n\n"
            f'![Imported image]({local_image} "Local observation")\n'
        )
        results.notebook._show_document()
        results.notebook.page.runJavaScript("document.querySelector('#outline-toggle').click()")
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            f"document.querySelector('#outline [data-object-id=\"{key}\"]') !== null",
        ))
        results.notebook.page.runJavaScript("sciview.clearSelection()")
        QTest.qWait(100)
        assert results._inline_selected_object is None
        unselected_plot_width = read_editor_value(results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] .plot-surface svg').clientWidth")
        assert not results.source_panel.isVisible()
        results.notebook.page.runJavaScript(
            f"document.querySelector('#outline [data-object-id=\"{key}\"]').click()",
        )
        QTest.qWait(100)
        assert results._inline_selected_object is None
        results.notebook.page.runJavaScript(
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"]').dispatchEvent("
            "new MouseEvent('mousedown', {bubbles: true}))",
        )
        wait_until(lambda: results._inline_selected_object == key)
        assert not results.source_panel.isVisible()
        assert read_editor_value(results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] .plot-surface svg').clientWidth") == unselected_plot_width
        results.notebook.page.runJavaScript(
            f"document.querySelector('#outline [data-object-id=\"{second_key}\"]').click()",
        )
        QTest.qWait(100)
        assert results._inline_selected_object == key
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                card.querySelector('.legend-entry[data-curve-index="1"] button').click();
                return true;
            }})()""",
        )
        wait_until(lambda: results.notebook.document.objects[key].state.selected_index == 1)
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                card.querySelector('[data-plot-action="settings"]').click();
                document.querySelector('.measurement-visibility[data-curve-index="1"] input').click();
                document.querySelector('#close-figure-settings').click();
            }})()""",
        )
        wait_until(lambda: (
            results.notebook.document.objects[key].sources[1]
            not in results.notebook.document.objects[key].state.hidden_sources
        ))
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            f"""document.querySelector(
                '.plot-card[data-object-id="{key}"] .plot-surface svg g[data-curve-index="1"]'
            ) !== null""",
        ))
        results.notebook.page.runJavaScript(
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] "
            "svg g[data-curve-index=\"1\"]').dispatchEvent("
            "new MouseEvent('click', {bubbles: true}))",
        )
        wait_until(lambda: results.curve_list.currentItem() is results._items[1])
        assert not results.curve_appearance.isVisible()
        assert not results.source_panel.isVisible()
        assert read_editor_value(
            results.notebook.page,
            f"""document.querySelector(
                '.plot-card[data-object-id="{key}"] .figure-context-tools'
            ).getBoundingClientRect().height > 0""",
        )
        results.notebook.page.runJavaScript(
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] .plot-surface svg').dispatchEvent("
            "new MouseEvent('click', {bubbles: true}))",
        )
        wait_until(lambda: read_editor_value(results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] .figure-context-tools').hidden"))
        assert read_editor_value(results.notebook.page, "document.querySelector('#figure-settings').hidden")
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                card.querySelector('[data-plot-action="settings"]').click();
                const panel = document.querySelector('#figure-settings');
                const palette = panel.querySelector('[aria-label="Color palette"]');
                const spacing = panel.querySelector('input[type="range"]');
                palette.value = 'cividis';
                palette.dispatchEvent(new Event('change', {{ bubbles: true }}));
                spacing.value = '200';
                spacing.dispatchEvent(new Event('input', {{ bubbles: true }}));
                panel.querySelector('.default-curve-appearance').open = true;
                const defaults = panel.querySelector('[aria-label="Default line style"]');
                defaults.value = 'dot';
                defaults.dispatchEvent(new Event('change', {{bubbles: true}}));
                const defaultWidth = panel.querySelector('[aria-label="Default thickness"]');
                defaultWidth.value = '2.5';
                defaultWidth.dispatchEvent(new Event('input', {{bubbles: true}}));
                card.querySelector('svg g[data-curve-index="1"]').dispatchEvent(new MouseEvent('click', {{bubbles:true}}));
                const tools = card.querySelector('.figure-context-tools');
                const lineStyle = tools.querySelector('select');
                const width = tools.querySelector('input[type="range"][aria-label="Line width"]');
                const scaling = tools.querySelector('input[type="range"][aria-label="Scaling"]');
                const opacity = tools.querySelector('input[type="range"][aria-label="Opacity"]');
                lineStyle.value = 'dash';
                lineStyle.dispatchEvent(new Event('change', {{ bubbles: true }}));
                width.value = '5';
                width.dispatchEvent(new Event('input', {{ bubbles: true }}));
                scaling.value = '1.5';
                scaling.dispatchEvent(new Event('input', {{ bubbles: true }}));
                opacity.value = '.4';
                opacity.dispatchEvent(new Event('input', {{bubbles: true}}));
                return true;
            }})()""",
        )
        wait_until(lambda: (
            results.notebook.document.objects[key].state.palette == "cividis"
            and results.notebook.document.objects[key].state.spacing == 2
            and results._curve_style(1).line_style == "dash"
            and results._curve_style(1).line_width == 5
            and results._curve_style(1).gain == 1.5
            and results._curve_style(1).opacity == .4
            and results.notebook.document.objects[key].state.default_line_width == 2.5
        ))
        assert results._curve_pen(0).widthF() == 2.5
        assert results._curve_pen(0).style() == Qt.DotLine
        assert results._curve_pen(1).color().alphaF() == pytest.approx(.4)
        assert read_editor_value(results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] .plot-surface svg g[data-curve-index=\"1\"] path').getAttribute('stroke-opacity')") == "0.4"
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            f"""document.querySelector(
                '#figure-settings select[aria-label="Color palette"]'
            ).value""",
        ) == "cividis")
        assert not read_editor_value(results.notebook.page, "document.querySelector('#figure-settings').hidden")
        assert read_editor_value(results.notebook.page,
            "document.querySelector('#figure-settings').closest('.plot-card').dataset.objectId") == key
        results.notebook.page.runJavaScript("document.querySelector('#close-figure-settings').click()")
        wait_until(lambda: read_editor_value(results.notebook.page, "document.querySelector('#figure-settings').hidden"))
        assert results._curve_style(1).line_width == 5
        assert results._curve_style(1).gain == 1.5
        results.notebook.page.runJavaScript(
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] "
            ".plot-body').scrollIntoView({block: 'center'})",
        )
        QTest.qWait(100)
        mark_fraction = .65 if results.notebook.document.objects[key].state.marks[0][1] == 0 else .35
        click_point = read_editor_value(
            results.notebook.page,
            f"""(() => {{
                const path = document.querySelector(
                    '.plot-card[data-object-id="{key}"] .plot-surface svg g[data-curve-index="1"] path[data-curve-index]'
                );
                const point = path.getPointAtLength(path.getTotalLength() * {mark_fraction})
                    .matrixTransform(path.getScreenCTM());
                return [point.x, point.y];
            }})()""",
        )
        results.notebook.page.runJavaScript(
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] "
            "[data-plot-action=\"mark\"]').click()",
        )
        QTest.qWait(50)
        QTest.mouseClick(
            editor_target, Qt.LeftButton,
            pos=QPoint(round(click_point[0]), round(click_point[1])),
        )
        wait_until(lambda: len(results.notebook.document.objects[key].state.marks) == 2)
        assert len(results._marks) == 2
        results.notebook.page.runJavaScript(
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] "
            "[data-plot-action=\"undo_mark\"]').click()",
        )
        wait_until(lambda: len(results.notebook.document.objects[key].state.marks) == 1)
        results.notebook.page.runJavaScript(
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] "
            "[data-plot-action=\"pan\"]').click()",
        )
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                card.querySelector('.legend-entry[data-curve-index="1"] button').click();
                card.querySelector('[data-plot-action="settings"]').click();
                document.querySelector('.measurement-visibility[data-curve-index="1"] input').click();
                document.querySelector('#close-figure-settings').click();
            }})()""",
        )
        wait_until(lambda: (
            results.notebook.document.objects[key].sources[1]
            in results.notebook.document.objects[key].state.hidden_sources
        ))
        inline_size = read_editor_value(
            results.notebook.page,
            f"""(() => {{
                const svg = document.querySelector(
                    '.plot-card[data-object-id="{key}"] .plot-surface svg'
                );
                return [svg.clientWidth, svg.clientHeight];
            }})()""",
        )
        assert inline_size[0] > 300 and inline_size[1] >= 180, inline_size
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                const svg = card.querySelector('.plot-surface svg');
                const hit = svg.querySelector(
                    'g[data-curve-index="0"] path[data-curve-index="0"]'
                );
                const point = hit.getPointAtLength(0).matrixTransform(hit.getScreenCTM());
                hit.dispatchEvent(new PointerEvent('pointermove', {{
                    bubbles: true, clientX: point.x, clientY: point.y,
                }}));
                return true;
            }})()""",
        )
        wait_until(lambda: results._hovered_curve_index == 0)
        assert results._items[0].data(Qt.BackgroundRole).style() != Qt.NoBrush
        assert " q " in results.cursor_label.text()
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const handle = document.querySelector(
                    '.plot-card[data-object-id="{key}"] .plot-resize'
                );
                handle.dispatchEvent(new KeyboardEvent('keydown', {{
                    key: 'ArrowLeft', bubbles: true, cancelable: true,
                }}));
                return true;
            }})()""",
        )
        wait_until(lambda: results.notebook.document.objects[key].state.width == 50)
        assert read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"]').style.width",
        ) == "50%"
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const handle = document.querySelector(
                    '.plot-card[data-object-id="{key}"] .plot-resize'
                );
                handle.dispatchEvent(new KeyboardEvent('keydown', {{
                    key: 'ArrowRight', bubbles: true, cancelable: true,
                }}));
                return true;
            }})()""",
        )
        wait_until(lambda: results.notebook.document.objects[key].state.width == 100)
        assert read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"]').style.width",
        ) == "100%"
        read_editor_value(
            results.notebook.page,
            f"""document.querySelector('.plot-card[data-object-id="{key}"] .plot-resize')
                .scrollIntoView({{block: 'nearest'}})""",
        )
        QTest.qWait(400)
        resize_start = read_editor_value(
            results.notebook.page,
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                const handle = card.querySelector('.plot-resize');
                const bounds = handle.getBoundingClientRect();
                return [bounds.x + bounds.width / 2, bounds.y + bounds.height / 2,
                    card.querySelector('.plot-surface').getBoundingClientRect().height];
            }})()""",
        )
        resize_origin = QPoint(round(resize_start[0]), round(resize_start[1]))
        resize_end = resize_origin + QPoint(-35, 25)
        QTest.mousePress(editor_target, Qt.LeftButton, pos=resize_origin)
        QTest.mouseMove(editor_target, resize_end, delay=30)
        QTest.qWait(150)
        QTest.mouseRelease(editor_target, Qt.LeftButton, pos=resize_end)
        wait_until(lambda: (
            results.notebook.document.objects[key].state.width < 100
            and results.notebook.document.objects[key].state.height == round(resize_start[2]) + 25
        ))
        QTest.keyClick(editor_target, Qt.Key_Escape)
        QTest.keyClicks(editor_target, "The reflection changes during heating.")
        wait_until(lambda: "reflection changes" in results.notebook.document.markdown)
        assert f"sciview:{key}" in results.notebook.document.markdown, results.notebook.document.markdown
        results.notebook.bridge.resizePlot(key, 67, 285)
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"]').style.width",
        ) == "67%")
        assert results.notebook.document.objects[key].state.height == 285
        from copy import deepcopy
        previous_state = deepcopy(results.notebook.document.objects[key].state)
        results.notebook.bridge.setPlotControl(key, "line_width", "100")
        assert results.notebook.document.objects[key].state == previous_state
        preview_size = results.notebook.preview_size(key)
        assert preview_size is not None
        inline_image = QImage.fromData(results.notebook.document.objects[key].preview)
        assert not inline_image.isNull()
        results.spacing_slider.setValue(250)
        results.curve_line_style.setCurrentIndex(results.curve_line_style.findData("dash"))
        results.curve_width_slider.setValue(5)
        results.curve_gain_slider.setValue(150)
        np.testing.assert_array_equal(results._lines[1].getData()[1], [47.5, 47.5])
        np.testing.assert_array_equal(results._run.curves[1].result.y, [30, 30])
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                card.querySelector('.plot-title').scrollIntoView({{block: 'center'}});
                const title = card.querySelector('.plot-title');
                title.focus();
                return true;
            }})()""",
        )
        wait_until(lambda: read_editor_value(
            results.notebook.page, "document.activeElement.dataset.figureField",
        ) == "title")
        assert read_editor_value(results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] .figure-context-tools').hidden")
        QTest.keyClick(editor_target, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClicks(editor_target, "Heating series")
        QTest.keyClick(editor_target, Qt.Key_Return)
        wait_until(lambda: results.notebook.document.objects[key].title == "Heating series")
        wait_until(lambda: read_editor_value(results.notebook.page,
            f"document.querySelector('#outline [data-object-id=\"{key}\"]').textContent") == "Heating series")
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                card.querySelector('[data-figure-label="x"]').dispatchEvent(new MouseEvent('click', {{bubbles: true}}));
                return true;
            }})()""",
        )
        wait_until(lambda: read_editor_value(
            results.notebook.page, "document.activeElement.dataset.figureField",
        ) == "x_label")
        assert read_editor_value(results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] .figure-context-tools').hidden")
        QTest.keyClick(editor_target, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClicks(editor_target, "Scattering vector")
        QTest.keyClick(editor_target, Qt.Key_Return)
        wait_until(lambda: results.notebook.document.objects[key].figure.x_label == "Scattering vector")
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                const name = card.querySelector('.legend-entry[data-curve-index="1"] input');
                name.scrollIntoView({{block: 'center'}});
                name.focus();
                return true;
            }})()""",
        )
        wait_until(lambda: read_editor_value(
            results.notebook.page, "document.activeElement.dataset.figureField",
        ) == "legend:1")
        QTest.keyClick(editor_target, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClicks(editor_target, "Heated sample")
        QTest.keyClick(editor_target, Qt.Key_Return)
        wait_until(lambda: results.notebook.document.objects[key].figure.legend_names.get(1) == "Heated sample")
        results.notebook.page.runJavaScript(
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                card.querySelector('.legend-entry[data-curve-index="1"] button').click();
                const number = card.querySelector('input[type="number"][aria-label="Line width"]');
                number.value = '4.25';
                number.dispatchEvent(new Event('input', {{bubbles: true}}));
                return true;
            }})()""",
        )
        wait_until(lambda: results.notebook.document.objects[key].state.curve_styles[1].line_width == 4.25)
        results.curve_width_slider.setValue(4)
        results.curve_width_slider.setValue(5)
        results.notebook.bridge.setFigureText(key, "y_units", "a.u.")
        np.testing.assert_array_equal(results.notebook.document.objects[key].curves[1].y, [30, 30])
        from copy import deepcopy
        from uuid import uuid4
        second_plot = deepcopy(results.notebook.document.objects[key])
        second_plot.id = uuid4().hex
        second_plot.title = "Second waterfall"
        results.notebook.add_object(second_plot)
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            f"document.querySelector('#outline [data-object-id=\"{second_plot.id}\"]') !== null",
        ))
        results.notebook.page.runJavaScript(
            f"""(() => {{
                document.querySelector('.plot-card[data-object-id="{key}"] [data-plot-action="settings"]').click();
                document.querySelector('.plot-card[data-object-id="{second_plot.id}"] [data-plot-action="settings"]').click();
            }})()""",
        )
        wait_until(lambda: read_editor_value(results.notebook.page,
            "document.querySelector('#figure-settings').dataset.objectId") == second_plot.id)
        assert read_editor_value(results.notebook.page,
            "document.querySelector('#figure-settings').closest('.plot-card').dataset.objectId") == second_plot.id
        results.notebook.page.runJavaScript(
            "document.querySelector('.plot-card').dispatchEvent("
            "new MouseEvent('mousedown', {bubbles: true}))",
        )
        wait_until(lambda: results._inline_selected_object == key)
        assert read_editor_value(results.notebook.page, "document.querySelector('#figure-settings').hidden")
        previous_range = results.view_box.viewRange()
        from sciview.processing.plot_rendering import figure_preview_png
        second_preview = QImage.fromData(figure_preview_png(
            results.notebook.document.objects[second_plot.id], (320, 180),
        ))
        assert (second_preview.width(), second_preview.height()) == (320, 180)
        assert results._active_object == key
        assert results._run.request.paths == selected
        assert results.curve_list.currentItem().data(Qt.UserRole) == 1
        np.testing.assert_allclose(results.view_box.viewRange(), previous_range)
        notebook_path = tmp_path / "findings.md"
        import sciview.interfaces.stable_qt.widgets.notebook_editor as notebook_editor
        monkeypatch.setattr(notebook_editor, "choose_path", lambda *_args, **_kwargs: (str(notebook_path), ""))
        results.notebook.page.runJavaScript("document.querySelector('#save-button').click()")
        wait_until(lambda: results.notebook.document.path == notebook_path.resolve())
        assert not results.notebook.dirty
        assert results._plot_state() == results.notebook.document.objects[key].state
        original_calls = len(calls)
        from PyQt5.QtWidgets import QMessageBox
        restart_state = window._collect_session_state()
        assert restart_state["results"]["notebook_path"] == str(notebook_path.resolve())
        restarted_window = SciAnaApp()
        restarted_results = ResultsTab(restarted_window)
        restarted_window.add_tab(restarted_results, "Notebook", icon_key="results")
        with monkeypatch.context() as restart_patch:
            restart_patch.setattr(session_cache, "load_session", lambda: restart_state)
            restart_patch.setattr(
                QMessageBox, "warning",
                lambda *_args: pytest.fail("Restoring a clean notebook prompted to save."),
            )
            restarted_window.restore_session_state()
            restarted_window.show()
            wait_until(lambda: restarted_results.notebook.editor_ready and key in restarted_results.notebook.document.objects)
            wait_until(lambda: read_editor_value(restarted_results.notebook.page,
                f"document.querySelector('.plot-card[data-object-id=\"{key}\"] .plot-title').value",
            ) == "Heating series")
            assert not restarted_results.notebook.dirty
            restarted_results.notebook.page.runJavaScript(
                f"document.querySelector('.plot-card[data-object-id=\"{key}\"]').dispatchEvent("
                "new MouseEvent('mousedown', {bubbles: true}))",
            )
            wait_until(lambda: restarted_results._active_object == key)
            restarted_results.notebook.bridge.curveSelected(key, 0)
            QTest.qWait(300)
            assert not restarted_results.notebook.dirty
            assert restarted_results.notebook.confirm_discard()
            assert restarted_results.notebook.document.objects[key].figure.legend_names[1] == "Heated sample"
            assert len(calls) == original_calls
            restarted_window.close()
        with monkeypatch.context() as reopen_patch:
            reopen_patch.setattr(
                QMessageBox, "warning",
                lambda *_args: pytest.fail("A clean, saved notebook prompted before reopening."),
            )
            previous_document = results.notebook.document
            results.notebook.page.runJavaScript("document.querySelector('[data-action=\"open\"]').click()")
            wait_until(lambda: results.notebook.document is not previous_document)
        read_editor_value(results.notebook.page,
            f"""(() => {{
                const card = document.querySelector('.plot-card[data-object-id="{key}"]');
                card.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}));
                card.querySelector('[data-plot-action="expand"]').click();
                return true;
            }})()""",
        )
        wait_until(lambda: results._active_object == key)
        wait_until(lambda: results.notebook.document.objects[key].state.width == 100)
        assert results.workspace.currentWidget() is results.notebook_workspace
        assert read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"]').classList.contains('expanded')",
        )
        assert len(calls) == original_calls
        reopened = results.notebook.snapshot_markdown()
        for content in ("Peak shifts", "[x] Calibrated", "300 K", "$I(q) = q^2$",
                        "```python", "print(intensity.max())", local_image, "Local observation"):
            assert content in reopened
        assert results.spacing_slider.value() == 250
        assert results._curve_style(1).line_style == "dash"
        assert results._curve_style(1).line_width == 5
        assert results._curve_style(1).gain == 1.5
        assert results.curve_gain_slider.value() == 150
        assert results.palette.currentText() == "cividis"
        results.notebook.page.runJavaScript(
            f"document.querySelector('.plot-card[data-object-id=\"{key}\"] "
            "[data-plot-action=\"expand\"]').click()",
        )
        wait_until(lambda: results.notebook.document.objects[key].state.width == 67)
        assert results.notebook.document.objects[key].state.height == 285
        assert not results._lines[1].isVisible()
        assert len(results._marks) == 1
        assert "I=30" in results._marks[0].label.toPlainText()
        np.testing.assert_array_equal(results._run.curves[1].result.y, [30, 30])
        np.testing.assert_allclose(results.view_box.viewRange(), zoomed)
        results._compose_notebook()
        assert results.workspace.currentWidget() is results.notebook_workspace
        assert len(results.notebook.document.objects) == 3
        results.spacing_slider.setValue(260)
        saved = notebook_path.read_bytes()
        with monkeypatch.context() as preview_patch:
            def preview_failure(_plot, _size=None):
                raise RuntimeError("Preview rendering failed")
            preview_patch.setattr(notebook_editor, "figure_preview_png", preview_failure)
            assert not results.notebook.save()
            assert notebook_path.read_bytes() == saved
        results._sync_notebook_plot()
        from PyQt5.QtWidgets import QMessageBox
        with monkeypatch.context() as close_patch:
            close_patch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.Cancel)
            window.close()
            assert window.isVisible()
            assert results.notebook.dirty
        assert results.notebook.save()

        # A new browser selection is not implicitly substituted into Update.
        browser.folder_files_list.item(1).setSelected(True)
        window.show_processing_tab("reduction")
        bins = reduction._operation_param_widgets["circular_average"]["bins_relative"]
        bins.setValue(bins.value() + 0.5)
        window.show_processing_tab("results")
        results.update_button.click()
        wait_until(lambda: results._worker is None)
        assert results._paths == selected
        assert [call[0] for call in calls[-2:]] == list(selected)
        assert all(call[2] == 7 for call in calls[-2:])
        assert not results._settings_changed
        assert not results._marks
        np.testing.assert_array_equal(results._run.curves[0].result.y, [10, 10])
        started.clear()
        release.clear()
        results.update_button.click()
        wait_until(started.is_set)
        with monkeypatch.context() as close_patch:
            close_patch.setattr(ResultsTab, "confirm_close", lambda _self: True)
            window.close()
            assert window.isVisible()
            release.set()
            wait_until(lambda: not window.isVisible())
    finally:
        release.set()
        results._cancel()
        wait_until(lambda: results._worker is None)
        results._closing = True
        window.close()
