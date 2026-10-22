"""Display-only data isolation and the image browsing workflow."""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QListWidgetItem, QWidget

from sciview.interfaces.stable_qt.widgets.image_annotations import ImageAnnotations
from sciview.interfaces.stable_qt.widgets.image_viewer import ImagePointerEvent, ImageViewer
from sciview.interfaces.theme.app_style import AppStyle
from tabs.image_browser_tab import ImageBrowserApp


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    AppStyle.apply_bundled_fonts(app)
    return app


@pytest.fixture
def canvas(qapp):
    host = QWidget()
    layout = QHBoxLayout(host)
    viewer = ImageViewer()
    viewer.set_image(np.arange(600, dtype=float).reshape(20, 30))
    marks = ImageAnnotations(viewer)
    layout.addWidget(viewer, 1)
    host.resize(1100, 700)
    host.show()
    qapp.processEvents()
    marks.button.click()
    yield viewer, marks
    marks.undo_stack.clear()
    host.close()
    host.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def pointer(x, y, button=Qt.LeftButton, *, inside=True):
    return ImagePointerEvent(x, y, button, Qt.NoModifier, inside, True)


def test_annotations_do_not_change_source_image_or_mask(canvas):
    viewer, marks = canvas
    image = viewer.source_array
    before = image.copy()
    mask = image < 5
    mask_item = viewer.add_mask_overlay("processing-mask", mask)
    mask_before = mask_item.image.copy()
    marks.select_tool("rectangle")
    marks.handle_press(pointer(3, 4))
    marks.handle_release(pointer(9, 10))
    assert len(marks.items) == 1
    assert viewer.source_array is image
    np.testing.assert_array_equal(image, before)
    np.testing.assert_array_equal(mask_item.image, mask_before)


def test_browser_keeps_drawing_across_playback_frames_without_publishing_marks(qapp, monkeypatch):
    published = []
    parent = SimpleNamespace(
        calibration=None,
        image_data=None,
        show_status=lambda _message: None,
        report_error=lambda *args, **kwargs: pytest.fail(str(args)),
        publish_shared_image=lambda image, **kwargs: published.append((image, kwargs)),
        publish_shared_mask=lambda *args, **kwargs: pytest.fail("Annotations published a mask"),
    )
    monkeypatch.setattr(ImageBrowserApp, "_setup_parent_sync", lambda self: None)
    browser = ImageBrowserApp(parent)
    browser.scianalysis_available = False
    browser.resize(1280, 800)
    browser.show()
    qapp.processEvents()
    image = np.arange(600, dtype=float).reshape(20, 30)
    replacement = image[:12, :18] + 100
    try:
        browser.session_manager.add_image(image, "first.tif")
        browser.session_manager.add_image(replacement, "second.tif")
        for filename in ("first.tif", "second.tif"):
            row = QListWidgetItem(filename)
            row.setData(Qt.UserRole, filename)
            browser.folder_files_list.addItem(row)
        browser._folder_browser_paths = ["first.tif", "second.tif"]
        browser.folder_files_list.setCurrentRow(0)
        marks = browser.annotations
        browser.folder_play_button.click()
        marks.select_tool("polygon")
        assert browser.folder_play_timer.isActive()
        marks.handle_press(pointer(3, 4))
        marks.handle_press(pointer(9, 10))
        browser.folder_play_timer.timeout.emit()
        qapp.processEvents()
        assert browser.folder_play_timer.isActive()
        assert not marks.items
        marks.handle_press(pointer(12, 4))
        assert marks.finish_polygon()
        item = marks.items[0]
        assert marks.items == [item]
        assert browser.image_viewer.source_array is replacement
        assert browser._sync_to_parent(show_status=False)
        assert published[-1][0] is replacement
        assert "annotations" not in published[-1][1]
        assert "annotations" not in browser.get_session_state()
        np.testing.assert_array_equal(image, np.arange(600).reshape(20, 30))
        np.testing.assert_array_equal(replacement, image[:12, :18] + 100)
        browser.session_manager.clear_session()
        assert not marks.layer.isVisible()
        assert marks.items == [item]
    finally:
        browser.folder_refresh_timer.stop()
        browser.folder_play_timer.stop()
        marks.undo_stack.clear()
        browser.close()
        browser.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
