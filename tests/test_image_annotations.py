"""Consequential annotation interactions and separation from scientific data."""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QWidget

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


def test_annotation_history_visibility_and_shared_image_coordinates(canvas):
    viewer, marks = canvas
    marks.tool_actions["line"].trigger()
    marks.handle_press(pointer(3, 4))
    marks.handle_release(pointer(25, 15))
    item = marks.items[0]
    original_path = item.path()
    marks._undo()
    assert marks.items == []
    assert item.scene() is None
    marks._redo()
    assert marks.items == [item]
    marks._clear()
    assert marks.items == []
    marks._undo()
    assert marks.items == [item]
    marks.show_marks.setChecked(False)
    assert not marks.layer.isVisible()
    marks.handle_press(pointer(3, 4))
    marks.handle_release(pointer(9, 10))
    assert marks.items == [item]
    marks.show_marks.setChecked(True)
    for shape in ((5, 8), (20, 30)):
        viewer.set_image(np.zeros(shape))
        marks.refresh_image()
        assert marks.items == [item]
        assert item.path() == original_path
    viewer.clear_image()
    marks.refresh_image()
    assert not marks.layer.isVisible()
    viewer.set_image(np.ones((20, 30)))
    marks.refresh_image()
    assert marks.layer.isVisible()
    assert marks.items == [item]


def test_annotation_gestures_cancel_and_release_outside_image(canvas):
    viewer, marks = canvas
    marks.select_tool("rectangle")
    marks.handle_press(pointer(-1, 2, inside=False))
    marks.handle_release(pointer(4, 5))
    assert not marks.items
    marks.handle_press(pointer(3, 4))
    marks.select_tool("line")
    marks.handle_release(pointer(10, 10))
    assert not marks.items
    marks.handle_press(pointer(3, 4))
    marks.handle_release(pointer(100, 100, inside=False))
    assert len(marks.items) == 1
    assert marks.items[0].path().boundingRect().right() == 30
    marks.handle_press(pointer(3, 4))
    marks.handle_press(pointer(3, 4, Qt.RightButton))
    assert len(marks.items) == 1
    marks.select_tool("text")
    marks.handle_press(pointer(3, 4))
    QTest.keyClick(marks._text_editor, Qt.Key_Return)
    assert len(marks.items) == 1


def test_viewport_drawing_and_escape_restore_navigation(canvas, qapp):
    viewer, marks = canvas
    host = viewer.parentWidget()
    host.resize(1100, 700)
    host.show()
    qapp.processEvents()
    marks.tool_actions["rectangle"].trigger()
    viewport = viewer._graphics.viewport()

    def position(x, y):
        scene = viewer._view_box.mapViewToScene(QPoint(x, y))
        return viewer._graphics.mapFromScene(scene)

    QTest.mousePress(viewport, Qt.LeftButton, pos=position(3, 4))
    QTest.mouseMove(viewport, position(9, 10))
    QTest.mouseRelease(viewport, Qt.LeftButton, pos=position(9, 10))
    assert len(marks.items) == 1
    QTest.mousePress(viewport, Qt.LeftButton, pos=position(3, 4))
    QTest.keyClick(viewport, Qt.Key_Escape)
    QTest.mouseRelease(viewport, Qt.LeftButton, pos=position(9, 10))
    assert len(marks.items) == 1
    assert not marks.button.isChecked()
    assert not viewer._pointer_captured
    assert not viewer._interaction_locked


def test_inline_labels_commit_cancel_and_keep_text_undo_local(canvas, qapp):
    viewer, marks = canvas
    marks.tool_actions["text"].trigger()
    marks.handle_press(pointer(3, 4))
    editor = marks._text_editor
    assert editor.isVisible()
    QTest.keyClicks(editor, "Peak 1")
    QTest.keyClick(editor, Qt.Key_Return)
    assert len(marks.items) == 1
    assert marks.items[0].toPlainText() == "Peak 1"
    assert marks._text_editor is None
    marks.handle_press(pointer(9, 10))
    QTest.keyClicks(marks._text_editor, "discard")
    QTest.keyClick(marks._text_editor, Qt.Key_Escape)
    assert len(marks.items) == 1
    assert marks._text_editor is None
    assert not marks.button.isChecked()
    marks.tool_actions["text"].trigger()
    marks.handle_press(pointer(9, 10))
    QTest.keyClicks(marks._text_editor, "typing")
    QTest.keyClick(marks._text_editor, Qt.Key_Z, Qt.ControlModifier)
    assert len(marks.items) == 1
    viewer._pan_button.setFocus()
    qapp.processEvents()
    QTest.keyClick(viewer._pan_button, Qt.Key_Z, Qt.ControlModifier)
    assert not marks.items
    QTest.keyClick(viewer._pan_button, Qt.Key_Y, Qt.ControlModifier)
    assert len(marks.items) == 1


def test_browser_shares_marks_but_publishes_only_original_data(qapp, monkeypatch):
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
    image = np.arange(600, dtype=float).reshape(20, 30)
    replacement = image + 100
    try:
        browser.session_manager.add_image(image, "first.tif")
        marks = browser.annotations
        browser.folder_play_timer.start(10000)
        marks.button.click()
        assert not browser.folder_play_timer.isActive()
        marks.handle_press(pointer(3, 4))
        marks.handle_release(pointer(9, 10))
        item = marks.items[0]
        browser.session_manager.add_image(replacement, "second.tif")
        browser.session_manager.set_current_index(1)
        assert marks.items == [item]
        assert browser.image_viewer.source_array is replacement
        assert browser._sync_to_parent(show_status=False)
        assert published[-1][0] is replacement
        assert "annotations" not in published[-1][1]
        assert "annotations" not in browser.get_session_state()
        np.testing.assert_array_equal(image, np.arange(600).reshape(20, 30))
        np.testing.assert_array_equal(replacement, image + 100)
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
