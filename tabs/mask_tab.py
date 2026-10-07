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
import pyqtgraph as pg
from pathlib import Path
from typing import List, Tuple, Optional

try:
    from scipy.interpolate import interp1d
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

from sciview.interfaces.stable_qt.tools.mask_drawing_tools import (
    BrushDrawingTool,
    CircleDrawingTool,
    LineDrawingTool,
    MaskDrawingSession,
    PolygonDrawingTool,
    RectangleDrawingTool,
    WatershedFillTool,
)

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QCheckBox, QComboBox, QSpinBox, QListWidget, QListWidgetItem,
    QGroupBox, QSlider, QDoubleSpinBox, QGridLayout,
    QScrollArea, QSplitter, QButtonGroup, QFrame, QMenu, QToolButton,
    QSizePolicy, QProgressBar, QUndoCommand, QUndoStack, QApplication,
    QShortcut, QInputDialog, QColorDialog, QMessageBox
)
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QIcon, QCursor, QColor, QKeySequence

# Import base class and configuration
from tabs.base_image_tab import BaseImageTab
from sciview.interfaces.theme.app_style import (
    AppStyle,
    apply_body_style,
    apply_emphasis_button_style,
    apply_info_style,
    setup_splitter_layout,
)
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION, DETECTOR_CONFIGS, get_file_status as get_profile_file_status
from sciview.settings.app_settings import MASK_BASE_DIR, PHYSICAL_CONSTANTS
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array, ImageShapeConverter
from sciview.masking.io import export_mask_file as backend_export_mask_file
from sciview.masking.io import load_mask_file as backend_load_mask_file
from sciview.masking.layers import MaskLayer, compose_mask_layers
from sciview.masking.operations import dilate_mask, erode_mask
from sciview.session.session_cache import choose_path
from sciview.settings.viewer_config import MASK_DRAWING_DEFAULTS, MASK_TOOL_ICON_FILES, MASK_TOOL_NAMES, VIEWER_COLORS
from sciview.session import session_cache


class _MaskArrayCommand(QUndoCommand):
    """Undo one mutation while retaining only its changed bounding rectangle."""

    def __init__(self, layer: MaskLayer, before: np.ndarray, after: np.ndarray, text: str, refresh):
        super().__init__(text)
        changed = np.argwhere(np.asarray(before) != np.asarray(after))
        if changed.size:
            row_min, col_min = changed.min(axis=0)
            row_max, col_max = changed.max(axis=0) + 1
            self._slice = (slice(row_min, row_max), slice(col_min, col_max))
        else:
            self._slice = (slice(0, 0), slice(0, 0))
        self._layer = layer
        self._before = np.asarray(before[self._slice], dtype=bool).copy()
        self._after = np.asarray(after[self._slice], dtype=bool).copy()
        self._refresh = refresh
        self._already_applied = True

    def undo(self):
        self._layer.data[self._slice] = self._before
        self._refresh()

    def redo(self):
        if self._already_applied:
            self._already_applied = False
            return
        self._layer.data[self._slice] = self._after
        self._refresh()


class _LayerAddCommand(QUndoCommand):
    """Add or remove one layer through the shared undo stack."""

    def __init__(self, layers: list[MaskLayer], layer: MaskLayer, index: int, refresh):
        super().__init__(f"Add {layer.name}")
        self._layers = layers
        self._layer = layer
        self._index = index
        self._refresh = refresh

    def undo(self):
        if self._layer in self._layers:
            self._layers.remove(self._layer)
        self._refresh()

    def redo(self):
        if self._layer not in self._layers:
            self._layers.insert(min(self._index, len(self._layers)), self._layer)
        self._refresh()


class _LayerClearCommand(QUndoCommand):
    """Clear and restore a layer stack as one edit."""

    def __init__(self, layers: list[MaskLayer], refresh):
        super().__init__("Clear mask layers")
        self._layers = layers
        self._removed = list(layers)
        self._refresh = refresh

    def undo(self):
        present = {id(layer) for layer in self._layers}
        for index, layer in enumerate(self._removed):
            if id(layer) not in present:
                self._layers.insert(min(index, len(self._layers)), layer)
        self._refresh()

    def redo(self):
        removed = {id(layer) for layer in self._removed}
        self._layers[:] = [layer for layer in self._layers if id(layer) not in removed]
        self._refresh()


class MaskApp(BaseImageTab):
    """Comprehensive mask editing application with layered approach"""

    @staticmethod
    def _use_compact_spinbox_width(spinbox):
        """Keep numeric controls from taking the whole control column."""
        spinbox.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        spinbox.setMaximumWidth(spinbox.sizeHint().width())

    def _effective_draw_value(self) -> bool:
        """Return the active tool effect, temporarily inverted while Alt is held."""
        draw_value = self.drawing_tool.name != "Eraser"
        if self._alt_inversion_active:
            draw_value = not draw_value
        return draw_value

    def _record_drawing_edit(self, layer_index: int, before: np.ndarray, after: np.ndarray) -> None:
        """Record one completed canvas gesture as one undoable command."""
        if not (0 <= layer_index < len(self.mask_layers)):
            return
        command = _MaskArrayCommand(
            self.mask_layers[layer_index],
            before,
            after,
            f"{self.drawing_tool.name} edit",
            self._update_layer_list,
        )
        self.undo_stack.push(command)
    
    def __init__(self, parent_app):
        super().__init__(parent_app)
        
        # Layer-based mask system
        self.mask_layers: List[MaskLayer] = []
        self.combined_mask: Optional[np.ndarray] = None
        self._preview_mask: Optional[np.ndarray] = None  # For temporary preview display
        self.overlay_color = VIEWER_COLORS.default_mask
        self.overlay_opacity = 50
        self.undo_stack = QUndoStack(self)
        self._threshold_preview: Optional[np.ndarray] = None
        self._updating_threshold_controls = False
        self._threshold_image_token = None
        self._threshold_histogram_bounds: Optional[Tuple[float, float]] = None
        self._alt_inversion_active = False
        self._asset_icon_buttons = []
        
        # Mask editing state
        self.drawing_mode = False
        self.draw_mask_value = True  # True = mask (add), False = unmask (remove)
        self.brush_size = int(MASK_DRAWING_DEFAULTS["brush_size"])
        self.toolbar_image = None  # Reference to toolbar for mode management
        
        # Drawing tool instance
        self.drawing_tool = BrushDrawingTool()
        self.drawing_tool.draw_value = self.draw_mask_value
        self.drawing_tool.brush_size = self.brush_size
        
        # Available drawing tools
        tool_classes = {
            "Brush": BrushDrawingTool,
            "Eraser": BrushDrawingTool,
            "Line": LineDrawingTool,
            "Rectangle": RectangleDrawingTool,
            "Circle": CircleDrawingTool,
            "Polygon": PolygonDrawingTool,
            "Smart Fill": WatershedFillTool,
        }
        self.drawing_tools = {tool_name: tool_classes[tool_name]() for tool_name in MASK_TOOL_NAMES}
        self.drawing_tools["Eraser"].name = "Eraser"
        self.drawing_tools["Smart Fill"].name = "Smart Fill"
        self.drawing_session = MaskDrawingSession(
            is_enabled=lambda: self.drawing_mode,
            get_tool=lambda: self.drawing_tool,
            get_active_layer=self._get_active_layer,
            get_active_layer_index=self._get_active_layer_index,
            get_layers=lambda: self.mask_layers,
            set_combined_mask=self._set_combined_mask_preview,
            update_combined_mask=self._update_combined_mask,
            update_plot=self._refresh_mask_overlay,
            set_drawing_enabled=self._set_drawing_enabled_from_session,
            should_auto_disable=lambda: self.auto_disable_drawing_mode,
            get_brush_size=lambda: self.brush_size,
            get_draw_value=self._effective_draw_value,
            on_edit_finished=self._record_drawing_edit,
        )
        
        # Developer control: auto-disable drawing mode after each stroke
        # Set to False to keep drawing mode enabled for continuous drawing
        self.auto_disable_drawing_mode = False
        
        # Add mask overlay hook to post-display hooks
        self.add_display_hook(self._add_mask_overlay, 'post')
        
        # Build UI
        self._build_ui()
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        """Reflect Alt inversion without replacing standard viewer shortcuts."""
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Alt:
            if event.isAutoRepeat():
                return super().eventFilter(watched, event)
            if not self._alt_inversion_active:
                self._alt_inversion_active = True
                self._refresh_inversion_feedback()
        elif event.type() == QEvent.KeyRelease and self._alt_inversion_active:
            if event.key() == Qt.Key_Alt or not event.modifiers() & Qt.AltModifier:
                self._alt_inversion_active = False
                self._refresh_inversion_feedback()
        elif event.type() == QEvent.ApplicationDeactivate and self._alt_inversion_active:
            self._alt_inversion_active = False
            self._refresh_inversion_feedback()
        return super().eventFilter(watched, event)

    def _refresh_inversion_feedback(self) -> None:
        if not self.drawing_mode or not self.drawing_tool:
            return
        draw_value = self._effective_draw_value()
        self.drawing_tool.draw_value = draw_value
        button = self.tool_buttons.get(self.drawing_tool.name)
        if button is not None:
            colors = AppStyle.resolved_colors()
            effect_color = colors['success'] if draw_value else colors['error']
            effect_border = QColor(effect_color).darker(125).name()
            button.setStyleSheet(
                f"QToolButton {{ background: {effect_color}; color: {colors['checked_fg']}; border: 2px solid {effect_border}; }}"
                if self._alt_inversion_active
                else button.property("baseStyleSheet") or ""
            )
        effect = "mask pixels" if draw_value else "restore pixels"
        self.active_tool_label.setText(f"{self.drawing_tool.name}: {effect}. Hold Alt to invert the effect.")

    def _build_ui(self):
        """Build the main user interface"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(self._create_visualization_panel())
        main_splitter.addWidget(self.make_scrollable_panel(self._create_sidebar_panel()))
        setup_splitter_layout(main_splitter, AppStyle.get_layout_ratios()['main_splitter_ratio'])
        main_layout.addWidget(main_splitter)

        for tool in self.drawing_tools.values():
            tool.set_image_data_getter(lambda: self.image_data)
        self.image_viewer.mouse_moved.connect(self.drawing_session.handle_motion)
        self.image_viewer.mouse_pressed.connect(self.drawing_session.handle_press)
        self.image_viewer.mouse_released.connect(self.drawing_session.handle_release)
        self.image_viewer.mouse_moved.connect(self._refresh_polygon_feedback)
        self.image_viewer.mouse_pressed.connect(self._refresh_polygon_feedback)
        self.image_viewer.mouse_double_clicked.connect(lambda _event: self._finish_polygon())
        self.image_viewer.interaction_mode_changed.connect(self._on_viewer_mode_changed)
        self._install_shortcuts()

    def _create_visualization_panel(self):
        """Use the shared image panel without Mask-specific viewer chrome."""
        return self._create_image_panel()

    def _create_tools_panel(self) -> QWidget:
        """Create the ordered mask-editing controls for the sidebar."""
        panel = QGroupBox("Tools")
        layout = QVBoxLayout(panel)
        self.edit_target_label = QLabel("Editing: no active layer")
        apply_info_style(self.edit_target_label)
        layout.addWidget(self.edit_target_label)

        self.navigation_buttons = {}
        navigation_tools = []
        for mode, label, tooltip in (
            ("pan", "Pan", "Pan across the image"),
            ("zoom", "Zoom", "Drag a rectangle to zoom"),
        ):
            button = self._make_square_tool_button(
                tooltip=tooltip,
                icon=self.image_viewer.toolbar_icon(mode),
                checkable=True,
            )
            button.clicked.connect(
                lambda _checked=False, selected_mode=mode: self.image_viewer.activate_navigation_mode(selected_mode)
            )
            self.navigation_buttons[mode] = button
            navigation_tools.append((label, button))
        self.fit_view_button = self._make_square_tool_button(
            tooltip="Reset to the full image view",
            icon=self.image_viewer.toolbar_icon("home"),
        )
        self.fit_view_button.clicked.connect(self.image_viewer.reset_view)
        navigation_tools.append(("Home", self.fit_view_button))
        self.navigation_buttons["pan"].setChecked(True)

        self.tool_buttons = {}
        tool_specs = (
            ("Brush", "Brush", "Brush: mask pixels. Hold Alt to restore pixels."),
            ("Eraser", "Eraser", "Eraser: restore pixels. Hold Alt to mask pixels."),
            ("Line", "Line", "Draw a straight mask line. Hold Alt to erase."),
            ("Rectangle", "Rect", "Draw a filled rectangle. Hold Alt to erase."),
            ("Circle", "Circle", "Draw a filled circle. Hold Alt to erase."),
            ("Polygon", "Polygon", "Click vertices; Enter or double-click finishes."),
            ("Smart Fill", "Fill", "Fill from an image seed. Hold Alt to erase."),
        )
        drawing_tools = []
        for tool_name, label, tooltip in tool_specs:
            icon = self._load_tool_icon(tool_name)
            button = self._make_square_tool_button(
                tooltip=tooltip,
                icon=icon,
                checkable=True,
            )
            button.clicked.connect(lambda checked, name=tool_name: self._activate_drawing_tool(name, checked))
            button.setProperty("baseStyleSheet", button.styleSheet())
            self.tool_buttons[tool_name] = button
            drawing_tools.append((label, button))

        shrink_button = self._make_square_tool_button(
            tooltip="Shrink active layer by 1 px",
            icon=self._load_asset_icon("tool_shrink.svg"),
        )
        self._register_asset_icon(shrink_button, "tool_shrink.svg")
        shrink_button.clicked.connect(lambda: self._refine_active_layer("shrink"))
        grow_button = self._make_square_tool_button(
            tooltip="Grow active layer by 1 px",
            icon=self._load_asset_icon("tool_grow.svg"),
        )
        self._register_asset_icon(grow_button, "tool_grow.svg")
        grow_button.clicked.connect(lambda: self._refine_active_layer("grow"))
        self.refine_buttons = [shrink_button, grow_button]
        refine_tools = [("Shrink", shrink_button), ("Grow", grow_button)]

        self.undo_button = self._make_square_tool_button(
            tooltip="Undo last mask edit (Ctrl+Z)",
            icon=self._load_asset_icon("tool_undo.svg"),
        )
        self._register_asset_icon(self.undo_button, "tool_undo.svg")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_stack.undo)

        self.redo_button = self._make_square_tool_button(
            tooltip="Redo mask edit (Ctrl+Shift+Z)",
            icon=self._load_asset_icon("tool_redo.svg"),
        )
        self._register_asset_icon(self.redo_button, "tool_redo.svg")
        self.redo_button.setEnabled(False)
        self.redo_button.clicked.connect(self.undo_stack.redo)
        history_tools = [("Undo", self.undo_button), ("Redo", self.redo_button)]

        utility_widget = QWidget()
        utility_row = QHBoxLayout(utility_widget)
        utility_row.setContentsMargins(0, 0, 0, 0)
        utility_row.setSpacing(6)
        for index, (title, tools) in enumerate((
            ("View", navigation_tools),
            ("Refine", refine_tools),
            ("History", history_tools),
        )):
            if index:
                separator = QFrame()
                separator.setFrameShape(QFrame.VLine)
                separator.setFrameShadow(QFrame.Sunken)
                utility_row.addWidget(separator)
            utility_row.addWidget(
                self._create_tool_group_widget(title, tools, columns=len(tools)),
                len(tools),
            )
        utility_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(utility_widget)

        self._add_tool_group(layout, "Draw", drawing_tools, columns=len(drawing_tools))
        self.undo_stack.canUndoChanged.connect(self.undo_button.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.redo_button.setEnabled)
        layout.addWidget(self._create_tool_options_panel())
        return panel

    def _make_square_tool_button(
        self,
        *,
        tooltip: str,
        icon: QIcon | None = None,
        text: str = "",
        checkable: bool = False,
    ) -> QToolButton:
        button = QToolButton()
        button.setCheckable(checkable)
        button.setToolTip(tooltip)
        button.setText(text)
        if icon is not None and not icon.isNull():
            button.setIcon(icon)
            button.setIconSize(AppStyle.mask_tool_icon_size())
        size = AppStyle.toolbar_symbol_button_size()
        side = max(size.width(), size.height())
        button.setFixedSize(side, side)
        AppStyle.apply_widget_style(button, 'compact_button')
        return button

    def _add_tool_group(
        self,
        parent_layout: QVBoxLayout,
        title: str,
        tools: list[tuple[str, QToolButton]],
        *,
        columns: int,
    ) -> None:
        heading = QHBoxLayout()
        heading.addWidget(QLabel(title))
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        heading.addWidget(line, 1)
        parent_layout.addLayout(heading)
        parent_layout.addWidget(
            self._create_tool_group_widget("", tools, columns=columns)
        )

    def _create_tool_group_widget(
        self,
        title: str,
        tools: list[tuple[str, QToolButton]],
        *,
        columns: int,
    ) -> QWidget:
        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        column_count = min(columns, max(1, len(tools)))
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if title:
            title_label = QLabel(title)
            title_label.setAlignment(Qt.AlignHCenter)
            layout.addWidget(title_label)
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        for index, (label_text, button) in enumerate(tools):
            button.setAccessibleName(label_text)
            cell = QWidget()
            cell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(1)
            cell_layout.addWidget(button, 0, Qt.AlignHCenter)
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignHCenter)
            AppStyle.set_font_role(label, 'toolbar_text')
            cell_layout.addWidget(label)
            column = index % columns
            grid.addWidget(cell, index // columns, column)
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        return group

    def _create_tool_options_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 4, 8, 4)
        self.active_tool_label = QLabel("Pan and inspect the image")
        self.active_tool_label.setWordWrap(True)
        layout.addWidget(self.active_tool_label)
        size_row = QHBoxLayout()
        self.tool_size_label = QLabel("Size")
        self.brush_size_spin = QSpinBox()
        self.brush_size_spin.setRange(1, 50)
        self.brush_size_spin.setValue(self.brush_size)
        self.brush_size_spin.setSuffix(" px")
        self.brush_size_spin.valueChanged.connect(self._update_tool_brush_size)
        self._use_compact_spinbox_width(self.brush_size_spin)
        self.brush_size_slider = QSlider(Qt.Horizontal)
        self.brush_size_slider.setRange(1, 50)
        self.brush_size_slider.setValue(self.brush_size)
        self.brush_size_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.brush_size_slider.valueChanged.connect(self.brush_size_spin.setValue)
        self.brush_size_spin.valueChanged.connect(self.brush_size_slider.setValue)
        size_row.addWidget(self.tool_size_label)
        size_row.addWidget(self.brush_size_spin)
        size_row.addWidget(self.brush_size_slider)
        layout.addLayout(size_row)
        polygon_row = QHBoxLayout()
        self.finish_polygon_button = QPushButton("Finish Polygon")
        self.finish_polygon_button.clicked.connect(self._finish_polygon)
        self.cancel_tool_button = QPushButton("Cancel")
        self.cancel_tool_button.clicked.connect(self._cancel_current_edit)
        polygon_row.addWidget(self.finish_polygon_button)
        polygon_row.addWidget(self.cancel_tool_button)
        polygon_row.addStretch()
        layout.addLayout(polygon_row)
        panel.setVisible(False)
        self.tool_options_panel = panel
        return panel

    def _create_sidebar_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        margin = AppStyle.LAYOUT['panel_inner_margin']
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(AppStyle.LAYOUT['section_spacing'])
        layout.addWidget(self._create_threshold_panel())
        layout.addWidget(self._create_tools_panel())
        layout.addWidget(self._create_layer_panel(), 1)
        self._refresh_edit_target()
        return panel

    def _create_layer_panel(self):
        """Create layer selection, visibility, appearance, and composition controls."""
        panel = QGroupBox("Layers")
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)

        self.layer_list = QListWidget()
        self.layer_list.setMinimumHeight(120)
        self.layer_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.layer_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.layer_list.customContextMenuRequested.connect(self._show_layer_context_menu)
        self.layer_list.currentRowChanged.connect(self._on_layer_selected)
        layout.addWidget(self.layer_list, 1)

        button_row = QHBoxLayout()
        self.add_layer_button = QPushButton("Add")
        self.add_layer_button.setToolTip("Add an empty, imported, instrument, or threshold layer")
        self.add_layer_button.clicked.connect(self._add_layer_menu)
        apply_emphasis_button_style(self.add_layer_button)
        button_row.addWidget(self.add_layer_button, 1)

        self.remove_layer_button = QPushButton("Remove")
        self.remove_layer_button.setToolTip("Remove the selected layer")
        self.remove_layer_button.clicked.connect(self._remove_selected_layer)
        self.remove_layer_button.setEnabled(False)
        button_row.addWidget(self.remove_layer_button)

        self.clear_layers_button = QPushButton("Clear Layers")
        self.clear_layers_button.setToolTip("Remove all layers")
        self.clear_layers_button.clicked.connect(self._clear_all_layers)
        button_row.addWidget(self.clear_layers_button)
        layout.addLayout(button_row)

        self.layer_empty_hint = QLabel("Create a mask from the threshold above, or add an empty layer for manual drawing.")
        self.layer_empty_hint.setWordWrap(True)
        apply_info_style(self.layer_empty_hint)
        layout.addWidget(self.layer_empty_hint)

        self.layer_appearance_panel = QWidget()
        appearance = QVBoxLayout(self.layer_appearance_panel)
        appearance.setContentsMargins(0, 0, 0, 0)
        appearance_header = QHBoxLayout()
        self.active_layer_label = QLabel("Combined overlay")
        apply_info_style(self.active_layer_label)
        appearance_header.addWidget(self.active_layer_label)
        appearance_header.addStretch()
        self.show_mask_check = self.image_viewer.mask_overlay_button
        self.show_mask_check.toggled.connect(self._refresh_mask_overlay)
        appearance.addLayout(appearance_header)
        appearance_row = QHBoxLayout()
        appearance_row.addWidget(QLabel("Color"))
        self.layer_color_button = QPushButton()
        self._update_overlay_color_button()
        self.layer_color_button.setFixedWidth(42)
        self.layer_color_button.setToolTip("Choose the combined mask overlay color")
        self.layer_color_button.clicked.connect(self._choose_overlay_color)
        appearance_row.addWidget(self.layer_color_button)
        appearance_row.addSpacing(12)
        appearance_row.addWidget(QLabel("Opacity"))
        self.alpha_spin = QSpinBox()
        self.alpha_spin.setRange(0, 100)
        self.alpha_spin.setSuffix("%")
        self.alpha_spin.setValue(self.overlay_opacity)
        self.alpha_spin.valueChanged.connect(self._set_active_layer_opacity)
        appearance_row.addWidget(self.alpha_spin)
        appearance_row.addStretch()
        appearance.addLayout(appearance_row)
        self.mask_coverage_bar = QProgressBar()
        self.mask_coverage_bar.setRange(0, 1000)
        self.mask_coverage_bar.setValue(0)
        self.mask_coverage_bar.setFormat("Masked 0.0%")
        self.mask_coverage_bar.setTextVisible(True)
        self.mask_coverage_bar.setToolTip("Fraction of visible image pixels included in the combined mask")
        appearance.addWidget(self.mask_coverage_bar)
        self.export_combined_button = QPushButton("Export Combined Mask")
        self.export_combined_button.setToolTip("Export the combined mask from all visible layers")
        self.export_combined_button.clicked.connect(self._export_combined_mask)
        self.export_combined_button.setEnabled(self.combined_mask is not None)
        apply_emphasis_button_style(self.export_combined_button)
        appearance.addWidget(self.export_combined_button)
        self.layer_appearance_panel.setVisible(bool(self.mask_layers))
        layout.addWidget(self.layer_appearance_panel)
        return panel

    def _create_threshold_panel(self) -> QWidget:
        panel = QGroupBox("Threshold Mask")
        layout = QVBoxLayout(panel)
        mode_row = QHBoxLayout()
        self.threshold_mode_combo = QComboBox(panel)
        self.threshold_mode_combo.addItems(["Below", "Range", "Above"])
        self.threshold_mode_combo.hide()
        self.threshold_mode_combo.currentTextChanged.connect(self._on_threshold_controls_changed)
        self.threshold_mode_buttons = QButtonGroup(self)
        self.threshold_mode_buttons.setExclusive(True)
        for label, mode, icon_filename in (
            ("Below", "Below", "tool_threshold_below.svg"),
            ("Between", "Range", "tool_threshold_between.svg"),
            ("Above", "Above", "tool_threshold_above.svg"),
        ):
            button = QToolButton()
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self._register_asset_icon(button, icon_filename)
            button.setCheckable(True)
            button.setChecked(mode == "Below")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setFixedHeight(AppStyle.toolbar_symbol_button_size().height())
            AppStyle.apply_widget_style(button, 'compact_button')
            AppStyle.set_font_role(button, 'toolbar_text')
            button.clicked.connect(
                lambda checked, selected_mode=mode: checked and self.threshold_mode_combo.setCurrentText(selected_mode)
            )
            self.threshold_mode_buttons.addButton(button)
            mode_row.addWidget(button, 1)
        layout.addLayout(mode_row)

        histogram_controls = QHBoxLayout()
        self.threshold_log_x_check = QCheckBox("Log X")
        self.threshold_log_x_check.setToolTip("Use logarithmic spacing for the intensity axis")
        self.threshold_log_x_check.toggled.connect(self._on_threshold_scale_changed)
        histogram_controls.addWidget(self.threshold_log_x_check)
        histogram_controls.addStretch()
        fit_x_button = QPushButton("Fit X")
        fit_x_button.setToolTip("Fit the full histogram intensity range")
        fit_x_button.clicked.connect(self._fit_threshold_x)
        histogram_controls.addWidget(fit_x_button)
        layout.addLayout(histogram_controls)

        self.threshold_plot = pg.PlotWidget()
        self.threshold_plot.setMaximumHeight(150)
        self.threshold_plot.setMinimumHeight(110)
        self.threshold_plot.setMouseEnabled(x=True, y=False)
        self.threshold_plot.hideAxis('left')
        self.threshold_plot.setLabel('bottom', 'Intensity')
        self.threshold_region = pg.LinearRegionItem(values=(0.25, 0.75))
        self.threshold_region.sigRegionChanged.connect(self._on_threshold_region_changed)
        self.threshold_plot.addItem(self.threshold_region)
        layout.addWidget(self.threshold_plot)

        values = QHBoxLayout()
        self.threshold_low_control = QWidget()
        low_layout = QHBoxLayout(self.threshold_low_control)
        low_layout.setContentsMargins(0, 0, 0, 0)
        self.threshold_low_label = QLabel("Lower")
        low_layout.addWidget(self.threshold_low_label)
        self.threshold_low_spin = QDoubleSpinBox()
        self.threshold_low_spin.setDecimals(4)
        self.threshold_low_spin.setRange(-1.0e15, 1.0e15)
        self.threshold_low_spin.valueChanged.connect(self._on_threshold_spins_changed)
        self.threshold_low_spin.editingFinished.connect(self._normalize_threshold_spins)
        low_layout.addWidget(self.threshold_low_spin)
        values.addWidget(self.threshold_low_control)
        self.threshold_high_control = QWidget()
        high_layout = QHBoxLayout(self.threshold_high_control)
        high_layout.setContentsMargins(0, 0, 0, 0)
        self.threshold_high_label = QLabel("Upper")
        high_layout.addWidget(self.threshold_high_label)
        self.threshold_high_spin = QDoubleSpinBox()
        self.threshold_high_spin.setDecimals(4)
        self.threshold_high_spin.setRange(-1.0e15, 1.0e15)
        self.threshold_high_spin.valueChanged.connect(self._on_threshold_spins_changed)
        self.threshold_high_spin.editingFinished.connect(self._normalize_threshold_spins)
        high_layout.addWidget(self.threshold_high_spin)
        values.addWidget(self.threshold_high_control)
        values.addStretch()
        layout.addLayout(values)
        self._on_threshold_controls_changed()
        action_row = QHBoxLayout()
        cancel_button = QPushButton("Cancel")
        cancel_button.setToolTip("Hide the current threshold preview")
        cancel_button.clicked.connect(self._cancel_threshold_preview)
        action_row.addWidget(cancel_button, 1)
        self.create_threshold_button = QPushButton("Create Layer")
        self.create_threshold_button.clicked.connect(self._generate_threshold_mask)
        apply_emphasis_button_style(self.create_threshold_button)
        action_row.addWidget(self.create_threshold_button, 1)
        layout.addLayout(action_row)
        return panel

    def _refresh_threshold_histogram(self, *, reset_thresholds: bool = True) -> None:
        if not hasattr(self, 'threshold_plot'):
            return
        image_2d, is_valid, _ = validate_and_prepare_image_array(self.image_data)
        if not is_valid:
            return
        self._threshold_image_token = id(self.image_data)
        finite = np.asarray(image_2d, dtype=float)
        finite = finite[np.isfinite(finite)]
        if finite.size == 0:
            return
        log_x = self.threshold_log_x_check.isChecked()
        histogram_values = finite[finite > 0] if log_x else finite
        if histogram_values.size == 0:
            self.threshold_log_x_check.blockSignals(True)
            self.threshold_log_x_check.setChecked(False)
            self.threshold_log_x_check.blockSignals(False)
            log_x = False
            histogram_values = finite
            self.parent_app.show_status("Log X requires positive intensity values; using Linear X")

        plot_values = np.log10(histogram_values) if log_x else histogram_values
        counts, edges = np.histogram(
            plot_values,
            bins=min(256, max(32, int(np.sqrt(plot_values.size)))),
        )
        centers = 0.5 * (edges[:-1] + edges[1:])
        log_counts = np.log1p(counts)
        normalized_counts = log_counts / max(1.0, float(np.max(log_counts)))
        self.threshold_plot.clear()
        self.threshold_plot.getAxis('bottom').setLogMode(log_x)
        histogram_color = AppStyle.theme_colors()['grid']
        histogram_fill = QColor(histogram_color)
        histogram_fill.setAlpha(45)
        self.threshold_plot.plot(
            centers,
            normalized_counts,
            pen=pg.mkPen(histogram_color, width=1.5),
            fillLevel=0,
            brush=pg.mkBrush(histogram_fill),
        )
        self.threshold_plot.addItem(self.threshold_region)
        self._threshold_histogram_bounds = (float(edges[0]), float(edges[-1]))

        if reset_thresholds:
            low, high = np.percentile(histogram_values, [5.0, 95.0])
        else:
            low = self.threshold_low_spin.value()
            high = self.threshold_high_spin.value()
            if log_x:
                positive_min = float(np.min(histogram_values))
                low = max(low, positive_min)
                high = max(high, low)
        if high <= low:
            high = low + 1.0
        plot_low, plot_high = self._threshold_values_to_plot(float(low), float(high))
        self._updating_threshold_controls = True
        try:
            self.threshold_region.setBounds(self._threshold_histogram_bounds)
            self.threshold_region.setRegion((plot_low, plot_high))
            self.threshold_low_spin.setValue(float(low))
            self.threshold_high_spin.setValue(float(high))
        finally:
            self._updating_threshold_controls = False
        self._fit_threshold_x()
        self._threshold_preview = None
        self.image_viewer.remove_overlay('threshold-preview')

    def _threshold_values_to_plot(self, low: float, high: float) -> tuple[float, float]:
        if self.threshold_log_x_check.isChecked():
            tiny = np.finfo(float).tiny
            return float(np.log10(max(low, tiny))), float(np.log10(max(high, tiny)))
        return low, high

    def _threshold_values_from_plot(self, low: float, high: float) -> tuple[float, float]:
        if self.threshold_log_x_check.isChecked():
            return float(10.0 ** low), float(10.0 ** high)
        return low, high

    def _on_threshold_scale_changed(self) -> None:
        had_preview = self._threshold_preview is not None
        self._refresh_threshold_histogram(reset_thresholds=False)
        if had_preview:
            self._update_threshold_preview()

    def _fit_threshold_x(self) -> None:
        if self._threshold_histogram_bounds is None:
            return
        low, high = self._threshold_histogram_bounds
        self.threshold_plot.setXRange(low, high, padding=0.02)

    def _on_threshold_region_changed(self) -> None:
        if self._updating_threshold_controls:
            return
        plot_low, plot_high = self.threshold_region.getRegion()
        low, high = self._threshold_values_from_plot(plot_low, plot_high)
        self._updating_threshold_controls = True
        try:
            self.threshold_low_spin.setValue(float(low))
            self.threshold_high_spin.setValue(float(high))
        finally:
            self._updating_threshold_controls = False
        self._update_threshold_preview()

    def _on_threshold_spins_changed(self) -> None:
        if self._updating_threshold_controls:
            return
        low = self.threshold_low_spin.value()
        high = self.threshold_high_spin.value()
        if high < low:
            low, high = high, low
        if self.threshold_log_x_check.isChecked() and low <= 0:
            if self._threshold_histogram_bounds is None:
                return
            low = 10.0 ** self._threshold_histogram_bounds[0]
            high = max(high, low)
            self._updating_threshold_controls = True
            try:
                self.threshold_low_spin.setValue(low)
                self.threshold_high_spin.setValue(high)
            finally:
                self._updating_threshold_controls = False
        plot_low, plot_high = self._threshold_values_to_plot(low, high)
        self._updating_threshold_controls = True
        try:
            self.threshold_region.setRegion((plot_low, plot_high))
        finally:
            self._updating_threshold_controls = False
        self._update_threshold_preview()

    def _normalize_threshold_spins(self) -> None:
        low = self.threshold_low_spin.value()
        high = self.threshold_high_spin.value()
        if low <= high:
            return
        self._updating_threshold_controls = True
        try:
            self.threshold_low_spin.setValue(high)
            self.threshold_high_spin.setValue(low)
        finally:
            self._updating_threshold_controls = False
        self._on_threshold_spins_changed()

    def _on_threshold_controls_changed(self) -> None:
        mode = self.threshold_mode_combo.currentText()
        self.threshold_low_control.setVisible(mode != "Below")
        self.threshold_high_control.setVisible(mode != "Above")
        self.threshold_low_label.setText("Threshold" if mode == "Above" else "Lower")
        self.threshold_high_label.setText("Threshold" if mode == "Below" else "Upper")
        self._update_threshold_preview()

    def _make_threshold_mask(self) -> np.ndarray | None:
        image_2d, is_valid, _ = validate_and_prepare_image_array(self.image_data)
        if not is_valid:
            return None
        low = self.threshold_low_spin.value()
        high = self.threshold_high_spin.value()
        if high < low:
            low, high = high, low
        mode = self.threshold_mode_combo.currentText()
        finite = np.isfinite(image_2d)
        if mode == "Below":
            return finite & (image_2d <= high)
        if mode == "Above":
            return finite & (image_2d >= low)
        return finite & (image_2d >= low) & (image_2d <= high)

    def _update_threshold_preview(self) -> None:
        mask = self._make_threshold_mask()
        if mask is None:
            self._threshold_preview = None
            return
        self._threshold_preview = mask
        if hasattr(self, 'image_viewer'):
            self.image_viewer.add_mask_overlay(
                'threshold-preview',
                mask,
                group='threshold-preview',
                color=VIEWER_COLORS.mask_preview,
                alpha=0.45,
            )

    def _cancel_threshold_preview(self) -> None:
        self._threshold_preview = None
        if hasattr(self, 'image_viewer'):
            self.image_viewer.remove_overlay('threshold-preview')

    def update_plot(self, image_data=None):
        super().update_plot(image_data)
        source = image_data if image_data is not None else self.image_data
        if source is not None and id(source) != self._threshold_image_token:
            self._refresh_threshold_histogram()
    
    def _create_separator(self):
        """Create a horizontal separator line"""
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        return separator
    
    def _load_tool_icon(self, tool_name: str) -> QIcon:
        icon_filename = MASK_TOOL_ICON_FILES.get(tool_name)
        if not icon_filename:
            return QIcon()
        return self._load_asset_icon(icon_filename)

    def _load_asset_icon(self, icon_filename: str) -> QIcon:
        workspace_root = getattr(self.parent_app, '_workspace_root', Path(__file__).resolve().parent.parent)
        return AppStyle.load_icon(workspace_root, icon_filename)

    def _register_asset_icon(self, button, icon_filename: str) -> None:
        button.setIcon(self._load_asset_icon(icon_filename))
        button.setIconSize(AppStyle.mask_tool_icon_size())
        self._asset_icon_buttons.append((button, icon_filename))

    def refresh_theme(self):
        """Refresh all Mask-owned icons, styles, and plot colors."""
        if hasattr(self, 'image_viewer'):
            self.image_viewer.refresh_theme()
        if hasattr(self, 'navigation_buttons'):
            for mode, button in self.navigation_buttons.items():
                AppStyle.apply_widget_style(button, 'compact_button')
                button.setIcon(self.image_viewer.toolbar_icon(mode))
                button.setIconSize(AppStyle.mask_tool_icon_size())
        if hasattr(self, 'fit_view_button'):
            AppStyle.apply_widget_style(self.fit_view_button, 'compact_button')
            self.fit_view_button.setIcon(self.image_viewer.toolbar_icon("home"))
            self.fit_view_button.setIconSize(AppStyle.mask_tool_icon_size())
        if hasattr(self, 'tool_buttons'):
            icon_size = AppStyle.mask_tool_icon_size()
            for tool_name, button in self.tool_buttons.items():
                AppStyle.apply_widget_style(button, 'compact_button')
                button.setProperty("baseStyleSheet", button.styleSheet())
                icon = self._load_tool_icon(tool_name)
                if not icon.isNull():
                    button.setIcon(icon)
                    button.setIconSize(icon_size)
        for button, icon_filename in self._asset_icon_buttons:
            AppStyle.apply_widget_style(button, 'compact_button')
            button.setIcon(self._load_asset_icon(icon_filename))
            button.setIconSize(AppStyle.mask_tool_icon_size())
        if hasattr(self, 'layer_list') and self.mask_layers:
            self._refresh_layer_row_states(self._get_active_layer_index())
        if hasattr(self, 'threshold_plot'):
            colors = AppStyle.theme_colors()
            self.threshold_plot.setBackground(colors['base'].name())
            bottom_axis = self.threshold_plot.getAxis('bottom')
            bottom_axis.setPen(colors['text'])
            bottom_axis.setTextPen(colors['text'])
            had_preview = self._threshold_preview is not None
            self._refresh_threshold_histogram(reset_thresholds=False)
            if had_preview:
                self._update_threshold_preview()
        if self._alt_inversion_active:
            self._refresh_inversion_feedback()
    
    def _add_tab_specific_status(self, info_lines):
        """Add mask-specific status information"""
        info_lines.append("")  # Blank line separator
        
        # === MASK STATUS ===
        info_lines.append("=== MASK LAYERS ===")
        info_lines.append(f"Number of layers: {len(self.mask_layers)}")
        
        for i, layer in enumerate(self.mask_layers):
            visibility = "visible" if layer.visible else "hidden"
            operation = "base" if i == 0 else ("add" if layer.combine_mode == "OR" else "overlap")
            masked_pixels = np.sum(layer.data)
            total_pixels = layer.data.size
            mask_percentage = (masked_pixels / total_pixels) * 100
            info_lines.append(
                f"  Layer {i+1}: {layer.name} ({visibility}, {operation}) - "
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
        """Render layer rows with explicit operators between adjacent layers."""
        active_index = self._get_active_layer_index()
        self.layer_list.blockSignals(True)
        self.layer_list.clear()

        for index, layer in enumerate(self.mask_layers):
            if index:
                connector_item = QListWidgetItem()
                connector_item.setFlags(Qt.ItemIsEnabled)
                self.layer_list.addItem(connector_item)
                connector_widget = QWidget()
                connector_layout = QHBoxLayout(connector_widget)
                connector_layout.setContentsMargins(8, 0, 8, 0)
                left_line = QFrame()
                left_line.setFrameShape(QFrame.HLine)
                connector_layout.addWidget(left_line)
                connector = QPushButton()
                connector.setFlat(True)
                connector.setFixedWidth(48)
                connector.setFixedHeight(AppStyle.toolbar_text_button_height())
                connector.setText(layer.combine_mode)
                operation_help = (
                    "∪ Union · either mask"
                    if layer.combine_mode == "OR"
                    else "∩ Intersection · both masks"
                )
                connector.setToolTip(operation_help)
                connector.clicked.connect(
                    lambda _checked=False, layer_index=index: self._toggle_layer_operator(layer_index)
                )
                connector_layout.addWidget(connector)
                right_line = QFrame()
                right_line.setFrameShape(QFrame.HLine)
                connector_layout.addWidget(right_line)
                connector_item.setSizeHint(connector_widget.sizeHint())
                self.layer_list.setItemWidget(connector_item, connector_widget)

            coverage = 100.0 * float(np.count_nonzero(layer.data)) / max(1, layer.data.size)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, index)
            self.layer_list.addItem(item)
            row_widget = self._create_layer_row(index, layer, coverage, index == active_index)
            item.setSizeHint(row_widget.sizeHint())
            self.layer_list.setItemWidget(item, row_widget)

        self.layer_list.blockSignals(False)
        self.layer_empty_hint.setVisible(not self.mask_layers)
        self.layer_appearance_panel.setVisible(bool(self.mask_layers))
        if self.mask_layers:
            target = active_index if active_index is not None else len(self.mask_layers) - 1
            self.layer_list.setCurrentRow(self._list_row_for_layer(target))
        self.remove_layer_button.setEnabled(bool(self.mask_layers))
        self._refresh_edit_target()
        self._update_combined_mask()
    
    def _create_layer_row(self, layer_index: int, layer: MaskLayer, coverage: float, active: bool) -> QWidget:
        row = QWidget()
        row.setObjectName("maskLayerRow")
        colors = AppStyle.resolved_colors()
        row.setStyleSheet(
            f"QWidget#maskLayerRow {{ border-left: 3px solid {colors['border_active']}; }}"
            if active else "QWidget#maskLayerRow { border-left: 3px solid transparent; }"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(5)
        visible = QToolButton()
        visible.setCheckable(True)
        visible.setChecked(layer.visible)
        visible.setAutoRaise(True)
        visible.setFixedSize(AppStyle.corner_button_size())
        visible.setIconSize(AppStyle.corner_button_icon_size())
        visible.setIcon(self._load_asset_icon("status_visible.svg" if layer.visible else "status_hidden.svg"))
        visible.setToolTip("Visible" if layer.visible else "Hidden")
        visible.toggled.connect(
            lambda checked, index=layer_index: self._set_layer_visibility(index, checked)
        )
        layout.addWidget(visible)
        labels = QVBoxLayout()
        labels.setSpacing(0)
        name = QLabel(layer.name)
        name.setToolTip(layer.name)
        labels.addWidget(name)
        details = QLabel(f"{coverage:.1f}% masked")
        apply_info_style(details)
        labels.addWidget(details)
        layout.addLayout(labels, 1)
        if active:
            editing_status = QLabel()
            editing_status.setPixmap(
                self._load_asset_icon("status_editing.svg").pixmap(AppStyle.corner_button_icon_size())
            )
            editing_status.setToolTip("Active editing layer" if layer.visible else "Active layer is hidden")
            layout.addWidget(editing_status)
        return row

    def _set_layer_visibility(self, layer_index: int, visible: bool) -> None:
        if 0 <= layer_index < len(self.mask_layers):
            self.mask_layers[layer_index].visible = visible
            self._update_layer_list()

    def _show_layer_context_menu(self, position) -> None:
        item = self.layer_list.itemAt(position)
        layer_index = item.data(Qt.UserRole) if item is not None else None
        if not isinstance(layer_index, int) or not (0 <= layer_index < len(self.mask_layers)):
            return
        self.layer_list.setCurrentItem(item)
        layer = self.mask_layers[layer_index]
        menu = QMenu(self.layer_list)
        menu.addAction("Rename...", self._rename_selected_layer)
        menu.addAction("Duplicate", self._duplicate_selected_layer)
        menu.addAction("Export...", self._export_selected_layer)
        menu.addSeparator()
        move_up = menu.addAction("Move Up", self._move_layer_up)
        move_up.setEnabled(layer_index > 0)
        move_down = menu.addAction("Move Down", self._move_layer_down)
        move_down.setEnabled(layer_index < len(self.mask_layers) - 1)
        menu.addSeparator()
        visibility = menu.addAction("Hide" if layer.visible else "Show")
        visibility.triggered.connect(
            lambda: self._set_layer_visibility(layer_index, not layer.visible)
        )
        menu.addSeparator()
        menu.addAction("Remove", self._remove_selected_layer)
        menu.exec_(self.layer_list.viewport().mapToGlobal(position))
    
    def _on_layer_selected(self, row):
        """Handle layer selection"""
        item = self.layer_list.item(row) if row >= 0 else None
        layer_index = item.data(Qt.UserRole) if item is not None else None
        has_active_layer = isinstance(layer_index, int) and (0 <= layer_index < len(self.mask_layers))
        self.remove_layer_button.setEnabled(has_active_layer)
        if not has_active_layer:
            self._refresh_edit_target()
            return
        layer = self.mask_layers[layer_index]
        state = "Editing" if layer.visible else "Hidden - show this layer before editing"
        self._refresh_layer_row_states(layer_index)
        self._refresh_edit_target()
        self.parent_app.show_status(f"Active mask layer: {layer.name} ({state})")

    def _refresh_layer_row_states(self, active_index: int | None) -> None:
        for layer_index, layer in enumerate(self.mask_layers):
            item = self.layer_list.item(self._list_row_for_layer(layer_index))
            if item is None:
                continue
            coverage = 100.0 * float(np.count_nonzero(layer.data)) / max(1, layer.data.size)
            row_widget = self._create_layer_row(layer_index, layer, coverage, layer_index == active_index)
            item.setSizeHint(row_widget.sizeHint())
            self.layer_list.setItemWidget(item, row_widget)

    def _refresh_edit_target(self) -> None:
        if not hasattr(self, 'edit_target_label') or not hasattr(self, 'layer_list'):
            return
        layer_index = self._get_active_layer_index()
        layer = self.mask_layers[layer_index] if layer_index is not None else None
        editable = layer is not None and layer.visible
        if layer is None:
            self.edit_target_label.setText("Editing: create or add a layer first")
        elif layer.visible:
            self.edit_target_label.setText(f"Editing: {layer.name}")
        else:
            self.edit_target_label.setText(f"Editing: {layer.name} (hidden)")
        for button in self.tool_buttons.values():
            button.setEnabled(editable)
        for button in self.refine_buttons:
            button.setEnabled(editable)

    def _get_active_layer_index(self) -> Optional[int]:
        """Return the currently editable layer index."""
        current_item = self.layer_list.currentItem() if hasattr(self, 'layer_list') else None
        layer_index = current_item.data(Qt.UserRole) if current_item is not None else None
        if isinstance(layer_index, int) and 0 <= layer_index < len(self.mask_layers):
            return layer_index

        if self.mask_layers:
            fallback = len(self.mask_layers) - 1
            self.layer_list.setCurrentRow(self._list_row_for_layer(fallback))
            return fallback

        return None

    def _get_active_layer(self) -> Optional[MaskLayer]:
        """Return the current editable layer object."""
        layer_index = self._get_active_layer_index()
        if layer_index is None:
            return None
        return self.mask_layers[layer_index]

    @staticmethod
    def _list_row_for_layer(layer_index: int) -> int:
        return layer_index * 2

    def _toggle_layer_operator(self, layer_index: int) -> None:
        if not (0 < layer_index < len(self.mask_layers)):
            return
        layer = self.mask_layers[layer_index]
        layer.combine_mode = "AND" if layer.combine_mode == "OR" else "OR"
        self._update_layer_list()

    def _set_overlay_color(self, color: str) -> None:
        self.overlay_color = color
        self._update_overlay_color_button()
        self._refresh_mask_overlay()

    def _choose_overlay_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.overlay_color), self, "Choose combined mask color")
        if color.isValid():
            self._set_overlay_color(color.name())

    def _update_overlay_color_button(self) -> None:
        self.layer_color_button.setIcon(AppStyle.color_swatch_icon(self.overlay_color))

    def _set_active_layer_opacity(self, opacity: int) -> None:
        self.overlay_opacity = int(opacity)
        self._refresh_mask_overlay()
    
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
            self.layer_list.setCurrentRow(self._list_row_for_layer(len(self.mask_layers) - 1))
            self.parent_app.show_status("Added empty layer")
            
        except Exception as e:
            self.parent_app.show_status(f"Error creating empty layer: {str(e)}")
            print(f"DEBUG: _add_empty_layer error: {e}")
            print(f"DEBUG: image_data type: {type(self.image_data)}")
    
    def _remove_selected_layer(self):
        """Remove the selected layer"""
        current_row = self._get_active_layer_index()
        if current_row is None:
            self.parent_app.show_status("No layer selected")
            return
        
        removed_layer = self.mask_layers.pop(current_row)
        self._update_layer_list()
        self.parent_app.show_status(f"Removed layer: {removed_layer.name}")

    def _clear_all_layers(self) -> None:
        """Remove every mask layer after confirmation."""
        if not self.mask_layers:
            return
        reply = QMessageBox.question(
            self, "Clear Layers",
            "Remove all mask layers?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if self.drawing_mode:
            self._set_drawing_enabled_from_session(False)
        self.undo_stack.push(_LayerClearCommand(self.mask_layers, self._update_layer_list))
        self.parent_app.show_status("Cleared all mask layers")

    def _rename_selected_layer(self) -> None:
        layer = self._get_active_layer()
        if layer is None:
            return
        name, accepted = QInputDialog.getText(self, "Rename Layer", "Layer name", text=layer.name)
        if accepted and name.strip():
            layer.name = name.strip()
            self._update_layer_list()

    def _duplicate_selected_layer(self) -> None:
        layer_index = self._get_active_layer_index()
        if layer_index is None:
            return
        original = self.mask_layers[layer_index]
        duplicate = MaskLayer(
            original.data.copy(),
            f"{original.name} Copy",
            original.visible,
            combine_mode=original.combine_mode,
        )
        duplicate.source = original.source
        self.mask_layers.insert(layer_index + 1, duplicate)
        self._update_layer_list()
        self.layer_list.setCurrentRow(self._list_row_for_layer(layer_index + 1))
    
    def _move_layer_up(self):
        """Move selected layer up"""
        current_row = self._get_active_layer_index()
        if current_row is None or current_row <= 0:
            return
        
        self.mask_layers[current_row], self.mask_layers[current_row-1] = \
            self.mask_layers[current_row-1], self.mask_layers[current_row]
        
        self._update_layer_list()
        self.layer_list.setCurrentRow(self._list_row_for_layer(current_row - 1))
    
    def _move_layer_down(self):
        """Move selected layer down"""
        current_row = self._get_active_layer_index()
        if current_row is None or current_row >= len(self.mask_layers) - 1:
            return
        
        self.mask_layers[current_row], self.mask_layers[current_row+1] = \
            self.mask_layers[current_row+1], self.mask_layers[current_row]
        
        self._update_layer_list()
        self.layer_list.setCurrentRow(self._list_row_for_layer(current_row + 1))
    
    def get_session_state(self) -> dict:
        """Serialize mask layers (as compressed arrays) for restart restore."""
        if not self.mask_layers:
            return {}
        layers_meta = []
        for i, layer in enumerate(self.mask_layers):
            filename = session_cache.save_array(f"mask_layer_{i}", layer.data)
            layers_meta.append({
                "name": layer.name,
                "visible": layer.visible,
                "source": layer.source,
                "combine_mode": layer.combine_mode,
                "file": filename,
            })
        return {
            "layers": layers_meta,
            "overlay_color": self.overlay_color,
            "overlay_opacity": self.overlay_opacity,
        }

    def restore_session_state(self, state: dict) -> None:
        """Rebuild mask layers from the last saved session, if any."""
        layers_meta = state.get("layers")
        if not layers_meta:
            return
        legacy_combine_mode = state.get("combine_method", "OR")
        restored = []
        for meta in layers_meta:
            data = session_cache.load_array(meta.get("file", ""))
            if data is None:
                continue
            layer = MaskLayer(
                data,
                meta.get("name", "Layer"),
                meta.get("visible", True),
                combine_mode=meta.get("combine_mode", legacy_combine_mode),
            )
            layer.source = meta.get("source", "custom")
            restored.append(layer)
        if not restored:
            return
        self.mask_layers = restored
        self.overlay_color = state.get("overlay_color", self.overlay_color)
        self.overlay_opacity = int(state.get("overlay_opacity", self.overlay_opacity))
        self._update_overlay_color_button()
        self.alpha_spin.blockSignals(True)
        self.alpha_spin.setValue(self.overlay_opacity)
        self.alpha_spin.blockSignals(False)
        self._update_layer_list()
        self.parent_app.show_status(f"Restored {len(restored)} mask layer(s) from last session")

    
    def _update_combined_mask(self):
        """Compose visible layers in list order using each incoming operator."""
        self._preview_mask = None
        self.combined_mask = compose_mask_layers(self.mask_layers)
        self.export_combined_button.setEnabled(self.combined_mask is not None)
        if self.combined_mask is None:
            if hasattr(self.parent_app, 'publish_shared_mask'):
                self.parent_app.publish_shared_mask(None, source_tab=self)
            self.mask_coverage_bar.setValue(0)
            self.mask_coverage_bar.setFormat("Masked 0.0%")
            self.mask_coverage_bar.setToolTip("No visible mask layers")
            self._refresh_mask_overlay()
            return

        if hasattr(self.parent_app, 'publish_shared_mask'):
            self.parent_app.publish_shared_mask(self.combined_mask.copy(), source_tab=self)
        
        # Update statistics
        masked_pixels = np.sum(self.combined_mask)
        total_pixels = self.combined_mask.size
        mask_percentage = (masked_pixels / total_pixels) * 100
        
        self.mask_coverage_bar.setValue(round(mask_percentage * 10))
        self.mask_coverage_bar.setFormat(f"Masked {mask_percentage:.1f}%")
        self.mask_coverage_bar.setToolTip(f"{masked_pixels:,} of {total_pixels:,} pixels masked")
        self._refresh_mask_overlay()

    def _set_combined_mask_preview(self, mask: np.ndarray) -> None:
        """Set a temporary combined mask generated by the drawing session."""
        self._preview_mask = mask

    def _set_drawing_enabled_from_session(self, enabled: bool) -> None:
        """Set drawing state and keep tool buttons/canvas lock in sync."""
        if self.drawing_mode and not enabled:
            self.drawing_session.cancel_current_edit()
        self.drawing_mode = bool(enabled)

        if self.drawing_mode:
            self.image_viewer.set_interaction_locked(True)
            self.image_viewer.setCursor(QCursor(Qt.CrossCursor))
            for button in self.navigation_buttons.values():
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
            if hasattr(self, 'tool_buttons') and self.drawing_tool.name in self.tool_buttons:
                button = self.tool_buttons[self.drawing_tool.name]
                button.blockSignals(True)
                button.setChecked(True)
                button.blockSignals(False)
            self.tool_options_panel.setVisible(True)
        else:
            if hasattr(self, 'tool_buttons'):
                for button in self.tool_buttons.values():
                    button.blockSignals(True)
                    button.setChecked(False)
                    button.blockSignals(False)
                    button.setStyleSheet(button.property("baseStyleSheet") or "")
            self.image_viewer.set_interaction_locked(False)
            self.image_viewer.setCursor(QCursor(Qt.ArrowCursor))
            self.tool_options_panel.setVisible(False)

        self._refresh_mask_overlay()
        
    # ===== Mask Generation Methods =====
    
    def _generate_threshold_mask(self):
        """Commit the current non-destructive threshold preview as a new layer."""
        mask = self._make_threshold_mask()
        if mask is None:
            self.parent_app.show_status("Load an image before creating a threshold mask")
            return
        mode = self.threshold_mode_combo.currentText()
        low = self.threshold_low_spin.value()
        high = self.threshold_high_spin.value()
        if mode == "Below":
            description = f"Below {high:.4g}"
        elif mode == "Above":
            description = f"Above {low:.4g}"
        else:
            description = f"Range {low:.4g} to {high:.4g}"
        layer = MaskLayer(mask, f"Threshold: {description}")
        layer.source = "generated"
        self._threshold_preview = None
        self.image_viewer.remove_overlay('threshold-preview')
        self.undo_stack.push(
            _LayerAddCommand(self.mask_layers, layer, len(self.mask_layers), self._update_layer_list)
        )
        self.layer_list.setCurrentRow(self._list_row_for_layer(len(self.mask_layers) - 1))
        self.parent_app.show_status(f"Created mask layer from intensity: {description}")
    
    def _activate_drawing_tool(self, tool_name: str, checked: bool):
        """Activate a drawing tool button and lock the image canvas while it is checked."""
        if checked:
            active_layer = self._get_active_layer()
            if active_layer is None:
                self.tool_buttons[tool_name].setChecked(False)
                self.parent_app.show_status("Create or select a mask layer before drawing")
                return
            if not active_layer.visible:
                self.tool_buttons[tool_name].setChecked(False)
                self.parent_app.show_status("Show the active layer before editing it")
                return
            if self.drawing_mode and self.drawing_tool.name != tool_name:
                self.drawing_session.cancel_current_edit()
            for name, button in self.tool_buttons.items():
                if name != tool_name:
                    button.blockSignals(True)
                    button.setChecked(False)
                    button.blockSignals(False)
                    button.setStyleSheet(button.property("baseStyleSheet") or "")
            self._set_drawing_tool(tool_name)
            self._set_drawing_enabled_from_session(True)
            self.parent_app.show_status(f"{tool_name} active")
            return

        if self.drawing_tool and self.drawing_tool.name == tool_name:
            self._set_drawing_enabled_from_session(False)
            self.image_viewer.activate_navigation_mode("pan")

    def _set_drawing_tool(self, tool_name: str):
        """Switch to a different drawing tool"""
        if tool_name in self.drawing_tools:
            self.drawing_tool = self.drawing_tools[tool_name]
            uses_size = tool_name in ['Brush', 'Eraser', 'Line', 'Smart Fill']
            if uses_size:
                self.drawing_tool.brush_size = self.brush_size
            self.tool_size_label.setVisible(uses_size)
            self.brush_size_spin.setVisible(uses_size)
            self.brush_size_slider.setVisible(uses_size)
            is_polygon = tool_name == "Polygon"
            self.finish_polygon_button.setVisible(is_polygon)
            self.cancel_tool_button.setVisible(is_polygon)
            effect = "restore pixels" if tool_name == "Eraser" else "mask pixels"
            hint = "Click vertices, then Enter or double-click to finish." if is_polygon else "Hold Alt to invert the effect."
            self.active_tool_label.setText(f"{tool_name}: {effect}. {hint}")
            self.drawing_tool.draw_value = self._effective_draw_value()
            self.parent_app.show_status(f"Drawing tool changed to: {tool_name}")
    
    def _update_tool_brush_size(self, size: int):
        """Update shared size controls for brush-like drawing tools."""
        self.brush_size = size
        for tool_name in ['Brush', 'Eraser', 'Line', 'Smart Fill']:
            if tool_name in self.drawing_tools:
                self.drawing_tools[tool_name].brush_size = size
        if self.drawing_tool.name in ['Brush', 'Eraser', 'Line', 'Smart Fill']:
            self.drawing_tool.brush_size = size
    
    def _update_tool_mode(self):
        """Compatibility shim; tool effect now follows Brush/Eraser plus Alt."""
        self.drawing_tool.draw_value = self._effective_draw_value()

    def _on_viewer_mode_changed(self, mode: str) -> None:
        if mode in {"pan", "zoom"} and self.drawing_mode:
            self._set_drawing_enabled_from_session(False)
        for name, button in self.navigation_buttons.items():
            button.blockSignals(True)
            button.setChecked(name == mode)
            button.blockSignals(False)

    def _finish_polygon(self) -> None:
        if self.drawing_session.finish_polygon():
            self._clear_polygon_feedback()
            self.parent_app.show_status("Polygon applied to the active layer")

    def _cancel_current_edit(self) -> None:
        self.drawing_session.cancel_current_edit()
        self._clear_polygon_feedback()
        self.parent_app.show_status("Current drawing cancelled")

    def _refresh_polygon_feedback(self, event=None) -> None:
        tool = self.drawing_tool
        if not self.drawing_mode or not isinstance(tool, PolygonDrawingTool) or not tool.vertices:
            self._clear_polygon_feedback()
            return
        points = list(tool.vertices)
        if event is not None and getattr(event, "inside_image", False):
            points.append((int(event.y), int(event.x)))
        x_values = [column + 0.5 for row, column in points]
        y_values = [row + 0.5 for row, column in points]
        self.image_viewer.add_polyline(
            "mask-polygon-boundary", x_values, y_values,
            group="mask-edit", color=VIEWER_COLORS.mask_preview, width=2.0,
        )
        vertices_x = [column + 0.5 for row, column in tool.vertices]
        vertices_y = [row + 0.5 for row, column in tool.vertices]
        self.image_viewer.add_points(
            "mask-polygon-vertices", vertices_x, vertices_y,
            group="mask-edit", color=VIEWER_COLORS.mask_preview,
            pen=VIEWER_COLORS.mask_preview, size=9.0,
        )

    def _clear_polygon_feedback(self) -> None:
        self.image_viewer.remove_overlay("mask-polygon-boundary")
        self.image_viewer.remove_overlay("mask-polygon-vertices")

    def _install_shortcuts(self) -> None:
        self._mask_shortcuts = []
        for key, tool_name in (("B", "Brush"), ("E", "Eraser"), ("L", "Line"), ("R", "Rectangle"), ("C", "Circle"), ("P", "Polygon"), ("F", "Smart Fill")):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda name=tool_name: self.tool_buttons[name].click())
            self._mask_shortcuts.append(shortcut)
        for sequence, callback in (
            (QKeySequence.Undo, self.undo_stack.undo),
            (QKeySequence.Redo, self.undo_stack.redo),
            (QKeySequence("Ctrl+Shift+Z"), self.undo_stack.redo),
            (QKeySequence(Qt.Key_Return), self._finish_polygon),
            (QKeySequence(Qt.Key_Escape), self._cancel_current_edit),
        ):
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(callback)
            self._mask_shortcuts.append(shortcut)

    def _refine_active_layer(self, operation: str) -> None:
        layer = self._get_active_layer()
        if layer is None:
            self.parent_app.show_status("Select a mask layer to refine")
            return
        if not layer.visible:
            self.parent_app.show_status("Show the active layer before refining it")
            return
        before = layer.data.copy()
        after = erode_mask(before, radius=1) if operation == "shrink" else dilate_mask(before, radius=1)
        layer.data = after
        self.undo_stack.push(_MaskArrayCommand(layer, before, after, f"{operation.title()} mask 1 px", self._update_layer_list))
        self._update_layer_list()
    
    
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

            def _normalize_rel_path(path_like: str | Path | None) -> Path | None:
                if not path_like:
                    return None
                text = str(path_like).strip()
                if not text:
                    return None
                # Accept both POSIX and Windows separators from config values.
                return Path(text.replace('\\', '/'))

            def _candidate_mask_roots() -> list[Path]:
                roots: list[Path] = []

                if MASK_BASE_DIR:
                    roots.append(Path(MASK_BASE_DIR))

                if getattr(self.parent_app, 'image_path', None):
                    roots.append(Path(self.parent_app.image_path).expanduser().resolve().parent)

                # Common local layouts for development or packaged installs.
                roots.append(Path.cwd())
                roots.append(Path.cwd() / 'masks')
                roots.append(Path.cwd() / 'SciAnalysis' / 'XSAnalysis' / 'masks')
                roots.append(Path.cwd() / 'XSAnalysis' / 'masks')

                # Keep order while removing duplicates.
                seen: set[str] = set()
                unique_roots: list[Path] = []
                for root in roots:
                    key = str(root)
                    if key in seen:
                        continue
                    seen.add(key)
                    unique_roots.append(root)
                return unique_roots

            def _resolve_mask_path(path_like: str | Path | None) -> tuple[Path | None, list[Path]]:
                rel = _normalize_rel_path(path_like)
                checked: list[Path] = []
                if rel is None:
                    return None, checked

                candidate = Path(rel).expanduser()
                if candidate.is_absolute():
                    checked.append(candidate)
                    return (candidate if candidate.exists() else None), checked

                for root in _candidate_mask_roots():
                    trial = root / rel
                    checked.append(trial)
                    if trial.exists():
                        return trial, checked

                # Last chance: as-provided relative to current working directory.
                checked.append(candidate)
                if candidate.exists():
                    return candidate, checked

                return None, checked
            
            # Use provided mask_path or fall back to default mask_file
            if mask_path is None:
                # Backward compatibility: use old mask_file format if available
                mask_file = detector_config.get('mask_file', '')
                if mask_file:
                    mask_path = mask_file
                else:
                    # Try to load default_mask from available_masks
                    available_masks = detector_config.get('available_masks', {})
                    default_mask_name = detector_config.get('default_mask', '')
                    if default_mask_name and default_mask_name in available_masks:
                        mask_path = available_masks[default_mask_name]
                    elif default_mask_name:
                        # New profile format stores the relative file path directly.
                        mask_path = default_mask_name
                    else:
                        self.parent_app.show_status(f"No mask configured for {detector_name}")
                        return

            resolved_mask_path, checked_paths = _resolve_mask_path(mask_path)

            if resolved_mask_path is not None:
                mask_data = self._load_mask_file(str(resolved_mask_path))
                
                if mask_data is not None:
                    # Extract mask name from path
                    mask_name = resolved_mask_path.name
                    layer = MaskLayer(mask_data, f"Instrument: {mask_name}")
                    layer.source = "default"
                    self.mask_layers.append(layer)
                    
                    self._update_layer_list()
                    self.parent_app.show_status(f"Loaded instrument mask: {mask_name}")
                    return
            else:
                checked_preview = '; '.join(str(path) for path in checked_paths[:3])
                if len(checked_paths) > 3:
                    checked_preview += '; ...'
                self.parent_app.show_status(
                    f"Mask file not found: {mask_path}. Checked: {checked_preview}"
                )
                
        except Exception as e:
            self.parent_app.show_status(f"Error loading instrument mask: {str(e)}")
    
    def _load_custom_mask(self):
        """Load a custom mask file"""
        file_path, _ = choose_path(
            self,
            "Load Mask File",
            file_filter="Mask Files (*.npy *.tif *.tiff *.png *.xcf);;All Files (*)",
            key="mask_open",
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
    
    # ===== Export Methods =====
    
    def _export_combined_mask(self):
        """Export the combined mask"""
        if self.combined_mask is None:
            self.parent_app.show_status("No mask to export")
            return
        
        self._export_mask_data(self.combined_mask, "combined_mask")
    
    def _export_selected_layer(self):
        """Export the currently selected layer"""
        current_row = self._get_active_layer_index()
        if current_row is None:
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
        file_path, filter_text = choose_path(
            self,
            "Export Mask",
            mode="save", default_name=default_name,
            file_filter="PNG Files (*.png);;NumPy Files (*.npy);;TIFF Files (*.tif);;All Files (*)",
            key="mask_save",
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

    def _overlay_mask(self):
        return None

    def _refresh_shared_image_overlays(self, *_args):
        super()._refresh_shared_image_overlays()
        self._refresh_mask_overlay()
    
    def _add_mask_overlay(self, viewer):
        """Render the composed mask, or the temporary in-progress edit."""
        viewer.clear_overlays(group='mask-layers')
        viewer.remove_overlay('edit-preview')
        if not hasattr(self, 'show_mask_check') or not self.show_mask_check.isChecked():
            return
        if self._preview_mask is not None:
            viewer.add_mask_overlay(
                'edit-preview',
                self._preview_mask,
                group='mask-layers',
                color=self.overlay_color,
                alpha=self.overlay_opacity / 100.0,
            )
            return
        if self.combined_mask is not None:
            viewer.add_mask_overlay(
                'combined-mask',
                self.combined_mask,
                group='mask-layers',
                color=self.overlay_color,
                alpha=self.overlay_opacity / 100.0,
            )

    def _refresh_mask_overlay(self):
        """Refresh only the PyQtGraph mask overlay, leaving the detector image untouched."""
        if hasattr(self, 'image_viewer'):
            self._add_mask_overlay(self.image_viewer)
    
