"""Shared drawing gestures, Qt geometry, and focus-scoped editor commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import math

from PyQt5.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PyQt5.QtGui import QKeySequence, QPainterPath, QPainterPathStroker
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QLineEdit,
    QPlainTextEdit, QTextEdit, QWidget,
)


TOOL_KEYS = {
    "brush": Qt.Key_B, "eraser": Qt.Key_E, "line": Qt.Key_L,
    "rectangle": Qt.Key_R, "circle": Qt.Key_C, "polygon": Qt.Key_P,
    "smart_fill": Qt.Key_F, "text": Qt.Key_T,
}


def tool_key_label(tool: str) -> str:
    """Return the native display spelling from the same binding used for dispatch."""
    return QKeySequence(TOOL_KEYS[tool]).toString(QKeySequence.NativeText)


class DrawingGesture:
    """One unfinished gesture, independent of its output or coordinate policy."""

    def __init__(self) -> None:
        self.tool = ""
        self.points: list[QPointF] = []
        self.current: QPointF | None = None
        self._brush_path = QPainterPath()

    @property
    def active(self) -> bool:
        return bool(self.points)

    def press(self, tool: str, point: QPointF) -> None:
        if tool != "polygon" or self.tool != tool:
            self.cancel()
        self.tool = tool
        # Qt emits a normal press before a double-click. Do not add duplicate vertices.
        if not self.points or self.points[-1] != point or tool != "polygon":
            self.points.append(QPointF(point))
        self.current = QPointF(point)
        if tool in ("brush", "eraser"):
            self._brush_path = QPainterPath(point)

    def move(self, point: QPointF) -> None:
        if not self.active:
            return
        if self.tool in ("brush", "eraser") and self.current != point:
            self.points.append(QPointF(point))
            self._brush_path.lineTo(point)
        self.current = QPointF(point)

    def release(self, point: QPointF | None) -> bool:
        if not self.active or self.tool == "polygon":
            return False
        if point is not None:
            self.move(point)
        return True

    def finish_polygon(self, point: QPointF | None = None) -> bool:
        if self.tool != "polygon":
            return False
        if point is not None:
            self.press("polygon", point)
        if len(self.points) < 3:
            return False
        self.current = QPointF(self.points[-1])
        return True

    def path(
        self, width: float, *, filled: bool = False, pixel_mask: bool = False,
        close_polygon: bool = False,
    ) -> QPainterPath:
        """Build native geometry; mask policy retains inclusive integer pixels."""
        if not self.points or self.current is None:
            return QPainterPath()
        start, end = self.points[0], self.current
        path = QPainterPath()
        if self.tool == "rectangle":
            rect = QRectF(start, end).normalized()
            if pixel_mask:
                rect.adjust(-0.5, -0.5, 0.5, 0.5)
            path.addRect(rect)
        elif self.tool in ("circle", "smart_fill"):
            radius = width / 2 if self.tool == "smart_fill" else math.hypot(
                end.x() - start.x(), end.y() - start.y(),
            )
            if pixel_mask:
                radius = max(1, round(radius))
            path.addEllipse(start, radius, radius)
        else:
            if self.tool in ("brush", "eraser"):
                path = QPainterPath(self._brush_path)
            else:
                path.moveTo(start)
                vertices = self.points[1:] if self.tool == "polygon" else []
                for vertex in vertices:
                    path.lineTo(vertex)
                path.lineTo(end)
            if self.tool == "polygon" and (filled or close_polygon):
                path.closeSubpath()
            elif self.tool in ("brush", "eraser", "line"):
                if path.boundingRect().isNull():
                    path.addEllipse(end, width / 2, width / 2)
                elif filled:
                    stroker = QPainterPathStroker()
                    stroker.setWidth(width)
                    stroker.setCapStyle(Qt.RoundCap)
                    stroker.setJoinStyle(Qt.RoundJoin)
                    path = stroker.createStroke(path)
        return path

    def cancel(self) -> None:
        self.points.clear()
        self.current = None
        self.tool = ""
        self._brush_path = QPainterPath()


class DrawingCommands(QObject):
    """Route keys only inside the owning editor; editable widgets keep their keys."""

    def __init__(
        self, owner: QWidget, *, select_tools: Mapping[str, Callable[[], None]],
        finish: Callable[[], object], cancel: Callable[[], None],
        undo: Callable[[], None], redo: Callable[[], None],
        enabled: Callable[[], bool],
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.enabled = enabled
        self.finish = finish
        self.cancel = cancel
        self.undo = undo
        self.redo = redo
        self._tools = {TOOL_KEYS[name]: callback for name, callback in select_tools.items()}
        QApplication.instance().installEventFilter(self)

    @staticmethod
    def _editing(widget: QWidget | None) -> bool:
        while widget is not None:
            if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)):
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() not in (QEvent.ShortcutOverride, QEvent.KeyPress):
            return False
        focus = QApplication.focusWidget()
        if (focus is None or not self.owner.isVisible()
                or not (focus is self.owner or self.owner.isAncestorOf(focus))
                or self._editing(focus) or not self.enabled()):
            return False
        callback = None
        if event.matches(QKeySequence.Undo):
            callback = self.undo
        elif event.matches(QKeySequence.Redo) or (
            event.key() == Qt.Key_Z and event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier)
        ):
            callback = self.redo
        elif event.modifiers() in (Qt.NoModifier, Qt.KeypadModifier):
            if event.key() == Qt.Key_Escape:
                callback = self.cancel
            elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
                callback = self.finish
            else:
                callback = self._tools.get(event.key())
        if callback is None:
            return False
        event.accept()
        if event.type() == QEvent.KeyPress and not event.isAutoRepeat():
            callback()
        return True
