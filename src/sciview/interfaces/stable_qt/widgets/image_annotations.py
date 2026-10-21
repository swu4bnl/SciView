"""Display-only, shared image-browser annotations in detector pixel coordinates."""

from __future__ import annotations

import math
from pathlib import Path

import pyqtgraph as pg
from PyQt5.QtCore import QEvent, QObject, QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QKeySequence, QPainterPath, QPixmap
from PyQt5.QtWidgets import (
    QAction, QActionGroup, QColorDialog, QFrame, QGraphicsItem, QHBoxLayout,
    QGraphicsPathItem, QGraphicsRectItem, QLabel, QLayout, QLineEdit,
    QScrollArea, QShortcut, QSizePolicy, QSpinBox, QToolButton,
    QUndoCommand, QUndoStack, QWidget,
)

from sciview.interfaces.stable_qt.widgets.image_viewer import ImagePointerEvent, ImageViewer
from sciview.interfaces.text import tr
from sciview.interfaces.theme.app_style import AppStyle
from sciview.settings.viewer_config import MASK_TOOL_ICON_FILES, VIEWER_BEHAVIOR, VIEWER_COLORS


class _AnnotationCommand(QUndoCommand):
    def __init__(self, annotations: ImageAnnotations, items: list[QGraphicsItem], *, adding: bool):
        super().__init__(tr("annotations.edit"))
        self.annotations = annotations
        self.items = items
        self.adding = adding

    def _apply(self, adding: bool) -> None:
        for item in self.items:
            if adding:
                item.setParentItem(self.annotations.layer)
                self.annotations.items.append(item)
            else:
                self.annotations.items.remove(item)
                item.setParentItem(None)
                if item.scene() is not None:
                    item.scene().removeItem(item)

    def redo(self) -> None:
        self._apply(self.adding)

    def undo(self) -> None:
        self._apply(not self.adding)


class ImageAnnotations(QObject):
    """Own annotation graphics and history, never image, mask, or processing state."""

    TOOLS = ("brush", "line", "rectangle", "circle", "polygon", "text")
    drawing_changed = pyqtSignal(bool)

    def __init__(self, viewer: ImageViewer) -> None:
        super().__init__(viewer)
        self.viewer = viewer
        self.items: list[QGraphicsItem] = []
        self.layer = QGraphicsRectItem()
        self.layer.setPen(pg.mkPen(None))
        self.layer.setBrush(pg.mkBrush(None))
        self.layer.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        self.layer.setAcceptedMouseButtons(Qt.NoButton)
        self.layer.setZValue(30)
        self._points: list[QPointF] = []
        self._preview: QGraphicsPathItem | None = None
        self._color = QColor(VIEWER_COLORS.default_mask)
        self._tool = "brush"
        self._text_editor: QLineEdit | None = None
        self._text_position = QPointF()
        self.undo_stack = QUndoStack(self)

        self.button = QToolButton()
        self.button.setCheckable(True)
        self.button.setProperty("sciview_viewer_tool_button", True)
        self.tools = QScrollArea()
        self.tools.setAccessibleName(tr("annotations.tools"))
        self.tools.setFrameShape(QFrame.NoFrame)
        self.tools.setWidgetResizable(True)
        self.tools.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tools.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tools.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.tools.setVisible(False)
        self._strip = QWidget()
        self._strip.setAttribute(Qt.WA_StyledBackground, True)
        strip_layout = QHBoxLayout(self._strip)
        strip_layout.setContentsMargins(*([AppStyle.LAYOUT["panel_margin"]] * 4))
        strip_layout.setSpacing(AppStyle.LAYOUT["toolbar_spacing"])
        strip_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.tools.setWidget(self._strip)
        self._strip_buttons: list[QToolButton] = []
        self.tool_actions: dict[str, QAction] = {}
        self._tool_group = QActionGroup(self)
        for tool in self.TOOLS:
            action = QAction(tr(f"annotations.tool.{tool}"), self)
            action.setCheckable(True)
            action.setData(tool)
            gesture_key = tool if tool in ("circle", "polygon", "text") else "drag"
            action.setToolTip(tr("annotations.tool_help",
                                 tool=action.text(), gesture=tr(f"annotations.gesture.{gesture_key}")))
            self._tool_group.addAction(action)
            action.triggered.connect(lambda _checked, tool=tool: self.select_tool(tool))
            self.tool_actions[tool] = action
            self._add_strip_button(action)
        self.tool_actions[self._tool].setChecked(True)
        self._add_separator()

        self.color_action = QAction(tr("annotations.color"), self)
        self.color_action.triggered.connect(self._choose_color)
        self._add_strip_button(self.color_action)
        self.stroke_width = QSpinBox()
        self.stroke_width.setRange(1, 50)
        self.stroke_width.setValue(math.ceil(VIEWER_BEHAVIOR.default_line_width))
        self.stroke_width.setAccessibleName(tr("annotations.width"))
        self.stroke_width.setToolTip(tr("annotations.width"))
        width_label = QLabel(tr("annotations.width_short"))
        width_label.setBuddy(self.stroke_width)
        strip_layout.addWidget(width_label)
        strip_layout.addWidget(self.stroke_width)
        self.opacity = QSpinBox()
        self.opacity.setRange(10, 90)
        self.opacity.setSuffix("%")
        self.opacity.setValue(60)
        self.layer.setOpacity(self.opacity.value() / 100)
        self.opacity.valueChanged.connect(lambda value: self.layer.setOpacity(value / 100))
        self.opacity.setAccessibleName(tr("annotations.opacity"))
        self.opacity.setToolTip(tr("annotations.opacity"))
        opacity_label = QLabel(tr("annotations.opacity_short"))
        opacity_label.setBuddy(self.opacity)
        strip_layout.addWidget(opacity_label)
        strip_layout.addWidget(self.opacity)
        self._add_separator()
        strip_layout.addStretch()

        self.show_marks = QAction(tr("annotations.show"), self)
        self.show_marks.setCheckable(True)
        self.show_marks.setChecked(True)
        undo = QAction(tr("annotations.undo"), self)
        redo = QAction(tr("annotations.redo"), self)
        undo.triggered.connect(self._undo)
        redo.triggered.connect(self._redo)
        clear = QAction(tr("annotations.clear"), self)
        clear.triggered.connect(self._clear)
        self._action_icons = {
            undo: "tool_undo.svg", redo: "tool_redo.svg",
            self.show_marks: "status_visible.svg", clear: "tool_delete.svg",
        }
        for action in (undo, redo, self.show_marks, clear):
            self._add_strip_button(action)
        self.undo_stack.canUndoChanged.connect(undo.setEnabled)
        self.undo_stack.canRedoChanged.connect(redo.setEnabled)
        self.undo_stack.indexChanged.connect(lambda _index: clear.setEnabled(bool(self.items)))
        undo.setEnabled(False)
        redo.setEnabled(False)
        clear.setEnabled(False)
        for action, key in ((undo, QKeySequence.Undo), (redo, QKeySequence.Redo)):
            action.setShortcuts(key)
            action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            viewer.addAction(action)

        self.button.toggled.connect(self._set_drawing)
        self.show_marks.toggled.connect(self._set_visible)
        viewer.mouse_pressed.connect(self.handle_press)
        viewer.mouse_moved.connect(self.handle_move)
        viewer.mouse_released.connect(self.handle_release)
        viewer.mouse_double_clicked.connect(self.handle_double_click)
        viewer.interaction_mode_changed.connect(lambda _mode: self._leave_drawing())
        viewer.theme_changed.connect(self.refresh_theme)
        viewer.view_changed.connect(self.cancel)
        self._escape = QShortcut(QKeySequence(Qt.Key_Escape), viewer)
        self._escape.setContext(Qt.WidgetWithChildrenShortcut)
        self._escape.activated.connect(self._leave_drawing)
        viewer.set_annotation_tool(self.button, self.tools)
        self.refresh_theme()
        self.refresh_image()

    def _add_strip_button(self, action: QAction) -> None:
        button = QToolButton()
        button.setDefaultAction(action)
        button.setAccessibleName(action.text())
        self._strip.layout().addWidget(button)
        self._strip_buttons.append(button)

    def _add_separator(self) -> None:
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Plain)
        self._strip.layout().addWidget(separator)

    def select_tool(self, tool: str) -> None:
        """Selecting a tool immediately enters drawing, without a second toggle."""
        if tool not in self.TOOLS:
            raise ValueError(f"Unsupported annotation tool: {tool}")
        self.cancel()
        self._tool = tool
        self.tool_actions[tool].setChecked(True)
        self.refresh_theme()
        if self.viewer.source_array is not None:
            self.show_marks.setChecked(True)
            self.button.setChecked(True)

    def refresh_theme(self) -> None:
        """Reuse viewer styles and drawing icons for the contextual tool strip."""
        root = Path(__file__).resolve().parents[5]
        for tool, action in self.tool_actions.items():
            if tool == "text":
                action.setIcon(QIcon())
            else:
                action.setIcon(AppStyle.load_icon(root, MASK_TOOL_ICON_FILES[tool.title()]))
        icon = self.tool_actions[self._tool].icon()
        self.button.setIcon(icon)
        self.button.setText("T" if self._tool == "text" else "")
        self.button.setFont(AppStyle.make_font("h3"))
        size = AppStyle.viewer_toolbar_button_size()
        self.button.setFixedSize(size)
        self.button.setIconSize(AppStyle.viewer_toolbar_icon_size())
        AppStyle.apply_widget_style(self.button, "compact_button")
        AppStyle.apply_widget_style(self._strip, "viewer_toolbar")
        for action, filename in self._action_icons.items():
            if action is self.show_marks and not action.isChecked():
                filename = "status_hidden.svg"
            action.setIcon(AppStyle.load_icon(root, filename))
        self._update_color_swatch()
        for button in self._strip_buttons:
            button.setFixedSize(AppStyle.toolbar_symbol_button_size())
            button.setIconSize(AppStyle.viewer_toolbar_icon_size())
            button.setFont(AppStyle.make_font("h3"))
            AppStyle.apply_widget_style(button, "compact_button")
        for spinbox in (self.stroke_width, self.opacity):
            spinbox.setFixedHeight(AppStyle.toolbar_text_button_height())
        self.tools.setFixedHeight(
            self._strip.sizeHint().height() + self.tools.horizontalScrollBar().sizeHint().height()
        )
        tool_name = tr(f"annotations.tool.{self._tool}")
        gesture_key = self._tool if self._tool in ("circle", "polygon", "text") else "drag"
        self.button.setAccessibleName(tr("annotations.active_tool", tool=tool_name))
        self.button.setToolTip(tr(
            "annotations.toolbar_help", tool=tool_name,
            gesture=tr(f"annotations.gesture.{gesture_key}"),
        ))

    def refresh_image(self) -> None:
        """Cancel unfinished gestures and reattach after a browser image refresh."""
        self.cancel()
        image = self.viewer.source_array
        if image is not None:
            height, width = image.shape[:2]
            self.layer.setRect(0, 0, width, height)
        self.viewer.set_overlay_item(
            "browser-annotations", self.layer, group="browser-annotations",
            visible=image is not None and self.show_marks.isChecked(), ignore_bounds=True,
        )
        self.button.setEnabled(image is not None)
        if image is None:
            self.button.setChecked(False)

    def _set_drawing(self, enabled: bool) -> None:
        self.cancel()
        self.tools.setVisible(enabled)
        if enabled:
            self.show_marks.setChecked(True)
        self.viewer.set_interaction_locked(enabled, navigation_enabled=True)
        self.viewer.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.drawing_changed.emit(enabled)

    def _set_visible(self, visible: bool) -> None:
        self.refresh_image()
        self.show_marks.setIcon(AppStyle.load_icon(
            Path(__file__).resolve().parents[5],
            "status_visible.svg" if visible else "status_hidden.svg",
        ))

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(self._color, self.viewer, tr("annotations.color"))
        if color.isValid():
            self._color = color
            self._update_color_swatch()

    def _update_color_swatch(self) -> None:
        swatch = QPixmap(AppStyle.viewer_toolbar_icon_size())
        swatch.fill(self._color)
        self.color_action.setIcon(QIcon(swatch))
        self.color_action.setToolTip(tr("annotations.selected_color", color=self._color.name()))

    def _leave_drawing(self) -> None:
        self.cancel()
        self.button.setChecked(False)

    def _undo(self) -> None:
        self.cancel()
        self.undo_stack.undo()

    def _redo(self) -> None:
        self.cancel()
        self.undo_stack.redo()

    def _clear(self) -> None:
        self.cancel()
        if self.items:
            self.undo_stack.push(_AnnotationCommand(self, list(self.items), adding=False))

    def cancel(self) -> None:
        """Discard only the unfinished gesture."""
        self._close_text_editor()
        self._points.clear()
        if self._preview is not None:
            self._preview.setParentItem(None)
            if self._preview.scene() is not None:
                self._preview.scene().removeItem(self._preview)
            self._preview = None

    def _can_draw(self, event: ImagePointerEvent) -> bool:
        return (
            self.button.isChecked() and self.show_marks.isChecked()
            and self.viewer.source_array is not None and event.inside_image
            and math.isfinite(event.x) and math.isfinite(event.y)
        )

    def _point(self, event: ImagePointerEvent) -> QPointF:
        bounds = self.layer.rect()
        return QPointF(
            min(max(event.x, 0), bounds.width()),
            min(max(event.y, 0), bounds.height()),
        )

    def handle_press(self, event: ImagePointerEvent) -> None:
        if event.button == Qt.RightButton and self.button.isChecked():
            self.cancel()
            self.button.setChecked(False)
            return
        if event.button != Qt.LeftButton or not self._can_draw(event):
            return
        point = self._point(event)
        tool = self._tool
        if tool == "text":
            self._start_text_editor(point)
        elif tool == "polygon":
            self._points.append(point)
            self._update_preview(point)
        else:
            self.cancel()
            self._points = [point]
            self._update_preview(point)

    def handle_move(self, event: ImagePointerEvent) -> None:
        if not self._points or not (math.isfinite(event.x) and math.isfinite(event.y)):
            return
        point = self._point(event)
        if self._tool == "brush":
            self._points.append(point)
        self._update_preview(point)

    def handle_release(self, event: ImagePointerEvent) -> None:
        if event.button != Qt.LeftButton or not self._points or self._tool == "polygon":
            return
        if not (math.isfinite(event.x) and math.isfinite(event.y)):
            self.cancel()
            return
        self._update_preview(self._point(event))
        self._finish_path()

    def handle_double_click(self, event: ImagePointerEvent) -> None:
        if event.button == Qt.LeftButton and self._can_draw(event) and self._tool == "polygon":
            point = self._point(event)
            if not self._points or self._points[-1] != point:
                self._points.append(point)
            if len(self._points) >= 3:
                self._update_preview(point, close=True)
                self._finish_path()

    def _update_preview(self, point: QPointF, *, close: bool = False) -> None:
        path = QPainterPath(self._points[0])
        tool = self._tool
        if tool == "rectangle":
            path.addRect(QRectF(self._points[0], point).normalized())
        elif tool == "circle":
            radius = math.hypot(point.x() - self._points[0].x(), point.y() - self._points[0].y())
            path.addEllipse(self._points[0], radius, radius)
        else:
            for vertex in self._points[1:]:
                path.lineTo(vertex)
            path.lineTo(point)
            if close:
                path.closeSubpath()
            if tool == "brush" and path.boundingRect().isNull():
                path.addEllipse(point, self.stroke_width.value() / 2, self.stroke_width.value() / 2)
        if self._preview is None:
            self._preview = QGraphicsPathItem(self.layer)
            self._preview.setAcceptedMouseButtons(Qt.NoButton)
        pen = pg.mkPen(self._color, width=self.stroke_width.value())
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        self._preview.setPen(pen)
        self._preview.setPath(path)

    def _finish_path(self) -> None:
        item = self._preview
        self._preview = None
        self._points.clear()
        if item is not None:
            self._commit(item)

    def _commit(self, item: QGraphicsItem) -> None:
        item.setAcceptedMouseButtons(Qt.NoButton)
        self.undo_stack.push(_AnnotationCommand(self, [item], adding=True))

    def _start_text_editor(self, point: QPointF) -> None:
        self.cancel()
        self._text_position = point
        editor = QLineEdit(self.viewer)
        editor.setPlaceholderText(tr("annotations.text_hint"))
        editor.setAccessibleName(tr("annotations.text"))
        editor.setFont(AppStyle.make_font("body"))
        editor.setMinimumWidth(AppStyle.wide_input_min_width())
        editor.resize(editor.sizeHint())
        position = self.viewer.image_to_widget(point).toPoint()
        editor.move(
            max(0, min(position.x(), self.viewer.width() - editor.width())),
            max(0, min(position.y(), self.viewer.height() - editor.height())),
        )
        self._text_editor = editor
        editor.installEventFilter(self)
        editor.show()
        editor.setFocus()

    def _close_text_editor(self) -> None:
        editor = self._text_editor
        self._text_editor = None
        if editor is not None:
            editor.removeEventFilter(self)
            editor.hide()
            editor.deleteLater()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._text_editor:
            if event.type() == QEvent.KeyPress:
                if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    text = self._text_editor.text()
                    if text.strip():
                        item = pg.TextItem(text=text, color=self._color, anchor=(0, 0))
                        item.setFont(AppStyle.make_font("body"))
                        item.setPos(self._text_position)
                        self._commit(item)
                    self._close_text_editor()
                    return True
                if event.key() == Qt.Key_Escape:
                    self._leave_drawing()
                    return True
            elif event.type() == QEvent.FocusOut:
                self._close_text_editor()
        return super().eventFilter(watched, event)
