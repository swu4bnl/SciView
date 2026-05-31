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

# Import configuration from package modules.
from sciview.interfaces.theme.app_style import *
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION, get_detector_config, get_file_status as get_profile_file_status
from sciview.settings.app_settings import MASK_BASE_DIR, PHYSICAL_CONSTANTS, SCIANALYSIS_AVAILABLE
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array, get_image_info

# Get constants
HC_E = PHYSICAL_CONSTANTS['hc_over_e_eV_A']


class BaseImageTab(QWidget):
    """Base class for tabs that work with images and provide status information"""
    
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.image_data = None
        
        # Initialize SciAnalysis availability from config
        self.scianalysis_available = SCIANALYSIS_AVAILABLE
        
        # Initialize calibration from config
        self._init_calibration()
        
        # Shared display state - all tabs will use these
        self.display_settings = {
            'vmin': -2,
            'vmax': 1000,
            'cmap': 'gray',
            'scale': 'linear'
        }
        
        # Image-related attributes that will be set by load_image
        self.export_cali_path = None
        self.mask_path = None
        self.custom_mask_path = None
        self.mask_dir = None
        self.measurement_type = None

        # Image information lines
        self.info_lines = []
        
        # Display hooks for tab-specific extensions
        self.pre_display_hooks = []
        self.post_display_hooks = []
        self._last_image_shape = None

    def _set_image_info_text(self, text):
        """Update image info text when an info widget is available."""
        if hasattr(self, 'image_info_text') and self.image_info_text is not None:
            self.image_info_text.setPlainText(text)

    def _sanitize_log_limits(self, img_array, vmin, vmax):
        """Return safe positive limits for log display or (None, None) if unavailable."""
        finite_positive = img_array[np.isfinite(img_array) & (img_array > 0)]
        if finite_positive.size == 0:
            return None, None

        min_positive = float(np.min(finite_positive))
        max_positive = float(np.max(finite_positive))

        safe_vmin = float(vmin) if vmin is not None and vmin > 0 else min_positive
        safe_vmax = float(vmax) if vmax is not None and vmax > safe_vmin else max_positive

        if safe_vmax <= safe_vmin:
            safe_vmax = max_positive
        if safe_vmax <= safe_vmin:
            safe_vmax = safe_vmin * 10.0

        return safe_vmin, safe_vmax

    def _init_calibration(self):
        """Initialize calibration object"""
        if self.scianalysis_available:
            try:
                from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv
                self.calibration = CalibrationRQconv(wavelength_A=DEFAULT_CALIBRATION['wavelength_A'])
                self.calibration.set_pixel_size(pixel_size_um=DEFAULT_CALIBRATION['pixel_size_um'])
                self.calibration.set_distance(DEFAULT_CALIBRATION['distance_m'])
                self.calibration.set_beam_position(
                    DEFAULT_CALIBRATION['beam_center_x'],
                    DEFAULT_CALIBRATION['beam_center_y'],
                )
                if hasattr(self.calibration, 'set_angles'):
                    self.calibration.set_angles(
                        det_orient=DEFAULT_CALIBRATION['detector_orient_deg'],
                        det_tilt=DEFAULT_CALIBRATION['detector_tilt_deg'],
                        det_phi=DEFAULT_CALIBRATION['detector_phi_deg'],
                    )
            except Exception as e:
                print(f"Warning: Failed to initialize SciAnalysis calibration: {e}")
                self.calibration = None
        else:
            self.calibration = None

    def _create_calibration_for_detector(self, measurement_type):
        """
        Create or update calibration object for specific detector type
        
        Args:
            measurement_type: 'saxs', 'waxs', 'maxs', or None
            
        Returns:
            CalibrationRQconv object configured for the detector
        """
        if not self.scianalysis_available:
            return None
            
        try:
            from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv

            detector_config = get_detector_config(measurement_type or 'waxs')
            
            # Use existing calibration if available, or create new one
            if hasattr(self, 'calibration') and self.calibration is not None:
                calibration = self.calibration
            else:
                calibration = CalibrationRQconv(wavelength_A=DEFAULT_CALIBRATION['wavelength_A'])
            
            # Update with detector-specific parameters
            calibration.set_pixel_size(pixel_size_um=detector_config['pixel_size_um'])
            calibration.set_distance(detector_config['default_distance_m'])
            calibration.set_beam_position(detector_config['beam_center_x'], detector_config['beam_center_y'])
            
            # Set angles to prevent None values - this is the missing piece!
            calibration.set_angles(
                det_orient=DEFAULT_CALIBRATION['detector_orient_deg'],
                det_tilt=DEFAULT_CALIBRATION['detector_tilt_deg'], 
                det_phi=DEFAULT_CALIBRATION['detector_phi_deg']
            )
            
            return calibration
            
        except Exception as e:
            print(f"Warning: Could not create calibration: {e}")
            return None

    def create_data2d_object(self, image_array, file_path):
        """
        Create a properly configured Data2DScattering object from image array
        
        Uses beamline configuration to automatically detect measurement type (SAXS/WAXS/MAXS)
        and apply appropriate detector configuration.
        
        Args:
            image_array: numpy array with image data
            file_path: path to the image file (for type detection)
            
        Returns:
            Data2DScattering object or numpy array if SciAnalysis not available
        """
        if not self.scianalysis_available:
            return image_array
        
        try:
            from SciAnalysis.XSAnalysis.Data import Data2DScattering

            # Detect measurement type and get appropriate configuration
            filename = os.path.basename(file_path)
            file_status = get_profile_file_status(filename, mask_dir=MASK_BASE_DIR)
            measurement_type = file_status['measurement_type']
            print(f"Creating Data2DScattering for {measurement_type}")
            
            # Create or reuse calibration for the specific detector
            calibration = self._create_calibration_for_detector(measurement_type)
            if calibration is None:
                return image_array
            
            # Create Data2DScattering object (correctly)
            if isinstance(image_array, np.ndarray):
                # Create empty Data2DScattering object, then set data and calibration
                data_obj = Data2DScattering(name=filename)
                data_obj.data = image_array
                data_obj.calibration = calibration
                
                # Update calibration with actual image size
                h, w = image_array.shape
                calibration.set_image_size(w, height=h)
                calibration.clear_maps()
                
                return data_obj
            else:
                # Already a Data2DScattering object
                return image_array
                
        except Exception as e:
            print(f"Warning: Could not create Data2DScattering object: {e}")
            import traceback
            traceback.print_exc()
            return image_array

    def add_display_hook(self, hook_func, position='post'):
        """
        Add a display hook function for tab-specific customizations
        
        Args:
            hook_func: Function to call during display update
            position: 'pre' or 'post' - when to call the hook
        """
        if position == 'pre':
            self.pre_display_hooks.append(hook_func)
        else:
            self.post_display_hooks.append(hook_func)

    def update_display_settings(self, **kwargs):
        """Update shared display settings and refresh all tabs"""
        # TODO: This is not working as intended - fix later
        self.display_settings.update(kwargs)
        
        # Notify all tabs to update their displays
        if hasattr(self.parent_app, 'update_all_displays'):
            self.parent_app.update_all_displays()
        else:
            # Fallback: just update this tab
            self.update_plot()

    def get_display_values(self):
        """Get current display values with validation"""
        try:
            vmin = float(self.display_settings['vmin'])
            vmax = float(self.display_settings['vmax'])
        except (ValueError, TypeError):
            vmin = vmax = None
        
        return {
            'vmin': vmin,
            'vmax': vmax,
            'cmap': self.display_settings['cmap'],
            'scale': self.display_settings['scale']
        }

    def _on_vmin_changed(self):
        """Handle vmin change"""
        try:
            vmin = float(self.vmin_input.text())
            self.update_display_settings(vmin=vmin)
        except ValueError:
            pass

    def _on_vmax_changed(self):
        """Handle vmax change"""
        try:
            vmax = float(self.vmax_input.text())
            self.update_display_settings(vmax=vmax)
        except ValueError:
            pass

    def _on_cmap_changed(self, cmap):
        """Handle colormap change"""
        self.update_display_settings(cmap=cmap)

    def _on_scale_changed(self, scale):
        """Handle scale change"""
        self.update_display_settings(scale=scale)

    def sync_display_controls(self):
        """Sync display controls with current settings"""
        self.vmin_input.setText(str(self.display_settings['vmin']))
        self.vmax_input.setText(str(self.display_settings['vmax']))
        self.cmap_selector.setCurrentText(self.display_settings['cmap'])
        self.img_scale_combo.setCurrentText(self.display_settings['scale'])

    def _create_image_panel(self):
        """Create the image display panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)  # Remove all spacing
        
        # Image display title
        title = QLabel("Raw Image")
        apply_subtitle_style(title)
        layout.addWidget(title)

        # Dynamic filename label
        self.filename_label = QLabel("File Name: No image loaded")
        apply_info_style(self.filename_label)
        layout.addWidget(self.filename_label)

        # Create matplotlib figure at 85% zoom for better space utilization
        self.fig_raw, self.ax_raw = plt.subplots(figsize=(5.1, 6.8))
        # Reduce margins around the image
        self.fig_raw.subplots_adjust(left=0.08, bottom=0.08, right=0.99, top=0.92)
        
        self.canvas_raw = FigureCanvas(self.fig_raw)
        layout.addWidget(self.canvas_raw)
        layout.addStretch()
        
        # Compact navigation toolbar
        toolbar_raw = NavigationToolbar(self.canvas_raw, self)
        toolbar_raw.setMaximumHeight(25)
        layout.addWidget(toolbar_raw)

        # Image controls - now shared across all tabs
        img_ctrl = QHBoxLayout()
        img_ctrl.addWidget(QLabel("vmin:"))
        self.vmin_input = QLineEdit(str(self.display_settings['vmin']))
        self.vmin_input.editingFinished.connect(self._on_vmin_changed)
        img_ctrl.addWidget(self.vmin_input)
        
        img_ctrl.addWidget(QLabel("vmax:"))
        self.vmax_input = QLineEdit(str(self.display_settings['vmax']))
        self.vmax_input.editingFinished.connect(self._on_vmax_changed)
        img_ctrl.addWidget(self.vmax_input)
        
        img_ctrl.addWidget(QLabel("cmap:"))
        self.cmap_selector = QComboBox()
        self.cmap_selector.addItems(['gray', 'viridis', 'plasma', 'inferno', 'jet'])
        self.cmap_selector.setCurrentText(self.display_settings['cmap'])
        self.cmap_selector.currentTextChanged.connect(self._on_cmap_changed)
        img_ctrl.addWidget(self.cmap_selector)
        
        img_ctrl.addWidget(QLabel("scale:"))
        self.img_scale_combo = QComboBox()
        self.img_scale_combo.addItems(["linear", "log"])
        self.img_scale_combo.setCurrentText(self.display_settings['scale'])
        self.img_scale_combo.currentTextChanged.connect(self._on_scale_changed)
        img_ctrl.addWidget(self.img_scale_combo)
        layout.addLayout(img_ctrl)
        
        return panel

    def _create_image_info_panel(self):
        """Create the image information display panel (reusable across tabs)"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        # Title
        title = QLabel("Image Information")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Scrollable text area for image info
        self.image_info_text = QTextEdit()
        self.image_info_text.setReadOnly(True)
        apply_info_style(self.image_info_text)
        
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
        self._set_image_info_text(initial_text)

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
            file_status = get_profile_file_status(os.path.basename(path), mask_dir=MASK_BASE_DIR)
            self.export_cali_path = file_status['calibration_file']
            self.mask_path = file_status['mask_file']
            self.custom_mask_path = file_status.get('custom_mask')
            self.mask_dir = file_status['mask_dir']
            self.measurement_type = file_status['measurement_type']
            
            # Populate image information panel
            self.populate_image_info(image_data, path)
            
            # Trigger plot update if method exists
            if hasattr(self, 'update_plot'):
                self.update_plot()

    def update_plot(self, image_data=None):
        """Update plots based on current image data - THE SINGLE METHOD FOR ALL IMAGE DISPLAY
        
        Args:
            image_data: Optional image data to display. If None, uses self.image_data.
                       Allows passing data directly without storing in self.image_data,
                       which improves memory efficiency for on-demand loading.
        """
        # Use provided data or fall back to instance variable
        display_data = image_data if image_data is not None else self.image_data
        
        # If no local image_data, pull from parent_app (synced by Image Browser)
        if display_data is None and hasattr(self, 'parent_app') and hasattr(self.parent_app, 'image_data'):
            display_data = self.parent_app.image_data
        
        if display_data is None:
            return

        # Refresh image filename display if available
        if hasattr(self, 'filename_label') and hasattr(display_data, 'name'):
            self.filename_label.setText(f"File Name: {display_data.name}")

        # Store current limits only if they are not default/unset
        raw_xlim, raw_ylim = self.ax_raw.get_xlim(), self.ax_raw.get_ylim()
        
        # Check if limits are meaningful (not default matplotlib values)
        raw_xlim_valid = not np.allclose(raw_xlim, (0, 1))
        raw_ylim_valid = not np.allclose(raw_ylim, (0, 1))

        # Call pre-display hooks
        for hook in self.pre_display_hooks:
            hook(self.ax_raw)

        # Update raw image display
        self.ax_raw.clear()
        
        # Get display settings
        display_vals = self.get_display_values()
        vmin, vmax, cmap, scale = display_vals['vmin'], display_vals['vmax'], display_vals['cmap'], display_vals['scale']
        
        # Validate and prepare image array using utility function
        # Handles: SciAnalysis objects, memoryview (Tiled), stacked arrays, etc.
        img_array, is_valid, error_msg = validate_and_prepare_image_array(display_data, use_converter=True)
        
        if not is_valid:
            print(f"ERROR: {error_msg}")
            print(f"  display_data type: {type(display_data)}")
            return

        current_shape = tuple(img_array.shape)
        image_shape_changed = self._last_image_shape is not None and self._last_image_shape != current_shape
        
        # Apply display settings
        if scale == 'log':
            safe_vmin, safe_vmax = self._sanitize_log_limits(img_array, vmin, vmax)
            if safe_vmin is not None and safe_vmax is not None:
                self.ax_raw.imshow(img_array, origin='upper', cmap=cmap, norm=LogNorm(vmin=safe_vmin, vmax=safe_vmax))
            else:
                self.ax_raw.imshow(img_array, origin='upper', cmap=cmap)
        else:
            self.ax_raw.imshow(img_array, origin='upper', cmap=cmap, vmin=vmin, vmax=vmax)
        
        # Restore limits only if they were meaningful
        if raw_xlim_valid and not image_shape_changed:
            self.ax_raw.set_xlim(raw_xlim)
        if raw_ylim_valid and not image_shape_changed:
            self.ax_raw.set_ylim(raw_ylim)

        # Call post-display hooks for tab-specific customizations
        for hook in self.post_display_hooks:
            hook(self.ax_raw)

        # Update raw image canvas with custom tight margins
        self.fig_raw.subplots_adjust(left=0.05, bottom=0.05, right=0.99, top=0.99)
        self.canvas_raw.draw()
        self._last_image_shape = current_shape

    def _reset_canvas_views(self):
        """Reset canvas views to default when loading new image"""
        try:
            # Reset raw image axes to auto-scale
            if hasattr(self, 'ax_raw'):
                self.ax_raw.clear()
                self.ax_raw.set_xlim(None, None)  # Auto-scale
                self.ax_raw.set_ylim(None, None)  # Auto-scale
                self._last_image_shape = None
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
                # Use shared utility function to extract image info (handles SciAnalysis objects & raw arrays)
                img_info = get_image_info(image_data)
                if img_info:
                    shape = img_info['shape']
                    dtype = img_info['dtype']
                    info_lines.append(f"Dimensions: {shape[1]} x {shape[0]} pixels")
                    info_lines.append(f"Data type: {dtype}")
                    info_lines.append(f"Value range: {img_info['min_value']:.2f} to {img_info['max_value']:.2f}")
                    info_lines.append(f"Mean: {img_info['mean_value']:.2f}")
                    info_lines.append(f"Std dev: {img_info['std_value']:.2f}")
                else:
                    info_lines.append("Unable to extract image information")
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
            info_text = '\n'.join(info_lines)
            self.info_lines = info_lines
            self._set_image_info_text(info_text)

            if hasattr(self.parent_app, 'publish_shared_info_text'):
                self.parent_app.publish_shared_info_text(info_text, source_tab=self)
            
        except Exception as e:
            error_info = f"Error loading image info: {str(e)}\n\n"
            error_info += f"Exception type: {type(e).__name__}\n"
            error_info += f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self._set_image_info_text(error_info)

            if hasattr(self.parent_app, 'publish_shared_info_text'):
                self.parent_app.publish_shared_info_text(error_info, source_tab=self)

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
            self._set_image_info_text(info_text)

            if hasattr(self.parent_app, 'publish_shared_info_text'):
                self.parent_app.publish_shared_info_text(info_text, source_tab=self)

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

    def create_filename_label(self, parent_layout=None):
        """Create a standardized filename display label"""
        self.filename_label = QLabel("File Name: No image loaded")
        self.filename_label.setStyleSheet("font-size: 10px;")
        if parent_layout:
            parent_layout.addWidget(self.filename_label)
        return self.filename_label