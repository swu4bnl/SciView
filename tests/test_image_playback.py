import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt, QTimer
from PyQt5.QtGui import QMouseEvent
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
