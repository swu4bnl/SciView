"""
SciAnalysis GUI - Main Application

A modular PyQt5-based GUI for X-ray scattering data analysis and calibration.
Designed for easy adaptation to different beamlines and analysis workflows.
"""

import sys
import os
import subprocess
import shutil
import tempfile
import tomllib
import logging
from dataclasses import replace
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


def _ensure_numpy_compat_aliases():
    """Apply NumPy 2.x compatibility aliases once for legacy SciAnalysis code."""
    if getattr(np, "_scianalysis_numpy_compat_applied", False):
        return

    for alias, target in {
        "float": float,
        "int": int,
        "bool": bool,
        "complex": complex,
    }.items():
        if not hasattr(np, alias):
            setattr(np, alias, target)

    np._scianalysis_numpy_compat_applied = True


# Compatibility shim for older SciAnalysis code paths that still reference
# deprecated NumPy aliases removed in NumPy 2.x. Keep this centralized here
# so it runs once early during app startup.
_ensure_numpy_compat_aliases()

# Add current directory and src/ to path for imports
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
sys.path.insert(0, os.path.join(app_dir, 'src'))

from PyQt5.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMessageBox, QPushButton, QTabWidget, QLabel,
    QWidget, QAction
)
from PyQt5.QtCore import Qt, QThread, QTimer

# Import configuration from package modules.
from sciview.interfaces.text import tr
from sciview.interfaces.theme.app_style import AppStyle, apply_info_style
from sciview.profiles.cms_profile import BEAMLINE_NAME, DEFAULT_CALIBRATION, get_calibration_class
from sciview.settings.app_settings import (
    GUI_SETTINGS,
    SCIANALYSIS_AVAILABLE,
    SCIANALYSIS_SOURCE_MODE,
    SCIANALYSIS_SOURCE_ROOT,
)
from sciview.settings.plot_style import AppearanceSettings, ImageDisplaySettings, PlotStyle

from sciview.interfaces.stable_qt.utils.resource_monitor import get_resource_monitor
from sciview.session.session_cache import choose_path
from sciview.session import session_cache


def _build_placeholder_tab(message):
    """Create a small placeholder widget when a tab module is unavailable."""
    from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

    placeholder = QWidget()
    layout = QVBoxLayout(placeholder)
    layout.addWidget(QLabel(message))
    return placeholder


class SciAnaApp(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr('shell.qapplication_applicationname_beamline_name', qapplication_applicationname=QApplication.applicationName(), beamline_name=BEAMLINE_NAME))
        self.status = self.statusBar()
        self._workspace_root = Path(__file__).resolve().parent
        self._closing_browser_workers = False

        # Shared application state
        self.image_data = None
        self.image_path = None
        self.calibration = None
        self.mask = None
        self.shared_info_text = None
        self.appearance_settings = AppearanceSettings()
        self.display_settings = ImageDisplaySettings(self)
        self._shared_image_revision = 0
        self._batch_recipe_bus: dict = {}
        self.shared_file_list: list[str] = []
        self.shared_file_list_info: dict[str, str] = {
            "folder": "",
            "pattern": "*",
            "source": "",
        }
        
        # Tab widget
        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)
        self._last_tab_index = -1
        self._tab_icon_keys = {}
        self.tab_widget.currentChanged.connect(self._on_current_tab_changed)
        tab_bar = self.tab_widget.tabBar()
        tab_bar.setFont(AppStyle.tab_font())
        tab_bar.setIconSize(AppStyle.tab_icon_size())
        tab_bar.setMinimumHeight(AppStyle.tab_min_height())
        tab_bar.setExpanding(False)
        self.tab_widget.setStyleSheet(AppStyle.tab_widget_stylesheet())
        
        self._icon_dir = AppStyle.icon_directory(self._workspace_root)

        # Use local transparent icons for platform-consistent button visuals.
        corner_button_size = AppStyle.corner_button_size()
        self.refresh_button = QPushButton("")
        self.refresh_button.setProperty("sciview_compact_button", True)
        self.refresh_button.setIcon(
            AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES['refresh'])
        )
        self.refresh_button.setIconSize(AppStyle.corner_button_icon_size())
        self.refresh_button.setToolTip(tr('shell.reload_current_tab_and_clear_cache'))
        self.refresh_button.setFixedSize(corner_button_size)
        self.refresh_button.clicked.connect(self._refresh_current_tab)

        self.style_inspector_button = QPushButton()
        self.style_inspector_button.setProperty("sciview_compact_button", True)
        self.style_inspector_button.setToolTip(tr('shell.open_style_inspector_dev_ctrl_shift'))
        self.style_inspector_button.setAccessibleName(tr('shell.open_style_inspector_dev_ctrl_shift'))
        self.style_inspector_button.setIcon(
            AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES['style_inspector'])
        )
        self.style_inspector_button.setIconSize(AppStyle.corner_button_icon_size())
        self.style_inspector_button.setFixedSize(corner_button_size)
        self.style_inspector_button.clicked.connect(self._show_style_inspector)

        self.theme_toggle_button = QPushButton()
        self.theme_toggle_button.setProperty("sciview_compact_button", True)
        self.theme_toggle_button.setFixedSize(corner_button_size)
        self.theme_toggle_button.clicked.connect(self._toggle_dark_light_theme)
        self._update_theme_toggle_icon()

        self.text_smaller_button = QPushButton()
        self.text_larger_button = QPushButton()
        for button, message_id, icon_key in (
            (self.text_smaller_button, 'shell.text_smaller', 'text_smaller'),
            (self.text_larger_button, 'shell.text_larger', 'text_larger'),
        ):
            button.setProperty("sciview_compact_button", True)
            button.setFixedSize(corner_button_size)
            button.setAccessibleName(tr(message_id))
            button.setToolTip(tr(message_id))
            button.setIcon(AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES[icon_key]))
            button.setIconSize(AppStyle.corner_button_icon_size())
        self.text_smaller_button.clicked.connect(lambda: self._step_text_scale(False))
        self.text_larger_button.clicked.connect(lambda: self._step_text_scale(True))
        self._update_text_scale_tooltips()

        self.high_contrast_button = QPushButton()
        self.high_contrast_button.setProperty("sciview_compact_button", True)
        self.high_contrast_button.setFixedSize(corner_button_size)
        self.high_contrast_button.setAccessibleName(tr('shell.high_contrast'))
        self.high_contrast_button.setToolTip(tr('shell.high_contrast'))
        self.high_contrast_button.setIcon(
            AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES['high_contrast'])
        )
        self.high_contrast_button.setIconSize(AppStyle.corner_button_icon_size())
        self.high_contrast_button.setCheckable(True)
        self.high_contrast_button.setChecked(AppStyle.high_contrast_enabled())
        self.high_contrast_button.toggled.connect(AppStyle.set_high_contrast)

        self.clear_session_button = QPushButton()
        self.clear_session_button.setAccessibleName(tr('shell.clear_saved_session'))
        self.clear_session_button.setProperty("sciview_compact_button", True)
        self.clear_session_button.setIcon(
            AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES['clear_session'])
        )
        self.clear_session_button.setIconSize(AppStyle.corner_button_icon_size())
        self.clear_session_button.setToolTip(
            tr('shell.clear_saved_session_cache_last_image')
        )
        self.clear_session_button.setFixedSize(corner_button_size)
        self.clear_session_button.clicked.connect(self._clear_session_cache)

        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(AppStyle.CORNER_BUTTON_UI['spacing'])
        corner_layout.addWidget(self.text_smaller_button)
        corner_layout.addWidget(self.text_larger_button)
        corner_layout.addWidget(self.high_contrast_button)
        corner_layout.addWidget(self.theme_toggle_button)
        corner_layout.addWidget(self.refresh_button)
        corner_layout.addWidget(self.clear_session_button)
        corner_layout.addWidget(self.style_inspector_button)
        corner_layout.addStretch()

        # Use QTabWidget's corner widget feature to place buttons on same line as tabs
        self.tab_widget.setCornerWidget(corner_widget, Qt.TopRightCorner)

        self._update_process = None
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._poll_update_process)
        self._update_output = b""
        self._update_output_file = None
        self._update_running_message = ""
        self._update_success_message = ""
        self._update_failure_prefix = tr('shell.update_failed')
        self._scianalysis_source_mode = SCIANALYSIS_SOURCE_MODE
        self._scianalysis_source_root = Path(SCIANALYSIS_SOURCE_ROOT) if SCIANALYSIS_SOURCE_ROOT else None
        
        # Set window sizing from config with screen-aware bounds.
        self._apply_window_size_from_config()
        self._base_window_minimum_size = self.minimumSize()
        
        # Setup resource monitoring
        self._setup_resource_monitor()
        
        # Setup keyboard shortcut for refresh
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self.refresh_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        self.refresh_shortcut.activated.connect(self._refresh_current_tab)
        self.theme_shortcut = QShortcut(QKeySequence("Ctrl+D"), self)
        self.theme_shortcut.activated.connect(self._toggle_dark_light_theme)
        self.text_smaller_action = QAction(tr('shell.text_smaller'), self)
        self.text_smaller_action.setShortcut(QKeySequence("Ctrl+-"))
        self.text_smaller_action.triggered.connect(self.text_smaller_button.click)
        self.addAction(self.text_smaller_action)
        self.text_larger_action = QAction(tr('shell.text_larger'), self)
        self.text_larger_action.setShortcuts([
            QKeySequence("Ctrl++"), QKeySequence("Ctrl+="), QKeySequence("Ctrl+Shift++"),
        ])
        self.text_larger_action.triggered.connect(self.text_larger_button.click)
        self.addAction(self.text_larger_action)

        # File hot-reload remains opt-in; the inspector is always available.
        self._style_hot_reloader = None
        self._style_inspector = None
        self._inspector_shortcut = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
        self._inspector_shortcut.setContext(Qt.ApplicationShortcut)
        self._inspector_shortcut.activated.connect(self._show_style_inspector)
        if os.environ.get("DEV_TOOLS") == "1":
            self._start_dev_tools()

    def _toggle_dark_light_theme(self):
        """Switch between qdarktheme dark and light."""
        variant = 'light' if AppStyle.theme_is_dark() else 'dark'
        if not AppStyle.apply_qdarktheme(variant):
            self.show_status(tr('shell.theme_unavailable'))

    def _set_text_scale(self, percent):
        AppStyle.update_font_tokens({'scale_pct': percent})
        AppStyle.apply_global_style(QApplication.instance(), preserve_existing=True)

    def _next_text_scale(self, increase: bool) -> int | None:
        current = int(AppStyle.FONTS['scale_pct'])
        options = AppStyle.TEXT_SCALE_OPTIONS
        candidates = [scale for scale in options if scale > current] if increase else [
            scale for scale in options if scale < current
        ]
        return (min(candidates) if increase else max(candidates)) if candidates else None

    def _step_text_scale(self, increase: bool) -> None:
        target = self._next_text_scale(increase)
        if target is not None:
            self._set_text_scale(target)

    def _update_text_scale_tooltips(self) -> None:
        current = int(AppStyle.FONTS['scale_pct'])
        for button, message_id, increase in (
            (self.text_smaller_button, 'shell.text_smaller', False),
            (self.text_larger_button, 'shell.text_larger', True),
        ):
            target = self._next_text_scale(increase)
            detail = (
                tr('shell.text_scale_next', current=current, target=target)
                if target is not None else tr('shell.text_scale_current', current=current)
            )
            tooltip = f"{tr(message_id)}\n{detail}"
            button.setToolTip(tooltip)
            button.setAccessibleDescription(detail)
            button.setEnabled(target is not None)

    def _update_theme_toggle_icon(self):
        if AppStyle.theme_is_dark():
            icon_key = 'light_mode'
            self.theme_toggle_button.setToolTip(tr('shell.switch_to_light_mode_ctrl_d'))
        else:
            icon_key = 'dark_mode'
            self.theme_toggle_button.setToolTip(tr('shell.switch_to_dark_mode_ctrl_d'))
        self.theme_toggle_button.setAccessibleName(self.theme_toggle_button.toolTip())
        self.theme_toggle_button.setIcon(
            AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES[icon_key])
        )
        self.theme_toggle_button.setIconSize(AppStyle.corner_button_icon_size())

    def _show_style_inspector(self):
        """Open the shared style inspector on demand."""
        if self._style_hot_reloader is not None:
            self._style_hot_reloader.show_inspector()
            return
        if self._style_inspector is None:
            from sciview.dev.style_inspector import StyleInspector
            self._style_inspector = StyleInspector(self)
        self._style_inspector.show()
        self._style_inspector.raise_()
        self._style_inspector.activateWindow()

    def _start_dev_tools(self):
        """Start optional file hot-reload."""
        try:
            from sciview.dev.style_inspector import StyleHotReloader
            self._style_hot_reloader = StyleHotReloader()
            self.show_status(tr('shell.dev_tools_active_hot_reload_on'))
        except Exception as exc:
            print(f"[dev tools] failed to start: {exc}")

    @staticmethod
    def _pair_from_config(value, fallback):
        """Parse a 2-item config sequence into numeric pair with fallback."""
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            return fallback
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return fallback

    def _apply_window_size_from_config(self):
        """Apply responsive window size and minimums without hard-coded screen assumptions."""
        screen = QApplication.primaryScreen()
        if screen is None:
            default_size = GUI_SETTINGS.get('default_window_size', (1200, 900))
            self.resize(*default_size)
            min_window_size = GUI_SETTINGS.get('minimum_window_size')
            if min_window_size:
                self.setMinimumSize(*min_window_size)
            return

        available = screen.availableGeometry()
        available_w = max(1, available.width())
        available_h = max(1, available.height())

        default_size = self._pair_from_config(GUI_SETTINGS.get('default_window_size'), (1200.0, 900.0))
        default_fraction = self._pair_from_config(
            GUI_SETTINGS.get('default_window_screen_fraction'),
            (0.9, 0.88),
        )
        target_w = int(default_fraction[0] * available_w)
        target_h = int(default_fraction[1] * available_h)

        # If configured fraction is invalid, fall back to configured absolute size.
        if target_w <= 0 or target_h <= 0:
            target_w, target_h = int(default_size[0]), int(default_size[1])

        target_w = min(max(640, target_w), available_w)
        target_h = min(max(480, target_h), available_h)

        min_size_cfg = self._pair_from_config(GUI_SETTINGS.get('minimum_window_size'), (1024.0, 768.0))
        min_size_floor = self._pair_from_config(GUI_SETTINGS.get('minimum_window_floor'), (720.0, 560.0))
        min_fraction = self._pair_from_config(GUI_SETTINGS.get('minimum_window_screen_fraction'), (0.75, 0.72))
        min_w_from_fraction = int(min_fraction[0] * available_w)
        min_h_from_fraction = int(min_fraction[1] * available_h)

        min_w = int(max(min_size_floor[0], min(min_size_cfg[0], min_w_from_fraction)))
        min_h = int(max(min_size_floor[1], min(min_size_cfg[1], min_h_from_fraction)))
        min_w = min(min_w, target_w)
        min_h = min(min_h, target_h)

        self.setMinimumSize(max(480, min_w), max(360, min_h))
        self.resize(target_w, target_h)

    def add_tab(self, widget, name, icon_key=None):
        """Add a tab to the main interface"""
        index = self.tab_widget.addTab(widget, name)
        if icon_key:
            self._tab_icon_keys[index] = icon_key
            icon_filename = AppStyle.TAB_ICON_FILES.get(icon_key)
            if icon_filename:
                self.tab_widget.setTabIcon(
                    index,
                    AppStyle.load_icon(self._workspace_root, icon_filename),
                )

    def _collect_session_state(self) -> dict:
        """Gather per-tab restart state, keyed by each tab's stable icon_key."""
        state = {"display_settings": dict(self.display_settings)}
        for index in range(self.tab_widget.count()):
            key = self._tab_icon_keys.get(index)
            widget = self.tab_widget.widget(index)
            if not key or not hasattr(widget, "get_session_state"):
                continue
            try:
                tab_state = widget.get_session_state()
            except Exception as exc:
                print(f"[session] failed to collect state for '{key}': {exc}")
                continue
            if tab_state:
                state[key] = tab_state
        return state

    def save_session_state(self) -> None:
        """Persist current tab state for restore on next launch (best-effort)."""
        try:
            session_cache.save_session(self._collect_session_state())
        except Exception as exc:
            print(f"[session] failed to save session cache: {exc}")

    def restore_session_state(self) -> None:
        """Restore last-saved tab state, if any. Never blocks or fails startup."""
        state = session_cache.load_session()
        if not state:
            return
        display_settings = state.get("display_settings")
        if display_settings:
            try:
                self.publish_shared_display_settings(display_settings)
            except Exception as exc:
                print(f"[session] failed to restore display settings: {exc}")
        for index in range(self.tab_widget.count()):
            key = self._tab_icon_keys.get(index)
            widget = self.tab_widget.widget(index)
            if not key or key not in state or not hasattr(widget, "restore_session_state"):
                continue
            try:
                widget.restore_session_state(state[key])
            except Exception as exc:
                print(f"[session] failed to restore state for '{key}': {exc}")

    def _clear_session_cache(self) -> None:
        """Manually wipe the on-disk session cache (no auto-pruning)."""
        response = QMessageBox.question(
            self,
            tr('shell.clear_session_cache'),
            tr('shell.this_deletes_the_saved_last_session'),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if response != QMessageBox.Yes:
            return
        session_cache.clear_session()
        self.show_status(tr('shell.session_cache_cleared'))

    def closeEvent(self, event):
        for index, icon_key in self._tab_icon_keys.items():
            if icon_key == "image_browser":
                self.tab_widget.widget(index).close()
        workers = [
            worker for worker in QApplication.instance().findChildren(QThread, "image-browser-load")
            if worker.isRunning()
        ]
        if workers:
            if not self._closing_browser_workers:
                self._closing_browser_workers = True
                for worker in workers:
                    worker.finished.connect(self._resume_browser_close)
            event.ignore()
            return
        self._closing_browser_workers = False
        self.save_session_state()
        session_cache.clear_scratch()
        super().closeEvent(event)

    def _resume_browser_close(self):
        if self._closing_browser_workers:
            self.close()

    def refresh_theme(self):
        """Refresh native sizing and theme-aware icons after a style change."""
        self.setMinimumSize(
            AppStyle.control_px(self._base_window_minimum_size.width()),
            AppStyle.control_px(self._base_window_minimum_size.height()),
        )
        self.tab_widget.setStyleSheet(AppStyle.tab_widget_stylesheet())
        self._update_theme_toggle_icon()
        tab_bar = self.tab_widget.tabBar()
        tab_bar.setFont(AppStyle.tab_font())
        tab_bar.setIconSize(AppStyle.tab_icon_size())
        tab_bar.setMinimumHeight(AppStyle.tab_min_height())

        for index, icon_key in self._tab_icon_keys.items():
            icon_filename = AppStyle.TAB_ICON_FILES.get(icon_key)
            if icon_filename:
                self.tab_widget.setTabIcon(index, AppStyle.load_icon(self._workspace_root, icon_filename))

        corner_button_size = AppStyle.corner_button_size()
        corner_icon_size = AppStyle.corner_button_icon_size()

        self.refresh_button.setIcon(AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES['refresh']))
        self.refresh_button.setIconSize(corner_icon_size)
        self.refresh_button.setFixedSize(corner_button_size)

        self.clear_session_button.setIcon(
            AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES['clear_session'])
        )
        self.clear_session_button.setIconSize(corner_icon_size)
        self.clear_session_button.setFixedSize(corner_button_size)

        self.style_inspector_button.setFixedSize(corner_button_size)
        self.theme_toggle_button.setFixedSize(corner_button_size)
        self.text_smaller_button.setFixedSize(corner_button_size)
        self.text_larger_button.setFixedSize(corner_button_size)
        for button, icon_key in (
            (self.text_smaller_button, 'text_smaller'),
            (self.text_larger_button, 'text_larger'),
            (self.style_inspector_button, 'style_inspector'),
        ):
            button.setIcon(AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES[icon_key]))
            button.setIconSize(corner_icon_size)
        self._update_text_scale_tooltips()
        self.high_contrast_button.setFixedSize(corner_button_size)
        self.high_contrast_button.setIcon(
            AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES['high_contrast'])
        )
        self.high_contrast_button.setIconSize(corner_icon_size)
        self.high_contrast_button.setChecked(AppStyle.high_contrast_enabled())

    def publish_shared_image(self, image_data, image_path=None, source_tab=None):
        """Publish active image into shared app state and propagate to tabs."""
        self.image_data = image_data
        if image_path is not None:
            self.image_path = image_path
        self._shared_image_revision += 1

        # Prefer the image-attached calibration as canonical when available.
        image_calibration = getattr(image_data, "calibration", None)
        if image_calibration is not None:
            self.calibration = image_calibration

        self.sync_tabs_from_shared(source_tab=source_tab)

    def publish_shared_calibration(self, calibration, source_tab=None, propagate=True):
        """Publish calibration so all tabs can consume a single shared object."""
        self.calibration = calibration
        if propagate:
            self.sync_tabs_from_shared(source_tab=source_tab)

    def publish_shared_mask(self, mask, source_tab=None, propagate=True):
        """Publish mask so all tabs can consume a single shared object."""
        self.mask = mask
        if propagate:
            self.sync_tabs_from_shared(source_tab=source_tab)

    @property
    def plot_style(self) -> PlotStyle:
        """Build a plot/export snapshot using the canonical display color map."""
        return self.appearance_settings.plot_snapshot()

    def publish_shared_display_settings(self, settings, source_tab=None):
        """Publish image display settings so image tabs share rendering and overlay state."""
        self.display_settings.update(settings)
        current_tab = self.tab_widget.currentWidget()
        if current_tab is not None and current_tab != source_tab and hasattr(current_tab, 'apply_shared_display_settings'):
            try:
                current_tab.apply_shared_display_settings(self.display_settings)
            except Exception as e:
                print(f"DEBUG: Error applying display settings to current tab: {e}")
        if "cmap" in settings or "scale" in settings:
            for i in range(self.tab_widget.count()):
                tab = self.tab_widget.widget(i)
                if hasattr(tab, "on_plot_style_changed"):
                    tab.on_plot_style_changed()

    def publish_shared_plot_style(self, style, source_tab=None):
        """Publish one plot style to previews and future batch recipes."""
        style = style if isinstance(style, PlotStyle) else PlotStyle.from_dict(style)
        self.appearance_settings = replace(self.appearance_settings, **style.to_dict())
        self.publish_shared_display_settings({"cmap": style.colormap}, source_tab=source_tab)

    def publish_shared_info_text(self, info_text, source_tab=None):
        """Publish image information text to dedicated info consumers."""
        self.shared_info_text = info_text
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if tab == source_tab:
                continue
            if hasattr(tab, 'set_shared_info_text'):
                try:
                    tab.set_shared_info_text(info_text)
                except Exception as e:
                    print(f"DEBUG: Error syncing shared info for tab {i}: {e}")

    def push_recipe_to_batch(self, recipe_payload: dict, source: str = "") -> None:
        """Register a protocol recipe from a processing tab and forward to the batch tab."""
        key = recipe_payload.get("name") or source or recipe_payload.get("operation", "recipe")
        recipe_payload = dict(recipe_payload)
        recipe_payload.setdefault("source", source)
        self._batch_recipe_bus[key] = recipe_payload
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, "receive_recipe"):
                tab.receive_recipe(key, recipe_payload)
                break

    def publish_shared_file_list(
        self,
        file_paths,
        *,
        folder: str = "",
        pattern: str = "*",
        source: str = "",
        source_tab=None,
    ) -> None:
        """Publish a canonical file-backed image list shared across tabs."""
        seen: set[str] = set()
        normalized: list[str] = []
        for item in file_paths or []:
            token = str(item).strip()
            if not token:
                continue
            if token not in seen:
                seen.add(token)
                normalized.append(token)

        self.shared_file_list = normalized
        self.shared_file_list_info = {
            "folder": str(folder or ""),
            "pattern": str(pattern or "*"),
            "source": str(source or ""),
        }

        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if tab == source_tab:
                continue
            if hasattr(tab, "on_shared_file_list_changed"):
                try:
                    tab.on_shared_file_list_changed(list(self.shared_file_list), dict(self.shared_file_list_info))
                except Exception as exc:
                    print(f"DEBUG: Error syncing shared file list for tab {i}: {exc}")

    def get_shared_file_list(self) -> list[str]:
        """Return the current shared local file list published by source tabs."""
        return list(self.shared_file_list)

    def get_shared_file_list_info(self) -> dict[str, str]:
        """Return metadata associated with the shared local file list."""
        return dict(self.shared_file_list_info)

    def get_shared_calibration(self, fallback_image_data=None):
        """Return shared calibration, with optional image calibration fallback."""
        if self.calibration is not None:
            return self.calibration
        if fallback_image_data is not None:
            return getattr(fallback_image_data, "calibration", None)
        return None

    def get_shared_mask(self):
        """Return shared mask object used by analysis tabs."""
        return self.mask

    def sync_tabs_from_shared(self, source_tab=None):
        """Push shared state into tabs and request redraws."""
        current_tab = self.tab_widget.currentWidget()
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if tab == source_tab:
                continue

            if hasattr(tab, 'image_data'):
                tab.image_data = self.image_data

            if (
                hasattr(tab, 'populate_image_info')
                and hasattr(tab, 'image_info_text')
                and self.image_data is not None
            ):
                try:
                    tab.populate_image_info(self.image_data, self.image_path)
                except Exception as e:
                    print(f"DEBUG: Error syncing image info for tab {i}: {e}")

            if hasattr(tab, 'set_shared_info_text') and self.shared_info_text:
                try:
                    tab.set_shared_info_text(self.shared_info_text)
                except Exception as e:
                    print(f"DEBUG: Error restoring shared info for tab {i}: {e}")

            if tab != current_tab:
                continue

            if hasattr(tab, 'update_plot'):
                try:
                    tab.update_plot()
                    setattr(tab, '_displayed_shared_image_revision', self._shared_image_revision)
                except Exception as e:
                    print(f"DEBUG: Error syncing plot for tab {i}: {e}")

    def show_status(self, msg):
        """Display status message"""
        self.status.showMessage(msg)

    def report_error(self, message, exc=None, *, user_visible=True):
        """Log an error and optionally surface it in the status bar.

        Always logged (with traceback when `exc` is given) so developers keep
        terminal visibility. Set `user_visible=False` for internal per-tab sync
        loops where a status message would be non-actionable noise or get
        overwritten mid-loop by the next tab's message.
        """
        if exc is not None:
            logger.exception(message)
        else:
            logger.error(message)
        if user_visible:
            self.show_status(message)

    def _on_current_tab_changed(self, index):
        """Publish outgoing tab state and render the newly active tab."""
        previous_index = self._last_tab_index
        self._last_tab_index = index

        if 0 <= previous_index < self.tab_widget.count():
            previous_tab = self.tab_widget.widget(previous_index)
            if hasattr(previous_tab, 'auto_publish_current_file_list'):
                try:
                    previous_tab.auto_publish_current_file_list()
                except Exception as e:
                    print(f"DEBUG: Error auto-publishing file list from previous tab: {e}")
            if hasattr(previous_tab, 'auto_publish_current_image'):
                try:
                    if previous_tab.auto_publish_current_image():
                        return
                except Exception as e:
                    print(f"DEBUG: Error auto-publishing image from previous tab: {e}")

        self._render_current_tab_from_shared()

    def _render_current_tab_from_shared(self, *_args):
        """Render shared image data when a tab becomes active."""
        tab = self.tab_widget.currentWidget()
        if tab is None:
            return

        if hasattr(tab, 'apply_shared_display_settings'):
            try:
                tab.apply_shared_display_settings(self.display_settings)
            except Exception as e:
                print(f"DEBUG: Error applying display settings to active tab: {e}")

        if self.image_data is None:
            return

        if hasattr(tab, 'image_data'):
            tab.image_data = self.image_data

        image_viewer = getattr(tab, 'image_viewer', None)
        rendered_revision = getattr(tab, '_displayed_shared_image_revision', None)
        needs_image_render = image_viewer is not None and (
            getattr(image_viewer, 'source_array', None) is None
            or rendered_revision != self._shared_image_revision
        )
        if needs_image_render:
            if hasattr(tab, 'update_plot'):
                try:
                    tab.update_plot()
                    setattr(tab, '_displayed_shared_image_revision', self._shared_image_revision)
                    return
                except Exception as e:
                    print(f"DEBUG: Error rendering active tab: {e}")

        if hasattr(tab, 'on_shared_state_activated'):
            try:
                tab.on_shared_state_activated()
                return
            except Exception as e:
                print(f"DEBUG: Error refreshing active tab shared state: {e}")

        if hasattr(tab, 'update_plot'):
            try:
                tab.update_plot()
            except Exception as e:
                print(f"DEBUG: Error rendering active tab: {e}")
    
    def _setup_resource_monitor(self):
        """Setup periodic resource usage updates in status bar"""
        self.resource_monitor = get_resource_monitor()
        self.resource_label = QLabel()
        self.resource_label.setMaximumWidth(250)
        self.status.addPermanentWidget(self.resource_label)
        apply_info_style(self.resource_label)
        
        # Timer to update resource info
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self._update_resource_display)
        # Update every 1 second
        self.monitor_timer.start(1000)
    
    def _update_resource_display(self):
        """Update the resource usage display in status bar"""
        try:
            resource_info = self.resource_monitor.get_resource_status()
            if resource_info:
                self.resource_label.setText(resource_info)
        except Exception as e:
            print(f"Error updating resource display: {e}")
    
    def update_all_displays(self, source_tab=None):
        """Update display across all tabs when display settings change"""
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)

            if tab == source_tab:
                continue
            
            if hasattr(tab, 'apply_shared_display_settings'):
                try:
                    tab.apply_shared_display_settings(self.display_settings)
                except Exception as e:
                    print(f"Error updating tab {i}: {e}")
            elif hasattr(tab, 'update_plot'):
                try:
                    tab.update_plot()
                except Exception as e:
                    print(f"Error updating tab {i}: {e}")
            # Remove the fallback to update_display since we unified on update_plot
    
    def load_image(self, calibration=None, file_filters="*.tiff *.tif *.h5 *.dat"):
        """
        Load image data from file
        
        Args:
            calibration: Calibration object to use, creates default if None
            file_filters: File type filters for the dialog
            
        Returns:
            tuple: (image_data, file_path) or (None, None) if failed
        """
        if not SCIANALYSIS_AVAILABLE:
            self.show_status(tr('shell.could_not_load_the_image_scianalysis'))
            return None, None
            
        path, _ = choose_path(self, tr('shell.open_image_file'), file_filter=file_filters, key="image_open")
        if not path:
            return None, None
            
        try:
            # Use provided calibration, active shared calibration, or create a default one
            if calibration is None:
                if self.calibration is not None:
                    calibration = self.calibration
                else:
                    cal_cls = get_calibration_class()
                    calibration = cal_cls(wavelength_A=DEFAULT_CALIBRATION['wavelength_A'])
                    calibration.set_pixel_size(pixel_size_um=DEFAULT_CALIBRATION['pixel_size_um'])
                    calibration.set_distance(DEFAULT_CALIBRATION['distance_m'])
                    if hasattr(calibration, 'set_angles'):
                        calibration.set_angles(
                            det_orient=DEFAULT_CALIBRATION['detector_orient_deg'],
                            det_tilt=DEFAULT_CALIBRATION['detector_tilt_deg'],
                            det_phi=DEFAULT_CALIBRATION['detector_phi_deg'],
                        )
            
            if SCIANALYSIS_AVAILABLE:
                from SciAnalysis.XSAnalysis.Data import Data2DScattering
                image_data = Data2DScattering(path, calibration=calibration)
            else:
                image_data = None
            
            # Store and propagate shared state
            self.publish_shared_image(image_data, image_path=path)
            self.publish_shared_calibration(calibration)
            
            # Update calibration with image size
            h, w = image_data.data.shape
            calibration.set_image_size(w, height=h)
            calibration.clear_maps()
            
            # Show success status
            self.show_status(tr('shell.loaded_image_basename_path_w_x', basename_path=os.path.basename(path), w=w, h=h))
            
            return image_data, path
            
        except Exception as e:
            self.report_error(tr('shell.could_not_load_basename_path_error', basename_path=os.path.basename(path), error=e), exc=e)
            return None, None
    
    def get_image_path(self):
        """Get the currently loaded image path"""
        return self.image_path
    
    def _refresh_current_tab(self):
        """Refresh the current tab by reloading its module and recreating it"""
        current_index = self.tab_widget.currentIndex()
        if current_index < 0:
            return
        
        current_tab = self.tab_widget.widget(current_index)
        tab_name = self.tab_widget.tabText(current_index)
        
        try:
            self.show_status(tr('shell.refreshing_tab_name', tab_name=tab_name))
            
            # Clear cache if it's the Image Browser tab
            if hasattr(current_tab, 'session_manager'):
                cache_info = current_tab.session_manager.get_cache_info()
                current_tab.session_manager.clear_session()
                self.show_status(tr('shell.cleared_cache_info_get_cached_items', cache_info_get_cached_items_0=cache_info.get('cached_items', 0)))
            
            # Dynamic module discovery - attempt to find the tab class from the instance
            # This makes the refresh button future-proof for new tabs
            class_name = current_tab.__class__.__name__
            module_name = current_tab.__class__.__module__
            
            # Fallback to hardcoded map if dynamic discovery doesn't work
            if not module_name or 'tabs.' not in module_name:
                stable_name = self._tab_icon_keys.get(current_index)
                module_map = {
                    "image_browser": "tabs.image_browser_tab.ImageBrowserApp",
                    "tiled_browser": "tabs.tiled_browser_tab.TiledBrowserTab",
                    "calibration": "tabs.calibration_tab.CalibrationApp",
                    "mask_editing": "tabs.mask_tab.MaskApp",
                    "reduction": "tabs.reduction_tab.ReductionTab",
                    "transform": "tabs.transform_tab.TransformTab",
                    "batch": "tabs.batch_tab.BatchTab",
                    "info": "tabs.info_tab.InfoTab",
                }
                if stable_name not in module_map:
                    self.show_status(tr('shell.cannot_refresh_tab_name_unknown_tab', tab_name=tab_name))
                    return
                
                module_path = module_map[stable_name]
                module_name, class_name = module_path.rsplit('.', 1)
            
            # Reload the module
            import importlib
            module = importlib.import_module(module_name)
            importlib.reload(module)
            
            # Get the class and create new instance
            tab_class = getattr(module, class_name)
            new_tab = tab_class(self)
            
            # Replace the tab
            self.tab_widget.removeTab(current_index)
            self.tab_widget.insertTab(current_index, new_tab, tab_name)
            self.tab_widget.setCurrentIndex(current_index)
            if self._tab_icon_keys.get(current_index) == "image_browser":
                current_tab.close()
                current_tab.deleteLater()
            
            self.show_status(tr('shell.refreshed_tab_name_successfully', tab_name=tab_name))
            
        except Exception as e:
            self.show_status(tr('shell.error_refreshing_tab_name_error', tab_name=tab_name, error=str(e)))
            print(f"Error refreshing tab: {e}")
            import traceback
            traceback.print_exc()

    def _set_update_ui_enabled(self, enabled: bool):
        self.refresh_button.setEnabled(enabled)

    def _start_update_process(
        self,
        *,
        title: str,
        confirm_message: str,
        command,
        running_message: str,
        success_message: str,
        failure_prefix: str,
    ):
        if self._update_process is not None:
            self.show_status(tr('shell.another_update_is_already_running'))
            return

        response = QMessageBox.question(
            self,
            title,
            confirm_message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if response != QMessageBox.Yes:
            self.show_status(tr('shell.title_canceled', title=title))
            return

        self._set_update_ui_enabled(False)
        self._update_output = b""
        self._update_output_file = tempfile.TemporaryFile()
        self._update_running_message = running_message
        self._update_success_message = success_message
        self._update_failure_prefix = failure_prefix
        self.show_status(running_message)

        try:
            self._update_process = subprocess.Popen(
                command,
                stdout=self._update_output_file,
                stderr=subprocess.STDOUT,
                cwd=str(self._workspace_root),
            )
            self._update_timer.start(1000)
        except Exception as exc:
            self._update_process = None
            if self._update_output_file is not None:
                self._update_output_file.close()
                self._update_output_file = None
            self._set_update_ui_enabled(True)
            self.show_status(tr('shell.failed_to_start_update_error', error=exc))

    def _update_sciview_source(self):
        """Update the SciView checkout from its git remote."""
        command = self._build_sciview_update_command()
        if command is None:
            return

        self._start_update_process(
            title=tr('shell.update_sciview'),
            confirm_message=tr('shell.this_will_run_git_pull_ff'),
            command=command,
            running_message=tr('shell.updating_sciview_source_checkout'),
            success_message=tr('shell.sciview_source_updated_restart_sciview_to'),
            failure_prefix=tr('shell.sciview_update_failed'),
        )

    def _update_scianalysis_source(self):
        """Update the active SciAnalysis source."""
        if self._scianalysis_source_mode == "pixi":
            command = self._build_pixi_update_command()
            action_label = tr('shell.pixi_managed_scianalysis_package')
        else:
            command = self._build_git_update_command()
            action_label = tr('shell.scianalysis_checkout')

        if command is None:
            return

        self._start_update_process(
            title=tr('shell.update_scianalysis'),
            confirm_message=tr('shell.this_will_update_the_active_action', action_label=action_label),
            command=command,
            running_message=tr('shell.updating_action_label', action_label=action_label),
            success_message=tr('shell.scianalysis_source_updated_restart_sciview_to'),
            failure_prefix=tr('shell.scianalysis_update_failed'),
        )

    def _build_sciview_update_command(self):
        git_executable = shutil.which("git")
        if not git_executable:
            self.show_status(tr('shell.git_executable_not_found_on_path'))
            QMessageBox.warning(
                self,
                tr('shell.sciview_update'),
                tr('shell.git_was_not_found_on_path'),
            )
            return None

        if not (self._workspace_root / ".git").exists():
            self.show_status(tr('shell.sciview_source_is_not_a_git'))
            QMessageBox.warning(
                self,
                tr('shell.sciview_update'),
                tr('shell.the_current_sciview_source_is_not'),
            )
            return None

        return [git_executable, "-C", str(self._workspace_root), "pull", "--ff-only"]

    def _build_pixi_update_command(self):
        pixi_executable = shutil.which("pixi")
        if not pixi_executable:
            self.show_status(tr('shell.pixi_executable_not_found_on_path'))
            QMessageBox.warning(
                self,
                tr('shell.scianalysis_update'),
                tr('shell.pixi_was_not_found_on_path'),
            )
            return None

        if not (self._workspace_root / "pixi.toml").exists():
            self.show_status(tr('shell.pixi_toml_not_found_in_workspace'))
            QMessageBox.warning(
                self,
                tr('shell.scianalysis_update'),
                tr('shell.pixi_toml_was_not_found_in'),
            )
            return None

        return [pixi_executable, "update", "scitoolsscianalysis"]

    def _build_git_update_command(self):
        git_executable = shutil.which("git")
        if not git_executable:
            self.show_status(tr('shell.git_executable_not_found_on_path'))
            QMessageBox.warning(
                self,
                tr('shell.scianalysis_update'),
                tr('shell.git_was_not_found_on_path_2'),
            )
            return None

        if self._scianalysis_source_root is None:
            self.show_status(tr('shell.scianalysis_checkout_not_configured'))
            QMessageBox.warning(
                self,
                tr('shell.scianalysis_update'),
                tr('shell.no_scianalysis_checkout_is_configured_set'),
            )
            return None

        if not (self._scianalysis_source_root / ".git").exists():
            self.show_status(tr('shell.scianalysis_source_is_not_a_git'))
            QMessageBox.warning(
                self,
                tr('shell.scianalysis_update'),
                tr('shell.the_selected_scianalysis_source_is_not'),
            )
            return None

        return [git_executable, "-C", str(self._scianalysis_source_root), "pull", "--ff-only"]

    def _poll_update_process(self):
        process = self._update_process
        if process is None:
            self._update_timer.stop()
            self._set_update_ui_enabled(True)
            return

        return_code = process.poll()
        if return_code is None:
            self.show_status(tr('shell.value_update_running_message_still_running', value__update_running_message=self._update_running_message))
            return

        try:
            process.wait(timeout=5)
        except Exception:
            pass

        output_file = self._update_output_file
        self._update_output_file = None
        output = b""
        if output_file is not None:
            try:
                output_file.seek(0)
                output = output_file.read()
            finally:
                output_file.close()

        if output:
            self._update_output += output

        self._update_timer.stop()
        self._update_process = None
        self._set_update_ui_enabled(True)

        text = self._update_output.decode("utf-8", errors="replace")
        if return_code == 0:
            self.show_status(self._update_success_message)
        else:
            tail = "\n".join(text.splitlines()[-8:]).strip()
            if tail:
                self.show_status(tr('shell.value_update_failure_prefix_tail', value__update_failure_prefix=self._update_failure_prefix, tail=tail))
            else:
                self.show_status(tr('shell.value_update_failure_prefix_with_exit', value__update_failure_prefix=self._update_failure_prefix, return_code=return_code))


def create_application():
    """Create and configure the main application"""
    print("[SciView] Starting up...")
    app = QApplication(sys.argv)
    AppStyle.apply_bundled_fonts(app)

    # Load layout/sizing ratios from runtime configuration before creating widgets.
    AppStyle.apply_gui_settings(GUI_SETTINGS)

    # Resolve the system theme before widgets create palette-derived styles and icons.
    if not AppStyle.apply_qdarktheme('auto', app):
        AppStyle.apply_global_style(app)
    
    with (Path(__file__).resolve().parent / "pyproject.toml").open("rb") as handle:
        metadata = tomllib.load(handle)
    project = metadata["project"]
    app.setApplicationName(metadata["tool"]["sciview"]["display_name"])
    app.setApplicationVersion(project["version"])
    app.setOrganizationName(project["name"])
    
    # Create main window
    print("[SciView] Initializing main window...")
    main_window = SciAnaApp()
    
    # Add tabs
    import time as _time

    _TAB_TOTAL = 8
    _tab_idx = 0

    def _tab_start(name):
        nonlocal _tab_idx
        _tab_idx += 1
        print(f"[SciView]  [{_tab_idx}/{_TAB_TOTAL}] Loading {name}...", end="", flush=True)
        return _time.perf_counter()

    def _tab_done(t0, *, failed=False):
        elapsed = (_time.perf_counter() - t0) * 1000
        status = "FAILED" if failed else "ok"
        print(f" {status} ({elapsed:.0f}ms)")

    # Image Browser
    t0 = _tab_start("Image Browser")
    try:
        from tabs.image_browser_tab import ImageBrowserApp
        image_browser_tab = ImageBrowserApp(main_window)
        main_window.add_tab(image_browser_tab, tr('shell.image_browser'), icon_key="image_browser")
        _tab_done(t0)
    except ImportError as e:
        _tab_done(t0, failed=True)
        placeholder = _build_placeholder_tab(tr('shell.image_browser_tab_n_import_error', error=e))
        main_window.add_tab(placeholder, tr('shell.image_browser'), icon_key="image_browser")

    # Tiled Browser
    t0 = _tab_start("Tiled Browser")
    try:
        from tabs.tiled_browser_tab import TiledBrowserTab
        tiled_browser_tab = TiledBrowserTab(main_window)
        main_window.add_tab(tiled_browser_tab, tr('shell.tiled_browser'), icon_key="tiled_browser")
        _tab_done(t0)
    except ImportError as e:
        _tab_done(t0, failed=True)
        placeholder = _build_placeholder_tab(tr('shell.tiled_browser_tab_n_import_error', error=e))
        main_window.add_tab(placeholder, tr('shell.tiled_browser'), icon_key="tiled_browser")

    # Calibration
    t0 = _tab_start("Calibration")
    try:
        if SCIANALYSIS_AVAILABLE:
            from tabs.calibration_tab import CalibrationApp
            calibration_tab = CalibrationApp(main_window)
            main_window.add_tab(calibration_tab, tr('shell.calibration'), icon_key="calibration")
            _tab_done(t0)
        else:
            _tab_done(t0, failed=True)
            placeholder = _build_placeholder_tab(tr('shell.calibration_tab_n_scianalysis_not_available'))
            main_window.add_tab(placeholder, tr('shell.calibration'), icon_key="calibration")
    except ImportError as e:
        _tab_done(t0, failed=True)
        placeholder = _build_placeholder_tab(tr('shell.calibration_tab_n_import_error_error', error=e))
        main_window.add_tab(placeholder, tr('shell.calibration'), icon_key="calibration")

    # Mask Editing
    t0 = _tab_start("Mask Editing")
    try:
        from tabs.mask_tab import MaskApp
        mask_tab = MaskApp(main_window)
        main_window.add_tab(mask_tab, tr('shell.mask_editing'), icon_key="mask_editing")
        _tab_done(t0)
    except ImportError as e:
        _tab_done(t0, failed=True)
        placeholder = _build_placeholder_tab(tr('shell.mask_tab_n_import_error_error', error=e))
        main_window.add_tab(placeholder, tr('shell.mask_editing'), icon_key="mask_editing")

    # Reduction
    t0 = _tab_start("Reduction")
    try:
        from tabs.reduction_tab import ReductionTab
        reduction_tab = ReductionTab(main_window)
        main_window.add_tab(reduction_tab, tr('shell.reduction'), icon_key="reduction")
        _tab_done(t0)
    except ImportError as e:
        _tab_done(t0, failed=True)
        placeholder = _build_placeholder_tab(tr('shell.reduction_tab_n_import_error_error', error=e))
        main_window.add_tab(placeholder, tr('shell.reduction'), icon_key="reduction")

    # Transform
    t0 = _tab_start("Transform")
    try:
        from tabs.transform_tab import TransformTab
        transform_tab = TransformTab(main_window)
        main_window.add_tab(transform_tab, tr('shell.transform'), icon_key="transform")
        _tab_done(t0)
    except ImportError as e:
        _tab_done(t0, failed=True)
        placeholder = _build_placeholder_tab(tr('shell.transform_tab_n_import_error_error', error=e))
        main_window.add_tab(placeholder, tr('shell.transform'), icon_key="transform")

    # Batch
    t0 = _tab_start("Batch")
    try:
        from tabs.batch_tab import BatchTab
        batch_tab = BatchTab(main_window)
        main_window.add_tab(batch_tab, tr('shell.batch'), icon_key="batch")
        _tab_done(t0)
    except ImportError as e:
        _tab_done(t0, failed=True)
        placeholder = _build_placeholder_tab(tr('shell.batch_tab_n_import_error_error', error=e))
        main_window.add_tab(placeholder, tr('shell.batch'), icon_key="batch")

    # Info
    t0 = _tab_start("Info")
    try:
        from tabs.info_tab import InfoTab
        info_tab = InfoTab(main_window)
        main_window.add_tab(info_tab, tr('shell.info'), icon_key="info")
        _tab_done(t0)
    except ImportError as e:
        _tab_done(t0, failed=True)
        placeholder = _build_placeholder_tab(tr('shell.info_tab_n_import_error_error', error=e))
        main_window.add_tab(placeholder, tr('shell.info'), icon_key="info")

    print("[SciView] All tabs loaded. Launching window...")
    main_window.restore_session_state()
    return app, main_window


def main():
    """Main entry point"""
    try:
        app, main_window = create_application()
        main_window.show()
        
        # Show startup status in GUI status bar
        if SCIANALYSIS_AVAILABLE:
            status_msg = tr('shell.scianalysis_gui_started_for_beamline_name', beamline_name=BEAMLINE_NAME)
        else:
            status_msg = tr('shell.scianalysis_gui_started_for_beamline_name_2', beamline_name=BEAMLINE_NAME)
        main_window.show_status(status_msg)

        sa_status = "available" if SCIANALYSIS_AVAILABLE else "NOT available"
        print(f"[SciView] Ready  |  Beamline: {BEAMLINE_NAME}  |  SciAnalysis: {sa_status}")
        print("[SciView] *** Do not close this window — it keeps the app running ***")
        
        sys.exit(app.exec_())
        
    except Exception as e:
        print(f"[SciView] Fatal error starting application: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
