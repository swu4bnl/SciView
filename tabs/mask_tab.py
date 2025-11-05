"""
Mask Tab Module

This module contains the MaskApp class which provides mask checking
and editing functionality, demonstrating how to use BaseImageTab.
"""

import os
import sys
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QCheckBox, QComboBox, QSpinBox
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
from config.app_style import *


class MaskApp(BaseImageTab):
    """Mask checking and editing application widget"""
    
    def __init__(self, parent_app):
        super().__init__(parent_app)
        
        # Mask-specific attributes
        self.mask_data = None
        self.mask_applied = False
        self.custom_mask_points = []
        
        # Add mask overlay hook to post-display hooks
        self.add_display_hook(self._add_mask_overlay, 'post')
        
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
        
        # Left side: Visualization area
        visualization_panel = self._create_visualization_panel()
        main_splitter.addWidget(visualization_panel)

        # Right side: Controls area with vertical splitter for each panel
        controls_splitter = QSplitter(Qt.Vertical)
        
        # Image information panel (inherited from base class)
        image_info_panel = self._create_image_info_panel()
        controls_splitter.addWidget(image_info_panel)
        
        # Mask control panel
        mask_control_panel = self._create_mask_control_panel()
        controls_splitter.addWidget(mask_control_panel)
        
        # Mask editing panel
        mask_editing_panel = self._create_mask_editing_panel()
        controls_splitter.addWidget(mask_editing_panel)
        
        # Set initial sizes for control panels
        mask_control_ratios = [120, 150, 100]  # Custom ratios for mask tab
        setup_splitter_layout(controls_splitter, mask_control_ratios)
        
        main_splitter.addWidget(controls_splitter)

        # Set initial sizes for main areas (visualization larger than controls)
        setup_splitter_layout(main_splitter, AppStyle.get_layout_ratios()['main_splitter_ratio'])
        
        main_layout.addWidget(main_splitter)
        main_layout.addStretch()

        # Connect matplotlib events
        self.canvas_image.mpl_connect('motion_notify_event', self.on_mouse_move)
        self.canvas_image.mpl_connect('button_press_event', self.on_mask_click)

    def _create_visualization_panel(self):
        """Create the image and mask visualization panel using unified display system"""
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

        # Mask-specific controls
        mask_controls_layout = QHBoxLayout()
        mask_controls_layout.addWidget(QLabel("Transparency:"))
        self.alpha_spin = QSpinBox()
        self.alpha_spin.setRange(0, 100)
        self.alpha_spin.setValue(50)
        self.alpha_spin.setSuffix("%")
        self.alpha_spin.valueChanged.connect(self.update_plot)
        mask_controls_layout.addWidget(self.alpha_spin)
        
        mask_controls_layout.addWidget(QLabel("Mask Color:"))
        self.mask_color_combo = QComboBox()
        self.mask_color_combo.addItems(["red", "blue", "green", "yellow", "magenta", "cyan"])
        self.mask_color_combo.currentTextChanged.connect(self.update_plot)
        mask_controls_layout.addWidget(self.mask_color_combo)
        
        layout.addLayout(mask_controls_layout)
        
        return panel

    def _create_mask_control_panel(self):
        """Create the mask control panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        
        # Title
        title = QLabel("Mask Control")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Load mask button
        btn_load_mask = QPushButton("Load Mask File")
        btn_load_mask.clicked.connect(self.load_mask)
        layout.addWidget(btn_load_mask)
        
        # Apply mask checkbox
        self.apply_mask_check = QCheckBox("Apply Mask to Image")
        self.apply_mask_check.stateChanged.connect(self.toggle_mask)
        layout.addWidget(self.apply_mask_check)
        
        # Mask statistics
        self.mask_stats_label = QLabel("Mask: Not loaded")
        self.mask_stats_label.setWordWrap(True)
        apply_info_style(self.mask_stats_label)
        layout.addWidget(self.mask_stats_label)
        
        # Export mask button
        btn_export_mask = QPushButton("Export Current Mask")
        btn_export_mask.clicked.connect(self.export_mask)
        layout.addWidget(btn_export_mask)
        
        layout.addStretch()
        return panel

    def _create_mask_editing_panel(self):
        """Create the mask editing panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        
        # Title
        title = QLabel("Mask Editing")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Editing instructions
        instructions = QLabel("Click on image to add/remove mask points")
        instructions.setWordWrap(True)
        apply_info_style(instructions)
        layout.addWidget(instructions)
        
        # Clear custom mask
        btn_clear_custom = QPushButton("Clear Custom Mask")
        btn_clear_custom.clicked.connect(self.clear_custom_mask)
        layout.addWidget(btn_clear_custom)
        
        # Custom mask info
        self.custom_mask_label = QLabel("Custom points: 0")
        apply_info_style(self.custom_mask_label)
        layout.addWidget(self.custom_mask_label)
        
        layout.addStretch()
        return panel

    def _add_tab_specific_status(self, info_lines):
        """Add mask-specific status information"""
        info_lines.append("")  # Blank line separator
        
        # === MASK STATUS ===
        info_lines.append("=== MASK STATUS ===")
        if self.mask_data is not None:
            info_lines.append(f"Mask loaded: Yes")
            info_lines.append(f"Mask dimensions: {self.mask_data.shape}")
            masked_pixels = np.sum(self.mask_data == 0)
            total_pixels = self.mask_data.size
            mask_percentage = (masked_pixels / total_pixels) * 100
            info_lines.append(f"Masked pixels: {masked_pixels:,} ({mask_percentage:.1f}%)")
            info_lines.append(f"Mask applied: {'Yes' if self.mask_applied else 'No'}")
        else:
            info_lines.append("Mask loaded: No")
        
        # Custom mask points
        info_lines.append(f"Custom mask points: {len(self.custom_mask_points)}")

    def load_mask(self):
        """Load a mask file"""
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Mask File", "", 
            "Mask Files (*.npy *.tif *.tiff);;All Files (*)"
        )
        
        if file_path:
            try:
                if file_path.endswith('.npy'):
                    self.mask_data = np.load(file_path)
                else:
                    # Try to load as image
                    from PIL import Image
                    img = Image.open(file_path)
                    self.mask_data = np.array(img)
                
                # Update mask statistics
                masked_pixels = np.sum(self.mask_data == 0)
                total_pixels = self.mask_data.size
                mask_percentage = (masked_pixels / total_pixels) * 100
                self.mask_stats_label.setText(
                    f"Mask: {os.path.basename(file_path)}\n"
                    f"Size: {self.mask_data.shape}\n"
                    f"Masked: {masked_pixels:,} pixels ({mask_percentage:.1f}%)"
                )
                
                self.update_plot()
                self.update_status_info()
                self.parent_app.show_status(f"Mask loaded: {os.path.basename(file_path)}")
                
            except Exception as e:
                self.parent_app.show_status(f"Error loading mask: {str(e)}")

    def toggle_mask(self, state):
        """Toggle mask application"""
        self.mask_applied = state == Qt.Checked
        
    def _add_mask_overlay(self, ax):
        """Hook to add mask overlay after base image display"""
        # Overlay mask if available
        if self.mask_data is not None:
            alpha = self.alpha_spin.value() / 100.0
            color = self.mask_color_combo.currentText()
            mask_overlay = np.zeros((*self.mask_data.shape, 4))
            
            # Set color for masked pixels
            color_map = {
                'red': [1, 0, 0, alpha],
                'blue': [0, 0, 1, alpha],
                'green': [0, 1, 0, alpha],
                'yellow': [1, 1, 0, alpha],
                'magenta': [1, 0, 1, alpha],
                'cyan': [0, 1, 1, alpha]
            }
            
            if color in color_map:
                mask_overlay[self.mask_data == 0] = color_map[color]
            
            ax.imshow(mask_overlay, origin='upper')
        
        # Mark custom mask points
        if self.custom_mask_points:
            xs, ys = zip(*self.custom_mask_points)
            ax.scatter(xs, ys, c='white', s=20, marker='x', linewidth=2)

    def on_mask_click(self, event):
        """Handle clicks for mask editing"""
        if not event.inaxes or event.inaxes != self.ax_image:
            return
        
        # Right click to add/remove custom mask points
        if event.button == 3:  # Right click
            x, y = int(event.xdata), int(event.ydata)
            point = (x, y)
            
            if point in self.custom_mask_points:
                self.custom_mask_points.remove(point)
                self.parent_app.show_status(f"Removed custom mask point at ({x}, {y})")
            else:
                self.custom_mask_points.append(point)
                self.parent_app.show_status(f"Added custom mask point at ({x}, {y})")
            
            self.custom_mask_label.setText(f"Custom points: {len(self.custom_mask_points)}")
            self.update_plot()
            self.update_status_info()

    def clear_custom_mask(self):
        """Clear all custom mask points"""
        self.custom_mask_points = []
        self.custom_mask_label.setText("Custom points: 0")
        self.update_plot()
        self.update_status_info()
        self.parent_app.show_status("Custom mask points cleared")

    def export_mask(self):
        """Export the current mask"""
        if self.mask_data is None:
            self.parent_app.show_status("No mask to export")
            return
        
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Mask", "", 
            "NumPy Files (*.npy);;TIFF Files (*.tif);;All Files (*)"
        )
        
        if file_path:
            try:
                if file_path.endswith('.npy'):
                    np.save(file_path, self.mask_data)
                else:
                    # Export as image
                    from PIL import Image
                    img = Image.fromarray(self.mask_data.astype(np.uint8) * 255)
                    img.save(file_path)
                
                self.parent_app.show_status(f"Mask exported to {file_path}")
                
            except Exception as e:
                self.parent_app.show_status(f"Error exporting mask: {str(e)}")