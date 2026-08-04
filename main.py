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
from pathlib import Path
import numpy as np


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
    QWidget
)
from PyQt5.QtCore import Qt, QTimer

# Import configuration from package modules.
from sciview.interfaces.theme.app_style import AppStyle, apply_info_style
from sciview.profiles.cms_profile import BEAMLINE_NAME, DEFAULT_CALIBRATION
from sciview.settings.app_settings import (
    DEFAULT_DISPLAY_SETTINGS,
    GUI_SETTINGS,
    SCIANALYSIS_AVAILABLE,
    SCIANALYSIS_SOURCE_MODE,
    SCIANALYSIS_SOURCE_ROOT,
)

# Import SciAnalysis dependencies only if available  
if SCIANALYSIS_AVAILABLE:
    from SciAnalysis.XSAnalysis.Data import Data2DScattering
    from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv
from sciview.interfaces.stable_qt.utils.resource_monitor import get_resource_monitor
from sciview.interfaces.stable_qt.utils.file_dialog_state import dialog_open_file


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
        self.setWindowTitle(f"SciView - {BEAMLINE_NAME}")
        self.status = self.statusBar()
        self._workspace_root = Path(__file__).resolve().parent

        # Shared application state
        self.image_data = None
        self.image_path = None
        self.calibration = None
        self.mask = None
        self.shared_info_text = None
        self.display_settings = DEFAULT_DISPLAY_SETTINGS.copy()
        self._shared_image_revision = 0
        
        # Tab widget
        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)
        self._last_tab_index = -1
        self.tab_widget.currentChanged.connect(self._on_current_tab_changed)
        tab_bar = self.tab_widget.tabBar()
        tab_bar.setIconSize(AppStyle.tab_icon_size())
        tab_bar.setExpanding(False)
        self.tab_widget.setStyleSheet(AppStyle.tab_widget_stylesheet())
        
        self._icon_dir = AppStyle.icon_directory(self._workspace_root)

        # Use local transparent icons for platform-consistent button visuals.
        self.refresh_button = QPushButton("")
        self.refresh_button.setIcon(
            AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES['refresh'])
        )
        self.refresh_button.setIconSize(AppStyle.corner_button_icon_size())
        self.refresh_button.setToolTip("Reload current tab and clear cache (Ctrl+R)")
        corner_button_size = AppStyle.corner_button_size()
        self.refresh_button.setFixedSize(corner_button_size)
        self.refresh_button.clicked.connect(self._refresh_current_tab)

        self.update_scianalysis_button = QPushButton("")
        self.update_scianalysis_button.setIcon(
            AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES['sci_update'])
        )
        self.update_scianalysis_button.setIconSize(AppStyle.corner_button_icon_size())
        source_label = {
            "pixi": "Pixi package",
            "local": "local SciAnalysis checkout",
            "custom": "custom SciAnalysis checkout",
        }.get(SCIANALYSIS_SOURCE_MODE, "selected SciAnalysis source")
        self.update_scianalysis_button.setToolTip(f"Update the {source_label} (restart after it finishes)")
        self.update_scianalysis_button.setFixedSize(corner_button_size)
        self.update_scianalysis_button.clicked.connect(self._update_scianalysis_source)

        self.update_sciview_button = QPushButton("")
        self.update_sciview_button.setIcon(
            AppStyle.load_icon(self._workspace_root, AppStyle.CORNER_ICON_FILES['app_update'])
        )
        self.update_sciview_button.setIconSize(AppStyle.corner_button_icon_size())
        self.update_sciview_button.setToolTip("Update the SciView checkout from GitHub (git pull --ff-only)")
        self.update_sciview_button.setFixedSize(corner_button_size)
        self.update_sciview_button.clicked.connect(self._update_sciview_source)
        
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(AppStyle.CORNER_BUTTON_UI['spacing'])
        corner_layout.addWidget(self.refresh_button)
        corner_layout.addWidget(self.update_sciview_button)
        corner_layout.addWidget(self.update_scianalysis_button)
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
        self._update_failure_prefix = "Update failed"
        self._scianalysis_source_mode = SCIANALYSIS_SOURCE_MODE
        self._scianalysis_source_root = Path(SCIANALYSIS_SOURCE_ROOT) if SCIANALYSIS_SOURCE_ROOT else None
        
        # Set window sizing from config with screen-aware bounds.
        self._apply_window_size_from_config()
        
        # Setup resource monitoring
        self._setup_resource_monitor()
        
        # Setup keyboard shortcut for refresh
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self.refresh_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        self.refresh_shortcut.activated.connect(self._refresh_current_tab)

        # Dev tools: hot-reload + style inspector (only when DEV_TOOLS=1)
        self._style_hot_reloader = None
        if os.environ.get("DEV_TOOLS") == "1":
            self._start_dev_tools()

    def _start_dev_tools(self):
        """Start hot-reloader and register Ctrl+Shift+I for the style inspector."""
        try:
            from sciview.dev.style_inspector import StyleHotReloader
            from PyQt5.QtWidgets import QShortcut
            from PyQt5.QtGui import QKeySequence
            self._style_hot_reloader = StyleHotReloader()
            inspector_shortcut = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
            inspector_shortcut.activated.connect(self._style_hot_reloader.show_inspector)
            self.show_status("Dev tools active: hot-reload ON  |  Ctrl+Shift+I = Style Inspector")
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
            icon_filename = AppStyle.TAB_ICON_FILES.get(icon_key)
            if icon_filename:
                self.tab_widget.setTabIcon(
                    index,
                    AppStyle.load_icon(self._workspace_root, icon_filename),
                )

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

    def publish_shared_display_settings(self, settings, source_tab=None):
        """Publish image display settings so all image tabs share contrast and colormap."""
        self.display_settings.update(settings)
        current_tab = self.tab_widget.currentWidget()
        if current_tab is not None and current_tab != source_tab and hasattr(current_tab, 'apply_shared_display_settings'):
            try:
                current_tab.apply_shared_display_settings(self.display_settings)
            except Exception as e:
                print(f"DEBUG: Error applying display settings to current tab: {e}")

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

    def _on_current_tab_changed(self, index):
        """Publish outgoing tab state and render the newly active tab."""
        previous_index = self._last_tab_index
        self._last_tab_index = index

        if 0 <= previous_index < self.tab_widget.count():
            previous_tab = self.tab_widget.widget(previous_index)
            if hasattr(previous_tab, 'auto_publish_current_image'):
                try:
                    if previous_tab.auto_publish_current_image():
                        return
                except Exception as e:
                    print(f"DEBUG: Error auto-publishing image from previous tab: {e}")

        self._render_current_tab_from_shared()

    def _render_current_tab_from_shared(self, *_args):
        """Render shared image data when a tab becomes active."""
        if self.image_data is None:
            return

        tab = self.tab_widget.currentWidget()
        if tab is None:
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

        if hasattr(tab, 'apply_shared_display_settings'):
            try:
                tab.apply_shared_display_settings(self.display_settings)
                return
            except Exception as e:
                print(f"DEBUG: Error applying display settings to active tab: {e}")

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
            self.show_status("Error: SciAnalysis not available")
            return None, None
            
        path, _ = dialog_open_file(self, "Open Image File", file_filters, key="image_open")
        if not path:
            return None, None
            
        try:
            # Use provided calibration or create a default one
            if calibration is None:
                calibration = CalibrationRQconv(wavelength_A=DEFAULT_CALIBRATION['wavelength_A'])
                calibration.set_pixel_size(pixel_size_um=DEFAULT_CALIBRATION['pixel_size_um'])
                calibration.set_distance(DEFAULT_CALIBRATION['distance_m'])
            
            image_data = Data2DScattering(path, calibration=calibration)
            
            # Store and propagate shared state
            self.publish_shared_image(image_data, image_path=path)
            self.publish_shared_calibration(calibration)
            
            # Update calibration with image size
            h, w = image_data.data.shape
            calibration.set_image_size(w, height=h)
            calibration.clear_maps()
            
            # Show success status
            self.show_status(f"Loaded image: {os.path.basename(path)} ({w}x{h} pixels)")
            
            return image_data, path
            
        except Exception as e:
            self.show_status(f"Error loading image: {str(e)}")
            print(f"Error loading image: {e}")
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
            self.show_status(f"Refreshing {tab_name}...")
            
            # Clear cache if it's the Image Browser tab
            if hasattr(current_tab, 'session_manager'):
                cache_info = current_tab.session_manager.get_cache_info()
                current_tab.session_manager.clear_session()
                self.show_status(f"Cleared {cache_info.get('cached_items', 0)} cached images")
            
            # Dynamic module discovery - attempt to find the tab class from the instance
            # This makes the refresh button future-proof for new tabs
            class_name = current_tab.__class__.__name__
            module_name = current_tab.__class__.__module__
            
            # Fallback to hardcoded map if dynamic discovery doesn't work
            if not module_name or 'tabs.' not in module_name:
                module_map = {
                    "Image Browser": "tabs.image_browser_tab.ImageBrowserApp",
                    "Calibration": "tabs.calibration_tab.CalibrationApp",
                    "Mask Editing": "tabs.mask_tab.MaskApp",
                    "Reduction": "tabs.reduction_tab.ReductionTab",
                    "Transform": "tabs.transform_tab.TransformTab",
                }
                
                if tab_name not in module_map:
                    self.show_status(f"Cannot refresh {tab_name} - unknown tab type")
                    return
                
                module_path = module_map[tab_name]
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
            
            self.show_status(f"✓ Refreshed {tab_name} successfully")
            
        except Exception as e:
            self.show_status(f"Error refreshing {tab_name}: {str(e)}")
            print(f"Error refreshing tab: {e}")
            import traceback
            traceback.print_exc()

    def _set_update_ui_enabled(self, enabled: bool):
        self.refresh_button.setEnabled(enabled)
        self.update_sciview_button.setEnabled(enabled)
        self.update_scianalysis_button.setEnabled(enabled)

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
            self.show_status("Another update is already running")
            return

        response = QMessageBox.question(
            self,
            title,
            confirm_message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if response != QMessageBox.Yes:
            self.show_status(f"{title} canceled")
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
            self.show_status(f"Failed to start update: {exc}")

    def _update_sciview_source(self):
        """Update the SciView checkout from its git remote."""
        command = self._build_sciview_update_command()
        if command is None:
            return

        self._start_update_process(
            title="Update SciView",
            confirm_message="This will run git pull --ff-only in the SciView repository. Continue?",
            command=command,
            running_message="Updating SciView source checkout...",
            success_message="SciView source updated. Restart SciView to use the new version.",
            failure_prefix="SciView update failed",
        )

    def _update_scianalysis_source(self):
        """Update the active SciAnalysis source."""
        if self._scianalysis_source_mode == "pixi":
            command = self._build_pixi_update_command()
            action_label = "Pixi-managed SciAnalysis package"
        else:
            command = self._build_git_update_command()
            action_label = "SciAnalysis checkout"

        if command is None:
            return

        self._start_update_process(
            title="Update SciAnalysis",
            confirm_message=f"This will update the active {action_label}. Continue?",
            command=command,
            running_message=f"Updating {action_label}...",
            success_message="SciAnalysis source updated. Restart SciView to use the new version.",
            failure_prefix="SciAnalysis update failed",
        )

    def _build_sciview_update_command(self):
        git_executable = shutil.which("git")
        if not git_executable:
            self.show_status("Git executable not found on PATH")
            QMessageBox.warning(
                self,
                "SciView Update",
                "Git was not found on PATH, so SciView cannot update from a repository checkout.",
            )
            return None

        if not (self._workspace_root / ".git").exists():
            self.show_status("SciView source is not a git checkout")
            QMessageBox.warning(
                self,
                "SciView Update",
                "The current SciView source is not a git checkout, so it cannot be updated with git pull.",
            )
            return None

        return [git_executable, "-C", str(self._workspace_root), "pull", "--ff-only"]

    def _build_pixi_update_command(self):
        pixi_executable = shutil.which("pixi")
        if not pixi_executable:
            self.show_status("Pixi executable not found on PATH")
            QMessageBox.warning(
                self,
                "SciAnalysis Update",
                "Pixi was not found on PATH, so the Pixi-managed SciAnalysis package cannot be updated.",
            )
            return None

        if not (self._workspace_root / "pixi.toml").exists():
            self.show_status("pixi.toml not found in workspace")
            QMessageBox.warning(
                self,
                "SciAnalysis Update",
                "pixi.toml was not found in the SciView workspace, so Pixi cannot update SciAnalysis here.",
            )
            return None

        return [pixi_executable, "update", "scitoolsscianalysis"]

    def _build_git_update_command(self):
        git_executable = shutil.which("git")
        if not git_executable:
            self.show_status("Git executable not found on PATH")
            QMessageBox.warning(
                self,
                "SciAnalysis Update",
                "Git was not found on PATH, so SciAnalysis cannot be updated from a checkout.",
            )
            return None

        if self._scianalysis_source_root is None:
            self.show_status("SciAnalysis checkout not configured")
            QMessageBox.warning(
                self,
                "SciAnalysis Update",
                "No SciAnalysis checkout is configured. Set SCIVIEW_SCIANALYSIS_SOURCE and SCIVIEW_SCIANALYSIS_PATH, or switch to pixi-managed SciAnalysis.",
            )
            return None

        if not (self._scianalysis_source_root / ".git").exists():
            self.show_status("SciAnalysis source is not a git checkout")
            QMessageBox.warning(
                self,
                "SciAnalysis Update",
                "The selected SciAnalysis source is not a git checkout, so it cannot be updated with git pull.",
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
            self.show_status(f"{self._update_running_message} still running")
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
                self.show_status(f"{self._update_failure_prefix}: {tail}")
            else:
                self.show_status(f"{self._update_failure_prefix} with exit code {return_code}")


def create_application():
    """Create and configure the main application"""
    app = QApplication(sys.argv)

    # Load layout/sizing ratios from runtime configuration before creating widgets.
    AppStyle.apply_gui_settings(GUI_SETTINGS)
    
    # Apply global styling
    AppStyle.apply_global_style(app)
    
    # Set application properties
    app.setApplicationName("SciAnalysis GUI")
    app.setApplicationVersion("2.0")
    app.setOrganizationName(BEAMLINE_NAME)
    
    # Create main window
    main_window = SciAnaApp()
    
    # Add tabs
    
    # Image Browser tab (first tab for primary image loading)
    try:
        from tabs.image_browser_tab import ImageBrowserApp
        image_browser_tab = ImageBrowserApp(main_window)
        main_window.add_tab(image_browser_tab, "Image Browser", icon_key="image_browser")
    except ImportError as e:
        print(f"Warning: Could not load image browser tab: {e}")
        placeholder = _build_placeholder_tab(f"Image Browser Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Image Browser", icon_key="image_browser")

    # Tiled Browser tab (metadata-first browsing and Tiled scan preview)
    try:
        from tabs.tiled_browser_tab import TiledBrowserTab
        tiled_browser_tab = TiledBrowserTab(main_window)
        main_window.add_tab(tiled_browser_tab, "Tiled Browser", icon_key="tiled_browser")
    except ImportError as e:
        print(f"Warning: Could not load tiled browser tab: {e}")
        placeholder = _build_placeholder_tab(f"Tiled Browser Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Tiled Browser", icon_key="tiled_browser")
    
    # Calibration tab
    try:
        if SCIANALYSIS_AVAILABLE:
            from tabs.calibration_tab import CalibrationApp
            calibration_tab = CalibrationApp(main_window)
            main_window.add_tab(calibration_tab, "Calibration", icon_key="calibration")
        else:
            placeholder = _build_placeholder_tab("Calibration Tab\\n(SciAnalysis not available)")
            main_window.add_tab(placeholder, "Calibration", icon_key="calibration")
    
    except ImportError as e:
        print(f"Warning: Could not load calibration tab: {e}")
        placeholder = _build_placeholder_tab(f"Calibration Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Calibration", icon_key="calibration")
    
    # Mask editing tab
    try:
        from tabs.mask_tab import MaskApp
        mask_tab = MaskApp(main_window)
        main_window.add_tab(mask_tab, "Mask Editing", icon_key="mask_editing")
    except ImportError as e:
        print(f"Warning: Could not load mask tab: {e}")
        placeholder = _build_placeholder_tab(f"Mask Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Mask Editing", icon_key="mask_editing")

    # Reduction tab
    try:
        from tabs.reduction_tab import ReductionTab
        reduction_tab = ReductionTab(main_window)
        main_window.add_tab(reduction_tab, "Reduction", icon_key="reduction")
    except ImportError as e:
        print(f"Warning: Could not load reduction tab: {e}")
        placeholder = _build_placeholder_tab(f"Reduction Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Reduction", icon_key="reduction")

    # Transform tab
    try:
        from tabs.transform_tab import TransformTab
        transform_tab = TransformTab(main_window)
        main_window.add_tab(transform_tab, "Transform", icon_key="transform")
    except ImportError as e:
        print(f"Warning: Could not load transform tab: {e}")
        placeholder = _build_placeholder_tab(f"Transform Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Transform", icon_key="transform")

    # Batch tab placeholder (reserved for future development)
    batch_placeholder = _build_placeholder_tab(
        "Batch Tab\\n(Placeholder for future batch processing workflows)"
    )
    main_window.add_tab(batch_placeholder, "Batch", icon_key="batch")

    # Info tab
    try:
        from tabs.info_tab import InfoTab
        info_tab = InfoTab(main_window)
        main_window.add_tab(info_tab, "Info", icon_key="info")
    except ImportError as e:
        print(f"Warning: Could not load info tab: {e}")
        placeholder = _build_placeholder_tab(f"Info Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Info", icon_key="info")
    
    return app, main_window


def main():
    """Main entry point"""
    try:
        app, main_window = create_application()
        main_window.show()
        
        # Show startup status
        status_msg = f"SciAnalysis GUI started for {BEAMLINE_NAME}"
        if SCIANALYSIS_AVAILABLE:
            status_msg += " - SciAnalysis loaded successfully"
        else:
            status_msg += " - SciAnalysis not available"
        main_window.show_status(status_msg)
        
        sys.exit(app.exec_())
        
    except Exception as e:
        print(f"Fatal error starting application: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
