"""
Dev-only style inspector and hot-reload watcher.

Activated at startup only when DEV_TOOLS=1 is set, or via Ctrl+Shift+I.

Hot-reload:   QFileSystemWatcher monitors app_style.py.  On every save the
              global stylesheet is re-applied instantly — no restart needed.
              Only CSS_TOKENS changes take visual effect immediately; LAYOUT
              changes (panel_margin, splitter ratios, etc.) require a tab
              rebuild via Ctrl+R.

Inspector:    A floating panel with two sections:
              - "Live (CSS)" — every key in AppStyle.CSS_TOKENS.  Drag a
                slider and the stylesheet updates in real time.
                            - "Live Typography" — adjust H1/H2/H3 and text font sizes and
                                apply immediately across the app.
              - "Construction-time (needs Ctrl+R)" — selected LAYOUT keys
                whose values you can edit and write back, but which only take
                effect after the active tab is rebuilt.
              "Write to file" persists the current values into app_style.py.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from PyQt5.QtCore import QFileSystemWatcher, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)

_APP_STYLE_PATH = (
    Path(__file__).resolve().parent.parent / "interfaces" / "theme" / "app_style.py"
)

# Construction-time LAYOUT keys worth exposing in the inspector.
# Format: key -> (label, min, max)
_LAYOUT_TOKENS: dict[str, tuple[str, int, int]] = {
    "panel_margin":           ("Panel margin (px)",        0, 20),
    "panel_spacing":          ("Panel spacing (px)",       0, 20),
    "toolbar_spacing":        ("Toolbar spacing (px)",     0, 20),
    "splitter_handle_width":  ("Splitter handle (px)",     2, 12),
    "control_panel_min_height": ("Control min height (px)", 40, 200),
}

_FONT_SIZE_TOKENS: dict[str, tuple[str, int, int]] = {
    "scale_pct": ("Global scale (%)", 50, 250),
    "h1": ("H1 heading (px)", 8, 40),
    "h2": ("H2 heading (px)", 8, 36),
    "h3": ("H3 heading (px)", 8, 32),
    "body": ("Body font (px)", 8, 30),
    "caption": ("Caption font (px)", 7, 24),
    "small": ("Small font (px)", 6, 20),
}

_ACTIVE_THEME_KEY: str | None = None


def _reload_app_style() -> type:
    """Force-reimport app_style and return the refreshed AppStyle class."""
    import sciview.interfaces.theme.app_style as _mod
    importlib.reload(_mod)
    return _mod.AppStyle


def _apply_stylesheet(app_style_cls: type) -> None:
    """Re-apply the current theme to the running QApplication."""
    _apply_theme(_ACTIVE_THEME_KEY, app_style_cls=app_style_cls)


def _available_qt_styles() -> list[str]:
    """Return the Qt widget styles available in the current runtime."""
    return list(QStyleFactory.keys())


def _theme_option_items() -> list[tuple[str, str]]:
    """Return the theme choices currently available in this environment."""
    options: list[tuple[str, str]] = []

    for style_name in _available_qt_styles():
        options.append((f"qt:{style_name}", f"Qt: {style_name}"))

    if importlib.util.find_spec("qdarkstyle") is not None:
        options.append(("qdarkstyle", "QDarkStyle"))

    if importlib.util.find_spec("qt_material") is not None:
        options.append(("qt-material:light_blue.xml", "qt-material: light_blue"))
        options.append(("qt-material:dark_teal.xml", "qt-material: dark_teal"))

    if importlib.util.find_spec("qdarktheme") is not None:
        options.append(("qdarktheme:dark", "qdarktheme: dark"))
        options.append(("qdarktheme:light", "qdarktheme: light"))

    return options


def _current_qt_style_key() -> str:
    """Return the active built-in Qt style as a theme key."""
    qapp = QApplication.instance()
    if qapp is None:
        return ""

    current_name = qapp.style().objectName().lower()
    for style_name in _available_qt_styles():
        if style_name.lower() == current_name:
            return f"qt:{style_name}"

    available = _available_qt_styles()
    return f"qt:{available[0]}" if available else ""


def _apply_theme(theme_key: str | None, app_style_cls: type | None = None) -> bool:
    """Apply the requested Qt style or external theme to the running app."""
    global _ACTIVE_THEME_KEY

    qapp = QApplication.instance()
    if qapp is None:
        return False

    if app_style_cls is None:
        app_style_cls = _reload_app_style()

    if not theme_key:
        theme_key = _ACTIVE_THEME_KEY or _current_qt_style_key()

    qapp.setProperty(app_style_cls.THEME_KEY_PROPERTY, theme_key)

    if theme_key.startswith("qt:"):
        style_name = theme_key.split(":", 1)[1]
        if style_name not in _available_qt_styles():
            return False
        qapp.setStyle(style_name)
        qapp.setPalette(qapp.style().standardPalette())
        app_style_cls.apply_global_style(qapp)
        _ACTIVE_THEME_KEY = theme_key
        return True

    qapp.setStyle(_current_qt_style_key().split(":", 1)[1])
    qapp.setPalette(qapp.style().standardPalette())

    if theme_key == "qdarkstyle":
        qdarkstyle = importlib.import_module("qdarkstyle")

        qapp.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
        app_style_cls.refresh_runtime_theme(qapp)
        _ACTIVE_THEME_KEY = theme_key
        return True

    if theme_key.startswith("qt-material:"):
        qt_material = importlib.import_module("qt_material")

        theme_name = theme_key.split(":", 1)[1]
        qt_material.apply_stylesheet(qapp, theme=theme_name, extra={"font_family": "Consolas"})
        readability_qss = app_style_cls.qt_material_readability_stylesheet(qapp)
        if readability_qss:
            qapp.setStyleSheet(qapp.styleSheet() + readability_qss)
        app_style_cls.refresh_runtime_theme(qapp)
        _ACTIVE_THEME_KEY = theme_key
        return True

    if theme_key.startswith("qdarktheme:"):
        qdarktheme = importlib.import_module("qdarktheme")

        theme_name = theme_key.split(":", 1)[1]
        qdarktheme.setup_theme(theme_name)
        app_style_cls.refresh_runtime_theme(qapp)
        _ACTIVE_THEME_KEY = theme_key
        return True

    return False


def _patch_dict_value_in_file(dict_name: str, key: str, value_repr: str) -> None:
    """Rewrite a single dict key value in app_style.py without formatting churn."""
    text = _APP_STYLE_PATH.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    in_dict = False
    brace_depth = 0
    changed = False

    for idx, line in enumerate(lines):
        stripped = line.lstrip()

        if not in_dict and stripped.startswith(f"{dict_name} = {{"):
            in_dict = True
            brace_depth = line.count("{") - line.count("}")
            continue

        if not in_dict:
            continue

        brace_depth += line.count("{") - line.count("}")

        key_pos = line.find(f"'{key}':")
        if key_pos != -1:
            colon_pos = line.find(":", key_pos)
            if colon_pos == -1:
                continue

            prefix = line[:colon_pos + 1]
            rest = line[colon_pos + 1:]

            newline = "\n" if line.endswith("\n") else ""
            comment = ""
            if "#" in rest:
                _, comment_part = rest.split("#", 1)
                comment = f" #{comment_part.rstrip()}"

            has_comma = "," in rest
            comma = "," if has_comma else ""
            new_line = f"{prefix} {value_repr}{comma}{comment}{newline}"
            lines[idx] = new_line
            changed = True
            break

        if brace_depth <= 0:
            in_dict = False

    if changed:
        _APP_STYLE_PATH.write_text("".join(lines), encoding="utf-8")


def _make_spin(mn: int, mx: int, value: int) -> QSpinBox:
    s = QSpinBox()
    s.setRange(mn, mx)
    s.setValue(int(value))
    return s


class StyleInspector(QWidget):
    """Floating panel for live CSS-token editing and layout-token inspection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Style Inspector  [dev]")
        self.resize(340, 600)
        self._style_combo: QComboBox | None = None
        self._css_spins: dict[str, QSpinBox] = {}
        self._layout_spins: dict[str, QSpinBox] = {}
        self._font_spins: dict[str, QSpinBox] = {}
        self._font_family_input: QLineEdit | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self) -> None:
        AppStyle = _reload_app_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Qt style section ────────────────────────────────────────────────
        style_group = QGroupBox("Qt Style")
        style_form = QFormLayout(style_group)
        style_form.setContentsMargins(6, 10, 6, 6)
        style_form.setSpacing(3)
        style_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self._style_combo = QComboBox()
        theme_options = _theme_option_items()
        for theme_key, label in theme_options:
            self._style_combo.addItem(label, theme_key)
        current_theme_key = _ACTIVE_THEME_KEY or _current_qt_style_key()
        current_index = -1
        for index in range(self._style_combo.count()):
            if self._style_combo.itemData(index) == current_theme_key:
                current_index = index
                break
        if current_index >= 0:
            self._style_combo.setCurrentIndex(current_index)
        self._style_combo.currentIndexChanged.connect(self._on_qt_style_changed)
        style_form.addRow("Theme", self._style_combo)

        style_note = QLabel("Built-in Qt styles and optional external themes apply immediately.")
        style_form.addRow("", style_note)

        # ── Live CSS section ──────────────────────────────────────────────────
        css_group = QGroupBox("Live  (stylesheet re-applies instantly)")
        css_group.setStyleSheet(
            "QGroupBox { font-weight: 600; color: #0078D4; margin-top: 8px; "
            "padding-top: 12px; } QGroupBox::title { left: 8px; }"
        )
        css_form = QFormLayout(css_group)
        css_form.setContentsMargins(6, 10, 6, 6)
        css_form.setSpacing(3)
        css_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        css_tokens = AppStyle.CSS_TOKENS
        # Build a human label from the key name
        for key, value in sorted(css_tokens.items()):
            label = key.replace("_", " ").capitalize()
            spin = _make_spin(0, 60, int(value))
            spin.valueChanged.connect(self._on_css_changed)
            self._css_spins[key] = spin
            css_form.addRow(label, spin)

        # ── Live typography section ──────────────────────────────────────────
        font_group = QGroupBox("Live Typography  (applies instantly)")
        font_group.setStyleSheet(
            "QGroupBox { font-weight: 600; color: #0E8A16; margin-top: 8px; "
            "padding-top: 12px; } QGroupBox::title { left: 8px; }"
        )
        font_form = QFormLayout(font_group)
        font_form.setContentsMargins(6, 10, 6, 6)
        font_form.setSpacing(3)
        font_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        fonts = AppStyle.FONTS
        for key, (label, mn, mx) in _FONT_SIZE_TOKENS.items():
            raw_value = fonts.get(key, 100 if key == "scale_pct" else "11px")
            try:
                if key == "scale_pct":
                    spin_value = int(raw_value)
                else:
                    spin_value = int(str(raw_value).replace("px", "").strip())
            except (TypeError, ValueError):
                spin_value = 100 if key == "scale_pct" else 11
            spin = _make_spin(mn, mx, spin_value)
            spin.valueChanged.connect(self._on_fonts_changed)
            self._font_spins[key] = spin
            font_form.addRow(label, spin)

        family = str(fonts.get("family", "")).strip()
        self._font_family_input = QLineEdit(family)
        self._font_family_input.setPlaceholderText("Optional global font-family stack")
        self._font_family_input.editingFinished.connect(self._on_fonts_changed)
        font_form.addRow("Font family", self._font_family_input)

        # ── Construction-time LAYOUT section ─────────────────────────────────
        layout_group = QGroupBox("Construction-time  (Ctrl+R to apply)")
        layout_group.setStyleSheet(
            "QGroupBox { font-weight: 600; color: #6C757D; margin-top: 8px; "
            "padding-top: 12px; } QGroupBox::title { left: 8px; }"
        )
        layout_form = QFormLayout(layout_group)
        layout_form.setContentsMargins(6, 10, 6, 6)
        layout_form.setSpacing(3)
        layout_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        for key, (label, mn, mx) in _LAYOUT_TOKENS.items():
            value = AppStyle.LAYOUT.get(key, 0)
            spin = _make_spin(mn, mx, int(value))
            # No live signal — changes only persist via "Write to file"
            self._layout_spins[key] = spin
            layout_form.addRow(label, spin)

        # ── Scroll area wrapping both groups ──────────────────────────────────
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)
        content_layout.addWidget(style_group)
        content_layout.addWidget(css_group)
        content_layout.addWidget(font_group)
        content_layout.addWidget(layout_group)
        content_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # ── Bottom buttons ────────────────────────────────────────────────────
        note = QLabel("'Write to file' persists values into app_style.py")
        note.setStyleSheet("color: #888;")
        AppStyle.set_font_role(note, 'status')
        root.addWidget(note)

        btn_row = QHBoxLayout()
        write_btn = QPushButton("Write to file")
        write_btn.setToolTip("Persist current spinbox values into app_style.py")
        write_btn.clicked.connect(self._write_to_file)
        reload_btn = QPushButton("Reload from file")
        reload_btn.setToolTip("Re-read values from app_style.py on disk")
        reload_btn.clicked.connect(self.reload_from_file)
        btn_row.addWidget(write_btn)
        btn_row.addWidget(reload_btn)
        root.addLayout(btn_row)

    # ── Signal handlers ───────────────────────────────────────────────────────

    def _on_qt_style_changed(self, _index: int) -> None:
        """Theme selection changed -> switch style immediately."""
        if self._suppress:
            return
        if self._style_combo is None:
            return
        theme_key = self._style_combo.currentData()
        theme_label = self._style_combo.currentText()
        if isinstance(theme_key, str) and _apply_theme(theme_key):
            self.setWindowTitle(f"Style Inspector  [dev]  • {theme_label}")

    def _on_css_changed(self) -> None:
        """CSS spinbox changed → update CSS_TOKENS live and re-apply stylesheet."""
        if self._suppress:
            return
        AppStyle = _reload_app_style()
        for key, spin in self._css_spins.items():
            AppStyle.CSS_TOKENS[key] = spin.value()
        _apply_stylesheet(AppStyle)
        self.setWindowTitle("Style Inspector  [dev]  •")

    def _on_fonts_changed(self) -> None:
        """Typography changed -> update FONTS live and re-apply stylesheet."""
        if self._suppress:
            return
        AppStyle = _reload_app_style()
        for key, spin in self._font_spins.items():
            if key == "scale_pct":
                AppStyle.FONTS[key] = int(spin.value())
            else:
                AppStyle.FONTS[key] = f"{spin.value()}px"
        if self._font_family_input is not None:
            family = self._font_family_input.text().strip()
            if family:
                AppStyle.FONTS["family"] = family
            elif "family" in AppStyle.FONTS:
                del AppStyle.FONTS["family"]
        _apply_stylesheet(AppStyle)
        self.setWindowTitle("Style Inspector  [dev]  •")

    def _write_to_file(self) -> None:
        """Persist all current spinbox values to app_style.py."""
        for key, spin in self._css_spins.items():
            _patch_dict_value_in_file("CSS_TOKENS", key, str(int(spin.value())))
        for key, spin in self._font_spins.items():
            if key == "scale_pct":
                _patch_dict_value_in_file("FONTS", key, str(int(spin.value())))
            else:
                _patch_dict_value_in_file("FONTS", key, repr(f"{spin.value()}px"))
        if self._font_family_input is not None:
            family = self._font_family_input.text().strip()
            if family:
                _patch_dict_value_in_file("FONTS", "family", repr(family))
        for key, spin in self._layout_spins.items():
            _patch_dict_value_in_file("LAYOUT", key, str(int(spin.value())))
        AppStyle = _reload_app_style()
        _apply_stylesheet(AppStyle)
        self.setWindowTitle("Style Inspector  [dev]  ✓ saved")

    def reload_from_file(self) -> None:
        """Reload spinbox values from app_style.py without triggering signals."""
        self._suppress = True
        AppStyle = _reload_app_style()
        for key, spin in self._css_spins.items():
            if key in AppStyle.CSS_TOKENS:
                spin.setValue(int(AppStyle.CSS_TOKENS[key]))
        for key, spin in self._layout_spins.items():
            if key in AppStyle.LAYOUT:
                spin.setValue(int(AppStyle.LAYOUT[key]))
        for key, spin in self._font_spins.items():
            try:
                if key == "scale_pct":
                    spin.setValue(int(AppStyle.FONTS.get(key, 100)))
                else:
                    raw_value = str(AppStyle.FONTS.get(key, "11px")).strip()
                    spin.setValue(int(raw_value.replace("px", "").strip()))
            except (TypeError, ValueError):
                pass
        if self._font_family_input is not None:
            self._font_family_input.setText(str(AppStyle.FONTS.get("family", "")).strip())
        self._suppress = False
        _apply_stylesheet(AppStyle)
        self.setWindowTitle("Style Inspector  [dev]")


# ── Hot-reloader ──────────────────────────────────────────────────────────────

class StyleHotReloader:
    """
    Watches app_style.py for on-disk changes (e.g. manual edits in VS Code)
    and re-applies the stylesheet immediately — no restart required.
    CSS_TOKENS changes take effect instantly; LAYOUT changes need Ctrl+R.
    """

    def __init__(self) -> None:
        self._watcher = QFileSystemWatcher()
        self._watcher.addPath(str(_APP_STYLE_PATH))
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._inspector: StyleInspector | None = None

    def _on_file_changed(self, _path: str) -> None:
        # Some editors replace files atomically — re-watch if path was dropped.
        if str(_APP_STYLE_PATH) not in self._watcher.files():
            self._watcher.addPath(str(_APP_STYLE_PATH))
        try:
            AppStyle = _reload_app_style()
            _apply_stylesheet(AppStyle)
            if self._inspector is not None and self._inspector.isVisible():
                self._inspector.reload_from_file()
            qapp = QApplication.instance()
            if qapp:
                for widget in qapp.topLevelWidgets():
                    if hasattr(widget, "show_status"):
                        widget.show_status("app_style.py hot-reloaded")
                        break
        except Exception as exc:  # noqa: BLE001
            print(f"[StyleHotReloader] reload failed: {exc}")

    def show_inspector(self) -> None:
        if self._inspector is None:
            self._inspector = StyleInspector()
        self._inspector.show()
        self._inspector.raise_()
        self._inspector.activateWindow()
