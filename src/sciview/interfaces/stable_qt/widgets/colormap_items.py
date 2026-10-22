"""Colormap previews for colormap selection menus."""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor, QGradient, QLinearGradient
from PyQt5.QtWidgets import QComboBox

from sciview.interfaces.stable_qt.widgets.image_viewer import ImageViewer

_GRADIENT_STOPS = 16
# Item text sits on the left; choose its color from that part of the preview.
_TEXT_REGION_FRACTION = 0.4


def show_colormap_previews(combo: QComboBox) -> None:
    """Paint each colormap item's background with its own color gradient."""
    for index in range(combo.count()):
        lut = ImageViewer.colormap_lut(combo.itemText(index))
        gradient = QLinearGradient(0.0, 0.0, 1.0, 0.0)
        gradient.setCoordinateMode(QGradient.ObjectBoundingMode)
        positions = np.linspace(0.0, 1.0, _GRADIENT_STOPS)
        for position, rgb in zip(positions, lut[np.round(positions * (len(lut) - 1)).astype(int)]):
            gradient.setColorAt(float(position), QColor(*(int(value) for value in rgb)))
        combo.setItemData(index, QBrush(gradient), Qt.BackgroundRole)

        text_region = lut[: max(1, int(len(lut) * _TEXT_REGION_FRACTION))]
        red, green, blue = text_region.mean(axis=0)
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        text_color = QColor(Qt.black) if luminance > 140 else QColor(Qt.white)
        combo.setItemData(index, QBrush(text_color), Qt.ForegroundRole)
