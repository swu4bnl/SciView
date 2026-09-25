"""Readable status text with an explicit contrast pair in either application theme."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel


class StatusLabel(QLabel):
    def refresh_theme(self):
        from sciview.interfaces.theme.app_style import AppStyle
        size = max(16, AppStyle.font_px("body"))
        self.setStyleSheet(
            "QLabel { color: #ffffff; background-color: #193549; "
            f"font-size: {size}px; font-weight: 600; padding: 10px; "
            "border: 1px solid #8caec4; border-radius: 5px; }"
        )


def readable_status(text="", parent=None):
    label = StatusLabel(text, parent)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    # Specify both foreground and background so
    # a muted theme label color cannot make connection state hard to distinguish.
    label.refresh_theme()
    return label
