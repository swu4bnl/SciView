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
    QDoubleSpinBox, QLineEdit, QComboBox, QGridLayout, QCheckBox, QSpinBox, QFormLayout
)
from PyQt5.QtCore import Qt, QTimer

import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)

# Import base class and configuration
from tabs.base_image_tab import BaseImageTab
from sciview.interfaces.theme.app_style import (
    AppStyle,
    apply_emphasis_button_style,
    apply_info_style,
    apply_status_led_style,
    apply_subtitle_style,
    apply_title_style,
    setup_splitter_layout,
)
from sciview.calibration.standards_db import STANDARDS
from sciview.interfaces.stable_qt.tools.ring_center import RingCenterCalculator
from sciview.interfaces.stable_qt.utils.file_dialog_state import dialog_select_directory, dialog_save_file
from sciview.processing.calibration_profiles import compute_calibration_profiles
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION, get_file_status as get_profile_file_status
from sciview.settings.app_settings import MASK_BASE_DIR, PHYSICAL_CONSTANTS
from sciview.calibration.io import build_calibration_payload, write_calibration_yaml

# Get constants
HC_E = PHYSICAL_CONSTANTS['hc_over_e_eV_A']


class CalibrationApp(BaseImageTab):
    """Main calibration application widget"""

    MAX_RING_POINTS = 15  # ring-center pick slots; drives indicator count, cycling, and status text

    def __init__(self, parent_app):
        super().__init__(parent_app)
        
        # Initialize ring center calculator
        self.ring_calculator = RingCenterCalculator()

        # Picked ring points live here, not in the UI; the panel only shows pick-state dots.
        self._ring_points = [None] * self.MAX_RING_POINTS
        self.current_point_index = 0
        self.temp_markers = []  # Track temporary yellow markers
        self.ring_point_indicators = []

        # Add crosshair hook to show beam center
        self.add_display_hook(self._add_beam_center_crosshair, 'post')
        
        # Load standards database
        self.standards_db = self._load_standards_db()
        self.selected_standard = None

        # Store 1D profile data for export
        self._profile_data = None
        self._last_profile_signature = None
        self._calibration_update_delay_ms = 150
        self._calibration_update_timer = QTimer(self)
        self._calibration_update_timer.setSingleShot(True)
        self._calibration_update_timer.timeout.connect(self.calibrate_and_update_status)
        self._profile_bins = 600
        
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
        controls_splitter.addWidget(self.make_scrollable_panel(ring_center_panel))

        # Standards reference panel — pick a standard right after finding the ring
        # center, so its reference lines are up before fine-tuning parameters below.
        standards_panel = self._create_standards_panel()
        controls_splitter.addWidget(self.make_scrollable_panel(standards_panel))

        # Calibration parameters panel
        calibration_panel = self._create_calibration_panel()
        controls_splitter.addWidget(self.make_scrollable_panel(calibration_panel))
        
        # Set initial sizes for control panels with ring workflow first.
        control_ratios = [2, 1, 4]
        setup_splitter_layout(controls_splitter, control_ratios)
        
        main_splitter.addWidget(controls_splitter)

        # Set initial sizes for main areas (visualization larger than controls)
        setup_splitter_layout(main_splitter, AppStyle.get_layout_ratios()['main_splitter_ratio'])
        
        main_layout.addWidget(main_splitter)

        # Connect image viewer and matplotlib plot events
        self.image_viewer.mouse_pressed.connect(self.on_mouse_click)
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
        
        title = QLabel("1D Profiles ")
        apply_subtitle_style(title)
        title_layout.addWidget(title)

        tip_label = QLabel("Tweak beam center to align peaks")
        title_layout.addWidget(tip_label)
        
        title_layout.addStretch()  # Push scale controls to the right
        
        scale_label = QLabel("Scale:")
        title_layout.addWidget(scale_label)
        
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["linear", "logx", "logy", "loglog"])
        self.scale_combo.currentTextChanged.connect(self.update_plot_calibration)
        self.scale_combo.setMinimumWidth(88)
        title_layout.addWidget(self.scale_combo)

        btn_export_1d = QPushButton("Export 1D")
        btn_export_1d.setMinimumWidth(88)
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
        layout.addWidget(toolbar)
        
        return panel

    def _create_calibration_panel(self):
        """Create the calibration parameters panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(*([AppStyle.LAYOUT['panel_inner_margin']] * 4))
        
        # Title
        title = QLabel("Calibration Parameters")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Parameter spinboxes using config defaults
        params_form = QFormLayout()
        self.configure_adaptive_form_layout(params_form)
        calibration_params = [
            ("spin_x", ("<u>Beam Center X</u>", -1024, 4096, DEFAULT_CALIBRATION['beam_center_x'], 1)),
            ("spin_y", ("<u>Beam Center Y</u>", -1024, 4096, DEFAULT_CALIBRATION['beam_center_y'], 1)),
            ("spin_orient", ("Detector Orient (°)", -180, 180, DEFAULT_CALIBRATION['detector_orient_deg'], 1)),
            ("spin_tilt", ("Detector Tilt (°)", -180, 180, DEFAULT_CALIBRATION['detector_tilt_deg'], 1)),
            ("spin_phi", ("Detector Phi (°)", -180, 180, DEFAULT_CALIBRATION['detector_phi_deg'], 1)),
            ("spin_dist", ("<u>Distance (m)</u>", 0.001, 200, DEFAULT_CALIBRATION['distance_m'], 0.001)),
            ("spin_pixel", ("Pixel Size (µm)", 0, 5000, DEFAULT_CALIBRATION['pixel_size_um'], 0.1)),
        ]
        
        for attr, params in calibration_params:
            setattr(self, attr, self._create_spin(*params, parent=params_form))

        # Wavelength/Energy section
        self.spin_wl_ang = QDoubleSpinBox()
        self.spin_wl_ang.setRange(0.01, 10.0)
        self.spin_wl_ang.setSingleStep(0.001)
        self.spin_wl_ang.setDecimals(4)
        self.spin_wl_ang.setValue(DEFAULT_CALIBRATION['wavelength_A'])
        self.spin_wl_ang.setAlignment(Qt.AlignRight)
        self.spin_wl_ang.setMinimumWidth(AppStyle.wide_input_min_width())
        self.spin_wl_ang.valueChanged.connect(self.on_wavelength_changed)
        params_form.addRow(QLabel("Wavelength (Å):"), self._right_aligned_field_row(self.spin_wl_ang))

        self.spin_energy_ev = QDoubleSpinBox()
        self.spin_energy_ev.setRange(100.0, 50000.0)
        self.spin_energy_ev.setSingleStep(1.0)
        self.spin_energy_ev.setValue(DEFAULT_CALIBRATION['energy_eV'])
        self.spin_energy_ev.setAlignment(Qt.AlignRight)
        self.spin_energy_ev.setMinimumWidth(AppStyle.wide_input_min_width())
        self.spin_energy_ev.valueChanged.connect(self.on_energy_changed)
        energy_label = QLabel("<u>Energy (eV):</u>")
        params_form.addRow(energy_label, self._right_aligned_field_row(self.spin_energy_ev))

        layout.addLayout(params_form)

        # Action buttons
        btns_layout = QHBoxLayout()
        btn_cal = QPushButton("Calibrate")
        btn_cal.clicked.connect(self.calibrate_and_update_status)
        btn_cal.setMinimumWidth(AppStyle.action_button_min_width())
        apply_emphasis_button_style(btn_cal)
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
        layout.setContentsMargins(*([AppStyle.LAYOUT['panel_inner_margin']] * 4))
        
        # Title
        title = QLabel("Calculate Ring Center")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Instructions
        instructions_label = QLabel("Right-click 3+ points on a ring.")
        instructions_label.setWordWrap(True)
        apply_info_style(instructions_label)
        layout.addWidget(instructions_label)

        # Snap options come first so they're set before the user starts picking.
        snap_row = QHBoxLayout()
        snap_row.setContentsMargins(0, 0, 0, 0)
        snap_row.setSpacing(6)
        self.snap_to_max_check = QCheckBox("Snap to Peak")
        self.snap_to_max_check.setToolTip("Snap each right-click to the brightest nearby pixel")
        self.snap_to_max_check.setChecked(True)
        snap_row.addWidget(self.snap_to_max_check)

        window_label = QLabel("Window")
        window_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        window_label.setMinimumWidth(AppStyle.inline_label_width())
        snap_row.addWidget(window_label)

        self.snap_window_spin = QSpinBox()
        self.snap_window_spin.setRange(3, 15)
        self.snap_window_spin.setSingleStep(2)
        self.snap_window_spin.setValue(5)
        self.snap_window_spin.setToolTip("Odd-size local search window (3-15 pixels)")
        self.snap_window_spin.setFixedWidth(AppStyle.compact_input_min_width())
        snap_row.addWidget(self.snap_window_spin)

        px_label = QLabel("px")
        px_label.setMinimumWidth(AppStyle.unit_label_width())
        snap_row.addWidget(px_label)
        snap_row.addStretch()
        layout.addLayout(snap_row)

        # Pick-state LEDs sit right under the snap options so picking progress
        # is visible before the user reaches the Calculate button below.
        # The actual (x, y) values live in self._ring_points, not in any widget.
        # Plain QLabel dots: this is a status readout, not a clickable control.
        indicators_row = QHBoxLayout()
        indicators_row.setContentsMargins(0, 0, 0, 0)
        indicators_row.setSpacing(AppStyle.LAYOUT['section_spacing'])
        self.ring_point_indicators = []
        for i in range(self.MAX_RING_POINTS):
            indicator = QLabel()
            indicator.setToolTip(f"Point {i + 1} ({'required' if i < 3 else 'optional'})")
            apply_status_led_style(indicator, state='off')
            self.ring_point_indicators.append(indicator)
            indicators_row.addWidget(indicator)
        indicators_row.addStretch()
        layout.addLayout(indicators_row)

        # Calculate is only clickable once enough points are picked.
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(6)
        self.calc_ring_button = QPushButton("Calculate")
        self.calc_ring_button.clicked.connect(self.calculate_ring_center)
        self.calc_ring_button.setMinimumWidth(AppStyle.action_button_min_width())
        self.calc_ring_button.setEnabled(False)
        apply_emphasis_button_style(self.calc_ring_button)
        controls_row.addWidget(self.calc_ring_button)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_ring_points)
        controls_row.addWidget(clear_button)
        controls_row.addStretch()
        layout.addLayout(controls_row)

        # Result display
        self.ring_result_label = QLabel("")
        self.ring_result_label.setWordWrap(True)
        apply_info_style(self.ring_result_label)
        layout.addWidget(self.ring_result_label)

        self._update_ring_picking_state()

        return panel

    def _create_standards_panel(self):
        """Create the standards reference panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(*([AppStyle.LAYOUT['panel_inner_margin']] * 4))

        title = QLabel("Check Against a Standard")
        apply_title_style(title)
        layout.addWidget(title)

        # Dropdown menu
        self.standards_combo = QComboBox()
        self.standards_combo.addItem("None")
        for mat in sorted(self.standards_db.keys()):
            self.standards_combo.addItem(mat)
        self.standards_combo.currentTextChanged.connect(self.on_standard_selected)
        layout.addWidget(self.standards_combo)
        self.standards_combo.setMaximumHeight(32)

        # Info label
        self.standards_info_label = QLabel("Pick a standard above to overlay its reference lines.")
        self.standards_info_label.setWordWrap(True)
        apply_info_style(self.standards_info_label)
        layout.addWidget(self.standards_info_label)

        panel.setMaximumHeight(120)

        return panel

    def _create_spin(self, label, mn, mx, default, step, *, parent):
        """Create a labeled spin box with status update connection"""
        form = parent if isinstance(parent, QFormLayout) else None
        if form is not None:
            row = None
            lay = None
        else:
            lay = QHBoxLayout()
            lay.addWidget(QLabel(label))

        spin = QDoubleSpinBox()
        spin.setRange(mn, mx)
        spin.setSingleStep(step)
        spin.setValue(default)
        spin.setDecimals(4 if step < 0.01 else 2)
        spin.setAlignment(Qt.AlignRight)
        spin.setMinimumWidth(AppStyle.wide_input_min_width())
        spin.valueChanged.connect(self._schedule_calibration_update)

        if form is not None:
            form.addRow(QLabel(label), self._right_aligned_field_row(spin))
        else:
            lay.addWidget(spin)
            parent.addLayout(lay)
        return spin

    @staticmethod
    def _right_aligned_field_row(widget):
        """Wrap a field widget so it stays aligned to the right edge of the form row."""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addStretch()
        lay.addWidget(widget)
        return row

    def _schedule_calibration_update(self, *_args):
        self.parent_app.show_status("Calibration update pending...")
        self._calibration_update_timer.start(self._calibration_update_delay_ms)

    def _load_standards_db(self):
        """Load standards database"""
        return dict(STANDARDS)

    def _add_beam_center_crosshair(self, viewer):
        """Hook to add crosshair at beam center position"""
        if hasattr(self, 'spin_x') and hasattr(self, 'spin_y'):
            center_x = self.spin_x.value()
            center_y = self.spin_y.value()
            
            # Add crosshair lines
            if hasattr(self, 'image_data') and self.image_data is not None:
                viewer.clear_overlays(group='calibration-crosshair')
                viewer.add_crosshair('beam-center', center_x, center_y, group='calibration-crosshair', color='#ff0000')

    def _set_ring_point_indicator(self, index, state):
        """Set a single pick-state LED: 'off', 'good', 'warn' (outlier), or 'error' (fit failed)."""
        apply_status_led_style(self.ring_point_indicators[index], state=state)

    def _update_ring_picking_state(self):
        """Gate the Calculate button and show a short picking-progress hint."""
        picked = sum(1 for point in self._ring_points if point is not None)
        self.calc_ring_button.setEnabled(picked >= 3)
        if picked < 3:
            self.ring_result_label.setText(f"{picked}/{self.MAX_RING_POINTS} points picked (need 3+)")
        else:
            self.ring_result_label.setText(f"{picked}/{self.MAX_RING_POINTS} points picked")

    def calculate_ring_center(self):
        """Calculate the center of a circle from multiple points, auto-excluding outliers on failure"""
        picked_indices = [i for i, point in enumerate(self._ring_points) if point is not None]
        points = [self._ring_points[i] for i in picked_indices]

        try:
            # calculate_center_robust retries with the worst point dropped if the plain fit fails.
            ux, uy, radius, used_positions, dropped_positions = self.ring_calculator.calculate_center_robust(points)
            used_indices = [picked_indices[p] for p in used_positions]
            dropped_indices = [picked_indices[p] for p in dropped_positions]
            used_points = [points[p] for p in used_positions]

            # Store the calculated center
            self.calculated_ring_center = (ux, uy)

            # Apply calculated center directly to beam position controls.
            self.spin_x.setValue(ux)
            self.spin_y.setValue(uy)
            self.calibrate_and_update_status()

            for i in dropped_indices:
                self._set_ring_point_indicator(i, 'warn')  # auto-excluded outlier

            # Flag any used point whose fit residual stands out from the rest as an outlier,
            # reusing the calculator's own fit-quality tolerance (single source of truth).
            outlier_tolerance = radius * self.ring_calculator.max_relative_radius_std
            for i, (x, y) in zip(used_indices, used_points):
                residual = abs(((x - ux) ** 2 + (y - uy) ** 2) ** 0.5 - radius)
                self._set_ring_point_indicator(i, 'warn' if residual > outlier_tolerance else 'good')

            # Fit score reuses the calculator's own quality metric (0-1, higher is better).
            quality = self.ring_calculator.validate_ring_quality(used_points, (ux, uy))
            fit_score_pct = quality['quality_score'] * 100.0
            result_text = f"Center ({ux:.1f}, {uy:.1f}), r={radius:.1f}px, fit={fit_score_pct:.0f}%"
            if dropped_indices:
                result_text += f" ({len(dropped_indices)} excluded)"
            self.ring_result_label.setText(result_text)
            
            # Mark points and center on the raw image
            if hasattr(self, 'image_viewer') and self.image_data is not None:
                self.image_viewer.clear_overlays(group='ring-center')

                # Plot the points used in the fit
                xs, ys = zip(*used_points)
                self.image_viewer.add_points('ring-points', xs, ys, group='ring-center', color='#00ffff', size=9.0, pen='#0000ff')
                
                # Plot the calculated center
                self.image_viewer.add_points('ring-center-point', [ux], [uy], group='ring-center', color='#ff0000', size=12.0, symbol='+')
                
                # Draw the circle
                self.image_viewer.add_circle('ring-center-circle', ux, uy, radius, group='ring-center', color='#ff0000', width=2.0)
            
            status_message = f"Ring center calculated and applied: ({ux:.2f}, {uy:.2f}) using {len(used_points)} points"
            if dropped_indices:
                status_message += f" ({len(dropped_indices)} outliers excluded)"
            self.parent_app.show_status(status_message)
            
            # Update status info to show ring center calculation
            self.update_status_info()
            
        except ValueError as e:
            for i in picked_indices:
                self._set_ring_point_indicator(i, 'error')
            self.ring_result_label.setText(f"Fit failed: {str(e)}")
            self.parent_app.show_status(f"Error calculating ring center: {str(e)}")
        except Exception as e:
            for i in picked_indices:
                self._set_ring_point_indicator(i, 'error')
            self.ring_result_label.setText(f"Fit failed: {str(e)}")
            self.parent_app.show_status(f"Unexpected error: {str(e)}")

    def update_beam_from_ring(self):
        """Legacy compatibility wrapper for old button callback paths."""
        self.calculate_ring_center()

    def clear_ring_points(self):
        """Clear all picked ring points, indicators, and markers"""
        self._ring_points = [None] * self.MAX_RING_POINTS
        for index in range(len(self.ring_point_indicators)):
            self._set_ring_point_indicator(index, 'off')

        # Clear temporary yellow markers
        self.temp_markers = []
        if hasattr(self, 'image_viewer'):
            self.image_viewer.clear_overlays(group='ring-temp')

        self.current_point_index = 0
        self._update_ring_picking_state()
        self.parent_app.show_status("Ring points cleared")

    def _add_tab_specific_status(self, info_lines):
        """Add calibration-specific status information"""
        info_lines.append("")  # Blank line separator
        
        # === RING CENTER STATUS ===
        info_lines.append("=== RING CENTER STATUS ===")
        ring_points_count = sum(1 for point in self._ring_points if point is not None)
        info_lines.append(f"Ring points entered: {ring_points_count}/{self.MAX_RING_POINTS}")
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

    def on_wavelength_changed(self, *_args):
        """Handle wavelength changes"""
        wavelength = self.spin_wl_ang.value()
        energy = HC_E / wavelength
        self.spin_energy_ev.blockSignals(True)
        self.spin_energy_ev.setValue(energy)
        self.spin_energy_ev.blockSignals(False)
        self._schedule_calibration_update()

    def on_energy_changed(self, *_args):
        """Handle energy changes"""
        energy = self.spin_energy_ev.value()
        wavelength = HC_E / energy
        self.spin_wl_ang.blockSignals(True)
        self.spin_wl_ang.setValue(wavelength)
        self.spin_wl_ang.blockSignals(False)
        self._schedule_calibration_update()

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
            self.standards_info_label.setText("Pick a standard above to overlay its reference lines.")
        else:
            self.selected_standard = text
            qvals = self.standards_db.get(text, [])
            self.standards_info_label.setText(f"Showing {len(qvals)} reference lines for {text}.")
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

    def update_plot(self, image_data=None):
        """Update 2D image viewer and 1D calibration plots/crosshair."""
        super().update_plot(image_data)
        if self.image_data is not None:
            plot_xlim, plot_ylim = self.ax_plot.get_xlim(), self.ax_plot.get_ylim()
            plot_xlim_valid = not np.allclose(plot_xlim, (0, 1))
            plot_ylim_valid = not np.allclose(plot_ylim, (0, 1))
            self._refresh_calibration_crosshair()
            self._update_1d_plots(plot_xlim, plot_ylim, plot_xlim_valid, plot_ylim_valid)

    def on_shared_state_activated(self):
        """Refresh calibration tab state when tab becomes active."""
        self.update_plot_calibration()

    def update_plot_calibration(self):
        """Update plots based on current calibration and image data"""
        if self.image_data is None:
            return
        
        # Store current limits for 1D plot
        plot_xlim, plot_ylim = self.ax_plot.get_xlim(), self.ax_plot.get_ylim()
        plot_xlim_valid = not np.allclose(plot_xlim, (0, 1))
        plot_ylim_valid = not np.allclose(plot_ylim, (0, 1))

        if getattr(self.image_viewer, 'source_array', None) is None:
            super().update_plot()
        else:
            self._refresh_calibration_crosshair()
        
        # Then, update the 1D plots
        self._update_1d_plots(plot_xlim, plot_ylim, plot_xlim_valid, plot_ylim_valid)
    
    def _update_1d_plots(self, plot_xlim, plot_ylim, plot_xlim_valid, plot_ylim_valid):
        """Update the 1D analysis plots"""
        # Update calibration if SciAnalysis is available
        if self.scianalysis_available and self.image_data:
            if not hasattr(self.image_data, 'calibration') or self.image_data.calibration is None:
                if hasattr(self.parent_app, 'calibration') and self.parent_app.calibration is not None:
                    self.image_data.calibration = self.parent_app.calibration
                elif hasattr(self, 'calibration') and self.calibration is not None:
                    self.image_data.calibration = self.calibration
                else:
                    from sciview.profiles.cms_profile import get_calibration_class
                    cal_cls = get_calibration_class()
                    self.image_data.calibration = cal_cls(wavelength_A=self.spin_wl_ang.value())

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
            
            # Calculate Q-space preview profiles using the backend fast path.
            try:
                profiles = compute_calibration_profiles(
                    image=self.image_data.data,
                    calibration=self.image_data.calibration,
                    bins=self._profile_bins,
                    sector_dangle_deg=5.0,
                )
                circ = profiles.circular
                hor_1 = profiles.horizontal_0
                hor_2 = profiles.horizontal_180
                ver_1 = profiles.vertical_90
                ver_2 = profiles.vertical_270
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
        self._profile_data = profiles.as_dict()

        # Update 1D plot with real data
        self._draw_1d_plots(circ, hor_1, hor_2, ver_1, ver_2, plot_xlim, plot_ylim, plot_xlim_valid, plot_ylim_valid)

    def _refresh_calibration_crosshair(self):
        if not hasattr(self, 'image_viewer') or self.image_data is None:
            return
        self.image_viewer.clear_overlays(group='calibration-crosshair')
        self.image_viewer.add_crosshair(
            'beam-center',
            self.spin_x.value(),
            self.spin_y.value(),
            group='calibration-crosshair',
            color='#ff0000',
        )
    
    def _clear_1d_plots(self):
        """Clear 1D plots when SciAnalysis is not available or analysis fails"""
        self.ax_plot.clear()
        self._last_profile_signature = None
        body_font = AppStyle.matplotlib_font_size('body')
        caption_font = AppStyle.matplotlib_font_size('caption')
        small_font = AppStyle.matplotlib_font_size('small')
        self.ax_plot.text(0.5, 0.5, 'No Q-space analysis available\n\nRequires:\n• Valid image data\n• SciAnalysis library\n• Proper calibration parameters', 
                         transform=self.ax_plot.transAxes, 
                         ha='center', va='center', 
                         fontsize=body_font, color='gray',
                         bbox=dict(boxstyle='round,pad=0.5', facecolor='lightgray', alpha=0.7))
        self.ax_plot.set_xlabel('Q (Å⁻¹)', fontsize=caption_font)
        self.ax_plot.set_ylabel('Intensity', fontsize=caption_font)
        self.ax_plot.tick_params(labelsize=small_font)
        AppStyle.apply_matplotlib_figure_theme(self.fig_plot)
        self.canvas_plot.draw()
    
    def _draw_1d_plots(self, circ, hor_1, hor_2, ver_1, ver_2, plot_xlim, plot_ylim, plot_xlim_valid, plot_ylim_valid):
        """Draw the 1D plots with given data"""
        # Update 1D plot
        self.ax_plot.clear()
        caption_font = AppStyle.matplotlib_font_size('caption')
        small_font = AppStyle.matplotlib_font_size('small')
        self.ax_plot.plot(circ.x, circ.y, label='Circular Avg', color='#44EE44', linewidth=1.5)
        self.ax_plot.plot(hor_1.x, hor_1.y, label='Horizontal 0°', color='#EE6622', linewidth=1.2)
        self.ax_plot.plot(hor_2.x, hor_2.y, label='Horizontal 180°', color='#EE2266', linewidth=1.2)
        self.ax_plot.plot(ver_1.x, ver_1.y, label='Vertical 90°', color='#2266EE', linewidth=1.2)
        self.ax_plot.plot(ver_2.x, ver_2.y, label='Vertical 270°', color='#6622EE', linewidth=1.2)

        # Draw standard lines if selected
        self._draw_standard_lines()

        # Set labels and legend with smaller fonts
        self.ax_plot.set_xlabel('Q (Å⁻¹)', fontsize=caption_font)
        self.ax_plot.set_ylabel('Intensity', fontsize=caption_font)
        self.ax_plot.legend(fontsize=small_font, loc='best', frameon=False)
        self.ax_plot.tick_params(labelsize=small_font)
        
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
        AppStyle.apply_matplotlib_figure_theme(self.fig_plot)
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
        if not getattr(event, 'inside_image', False):
            return
        
        # Mouse button mapping: 1=left, 2=middle, 3=right
        if event.button == Qt.RightButton:  # Right click for coordinate selection (left click reserved for zoom/pan)
            x, y = event.x, event.y
            if x is not None and y is not None:
                display_x, display_y = x, y
                if getattr(self, 'snap_to_max_check', None) is not None and self.snap_to_max_check.isChecked():
                    snapped = self._snap_to_local_max(x, y, half_window=self._get_snap_window_half_size())
                    if snapped is not None:
                        display_x, display_y = snapped

                # Fill the next available point slot (cycles through the point slots)
                self._ring_points[self.current_point_index] = (display_x, display_y)
                self._set_ring_point_indicator(self.current_point_index, 'good')
                self._update_ring_picking_state()

                # Visual feedback - add yellow marker
                if hasattr(self, 'image_viewer'):
                    marker_id = f"ring-temp-{len(self.temp_markers)}"
                    self.image_viewer.add_points(marker_id, [display_x], [display_y], group='ring-temp', color='#ffff00', size=12.0)
                    self.temp_markers.append(marker_id)
                    
                    # Remove oldest marker if we exceed the point-slot cap
                    if len(self.temp_markers) > self.MAX_RING_POINTS:
                        oldest_marker_id = self.temp_markers.pop(0)
                        self.image_viewer.remove_overlay(oldest_marker_id)
                
                self.current_point_index = (self.current_point_index + 1) % self.MAX_RING_POINTS
                
                # Update status
                if self.current_point_index == 0:
                    self.parent_app.show_status(f"All {self.MAX_RING_POINTS} points filled. Click 'Calculate Ring Center' or continue right-clicking to replace points.")
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