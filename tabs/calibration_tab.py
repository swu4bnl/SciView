"""
Calibration Tab Module

This module contains the CalibrationApp class which provides the main
calibration interface for detector geometry and beam parameters.
"""

import os
import sys
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QDoubleSpinBox, QLineEdit, QComboBox, QGridLayout, QCheckBox, QSpinBox
)
from PyQt5.QtCore import Qt

import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)

# Import base class and configuration
from tabs.base_image_tab import BaseImageTab
from sciview.interfaces.theme.app_style import *
from sciview.calibration.standards_db import STANDARDS
from sciview.interfaces.stable_qt.tools.ring_center import RingCenterCalculator
from sciview.interfaces.stable_qt.utils.file_dialog_state import dialog_select_directory, dialog_save_file
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION, get_file_status as get_profile_file_status
from sciview.settings.app_settings import MASK_BASE_DIR, PHYSICAL_CONSTANTS
from sciview.calibration.io import build_calibration_payload, write_calibration_yaml

# Get constants
HC_E = PHYSICAL_CONSTANTS['hc_over_e_eV_A']


class CalibrationApp(BaseImageTab):
    """Main calibration application widget"""
    
    def __init__(self, parent_app):
        super().__init__(parent_app)
        
        # Initialize ring center calculator
        self.ring_calculator = RingCenterCalculator()
        
        # Add crosshair hook to show beam center
        self.add_display_hook(self._add_beam_center_crosshair, 'post')
        
        # Load standards database
        self.standards_db = self._load_standards_db()
        self.selected_standard = None

        # Store 1D profile data for export
        self._profile_data = None
        self._last_profile_signature = None
        
        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build the main user interface"""
        from PyQt5.QtWidgets import QSplitter
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Main horizontal splitter: visualization area | controls area
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Visualization area with vertical splitter for image | plot
        visualization_splitter = QSplitter(Qt.Vertical)
        
        # Image panel (top)
        image_panel = self._create_image_panel()
        visualization_splitter.addWidget(image_panel)
        
        # Plot panel (bottom)
        plot_panel = self._create_plot_panel()
        visualization_splitter.addWidget(plot_panel)
        
        # Set initial sizes for visualization panels (image larger than plot)
        setup_splitter_layout(visualization_splitter, AppStyle.get_layout_ratios()['viz_splitter_ratio'])
        
        main_splitter.addWidget(visualization_splitter)

        # Right side: Controls area with vertical splitter for each panel
        controls_splitter = QSplitter(Qt.Vertical)
        
        # Ring center calculation panel
        ring_center_panel = self._create_ring_center_panel()
        controls_splitter.addWidget(ring_center_panel)

        # Calibration parameters panel
        calibration_panel = self._create_calibration_panel()
        controls_splitter.addWidget(calibration_panel)
        
        # Standards reference panel
        standards_panel = self._create_standards_panel()
        controls_splitter.addWidget(standards_panel)
        
        # Set initial sizes for control panels with ring workflow first.
        control_ratios = [2, 1, 1]
        setup_splitter_layout(controls_splitter, control_ratios)
        
        main_splitter.addWidget(controls_splitter)

        # Set initial sizes for main areas (visualization larger than controls)
        setup_splitter_layout(main_splitter, AppStyle.get_layout_ratios()['main_splitter_ratio'])
        
        main_layout.addWidget(main_splitter)

        # Connect matplotlib events
        self.canvas_raw.mpl_connect('motion_notify_event', self.on_mouse_move)
        self.canvas_raw.mpl_connect('button_press_event', self.on_mouse_click)
        self.canvas_plot.mpl_connect('motion_notify_event', self.on_mouse_move)

    def _create_plot_panel(self):
        """Create the analysis plot panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)  # Remove all spacing between elements
        
        # Title and plot scale controls in same line
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        
        title = QLabel("1D Profiles")
        apply_subtitle_style(title)
        title_layout.addWidget(title)
        
        title_layout.addStretch()  # Push scale controls to the right
        
        scale_label = QLabel("Scale:")
        title_layout.addWidget(scale_label)
        
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["linear", "logx", "logy", "loglog"])
        self.scale_combo.currentTextChanged.connect(self.update_plot_calibration)
        self.scale_combo.setMaximumWidth(80)  # Limit width
        title_layout.addWidget(self.scale_combo)

        btn_export_1d = QPushButton("Export 1D")
        btn_export_1d.setMaximumWidth(80)
        btn_export_1d.clicked.connect(self.export_1d_profiles)
        title_layout.addWidget(btn_export_1d)

        layout.addLayout(title_layout)

        # Create matplotlib plot with tighter margins
        self.fig_plot, self.ax_plot = plt.subplots(figsize=(6.0, 2.8))
        # Reduce margins around the plot
        self.fig_plot.subplots_adjust(left=0.08, bottom=0.15, right=0.99, top=0.99)
        
        self.canvas_plot = FigureCanvas(self.fig_plot)
        layout.addWidget(self.canvas_plot)
        
        # Use more compact navigation toolbar or remove it
        toolbar = NavigationToolbar(self.canvas_plot, self)
        toolbar.setMaximumHeight(25)  # Make toolbar smaller
        layout.addWidget(toolbar)
        
        return panel

    def _create_calibration_panel(self):
        """Create the calibration parameters panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        
        # Title
        title = QLabel("Calibration Parameters")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Parameter spinboxes using config defaults
        calibration_params = [
            ("spin_x", ("Beam Center X", -1024, 4096, DEFAULT_CALIBRATION['beam_center_x'], 1)),
            ("spin_y", ("Beam Center Y", -1024, 4096, DEFAULT_CALIBRATION['beam_center_y'], 1)),
            ("spin_orient", ("Detector Orient (°)", -180, 180, DEFAULT_CALIBRATION['detector_orient_deg'], 1)),
            ("spin_tilt", ("Detector Tilt (°)", -180, 180, DEFAULT_CALIBRATION['detector_tilt_deg'], 1)),
            ("spin_phi", ("Detector Phi (°)", -180, 180, DEFAULT_CALIBRATION['detector_phi_deg'], 1)),
            ("spin_dist", ("Distance (m)", 0.001, 200, DEFAULT_CALIBRATION['distance_m'], 0.001)),
            ("spin_pixel", ("Pixel Size (µm)", 0, 5000, DEFAULT_CALIBRATION['pixel_size_um'], 0.1)),
        ]
        
        for attr, params in calibration_params:
            setattr(self, attr, self._create_spin(*params, parent=layout))

        # Wavelength/Energy section
        wl_layout = QHBoxLayout()
        wl_layout.addWidget(QLabel("Wavelength (Å):"))
        self.spin_wl_ang = QDoubleSpinBox()
        self.spin_wl_ang.setRange(0.01, 10.0)
        self.spin_wl_ang.setSingleStep(0.001)
        self.spin_wl_ang.setDecimals(4)
        self.spin_wl_ang.setValue(DEFAULT_CALIBRATION['wavelength_A'])
        self.spin_wl_ang.editingFinished.connect(self.on_wavelength_changed)
        wl_layout.addWidget(self.spin_wl_ang)
        layout.addLayout(wl_layout)
        
        energy_layout = QHBoxLayout()
        energy_layout.addWidget(QLabel("Energy (eV):"))
        self.spin_energy_ev = QDoubleSpinBox()
        self.spin_energy_ev.setRange(100.0, 50000.0)
        self.spin_energy_ev.setSingleStep(1.0)
        self.spin_energy_ev.setValue(DEFAULT_CALIBRATION['energy_eV'])
        self.spin_energy_ev.editingFinished.connect(self.on_energy_changed)
        energy_layout.addWidget(self.spin_energy_ev)
        layout.addLayout(energy_layout)

        # Action buttons
        btns_layout = QHBoxLayout()
        btn_cal = QPushButton("Calibrate")
        btn_cal.clicked.connect(self.calibrate_and_update_status)
        btns_layout.addWidget(btn_cal)
        btn_export = QPushButton("Export")
        btn_export.clicked.connect(self.export_calibration)
        # btn_export.setMaximumWidth(90)
        btns_layout.addWidget(btn_export)
        # apply_primary_button_style(btn_export)
        layout.addLayout(btns_layout)
        
        layout.addStretch()
        return panel

    def _create_ring_center_panel(self):
        """Create the ring center calculation panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        
        # Title
        title = QLabel("Ring Center Calculation")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Instructions
        instructions_label = QLabel("Pick points on one ring. 3+ points required.")
        instructions_label.setWordWrap(True)
        instructions_label.setStyleSheet("font-size: 11px; color: #666;")
        layout.addWidget(instructions_label)
        
        # Create scroll area for point inputs
        from PyQt5.QtWidgets import QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(280)  # Show more points with current compact design
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # Create widget to hold all point inputs
        points_widget = QWidget()
        points_layout = QVBoxLayout(points_widget)
        points_layout.setContentsMargins(2, 2, 2, 2)
        points_layout.setSpacing(2)
        
        # Create fixed list of 10 point inputs
        self.ring_center_inputs = []
        for i in range(10):
            point_widget = QWidget()
            point_layout = QHBoxLayout(point_widget)
            point_layout.setContentsMargins(0, 0, 0, 0)
            point_layout.setSpacing(0)
            
            # Point label with required/optional indicator
            if i < 3:
                label = QLabel(f"Pt {i+1}*:")  # Asterisk for required
                label.setStyleSheet("font-size: 10px; font-weight: bold; color: #333;")
            else:
                label = QLabel(f"Pt {i+1}:")   # Optional points
                label.setStyleSheet("font-size: 10px; color: #666;")
            # label.setFixedWidth(35)
            point_layout.addWidget(label)
            
            x_spin = QDoubleSpinBox()
            x_spin.setRange(-9999, 9999)
            x_spin.setDecimals(1)
            x_spin.setValue(0)
            point_layout.addWidget(x_spin)
            
            y_spin = QDoubleSpinBox()
            y_spin.setRange(-9999, 9999)
            y_spin.setDecimals(1)
            y_spin.setValue(0)
            point_layout.addWidget(y_spin)
            
            self.ring_center_inputs.append((x_spin, y_spin))
            points_layout.addWidget(point_widget)
        
        # Set the points widget in the scroll area
        scroll_area.setWidget(points_widget)
        layout.addWidget(scroll_area)
        
        # Buttons layout
        btn_layout = QHBoxLayout()
        calc_button = QPushButton("Calculate")
        calc_button.clicked.connect(self.calculate_ring_center)
        btn_layout.addWidget(calc_button)
        
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_ring_points)
        btn_layout.addWidget(clear_button)
        layout.addLayout(btn_layout)
        
        # Result display
        self.ring_result_label = QLabel("Ring center: Not calculated")
        self.ring_result_label.setWordWrap(True)
        apply_info_style(self.ring_result_label)
        layout.addWidget(self.ring_result_label)

        # Right-click assist controls
        snap_window_row = QHBoxLayout()
        self.snap_to_max_check = QCheckBox("Local Maximum")
        self.snap_to_max_check.setChecked(True)
        snap_window_row.addWidget(self.snap_to_max_check)
        snap_window_row.addWidget(QLabel("Window"))
        self.snap_window_spin = QSpinBox()
        self.snap_window_spin.setRange(3, 15)
        self.snap_window_spin.setSingleStep(2)
        self.snap_window_spin.setValue(5)
        self.snap_window_spin.setToolTip("Odd-size local search window (3-15 pixels)")
        self.snap_window_spin.setMaximumWidth(70)
        snap_window_row.addWidget(self.snap_window_spin)
        snap_window_row.addWidget(QLabel("px"))
        snap_window_row.addStretch()
        layout.addLayout(snap_window_row)
        
        # Click instruction
        click_instruction = QLabel("Right-click to fill next point.")
        click_instruction.setWordWrap(True)
        apply_info_style(click_instruction)
        layout.addWidget(click_instruction)
        
        # Initialize click tracking
        self.current_point_index = 0
        self.temp_markers = []  # Track temporary yellow markers
        
        layout.addStretch()
        return panel

    def _create_standards_panel(self):
        """Create the standards reference panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)

        title = QLabel("Standard Materials")
        apply_title_style(title)
        layout.addWidget(title)

        # Dropdown menu
        self.standards_combo = QComboBox()
        self.standards_combo.addItem("None")
        for mat in sorted(self.standards_db.keys()):
            self.standards_combo.addItem(mat)
        self.standards_combo.currentTextChanged.connect(self.on_standard_selected)
        layout.addWidget(self.standards_combo)

        # Info label
        self.standards_info_label = QLabel("Select a material to show its diffraction lines in the 1D plot.")
        self.standards_info_label.setWordWrap(True)
        apply_info_style(self.standards_info_label)
        layout.addWidget(self.standards_info_label)

        return panel

    def _create_spin(self, label, mn, mx, default, step, parent):
        """Create a labeled spin box with status update connection"""
        lay = QHBoxLayout()
        lay.addWidget(QLabel(label))
        spin = QDoubleSpinBox()
        spin.setRange(mn, mx)
        spin.setSingleStep(step)
        spin.setValue(default)
        spin.setDecimals(4 if step < 0.01 else 2)
        # Connect value changes to both status updates and plot updates
        spin.editingFinished.connect(self.calibrate_and_update_status)
        lay.addWidget(spin)
        parent.addLayout(lay)
        return spin

    def _load_standards_db(self):
        """Load standards database"""
        return dict(STANDARDS)

    def _add_beam_center_crosshair(self, ax):
        """Hook to add crosshair at beam center position"""
        if hasattr(self, 'spin_x') and hasattr(self, 'spin_y'):
            center_x = self.spin_x.value()
            center_y = self.spin_y.value()
            
            # Add crosshair lines
            if hasattr(self, 'image_data') and self.image_data is not None:
                # Get image dimensions
                if hasattr(self.image_data, 'data'):
                    img_shape = self.image_data.data.shape
                else:
                    img_shape = self.image_data.shape
                
                # Draw crosshair lines
                ax.axhline(y=center_y, color='red', linestyle='--', linewidth=1, alpha=0.7)
                ax.axvline(x=center_x, color='red', linestyle='--', linewidth=1, alpha=0.7)
                
                # Add a small circle at the center
                import matplotlib.pyplot as plt
                circle = plt.Circle((center_x, center_y), radius=3, color='red', fill=False, linewidth=2, alpha=0.8)
                ax.add_patch(circle)

    def calculate_ring_center(self):
        """Calculate the center of a circle from multiple points"""
        try:
            # Get coordinates from input fields, skipping empty points
            points = []
            for i, (x_input, y_input) in enumerate(self.ring_center_inputs):
                x_val = x_input.value()
                y_val = y_input.value()
                # Skip points that are at origin (0,0) as they are likely empty
                if x_val != 0 or y_val != 0:
                    points.append((x_val, y_val))
            
            if len(points) < 3:
                self.ring_result_label.setText("Error: Need at least 3 points to calculate ring center")
                return
            
            # Use the enhanced ring center calculator
            ux, uy, radius = self.ring_calculator.calculate_center(points)
            
            # Store the calculated center
            self.calculated_ring_center = (ux, uy)

            # Apply calculated center directly to beam position controls.
            self.spin_x.setValue(ux)
            self.spin_y.setValue(uy)
            self.calibrate_and_update_status()
            
            # Update result display
            fit_method = "exact (3 pts)" if len(points) == 3 else "least-squares fit"
            self.ring_result_label.setText(
                f"Ring center: ({ux:.2f}, {uy:.2f})\n"
                f"Radius: {radius:.2f} pixels\n"
                f"Used {len(points)} points ({fit_method})\n"
                "Beam center auto-updated"
            )
            
            # Mark points and center on the raw image
            if hasattr(self, 'ax_raw') and self.image_data is not None:
                # Clear previous ring markers
                for artist in self.ax_raw.collections[:]:
                    if hasattr(artist, '_ring_marker'):
                        artist.remove()
                for artist in self.ax_raw.patches[:]:
                    if hasattr(artist, '_ring_marker'):
                        artist.remove()
                
                # Plot the input points
                xs, ys = zip(*points)
                scatter = self.ax_raw.scatter(xs, ys, c='cyan', s=50, marker='o', edgecolors='blue', linewidth=2)
                scatter._ring_marker = True
                
                # Plot the calculated center
                center_scatter = self.ax_raw.scatter([ux], [uy], c='red', s=100, marker='x', linewidth=3)
                center_scatter._ring_marker = True
                
                # Draw the circle
                circle = plt.Circle((ux, uy), radius, fill=False, color='red', linestyle='--', linewidth=2)
                circle._ring_marker = True
                self.ax_raw.add_patch(circle)
                
                self.canvas_raw.draw()
            
            self.parent_app.show_status(f"Ring center calculated and applied: ({ux:.2f}, {uy:.2f}) using {len(points)} points")
            
            # Update status info to show ring center calculation
            self.update_status_info()
            
        except ValueError as e:
            self.ring_result_label.setText(f"Error: {str(e)}")
            self.parent_app.show_status(f"Error calculating ring center: {str(e)}")
        except Exception as e:
            self.ring_result_label.setText(f"Unexpected error: {str(e)}")
            self.parent_app.show_status(f"Unexpected error: {str(e)}")

    def update_beam_from_ring(self):
        """Legacy compatibility wrapper for old button callback paths."""
        self.calculate_ring_center()

    def clear_ring_points(self):
        """Clear all ring coordinate inputs and markers"""
        for x_input, y_input in self.ring_center_inputs:
            x_input.setValue(0.0)
            y_input.setValue(0.0)
        
        # Clear temporary yellow markers
        if hasattr(self, 'temp_markers'):
            for marker in self.temp_markers:
                try:
                    marker.remove()
                except:
                    pass
            self.temp_markers = []
            if hasattr(self, 'canvas_raw'):
                self.canvas_raw.draw()
        
        self.ring_result_label.setText("Enter coordinates on a ring and click 'Calculate'")
        self.current_point_index = 0
        self.parent_app.show_status("Ring coordinate inputs cleared")

    def _add_tab_specific_status(self, info_lines):
        """Add calibration-specific status information"""
        info_lines.append("")  # Blank line separator
        
        # === RING CENTER STATUS ===
        info_lines.append("=== RING CENTER STATUS ===")
        # Count non-zero ring points
        ring_points_count = 0
        for x_input, y_input in self.ring_center_inputs:
            if x_input.value() != 0 or y_input.value() != 0:
                ring_points_count += 1
        
        info_lines.append(f"Ring points entered: {ring_points_count}/10")
        if hasattr(self, 'calculated_ring_center'):
            cx, cy = self.calculated_ring_center
            info_lines.append(f"Calculated center: ({cx:.2f}, {cy:.2f})")
        else:
            info_lines.append("Ring center: Not calculated")
        
        # === STANDARDS STATUS ===
        if self.selected_standard:
            info_lines.append("")
            info_lines.append("=== STANDARDS STATUS ===")
            info_lines.append(f"Selected: {self.selected_standard}")
            qvals = self.standards_db.get(self.selected_standard, [])
            info_lines.append(f"Reference lines: {len(qvals)}")

    def calibrate_and_update_status(self):
        """Update calibration and status information"""
        self.update_plot_calibration()
        self.update_status_info()
        self.parent_app.show_status("Calibration updated and plots refreshed")

    def on_wavelength_changed(self):
        """Handle wavelength changes"""
        wavelength = self.spin_wl_ang.value()
        energy = HC_E / wavelength
        self.spin_energy_ev.setValue(energy)
        self.calibrate_and_update_status()

    def on_energy_changed(self):
        """Handle energy changes"""
        energy = self.spin_energy_ev.value()
        wavelength = HC_E / energy
        self.spin_wl_ang.setValue(wavelength)
        self.calibrate_and_update_status()

    def _draw_standard_lines(self):
        """Draw vertical lines for selected standard in 1D plot"""
        if self.selected_standard:
            qvals = self.standards_db.get(self.selected_standard, [])
            for q in qvals:
                self.ax_plot.axvline(q, color='magenta', linestyle='--', linewidth=1.5, alpha=0.7)

    def on_standard_selected(self, text):
        """Handle standard material selection"""
        if text == "None":
            self.selected_standard = None
            self.standards_info_label.setText("No standard selected.")
        else:
            self.selected_standard = text
            qvals = self.standards_db.get(text, [])
            self.standards_info_label.setText(f"Selected: {text} ({len(qvals)} lines)")
        self.update_plot_calibration()

        # === STANDARDS STATUS ===
        try:
            if self.selected_standard:
                self.info_lines.append("")
                self.info_lines.append("=== STANDARDS STATUS ===")
                self.info_lines.append(f"Selected: {self.selected_standard}")
                qvals = self.standards_db.get(self.selected_standard, [])
                self.info_lines.append(f"Reference lines: {len(qvals)}")
        except Exception as e:
            print(f"Error updating standards status: {e}")

    def update_plot_calibration(self):
        """Update plots based on current calibration and image data"""
        if self.image_data is None:
            return
        
        # Store current limits for 1D plot
        plot_xlim, plot_ylim = self.ax_plot.get_xlim(), self.ax_plot.get_ylim()
        plot_xlim_valid = not np.allclose(plot_xlim, (0, 1))
        plot_ylim_valid = not np.allclose(plot_ylim, (0, 1))

        # First, update the raw image using the unified base class method
        self.update_plot()
        
        # Then, update the 1D plots
        self._update_1d_plots(plot_xlim, plot_ylim, plot_xlim_valid, plot_ylim_valid)
    
    def _update_1d_plots(self, plot_xlim, plot_ylim, plot_xlim_valid, plot_ylim_valid):
        """Update the 1D analysis plots"""
        # Update calibration if SciAnalysis is available
        if self.scianalysis_available and self.image_data.calibration:

            height, width = self.image_data.data.shape
            self.image_data.calibration.width = width
            self.image_data.calibration.height = height

            self.image_data.calibration.set_beam_position(self.spin_x.value(), self.spin_y.value())
            self.image_data.calibration.set_angles(det_orient=self.spin_orient.value(), 
                                        det_tilt=self.spin_tilt.value(), 
                                        det_phi=self.spin_phi.value())
            self.image_data.calibration.set_distance(self.spin_dist.value())
            self.image_data.calibration.set_pixel_size(pixel_size_um=self.spin_pixel.value())
            self.image_data.calibration.set_wavelength(self.spin_wl_ang.value())

            self.image_data.calibration.clear_maps()

            # Publish updated calibration so other tabs consume the same object.
            if hasattr(self.parent_app, 'publish_shared_calibration'):
                self.parent_app.publish_shared_calibration(self.image_data.calibration, source_tab=self)


            # cal = self.calibration
            # cal.set_beam_position(self.spin_x.value(), self.spin_y.value())
            # cal.set_angles(det_orient=self.spin_orient.value(), det_tilt=self.spin_tilt.value(), det_phi=self.spin_phi.value())
            # cal.set_distance(self.spin_dist.value())
            # cal.set_pixel_size(pixel_size_um=self.spin_pixel.value())
            # cal.set_wavelength(self.spin_wl_ang.value())
            
            # # Set detector dimensions if image data is available
            # if hasattr(self.image_data, 'data'):
            #     height, width = self.image_data.data.shape
            #     cal.width = width
            #     cal.height = height
            
            # cal.clear_maps()
            
            # Re-assign the updated calibration to the image data
            # This is crucial for Q-space calculations to use the new parameters
            # self.image_data.calibration = cal
            
            # Calculate Q-space data using SciAnalysis with error handling
            try:
                circ = self.image_data.circular_average_q_bin(apply_mask=False)
                hor_1 = self.image_data.sector_average_q_bin(angle=0, dangle=5, apply_mask=False)
                hor_2 = self.image_data.sector_average_q_bin(angle=180, dangle=5, apply_mask=False)
                ver_1 = self.image_data.sector_average_q_bin(angle=90, dangle=5, apply_mask=False)
                ver_2 = self.image_data.sector_average_q_bin(angle=-90, dangle=5, apply_mask=False)
            except Exception as e:
                # If Q-space analysis fails, clear the plot and show error
                print(f"Warning: Q-space analysis failed: {e}")
                self._profile_data = None
                self._clear_1d_plots()
                return
        else:
            # SciAnalysis not available - clear plots and show message
            self._profile_data = None
            self._clear_1d_plots()
            return

        # Store profile data for export
        self._profile_data = {
            'Circular Avg': circ,
            'Horizontal 0deg': hor_1,
            'Horizontal 180deg': hor_2,
            'Vertical 90deg': ver_1,
            'Vertical 270deg': ver_2,
        }

        # Update 1D plot with real data
        self._draw_1d_plots(circ, hor_1, hor_2, ver_1, ver_2, plot_xlim, plot_ylim, plot_xlim_valid, plot_ylim_valid)
    
    def _clear_1d_plots(self):
        """Clear 1D plots when SciAnalysis is not available or analysis fails"""
        self.ax_plot.clear()
        self._last_profile_signature = None
        self.ax_plot.text(0.5, 0.5, 'No Q-space analysis available\n\nRequires:\n• Valid image data\n• SciAnalysis library\n• Proper calibration parameters', 
                         transform=self.ax_plot.transAxes, 
                         ha='center', va='center', 
                         fontsize=10, color='gray',
                         bbox=dict(boxstyle='round,pad=0.5', facecolor='lightgray', alpha=0.7))
        self.ax_plot.set_xlabel('Q (Å⁻¹)', fontsize=8)
        self.ax_plot.set_ylabel('Intensity', fontsize=8)
        self.ax_plot.tick_params(labelsize=7)
        self.canvas_plot.draw()
    
    def _draw_1d_plots(self, circ, hor_1, hor_2, ver_1, ver_2, plot_xlim, plot_ylim, plot_xlim_valid, plot_ylim_valid):
        """Draw the 1D plots with given data"""
        # Update 1D plot
        self.ax_plot.clear()
        self.ax_plot.plot(circ.x, circ.y, label='Circular Avg', color='#22BB44', linewidth=1.5)
        self.ax_plot.plot(hor_1.x, hor_1.y, label='Horizontal 0°', color='#BB4422', linewidth=1.2)
        self.ax_plot.plot(hor_2.x, hor_2.y, label='Horizontal 180°', color='#BB2244', linewidth=1.2)
        self.ax_plot.plot(ver_1.x, ver_1.y, label='Vertical 90°', color='#2244BB', linewidth=1.2)
        self.ax_plot.plot(ver_2.x, ver_2.y, label='Vertical 270°', color='#4422BB', linewidth=1.2)

        # Draw standard lines if selected
        self._draw_standard_lines()

        # Set labels and legend with smaller fonts
        self.ax_plot.set_xlabel('Q (Å⁻¹)', fontsize=8)
        self.ax_plot.set_ylabel('Intensity', fontsize=8)
        self.ax_plot.legend(fontsize=6, loc='best', frameon=False)
        self.ax_plot.tick_params(labelsize=7)
        
        # Apply scaling options properly
        ps = self.scale_combo.currentText()
        if ps == 'linear':
            self.ax_plot.set_xscale('linear')
            self.ax_plot.set_yscale('linear')
        elif ps == 'logx':
            self.ax_plot.set_xscale('log')
            self.ax_plot.set_yscale('linear')
        elif ps == 'logy':
            self.ax_plot.set_xscale('linear')
            self.ax_plot.set_yscale('log')
        elif ps == 'loglog':
            self.ax_plot.set_xscale('log')
            self.ax_plot.set_yscale('log')

        circ_x = np.asarray(circ.x)
        circ_y = np.asarray(circ.y)
        finite_x = circ_x[np.isfinite(circ_x)]
        finite_y = circ_y[np.isfinite(circ_y)]
        profile_signature = (
            ps,
            int(circ_x.size),
            float(np.min(finite_x)) if finite_x.size else None,
            float(np.max(finite_x)) if finite_x.size else None,
            float(np.min(finite_y)) if finite_y.size else None,
            float(np.max(finite_y)) if finite_y.size else None,
        )
        signature_changed = profile_signature != self._last_profile_signature
        
        # Restore limits only if they were meaningful and scale hasn't changed
        if plot_xlim_valid and plot_ylim_valid and not signature_changed:
            try:
                if ps in ['logx', 'loglog'] and plot_xlim[0] <= 0:
                    pass  # Log scale incompatible with stored limits
                elif ps in ['logy', 'loglog'] and plot_ylim[0] <= 0:
                    pass  # Log scale incompatible with stored limits
                else:
                    self.ax_plot.set_xlim(plot_xlim)
                    self.ax_plot.set_ylim(plot_ylim)
            except ValueError:
                pass  # If setting limits fails, let matplotlib autoscale
        
        # Ensure plot fills the canvas with custom tight margins
        self.fig_plot.subplots_adjust(left=0.05, bottom=0.10, right=0.99, top=0.99)
        self.canvas_plot.draw()
        self._last_profile_signature = profile_signature

    def export_calibration(self):
        """Export current calibration parameters to a YAML file"""
        # Prompt for directory
        dir_path = dialog_select_directory(
            self,
            "Select Directory to Export Calibration",
            key="calibration_export",
        )
        if not dir_path:
            return
        
        # Get beamline-specific file status and naming
        filename = os.path.basename(self.parent_app.get_image_path()) if hasattr(self.parent_app, 'get_image_path') and self.parent_app.get_image_path() else ""
        file_status = get_profile_file_status(filename, mask_dir=MASK_BASE_DIR)
        
        # Gather parameters
        wavelength_A = self.spin_wl_ang.value()
        pixel_size_um = self.spin_pixel.value()
        beam_position = (self.spin_x.value(), self.spin_y.value())
        distance = self.spin_dist.value()
        if self.image_data is not None:
            image_size = list(self.image_data.data.shape[::-1])
        else:
            image_size = [int(self.spin_x.maximum()), int(self.spin_y.maximum())]

        # Write to YAML using beamline-specific naming
        yaml_path = os.path.join(dir_path, file_status['calibration_file'])
        payload = build_calibration_payload(
            wavelength_A=wavelength_A,
            pixel_size_um=pixel_size_um,
            beam_position=beam_position,
            distance_m=distance,
            image_size=image_size,
            hc_over_e_eV_A=HC_E,
        )
        written_path = write_calibration_yaml(payload, yaml_path)
        self.parent_app.show_status(f"Calibration parameters exported to {written_path}")

    def export_1d_profiles(self):
        """Export 1D profile curves to a CSV file"""
        if self._profile_data is None:
            self.parent_app.show_status("No 1D profile data available to export. Load an image and calibrate first.")
            return

        # Build default filename from current image
        default_name = "1d_profiles.csv"
        if hasattr(self.parent_app, 'get_image_path') and self.parent_app.get_image_path():
            base = os.path.splitext(os.path.basename(self.parent_app.get_image_path()))[0]
            default_name = f"{base}_1d_profiles.csv"

        file_path, _ = dialog_save_file(
            self,
            "Export 1D Profiles",
            default_name,
            "CSV files (*.csv);;Text files (*.txt);;All files (*)",
            key="profile_export",
        )

        if not file_path:
            return

        # Interpolate all curves onto a common Q grid (the circular average grid)
        profiles = self._profile_data
        q_ref = profiles['Circular Avg'].x
        header_cols = ['Q_inv_Angstrom']
        columns = [q_ref]

        for name, profile in profiles.items():
            # Use a tolerant float comparison to avoid unnecessary interpolation
            if profile.x.shape == q_ref.shape and np.allclose(profile.x, q_ref, rtol=1e-8, atol=1e-10):
                columns.append(profile.y)
            else:
                columns.append(np.interp(q_ref, profile.x, profile.y))
            header_cols.append(name.replace(' ', '_'))

        data = np.column_stack(columns)

        # Write CSV using a standard single-character comma delimiter
        header = ','.join(header_cols)
        np.savetxt(file_path, data, delimiter=',', header=header, comments='# ')

        self.parent_app.show_status(f"1D profiles exported to {file_path}")

    def on_mouse_click(self, event):
        """Handle mouse clicks on the raw image for ring center calculation"""
        if not event.inaxes or event.inaxes != self.ax_raw:
            return
        
        # Mouse button mapping: 1=left, 2=middle, 3=right
        if event.button == 3:  # Right click for coordinate selection (left click reserved for zoom/pan)
            x, y = event.xdata, event.ydata
            if x is not None and y is not None:
                display_x, display_y = x, y
                if getattr(self, 'snap_to_max_check', None) is not None and self.snap_to_max_check.isChecked():
                    snapped = self._snap_to_local_max(x, y, half_window=self._get_snap_window_half_size())
                    if snapped is not None:
                        display_x, display_y = snapped

                # Fill the next available coordinate field (cycles through 10 points)
                x_input, y_input = self.ring_center_inputs[self.current_point_index]
                x_input.setValue(display_x)
                y_input.setValue(display_y)
                
                # Visual feedback - add yellow marker
                if hasattr(self, 'ax_raw'):
                    temp_point = self.ax_raw.scatter([display_x], [display_y], c='yellow', s=100, marker='o', alpha=0.7)
                    
                    # Add to temp markers list
                    if not hasattr(self, 'temp_markers'):
                        self.temp_markers = []
                    self.temp_markers.append(temp_point)
                    
                    # Remove oldest marker if we exceed 10 markers
                    if len(self.temp_markers) > 10:
                        oldest_marker = self.temp_markers.pop(0)
                        try:
                            oldest_marker.remove()
                        except:
                            pass
                    
                    self.canvas_raw.draw()
                
                self.current_point_index = (self.current_point_index + 1) % 10
                
                # Update status
                if self.current_point_index == 0:
                    self.parent_app.show_status("All 10 points filled. Click 'Calculate Ring Center' or continue right-clicking to replace points.")
                else:
                    self.parent_app.show_status(f"Point {self.current_point_index} filled. Right-click for point {self.current_point_index + 1}.")

    def _get_image_array_for_click_tools(self):
        """Return a 2D image array for click-assist features, if available."""
        if self.image_data is None:
            return None
        data_array = self.image_data.data if hasattr(self.image_data, 'data') else self.image_data
        if not isinstance(data_array, np.ndarray):
            return None
        if data_array.ndim != 2:
            return None
        return data_array

    def _get_snap_window_half_size(self):
        """Return half-window size from the odd snap window value."""
        window_size = 5
        if hasattr(self, 'snap_window_spin') and self.snap_window_spin is not None:
            window_size = int(self.snap_window_spin.value())
        if window_size % 2 == 0:
            window_size += 1
        window_size = max(3, min(15, window_size))
        return window_size // 2

    def _snap_to_local_max(self, x, y, half_window=2):
        """Snap click coordinate to brightest finite pixel inside a local window."""
        image_array = self._get_image_array_for_click_tools()
        if image_array is None:
            return None

        height, width = image_array.shape
        px = int(round(x))
        py = int(round(y))
        if px < 0 or py < 0 or px >= width or py >= height:
            return None

        x0 = max(0, px - half_window)
        x1 = min(width, px + half_window + 1)
        y0 = max(0, py - half_window)
        y1 = min(height, py + half_window + 1)
        window = image_array[y0:y1, x0:x1]

        finite_mask = np.isfinite(window)
        if not np.any(finite_mask):
            return None

        window_for_argmax = np.where(finite_mask, window, -np.inf)
        max_index_flat = int(np.argmax(window_for_argmax))
        local_y, local_x = np.unravel_index(max_index_flat, window.shape)
        return float(x0 + local_x), float(y0 + local_y)

    def keyPressEvent(self, event):
        """Handle key press events"""
        # Enter key to update plot
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.calibrate_and_update_status()