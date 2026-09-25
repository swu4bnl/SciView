"""User-facing, persistent readability settings shared by all beamline views."""
from PyQt5.QtCore import QSettings
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QFormLayout, QSpinBox, QComboBox,
    QPushButton, QColorDialog, QDialogButtonBox, QLabel,
)

from sciview.interfaces.theme.app_style import AppStyle


def preferences():
    # Use a stable application key, independent of the selected beamline.
    return QSettings("SciView", "Appearance")


def load_appearance(app):
    settings = preferences()
    screen = app.primaryScreen()
    large_screen = screen is not None and screen.size().width() >= 3000
    default_scale = 150 if large_screen else 125
    try:
        scale = int(settings.value("scale_percent", default_scale))
    except (ValueError, TypeError):
        scale = default_scale
    AppStyle.update_font_tokens({"scale_pct": scale})
    app.setProperty("sciview_text_mode", str(settings.value("text_mode", "contrast")))
    app.setProperty("sciview_custom_text", str(settings.value("custom_text", "#101010")))


def text_color(app, fallback, background):
    mode = app.property("sciview_text_mode") if app else None
    if mode == "contrast":
        return QColor("#ffffff" if background.lightness() < 128 else "#101010")
    if mode == "custom":
        color = QColor(app.property("sciview_custom_text") or "")
        if color.isValid(): return color
    return fallback


def stylesheet(app):
    colors = AppStyle.theme_colors(app)
    body = AppStyle.font_px("body")
    text = colors["text"].name()
    # Widget-local semantic styles still take precedence. Enabled label text
    # uses the configured foreground; disabled controls retain their distinction.
    return (
        f"QWidget {{ font-size: {body}px; }} "
        f"QLabel:enabled, QGroupBox, QMenuBar, QMenu, QCheckBox:enabled, "
        f"QRadioButton:enabled, QLineEdit:enabled, QAbstractSpinBox:enabled, "
        f"QComboBox:enabled, QAbstractItemView:enabled, QTextEdit:enabled "
        f"{{ color: {text}; }}"
    )


class AppearanceDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Appearance — text and readability")
        self.app = QApplication.instance()
        self.custom = self.app.property("sciview_custom_text") or "#101010"
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.scale = QSpinBox(); self.scale.setRange(75, 250); self.scale.setSingleStep(25)
        self.scale.setSuffix(" %"); self.scale.setValue(int(AppStyle.FONTS["scale_pct"]))
        self.mode = QComboBox()
        for label, value in (("High contrast (follows light/dark theme)", "contrast"),
                             ("Theme default", "theme"), ("Custom text color", "custom")):
            self.mode.addItem(label, value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.app.property("sciview_text_mode"))))
        self.color = QPushButton(self.custom); self.color.clicked.connect(self.choose_color)
        form.addRow("Text size", self.scale); form.addRow("Text color", self.mode)
        form.addRow("Custom color", self.color); layout.addLayout(form)
        note = QLabel("Settings apply to the application and plot labels, and are saved for the next launch. "
                      "High contrast uses dark text on light themes and white text on dark themes.")
        note.setWordWrap(True); layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Close | QDialogButtonBox.RestoreDefaults)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.defaults)
        layout.addWidget(buttons)

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.custom), self, "Text color")
        if color.isValid():
            self.custom = color.name(); self.color.setText(self.custom)
            self.mode.setCurrentIndex(self.mode.findData("custom"))

    def defaults(self):
        self.scale.setValue(150); self.mode.setCurrentIndex(0)
        self.apply()

    def apply(self):
        settings = preferences()
        settings.setValue("scale_percent", self.scale.value())
        settings.setValue("text_mode", self.mode.currentData())
        settings.setValue("custom_text", self.custom)
        settings.sync()
        load_appearance(self.app)
        # Rebuild from the base theme, avoiding accumulated global styles.
        variant = "dark" if AppStyle.theme_is_dark(self.app) else "light"
        if not AppStyle.apply_qdarktheme(variant, self.app):
            AppStyle.apply_global_style(self.app)


def install_menu(window):
    menu = window.menuBar().addMenu("View")
    action = menu.addAction("Appearance…")
    action.setShortcut("Ctrl+Shift+A")
    def show():
        dialog = AppearanceDialog(window)
        dialog.exec_()
    action.triggered.connect(show)
    menu.addAction("Toggle light / dark theme", window._toggle_dark_light_theme)
