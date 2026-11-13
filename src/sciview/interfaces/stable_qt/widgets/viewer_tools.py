"""Toolbar building blocks shared by image and curve viewers."""

from pathlib import Path

import pyqtgraph as pg
import pyqtgraph.exporters
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QLabel, QToolButton, QVBoxLayout, QWidget

from sciview.interfaces.text import tr
from sciview.interfaces.theme.app_style import AppStyle
from sciview.settings.viewer_config import VIEWER_TOOL_ICON_FILES, ViewerToolbarAction


def export_plot_view(plot: pg.PlotItem, path: str | Path) -> None:
    pg.exporters.ImageExporter(plot).export(str(path))


def load_toolbar_icon(key: str) -> QIcon:
    filename = VIEWER_TOOL_ICON_FILES.get(key)
    if not filename:
        return QIcon()
    return AppStyle.load_icon(Path(__file__).resolve().parents[5], filename)


def make_tool_button(action: ViewerToolbarAction, icon: QIcon) -> QToolButton:
    button = QToolButton()
    button.setProperty("sciview_viewer_tool_button", True)
    button.setAccessibleName(tr(action.label_id))
    button.setAutoRaise(False)
    button.setFixedSize(AppStyle.viewer_toolbar_button_size())
    AppStyle.apply_widget_style(button, "compact_button")
    if icon.isNull():
        button.setText(tr(action.label_id))
        button.setFont(AppStyle.make_font("h3", weight=QFont.Weight.Bold))
    else:
        button.setIcon(icon)
        button.setIconSize(AppStyle.viewer_toolbar_icon_size())
    button.setToolTip(tr(action.tooltip_id))
    return button


def make_labeled_tool_cell(label_text: str, button: QToolButton) -> QWidget:
    cell = QWidget()
    layout = QVBoxLayout(cell)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(AppStyle.LAYOUT["tool_label_spacing"])
    layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
    label = QLabel(label_text)
    label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    AppStyle.set_font_role(label, "toolbar_text")
    layout.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
    return cell
