"""
SciAnalysis GUI - Main Application

A modular PyQt5-based GUI for X-ray scattering data analysis and calibration.
Designed for easy adaptation to different beamlines and analysis workflows.
"""

import sys
import os
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
    QApplication, QMainWindow, QTabWidget, QLabel,
    QPushButton
)
from PyQt5.QtCore import Qt, QTimer

# Import configuration from package modules.
from sciview.interfaces.theme.app_style import AppStyle, apply_info_style
from sciview.profiles.cms_profile import BEAMLINE_NAME, DEFAULT_CALIBRATION
from sciview.settings.app_settings import GUI_SETTINGS, SCIANALYSIS_AVAILABLE, SCIANALYSIS_PATH

# Ensure SciAnalysis is on the path
if SCIANALYSIS_PATH not in sys.path:
    sys.path.append(SCIANALYSIS_PATH)

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
        
        # Tab widget
        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)
        
        # Refresh button - add to tab widget's corner
        self.refresh_button = QPushButton("🔄")
        self.refresh_button.setToolTip("Reload current tab and clear cache (Ctrl+R)")
        self.refresh_button.setFixedSize(30, 25)
        self.refresh_button.clicked.connect(self._refresh_current_tab)
        
        # Use QTabWidget's corner widget feature to place button on same line as tabs
        self.tab_widget.setCornerWidget(self.refresh_button, Qt.TopRightCorner)
        
        # Shared application state
        self.image_data = None
        self.image_path = None
        self.calibration = None
        self.mask = None
        
        # Set initial window size from config
        window_size = GUI_SETTINGS['default_window_size']
        self.resize(*window_size)

        # Keep app usable on small displays by enforcing configurable minimums
        min_window_size = GUI_SETTINGS.get('minimum_window_size')
        if min_window_size:
            self.setMinimumSize(*min_window_size)
        
        # Setup resource monitoring
        self._setup_resource_monitor()
        
        # Setup keyboard shortcut for refresh
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self.refresh_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        self.refresh_shortcut.activated.connect(self._refresh_current_tab)

    def add_tab(self, widget, name):
        """Add a tab to the main interface"""
        self.tab_widget.addTab(widget, name)

    def publish_shared_image(self, image_data, image_path=None, source_tab=None):
        """Publish active image into shared app state and propagate to tabs."""
        self.image_data = image_data
        if image_path is not None:
            self.image_path = image_path

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

            if hasattr(tab, 'update_plot'):
                try:
                    tab.update_plot()
                except Exception as e:
                    print(f"DEBUG: Error syncing plot for tab {i}: {e}")

    def show_status(self, msg):
        """Display status message"""
        self.status.showMessage(msg)
    
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
    
    def update_all_displays(self):
        """Update display across all tabs when display settings change"""
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            
            if hasattr(tab, 'update_plot'):
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
                    "Reduction": "tabs.reduction_tab.ReductionTab"
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


def create_application():
    """Create and configure the main application"""
    app = QApplication(sys.argv)
    
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
        main_window.add_tab(image_browser_tab, "Image Browser")
    except ImportError as e:
        print(f"Warning: Could not load image browser tab: {e}")
        placeholder = _build_placeholder_tab(f"Image Browser Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Image Browser")

    # Tiled Browser tab (metadata-first browsing and Tiled scan preview)
    try:
        from tabs.tiled_browser_tab import TiledBrowserTab
        tiled_browser_tab = TiledBrowserTab(main_window)
        main_window.add_tab(tiled_browser_tab, "Tiled Browser")
    except ImportError as e:
        print(f"Warning: Could not load tiled browser tab: {e}")
        placeholder = _build_placeholder_tab(f"Tiled Browser Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Tiled Browser")
    
    # Calibration tab
    try:
        if SCIANALYSIS_AVAILABLE:
            from tabs.calibration_tab import CalibrationApp
            calibration_tab = CalibrationApp(main_window)
            main_window.add_tab(calibration_tab, "Calibration")
        else:
            placeholder = _build_placeholder_tab("Calibration Tab\\n(SciAnalysis not available)")
            main_window.add_tab(placeholder, "Calibration")
    
    except ImportError as e:
        print(f"Warning: Could not load calibration tab: {e}")
        placeholder = _build_placeholder_tab(f"Calibration Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Calibration")
    
    # Mask editing tab
    try:
        from tabs.mask_tab import MaskApp
        mask_tab = MaskApp(main_window)
        main_window.add_tab(mask_tab, "Mask Editing")
    except ImportError as e:
        print(f"Warning: Could not load mask tab: {e}")
        placeholder = _build_placeholder_tab(f"Mask Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Mask Editing")

    # Reduction tab
    try:
        from tabs.reduction_tab import ReductionTab
        reduction_tab = ReductionTab(main_window)
        main_window.add_tab(reduction_tab, "Reduction")
    except ImportError as e:
        print(f"Warning: Could not load reduction tab: {e}")
        placeholder = _build_placeholder_tab(f"Reduction Tab\\n(Import error: {e})")
        main_window.add_tab(placeholder, "Reduction")
    
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
