"""
Base Image Tab Module

This module contains the BaseImageTab class which provides common
image-related functionality that can be reused across different tabs.
"""

import os
import sys
import numpy as np
import datetime

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QDoubleSpinBox, QLineEdit, QComboBox, QGridLayout, QFileDialog,
    QTextEdit
)
from PyQt5.QtCore import Qt

import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)

# Import configuration
from config.beamline_config import (
    DEFAULT_CALIBRATION, PHYSICAL_CONSTANTS, get_file_status
)

# Get constants
HC_E = PHYSICAL_CONSTANTS['hc_over_e_eV_A']


class BaseImageTab(QWidget):
    """Base class for tabs that work with images and provide status information"""
    
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.image_data = None
        
        # Initialize SciAnalysis availability
        self.scianalysis_available = self._check_scianalysis_availability()
        
        # Initialize calibration from config
        self._init_calibration()
        
        # Image-related attributes that will be set by load_image
        self.export_cali_path = None
        self.mask_path = None
        self.custom_mask_path = None
        self.mask_dir = None
        self.measurement_type = None

        # Image information lines
        self.info_lines = []

    def _check_scianalysis_availability(self):
        """Check if SciAnalysis is available"""
        try:
            from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv
            return True
        except ImportError:
            print("Warning: SciAnalysis not available - using mock mode")
            return False

    def _init_calibration(self):
        """Initialize calibration object"""
        if self.scianalysis_available:
            try:
                from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv
                self.calibration = CalibrationRQconv(wavelength_A=DEFAULT_CALIBRATION['wavelength_A'])
                self.calibration.set_pixel_size(pixel_size_um=DEFAULT_CALIBRATION['pixel_size_um'])
                self.calibration.set_distance(DEFAULT_CALIBRATION['distance_m'])
            except Exception as e:
                print(f"Warning: Failed to initialize SciAnalysis calibration: {e}")
                self.calibration = None
                self.scianalysis_available = False
        else:
            self.calibration = None

    def _create_image_info_panel(self):
        """Create the image information display panel (reusable across tabs)"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        # Title
        title = QLabel("Image Information")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        # Scrollable text area for image info
        self.image_info_text = QTextEdit()
        self.image_info_text.setReadOnly(True)
        self.image_info_text.setMaximumHeight(120)  # Compact height
        self.image_info_text.setStyleSheet("""
            QTextEdit {
                font-family: 'Courier New', monospace;
                font-size: 10px;
                background-color: #f8f8f8;
                border: 1px solid #ccc;
                padding: 5px;
            }
        """)
        
        # Set initial text
        self._set_initial_image_info_text()
        
        layout.addWidget(self.image_info_text)
        
        return panel

    def _set_initial_image_info_text(self):
        """Set initial text for image info panel"""
        initial_text = "No image loaded\n\nLoad an image to see detailed information about:\n"
        initial_text += "• File path and metadata\n"
        initial_text += "• Image dimensions and statistics\n"
        initial_text += "• Measurement type (SAXS/WAXS/MAXS)\n"
        initial_text += "• Detector configuration\n"
        initial_text += "• Calibration status\n"
        initial_text += "• Processing parameters"
        self.image_info_text.setPlainText(initial_text)

    def load_image(self):
        """Load image using shared application method"""
        if self.scianalysis_available:
            image_data, path = self.parent_app.load_image(calibration=self.calibration)
        else:
            image_data, path = self.parent_app.load_image(calibration=None)
        
        if image_data is not None and path is not None:
            self.image_data = image_data
            
            # Update filename display if available
            if hasattr(self, 'filename_label'):
                self.filename_label.setText(f"File Name: {os.path.basename(path)}")
            
            # Reset canvas views when loading new image
            self._reset_canvas_views()
            
            # Get file status for mask and export settings
            file_status = get_file_status(os.path.basename(path))
            self.export_cali_path = file_status['calibration_file']
            self.mask_path = file_status['mask_file']
            self.custom_mask_path = file_status['custom_mask']
            self.mask_dir = file_status['mask_dir']
            self.measurement_type = file_status['measurement_type']
            
            # Populate image information panel
            self.populate_image_info(image_data, path)
            
            # Trigger plot update if method exists
            if hasattr(self, 'update_plot'):
                self.update_plot()

    def _reset_canvas_views(self):
        """Reset canvas views to default when loading new image"""
        try:
            # Reset raw image axes to auto-scale
            if hasattr(self, 'ax_raw'):
                self.ax_raw.clear()
                self.ax_raw.set_xlim(None, None)  # Auto-scale
                self.ax_raw.set_ylim(None, None)  # Auto-scale
                if hasattr(self, 'canvas_raw'):
                    self.canvas_raw.draw()
            
            # Reset plot axes to auto-scale  
            if hasattr(self, 'ax_plot'):
                self.ax_plot.clear()
                self.ax_plot.set_xlim(None, None)  # Auto-scale
                self.ax_plot.set_ylim(None, None)  # Auto-scale
                if hasattr(self, 'canvas_plot'):
                    self.canvas_plot.draw()
                    
            # Reset any zoom/pan states in navigation toolbars
            if hasattr(self, 'canvas_raw') and hasattr(self.canvas_raw, 'toolbar'):
                try:
                    self.canvas_raw.toolbar.home()
                except:
                    pass
                    
            if hasattr(self, 'canvas_plot') and hasattr(self.canvas_plot, 'toolbar'):
                try:
                    self.canvas_plot.toolbar.home()
                except:
                    pass
                    
        except Exception as e:
            # Silently handle any errors during reset
            pass

    def populate_image_info(self, image_data, image_path):
        """Populate the image information panel with file details and status"""
        try:
            info_lines = []
            
            # === APPLICATION STATUS ===
            info_lines.append("=== APPLICATION STATUS ===")
            info_lines.append(f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # File information
            if image_path:
                info_lines.append(f"Loaded: {os.path.basename(image_path)}")
                info_lines.append(f"Path: {image_path}")
                if os.path.exists(image_path):
                    file_size = os.path.getsize(image_path)
                    info_lines.append(f"Size: {file_size:,} bytes")
                    mod_time = os.path.getmtime(image_path)
                    mod_time_str = datetime.datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M:%S")
                    info_lines.append(f"Modified: {mod_time_str}")
            
            # Beamline configuration status
            if hasattr(self, 'measurement_type') and self.measurement_type:
                info_lines.append(f"Measurement: {self.measurement_type}")
            if hasattr(self, 'export_cali_path') and self.export_cali_path:
                info_lines.append(f"Calibration file: {self.export_cali_path}")
            if hasattr(self, 'mask_path') and self.mask_path:
                info_lines.append(f"Mask file: {self.mask_path}")
            
            info_lines.append("")  # Blank line separator
            
            # === IMAGE DATA ===
            info_lines.append("=== IMAGE DATA ===")
            if image_data is not None:
                if hasattr(image_data, 'data'):
                    shape = image_data.data.shape
                    dtype = image_data.data.dtype
                    info_lines.append(f"Dimensions: {shape[1]} x {shape[0]} pixels")
                    info_lines.append(f"Data type: {dtype}")
                    info_lines.append(f"Value range: {image_data.data.min():.2f} to {image_data.data.max():.2f}")
                    info_lines.append(f"Mean: {image_data.data.mean():.2f}")
                    info_lines.append(f"Std dev: {image_data.data.std():.2f}")
                elif hasattr(image_data, 'shape'):
                    shape = image_data.shape
                    dtype = image_data.dtype
                    info_lines.append(f"Dimensions: {shape[1]} x {shape[0]} pixels")
                    info_lines.append(f"Data type: {dtype}")
                    info_lines.append(f"Value range: {image_data.min():.2f} to {image_data.max():.2f}")
                    info_lines.append(f"Mean: {image_data.mean():.2f}")
                    info_lines.append(f"Std dev: {image_data.std():.2f}")
            else:
                info_lines.append("No image data loaded")
            
            info_lines.append("")  # Blank line separator
            
            # === CALIBRATION STATUS ===
            info_lines.append("=== CALIBRATION STATUS ===")
            info_lines.append(f"SciAnalysis: {'Available' if self.scianalysis_available else 'Not available'}")
            if hasattr(self, 'spin_wl_ang'):
                # If wavelength control exists, show calibration parameters
                info_lines.append(f"Wavelength: {self.spin_wl_ang.value():.4f} Å")
                info_lines.append(f"Energy: {self.spin_energy_ev.value():.1f} eV")
                info_lines.append(f"Beam center: ({self.spin_x.value():.1f}, {self.spin_y.value():.1f})")
                info_lines.append(f"Distance: {self.spin_dist.value():.3f} m")
                info_lines.append(f"Pixel size: {self.spin_pixel.value():.1f} µm")
                if hasattr(self, 'spin_orient'):
                    info_lines.append(f"Detector orient: {self.spin_orient.value():.1f}°")
                    info_lines.append(f"Detector tilt: {self.spin_tilt.value():.1f}°")
                    info_lines.append(f"Detector phi: {self.spin_phi.value():.1f}°")
            else:
                info_lines.append("Calibration parameters: Using defaults")
                info_lines.append(f"Wavelength: {DEFAULT_CALIBRATION['wavelength_A']:.4f} Å")
                info_lines.append(f"Energy: {DEFAULT_CALIBRATION['energy_eV']:.1f} eV")
            
            # Add tab-specific status information
            self._add_tab_specific_status(info_lines)
            
            # Set the text in the info panel
            self.image_info_text.setPlainText('\n'.join(info_lines))
            
        except Exception as e:
            error_info = f"Error loading image info: {str(e)}\n\n"
            error_info += f"Exception type: {type(e).__name__}\n"
            error_info += f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.image_info_text.setPlainText(error_info)

    def _add_tab_specific_status(self, info_lines):
        """Override this method in subclasses to add tab-specific status information"""
        # This method should be overridden by subclasses to add their own status sections
        pass

    def update_status_info(self):
        """Update status information without changing image data"""
        if hasattr(self, 'image_data') and self.image_data is not None:
            # Get the current image path if available
            image_path = getattr(self.parent_app, '_current_image_path', None) if hasattr(self.parent_app, '_current_image_path') else None
            self.populate_image_info(self.image_data, image_path)
        else:
            # Just update timestamp and show no image loaded
            info_text = f"No image loaded\n\nLast update: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            info_text += "Load an image to see detailed status information including:\n"
            info_text += "• File information and metadata\n"
            info_text += "• Image data statistics\n"
            info_text += "• Current calibration parameters\n"
            info_text += "• Processing status\n"
            info_text += "• Beamline configuration status"
            self.image_info_text.setPlainText(info_text)

    def on_mouse_move(self, event):
        """Handle mouse movement over plots (common functionality)"""
        # Display pixel value or plot coordinates
        if not event.inaxes:
            return
        if hasattr(self, 'ax_raw') and event.inaxes == self.ax_raw and self.image_data is not None:
            x, y = int(event.xdata), int(event.ydata)
            if hasattr(self.image_data, 'data'):
                h, w = self.image_data.data.shape
                if 0 <= x < w and 0 <= y < h:
                    val = self.image_data.data[y, x]
                    self.parent_app.show_status(f"Raw Pixel (x={x}, y={y}) = {val:.2f}")
            elif hasattr(self.image_data, 'shape'):
                h, w = self.image_data.shape
                if 0 <= x < w and 0 <= y < h:
                    val = self.image_data[y, x]
                    self.parent_app.show_status(f"Raw Pixel (x={x}, y={y}) = {val:.2f}")
        elif hasattr(self, 'ax_plot') and event.inaxes == self.ax_plot:
            x, y = event.xdata, event.ydata
            self.parent_app.show_status(f"Q={x:.3f}, I={y:.2f}")

    def create_load_button(self, parent_layout=None):
        """Create a standardized load image button"""
        btn_load = QPushButton("Load Image")
        btn_load.clicked.connect(self.load_image)
        btn_load.setMaximumHeight(30)  # Compact button
        if parent_layout:
            parent_layout.addWidget(btn_load)
        return btn_load

    def create_filename_label(self, parent_layout=None):
        """Create a standardized filename display label"""
        self.filename_label = QLabel("File Name: No image loaded")
        self.filename_label.setStyleSheet("font-size: 10px;")
        if parent_layout:
            parent_layout.addWidget(self.filename_label)
        return self.filename_label