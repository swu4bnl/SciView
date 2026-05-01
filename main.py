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
    QPushButton, QWidget, QHBoxLayout, QVBoxLayout
)
from PyQt5.QtCore import Qt, QTimer

# Import configuration
from config.beamline_config import (
    SCIANALYSIS_PATH, GUI_SETTINGS, BEAMLINE_NAME
)
from config.app_style import AppStyle

# Ensure SciAnalysis is on the path
if SCIANALYSIS_PATH not in sys.path:
    sys.path.append(SCIANALYSIS_PATH)

# Import configuration including SciAnalysis availability
from config.beamline_config import (
    get_file_status, DEFAULT_CALIBRATION, BEAMLINE_NAME, GUI_SETTINGS, 
    SCIANALYSIS_AVAILABLE
)
from config.app_style import *

# Import SciAnalysis dependencies only if available  
if SCIANALYSIS_AVAILABLE:
    from SciAnalysis.XSAnalysis.Data import Data2DScattering
    from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv
from utils.calibration_utils import calibration_manager
from utils.resource_monitor import get_resource_monitor


class SciAnaApp(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"SciAnalysis GUI - {BEAMLINE_NAME}")
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
            
        from PyQt5.QtWidgets import QFileDialog
        
        path, _ = QFileDialog.getOpenFileName(self, "Open Image File", "", file_filters)
        if not path:
            return None, None
            
        try:
            # Use provided calibration or create a default one
            if calibration is None:
                calibration = CalibrationRQconv(wavelength_A=DEFAULT_CALIBRATION['wavelength_A'])
                calibration.set_pixel_size(pixel_size_um=DEFAULT_CALIBRATION['pixel_size_um'])
                calibration.set_distance(DEFAULT_CALIBRATION['distance_m'])
            
            image_data = Data2DScattering(path, calibration=calibration)
            
            # Store in application state
            self.image_data = image_data
            self.image_path = path
            self.calibration = calibration
            
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
    
    def get_image_data(self):
        """Get the currently loaded image data"""
        return self.image_data
    
    def get_image_path(self):
        """Get the currently loaded image path"""
        return self.image_path
    
    def get_calibration(self):
        """Get the current calibration object"""
        return self.calibration
    
    def set_calibration(self, calibration):
        """Update the current calibration object"""
        self.calibration = calibration
    
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
                    # "Data Reduction": "tabs.data_reduction_tab.DataReductionApp",
                    "Protocol": "tabs.protocol_preview_tab.ProtocolPreviewApp"
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
        from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        layout.addWidget(QLabel(f"Image Browser Tab\\n(Import error: {e})"))
        main_window.add_tab(placeholder, "Image Browser")
    
    # Calibration tab
    try:
        if SCIANALYSIS_AVAILABLE:
            from tabs.calibration_tab import CalibrationApp
            calibration_tab = CalibrationApp(main_window)
            main_window.add_tab(calibration_tab, "Calibration")
        else:
            from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
            placeholder = QWidget()
            layout = QVBoxLayout(placeholder)
            layout.addWidget(QLabel("Calibration Tab\\n(SciAnalysis not available)"))
            main_window.add_tab(placeholder, "Calibration")
    
    except ImportError as e:
        print(f"Warning: Could not load calibration tab: {e}")
        from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        layout.addWidget(QLabel(f"Calibration Tab\\n(Import error: {e})"))
        main_window.add_tab(placeholder, "Calibration")
    
    # Mask editing tab
    try:
        from tabs.mask_tab import MaskApp
        mask_tab = MaskApp(main_window)
        main_window.add_tab(mask_tab, "Mask Editing")
    except ImportError as e:
        print(f"Warning: Could not load mask tab: {e}")
        from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        layout.addWidget(QLabel(f"Mask Tab\\n(Import error: {e})"))
        main_window.add_tab(placeholder, "Mask Editing")
    
    # Protocol Preview tab
    # Under development
    try:
        if SCIANALYSIS_AVAILABLE:
            from tabs.protocol_preview_tab import ProtocolPreviewApp
            protocol_tab = ProtocolPreviewApp(main_window)
            main_window.add_tab(protocol_tab, "Protocol(test)")
        else:
            from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
            placeholder = QWidget()
            layout = QVBoxLayout(placeholder)
            layout.addWidget(QLabel("Protocol Tab\\n(SciAnalysis not available)"))
            main_window.add_tab(placeholder, "Protocol")
    except ImportError as e:
        print(f"Warning: Could not load protocol preview tab: {e}")
        from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        layout.addWidget(QLabel(f"Protocol Tab\\n(Import error: {e})"))
        main_window.add_tab(placeholder, "Protocol")
    
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