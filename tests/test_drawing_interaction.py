"""Shared keyboard/gesture contracts across the two drawing editors."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from sciview.interfaces.stable_qt.widgets.image_annotations import ImageAnnotations
from sciview.interfaces.stable_qt.widgets.image_viewer import ImagePointerEvent, ImageViewer
from sciview.interfaces.theme.app_style import AppStyle
from sciview.masking.layers import MaskLayer
from tabs.mask_tab import MaskApp
from test_image_viewer import DummyParentApp


def pointer(x, y):
    return ImagePointerEvent(x, y, Qt.LeftButton, Qt.NoModifier, True, True)


@pytest.fixture
def editors():
    app = QApplication.instance() or QApplication([])
    AppStyle.apply_bundled_fonts(app)
    host = QTabWidget()
    page = QWidget()
    layout = QVBoxLayout(page)
    viewer = ImageViewer()
    viewer.set_image(np.ones((24, 32)))
    marks = ImageAnnotations(viewer)
    layout.addWidget(viewer)
    entry = QLineEdit()
    layout.addWidget(entry)
    host.addTab(page, "Annotations")
    mask = MaskApp(DummyParentApp())
    mask.image_data = np.ones((24, 32))
    mask.update_plot()
    mask.mask_layers.append(MaskLayer(np.zeros((24, 32), dtype=bool)))
    mask._update_layer_list()
    host.addTab(mask, "Mask")
    host.resize(1280, 800)
    host.show()
    marks.button.click()
    app.processEvents()
    yield app, host, viewer, marks, mask, entry
    marks.undo_stack.clear()
    host.close()
    host.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.parametrize("editor", ["annotation", "mask"])
@pytest.mark.parametrize("finish", ["keyboard", "double_click"])
def test_polygon_completion_and_history_commands_are_shared(editors, editor, finish):
    app, host, viewer, marks, mask, _entry = editors
    if editor == "mask":
        host.setCurrentIndex(1)
        viewer = mask.image_viewer
        press = mask.drawing_session.handle_press
        double_click = mask.drawing_session.handle_double_click
        stack = mask.undo_stack
    else:
        press = marks.handle_press
        double_click = marks.handle_double_click
        stack = marks.undo_stack
    app.processEvents()
    viewport = viewer._graphics.viewport()
    viewport.setFocus()
    QTest.keyClick(viewport, Qt.Key_P)
    # Selecting the current tool is idempotent, not a drawing-mode toggle.
    QTest.keyClick(viewport, Qt.Key_P)
    press(pointer(3, 4))
    press(pointer(13, 14))
    if finish == "double_click":
        double_click(pointer(13, 4))
    else:
        press(pointer(13, 4))
        if editor == "mask":
            QTest.keyClick(viewport, Qt.Key_Enter, Qt.KeypadModifier)
        else:
            QTest.keyClick(viewport, Qt.Key_Return)
    assert stack.count() == stack.index() == 1
    if editor == "mask":
        committed = mask.mask_layers[0].data.copy()
        assert committed.any()
        assert not marks.items
    else:
        assert len(marks.items) == 1
        assert not mask.mask_layers[0].data.any()
    QTest.keyClick(viewport, Qt.Key_Z, Qt.ControlModifier)
    assert stack.index() == 0
    QTest.keyClick(viewport, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
    assert stack.index() == 1
    QTest.keyClick(viewport, Qt.Key_Z, Qt.ControlModifier)
    QTest.keyClick(viewport, Qt.Key_Y, Qt.ControlModifier)
    assert stack.index() == 1
    if editor == "mask":
        np.testing.assert_array_equal(mask.mask_layers[0].data, committed)
    else:
        assert len(marks.items) == 1


def test_tool_keys_text_focus_and_tab_isolation(editors):
    app, host, viewer, marks, mask, entry = editors
    viewport = viewer._graphics.viewport()
    viewport.setFocus()
    QTest.keyClick(viewport, Qt.Key_R)
    assert marks._tool == "rectangle"
    assert mask.drawing_tool.name == "Brush"
    # A sibling text field and inactive tabs must not receive drawing commands.
    entry.setFocus()
    QTest.keyClicks(entry, "brclpet")
    assert entry.text() == "brclpet"
    assert marks._tool == "rectangle"
    assert mask.drawing_tool.name == "Brush"
    viewport.setFocus()
    QTest.keyClick(viewport, Qt.Key_T)
    marks.handle_press(pointer(3, 4))
    editor = marks._text_editor
    QTest.keyClicks(editor, "brclpet")
    QTest.keyClick(editor, Qt.Key_Z, Qt.ControlModifier)
    assert marks._tool == "text"
    assert mask.undo_stack.count() == marks.undo_stack.count() == 0
    QTest.keyClicks(editor, "Label")
    QTest.keyClick(editor, Qt.Key_Return)
    assert len(marks.items) == 1
    host.setCurrentIndex(1)
    app.processEvents()
    viewport = mask.image_viewer._graphics.viewport()
    viewport.setFocus()
    QTest.keyClick(viewport, Qt.Key_R)
    assert mask.drawing_tool.name == "Rectangle"
    assert marks._tool == "text"
    QTest.keyClick(viewport, Qt.Key_Z, Qt.ControlModifier)
    assert len(marks.items) == 1
    QTest.keyClick(viewport, Qt.Key_B)
    app.processEvents()
    mask.brush_size_spin.setFocus()
    QTest.keyClick(mask.brush_size_spin, Qt.Key_P)
    assert mask.drawing_tool.name == "Brush"


def test_alt_inversion_belongs_only_to_the_focused_mask_editor(editors):
    app, host, viewer, marks, mask, _entry = editors
    host.setCurrentIndex(1)
    app.processEvents()
    viewport = mask.image_viewer._graphics.viewport()
    viewport.setFocus()
    QTest.keyClick(viewport, Qt.Key_B)
    QTest.keyPress(viewport, Qt.Key_Alt)
    assert mask._alt_inversion_active
    assert not mask._effective_draw_value()
    QTest.keyRelease(viewport, Qt.Key_Alt)
    assert not mask._alt_inversion_active
    host.setCurrentIndex(0)
    app.processEvents()
    viewport = viewer._graphics.viewport()
    viewport.setFocus()
    QTest.keyPress(viewport, Qt.Key_Alt)
    assert not mask._alt_inversion_active
    assert mask._effective_draw_value()
    assert marks._tool == "brush"
    QTest.keyRelease(viewport, Qt.Key_Alt)


@pytest.mark.parametrize("editor", ["annotation", "mask"])
def test_undo_and_escape_discard_pending_gestures(editors, editor):
    app, host, viewer, marks, mask, _entry = editors
    if editor == "mask":
        host.setCurrentIndex(1)
        viewer = mask.image_viewer
        press = mask.drawing_session.handle_press
        release = mask.drawing_session.handle_release
        pending = lambda: mask.drawing_tool.gesture.active
        stack = mask.undo_stack
    else:
        press, release = marks.handle_press, marks.handle_release
        pending = lambda: marks.gesture.active
        stack = marks.undo_stack
    app.processEvents()
    viewport = viewer._graphics.viewport()
    viewport.setFocus()
    QTest.keyClick(viewport, Qt.Key_R)
    press(pointer(3, 4))
    release(pointer(8, 9))
    assert stack.index() == 1
    press(pointer(10, 11))
    QTest.keyClick(viewport, Qt.Key_Z, Qt.ControlModifier)
    assert not pending()
    assert stack.index() == 0
    release(pointer(15, 16))
    assert stack.count() == 1
    assert stack.index() == 0
    press(pointer(5, 6))
    QTest.keyClick(viewport, Qt.Key_Escape)
    assert not pending()
    release(pointer(15, 16))
    assert stack.index() == 0
