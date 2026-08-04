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
              - "Construction-time (needs Ctrl+R)" — selected LAYOUT keys
                whose values you can edit and write back, but which only take
                effect after the active tab is rebuilt.
              "Write to file" persists the current values into app_style.py.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from PyQt5.QtCore import QFileSystemWatcher, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
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


def _reload_app_style() -> type:
    """Force-reimport app_style and return the refreshed AppStyle class."""
    import sciview.interfaces.theme.app_style as _mod
    importlib.reload(_mod)
    return _mod.AppStyle


def _apply_stylesheet(app_style_cls: type) -> None:
    """Re-apply the global stylesheet to the running QApplication."""
    qapp = QApplication.instance()
    if qapp is not None:
        app_style_cls.apply_global_style(qapp)


def _patch_token_in_file(token: str, value: int) -> None:
    """Rewrite a single integer token value inline in app_style.py."""
    text = _APP_STYLE_PATH.read_text(encoding="utf-8")
    pattern = rf"('{re.escape(token)}':\s*)([0-9]+)(.*)"
    new_text, count = re.subn(pattern, rf"\g<1>{int(value)}\g<3>", text)
    if count and new_text != text:
        _APP_STYLE_PATH.write_text(new_text, encoding="utf-8")


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
        self._css_spins: dict[str, QSpinBox] = {}
        self._layout_spins: dict[str, QSpinBox] = {}
        self._suppress = False
        self._build_ui()

    def _build_ui(self) -> None:
        AppStyle = _reload_app_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

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
        content_layout.addWidget(css_group)
        content_layout.addWidget(layout_group)
        content_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # ── Bottom buttons ────────────────────────────────────────────────────
        note = QLabel("'Write to file' persists values into app_style.py")
        note.setStyleSheet("font-size: 10px; color: #888;")
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

    def _on_css_changed(self) -> None:
        """CSS spinbox changed → update CSS_TOKENS live and re-apply stylesheet."""
        if self._suppress:
            return
        AppStyle = _reload_app_style()
        for key, spin in self._css_spins.items():
            AppStyle.CSS_TOKENS[key] = spin.value()
        _apply_stylesheet(AppStyle)
        self.setWindowTitle("Style Inspector  [dev]  •")

    def _write_to_file(self) -> None:
        """Persist all current spinbox values to app_style.py."""
        for key, spin in self._css_spins.items():
            _patch_token_in_file(key, spin.value())
        for key, spin in self._layout_spins.items():
            _patch_token_in_file(key, spin.value())
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
