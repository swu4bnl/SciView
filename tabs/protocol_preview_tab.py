"""
Protocol Preview Tab Module

This module provides an interface for previewing and configuring SciAnalysis 
protocols with support for multiple protocol stacks, dynamic parameter entry,
and export capabilities for batch processing workflows.
"""

import os
import sys
import numpy as np
from typing import Dict, List, Optional, Any
from PIL import Image

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox, QGridLayout, 
    QFileDialog, QListWidget, QListWidgetItem, QCheckBox, QGroupBox,
    QScrollArea, QSplitter, QTextEdit, QTabWidget, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)

# Import base class and configuration
from tabs.base_image_tab import BaseImageTab
from sciview.interfaces.theme.app_style import *
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION
from sciview.settings.app_settings import PHYSICAL_CONSTANTS, SCIANALYSIS_AVAILABLE, SCIANALYSIS_PATH
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array
from sciview.interfaces.stable_qt.utils.file_dialog_state import dialog_open_file, dialog_save_file

# Try to import SciAnalysis
if SCIANALYSIS_AVAILABLE:
    try:
        if SCIANALYSIS_PATH and SCIANALYSIS_PATH not in sys.path:
            sys.path.insert(0, SCIANALYSIS_PATH)
        from SciAnalysis.XSAnalysis.Data import Data2DScattering
        from SciAnalysis.XSAnalysis.Protocols import (
            thumbnails, circular_average, q_image
        )
    except ImportError as e:
        print(f"Warning: Could not import SciAnalysis protocols: {e}")
        SCIANALYSIS_AVAILABLE = False


class ProtocolInstance:
    """Represents a single protocol with its parameters"""
    
    def __init__(self, protocol_name: str, protocol_func: Any):
        self.name = protocol_name
        self.protocol_func = protocol_func
        self.parameters = {}
        self.run_args = {}
        self.enabled = True
        self.result = None
        
    def __str__(self):
        status = "✓" if self.enabled else "✗"
        return f"{status} {self.name}"


class ProtocolPreviewApp(BaseImageTab):
    """Protocol preview and configuration tab"""
    
    def __init__(self, parent_app):
        super().__init__(parent_app)
        
        # Protocol stack
        self.protocol_stack: List[ProtocolInstance] = []
        self.selected_protocol: Optional[ProtocolInstance] = None
        
        # Calibration and mask state
        self.calibration_loaded = False
        self.mask_loaded = False
        self.loaded_calibration_info = {}
        self.loaded_mask_info = {}
        
        # Output directory tracking for temporary results
        self.last_output_dir = None
        self.last_results = {}
        
        # Available protocols
        self.available_protocols = self._get_available_protocols()
        
        # Build UI
        self._build_ui()
        
    def _get_available_protocols(self) -> Dict[str, Any]:
        """Get available SciAnalysis protocols"""
        protocols = {}
        
        if SCIANALYSIS_AVAILABLE:
            protocols['thumbnails'] = thumbnails
            protocols['circular_average'] = circular_average
            protocols['q_image'] = q_image
        
        return protocols
    
    def _build_ui(self):
        """Build the main user interface"""
        from PyQt5.QtWidgets import QSplitter
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Main horizontal splitter: visualization | controls
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Visualization area
        self.viz_tabs = QTabWidget()
        
        # Enable tab closing and connect close signal
        self.viz_tabs.setTabsClosable(True)
        self.viz_tabs.tabCloseRequested.connect(self._on_tab_close_requested)

        # Tab 1: raw image display
        image_panel = self._create_image_panel()

        # Tab 2: processed image display (placeholder)
        # processed_panel = self._create_processed_panel()

        self.viz_tabs.addTab(image_panel, "Raw Image")
        # self.viz_tabs.addTab(processed_panel, "Processed Image")
        main_splitter.addWidget(self.viz_tabs)

        # Right side: Controls (tabbed)
        self.controls_tabs = QTabWidget()
        
        # Tab 1: Configuration (Calibration, Mask, Parameters)
        config_panel = self._create_configuration_panel()
        self.controls_tabs.addTab(config_panel, "Configuration")

        # Tab 2: Protocol Stack
        stack_panel = self._create_protocol_stack_panel()
        self.controls_tabs.addTab(stack_panel, "Protocols")
        
        # Tab 3: Info (Display loaded calibration, masks, exports)
        info_panel = self._create_info_panel()
        self.controls_tabs.addTab(info_panel, "Info")
        
        main_splitter.addWidget(self.controls_tabs)
        
        # Set initial sizes (3:1 ratio for viz:controls)
        setup_splitter_layout(main_splitter, AppStyle.get_layout_ratios()['main_splitter_ratio'])
        
        main_layout.addWidget(main_splitter)
    
    def _create_controls_panel(self) -> QWidget:
        """Create the right controls panel (deprecated - now using tabs)"""
        # This method is deprecated. Use individual panel creation methods instead.
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("This panel is deprecated"))
        return panel
    
    def _create_configuration_panel(self) -> QWidget:
        """Create the configuration panel (Calibration, Mask, Parameters)"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        # Create scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(2, 2, 2, 2)
        scroll_layout.setSpacing(4)

        # ===== CALIBRATION & MASK SECTION =====
        cal_title = QLabel("Calibration & Mask")
        apply_title_style(cal_title)
        scroll_layout.addWidget(cal_title)

        # Load calibration button
        btn_load_cal = QPushButton("Load Calibration File")
        btn_load_cal.clicked.connect(self._load_calibration_file)
        apply_sync_button_style(btn_load_cal)
        scroll_layout.addWidget(btn_load_cal)

        # Load mask button
        btn_load_mask = QPushButton("Load Mask File")
        btn_load_mask.clicked.connect(self._load_mask_file)
        apply_sync_button_style(btn_load_mask)
        scroll_layout.addWidget(btn_load_mask)

        scroll_layout.addSpacing(10)

        # ===== IMAGE DISPLAY SETTINGS SECTION =====
        display_title = QLabel("Image Display")
        apply_title_style(display_title)
        scroll_layout.addWidget(display_title)

        # Color map selection
        cmap_layout = QHBoxLayout()
        cmap_layout.addWidget(QLabel("Color Map:"))
        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(sorted(plt.colormaps()))
        self.cmap_combo.setCurrentText("viridis")
        cmap_layout.addWidget(self.cmap_combo)
        cmap_layout.addStretch()
        scroll_layout.addLayout(cmap_layout)

        # Color map limits
        clim_layout = QHBoxLayout()
        clim_layout.addWidget(QLabel("Color Limits:"))
        self.clim_min_edit = QDoubleSpinBox()
        self.clim_min_edit.setValue(0.01)
        self.clim_min_edit.setMaximumWidth(80)
        clim_layout.addWidget(QLabel("Min:"))
        clim_layout.addWidget(self.clim_min_edit)
        self.clim_max_edit = QDoubleSpinBox()
        self.clim_max_edit.setValue(0.99)
        self.clim_max_edit.setMaximumWidth(80)
        clim_layout.addWidget(QLabel("Max:"))
        clim_layout.addWidget(self.clim_max_edit)
        clim_layout.addStretch()
        scroll_layout.addLayout(clim_layout)

        scroll_layout.addSpacing(10)

        # ===== PLOT EXPORT SETTINGS SECTION =====
        export_title = QLabel("Export Settings")
        apply_title_style(export_title)
        scroll_layout.addWidget(export_title)

        # Figure size
        figsize_layout = QHBoxLayout()
        figsize_layout.addWidget(QLabel("Figure Size:"))
        figsize_layout.addWidget(QLabel("W:"))
        self.figwidth_spin = QDoubleSpinBox()
        self.figwidth_spin.setRange(2.0, 20.0)
        self.figwidth_spin.setValue(8.0)
        self.figwidth_spin.setSingleStep(0.5)
        self.figwidth_spin.setMaximumWidth(70)
        figsize_layout.addWidget(self.figwidth_spin)
        figsize_layout.addWidget(QLabel("H:"))
        self.figheight_spin = QDoubleSpinBox()
        self.figheight_spin.setRange(2.0, 20.0)
        self.figheight_spin.setValue(6.0)
        self.figheight_spin.setSingleStep(0.5)
        self.figheight_spin.setMaximumWidth(70)
        figsize_layout.addWidget(self.figheight_spin)
        figsize_layout.addWidget(QLabel("in"))
        figsize_layout.addStretch()
        scroll_layout.addLayout(figsize_layout)

        # DPI setting
        dpi_layout = QHBoxLayout()
        dpi_layout.addWidget(QLabel("DPI:"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(50, 600)
        self.dpi_spin.setValue(300)
        dpi_layout.addWidget(self.dpi_spin)
        dpi_layout.addStretch()
        scroll_layout.addLayout(dpi_layout)

        # Margin size
        margin_label = QLabel("Margins (L/R/T/B):")
        scroll_layout.addWidget(margin_label)

        margin_spin_layout = QHBoxLayout()
        self.margin_spin_left = QDoubleSpinBox()
        self.margin_spin_left.setRange(-0.2, 2.0)
        self.margin_spin_left.setValue(0.2)
        self.margin_spin_left.setSingleStep(0.05)
        self.margin_spin_left.setMaximumWidth(60)
        margin_spin_layout.addWidget(self.margin_spin_left)

        self.margin_spin_right = QDoubleSpinBox()
        self.margin_spin_right.setRange(-0.2, 2.0)
        self.margin_spin_right.setValue(0.05)
        self.margin_spin_right.setSingleStep(0.05)
        self.margin_spin_right.setMaximumWidth(60)
        margin_spin_layout.addWidget(self.margin_spin_right)

        self.margin_spin_top = QDoubleSpinBox()
        self.margin_spin_top.setRange(-0.2, 2.0)
        self.margin_spin_top.setValue(0.2)
        self.margin_spin_top.setSingleStep(0.05)
        self.margin_spin_top.setMaximumWidth(60)
        margin_spin_layout.addWidget(self.margin_spin_top)

        self.margin_spin_bottom = QDoubleSpinBox()
        self.margin_spin_bottom.setRange(-0.2, 2.0)
        self.margin_spin_bottom.setValue(0.05)
        self.margin_spin_bottom.setSingleStep(0.05)
        self.margin_spin_bottom.setMaximumWidth(60)
        margin_spin_layout.addWidget(self.margin_spin_bottom)

        margin_spin_layout.addStretch()
        scroll_layout.addLayout(margin_spin_layout)

        scroll_layout.addSpacing(10)

        # ===== FONT SETTINGS SECTION =====
        font_title = QLabel("Font Settings")
        apply_title_style(font_title)
        scroll_layout.addWidget(font_title)

        # Font family
        fontfamily_layout = QHBoxLayout()
        fontfamily_layout.addWidget(QLabel("Font:"))
        self.fontfamily_combo = QComboBox()
        self.fontfamily_combo.addItems(["Arial", "Times New Roman", "Courier New", "Helvetica", "Verdana"])
        fontfamily_layout.addWidget(self.fontfamily_combo)
        fontfamily_layout.addStretch()
        scroll_layout.addLayout(fontfamily_layout)

        # Font size
        fontsize_layout = QHBoxLayout()
        fontsize_layout.addWidget(QLabel("Size:"))
        self.fontsize_spin = QSpinBox()
        self.fontsize_spin.setRange(6, 24)
        self.fontsize_spin.setValue(10)
        fontsize_layout.addWidget(self.fontsize_spin)
        fontsize_layout.addWidget(QLabel("pt"))
        fontsize_layout.addStretch()
        scroll_layout.addLayout(fontsize_layout)

        scroll_layout.addSpacing(10)

        # ===== IMAGE RENDERING SECTION =====
        render_title = QLabel("Image Rendering")
        apply_title_style(render_title)
        scroll_layout.addWidget(render_title)

        # Shading options
        shading_layout = QHBoxLayout()
        shading_layout.addWidget(QLabel("Shading:"))
        self.shading_combo = QComboBox()
        self.shading_combo.addItems(["auto", "flat", "gouraud"])
        shading_layout.addWidget(self.shading_combo)
        shading_layout.addStretch()
        scroll_layout.addLayout(shading_layout)

        # Add stretch to fill remaining space
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        return panel
    
    def _create_info_panel(self) -> QWidget:
        """Create the info panel (calibration, masks, exports info)"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        
        
        # Image info text (used by BaseImageTab.update_plot for detailed image stats)
        self.image_info_text = QTextEdit()
        self.image_info_text.setReadOnly(True)
        apply_info_style(self.image_info_text)
        self.image_info_text.setMaximumHeight(80)
        layout.addWidget(self.image_info_text)
        
        # Title
        title = QLabel("Loaded Configuration")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Create info text area
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        apply_info_style(self.info_text)
        
        # Set initial text
        self._update_info_display()
        
        layout.addWidget(self.info_text)
        
        # Refresh button
        btn_refresh = QPushButton("Refresh Info")
        btn_refresh.clicked.connect(self._update_info_display)
        layout.addWidget(btn_refresh)
        
        return panel
    
    def _update_info_display(self):
        """Update the info display with current calibration and mask info"""
        text = "=== CONFIGURATION STATUS ===\n\n"
        
        # Image status
        text += "IMAGE:\n"
        if self.image_data is not None:
            shape = getattr(self.image_data, 'shape', 'Unknown')
            text += f"  ✓ Loaded\n  Shape: {shape}\n\n"
        else:
            text += "  ✗ Not loaded\n\n"
        
        # Calibration status
        text += "CALIBRATION:\n"
        if self.calibration_loaded and self.loaded_calibration_info:
            text += "  ✓ Loaded\n"
            for key, value in self.loaded_calibration_info.items():
                text += f"    {key}: {value}\n"
            text += "\n"
        else:
            text += "  ✗ Using defaults\n\n"
        
        # Mask status
        text += "MASK:\n"
        if self.mask_loaded and self.loaded_mask_info:
            text += "  ✓ Loaded\n"
            for key, value in self.loaded_mask_info.items():
                text += f"    {key}: {value}\n"
            text += "\n"
        else:
            text += "  ⊘ Optional (not loaded)\n\n"
        
        # Protocols status
        text += f"PROTOCOLS: {len(self.protocol_stack)}\n"
        for i, p in enumerate(self.protocol_stack, 1):
            status = "✓" if p.enabled else "✗"
            text += f"  {i}. {status} {p.name}\n"
        
        self.info_text.setPlainText(text)
    
    def _create_protocol_stack_panel(self) -> QWidget:
        """Create protocol stack management panel (like mask layers)"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        
        # Title
        title = QLabel("Protocol Stack")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Info
        info = QLabel("Add and configure protocols to run in sequence")
        info.setWordWrap(True)
        apply_info_style(info)
        layout.addWidget(info)
        
        # Protocol list
        self.protocol_list = QListWidget()
        self.protocol_list.setMaximumHeight(150)
        self.protocol_list.itemChanged.connect(self._on_protocol_item_changed)
        self.protocol_list.currentRowChanged.connect(self._on_protocol_selected)
        layout.addWidget(self.protocol_list)
        
        # Control buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)
        
        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self._show_add_protocol_menu)
        btn_layout.addWidget(btn_add)
        
        btn_remove = QPushButton("Remove")
        btn_remove.clicked.connect(self._remove_selected_protocol)
        btn_layout.addWidget(btn_remove)
        
        btn_layout.addSpacing(8)
        
        btn_up = QPushButton("↑")
        btn_up.setMaximumWidth(40)
        btn_up.clicked.connect(self._move_protocol_up)
        btn_layout.addWidget(btn_up)
        
        btn_down = QPushButton("↓")
        btn_down.setMaximumWidth(40)
        btn_down.clicked.connect(self._move_protocol_down)
        btn_layout.addWidget(btn_down)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)


        # Protocol Parameters Section
        param_title = QLabel("Protocol Parameters")
        apply_title_style(param_title)
        layout.addWidget(param_title)
        
        # Scrollable area for dynamic parameters
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(250)
        
        self.param_widget = QWidget()
        self.param_layout = QVBoxLayout(self.param_widget)
        self.param_layout.setContentsMargins(4, 4, 4, 4)
        self.param_layout.setSpacing(4)
        
        # Placeholder
        placeholder = QLabel("Select a protocol in 'Protocols' tab to configure parameters")
        placeholder.setWordWrap(True)
        apply_info_style(placeholder)
        self.param_layout.addWidget(placeholder)
        self.param_layout.addStretch()
        
        scroll.setWidget(self.param_widget)
        layout.addWidget(scroll)
        
        # Plot Settings Section
        settings_title = QLabel("Plot Settings")
        apply_title_style(settings_title)
        layout.addWidget(settings_title)
        
        # Line width
        lw_layout = QHBoxLayout()
        lw_layout.addWidget(QLabel("Line Width:"))
        self.linewidth_spin = QDoubleSpinBox()
        self.linewidth_spin.setRange(0.5, 5.0)
        self.linewidth_spin.setValue(1.5)
        self.linewidth_spin.setSingleStep(0.5)
        lw_layout.addWidget(self.linewidth_spin)
        lw_layout.addStretch()
        layout.addLayout(lw_layout)
        
        # X/Y log scale options
        self.xlog_check = QCheckBox("X Log Scale")
        self.ylog_check = QCheckBox("Y Log Scale")
        layout.addWidget(self.xlog_check)
        layout.addWidget(self.ylog_check)
        
        layout.addStretch()
        
        
        # Export section
        export_title = QLabel("Export")
        apply_title_style(export_title)
        layout.addWidget(export_title)
        
        # Export format
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Format:"))
        self.export_format_combo = QComboBox()
        self.export_format_combo.addItems(["Python Script", "JSON", "YAML"])
        format_layout.addWidget(self.export_format_combo)
        layout.addLayout(format_layout)
        
        # Export buttons
        btn_preview = QPushButton("Preview Export")
        btn_preview.clicked.connect(self._preview_export)
        layout.addWidget(btn_preview)
        
        btn_export = QPushButton("Export Workflow")
        btn_export.clicked.connect(self._export_workflow)
        apply_secondary_button_style(btn_export)
        layout.addWidget(btn_export)
        
        layout.addSpacing(8)
        
        # Run button (at bottom)
        btn_run = QPushButton("Run Preview")
        btn_run.clicked.connect(self._run_preview)
        apply_sync_button_style(btn_run)
        layout.addWidget(btn_run)
        
        return panel
    
    def _load_calibration_file(self):
        """Load calibration file and store in parent_app for shared access"""
        file_path, _ = dialog_open_file(
            self,
            "Load Calibration File",
            "YAML Files (*.yaml *.yml);;All Files (*)",
            key="calibration_open",
        )
        
        if file_path:
            try:
                # Load calibration from file
                import yaml
                with open(file_path, 'r') as f:
                    cal_data = yaml.safe_load(f)
                
                # Create SciAnalysis calibration object if available
                if SCIANALYSIS_AVAILABLE:
                    try:
                        from SciAnalysis.XSAnalysis.Data import Calibration
                        
                        calibration = Calibration(wavelength_A=cal_data.get('wavelength_A', DEFAULT_CALIBRATION['wavelength_A']))
                        
                        # Set properties from loaded file
                        if 'image_size' in cal_data:
                            size = cal_data['image_size']
                            if isinstance(size, (list, tuple)):
                                calibration.set_image_size(size[0], height=size[1])
                        
                        if 'pixel_size_um' in cal_data:
                            calibration.set_pixel_size(pixel_size_um=cal_data['pixel_size_um'])
                        
                        if 'beam_position' in cal_data:
                            pos = cal_data['beam_position']
                            if isinstance(pos, (list, tuple)):
                                calibration.set_beam_position(pos[0], pos[1])
                        
                        if 'distance_m' in cal_data:
                            calibration.set_distance(cal_data['distance_m'])
                        
                        # Store in parent_app for shared access across tabs
                        self.parent_app.calibration = calibration
                        
                    except Exception as e:
                        self.parent_app.show_status(f"Warning: Could not create SciAnalysis calibration: {e}")
                
                # Store calibration info for display
                self.loaded_calibration_info = {
                    'file': os.path.basename(file_path),
                    'wavelength': str(cal_data.get('wavelength_A', 'N/A')),
                    'image_size': str(cal_data.get('image_size', 'N/A')),
                    'pixel_size_um': str(cal_data.get('pixel_size_um', 'N/A')),
                    'beam_position': str(cal_data.get('beam_position', 'N/A')),
                    'distance_m': str(cal_data.get('distance_m', 'N/A')),
                }
                self.calibration_loaded = True
                self._update_info_display()
                self.parent_app.show_status(f"✓ Loaded calibration: {os.path.basename(file_path)} (shared with all tabs)")
                
            except Exception as e:
                self.parent_app.show_status(f"Error loading calibration: {e}")
                import traceback
                traceback.print_exc()
    
    def _load_mask_file(self):
        """Load mask file and store in parent_app for shared access"""
        file_path, _ = dialog_open_file(
            self,
            "Load Mask File",
            "Mask Files (*.png *.tif *.tiff *.xcf *.yaml);;All Files (*)",
            key="mask_open",
        )
        
        if file_path:
            try:
                # Create SciAnalysis mask object if available
                if SCIANALYSIS_AVAILABLE:
                    try:
                        from SciAnalysis.XSAnalysis.Data import Mask
                        mask = Mask(file_path)
                        
                        # Verify mask was loaded
                        if mask.data is None:
                            print(f"DEBUG: Mask.data is None after loading {file_path}")
                            print(f"DEBUG: Attempting to manually load...")
                            mask.load(file_path)  # Try explicit load
                        
                        if mask.data is not None:
                            print(f"DEBUG: Mask loaded successfully")
                            print(f"DEBUG:   shape: {mask.data.shape}, dtype: {mask.data.dtype}")
                            print(f"DEBUG:   True pixels: {np.sum(mask.data)}")
                        else:
                            print(f"DEBUG: Mask.data still None after explicit load")
                        
                        # Store in parent_app for shared access across tabs
                        self.parent_app.mask = mask
                        
                    except Exception as e:
                        print(f"DEBUG: Exception creating SciAnalysis mask: {e}")
                        import traceback
                        traceback.print_exc()
                        self.parent_app.show_status(f"Warning: Could not create SciAnalysis mask: {e}")
                
                # Store mask info for display
                self.loaded_mask_info = {
                    'file': os.path.basename(file_path),
                    'path': file_path,
                }
                self.mask_loaded = True
                self._update_info_display()
                self.parent_app.show_status(f"✓ Loaded mask: {os.path.basename(file_path)} (shared with all tabs)")
                
            except Exception as e:
                print(f"DEBUG: Exception in _load_mask_file: {e}")
                import traceback
                traceback.print_exc()
                self.parent_app.show_status(f"Error loading mask: {e}")
    
    

    # ===== Protocol Stack Management =====
    
    def _show_add_protocol_menu(self):
        """Show menu to add a protocol"""
        from PyQt5.QtWidgets import QMenu
        
        menu = QMenu(self)
        
        if not SCIANALYSIS_AVAILABLE:
            menu.addAction("SciAnalysis not available")
        else:
            for protocol_name, protocol_func in self.available_protocols.items():
                action = menu.addAction(protocol_name)
                action.triggered.connect(
                    lambda checked=False, name=protocol_name, func=protocol_func: 
                    self._add_protocol(name, func)
                )
        
        menu.exec_(self.sender().mapToGlobal(self.sender().rect().bottomLeft()))
    
    def _add_protocol(self, protocol_name: str, protocol_func: Any):
        """Add a protocol to the stack"""
        protocol = ProtocolInstance(protocol_name, protocol_func)
        self.protocol_stack.append(protocol)
        self._update_protocol_list()
        self.parent_app.show_status(f"Added protocol: {protocol_name}")
    
    def _remove_selected_protocol(self):
        """Remove selected protocol from stack"""
        current_row = self.protocol_list.currentRow()
        if current_row < 0:
            self.parent_app.show_status("No protocol selected")
            return
        
        removed = self.protocol_stack.pop(current_row)
        self._update_protocol_list()
        self.parent_app.show_status(f"Removed protocol: {removed.name}")
    
    def _move_protocol_up(self):
        """Move selected protocol up"""
        current_row = self.protocol_list.currentRow()
        if current_row <= 0:
            return
        
        self.protocol_stack[current_row], self.protocol_stack[current_row - 1] = \
            self.protocol_stack[current_row - 1], self.protocol_stack[current_row]
        self._update_protocol_list()
        self.protocol_list.setCurrentRow(current_row - 1)
    
    def _move_protocol_down(self):
        """Move selected protocol down"""
        current_row = self.protocol_list.currentRow()
        if current_row < 0 or current_row >= len(self.protocol_stack) - 1:
            return
        
        self.protocol_stack[current_row], self.protocol_stack[current_row + 1] = \
            self.protocol_stack[current_row + 1], self.protocol_stack[current_row]
        self._update_protocol_list()
        self.protocol_list.setCurrentRow(current_row + 1)
    
    def _update_protocol_list(self):
        """Update the protocol list display"""
        self.protocol_list.clear()
        
        for protocol in self.protocol_stack:
            item = QListWidgetItem(str(protocol))
            item.setCheckState(Qt.Checked if protocol.enabled else Qt.Unchecked)
            self.protocol_list.addItem(item)
    
    def _on_protocol_item_changed(self, item: QListWidgetItem):
        """Handle protocol item check state change"""
        row = self.protocol_list.row(item)
        if 0 <= row < len(self.protocol_stack):
            self.protocol_stack[row].enabled = (item.checkState() == Qt.Checked)
    
    def _on_protocol_selected(self, current_row: int):
        """Handle protocol selection"""
        if 0 <= current_row < len(self.protocol_stack):
            self.selected_protocol = self.protocol_stack[current_row]
            self._update_parameter_panel()
        else:
            self.selected_protocol = None
    
    def _update_parameter_panel(self):
        """Update parameter panel for selected protocol"""
        # Clear existing widgets
        while self.param_layout.count():
            child = self.param_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        if not self.selected_protocol:
            placeholder = QLabel("Select a protocol to configure parameters")
            placeholder.setWordWrap(True)
            apply_info_style(placeholder)
            self.param_layout.addWidget(placeholder)
            self.param_layout.addStretch()
            return
        
        # Add protocol-specific parameters
        protocol_name = self.selected_protocol.name
        
        # Dynamic parameter generation based on protocol
        if protocol_name == "circular_average":
            self._add_circular_average_params()
        elif protocol_name == "q_image":
            self._add_q_image_params()
        elif protocol_name == "thumbnails":
            self._add_thumbnails_params()
        
        self.param_layout.addStretch()
    
    def _add_circular_average_params(self):
        """Add parameters for circular_average protocol"""
        # Q range
        qmin_layout = QHBoxLayout()
        qmin_layout.addWidget(QLabel("Q min:"))
        qmin_spin = QDoubleSpinBox()
        qmin_spin.setRange(0.0, 10.0)
        qmin_spin.setValue(0.01)
        qmin_spin.setSingleStep(0.01)
        qmin_spin.setDecimals(3)
        qmin_layout.addWidget(qmin_spin)
        qmin_layout.addStretch()
        self.param_layout.addLayout(qmin_layout)
        
        qmax_layout = QHBoxLayout()
        qmax_layout.addWidget(QLabel("Q max:"))
        qmax_spin = QDoubleSpinBox()
        qmax_spin.setRange(0.0, 10.0)
        qmax_spin.setValue(5.0)
        qmax_spin.setSingleStep(0.1)
        qmax_spin.setDecimals(3)
        qmax_layout.addWidget(qmax_spin)
        qmax_layout.addStretch()
        self.param_layout.addLayout(qmax_layout)
        
        # Store references
        self.selected_protocol.parameters['qmin'] = qmin_spin
        self.selected_protocol.parameters['qmax'] = qmax_spin
    
    def _add_q_image_params(self):
        """Add parameters for q_image protocol"""
        info = QLabel("Q-space image transformation")
        apply_info_style(info)
        self.param_layout.addWidget(info)
    
    def _add_thumbnails_params(self):
        """Add parameters for thumbnails protocol"""
        # Resize factor
        resize_layout = QHBoxLayout()
        resize_layout.addWidget(QLabel("Resize Factor:"))
        resize_spin = QDoubleSpinBox()
        resize_spin.setRange(0.1, 1.0)
        resize_spin.setValue(0.5)
        resize_spin.setSingleStep(0.1)
        resize_layout.addWidget(resize_spin)
        resize_layout.addStretch()
        self.param_layout.addLayout(resize_layout)
        
        self.selected_protocol.parameters['resize'] = resize_spin
    
    # ===== Preview and Export =====
    
    def _run_preview(self):
        """Run protocol stack in preview mode with user-selected image file"""
        print("DEBUG: _run_preview called")
        
        if not SCIANALYSIS_AVAILABLE:
            print("DEBUG: SciAnalysis not available")
            self.parent_app.show_status("SciAnalysis not available")
            return
        
        if not self.protocol_stack:
            print("DEBUG: protocol_stack is empty")
            self.parent_app.show_status("No protocols in stack")
            return
        
        # Get image file path from parent_app (set by Image Browser)
        if not hasattr(self.parent_app, 'image_path') or not self.parent_app.image_path:
            print("DEBUG: No image_path in parent_app")
            self.parent_app.show_status("No image file selected. Load image from Image Browser tab.")
            return
        
        image_path = self.parent_app.image_path
        print(f"DEBUG: image_path = {image_path}")
        if not os.path.isfile(image_path):
            print(f"DEBUG: File not found: {image_path}")
            self.parent_app.show_status(f"Image file not found: {image_path}")
            return
        
        try:
            self.parent_app.show_status(f"Preparing image data...")
            print(f"DEBUG: parent_app.image_data type = {type(self.parent_app.image_data)}")
            
            # Validate and prepare image data using existing utility
            image_2d, is_valid, error_msg = validate_and_prepare_image_array(self.parent_app.image_data)
            if not is_valid:
                error_msg = error_msg or "Invalid image data"
                print(f"DEBUG: Image validation failed: {error_msg}")
                self.parent_app.show_status(f"Error: {error_msg}")
                return
            
            print(f"DEBUG: Image validation passed, shape={image_2d.shape}")
            self.parent_app.show_status(f"✓ Image validated: shape={image_2d.shape}")
            
            # Get calibration from parent_app or use defaults
            if hasattr(self.parent_app, 'calibration') and self.parent_app.calibration:
                calibration = self.parent_app.calibration
                print("DEBUG: Using parent_app calibration")
            else:
                # Use default calibration from config
                from SciAnalysis.XSAnalysis.Data import Calibration
                calibration = Calibration(wavelength_A=DEFAULT_CALIBRATION['wavelength_A'])
                # Use actual image dimensions instead of fixed detector size
                calibration.set_image_size(image_2d.shape[1], height=image_2d.shape[0])
                calibration.set_pixel_size(pixel_size_um=DEFAULT_CALIBRATION['pixel_size_um'])
                calibration.set_beam_position(
                    DEFAULT_CALIBRATION['beam_center_x'],
                    DEFAULT_CALIBRATION['beam_center_y']
                )
                calibration.set_distance(DEFAULT_CALIBRATION['detector_distance_m'] if 'detector_distance_m' in DEFAULT_CALIBRATION else DEFAULT_CALIBRATION['distance_m'])
                print("DEBUG: Using default calibration")
            
            # Get mask from parent_app
            mask = None
            if hasattr(self.parent_app, 'mask') and self.parent_app.mask:
                mask = self.parent_app.mask
                print("DEBUG: Using parent_app mask")
                if hasattr(mask, 'data') and mask.data is not None:
                    print(f"DEBUG:   mask.data shape: {mask.data.shape}, dtype: {mask.data.dtype}")
                    print(f"DEBUG:   True pixels: {np.sum(mask.data)}")
                else:
                    print("DEBUG:   WARNING: mask.data is None")
                self.parent_app.show_status("Using loaded mask")
            else:
                print("DEBUG: No mask loaded")
            
            # Create output directory for results
            output_dir = os.path.join(os.path.dirname(image_path), "preview_output")
            os.makedirs(output_dir, exist_ok=True)
            self.last_output_dir = output_dir  # Store for tracking
            print(f"DEBUG: output_dir = {output_dir}")
            
            self.parent_app.show_status(f"Creating Data2DScattering...")
            print(f"DEBUG: Creating Data2DScattering with validated image")
            
            # Create Data2DScattering object with validated image data
            data_2d = Data2DScattering(name=os.path.splitext(os.path.basename(image_path))[0])
            data_2d.data = image_2d
            data_2d.calibration = calibration
            
            if mask is not None:
                data_2d.mask = mask
                print(f"DEBUG: Mask set on data_2d")
                if hasattr(data_2d.mask, 'data'):
                    print(f"DEBUG:   data_2d.mask.data: {data_2d.mask.data is not None}")
            else:
                print(f"DEBUG: No mask to set on data_2d")
            
            print(f"DEBUG: Data2DScattering created with shape = {data_2d.data.shape}")
            self.parent_app.show_status(f"✓ Created Data2DScattering: shape={data_2d.data.shape}")
            
            # Run each protocol in the stack
            all_results = {}
            enabled_protocols = [p for p in self.protocol_stack if p.enabled]
            print(f"DEBUG: enabled_protocols count = {len(enabled_protocols)}")
            
            for i, protocol_instance in enumerate(enabled_protocols, 1):
                protocol_name = protocol_instance.name
                protocol_func = protocol_instance.protocol_func
                print(f"DEBUG: Running protocol {i}: {protocol_name}")
                
                try:
                    self.parent_app.show_status(f"Running protocol {i}/{len(enabled_protocols)}: {protocol_name}...")
                    
                    # Prepare run_args from protocol instance
                    run_args = {
                        'verbosity': 3,
                        'save_results': ['plots'],
                    }
                    
                    # Add protocol-specific parameters
                    if protocol_name == 'circular_average':
                        run_args.update({
                            'bins_relative': 1.0,
                            'markersize': 0,
                            'linewidth': self.linewidth_spin.value() if hasattr(self, 'linewidth_spin') else 1.5,
                        })
                    elif protocol_name == 'q_image':
                        run_args.update({
                            'blur': None,
                            'ztrim': [0.05, 0.005],
                            'method': 'nearest',
                        })
                    elif protocol_name == 'thumbnails':
                        run_args.update({
                            'crop': None,
                            'blur': 2.0,
                            'resize': 0.5 if 'resize' in protocol_instance.parameters else 0.2,
                            'ztrim': [0.05, 0.005],
                            'preserve_data': True,
                        })
                    
                    # Instantiate and run protocol
                    print(f"DEBUG: Instantiating protocol {protocol_name}")
                    protocol = protocol_func()
                    print(f"DEBUG: Running protocol {protocol_name} with run_args")
                    result = protocol.run(data_2d, output_dir, **run_args)
                    print(f"DEBUG: Protocol {protocol_name} returned result type={type(result)}")
                    
                    protocol_instance.result = result
                    all_results[protocol_name] = result
                    
                    self.parent_app.show_status(f"✓ Completed: {protocol_name}")
                    
                except Exception as protocol_error:
                    error_msg = f"Error in {protocol_name}: {str(protocol_error)}"
                    print(f"DEBUG: Protocol error: {error_msg}")
                    self.parent_app.show_status(error_msg)
                    import traceback
                    traceback.print_exc()
            
            print(f"DEBUG: All protocols complete. Results count = {len(all_results)}")
            self.last_results = all_results  # Store for tracking
            self.parent_app.show_status(f"✓ Protocol execution complete: {len(enabled_protocols)} protocols")
            
            # Display results in new visualization tab
            print(f"DEBUG: Calling _display_protocol_results with {len(all_results)} results")
            self._display_protocol_results(all_results)
            print("DEBUG: _display_protocol_results completed")
            
        except Exception as e:
            self.parent_app.show_status(f"Error running protocols: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def _display_protocol_results(self, results: Dict[str, Any]):
        """Display protocol execution results in a new closeable tab"""
        try:
            if not results:
                self.parent_app.show_status("No results to display")
                return
            
            print(f"DEBUG: _display_protocol_results called with {len(results)} results")
            
            # Get the first protocol result (most recent execution)
            first_protocol = list(results.keys())[0]
            result = results[first_protocol]
            
            print(f"DEBUG: Displaying results for protocol: {first_protocol}")
            print(f"DEBUG: Result type: {type(result)}, Result: {result}")
            
            # Extract file paths from results
            saved_files = []
            if isinstance(result, dict) and 'files_saved' in result:
                saved_files = result['files_saved']
                print(f"DEBUG: Found {len(saved_files)} saved files")
            
            # Create a new tab for results with its own matplotlib canvas
            results_widget = QWidget()
            results_layout = QVBoxLayout(results_widget)
            results_layout.setContentsMargins(0, 0, 0, 0)
            
            # Create matplotlib figure and canvas for this tab
            fig, ax = plt.subplots(figsize=(5.1, 6.8))
            fig.subplots_adjust(left=0.08, bottom=0.08, right=0.99, top=0.92)
            canvas = FigureCanvas(fig)
            
            # Add canvas to results widget
            results_layout.addWidget(canvas)
            
            # Display first image file in this new canvas
            image_displayed = False
            for file_info in saved_files:
                if isinstance(file_info, dict) and 'filename' in file_info:
                    filepath = file_info['filename']
                    file_type = file_info.get('type', 'plot')
                    description = file_info.get('description', 'Protocol output')
                    
                    print(f"DEBUG: Processing file: {filepath}, type: {file_type}, desc: {description}")
                    
                    # Try to display image files in canvas
                    if file_type == 'plot' and os.path.isfile(filepath):
                        try:
                            from PIL import Image
                            img = Image.open(filepath)
                            img_array = np.array(img)
                            
                            print(f"DEBUG: Loaded image from {filepath}, shape: {img_array.shape}")
                            
                            # Display in new tab's canvas
                            ax.clear()
                            ax.imshow(img_array, origin='upper')
                            ax.set_title(description, fontsize=10)
                            fig.subplots_adjust(left=0.05, bottom=0.05, right=0.99, top=0.99)
                            canvas.draw()
                            image_displayed = True
                            
                            print(f"DEBUG: Image displayed successfully in new tab")
                            
                            # Update info panel with result details
                            if hasattr(self, 'image_info_text'):
                                info_text = f"Protocol: {first_protocol}\n"
                                info_text += f"Description: {description}\n"
                                info_text += f"Output File: {os.path.basename(filepath)}\n"
                                info_text += f"Output Dir: {self.last_output_dir if hasattr(self, 'last_output_dir') else 'N/A'}\n"
                                info_text += f"Image Shape: {img_array.shape}\n"
                                self.image_info_text.setPlainText(info_text)
                            
                            break  # Display only first image
                        except Exception as e:
                            print(f"DEBUG: Error loading/displaying image: {e}")
                            import traceback
                            traceback.print_exc()
            
            if not image_displayed and saved_files:
                # If no image was displayed but files were saved, show text summary
                print(f"DEBUG: No image displayed, creating summary panel")
                summary_text = f"Protocol: {first_protocol}\n\nFiles saved:\n"
                for file_info in saved_files[:3]:
                    if isinstance(file_info, dict):
                        summary_text += f"  • {os.path.basename(file_info.get('filename', 'unknown'))}\n"
                    else:
                        summary_text += f"  • {str(file_info)[:50]}\n"
                
                summary_label = QLabel(summary_text)
                summary_label.setWordWrap(True)
                results_layout.addWidget(summary_label)
            
            # Add results tab to visualization tabs (if viz_tabs exists)
            if hasattr(self, 'viz_tabs'):
                # Remove old Results tab if exists
                for i in range(self.viz_tabs.count()):
                    if self.viz_tabs.tabText(i) == "Results":
                        print(f"DEBUG: Removing old Results tab at index {i}")
                        self.viz_tabs.removeTab(i)
                        break
                
                # Add new Results tab with close button enabled
                tab_index = self.viz_tabs.addTab(results_widget, f"Results: {first_protocol}")
                print(f"DEBUG: Added Results tab at index {tab_index}")
                
                # Enable close button for this tab
                self.viz_tabs.setTabsClosable(True)
                
                # Switch to Results tab
                self.viz_tabs.setCurrentIndex(tab_index)
                print(f"DEBUG: Switched to Results tab")
                
                self.parent_app.show_status(f"✓ Results displayed in new tab: {first_protocol}")
            else:
                print(f"DEBUG: WARNING - viz_tabs not found")
                self.parent_app.show_status(f"Could not find visualization tabs")
            
        except Exception as e:
            self.parent_app.show_status(f"Could not display results: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_tab_close_requested(self, index: int):
        """Handle tab close request (user clicked X button)"""
        tab_name = self.viz_tabs.tabText(index)
        print(f"DEBUG: Tab close requested for tab {index}: {tab_name}")
        
        # Only allow closing non-Raw Image tabs (keep Raw Image tab permanent)
        if tab_name != "Raw Image":
            self.viz_tabs.removeTab(index)
            self.parent_app.show_status(f"Closed {tab_name}")
        else:
            # Try to close another tab or show message
            print(f"DEBUG: Cannot close Raw Image tab")

    
    def _preview_export(self):
        """Preview the export file"""
        if not self.protocol_stack:
            self.parent_app.show_status("No protocols to export")
            return
        
        export_format = self.export_format_combo.currentText()
        content = self._generate_export_content(export_format)
        
        # Show in dialog
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Export Preview")
        dialog.setText(f"Preview of {export_format}:")
        dialog.setDetailedText(content)
        dialog.exec_()
    
    def _export_workflow(self):
        """Export protocol workflow to file"""
        if not self.protocol_stack:
            self.parent_app.show_status("No protocols to export")
            return
        
        export_format = self.export_format_combo.currentText()
        
        # Determine file extension
        if "Python" in export_format:
            ext = "py"
            filter_str = "Python Files (*.py)"
        elif "JSON" in export_format:
            ext = "json"
            filter_str = "JSON Files (*.json)"
        else:  # YAML
            ext = "yaml"
            filter_str = "YAML Files (*.yaml *.yml)"
        
        file_path, _ = dialog_save_file(
            self,
            "Export Workflow",
            f"workflow.{ext}",
            filter_str,
            key="workflow_export",
        )
        
        if file_path:
            content = self._generate_export_content(export_format)
            
            with open(file_path, 'w') as f:
                f.write(content)
            
            self.parent_app.show_status(f"Exported workflow to {file_path}")
    
    def _generate_export_content(self, export_format: str) -> str:
        """Generate export content based on format"""
        if "Python" in export_format:
            return self._generate_python_script()
        elif "JSON" in export_format:
            return self._generate_json()
        else:  # YAML
            return self._generate_yaml()
    
    def _generate_python_script(self) -> str:
        """Generate Python script"""
        lines = [
            "#!/usr/bin/env python",
            "# Generated by SciAnaGui Protocol Preview",
            "",
            "from SciAnalysis.XSAnalysis.Data import Data2D",
            "from SciAnalysis.XSAnalysis.Protocols import (",
        ]

        if SCIANALYSIS_PATH:
            lines[3:3] = [
                "import sys",
                f"sys.path.insert(0, '{SCIANALYSIS_PATH}')",
                "",
            ]
        
        # Add protocol imports
        protocol_names = [p.name for p in self.protocol_stack]
        for name in set(protocol_names):
            lines.append(f"    {name},")
        lines.append(")")
        lines.append("")
        
        # Add protocol execution
        lines.append("def run_protocols(data):")
        lines.append("    \"\"\"Run protocol stack\"\"\"")
        
        for protocol in self.protocol_stack:
            if protocol.enabled:
                lines.append(f"    # {protocol.name}")
                lines.append(f"    data = {protocol.name}(data)")
        
        lines.append("")
        lines.append("if __name__ == '__main__':")
        lines.append("    # Load your data here")
        lines.append("    # data = Data2D()")
        lines.append("    # run_protocols(data)")
        lines.append("    pass")
        
        return "\n".join(lines)
    
    def _generate_json(self) -> str:
        """Generate JSON config"""
        import json
        
        config = {
            "protocols": [
                {
                    "name": p.name,
                    "enabled": p.enabled,
                    "parameters": {},
                    "run_args": {}
                }
                for p in self.protocol_stack
            ]
        }
        
        return json.dumps(config, indent=2)
    
    def _generate_yaml(self) -> str:
        """Generate YAML config"""
        lines = [
            "# SciAnalysis Protocol Workflow",
            "# Generated by SciAnaGui Protocol Preview",
            "",
            "protocols:",
        ]
        
        for protocol in self.protocol_stack:
            lines.append(f"  - name: {protocol.name}")
            lines.append(f"    enabled: {str(protocol.enabled).lower()}")
            lines.append("    parameters: {}")
            lines.append("    run_args: {}")
        
        return "\n".join(lines)
    
    # def update_plot(self, image_data=None):
    #     """Update the visualization - use inherited BaseImageTab implementation
        
    #     Args:
    #         image_data: Optional image data to display. Uses self.image_data if None.
    #     """
    #     # Call parent class update_plot which handles all display logic
    #     super().update_plot(image_data)
