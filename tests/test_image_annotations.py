"""Consequential annotation interactions and separation from scientific data."""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QToolButton, QWidget

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


@pytest.mark.parametrize("tool", ImageAnnotations.TOOLS)
def test_annotation_tools_render_without_changing_image_or_mask(canvas, tool, tmp_path):
    viewer, marks = canvas
    image = viewer.source_array
    before = image.copy()
    mask = image < 5
    mask_item = viewer.add_mask_overlay("processing-mask", mask)
    mask_before = mask_item.image.copy()
    marks.tool_actions[tool].trigger()
    marks.handle_press(pointer(3, 4))
    if tool == "text":
        QTest.keyClicks(marks._text_editor, "<peak & label>")
        QTest.keyClick(marks._text_editor, Qt.Key_Return)
    marks.handle_move(pointer(9, 10, Qt.NoButton))
    marks.handle_release(pointer(9, 10))
    if tool == "polygon":
        marks.handle_press(pointer(9, 10))
        marks.handle_double_click(pointer(12, 4))
    assert len(marks.items) == 1
    assert marks.items[0].parentItem() is marks.layer
    assert marks.layer.opacity() == pytest.approx(0.6)
    assert viewer.source_array is image
    np.testing.assert_array_equal(image, before)
    np.testing.assert_array_equal(mask_item.image, mask_before)
    if tool == "text":
        assert marks.items[0].toPlainText() == "<peak & label>"
    QApplication.processEvents()
    output = tmp_path / f"{tool}.png"
    viewer.export_rendered_view(str(output))
    assert output.stat().st_size > 0
    assert viewer.copy_rendered_view_to_clipboard()
    copied = QApplication.clipboard().pixmap().toImage()
    marks.show_marks.setChecked(False)
    hidden = tmp_path / f"{tool}-hidden.png"
    viewer.export_rendered_view(str(hidden))
    assert output.read_bytes() != hidden.read_bytes()
    assert viewer.copy_rendered_view_to_clipboard()
    assert copied != QApplication.clipboard().pixmap().toImage()


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
    marks.opacity.setValue(35)
    assert marks.layer.opacity() == pytest.approx(0.35)
    marks.show_marks.setChecked(False)
    assert not marks.layer.isVisible()
    assert marks.tools.isVisible()
    marks.handle_press(pointer(3, 4))
    marks.handle_release(pointer(9, 10))
    assert marks.items == [item]
    assert marks.button.isEnabled()
    marks.show_marks.setChecked(True)
    for shape in ((5, 8), (20, 30)):
        viewer.set_image(np.zeros(shape))
        marks.refresh_image()
        assert marks.items == [item]
        assert item.path() == original_path
        assert marks.layer.rect().width() == shape[1]
        assert marks.layer.rect().height() == shape[0]
        viewer.reset_view()
        assert viewer.get_view_range()[0][0] <= 0
        assert viewer.get_view_range()[0][1] >= shape[1]
    viewer.clear_image()
    marks.refresh_image()
    assert not marks.layer.isVisible()
    assert not marks.button.isEnabled()
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
    assert marks._preview is None
    assert not viewer._interaction_locked
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


def test_toolbar_reuses_tool_and_pan_zoom_exit_without_extra_toggle(canvas):
    viewer, marks = canvas
    rectangle = next(button for button in marks.tools.findChildren(QToolButton)
                     if button.defaultAction() is marks.tool_actions["rectangle"])
    rectangle.click()
    assert marks.tools.isVisible()
    assert marks.tool_actions["rectangle"].isChecked()
    marks.handle_press(pointer(3, 4))
    assert viewer._pan_button.isEnabled()
    viewer._pan_button.click()
    assert not marks.button.isChecked()
    assert not marks.tools.isVisible()
    assert marks._preview is None
    assert not viewer._interaction_locked
    QTest.mouseClick(marks.button, Qt.LeftButton, pos=QPoint(5, marks.button.height() // 2))
    assert marks.button.isChecked()
    assert marks.tools.isVisible()
    assert marks.tool_actions["rectangle"].isChecked()
    marks.handle_press(pointer(3, 4))
    marks.handle_release(pointer(9, 10))
    assert len(marks.items) == 1
    viewer._zoom_button.click()
    assert not marks.button.isChecked()
    assert not viewer._interaction_locked
    marks.show_marks.setChecked(False)
    marks.tool_actions["rectangle"].trigger()
    assert marks.show_marks.isChecked()
    assert marks.layer.isVisible()
    marks.button.click()
    assert not marks.tools.isVisible()
    assert marks.layer.isVisible()
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
    assert marks._text_editor is None
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
