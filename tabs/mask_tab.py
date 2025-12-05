"""
Mask Tab Module

This module provides comprehensive mask editing functionality with a layered
approach similar to GIMP. Users can create, edit, combine, and export masks
using multiple layers with boolean operations.

Features:
- Layer-based mask editing (add, remove, reorder, toggle visibility)
- Load instrument default masks and custom masks
- Generate masks using image processing (threshold, filters)
- External editor integration (GIMP)
- Combine layers with boolean operations (OR/AND)
- Export masks in multiple formats
"""

import os
import sys
import numpy as np
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional

try:
    from scipy.interpolate import interp1d
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QCheckBox, QComboBox, QSpinBox, QListWidget, QListWidgetItem,
    QGroupBox, QSlider, QDoubleSpinBox, QFileDialog, QMessageBox,
    QScrollArea, QSplitter, QButtonGroup, QRadioButton
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QCursor

import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)

# Import base class and configuration
from tabs.base_image_tab import BaseImageTab
from config.beamline_config import (
    DEFAULT_CALIBRATION, PHYSICAL_CONSTANTS, get_file_status,
    MASK_BASE_DIR, DETECTOR_CONFIGS
)
from config.app_style import *
from utils.image_utils import validate_and_prepare_image_array, ImageShapeConverter


class MaskLayer:
    """Represents a single mask layer with metadata"""
    
    def __init__(self, data: np.ndarray, name: str = "Layer", visible: bool = True):
        self.data = data.astype(bool)  # True = masked, False = unmasked
        self.name = name
        self.visible = visible
        self.source = "custom"  # "default", "custom", "generated", "external"
    
    def __repr__(self):
        return f"MaskLayer('{self.name}', visible={self.visible}, shape={self.data.shape})"


class MaskApp(BaseImageTab):
    """Comprehensive mask editing application with layered approach"""
    
    def __init__(self, parent_app):
        super().__init__(parent_app)
        
        # Layer-based mask system
        self.mask_layers: List[MaskLayer] = []
        self.combined_mask: Optional[np.ndarray] = None
        self.combine_method = "OR"  # OR or AND
        
        # Mask editing state
        self.drawing_mode = False
        self.draw_mask_value = True  # True = mask (add), False = unmask (remove)
        self.brush_size = 5
        self.is_dragging = False  # Track if currently dragging the brush
        self.last_draw_point = None  # Track last point for line interpolation
        self.toolbar_image = None  # Reference to toolbar for mode management
        
        # Temporary files for external editing
        self.temp_files = []
        
        # Add mask overlay hook to post-display hooks
        self.add_display_hook(self._add_mask_overlay, 'post')
        
        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build the main user interface"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Main horizontal splitter: visualization area | controls area
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Visualization area
        visualization_panel = self._create_visualization_panel()
        main_splitter.addWidget(visualization_panel)

        # Right side: Controls area with vertical splitter for each panel
        controls_splitter = QSplitter(Qt.Vertical)
        
        # Image information panel (inherited from base class)
        image_info_panel = self._create_image_info_panel()
        controls_splitter.addWidget(image_info_panel)
        
        # Layer management panel
        layer_panel = self._create_layer_panel()
        controls_splitter.addWidget(layer_panel)
        
        # Mask generation panel
        generation_panel = self._create_generation_panel()
        controls_splitter.addWidget(generation_panel)
        
        # External editor panel
        external_panel = self._create_external_editor_panel()
        controls_splitter.addWidget(external_panel)
        
        # Export and Apply panel 
        action_panel = self._create_action_panel()
        controls_splitter.addWidget(action_panel)
        
        # Set initial sizes for control panels
        mask_control_ratios = [100, 150, 120, 100, 100]  # Custom ratios for mask tab
        setup_splitter_layout(controls_splitter, mask_control_ratios)
        
        main_splitter.addWidget(controls_splitter)

        # Set initial sizes for main areas 
        setup_splitter_layout(main_splitter, AppStyle.get_layout_ratios()['main_splitter_ratio'])
        
        main_layout.addWidget(main_splitter)

        # Connect matplotlib events
        self.canvas_image.mpl_connect('motion_notify_event', self.on_mask_motion)
        self.canvas_image.mpl_connect('button_press_event', self.on_mask_click)
        self.canvas_image.mpl_connect('button_release_event', self.on_mask_release)

    def _create_visualization_panel(self):
        """Create the image and mask visualization panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        
        # Image display title
        title = QLabel("Image with Mask Overlay")
        apply_subtitle_style(title)
        layout.addWidget(title)

        # Filename label using inherited method
        self.create_filename_label(layout)

        # Use the base class image panel (creates self.ax_raw, self.canvas_raw, etc.)
        base_image_panel = self._create_image_panel()
        layout.addWidget(base_image_panel)
        
        # Use unified canvas references for mask tab
        self.ax_image = self.ax_raw
        self.canvas_image = self.canvas_raw

        # Mask display controls - compact layout with consistent spacing
        controls_group = QGroupBox("Display Options")
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setSpacing(8)
        controls_layout.setContentsMargins(8, 4, 8, 4)
        
        # Show/hide mask
        self.show_mask_check = QCheckBox("Show Mask")
        self.show_mask_check.setChecked(True)
        self.show_mask_check.stateChanged.connect(lambda: self.update_plot())
        controls_layout.addWidget(self.show_mask_check)
        
        # Separator
        controls_layout.addSpacing(12)
        
        # Color control
        controls_layout.addWidget(QLabel("Color:"))
        self.mask_color_combo = QComboBox()
        self.mask_color_combo.addItems(["red", "blue", "green", "yellow", "magenta", "cyan"])
        self.mask_color_combo.setMaximumWidth(90)
        self.mask_color_combo.currentTextChanged.connect(lambda: self.update_plot())
        controls_layout.addWidget(self.mask_color_combo)
        
        # Separator
        controls_layout.addSpacing(12)
        
        # Transparency control
        controls_layout.addWidget(QLabel("Transparency:"))
        self.alpha_spin = QSpinBox()
        self.alpha_spin.setRange(0, 100)
        self.alpha_spin.setValue(50)
        self.alpha_spin.setSuffix("%")
        self.alpha_spin.setMaximumWidth(80)
        self.alpha_spin.valueChanged.connect(lambda: self.update_plot())
        controls_layout.addWidget(self.alpha_spin)
        
        controls_layout.addStretch()
        layout.addWidget(controls_group)
        
        return panel

    def _create_layer_panel(self):
        """Create the layer management panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        
        # Title
        title = QLabel("Mask Layers")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Layer list
        self.layer_list = QListWidget()
        self.layer_list.setMaximumHeight(150)
        self.layer_list.itemChanged.connect(self._on_layer_item_changed)
        self.layer_list.currentRowChanged.connect(self._on_layer_selected)
        layout.addWidget(self.layer_list)
        
        # Layer control buttons - properly spaced
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)
        
        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self._add_layer_menu)
        btn_layout.addWidget(btn_add)
        
        btn_remove = QPushButton("Remove")
        btn_remove.clicked.connect(self._remove_selected_layer)
        btn_layout.addWidget(btn_remove)
        
        btn_layout.addSpacing(8)  # Separator
        
        btn_up = QPushButton("↑")
        btn_up.setMaximumWidth(40)
        btn_up.clicked.connect(self._move_layer_up)
        btn_layout.addWidget(btn_up)
        
        btn_down = QPushButton("↓")
        btn_down.setMaximumWidth(40)
        btn_down.clicked.connect(self._move_layer_down)
        btn_layout.addWidget(btn_down)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Combine method - properly aligned
        combine_layout = QHBoxLayout()
        combine_layout.setSpacing(8)
        combine_layout.addWidget(QLabel("Combine:"))
        
        self.combine_or_radio = QRadioButton("OR")
        self.combine_or_radio.setChecked(True)
        self.combine_or_radio.toggled.connect(self._update_combine_method)
        combine_layout.addWidget(self.combine_or_radio)
        
        self.combine_and_radio = QRadioButton("AND")
        combine_layout.addWidget(self.combine_and_radio)
        
        combine_layout.addStretch()
        layout.addLayout(combine_layout)
        
        # Combined mask statistics
        self.combined_stats_label = QLabel("No layers")
        self.combined_stats_label.setWordWrap(True)
        apply_info_style(self.combined_stats_label)
        layout.addWidget(self.combined_stats_label)
        
        layout.addStretch()
        return panel
    
    def _create_generation_panel(self):
        """Create the mask generation panel with image processing tools"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        # Title
        title = QLabel("Mask Generation")
        apply_title_style(title)
        layout.addWidget(title)

        ###### Threshold-based mask controls ######
        
        # Threshold-based mask
        threshold_group = QGroupBox("Threshold")
        threshold_layout = QVBoxLayout(threshold_group)
        threshold_layout.setSpacing(2)
        
        # Threshold controls in grid for better alignment
        thresh_grid = QHBoxLayout()
        
        # Mode control
        thresh_grid.addWidget(QLabel("Mode:"))
        self.threshold_mode_combo = QComboBox()
        self.threshold_mode_combo.addItems(["Above", "Below", "Range"])
        self.threshold_mode_combo.setCurrentIndex(1)
        self.threshold_mode_combo.setMinimumWidth(100)
        self.threshold_mode_combo.setMaximumWidth(120)
        thresh_grid.addWidget(self.threshold_mode_combo)
        thresh_grid.addStretch()

        # Value control
        thresh_grid.addWidget(QLabel("Value:"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-1e9, 1e9)
        self.threshold_spin.setValue(10)
        self.threshold_spin.setDecimals(1)
        self.threshold_spin.setMinimumWidth(100)
        self.threshold_spin.setMaximumWidth(120)
        thresh_grid.addWidget(self.threshold_spin)
        
        threshold_layout.addLayout(thresh_grid)
        
        btn_gen_threshold = QPushButton("Generate Threshold Mask")
        btn_gen_threshold.clicked.connect(self._generate_threshold_mask)
        threshold_layout.addWidget(btn_gen_threshold)
        
        layout.addWidget(threshold_group)
        
        ###### Filter-based mask controls ######

        # Filter-based mask
        filter_group = QGroupBox("Filter")
        filter_layout = QVBoxLayout(filter_group)
        filter_layout.setSpacing(2)
        
        # Filter controls in grid
        filter_grid = QHBoxLayout()
        
        # Type control
        filter_grid.addWidget(QLabel("Type:"))
        self.filter_type_combo = QComboBox()
        self.filter_type_combo.addItems(["Median", "Gaussian", "Edge Detection"])
        self.filter_type_combo.setMinimumWidth(100)
        filter_grid.addWidget(self.filter_type_combo)
        filter_grid.addStretch()
        
        # Size control
        filter_grid.addWidget(QLabel("Size:"))
        self.filter_size_spin = QDoubleSpinBox()
        self.filter_size_spin.setRange(1, 21)
        self.filter_size_spin.setValue(3)
        self.filter_size_spin.setDecimals(0)
        self.filter_size_spin.setSingleStep(2)
        self.filter_size_spin.setMinimumWidth(100)
        filter_grid.addWidget(self.filter_size_spin)
        
        filter_layout.addLayout(filter_grid)
        
        btn_gen_filter = QPushButton("Generate Filter Mask")
        btn_gen_filter.clicked.connect(self._generate_filter_mask)
        filter_layout.addWidget(btn_gen_filter)
        
        layout.addWidget(filter_group)
        

        ###### Manual drawing controls ######
        # Manual drawing
        drawing_group = QGroupBox("Manual Drawing")
        drawing_layout = QVBoxLayout(drawing_group)
        drawing_layout.setSpacing(2)
        
        self.drawing_mode_check = QCheckBox("Enable Drawing Mode")
        self.drawing_mode_check.stateChanged.connect(self._toggle_drawing_mode)
        drawing_layout.addWidget(self.drawing_mode_check)
        
        # Drawing controls in grid for better alignment
        draw_grid = QHBoxLayout()
        
        # Brush size
        draw_grid.addWidget(QLabel("Brush:"))
        self.brush_size_spin = QSpinBox()
        self.brush_size_spin.setRange(1, 50)
        self.brush_size_spin.setValue(5)
        self.brush_size_spin.setMinimumWidth(50)
        self.brush_size_spin.setMaximumWidth(120)
        self.brush_size_spin.valueChanged.connect(lambda v: setattr(self, 'brush_size', v))
        draw_grid.addWidget(self.brush_size_spin)
        
        # Draw mode
        draw_grid.addWidget(QLabel("Mode:"))
        self.draw_add_radio = QRadioButton("Add")
        self.draw_add_radio.setChecked(True)
        self.draw_remove_radio = QRadioButton("Remove")
        draw_grid.addWidget(self.draw_add_radio)
        draw_grid.addWidget(self.draw_remove_radio)
        draw_grid.addStretch()
        
        drawing_layout.addLayout(draw_grid)
        
        layout.addWidget(drawing_group)
        
        layout.addStretch()
        return panel
    
    def _create_external_editor_panel(self):
        """Create the external editor integration panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        
        # Title
        title = QLabel("External Editor")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Instructions
        info = QLabel("Export to GIMP for advanced editing")
        info.setWordWrap(True)
        apply_info_style(info)
        layout.addWidget(info)
        
        # Export to GIMP button
        btn_gimp = QPushButton("Open in GIMP")
        btn_gimp.clicked.connect(self._open_in_gimp)
        layout.addWidget(btn_gimp)
        
        # Reload mask from file
        btn_reload = QPushButton("Import from External Edit")
        btn_reload.clicked.connect(self._import_external_mask)
        layout.addWidget(btn_reload)
        
        layout.addStretch()
        return panel

    def _create_action_panel(self):
        """Create the action panel with export and apply mask buttons"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        
        # Title
        title = QLabel("Actions")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Export Selected Layer button
        btn_export_layer = QPushButton("Export Selected Layer")
        btn_export_layer.clicked.connect(self._export_selected_layer)
        layout.addWidget(btn_export_layer)

        # Export Combined Mask button (green)
        btn_export_combined = QPushButton("Export Combined Mask")
        btn_export_combined.clicked.connect(self._export_combined_mask)
        btn_export_combined.setStyleSheet("background-color: #16C60C; color: white; font-weight: bold;")
        layout.addWidget(btn_export_combined)
        
        # Apply mask button (placeholder for future implementation)
        btn_apply = QPushButton("Apply Mask to Tabs")
        btn_apply.setStyleSheet("background-color: #999999; color: white; font-weight: bold;")
        btn_apply.clicked.connect(self._apply_mask_to_tabs)
        layout.addWidget(btn_apply)
        
        layout.addStretch()
        return panel
        return panel

    def _apply_mask_to_tabs(self):
        """Apply the current combined mask to other tabs and SciAnalysis objects
        
        TODO: This is a placeholder for now. Future implementation should:
        1. Store the combined mask in a shared location (parent_app)
        2. Update calibration_tab to use apply_mask=True in circular_average_q_bin()
        3. Update data_reduction_tab to use the mask in analysis
        """
        if self.combined_mask is None:
            self.parent_app.show_status("No mask to apply - create or load a mask first")
            return
        
        try:
            # Store combined mask in parent_app for other tabs to access
            if not hasattr(self.parent_app, 'current_mask'):
                self.parent_app.current_mask = None
            
            self.parent_app.current_mask = self.combined_mask.copy()
            
            # Notify other tabs of the mask update
            if hasattr(self.parent_app, 'update_all_displays'):
                self.parent_app.update_all_displays()
            
            masked_pixels = np.sum(self.combined_mask)
            total_pixels = self.combined_mask.size
            mask_percentage = (masked_pixels / total_pixels) * 100
            
            self.parent_app.show_status(
                f"✓ Mask applied to tabs: {masked_pixels:,} pixels masked ({mask_percentage:.1f}%)"
            )
            
        except Exception as e:
            self.parent_app.show_status(f"Error applying mask: {str(e)}")

    def _add_tab_specific_status(self, info_lines):
        """Add mask-specific status information"""
        info_lines.append("")  # Blank line separator
        
        # === MASK STATUS ===
        info_lines.append("=== MASK LAYERS ===")
        info_lines.append(f"Number of layers: {len(self.mask_layers)}")
        info_lines.append(f"Combine method: {self.combine_method}")
        
        for i, layer in enumerate(self.mask_layers):
            visibility = "visible" if layer.visible else "hidden"
            masked_pixels = np.sum(layer.data)
            total_pixels = layer.data.size
            mask_percentage = (masked_pixels / total_pixels) * 100
            info_lines.append(
                f"  Layer {i+1}: {layer.name} ({visibility}) - "
                f"{masked_pixels:,} pixels ({mask_percentage:.1f}%)"
            )
        
        if self.combined_mask is not None:
            info_lines.append("")
            info_lines.append("=== COMBINED MASK ===")
            masked_pixels = np.sum(self.combined_mask)
            total_pixels = self.combined_mask.size
            mask_percentage = (masked_pixels / total_pixels) * 100
            info_lines.append(f"Masked pixels: {masked_pixels:,} ({mask_percentage:.1f}%)")

    # ===== Layer Management Methods =====
    
    def _update_layer_list(self):
        """Update the layer list widget"""
        self.layer_list.blockSignals(True)  # Prevent triggering itemChanged during update
        self.layer_list.clear()
        
        for i, layer in enumerate(self.mask_layers):
            item = QListWidgetItem(f"{i+1}. {layer.name}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
            self.layer_list.addItem(item)
        
        self.layer_list.blockSignals(False)
        self._update_combined_mask()
    
    def _on_layer_item_changed(self, item):
        """Handle layer visibility toggle"""
        row = self.layer_list.row(item)
        if 0 <= row < len(self.mask_layers):
            self.mask_layers[row].visible = (item.checkState() == Qt.Checked)
            self._update_combined_mask()
    
    def _on_layer_selected(self, row):
        """Handle layer selection"""
        if row >= 0:
            self.parent_app.show_status(f"Selected layer: {self.mask_layers[row].name}")
    
    def _add_layer_menu(self):
        """Show menu for adding a new layer"""
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        
        menu.addAction("Empty Layer", self._add_empty_layer)
        menu.addAction("From File", self._load_custom_mask)
        
        # Add submenu for instrument default masks by detector
        instrument_submenu = menu.addMenu("From Instrument Default")
        for detector_key, detector_config in DETECTOR_CONFIGS.items():
            detector_name = detector_config.get('name', detector_key)
            action = instrument_submenu.addAction(detector_name)
            # Use lambda with default argument to capture detector_key
            action.triggered.connect(lambda checked=False, dk=detector_key: self._load_instrument_mask(dk))
        
        menu.addAction("From Current Image (Threshold)", self._generate_threshold_mask)
        
        menu.exec_(self.sender().mapToGlobal(self.sender().rect().bottomLeft()))
    
    def _add_empty_layer(self):
        """Add an empty mask layer"""
        # Validate and prepare image for use
        image_2d, is_valid, error_msg = validate_and_prepare_image_array(self.image_data)
        
        if not is_valid:
            self.parent_app.show_status(error_msg or "Load an image first. Use 'Sync to Other Tabs' in Image Browser.")
            return
        
        try:
            # Create empty mask matching image dimensions
            empty_mask = np.zeros(image_2d.shape, dtype=bool)
            
            layer = MaskLayer(empty_mask, f"Empty Layer {len(self.mask_layers)+1}")
            layer.source = "custom"
            self.mask_layers.append(layer)
            
            self._update_layer_list()
            self.parent_app.show_status("Added empty layer")
            
        except Exception as e:
            self.parent_app.show_status(f"Error creating empty layer: {str(e)}")
            print(f"DEBUG: _add_empty_layer error: {e}")
            print(f"DEBUG: image_data type: {type(self.image_data)}")
    
    def _remove_selected_layer(self):
        """Remove the selected layer"""
        current_row = self.layer_list.currentRow()
        if current_row < 0:
            self.parent_app.show_status("No layer selected")
            return
        
        removed_layer = self.mask_layers.pop(current_row)
        self._update_layer_list()
        self.parent_app.show_status(f"Removed layer: {removed_layer.name}")
    
    def _move_layer_up(self):
        """Move selected layer up"""
        current_row = self.layer_list.currentRow()
        if current_row <= 0:
            return
        
        self.mask_layers[current_row], self.mask_layers[current_row-1] = \
            self.mask_layers[current_row-1], self.mask_layers[current_row]
        
        self._update_layer_list()
        self.layer_list.setCurrentRow(current_row - 1)
    
    def _move_layer_down(self):
        """Move selected layer down"""
        current_row = self.layer_list.currentRow()
        if current_row < 0 or current_row >= len(self.mask_layers) - 1:
            return
        
        self.mask_layers[current_row], self.mask_layers[current_row+1] = \
            self.mask_layers[current_row+1], self.mask_layers[current_row]
        
        self._update_layer_list()
        self.layer_list.setCurrentRow(current_row + 1)
    
    def _update_combine_method(self):
        """Update the combine method and recalculate combined mask"""
        self.combine_method = "OR" if self.combine_or_radio.isChecked() else "AND"
        self._update_combined_mask()
    
    def _update_combined_mask(self):
        """Combine all visible layers into a single mask"""
        visible_layers = [layer.data for layer in self.mask_layers if layer.visible]
        
        if not visible_layers:
            self.combined_mask = None
            self.combined_stats_label.setText("No visible layers")
            self.update_plot()
            self.update_status_info()
            return
        
        # Combine layers using selected method
        if self.combine_method == "OR":
            self.combined_mask = np.logical_or.reduce(visible_layers)
        else:  # AND
            self.combined_mask = np.logical_and.reduce(visible_layers)
        
        # Update statistics
        masked_pixels = np.sum(self.combined_mask)
        total_pixels = self.combined_mask.size
        mask_percentage = (masked_pixels / total_pixels) * 100
        
        self.combined_stats_label.setText(
            f"Combined Mask:\n"
            f"{len(visible_layers)} layers ({self.combine_method})\n"
            f"Masked: {masked_pixels:,} pixels\n"
            f"({mask_percentage:.1f}%)"
        )
        
        self.update_plot()
        self.update_status_info()
        
    # ===== Mask Generation Methods =====
    
    def _generate_threshold_mask(self):
        """Generate a mask based on intensity threshold"""
        # Validate and prepare image
        image_2d, is_valid, error_msg = validate_and_prepare_image_array(self.image_data)
        
        if not is_valid:
            self.parent_app.show_status(error_msg or "Load an image first. Use 'Sync to Other Tabs' in Image Browser.")
            return
        
        try:
            threshold = self.threshold_spin.value()
            mode = self.threshold_mode_combo.currentText()
            
            # Generate mask based on mode
            if mode == "Above":
                mask = image_2d > threshold
            elif mode == "Below":
                mask = image_2d < threshold
            else:  # Range - would need two thresholds, simplified here
                mask = np.abs(image_2d - threshold) < (threshold * 0.1)
            
            # Create new layer
            layer = MaskLayer(mask, f"Threshold ({mode} {threshold:.1f})")
            layer.source = "generated"
            self.mask_layers.append(layer)
            
            self._update_layer_list()
            self.parent_app.show_status(f"Generated threshold mask: {mode} {threshold:.1f}")
            
        except Exception as e:
            self.parent_app.show_status(f"Error generating threshold mask: {str(e)}")
    
    def _generate_filter_mask(self):
        """Generate a mask based on image filtering"""
        # Validate and prepare image
        image_2d, is_valid, error_msg = validate_and_prepare_image_array(self.image_data)
        
        if not is_valid:
            self.parent_app.show_status(error_msg or "Load an image first. Use 'Sync to Other Tabs' in Image Browser.")
            return
        
        try:
            from scipy import ndimage
            
            filter_type = self.filter_type_combo.currentText()
            filter_size = self.filter_size_spin.value()
            
            # Apply filter
            if filter_type == "Median":
                filtered = ndimage.median_filter(image_2d, size=filter_size)
                mask = np.abs(image_2d - filtered) > (np.std(image_2d) * 0.5)
            elif filter_type == "Gaussian":
                filtered = ndimage.gaussian_filter(image_2d, sigma=filter_size)
                mask = np.abs(image_2d - filtered) > (np.std(image_2d) * 0.5)
            else:  # Edge Detection
                edges = ndimage.sobel(image_2d)
                threshold = np.percentile(edges, 90)
                mask = edges > threshold
            
            # Create new layer
            layer = MaskLayer(mask, f"Filter ({filter_type})")
            layer.source = "generated"
            self.mask_layers.append(layer)
            
            self._update_layer_list()
            self.parent_app.show_status(f"Generated filter mask: {filter_type}")
            
        except ImportError:
            self.parent_app.show_status("scipy is required for filtering. Install with: pip install scipy")
        except Exception as e:
            self.parent_app.show_status(f"Error generating filter mask: {str(e)}")
    
    def _toggle_drawing_mode(self, state):
        """Toggle manual drawing mode"""
        self.drawing_mode = (state == Qt.Checked)
        self.is_dragging = False  # Reset dragging state
        self.last_draw_point = None  # Reset line interpolation
        
        if self.drawing_mode:
            # Create a new empty layer if none exist or if current is not editable
            if not self.mask_layers:
                self._add_empty_layer()
            # Change cursor to indicate drawing mode ready
            self.canvas_image.setCursor(QCursor(Qt.CrossCursor))
            # Disable matplotlib toolbar zoom/pan to avoid conflicts
            self._disable_matplotlib_tools()
            self.parent_app.show_status("Drawing mode enabled. Click and drag to draw mask. (Pan/Zoom disabled)")
        else:
            # Reset cursor to normal
            self.canvas_image.setCursor(QCursor(Qt.ArrowCursor))
            # Re-enable matplotlib toolbar zoom/pan
            self._enable_matplotlib_tools()
            self.parent_app.show_status("Drawing mode disabled")
    
    def _disable_matplotlib_tools(self):
        """Disable matplotlib zoom/pan tools during drawing by setting mode to None"""
        toolbar = self.canvas_image.toolbar if hasattr(self.canvas_image, 'toolbar') else None
        if toolbar:
            # Set mode to None to disable all tools (zoom, pan, etc)
            toolbar.mode = ''
            # Also disable the buttons in toolbar
            for action in toolbar.actions():
                action_text = action.text().lower() if hasattr(action, 'text') else ''
                if any(x in action_text for x in ['zoom', 'pan']):
                    action.setEnabled(False)
    
    def _enable_matplotlib_tools(self):
        """Re-enable matplotlib zoom/pan tools to default state"""
        toolbar = self.canvas_image.toolbar if hasattr(self.canvas_image, 'toolbar') else None
        if toolbar:
            # Re-enable the buttons in toolbar
            for action in toolbar.actions():
                action_text = action.text().lower() if hasattr(action, 'text') else ''
                if any(x in action_text for x in ['zoom', 'pan']):
                    action.setEnabled(True)
    
    # ===== External Editor Methods =====
    
    def _load_instrument_mask(self, detector_key=None):
        """Load the instrument default mask for a specific detector
        
        Args:
            detector_key: Key from DETECTOR_CONFIGS (e.g., 'saxs', 'waxs', 'maxs')
                         If None, defaults to 'waxs' (for backward compatibility)
        """
        try:
            # Use provided detector_key or default to waxs
            if detector_key is None:
                detector_key = 'waxs'
            
            if detector_key not in DETECTOR_CONFIGS:
                self.parent_app.show_status(f"Unknown detector: {detector_key}")
                return
            
            detector_config = DETECTOR_CONFIGS[detector_key]
            detector_name = detector_config.get('name', detector_key)
            mask_file = detector_config.get('mask_file', '')
            
            if mask_file:
                mask_path = os.path.join(MASK_BASE_DIR, mask_file)
                
                if os.path.exists(mask_path):
                    mask_data = self._load_mask_file(mask_path)
                    
                    if mask_data is not None:
                        layer = MaskLayer(mask_data, f"Instrument: {detector_name}")
                        layer.source = "default"
                        self.mask_layers.append(layer)
                        
                        self._update_layer_list()
                        self.parent_app.show_status(f"Loaded instrument mask: {mask_file}")
                        return
                else:
                    self.parent_app.show_status(f"Mask file not found: {mask_path}")
            else:
                self.parent_app.show_status(f"No mask file configured for {detector_name}")
                
        except Exception as e:
            self.parent_app.show_status(f"Error loading instrument mask: {str(e)}")
    
    def _load_custom_mask(self):
        """Load a custom mask file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Mask File", "", 
            "Mask Files (*.npy *.tif *.tiff *.png *.xcf);;All Files (*)"
        )
        
        if file_path:
            mask_data = self._load_mask_file(file_path)
            
            if mask_data is not None:
                layer = MaskLayer(mask_data, os.path.basename(file_path))
                layer.source = "custom"
                self.mask_layers.append(layer)
                
                self._update_layer_list()
                self.parent_app.show_status(f"Loaded custom mask: {os.path.basename(file_path)}")
    
    def _load_mask_file(self, file_path: str) -> Optional[np.ndarray]:
        """Load mask data from various file formats"""
        try:
            if file_path.endswith('.npy'):
                data = np.load(file_path)
            elif file_path.endswith('.xcf'):
                # GIMP XCF format - try to extract first layer
                try:
                    from PIL import Image
                    img = Image.open(file_path)
                    data = np.array(img)
                except:
                    self.parent_app.show_status("Cannot read XCF directly. Export from GIMP as PNG/TIFF first.")
                    return None
            else:
                # Try to load as image
                from PIL import Image
                img = Image.open(file_path)
                data = np.array(img)
            
            # Convert to boolean mask
            # Convention: 0 or False = masked, non-zero or True = unmasked
            if data.dtype == bool:
                return data
            elif data.ndim > 2:
                # Handle RGB/RGBA - use first channel or convert to grayscale
                data = data[:, :, 0]
            
            # Convert to boolean (0 = masked)
            return data == 0
            
        except Exception as e:
            self.parent_app.show_status(f"Error loading mask file: {str(e)}")
            return None
    
    def _open_in_gimp(self):
        """Open current image and mask in GIMP using current display settings"""
        # Validate and prepare image
        image_2d, is_valid, error_msg = validate_and_prepare_image_array(self.image_data)
        
        if not is_valid:
            self.parent_app.show_status(error_msg or "Load an image first. Use 'Sync to Other Tabs' in Image Browser.")
            return
        
        try:
            import tempfile
            from PIL import Image
            import matplotlib.pyplot as plt
            import matplotlib.cm as cm
            
            # Get current display settings (vmin, vmax, colormap)
            display_vals = self.get_display_values()
            vmin = display_vals['vmin'] if display_vals['vmin'] is not None else image_2d.min()
            vmax = display_vals['vmax'] if display_vals['vmax'] is not None else image_2d.max()
            cmap_name = display_vals['cmap']
            
            # Normalize image using current display settings
            if vmax > vmin:
                img_normalized = ((image_2d - vmin) / (vmax - vmin) * 255).astype(np.uint8)
                # Clamp values outside vmin/vmax range
                img_normalized = np.clip(img_normalized, 0, 255)
            else:
                img_normalized = np.zeros_like(image_2d, dtype=np.uint8)
            
            # Apply colormap to get RGB image (unless it's a grayscale colormap)
            cmap = cm.get_cmap(cmap_name)
            img_colored = (cmap(img_normalized / 255.0)[:, :, :3] * 255).astype(np.uint8)
            
            # Create temp file for image
            temp_img = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            Image.fromarray(img_colored).save(temp_img.name)
            self.temp_files.append(temp_img.name)
            
            # Create temp file for mask if exists
            temp_mask_path = None
            if self.combined_mask is not None:
                temp_mask = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                # Convert boolean mask: True=black (0), False=white (255)
                # This way masked regions are black and unmasked regions are white
                mask_img = np.where(self.combined_mask, 0, 255).astype(np.uint8)
                Image.fromarray(mask_img).save(temp_mask.name)
                temp_mask_path = temp_mask.name
                self.temp_files.append(temp_mask_path)
            
            # Launch GIMP
            gimp_cmd = ['gimp', temp_img.name]
            if temp_mask_path:
                gimp_cmd.append(temp_mask_path)
            
            subprocess.Popen(gimp_cmd)
            
            msg = f"Opened in GIMP:\n{temp_img.name}"
            if temp_mask_path:
                msg += f"\n{temp_mask_path}\n(Black=Masked, White=Unmasked)"
            msg += "\n\nUse 'Import from External Edit' to reload the edited mask."
            
            QMessageBox.information(self, "GIMP Launched", msg)
            self.parent_app.show_status("Image and mask exported to GIMP")
            
        except FileNotFoundError:
            self.parent_app.show_status("GIMP not found. Install GIMP or check your PATH.")
        except Exception as e:
            self.parent_app.show_status(f"Error launching GIMP: {str(e)}")
    
    def _import_external_mask(self):
        """Import mask edited in external application"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import External Mask", "", 
            "Image Files (*.png *.tif *.tiff);;All Files (*)"
        )
        
        if file_path:
            mask_data = self._load_mask_file(file_path)
            
            if mask_data is not None:
                layer = MaskLayer(mask_data, f"External: {os.path.basename(file_path)}")
                layer.source = "external"
                self.mask_layers.append(layer)
                
                self._update_layer_list()
                self.parent_app.show_status(f"Imported external mask: {os.path.basename(file_path)}")
    
    # ===== Export Methods =====
    
    def _export_combined_mask(self):
        """Export the combined mask"""
        if self.combined_mask is None:
            self.parent_app.show_status("No mask to export")
            return
        
        self._export_mask_data(self.combined_mask, "combined_mask")
    
    def _export_selected_layer(self):
        """Export the currently selected layer"""
        current_row = self.layer_list.currentRow()
        if current_row < 0:
            self.parent_app.show_status("No layer selected")
            return
        
        layer = self.mask_layers[current_row]
        self._export_mask_data(layer.data, layer.name.replace(" ", "_"))
    
    def _export_mask_data(self, mask_data: np.ndarray, default_name: str):
        """Export mask data to file
        
        Handles conversion of boolean mask to appropriate image format based on file extension.
        - .npy: Saves as numpy array (preserves boolean type)
        - .png/.tif: Converts to 8-bit image (True=255/white, False=0/black)
        """
        file_path, filter_text = QFileDialog.getSaveFileName(
            self, "Export Mask", default_name, 
            "PNG Files (*.png);;NumPy Files (*.npy);;TIFF Files (*.tif);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            # Ensure filename has proper extension based on filter selected
            if not any(file_path.lower().endswith(ext) for ext in ['.npy', '.png', '.tif', '.tiff']):
                # Add extension based on filter if not present
                if 'NumPy' in filter_text:
                    file_path += '.npy'
                elif 'PNG' in filter_text:
                    file_path += '.png'
                elif 'TIFF' in filter_text:
                    file_path += '.tif'
            
            # Export based on file extension
            if file_path.lower().endswith('.npy'):
                np.save(file_path, mask_data)
                self.parent_app.show_status(f"✓ Mask exported (numpy): {os.path.basename(file_path)}")
                
            else:
                # Export as image (True=0/black=masked, False=255/white=unmasked)
                # Convert bool to uint8: True → 0, False → 255
                from PIL import Image
                img_array = (np.invert(mask_data).astype(np.uint8) * 255)
                img = Image.fromarray(img_array, mode='L')  # 'L' = grayscale 8-bit
                img.save(file_path, quality=95)
                
                self.parent_app.show_status(f"✓ Mask exported (image): {os.path.basename(file_path)}")
            
        except Exception as e:
            import traceback
            self.parent_app.show_status(f"✗ Error exporting mask: {str(e)}")
            print(f"Export error details:\n{traceback.format_exc()}")
    
    # ===== Display Methods =====
    
    def _add_mask_overlay(self, ax):
        """Hook to add mask overlay after base image display"""
        # Only add overlay if mask should be shown
        if not self.show_mask_check.isChecked():
            return
        
        # Overlay combined mask if available
        if self.combined_mask is None:
            return
        
        # Validate combined_mask shape
        if not isinstance(self.combined_mask, np.ndarray) or self.combined_mask.ndim != 2:
            return
        
        try:
            alpha = self.alpha_spin.value() / 100.0
            color = self.mask_color_combo.currentText()
            
            # Create RGBA overlay
            mask_overlay = np.zeros((*self.combined_mask.shape, 4))
            
            # Set color for masked pixels (True values)
            color_map = {
                'red': [1, 0, 0, alpha],
                'blue': [0, 0, 1, alpha],
                'green': [0, 1, 0, alpha],
                'yellow': [1, 1, 0, alpha],
                'magenta': [1, 0, 1, alpha],
                'cyan': [0, 1, 1, alpha]
            }
            
            if color in color_map:
                mask_overlay[self.combined_mask] = color_map[color]
            
            ax.imshow(mask_overlay, origin='upper', interpolation='nearest')
        except Exception as e:
            # Silently skip overlay if there's any issue
            print(f"DEBUG: _add_mask_overlay error: {e}")
            pass
    
    # ===== Mouse Event Handlers =====
    
    def on_mask_click(self, event):
        """Handle mouse clicks for mask editing - start drag"""
        if not event.inaxes or event.inaxes != self.ax_image:
            return
        
        if not self.drawing_mode:
            return
        
        # Start drawing on left click
        if event.button == 1:  # Left click
            self.is_dragging = True
            self.last_draw_point = None  # Reset line interpolation for new stroke
            # Set cursor to crosshair to indicate drawing mode
            self.canvas_image.setCursor(QCursor(Qt.CrossCursor))
            self._draw_on_mask(event)
    
    def on_mask_motion(self, event):
        """Handle mouse motion for real-time brush drawing during drag"""
        if not event.inaxes or event.inaxes != self.ax_image:
            # Set normal cursor when leaving image area
            if self.drawing_mode:
                self.canvas_image.setCursor(QCursor(Qt.CrossCursor))
            return
        
        # Update cursor feedback
        if self.drawing_mode:
            self.canvas_image.setCursor(QCursor(Qt.CrossCursor))
        
        # Draw continuously while dragging (left button is pressed)
        # In matplotlib, button==1 means left mouse button, button is set during motion if button is held
        if self.drawing_mode and (self.is_dragging or event.button == 1):
            self._draw_on_mask(event)
    
    def on_mask_release(self, event):
        """Handle mouse release - stop drag and auto-disable drawing mode"""
        if self.is_dragging:
            self.is_dragging = False
            # Reset cursor
            self.canvas_image.setCursor(QCursor(Qt.ArrowCursor))
            # Auto-disable drawing mode to prevent unintended clicks
            self.drawing_mode = False
            self.drawing_mode_check.setChecked(False)
    
    def _draw_on_mask(self, event):
        """Draw on the current mask layer with line interpolation for smooth traces"""
        if not self.mask_layers:
            self._add_empty_layer()
        
        try:
            x, y = int(event.xdata), int(event.ydata)
            current_layer = self.mask_layers[-1]
            mask_value = self.draw_add_radio.isChecked()  # True = mask, False = unmask
            
            # Interpolate between last point and current point for smooth lines
            points_to_draw = [(x, y)]
            if self.last_draw_point is not None:
                last_x, last_y = self.last_draw_point
                # Calculate distance between points
                dx = x - last_x
                dy = y - last_y
                distance = np.sqrt(dx**2 + dy**2)
                
                # If distance is large enough, interpolate intermediate points
                if distance > self.brush_size / 2:
                    num_steps = max(2, int(distance / max(1, self.brush_size / 3)))
                    interp_x = np.linspace(last_x, x, num_steps)
                    interp_y = np.linspace(last_y, y, num_steps)
                    points_to_draw = list(zip(interp_x, interp_y))
            
            # Draw at all interpolated points
            for px, py in points_to_draw:
                px, py = int(px), int(py)
                # Draw circle with brush size using ogrid for efficiency
                y_coords, x_coords = np.ogrid[:current_layer.data.shape[0], :current_layer.data.shape[1]]
                distance = np.sqrt((x_coords - px)**2 + (y_coords - py)**2)
                brush_mask = distance <= self.brush_size
                current_layer.data[brush_mask] = mask_value
            
            # Store current point for next interpolation
            self.last_draw_point = (x, y)
            
            # Update combined mask and display immediately for real-time feedback
            self._update_combined_mask()
            
        except (TypeError, ValueError):
            pass  # Mouse outside valid coordinates