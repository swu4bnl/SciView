"""Colormap previews for colormap selection menus."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import QComboBox

from sciview.interfaces.stable_qt.widgets.image_viewer import ImageViewer

_GRADIENT_STOPS = 16
_PREVIEW_SIZE = QSize(64, 14)


def show_colormap_previews(combo: QComboBox) -> None:
    """Show each colormap as a gradient swatch beside its item text."""
    combo.setIconSize(_PREVIEW_SIZE)
    for index in range(combo.count()):
        lut = ImageViewer.colormap_lut(combo.itemText(index))
        gradient = QLinearGradient(0.0, 0.0, _PREVIEW_SIZE.width(), 0.0)
        positions = np.linspace(0.0, 1.0, _GRADIENT_STOPS)
        for position, rgb in zip(positions, lut[np.round(positions * (len(lut) - 1)).astype(int)]):
            gradient.setColorAt(float(position), QColor(*(int(value) for value in rgb)))
        preview = QPixmap(_PREVIEW_SIZE)
        preview.fill(Qt.GlobalColor.transparent)
        painter = QPainter(preview)
        painter.fillRect(preview.rect(), gradient)
        painter.end()
        combo.setItemData(index, QIcon(preview), Qt.ItemDataRole.DecorationRole)
