"""Interactive 2D transform tab for SciView."""

from __future__ import annotations

import os
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import yaml
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sciview.session.session_cache import choose_path
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array
from sciview.interfaces.theme.app_style import (
    AppStyle,
    apply_emphasis_button_style,
    apply_info_style,
    apply_protocol_selector_button_style,
    apply_subtitle_style,
    apply_toolbar_text_button_style,
    setup_splitter_layout,
)
from sciview.masking.io import load_mask_file as backend_load_mask_file
from sciview.processing.plot_rendering import (
    TRANSFORM_FIGURE_SIZE,
    create_transform_axes,
    render_transform_plot,
)
from sciview.processing.transform import TransformBackend, TransformRequest, save_transform_result
from sciview.settings.app_settings import SPINBOX_CONFIG
from sciview.settings.plot_style import resolve_plot_style
from sciview.settings.viewer_config import SUPPORTED_IMAGE_COLORMAPS, SUPPORTED_IMAGE_SCALES


def _spin(key):
    mn, mx, default, step, decimals = SPINBOX_CONFIG[key]
    if decimals is None:
        w = QSpinBox(); w.setRange(int(mn), int(mx)); w.setSingleStep(int(step)); w.setValue(int(default))
    else:
        w = QDoubleSpinBox(); w.setRange(mn, mx); w.setDecimals(decimals); w.setSingleStep(step); w.setValue(default)
    return w
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION, get_calibration_class as _get_calibration_class
from tabs.base_image_tab import BaseImageTab


class TransformTab(BaseImageTab):
    """Interactive 2D transform tab with live preview and export."""

    def __init__(self, parent_app):
        super().__init__(parent_app)
        self.backend = TransformBackend()
        self._current_result = None
        self._transform_colorbar = None
        self._q_bounds = {}
        self._custom_calibration = None
        self._custom_calibration_label = "None"
        self._custom_mask = None
        self._custom_mask_label = "None"
        self._building_controls = True
        self._updating_plot_style_controls = False
        self._preview_delay_ms = 450
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self.refresh_preview)
        self._build_ui()
        self._building_controls = False
        self._refresh_payload_view()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        layout_ratios = AppStyle.get_layout_ratios()

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(self._create_transform_panel())

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(self._create_image_panel())
        right_splitter.addWidget(self.make_scrollable_panel(self._create_controls_panel()))
        setup_splitter_layout(right_splitter, layout_ratios['preview_sidebar_ratio'])
        main_splitter.addWidget(right_splitter)

        setup_splitter_layout(main_splitter, [1, 1])
        main_layout.addWidget(main_splitter)

    def _create_transform_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addLayout(self._create_protocol_selector())

        title_row = QHBoxLayout()
        title = QLabel("Transform Preview")
        apply_subtitle_style(title)
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        self.result_summary = QLabel("No preview yet")
        apply_info_style(self.result_summary)
        layout.addWidget(self.result_summary)

        self.fig_transform, self.ax_transform = plt.subplots(
            figsize=TRANSFORM_FIGURE_SIZE,
            layout="constrained",
        )
        self.canvas_transform = FigureCanvas(self.fig_transform)
        layout.addWidget(self.canvas_transform, 1)

        toolbar = NavigationToolbar(self.canvas_transform, self)
        layout.addWidget(toolbar)
        layout.addWidget(self._create_plot_style_group())

        return panel

    def _create_plot_style_group(self):
        style_group = QGroupBox("Plot Style")
        style_layout = QGridLayout(style_group)
        plot_style = resolve_plot_style(self.parent_app)

        self.plot_title_size_spin = QDoubleSpinBox()
        self.plot_label_size_spin = QDoubleSpinBox()
        self.plot_tick_size_spin = QDoubleSpinBox()
        for index, (label, spin, value) in enumerate((
            ("Plot title size", self.plot_title_size_spin, plot_style.title_size),
            ("Axis label size", self.plot_label_size_spin, plot_style.label_size),
            ("Tick label size", self.plot_tick_size_spin, plot_style.tick_size),
        )):
            spin.setRange(6.0, 72.0)
            spin.setValue(value)
            self._add_grid_field(style_layout, 0, index, label, spin)

        self.plot_dpi_spin = QSpinBox()
        self.plot_dpi_spin.setRange(72, 1200)
        self.plot_dpi_spin.setValue(plot_style.dpi)

        display_values = self.get_display_values()
        self.plot_cmap_combo = QComboBox()
        self.plot_cmap_combo.addItems(SUPPORTED_IMAGE_COLORMAPS)
        self.plot_cmap_combo.setCurrentText(plot_style.colormap)
        self.plot_scale_combo = QComboBox()
        self.plot_scale_combo.addItems(SUPPORTED_IMAGE_SCALES)
        self.plot_scale_combo.setCurrentText(display_values["scale"])
        self.color_auto_check = QCheckBox("Auto intensity range")
        self.color_auto_check.setChecked(True)
        self.plot_vmin_spin = QDoubleSpinBox()
        self.plot_vmax_spin = QDoubleSpinBox()
        for spin, value in (
            (self.plot_vmin_spin, display_values["vmin"]),
            (self.plot_vmax_spin, display_values["vmax"]),
        ):
            spin.setRange(-1.0e15, 1.0e15)
            spin.setDecimals(4)
            spin.setValue(0.0 if value is None else value)
            spin.setEnabled(False)
        self._add_grid_field(style_layout, 0, 3, "Export resolution (DPI)", self.plot_dpi_spin)
        self._add_grid_field(style_layout, 1, 0, "Colormap", self.plot_cmap_combo)
        self._add_grid_field(style_layout, 1, 1, "Intensity scale", self.plot_scale_combo)
        self._add_grid_field(style_layout, 1, 2, "Intensity min", self.plot_vmin_spin)
        self._add_grid_field(style_layout, 1, 3, "Intensity max", self.plot_vmax_spin)
        style_layout.addWidget(self.color_auto_check, 2, 0, 1, 2)
        return style_group

    def _create_protocol_selector(self):
        protocol_layout = QGridLayout()
        protocol_label = QLabel("Protocol")
        apply_subtitle_style(protocol_label)
        protocol_layout.addWidget(protocol_label, 0, 0, 1, 3)
        self.protocol_button_group = QButtonGroup(self)
        self.protocol_button_group.setExclusive(True)
        self._operation_buttons = {}
        for index, (operation, label) in enumerate((
            ("q_image", "Q Image"),
            ("q_phi_image", "Q-Phi Image"),
            ("qr_qz_image", "Qr-Qz Image"),
        )):
            button = QPushButton(label)
            apply_protocol_selector_button_style(button)
            self.protocol_button_group.addButton(button)
            self._operation_buttons[operation] = button
            protocol_layout.addWidget(button, 1, index)
        self._operation_buttons["q_image"].setChecked(True)
        for column in range(3):
            protocol_layout.setColumnStretch(column, 1)
        return protocol_layout

    def _create_payload_group(self):
        group = QGroupBox("Recipe")
        layout = QVBoxLayout(group)
        self.payload_view = QTextEdit()
        self.payload_view.setFontFamily("monospace")
        self.payload_view.setMinimumHeight(150)
        layout.addWidget(self.payload_view, 1)
        return group

    def _create_controls_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(*([AppStyle.LAYOUT['panel_inner_margin']] * 4))
        layout.setSpacing(AppStyle.LAYOUT['section_spacing'])

        source_layout = QHBoxLayout()
        source_layout.setSpacing(AppStyle.LAYOUT['section_spacing'])

        self.calibration_source_combo = QComboBox()
        self.calibration_source_combo.addItem("Shared", "From calibration tab")
        self.calibration_source_combo.addItem("Custom", "Custom profile")
        source_layout.addWidget(QLabel("Calibration"))
        source_layout.addWidget(self.calibration_source_combo, 1)
        self.load_calibration_button = QPushButton("Browse")
        self.load_calibration_button.clicked.connect(self._load_custom_calibration)
        apply_toolbar_text_button_style(self.load_calibration_button)
        source_layout.addWidget(self.load_calibration_button)

        self.mask_source_combo = QComboBox()
        self.mask_source_combo.addItem("Shared", "From mask tab")
        self.mask_source_combo.addItem("Custom", "Custom mask")
        self.mask_source_combo.addItem("None", "No mask")
        source_layout.addWidget(QLabel("Mask"))
        source_layout.addWidget(self.mask_source_combo, 1)
        self.load_mask_button = QPushButton("Browse")
        self.load_mask_button.clicked.connect(self._load_custom_mask)
        apply_toolbar_text_button_style(self.load_mask_button)
        source_layout.addWidget(self.load_mask_button)
        layout.addLayout(source_layout)

        self.auto_update_check = QCheckBox("Live preview")
        self.auto_update_check.setChecked(True)
        layout.addWidget(self.auto_update_check)

        self.q_image_group = QGroupBox("Parameters")
        q_image_layout = QGridLayout(self.q_image_group)
        self.q_bins_relative_spin = _spin("bins_relative")
        self._add_grid_field(q_image_layout, 0, 0, "Bins (relative)", self.q_bins_relative_spin)
        self.q_auto_crop_check = QCheckBox("Auto crop to calibration")
        self.q_auto_crop_check.setChecked(True)
        q_image_layout.addWidget(self.q_auto_crop_check, 0, 2, 1, 2)
        self.q_x_min_spin = _spin("crop_min")
        self._add_grid_field(q_image_layout, 1, 0, "q<sub>x</sub> min (Å⁻¹)", self.q_x_min_spin)
        self.q_x_max_spin = _spin("crop_max")
        self._add_grid_field(q_image_layout, 1, 1, "q<sub>x</sub> max (Å⁻¹)", self.q_x_max_spin)
        self.q_y_min_spin = _spin("crop_min")
        self._add_grid_field(q_image_layout, 2, 0, "q<sub>z</sub> min (Å⁻¹)", self.q_y_min_spin)
        self.q_y_max_spin = _spin("crop_max")
        self._add_grid_field(q_image_layout, 2, 1, "q<sub>z</sub> max (Å⁻¹)", self.q_y_max_spin)
        self.q_incident_angle_spin = _spin("incident_angle_deg")
        self.q_incident_angle_spin.setToolTip(
            "Grazing-incidence angle (GISAXS/GIWAXS); 0 for transmission/normal-incidence data"
        )
        self._add_grid_field(q_image_layout, 3, 0, "Incident angle (°)", self.q_incident_angle_spin)
        self.q_sample_normal_spin = _spin("sample_normal_deg")
        self.q_sample_normal_spin.setToolTip("Azimuthal (phi) reference offset for sample-stage misalignment")
        self._add_grid_field(q_image_layout, 3, 1, "Sample normal (°)", self.q_sample_normal_spin)
        layout.addWidget(self.q_image_group)

        self.q_phi_group = QGroupBox("Parameters")
        q_phi_layout = QGridLayout(self.q_phi_group)
        self.qphi_bins_relative_spin = _spin("bins_relative")
        self._add_grid_field(q_phi_layout, 0, 0, "Bins (relative)", self.qphi_bins_relative_spin)
        self.qphi_bins_phi_spin = _spin("bins_phi")
        self._add_grid_field(q_phi_layout, 0, 1, "Phi bins", self.qphi_bins_phi_spin)
        self.qphi_auto_crop_check = QCheckBox("Auto crop to calibration")
        self.qphi_auto_crop_check.setChecked(True)
        q_phi_layout.addWidget(self.qphi_auto_crop_check, 1, 0, 1, 4)
        self.qphi_x_min_spin = _spin("q_min")
        self._add_grid_field(q_phi_layout, 2, 0, "q min (Å⁻¹)", self.qphi_x_min_spin)
        self.qphi_x_max_spin = _spin("q_max")
        self._add_grid_field(q_phi_layout, 2, 1, "q max (Å⁻¹)", self.qphi_x_max_spin)
        self.qphi_y_min_spin = _spin("phi_min")
        self._add_grid_field(q_phi_layout, 3, 0, "Phi min (°)", self.qphi_y_min_spin)
        self.qphi_y_max_spin = _spin("phi_max")
        self._add_grid_field(q_phi_layout, 3, 1, "Phi max (°)", self.qphi_y_max_spin)
        self.qphi_sample_normal_spin = _spin("sample_normal_deg")
        self.qphi_sample_normal_spin.setToolTip("Azimuthal (phi) reference offset for sample-stage misalignment")
        self._add_grid_field(q_phi_layout, 4, 0, "Sample normal (°)", self.qphi_sample_normal_spin)
        layout.addWidget(self.q_phi_group)

        self.qr_qz_group = QGroupBox("Parameters")
        qr_qz_layout = QGridLayout(self.qr_qz_group)
        self.qrqz_bins_relative_spin = _spin("bins_relative")
        self._add_grid_field(qr_qz_layout, 0, 0, "Bins (relative)", self.qrqz_bins_relative_spin)
        self.qrqz_auto_crop_check = QCheckBox("Auto crop to calibration")
        self.qrqz_auto_crop_check.setChecked(True)
        qr_qz_layout.addWidget(self.qrqz_auto_crop_check, 0, 2, 1, 2)
        self.qrqz_x_min_spin = _spin("crop_min")
        self._add_grid_field(qr_qz_layout, 1, 0, "q<sub>r</sub> min (Å⁻¹)", self.qrqz_x_min_spin)
        self.qrqz_x_max_spin = _spin("crop_max")
        self._add_grid_field(qr_qz_layout, 1, 1, "q<sub>r</sub> max (Å⁻¹)", self.qrqz_x_max_spin)
        self.qrqz_y_min_spin = _spin("crop_min")
        self._add_grid_field(qr_qz_layout, 2, 0, "q<sub>z</sub> min (Å⁻¹)", self.qrqz_y_min_spin)
        self.qrqz_y_max_spin = _spin("crop_max")
        self._add_grid_field(qr_qz_layout, 2, 1, "q<sub>z</sub> max (Å⁻¹)", self.qrqz_y_max_spin)
        self.qrqz_incident_angle_spin = _spin("incident_angle_deg")
        self.qrqz_incident_angle_spin.setToolTip(
            "Grazing-incidence angle (GISAXS/GIWAXS); 0 for transmission/normal-incidence data"
        )
        self._add_grid_field(qr_qz_layout, 3, 0, "Incident angle (°)", self.qrqz_incident_angle_spin)
        self.qrqz_sample_normal_spin = _spin("sample_normal_deg")
        self.qrqz_sample_normal_spin.setToolTip("Azimuthal (phi) reference offset for sample-stage misalignment")
        self._add_grid_field(qr_qz_layout, 3, 1, "Sample normal (°)", self.qrqz_sample_normal_spin)
        layout.addWidget(self.qr_qz_group)

        self._operation_groups = {
            "q_image": self.q_image_group,
            "q_phi_image": self.q_phi_group,
            "qr_qz_image": self.qr_qz_group,
        }
        self._operation_labels = {
            "q_image": "Q Image",
            "q_phi_image": "Q-Phi Image",
            "qr_qz_image": "Qr-Qz Image",
        }
        self._operation_param_widgets = {
            "q_image": {
                "bins_relative": self.q_bins_relative_spin,
                "auto_crop": self.q_auto_crop_check,
                "x_min": self.q_x_min_spin,
                "x_max": self.q_x_max_spin,
                "y_min": self.q_y_min_spin,
                "y_max": self.q_y_max_spin,
                "incident_angle_deg": self.q_incident_angle_spin,
                "sample_normal_deg": self.q_sample_normal_spin,
            },
            "q_phi_image": {
                "bins_relative": self.qphi_bins_relative_spin,
                "bins_phi": self.qphi_bins_phi_spin,
                "auto_crop": self.qphi_auto_crop_check,
                "x_min": self.qphi_x_min_spin,
                "x_max": self.qphi_x_max_spin,
                "y_min": self.qphi_y_min_spin,
                "y_max": self.qphi_y_max_spin,
                "sample_normal_deg": self.qphi_sample_normal_spin,
            },
            "qr_qz_image": {
                "bins_relative": self.qrqz_bins_relative_spin,
                "auto_crop": self.qrqz_auto_crop_check,
                "x_min": self.qrqz_x_min_spin,
                "x_max": self.qrqz_x_max_spin,
                "y_min": self.qrqz_y_min_spin,
                "y_max": self.qrqz_y_max_spin,
                "incident_angle_deg": self.qrqz_incident_angle_spin,
                "sample_normal_deg": self.qrqz_sample_normal_spin,
            },
        }
        self._sync_operation_group_visibility()

        layout.addWidget(self._create_payload_group(), 1)

        button_row = QHBoxLayout()
        self.payload_apply_button = QPushButton("Apply YAML")
        self.payload_apply_button.setToolTip("Parse the edited Recipe YAML above and apply it to the controls")
        self.payload_apply_button.clicked.connect(self._apply_payload_edits)
        self.preview_button = QPushButton("Refresh Preview")
        self.preview_button.clicked.connect(self.refresh_preview)
        self.export_button = QPushButton("Export Data")
        self.export_button.clicked.connect(self.export_result)
        self.send_to_batch_button = QPushButton("Send to Batch")
        self.send_to_batch_button.setToolTip("Push current settings as a protocol to the Batch tab")
        self.send_to_batch_button.clicked.connect(self._send_to_batch)
        apply_emphasis_button_style(self.send_to_batch_button)
        button_row.addWidget(self.payload_apply_button)
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.send_to_batch_button)
        layout.addLayout(button_row)

        for operation, button in self._operation_buttons.items():
            button.toggled.connect(lambda checked, op=operation: self._on_protocol_changed(op, checked))

        self.auto_update_check.stateChanged.connect(self._on_parameters_changed)
        self.color_auto_check.stateChanged.connect(self._on_parameters_changed)
        self.plot_cmap_combo.currentTextChanged.connect(self._on_plot_style_controls_changed)
        self.plot_scale_combo.currentTextChanged.connect(self._on_plot_style_controls_changed)
        for spin in (
            self.plot_title_size_spin,
            self.plot_label_size_spin,
            self.plot_tick_size_spin,
            self.plot_dpi_spin,
            self.plot_vmin_spin,
            self.plot_vmax_spin,
        ):
            spin.valueChanged.connect(self._on_plot_style_controls_changed)
        for widgets in self._operation_param_widgets.values():
            for widget in widgets.values():
                if hasattr(widget, "stateChanged"):
                    widget.stateChanged.connect(self._on_parameters_changed)
                elif hasattr(widget, "valueChanged"):
                    widget.valueChanged.connect(self._on_parameters_changed)

        self.calibration_source_combo.currentTextChanged.connect(self._on_source_changed)
        self.mask_source_combo.currentTextChanged.connect(self._on_source_changed)

        self._on_parameters_changed()
        self._refresh_source_status()
        return panel

    def _on_plot_style_controls_changed(self, *args) -> None:
        if self._building_controls or self._updating_plot_style_controls:
            return
        try:
            style = replace(
                resolve_plot_style(self.parent_app),
                title_size=self.plot_title_size_spin.value(),
                label_size=self.plot_label_size_spin.value(),
                tick_size=self.plot_tick_size_spin.value(),
                colormap=self.plot_cmap_combo.currentText(),
                dpi=self.plot_dpi_spin.value(),
            )
        except ValueError as exc:
            self.parent_app.show_status(f"Invalid plot style: {exc}")
            return
        self.parent_app.publish_shared_plot_style(style, source_tab=self)
        self._update_transform_plot(self._current_result)
        self._refresh_payload_view()

    def _sync_plot_style_controls(self) -> None:
        style = resolve_plot_style(self.parent_app)
        self._updating_plot_style_controls = True
        try:
            self.plot_title_size_spin.setValue(style.title_size)
            self.plot_label_size_spin.setValue(style.label_size)
            self.plot_tick_size_spin.setValue(style.tick_size)
            self.plot_cmap_combo.setCurrentText(style.colormap)
            self.plot_dpi_spin.setValue(style.dpi)
        finally:
            self._updating_plot_style_controls = False

    @staticmethod
    def _add_grid_field(grid: QGridLayout, row: int, col: int, label_text: str, widget: QWidget) -> None:
        """Place a label+field pair in a 2-column QGridLayout (each column uses 2 grid columns)."""
        grid.addWidget(QLabel(label_text), row, col * 2)
        grid.addWidget(widget, row, col * 2 + 1)

    def _on_source_changed(self, _text: str):
        self._refresh_source_status()
        self._on_parameters_changed()

    def _on_protocol_changed(self, operation: str, checked: bool):
        if self._building_controls or not checked:
            return
        self._sync_operation_group_visibility()
        self._on_parameters_changed()

    def _sync_operation_group_visibility(self):
        selected_operation = self._selected_operation()
        for operation, group in self._operation_groups.items():
            group.setVisible(operation == selected_operation)

    def _on_parameters_changed(self, *args):
        if self._building_controls:
            return
        self.plot_vmin_spin.setEnabled(not self.color_auto_check.isChecked())
        self.plot_vmax_spin.setEnabled(not self.color_auto_check.isChecked())
        for operation, widgets in self._operation_param_widgets.items():
            auto_check = widgets.get("auto_crop")
            if auto_check is None:
                continue
            manual_crop = not auto_check.isChecked()
            # Auto crop only covers axes SciAnalysis derives from calibration:
            # both axes for Q Image/Qr-Qz Image, only x (q) for Q-Phi Image —
            # phi (y) is always independently editable since SciAnalysis fixes
            # it at -180/180 by default rather than deriving it from calibration.
            keys = ("x_min", "x_max") if operation == "q_phi_image" else ("x_min", "x_max", "y_min", "y_max")
            for key in keys:
                widget = widgets.get(key)
                if widget is not None:
                    widget.setEnabled(manual_crop)
        self._refresh_payload_view()
        self.update_plot(schedule_preview=True)

    def _selected_operation(self):
        for operation, button in self._operation_buttons.items():
            if button.isChecked():
                return operation
        return "q_image"

    def _op_widget(self, key):
        return self._operation_param_widgets.get(self._selected_operation(), {}).get(key)

    def _op_bool(self, key, default=False):
        widget = self._op_widget(key)
        return widget.isChecked() if widget is not None else default

    def _op_int(self, key, default=0):
        widget = self._op_widget(key)
        return int(widget.value()) if widget is not None else default

    def _op_float(self, key, default=None):
        widget = self._op_widget(key)
        return float(widget.value()) if widget is not None else default

    def _use_mask_enabled(self):
        return self.mask_source_combo.currentData() != "No mask"

    def _resolved_calibration(self):
        """Return the active calibration with this operation's incident-angle /
        sample-normal overrides applied (GISAXS/GIWAXS), without mutating the shared
        calibration."""
        calibration = self._selected_calibration()
        incident_widget = self._op_widget("incident_angle_deg")
        sample_normal_widget = self._op_widget("sample_normal_deg")
        if calibration is None or (incident_widget is None and sample_normal_widget is None):
            return calibration
        from sciview.processing.batch import clone_calibration_with_angles
        return clone_calibration_with_angles(
            calibration,
            incident_angle_deg=incident_widget.value() if incident_widget is not None else None,
            sample_normal_deg=sample_normal_widget.value() if sample_normal_widget is not None else None,
        )

    def _selected_calibration(self):
        if self.calibration_source_combo.currentData() == "Custom profile":
            return self._custom_calibration
        if hasattr(self.parent_app, "get_shared_calibration"):
            return self.parent_app.get_shared_calibration(self.image_data)
        return getattr(self.parent_app, "calibration", None)

    def _selected_mask(self):
        mode = self.mask_source_combo.currentData()
        if mode == "No mask":
            return None
        if mode == "Custom mask":
            return self._custom_mask
        if hasattr(self.parent_app, "get_shared_mask"):
            shared_mask = self.parent_app.get_shared_mask()
            if shared_mask is not None:
                return shared_mask
        return getattr(self.parent_app, "mask", getattr(self.parent_app, "current_mask", None))

    def _load_custom_calibration(self):
        file_path, _ = choose_path(
            self,
            "Load Calibration YAML",
            file_filter="YAML files (*.yaml *.yml);;All files (*)",
            key="transform_calibration_open",
        )
        if not file_path:
            return

        try:
            payload = yaml.safe_load(open(file_path, "r", encoding="utf-8")) or {}
            calibration_cls = _get_calibration_class()
            if calibration_cls is None:
                raise RuntimeError("SciAnalysis calibration class not available")

            calibration = calibration_cls(wavelength_A=float(payload.get("wavelength_A", DEFAULT_CALIBRATION["wavelength_A"])))
            image_size = payload.get("image_size")
            if image_size and len(image_size) >= 2:
                calibration.set_image_size(int(image_size[0]), height=int(image_size[1]))
            calibration.set_pixel_size(pixel_size_um=float(payload.get("pixel_size_um", DEFAULT_CALIBRATION["pixel_size_um"])))
            beam = payload.get("beam_position", [DEFAULT_CALIBRATION["beam_center_x"], DEFAULT_CALIBRATION["beam_center_y"]])
            calibration.set_beam_position(float(beam[0]), float(beam[1]))
            calibration.set_distance(float(payload.get("distance", DEFAULT_CALIBRATION["distance_m"])))

            self._custom_calibration = calibration
            self._custom_calibration_label = os.path.basename(file_path)
            self.calibration_source_combo.setCurrentIndex(self.calibration_source_combo.findData("Custom profile"))
            self._refresh_source_status()
            self.parent_app.show_status(f"Loaded custom calibration: {self._custom_calibration_label}")
            self._on_parameters_changed()
        except Exception as exc:
            self.parent_app.show_status(f"Failed to load custom calibration: {exc}")

    def _load_custom_mask(self):
        file_path, _ = choose_path(
            self,
            "Load Mask",
            file_filter="Mask files (*.png *.tif *.tiff *.npy);;All files (*)",
            key="transform_mask_open",
        )
        if not file_path:
            return

        try:
            self._custom_mask = backend_load_mask_file(file_path)
            self._custom_mask_label = os.path.basename(file_path)
            self.mask_source_combo.setCurrentIndex(self.mask_source_combo.findData("Custom mask"))
            self._refresh_source_status()
            self.parent_app.show_status(f"Loaded custom mask: {self._custom_mask_label}")
            self._on_parameters_changed()
        except Exception as exc:
            self.parent_app.show_status(f"Failed to load custom mask: {exc}")

    def _refresh_source_status(self):
        if hasattr(self.parent_app, "get_shared_calibration"):
            shared_cal = self.parent_app.get_shared_calibration(self.image_data)
        else:
            shared_cal = getattr(self.parent_app, "calibration", None)
        cal = self._selected_calibration()
        mask = self._selected_mask()

        if self.calibration_source_combo.currentData() == "Custom profile":
            cal_text = f"Calibration: custom ({self._custom_calibration_label})"
        elif shared_cal is None:
            cal_text = "Calibration: from calibration tab (not loaded)"
        else:
            cal_text = "Calibration: from calibration tab"

        if self.mask_source_combo.currentData() == "No mask":
            mask_text = "Mask: disabled"
        elif self.mask_source_combo.currentData() == "Custom mask":
            mask_text = f"Mask: custom ({self._custom_mask_label})"
        else:
            mask_text = "Mask: from mask tab" if mask is not None else "Mask: from mask tab (not loaded)"

        self.calibration_source_combo.setToolTip(cal_text)
        self.mask_source_combo.setToolTip(mask_text)
        self.load_calibration_button.setVisible(self.calibration_source_combo.currentData() == "Custom profile")
        self.load_mask_button.setVisible(self.mask_source_combo.currentData() == "Custom mask")

        if cal is None:
            self.result_summary.setText("Calibration required")

    def _get_image_array(self):
        display_data = self.image_data if self.image_data is not None else getattr(self.parent_app, "image_data", None)
        if display_data is None:
            return None

        img_array, is_valid, error_msg = validate_and_prepare_image_array(display_data, use_converter=True)
        if not is_valid:
            self.parent_app.show_status(error_msg or "Unable to prepare image array for transform")
            return None

        array = np.asarray(img_array)
        if array.ndim != 2:
            self.parent_app.show_status(f"Transform requires 2D image data (got {array.ndim}D)")
            return None
        return array

    def _get_mask_array(self, shape: tuple[int, int]):
        from sciview.masking.io import coerce_mask_to_bool
        raw = self._selected_mask()
        result = coerce_mask_to_bool(raw, shape)
        if result is None and raw is not None:
            self.parent_app.show_status("Mask shape does not match the active image; ignoring mask for preview")
        return result

    def _compute_q_bounds(self, image_shape: tuple[int, int]):
        from sciview.processing.batch import compute_q_bounds
        mask = self._get_mask_array(image_shape) if self._use_mask_enabled() else None
        self._q_bounds = compute_q_bounds(self._resolved_calibration(), mask)

    def _refresh_auto_q_range(self):
        """Fill each operation's own crop fields from calibration bounds, for
        whichever operations have "Auto crop" checked. Bounds keys differ per
        operation's real axes (see sciview.processing.batch.compute_q_bounds);
        Q-Phi Image's phi (y) axis has no calibration-derived bound, matching
        SciAnalysis's own hardcoded -180/180 default.
        """
        if not self._q_bounds:
            return
        bounds_keys_by_operation = {
            "q_image": {"x_min": "qx_min", "x_max": "qx_max", "y_min": "qz_min", "y_max": "qz_max"},
            "q_phi_image": {"x_min": "q_min", "x_max": "q_max"},
            "qr_qz_image": {"x_min": "qr_min", "x_max": "qr_max", "y_min": "qz_min", "y_max": "qz_max"},
        }
        for operation, widgets in self._operation_param_widgets.items():
            auto_check = widgets.get("auto_crop")
            if auto_check is None or not auto_check.isChecked():
                continue
            for widget_key, bounds_key in bounds_keys_by_operation.get(operation, {}).items():
                widget = widgets.get(widget_key)
                bound_value = self._q_bounds.get(bounds_key)
                if widget is None or bound_value is None:
                    continue
                widget.blockSignals(True)
                widget.setValue(bound_value)
                widget.blockSignals(False)

    def _build_request(self):
        image = self._get_image_array()
        if image is None:
            return None

        calibration = self._resolved_calibration()
        if calibration is None:
            self.parent_app.show_status("Load calibration before running transform")
            return None

        request = TransformRequest(
            image=image,
            operation=self._selected_operation(),
            calibration=calibration,
            mask=self._get_mask_array(image.shape),
            use_mask=self._use_mask_enabled(),
            bins_relative=self._op_float("bins_relative", 1.0),
            bins_phi=self._op_int("bins_phi", 360),
            x_min=self._op_float("x_min"),
            x_max=self._op_float("x_max"),
            y_min=self._op_float("y_min"),
            y_max=self._op_float("y_max"),
            metadata={
                "image_shape": tuple(int(v) for v in image.shape),
                "source_path": self.parent_app.get_image_path() if hasattr(self.parent_app, "get_image_path") else None,
                "calibration_source": self.calibration_source_combo.currentData(),
                "mask_source": self.mask_source_combo.currentData(),
                "q_bounds": dict(self._q_bounds),
            },
        )
        return request

    def refresh_preview(self):
        request = self._build_request()
        if request is None:
            self.result_summary.setText("No image/calibration available")
            self._update_transform_plot(None, message="Load an image and calibration first")
            return

        try:
            result = self.backend.run(request)
        except Exception as exc:
            self._current_result = None
            self._update_transform_plot(None, message=f"Preview failed: {exc}")
            self.result_summary.setText(f"Preview failed: {exc}")
            self.parent_app.show_status(f"Transform failed: {exc}")
            return

        self._current_result = result
        try:
            self._update_transform_plot(result)
        except Exception as exc:
            # Don't leave the status stuck on "Preview pending..." if rendering itself fails.
            self.result_summary.setText(f"Preview failed: {exc}")
            self.parent_app.show_status(f"Transform failed: {exc}")
            return
        result_size = f"{result.image.shape[1]}x{result.image.shape[0]}"
        operation_name = result.operation.replace('_', ' ').title()
        self.result_summary.setText(f"{operation_name}: {result_size}")
        self.parent_app.show_status(f"{operation_name} complete: {result_size}")

    def _update_transform_plot(self, result, message: str | None = None):
        self.ax_transform, self._transform_colorbar_axis = create_transform_axes(self.fig_transform)
        self._transform_colorbar = None
        plot_style = resolve_plot_style(self.parent_app)
        preview_sizes = plot_style.preview_sizes()
        body_font = preview_sizes["title"]
        caption_font = preview_sizes["label"]
        small_font = preview_sizes["tick"]

        if result is None:
            self._transform_colorbar_axis.set_axis_off()
            self.ax_transform.text(
                0.5,
                0.5,
                message or "No transform preview\n\nLoad an image and run preview.",
                transform=self.ax_transform.transAxes,
                ha="center",
                va="center",
                fontsize=body_font,
            )
            self.ax_transform.set_axis_off()
            AppStyle.apply_matplotlib_figure_theme(self.fig_transform)
            self.canvas_transform.draw()
            return

        scale = self.plot_scale_combo.currentText()
        x_min = self._op_float("x_min")
        x_max = self._op_float("x_max")
        y_min = self._op_float("y_min")
        y_max = self._op_float("y_max")
        x_limits = (x_min, x_max) if x_min is not None and x_max is not None else None
        y_limits = (y_min, y_max) if y_min is not None and y_max is not None else None
        theme = {key: value.name() for key, value in AppStyle.theme_colors().items()}
        self._transform_colorbar = render_transform_plot(
            self.fig_transform,
            self.ax_transform,
            result,
            plot_style,
            colorbar_axis=self._transform_colorbar_axis,
            scale=scale,
            vmin=self.plot_vmin_spin.value(),
            vmax=self.plot_vmax_spin.value(),
            x_limits=x_limits,
            y_limits=y_limits,
            theme=theme,
        )
        self.canvas_transform.draw()

    def on_plot_style_changed(self):
        """Redraw the current transform result with the shared plot style."""
        self._sync_plot_style_controls()
        self._update_transform_plot(self._current_result)

    def _apply_display_crop(self):
        """Crop the plot axes to the selected operation's display-only x/y
        range, matching SciAnalysis's own universal
        plot_range=[x_min, x_max, y_min, y_max] convention (Data2D.plot()) —
        remesh_* always covers the full calibration extent regardless."""
        x_min = self._op_float("x_min")
        x_max = self._op_float("x_max")
        if x_min is not None and x_max is not None:
            self.ax_transform.set_xlim(x_min, x_max)
        y_min = self._op_float("y_min")
        y_max = self._op_float("y_max")
        if y_min is not None and y_max is not None:
            self.ax_transform.set_ylim(y_min, y_max)

    def export_result(self):
        if self._current_result is None:
            self.parent_app.show_status("Run preview before export")
            return

        default_name = "transform_output.npz"
        if hasattr(self.parent_app, "get_image_path") and self.parent_app.get_image_path():
            base = os.path.splitext(os.path.basename(self.parent_app.get_image_path()))[0]
            default_name = f"{base}_{self._current_result.operation}.npz"

        file_path, _ = choose_path(
            self,
            "Export transformed image",
            mode="save", default_name=default_name,
            file_filter="NumPy zipped (*.npz);;NumPy array (*.npy);;All files (*)",
            key="transform_export",
        )
        if not file_path:
            return

        written_path = save_transform_result(self._current_result, file_path)
        self.parent_app.show_status(f"Transformed image exported to {written_path}")

    def _xy_plot_bounds(self):
        """x/y (or x/phi) bounds to send: None (native SciAnalysis autoscale)
        while "Auto crop to calibration" is checked, else the exact typed
        values — same auto-vs-explicit rule as Reduction tab's q_min/q_max.
        q_phi_image is exempt on y: phi is always explicit, never
        calibration-derived (see _on_parameters_changed)."""
        auto = self._op_bool("auto_crop", True)
        x_min = None if auto else self._op_float("x_min")
        x_max = None if auto else self._op_float("x_max")
        if self._selected_operation() == "q_phi_image":
            return x_min, x_max, self._op_float("y_min", -180.0), self._op_float("y_max", 180.0)
        y_min = None if auto else self._op_float("y_min")
        y_max = None if auto else self._op_float("y_max")
        return x_min, x_max, y_min, y_max

    def _build_batch_payload(self) -> dict:
        """Build SA-compatible protocol recipe for push to batch.

        x_min/x_max/y_min/y_max (phi_min/phi_max for q_phi_image) are set here
        from this tab's own crop controls — None while "Auto crop to
        calibration" is checked (so SciAnalysis's own calibration-derived
        plot_range applies per file, matching per-file calibration in a
        batch), or the exact typed values once the user overrides it manually
        (see transform_canonical_to_scianalysis_kwargs, which assembles the
        final plot_range and is the only place that conversion happens).
        zmin/zmax mirror the Intensity min/max controls exactly (None while
        "Auto intensity range" is checked, so SciAnalysis's own ztrim-based
        auto-scaling applies) — these are real, honored SciAnalysis kwargs,
        unlike the log/linear scale mode (hardcoded to 'gamma' inside
        SciAnalysis's own q_image/qr_image/q_phi_image protocols).
        """
        op   = self._selected_operation()
        name = self._operation_labels[op]
        bins_relative = self._op_float("bins_relative", 1.0)
        transform_method = None
        if self._current_result is not None and self._current_result.operation == op:
            transform_method = getattr(self._current_result, "metadata", {}).get("method")
        auto_intensity = self.color_auto_check.isChecked()
        zmin = None if auto_intensity else self.plot_vmin_spin.value()
        zmax = None if auto_intensity else self.plot_vmax_spin.value()
        x_min, x_max, y_min, y_max = self._xy_plot_bounds()
        preview = {
            "scale": self.plot_scale_combo.currentText(),
            "vmin": self.plot_vmin_spin.value(),
            "vmax": self.plot_vmax_spin.value(),
            "transform_method": transform_method,
            "x_min": self._op_float("x_min"),
            "x_max": self._op_float("x_max"),
            "y_min": self._op_float("y_min"),
            "y_max": self._op_float("y_max"),
        }

        if op == "q_image":
            return {
                "operation": op, "name": name, "bins_relative": bins_relative,
                "zmin": zmin, "zmax": zmax,
                "x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max,
                "incident_angle_deg": self._op_float("incident_angle_deg", 0.0),
                "sample_normal_deg": self._op_float("sample_normal_deg", 0.0),
                "preview_params": preview, "save_results": ["plots", "npz"],
            }

        if op == "q_phi_image":
            return {
                "operation": op, "name": name,
                "bins_relative": bins_relative,
                "bins_phi": self._op_int("bins_phi", 360),
                "zmin": zmin, "zmax": zmax,
                "x_min": x_min, "x_max": x_max,
                "phi_min": y_min, "phi_max": y_max,
                "sample_normal_deg": self._op_float("sample_normal_deg", 0.0),
                "preview_params": preview,
                "save_results": ["plots", "npz"],
            }

        if op == "qr_qz_image":
            return {
                "operation": op, "name": name,
                "bins_relative": bins_relative,
                "zmin": zmin, "zmax": zmax,
                "x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max,
                "incident_angle_deg": self._op_float("incident_angle_deg", 0.0),
                "sample_normal_deg": self._op_float("sample_normal_deg", 0.0),
                "preview_params": preview,
                "save_results": ["plots", "npz"],
            }

        return {"operation": op, "name": name, "save_results": ["plots", "npz"]}

    def _build_recipe_payload(self) -> dict:
        """Full recipe for Export Recipe: SA-compatible params + context metadata."""
        return {
            **self._build_batch_payload(),
            "q_bounds": dict(self._q_bounds),
            "calibration_source": self.calibration_source_combo.currentData(),
            "mask_source": self.mask_source_combo.currentData(),
            "source_path": self.parent_app.get_image_path() if hasattr(self.parent_app, "get_image_path") else None,
        }

    def _build_payload_preview(self) -> dict:
        """Curated view shown in the YAML payload box: the batch payload plus
        calibration/mask context, minus preview_params entries that duplicate
        a top-level field already shown (vmin/vmax duplicate zmin/zmax;
        x_min/x_max duplicate the top-level crop; y_min/y_max duplicate
        phi_min/phi_max for q_phi_image). scale and transform_method have no
        top-level equivalent and stay, since Batch's WYSIWYG match-preview
        genuinely needs them."""
        payload = {
            **self._build_batch_payload(),
            "calibration_source": self.calibration_source_combo.currentData(),
            "mask_source": self.mask_source_combo.currentData(),
        }
        preview = payload.get("preview_params", {})
        preview.pop("vmin", None)
        preview.pop("vmax", None)
        preview.pop("x_min", None)
        preview.pop("x_max", None)
        preview.pop("y_min", None)
        preview.pop("y_max", None)
        return payload

    def _refresh_payload_view(self) -> None:
        if not hasattr(self, "payload_view") or self.payload_view.hasFocus():
            return
        text = "# Recipe sent to Batch tab\n" + yaml.safe_dump(
            self._build_payload_preview(), sort_keys=False, default_flow_style=False
        )
        self.payload_view.setPlainText(text)

    def _apply_payload_edits(self) -> None:
        try:
            data = yaml.safe_load(self.payload_view.toPlainText()) or {}
        except yaml.YAMLError as exc:
            self.parent_app.show_status(f"Invalid YAML: {exc}")
            return
        if not isinstance(data, dict):
            self.parent_app.show_status("Invalid recipe: expected a YAML mapping")
            return

        operation = data.get("operation")
        if operation in self._operation_buttons:
            self._operation_buttons[operation].setChecked(True)

        widgets = self._operation_param_widgets.get(self._selected_operation(), {})

        def _set(key, value):
            widget = widgets.get(key)
            if widget is not None and value is not None:
                widget.blockSignals(True)
                widget.setValue(float(value))
                widget.blockSignals(False)

        _set("bins_relative", data.get("bins_relative"))
        _set("bins_phi", data.get("bins_phi"))
        _set("incident_angle_deg", data.get("incident_angle_deg"))
        _set("sample_normal_deg", data.get("sample_normal_deg"))

        auto_crop = widgets.get("auto_crop")
        x_min, x_max = data.get("x_min"), data.get("x_max")
        if "x_min" in data or "x_max" in data:
            if x_min is None and x_max is None:
                if auto_crop is not None:
                    auto_crop.setChecked(True)
            else:
                if auto_crop is not None:
                    auto_crop.setChecked(False)
                _set("x_min", x_min)
                _set("x_max", x_max)

        if self._selected_operation() == "q_phi_image":
            _set("y_min", data.get("phi_min"))
            _set("y_max", data.get("phi_max"))
        else:
            y_min, y_max = data.get("y_min"), data.get("y_max")
            if "y_min" in data or "y_max" in data:
                if y_min is not None or y_max is not None:
                    _set("y_min", y_min)
                    _set("y_max", y_max)

        if "zmin" in data or "zmax" in data:
            zmin, zmax = data.get("zmin"), data.get("zmax")
            if zmin is None and zmax is None:
                self.color_auto_check.setChecked(True)
            else:
                self.color_auto_check.setChecked(False)
                if zmin is not None:
                    self.plot_vmin_spin.setValue(float(zmin))
                if zmax is not None:
                    self.plot_vmax_spin.setValue(float(zmax))

        preview = data.get("preview_params", {})
        scale = preview.get("scale")
        if scale:
            self.plot_scale_combo.setCurrentText(str(scale))

        self._on_parameters_changed()
        self.parent_app.show_status("Recipe applied from YAML")

    def _send_to_batch(self):
        payload = self._build_batch_payload()
        if hasattr(self.parent_app, "push_recipe_to_batch"):
            self.parent_app.push_recipe_to_batch(payload, source="transform_tab")
        else:
            self.parent_app.show_status("Batch tab not available")

    def _schedule_preview(self):
        self.result_summary.setText("Preview pending...")
        self._preview_timer.start(self._preview_delay_ms)

    def update_plot(self, image_data=None, schedule_preview: bool = False):
        display_data = image_data if image_data is not None else self.image_data
        if display_data is None and hasattr(self.parent_app, "image_data"):
            display_data = self.parent_app.image_data

        if display_data is None:
            self._current_result = None
            self._update_transform_plot(None)
            return

        self.image_data = display_data
        image_array, is_valid, error_msg = validate_and_prepare_image_array(display_data, use_converter=True)
        if not is_valid:
            self.result_summary.setText(error_msg or "Unable to update transform display")
            self.parent_app.show_status(error_msg or "Unable to update transform display")
            return

        self.result_summary.setText(f"Image loaded: {image_array.shape[1]}x{image_array.shape[0]}")

        self._compute_q_bounds(image_array.shape)
        self._refresh_auto_q_range()
        self._refresh_source_status()
        super().update_plot(display_data)

        if self.auto_update_check.isChecked():
            if schedule_preview:
                self._schedule_preview()
            else:
                self.refresh_preview()

    def on_shared_state_activated(self):
        """Refresh transform state when shared image/calibration/mask becomes active."""
        self.update_plot()

    def _add_tab_specific_status(self, info_lines):
        info_lines.append("")
        info_lines.append("=== TRANSFORM STATUS ===")
        info_lines.append(f"Operation: {self._operation_labels[self._selected_operation()]}")
        info_lines.append(f"Mask enabled: {'Yes' if self._use_mask_enabled() else 'No'}")
        bins_relative = self._op_float("bins_relative")
        if bins_relative is not None:
            info_lines.append(f"Bins (relative): {bins_relative:.2f}")
        x_min = self._op_float("x_min")
        x_max = self._op_float("x_max")
        if x_min is not None and x_max is not None:
            info_lines.append(f"x crop: {x_min:.4f} to {x_max:.4f}")
        y_min = self._op_float("y_min")
        y_max = self._op_float("y_max")
        if y_min is not None and y_max is not None:
            info_lines.append(f"y crop: {y_min:.4f} to {y_max:.4f}")
        incident_angle = self._op_float("incident_angle_deg")
        if incident_angle is not None:
            info_lines.append(f"Incident angle: {incident_angle:.3f} deg")
        sample_normal = self._op_float("sample_normal_deg")
        if sample_normal is not None:
            info_lines.append(f"Sample normal: {sample_normal:.3f} deg")
        info_lines.append(f"Calibration source: {self.calibration_source_combo.currentData()}")
        info_lines.append(f"Mask source: {self.mask_source_combo.currentData()}")
        if self._current_result is not None:
            info_lines.append(f"Last preview: {self._current_result.operation}")
            info_lines.append(
                f"Preview shape: {self._current_result.image.shape[1]}x{self._current_result.image.shape[0]}"
            )
        else:
            info_lines.append("Last preview: None")
