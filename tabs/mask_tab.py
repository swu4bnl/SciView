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

from tools.mask_drawing_tools import BrushDrawingTool, LineDrawingTool, RectangleDrawingTool

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QCheckBox, QComboBox, QSpinBox, QListWidget, QListWidgetItem,
    QGroupBox, QSlider, QDoubleSpinBox, QFileDialog, QMessageBox,
    QScrollArea, QSplitter, QButtonGroup, QRadioButton, QFrame, QMenu
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
from config.app_style import (
    AppStyle, apply_body_style, apply_sync_button_style, 
    apply_secondary_button_style, apply_title_style, apply_info_style
)
from config.beamline_config import (
    DEFAULT_CALIBRATION, PHYSICAL_CONSTANTS, get_file_status,
    MASK_BASE_DIR, DETECTOR_CONFIGS
)
from config.app_style import *
from utils.image_utils import validate_and_prepare_image_array, ImageShapeConverter
from sciview.masking.io import export_mask_file as backend_export_mask_file
from sciview.masking.io import load_mask_file as backend_load_mask_file


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
        self._preview_mask: Optional[np.ndarray] = None  # For temporary preview display
        self.combine_method = "OR"  # OR or AND
        
        # Mask editing state
        self.drawing_mode = False
        self.draw_mask_value = True  # True = mask (add), False = unmask (remove)
        self.brush_size = 5
        self.toolbar_image = None  # Reference to toolbar for mode management
        
        # Drawing tool instance
        self.drawing_tool = BrushDrawingTool()
        self.drawing_tool.draw_value = self.draw_mask_value
        self.drawing_tool.brush_size = self.brush_size
        
        # Available drawing tools
        self.drawing_tools = {
            'Brush': BrushDrawingTool(),
            'Line': LineDrawingTool(),
            'Rectangle': RectangleDrawingTool()
        }
        
        # Developer control: auto-disable drawing mode after each stroke
        # Set to False to keep drawing mode enabled for continuous drawing
        self.auto_disable_drawing_mode = False
        
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
        
        # Set initial sizes for control panels from centralized style config
        mask_control_ratios = AppStyle.get_layout_ratios()['mask_controls_ratio']
        setup_splitter_layout(controls_splitter, mask_control_ratios)
        
        main_splitter.addWidget(controls_splitter)

        # Set initial sizes for main areas 
        setup_splitter_layout(main_splitter, AppStyle.get_layout_ratios()['main_splitter_ratio'])
        
        main_layout.addWidget(main_splitter)

        # Configure drawing tools and connect events
        for tool in self.drawing_tools.values():
            tool.configure(self.canvas_image, self.ax_image, self.parent_app, lambda: self.image_data)
        
        # Connect matplotlib events - delegate to tool event handlers
        self.canvas_image.mpl_connect('motion_notify_event', self._on_canvas_motion)
        self.canvas_image.mpl_connect('button_press_event', self._on_canvas_press)
        self.canvas_image.mpl_connect('button_release_event', self._on_canvas_release)

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
    
    def _create_separator(self):
        """Create a horizontal separator line"""
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        return separator
    
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
        
        ###### Drawing Tools (Photoshop-style, Compact) ######
        drawing_group = QGroupBox("Drawing Tools")
        drawing_layout = QVBoxLayout(drawing_group)
        drawing_layout.setSpacing(2)
        drawing_layout.setContentsMargins(6, 6, 6, 6)
        
        # Enable/Disable drawing mode
        self.drawing_mode_check = QCheckBox("Enable drawing mode")
        self.drawing_mode_check.stateChanged.connect(self._toggle_drawing_mode)
        drawing_layout.addWidget(self.drawing_mode_check)
        
        # Tool selection row
        tool_layout = QHBoxLayout()
        tool_layout.setSpacing(2)
        tool_layout.setContentsMargins(0, 4, 0, 4)
        tool_label = QLabel("Tool:")
        apply_body_style(tool_label)
        tool_layout.addWidget(tool_label)
        
        # Create button group for tool selection to ensure mutual exclusivity
        self.tool_group = QButtonGroup()
        self.tool_brush_radio = QRadioButton("Brush")
        self.tool_brush_radio.setChecked(True)
        self.tool_brush_radio.setToolTip("Freehand drawing")
        self.tool_brush_radio.toggled.connect(lambda checked: checked and self._set_drawing_tool('Brush'))
        self.tool_group.addButton(self.tool_brush_radio, 0)
        tool_layout.addWidget(self.tool_brush_radio)
        
        self.tool_line_radio = QRadioButton("Line")
        self.tool_line_radio.setToolTip("Straight line")
        self.tool_line_radio.toggled.connect(lambda checked: checked and self._set_drawing_tool('Line'))
        self.tool_group.addButton(self.tool_line_radio, 1)
        tool_layout.addWidget(self.tool_line_radio)
        
        self.tool_rect_radio = QRadioButton("Rect")
        self.tool_rect_radio.setToolTip("Filled rectangle")
        self.tool_rect_radio.toggled.connect(lambda checked: checked and self._set_drawing_tool('Rectangle'))
        self.tool_group.addButton(self.tool_rect_radio, 2)
        tool_layout.addWidget(self.tool_rect_radio)
        
        tool_layout.addStretch()
        drawing_layout.addLayout(tool_layout)
        
        # Mode selection row (Add/Remove)
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(2)
        mode_layout.setContentsMargins(0, 4, 0, 4)
        mode_label = QLabel("Mode:")
        apply_body_style(mode_label)
        mode_layout.addWidget(mode_label)
        
        # Create button group for mode selection
        self.mode_group = QButtonGroup()
        self.draw_add_radio = QRadioButton("Add")
        self.draw_add_radio.setChecked(True)
        self.draw_add_radio.setToolTip("Add to mask")
        self.draw_add_radio.toggled.connect(lambda checked: checked and self._update_tool_mode())
        self.mode_group.addButton(self.draw_add_radio, 0)
        mode_layout.addWidget(self.draw_add_radio)
        
        self.draw_remove_radio = QRadioButton("Remove")
        self.draw_remove_radio.setToolTip("Remove from mask")
        self.draw_remove_radio.toggled.connect(lambda checked: checked and self._update_tool_mode())
        self.mode_group.addButton(self.draw_remove_radio, 1)
        mode_layout.addWidget(self.draw_remove_radio)
        
        mode_layout.addStretch()
        drawing_layout.addLayout(mode_layout)
        
        # Brush size control (compact)
        brush_layout = QHBoxLayout()
        brush_layout.setSpacing(4)
        brush_layout.setContentsMargins(0, 4, 0, 4)
        brush_label = QLabel("Size:")
        apply_body_style(brush_label)
        brush_layout.addWidget(brush_label)
        
        self.brush_size_spin = QSpinBox()
        self.brush_size_spin.setRange(1, 50)
        self.brush_size_spin.setValue(5)
        self.brush_size_spin.setMinimumWidth(50)
        self.brush_size_spin.setMaximumWidth(70)
        self.brush_size_spin.setSuffix("px")
        self.brush_size_spin.valueChanged.connect(lambda v: self._update_tool_brush_size(v))
        self.brush_size_spin.setToolTip("Brush size for Brush and Line tools")
        brush_layout.addWidget(self.brush_size_spin)
        
        # Slider for brush size
        self.brush_size_slider = QSlider(Qt.Horizontal)
        self.brush_size_slider.setRange(1, 50)
        self.brush_size_slider.setValue(5)
        self.brush_size_slider.setMaximumWidth(120)
        self.brush_size_slider.setMaximumHeight(18)
        self.brush_size_slider.sliderMoved.connect(lambda v: self.brush_size_spin.setValue(v))
        self.brush_size_spin.valueChanged.connect(lambda v: self.brush_size_slider.blockSignals(True) or self.brush_size_slider.setValue(v) or self.brush_size_slider.blockSignals(False))
        brush_layout.addWidget(self.brush_size_slider)
        brush_layout.addStretch()
        drawing_layout.addLayout(brush_layout)
        
        layout.addWidget(drawing_group)
        
        # Disable drawing controls initially (drawing mode is off by default)
        self.tool_brush_radio.setEnabled(False)
        self.tool_line_radio.setEnabled(False)
        self.tool_rect_radio.setEnabled(False)
        self.draw_add_radio.setEnabled(False)
        self.draw_remove_radio.setEnabled(False)
        self.brush_size_spin.setEnabled(False)
        self.brush_size_slider.setEnabled(False)
        
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
        btn_reload = QPushButton("Import mask")
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
        btn_export_combined = QPushButton("Export Mask (All Layers)")
        btn_export_combined.clicked.connect(self._export_combined_mask)
        apply_sync_button_style(btn_export_combined)
        layout.addWidget(btn_export_combined)
        
        # Apply mask button (placeholder for future implementation)
        # btn_apply = QPushButton("Apply Mask to Tabs")
        # apply_secondary_button_style(btn_apply)
        # btn_apply.clicked.connect(self._apply_mask_to_tabs)
        # layout.addWidget(btn_apply)
        
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
            
            # Create submenu for each detector with available masks
            detector_masks = detector_config.get('available_masks', {})
            if detector_masks:
                detector_submenu = instrument_submenu.addMenu(detector_name)
                for mask_name, mask_path in detector_masks.items():
                    action = detector_submenu.addAction(mask_name)
                    # Use lambda with default argument to capture detector_key and mask_path
                    action.triggered.connect(
                        lambda checked=False, dk=detector_key, mp=mask_path: 
                        self._load_instrument_mask(dk, mp)
                    )
            else:
                # Fallback for old config format without available_masks
                action = instrument_submenu.addAction(detector_name)
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
        
        # Reset tool state when toggling mode
        if self.drawing_tool:
            self.drawing_tool.reset()
        
        # Disable/enable all drawing controls (except the checkbox itself)
        drawing_controls = [
            self.tool_brush_radio, self.tool_line_radio, self.tool_rect_radio,
            self.draw_add_radio, self.draw_remove_radio,
            self.brush_size_spin, self.brush_size_slider
        ]
        for control in drawing_controls:
            control.setEnabled(self.drawing_mode)
        
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
    
    def _set_drawing_tool(self, tool_name: str):
        """Switch to a different drawing tool"""
        if tool_name in self.drawing_tools:
            self.drawing_tool = self.drawing_tools[tool_name]
            # Sync settings with new tool
            # Only brush and line tools use brush_size; rectangle doesn't
            if tool_name in ['Brush', 'Line']:
                self.drawing_tool.brush_size = self.brush_size
                self.brush_size_spin.setEnabled(True)
                self.brush_size_slider.setEnabled(True)
            else:  # Rectangle
                self.brush_size_spin.setEnabled(False)
                self.brush_size_slider.setEnabled(False)
            
            self.drawing_tool.draw_value = self.draw_add_radio.isChecked()
            self.parent_app.show_status(f"Drawing tool changed to: {tool_name}")
    
    def _update_tool_brush_size(self, size: int):
        """Update brush size for Brush and Line tools only"""
        self.brush_size = size
        # Only update Brush and Line tools
        if 'Brush' in self.drawing_tools:
            self.drawing_tools['Brush'].brush_size = size
        if 'Line' in self.drawing_tools:
            self.drawing_tools['Line'].brush_size = size
        # Always sync current tool
        if self.drawing_tool.name in ['Brush', 'Line']:
            self.drawing_tool.brush_size = size
    
    def _update_tool_mode(self):
        """Update add/remove mode for all tools"""
        is_add = self.draw_add_radio.isChecked()
        for tool in self.drawing_tools.values():
            tool.draw_value = is_add
    
    
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
    
    def _load_instrument_mask(self, detector_key=None, mask_path=None):
        """Load the instrument default mask for a specific detector
        
        Args:
            detector_key: Key from DETECTOR_CONFIGS (e.g., 'saxs', 'waxs', 'maxs')
                         If None, defaults to 'waxs' (for backward compatibility)
            mask_path: Specific mask file path. If provided, uses this instead of default.
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
            
            # Use provided mask_path or fall back to default mask_file
            if mask_path is None:
                # Backward compatibility: use old mask_file format if available
                mask_file = detector_config.get('mask_file', '')
                if mask_file:
                    mask_path = os.path.join(MASK_BASE_DIR, mask_file)
                else:
                    # Try to load default_mask from available_masks
                    available_masks = detector_config.get('available_masks', {})
                    default_mask_name = detector_config.get('default_mask', '')
                    if default_mask_name and default_mask_name in available_masks:
                        mask_path = os.path.join(MASK_BASE_DIR, available_masks[default_mask_name])
                    else:
                        self.parent_app.show_status(f"No mask configured for {detector_name}")
                        return
            else:
                # Make path absolute if relative
                if not os.path.isabs(mask_path):
                    mask_path = os.path.join(MASK_BASE_DIR, mask_path)
            
            if mask_path and os.path.exists(mask_path):
                mask_data = self._load_mask_file(mask_path)
                
                if mask_data is not None:
                    # Extract mask name from path
                    mask_name = os.path.basename(mask_path)
                    layer = MaskLayer(mask_data, f"Instrument: {mask_name}")
                    layer.source = "default"
                    self.mask_layers.append(layer)
                    
                    self._update_layer_list()
                    self.parent_app.show_status(f"Loaded instrument mask: {mask_name}")
                    return
            else:
                self.parent_app.show_status(f"Mask file not found: {mask_path}")
                
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
            return backend_load_mask_file(file_path)
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
            
            written_path = backend_export_mask_file(mask_data, file_path)
            if str(written_path).lower().endswith('.npy'):
                self.parent_app.show_status(f"✓ Mask exported (numpy): {os.path.basename(str(written_path))}")
            else:
                self.parent_app.show_status(f"✓ Mask exported (image): {os.path.basename(str(written_path))}")
            
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
    
    def _get_valid_image_coordinates(self, event):
        """Get valid image pixel coordinates, clamped to image bounds.
        
        Handles zoom/pan states correctly by using image dimensions directly.
        Returns None if coordinates are invalid.
        """
        # Check if event has valid coordinates
        if event.xdata is None or event.ydata is None:
            return None
        
        # Check if image data is loaded
        if self.image_data is None or self.ax_image is None:
            return None
        
        # Get actual image array (handles Data2DScattering objects)
        image_2d, is_valid, error_msg = validate_and_prepare_image_array(self.image_data)
        if not is_valid:
            return None
        
        # Get image dimensions (height, width)
        img_height, img_width = image_2d.shape[:2]
        
        try:
            # Convert to integers and clamp to valid pixel range
            # Data coordinates from imshow already respect zoom/pan state
            x = int(event.xdata)
            y = int(event.ydata)
            
            # Clamp to image bounds
            x = max(0, min(img_width - 1, x))
            y = max(0, min(img_height - 1, y))
            
            return (x, y)
        except (TypeError, ValueError):
            return None
    
    def _on_canvas_press(self, event):
        """Handle canvas mouse press event - delegate to drawing tool"""
        if not self.drawing_mode or not self.drawing_tool:
            return
        
        # Tool handles press event (sets is_dragging, initializes state)
        self.drawing_tool.on_press(event)
        
        # Show initial preview if tool is active
        if self.drawing_tool.is_dragging and self.drawing_tool.is_active:
            self._show_preview(event)
    
    def _on_canvas_motion(self, event):
        """Handle canvas mouse motion - delegate to tool and update visualization"""
        if not self.drawing_mode or not self.drawing_tool:
            return
        
        # Tool handles motion event (state tracking, edge detection, cursor management)
        self.drawing_tool.on_motion(event)
        
        # Update visualization during drag
        if self.drawing_tool.is_dragging and self.drawing_tool.is_active:
            if isinstance(self.drawing_tool, BrushDrawingTool):
                # Brush accumulates strokes on layer during motion
                self._draw_brush_stroke(event)
            else:
                # Line/Rectangle show non-destructive preview
                self._show_preview(event)
    
    def _on_canvas_release(self, event):
        """Handle canvas mouse release - finalize drawing"""
        if not self.drawing_tool or not self.drawing_tool.is_dragging:
            return
        
        # Capture state before tool resets
        was_dragging = self.drawing_tool.is_dragging
        pointer_left = self.drawing_tool.pointer_left_canvas
        exit_edge = self.drawing_tool.pointer_exit_edge
        last_point = self.drawing_tool.last_draw_point
        
        # Tool handles release (resets state)
        self.drawing_tool.on_release(event)
        
        if was_dragging and self.drawing_tool.is_active:
            try:
                # Get image dimensions
                image_2d, is_valid, _ = validate_and_prepare_image_array(self.image_data)
                if not is_valid:
                    return
                
                img_height, img_width = image_2d.shape[:2]
                
                # Determine final endpoint
                if pointer_left and last_point is not None:
                    # Extend to edge/corner based on detected zone
                    x, y = self.drawing_tool.get_endpoint_for_edge(exit_edge, last_point[1], last_point[0], img_width, img_height)
                elif event.inaxes == self.ax_image and event.xdata is not None and event.ydata is not None:
                    # Normal release inside canvas
                    x = max(0, min(img_width - 1, int(event.xdata)))
                    y = max(0, min(img_height - 1, int(event.ydata)))
                else:
                    return
                
                # Finalize non-brush tools (Line, Rectangle draw on release)
                # Brush tools finalize immediately during motion
                if not isinstance(self.drawing_tool, BrushDrawingTool):
                    if not self.mask_layers:
                        self._add_empty_layer()
                    
                    current_layer = self.mask_layers[-1]
                    current_layer.data = self.drawing_tool.finalize(current_layer.data, (y, x))
                
                # Rebuild combined mask and update display
                self._update_combined_mask()
                
            except Exception as e:
                pass  # Finalization failed gracefully
            finally:
                self._preview_mask = None
                self.drawing_tool.reset()
        
        # Auto-disable drawing mode if configured
        if self.auto_disable_drawing_mode:
            self.drawing_mode = False
            self.drawing_mode_check.setChecked(False)
    
    def _draw_brush_stroke(self, event):
        """Draw continuously with brush tool during drag"""
        if not self.mask_layers:
            self._add_empty_layer()
        
        try:
            x, y = int(event.xdata), int(event.ydata)
            current_layer = self.mask_layers[-1]
            
            # Update tool settings
            self.drawing_tool.brush_size = self.brush_size
            self.drawing_tool.draw_value = self.draw_add_radio.isChecked()
            
            # Finalize on the actual layer to accumulate strokes
            current_layer.data = self.drawing_tool.finalize(current_layer.data, (y, x))
            
            # Update combined mask and display immediately for real-time feedback
            self._update_combined_mask()
            
        except (TypeError, ValueError):
            pass  # Mouse outside valid coordinates
    
    def _show_preview(self, event):
        """Show preview of what would be drawn without committing to the layer"""
        if not self.mask_layers:
            self._add_empty_layer()
        
        try:
            x, y = int(event.xdata), int(event.ydata)
            current_layer = self.mask_layers[-1]
            
            # Update tool settings
            self.drawing_tool.brush_size = self.brush_size
            self.drawing_tool.draw_value = self.draw_add_radio.isChecked()
            
            # Get preview from tool (doesn't modify original)
            preview_data = self.drawing_tool.preview(current_layer.data, (y, x))
            
            # Temporarily update combined mask to show preview
            # Rebuild with preview data
            temp_combined = np.zeros_like(current_layer.data)
            for layer in self.mask_layers[:-1]:  # All layers except current
                temp_combined = np.logical_or(temp_combined, layer.data).astype(np.uint8)
            temp_combined = np.logical_or(temp_combined, preview_data).astype(np.uint8)
            
            # Save original mask and temporarily set preview
            original_mask = self.combined_mask
            self.combined_mask = temp_combined.astype(bool)
            
            # Redraw with preview, then restore
            self.update_plot()
            
            # Restore after a brief moment or on next event
            # Store for restoration in next call or on release
            self._preview_mask = temp_combined.astype(bool)
            
        except (TypeError, ValueError):
            pass  # Mouse outside valid coordinates
    
    def _draw_on_mask(self, event):
        """Legacy method - kept for backward compatibility
        
        Main drawing now happens through:
        _on_canvas_press → _show_preview/draw → _on_canvas_release → finalize
        """
        pass
