"""
Calibration Tab Module

This module contains the CalibrationApp class which provides the main
calibration interface for detector geometry and beam parameters.
"""

import os
import sys
import numpy as np
import importlib.util

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QDoubleSpinBox, QLineEdit, QComboBox, QGridLayout, QFileDialog
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
from config.beamline_config import (
    DEFAULT_CALIBRATION, PHYSICAL_CONSTANTS, get_file_status
)
from tools.ring_center import RingCenterCalculator

# Get constants
HC_E = PHYSICAL_CONSTANTS['hc_over_e_eV_A']


class CalibrationApp(BaseImageTab):
    """Main calibration application widget"""
    
    def __init__(self, parent_app):
        super().__init__(parent_app)
        
        # Initialize ring center calculator
        self.ring_calculator = RingCenterCalculator()
        
        # Load standards database
        self.standards_db = self._load_standards_db()
        self.selected_standard = None
        
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
        visualization_splitter.setSizes([300, 100])  # 3:1 ratio
        
        main_splitter.addWidget(visualization_splitter)

        # Right side: Controls area with vertical splitter for each panel
        controls_splitter = QSplitter(Qt.Vertical)
        
        # Image information panel
        image_info_panel = self._create_image_info_panel()
        controls_splitter.addWidget(image_info_panel)
        
        # Calibration parameters panel
        calibration_panel = self._create_calibration_panel()
        controls_splitter.addWidget(calibration_panel)
        
        # Ring center calculation panel
        ring_center_panel = self._create_ring_center_panel()
        controls_splitter.addWidget(ring_center_panel)
        
        # Standards reference panel
        standards_panel = self._create_standards_panel()
        controls_splitter.addWidget(standards_panel)
        
        # Set initial sizes for control panels (adjust based on content)
        controls_splitter.setSizes([80, 120, 150, 60])
        
        main_splitter.addWidget(controls_splitter)

        # Set initial sizes for main areas (visualization larger than controls)
        main_splitter.setSizes([600, 200])  # 3:1 ratio
        
        main_layout.addWidget(main_splitter)

        # Connect matplotlib events
        self.canvas_raw.mpl_connect('motion_notify_event', self.on_mouse_move)
        self.canvas_raw.mpl_connect('button_press_event', self.on_mouse_click)
        self.canvas_plot.mpl_connect('motion_notify_event', self.on_mouse_move)

    def _create_image_panel(self):
        """Create the image display panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)  # Remove all spacing

        # Load button
        btn_load = QPushButton("Load Image")
        btn_load.clicked.connect(self.load_image)
        btn_load.setMaximumHeight(30)  # Compact button
        layout.addWidget(btn_load)
        
        # Image display title - smaller font
        title = QLabel("Raw Image")
        title.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(title)

        # Dynamic filename label - smaller font
        self.filename_label = QLabel("File Name: No image loaded")
        self.filename_label.setStyleSheet("font-size: 10px;")
        layout.addWidget(self.filename_label)

        # Create matplotlib figure with tighter margins
        self.fig_raw, self.ax_raw = plt.subplots(figsize=(6, 6))
        # Reduce margins around the image
        self.fig_raw.subplots_adjust(left=0.05, bottom=0.05, right=0.99, top=0.99)
        
        self.canvas_raw = FigureCanvas(self.fig_raw)
        layout.addWidget(self.canvas_raw)
        
        # Compact navigation toolbar
        toolbar_raw = NavigationToolbar(self.canvas_raw, self)
        toolbar_raw.setMaximumHeight(25)
        layout.addWidget(toolbar_raw)

        # Image controls
        img_ctrl = QHBoxLayout()
        img_ctrl.addWidget(QLabel("vmin:"))
        self.vmin_input = QLineEdit("-2")
        # self.vmin_input.setFixedWidth(60)
        self.vmin_input.editingFinished.connect(self.update_plot)
        img_ctrl.addWidget(self.vmin_input)
        img_ctrl.addWidget(QLabel("vmax:"))
        self.vmax_input = QLineEdit("1000")
        # self.vmax_input.setFixedWidth(60)
        self.vmax_input.editingFinished.connect(self.update_plot)
        img_ctrl.addWidget(self.vmax_input)
        img_ctrl.addWidget(QLabel("cmap:"))
        self.cmap_selector = QComboBox()
        self.cmap_selector.addItems(plt.colormaps())
        self.cmap_selector.setCurrentText("gray")
        self.cmap_selector.currentTextChanged.connect(self.update_plot)
        img_ctrl.addWidget(self.cmap_selector)
        img_ctrl.addWidget(QLabel("scale:"))
        self.img_scale_combo = QComboBox()
        self.img_scale_combo.addItems(["linear", "log"])
        self.img_scale_combo.currentTextChanged.connect(self.update_plot)
        img_ctrl.addWidget(self.img_scale_combo)
        layout.addLayout(img_ctrl)
        
        return panel
    
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
        title.setStyleSheet("font-weight: bold; font-size: 12px;")  # Smaller title font
        title_layout.addWidget(title)
        
        title_layout.addStretch()  # Push scale controls to the right
        
        scale_label = QLabel("Scale:")
        scale_label.setStyleSheet("font-size: 10px;")  # Smaller font
        title_layout.addWidget(scale_label)
        
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["linear", "logx", "logy", "loglog"])
        self.scale_combo.currentTextChanged.connect(self.update_plot)
        self.scale_combo.setMaximumWidth(80)  # Limit width
        title_layout.addWidget(self.scale_combo)
        
        layout.addLayout(title_layout)

        # Create matplotlib plot with tighter margins
        self.fig_plot, self.ax_plot = plt.subplots(figsize=(6.0, 2.8))
        # Reduce margins around the plot
        self.fig_plot.subplots_adjust(left=0.05, bottom=0.10, right=0.99, top=0.99)
        
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
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        # Parameter spinboxes using config defaults
        calibration_params = [
            ("spin_x", ("Beam Center X", 0, 2000, DEFAULT_CALIBRATION['beam_center_x'], 1)),
            ("spin_y", ("Beam Center Y", 0, 2000, DEFAULT_CALIBRATION['beam_center_y'], 1)),
            ("spin_orient", ("Detector Orient (°)", -180, 180, DEFAULT_CALIBRATION['detector_orient_deg'], 1)),
            ("spin_tilt", ("Detector Tilt (°)", -180, 180, DEFAULT_CALIBRATION['detector_tilt_deg'], 1)),
            ("spin_phi", ("Detector Phi (°)", -180, 180, DEFAULT_CALIBRATION['detector_phi_deg'], 1)),
            ("spin_dist", ("Distance (m)", 0.1, 5.5, DEFAULT_CALIBRATION['distance_m'], 0.001)),
            ("spin_pixel", ("Pixel Size (µm)", 50, 500, DEFAULT_CALIBRATION['pixel_size_um'], 0.1)),
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
        btns_layout.addWidget(btn_export)
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
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        # Instructions
        instructions_label = QLabel("Enter (x, y) from the same ring.\nPoints 1-3 are required, 4-10 are optional.")
        instructions_label.setWordWrap(True)
        instructions_label.setStyleSheet("font-size: 11px; color: #666;")
        layout.addWidget(instructions_label)
        
        # Create scroll area for point inputs
        from PyQt5.QtWidgets import QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(180)  # Limit height to show ~6-7 points
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
            # x_spin.setFixedWidth(65)
            x_spin.setStyleSheet("font-size: 10px;")
            point_layout.addWidget(x_spin)
            
            y_spin = QDoubleSpinBox()
            y_spin.setRange(-9999, 9999)
            y_spin.setDecimals(1)
            y_spin.setValue(0)
            # y_spin.setFixedWidth(65)
            y_spin.setStyleSheet("font-size: 10px;")
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
        self.ring_result_label.setStyleSheet("font-size: 11px; background-color: #f0f0f0; padding: 5px; border: 1px solid #ccc;")
        layout.addWidget(self.ring_result_label)
        
        # Update beam position button
        update_beam_button = QPushButton("Update Beam Position")
        update_beam_button.clicked.connect(self.update_beam_from_ring)
        layout.addWidget(update_beam_button)
        
        # Click instruction
        click_instruction = QLabel("Tip: Right-click on the image to fill coordinates")
        click_instruction.setWordWrap(True)
        click_instruction.setStyleSheet("color: gray; font-style: italic; font-size: 10px;")
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
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
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
        self.standards_info_label.setStyleSheet("font-size: 11px; color: gray;")
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
        # Connect value changes to status updates
        spin.editingFinished.connect(self.update_status_info)
        lay.addWidget(spin)
        parent.addLayout(lay)
        return spin

    def _load_standards_db(self):
        """Load standards database"""
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "standards", "standards_db.py")
        spec = importlib.util.spec_from_file_location("standards_db", db_path)
        standards_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(standards_module)
        return getattr(standards_module, "STANDARDS", {})

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
            
            # Update result display
            fit_method = "exact (3 pts)" if len(points) == 3 else "least-squares fit"
            self.ring_result_label.setText(f"Ring center: ({ux:.2f}, {uy:.2f}) \n Radius: {radius:.2f} pixels \n Used {len(points)} points ({fit_method})")
            
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
            
            self.parent_app.show_status(f"Ring center calculated: ({ux:.2f}, {uy:.2f}) using {len(points)} points")
            
            # Update status info to show ring center calculation
            self.update_status_info()
            
        except ValueError as e:
            self.ring_result_label.setText(f"Error: {str(e)}")
            self.parent_app.show_status(f"Error calculating ring center: {str(e)}")
        except Exception as e:
            self.ring_result_label.setText(f"Unexpected error: {str(e)}")
            self.parent_app.show_status(f"Unexpected error: {str(e)}")

    def update_beam_from_ring(self):
        """Update beam position from calculated ring center"""
        try:
            # Get coordinates from input fields, skipping empty points
            points = []
            for x_input, y_input in self.ring_center_inputs:
                x_val = x_input.value()
                y_val = y_input.value()
                if x_val != 0 or y_val != 0:  # Skip zero points
                    points.append((x_val, y_val))
            
            if len(points) < 3:
                self.ring_result_label.setText("Error: Need at least 3 points")
                return
            
            # Calculate ring center using the enhanced calculator
            result = self.ring_calculator.calculate_center(points)
            if result is None:
                self.ring_result_label.setText("Error: Cannot calculate center")
                return
                
            center_x, center_y, radius = result
            
            # Validate the result
            if not (np.isfinite(center_x) and np.isfinite(center_y) and np.isfinite(radius)):
                self.ring_result_label.setText("Error: Invalid calculation result")
                return
            
            # Update the beam position spin boxes
            self.spin_x.setValue(center_x)
            self.spin_y.setValue(center_y)
            self.spin_y.setValue(center_y)
            
            # Update the result display
            self.ring_result_label.setText(f"Center: ({center_x:.1f}, {center_y:.1f}), Radius: {radius:.1f}")
            
            # Update the plot to show new beam position
            self.update_plot()
            
            # Update status info to reflect changes
            self.update_status_info()
            
            self.parent_app.show_status(f"Beam position updated to ({center_x:.1f}, {center_y:.1f})")
            
        except ValueError as e:
            self.ring_result_label.setText(f"Error: {str(e)}")
        except Exception as e:
            self.ring_result_label.setText(f"Calculation error: {str(e)}")
            print(f"Ring center calculation error: {e}")

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
        
        self.ring_result_label.setText("Enter coordinates on a ring and click 'Calculate Ring Center'")
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
        self.update_plot()
        self.update_status_info()
        self.parent_app.show_status("Calibration updated and plots refreshed")

    def on_wavelength_changed(self):
        """Handle wavelength changes"""
        wavelength = self.spin_wl_ang.value()
        energy = HC_E / wavelength
        self.spin_energy_ev.setValue(energy)
        self.update_plot()
        self.update_status_info()  # Update status when calibration changes

    def on_energy_changed(self):
        """Handle energy changes"""
        energy = self.spin_energy_ev.value()
        wavelength = HC_E / energy
        self.spin_wl_ang.setValue(wavelength)
        self.update_plot()
        self.update_status_info()  # Update status when calibration changes

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
        self.update_plot()

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

    def update_plot(self):
        """Update plots based on current calibration and image data"""
        if self.image_data is None:
            return
        
        # Store current limits only if they are not default/unset
        raw_xlim, raw_ylim = self.ax_raw.get_xlim(), self.ax_raw.get_ylim()
        plot_xlim, plot_ylim = self.ax_plot.get_xlim(), self.ax_plot.get_ylim()
        
        # Check if limits are meaningful (not default matplotlib values)
        raw_xlim_valid = not np.allclose(raw_xlim, (0, 1))
        raw_ylim_valid = not np.allclose(raw_ylim, (0, 1))
        plot_xlim_valid = not np.allclose(plot_xlim, (0, 1))
        plot_ylim_valid = not np.allclose(plot_ylim, (0, 1))

        # Update calibration if SciAnalysis is available
        if self.scianalysis_available and self.calibration:
            cal = self.calibration
            cal.set_beam_position(self.spin_x.value(), self.spin_y.value())
            cal.set_angles(det_orient=self.spin_orient.value(), det_tilt=self.spin_tilt.value(), det_phi=self.spin_phi.value())
            cal.set_distance(self.spin_dist.value())
            cal.set_pixel_size(pixel_size_um=self.spin_pixel.value())
            cal.set_wavelength(self.spin_wl_ang.value())
            cal.clear_maps()
            
            # Calculate Q-space data using SciAnalysis
            circ = self.image_data.circular_average_q_bin(apply_mask=False)
            hor_1 = self.image_data.sector_average_q_bin(angle=0, dangle=5, apply_mask=False)
            hor_2 = self.image_data.sector_average_q_bin(angle=180, dangle=5, apply_mask=False)
            ver_1 = self.image_data.sector_average_q_bin(angle=90, dangle=5, apply_mask=False)
            ver_2 = self.image_data.sector_average_q_bin(angle=-90, dangle=5, apply_mask=False)
        else:
            # Create mock Q-space data for testing
            class MockProfile:
                def __init__(self, x_data, y_data):
                    self.x = x_data
                    self.y = y_data
            
            # Generate mock Q-space profiles
            x_vals = np.linspace(0.01, 2.0, 100)
            circ = MockProfile(x_vals, 1000 * np.exp(-x_vals * 2) + 50)
            hor_1 = MockProfile(x_vals, 800 * np.exp(-x_vals * 1.5) + 30)
            hor_2 = MockProfile(x_vals, 750 * np.exp(-x_vals * 1.8) + 25)
            ver_1 = MockProfile(x_vals, 900 * np.exp(-x_vals * 1.2) + 40)
            ver_2 = MockProfile(x_vals, 850 * np.exp(-x_vals * 1.6) + 35)

        # Update raw image display
        self.ax_raw.clear()
        try:
            vmin = float(self.vmin_input.text())
            vmax = float(self.vmax_input.text())
        except ValueError:
            vmin = vmax = None
        
        cmap = self.cmap_selector.currentText()
        scale = self.img_scale_combo.currentText()
        if scale == 'log':
            norm = LogNorm(vmin=vmin, vmax=vmax) if vmin and vmax else LogNorm()
            self.ax_raw.imshow(self.image_data.data, origin='upper', cmap=cmap, norm=norm)
        else:
            self.ax_raw.imshow(self.image_data.data, origin='upper', cmap=cmap, vmin=vmin, vmax=vmax)
        
        # Add beam center crosshairs
        self.ax_raw.axhline(self.spin_y.value(), color='r', ls='--', alpha=0.8)
        self.ax_raw.axvline(self.spin_x.value(), color='r', ls='--', alpha=0.8)
        self.ax_raw.set_title('Raw Image', fontsize=9)  # Smaller title
        self.ax_raw.tick_params(labelsize=7)  # Smaller tick labels
        
        # Restore limits only if they were meaningful
        if raw_xlim_valid:
            self.ax_raw.set_xlim(raw_xlim)
        if raw_ylim_valid:
            self.ax_raw.set_ylim(raw_ylim)

        # Update raw image canvas with custom tight margins
        self.fig_raw.subplots_adjust(left=0.05, bottom=0.05, right=0.99, top=0.99)
        self.canvas_raw.draw()
        
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
        self.ax_plot.set_xlabel('Q (Å⁻¹)', fontsize=8)  # Smaller xlabel
        self.ax_plot.set_ylabel('Intensity', fontsize=8)  # Smaller ylabel
        self.ax_plot.legend(fontsize=6, loc='best', frameon=False)  # Smaller legend, no frame
        self.ax_plot.tick_params(labelsize=7)  # Smaller tick labels
        
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
        
        # Restore limits only if they were meaningful and scale hasn't changed
        if plot_xlim_valid and plot_ylim_valid:
            # Check if current scale is compatible with stored limits
            try:
                if ps in ['logx', 'loglog'] and plot_xlim[0] <= 0:
                    # Log scale incompatible with stored limits, let it autoscale
                    pass
                elif ps in ['logy', 'loglog'] and plot_ylim[0] <= 0:
                    # Log scale incompatible with stored limits, let it autoscale
                    pass
                else:
                    self.ax_plot.set_xlim(plot_xlim)
                    self.ax_plot.set_ylim(plot_ylim)
            except ValueError:
                # If setting limits fails, let matplotlib autoscale
                pass
        
        # Ensure plot fills the canvas with custom tight margins
        self.fig_plot.subplots_adjust(left=0.05, bottom=0.10, right=0.99, top=0.99)
        self.canvas_plot.draw()

    def export_calibration(self):
        """Export current calibration parameters to a YAML file"""
        # Prompt for directory
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory to Export Calibration")
        if not dir_path:
            return
        
        # Get beamline-specific file status and naming
        filename = os.path.basename(self.parent_app.get_image_path()) if hasattr(self.parent_app, 'get_image_path') and self.parent_app.get_image_path() else ""
        file_status = get_file_status(filename)
        
        # Gather parameters
        wavelength_A = self.spin_wl_ang.value()
        energy_eV = HC_E / wavelength_A
        pixel_size_um = self.spin_pixel.value()
        beam_position = [self.spin_x.value(), self.spin_y.value()]
        distance = self.spin_dist.value()
        if self.image_data is not None:
            image_size = list(self.image_data.data.shape[::-1])
        else:
            image_size = [int(self.spin_x.maximum()), int(self.spin_y.maximum())]

        # Write to YAML using beamline-specific naming
        yaml_path = os.path.join(dir_path, file_status['calibration_file'])
        mask_dir = file_status['mask_dir']
        mask_file = file_status['mask_file']
        custom_mask = file_status['custom_mask']
        
        with open(yaml_path, "w") as f:
            f.write(f"wavelength_A: {wavelength_A}  # X-ray wavelength in Angstroms ({energy_eV} eV)\n")
            f.write(f"image_size: {image_size}  # [horizontal, vertical] in pixels\n")
            f.write(f"pixel_size_um: {pixel_size_um}  # pixel size in microns\n")
            f.write(f"beam_position: {beam_position}  # beam position in pixels\n")
            f.write(f"distance: {distance}  # sample to detector distance in meters\n")
            f.write(f"mask_dir: \"{mask_dir}\"\n")
            f.write(f"mask_file: \"{mask_file}\"\n")
            f.write(f"custom_mask: \"{custom_mask}\"\n")
        self.parent_app.show_status(f"Calibration parameters exported to {yaml_path}")

    def on_mouse_click(self, event):
        """Handle mouse clicks on the raw image for ring center calculation"""
        if not event.inaxes or event.inaxes != self.ax_raw:
            return
        
        # Mouse button mapping: 1=left, 2=middle, 3=right
        if event.button == 3:  # Right click for coordinate selection (left click reserved for zoom/pan)
            x, y = event.xdata, event.ydata
            if x is not None and y is not None:
                # Fill the next available coordinate field (cycles through 10 points)
                x_input, y_input = self.ring_center_inputs[self.current_point_index]
                x_input.setValue(x)
                y_input.setValue(y)
                
                # Visual feedback - add yellow marker
                if hasattr(self, 'ax_raw'):
                    temp_point = self.ax_raw.scatter([x], [y], c='yellow', s=100, marker='o', alpha=0.7)
                    
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

    def keyPressEvent(self, event):
        """Handle key press events"""
        # Enter key to update plot
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.update_plot()