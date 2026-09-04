"""Interactive 2D reduction tab for SciView."""

from __future__ import annotations

import json
from importlib import import_module
import os
from pathlib import Path

import numpy as np
import yaml

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from sciview.interfaces.stable_qt.utils.file_dialog_state import dialog_open_file, dialog_save_file
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array
from sciview.interfaces.stable_qt.utils.reduction_overlay import (
    OVERLAY_STYLE,
    chi_q_to_pixel,
    chi_convention_text,
    chi_to_screen_vector,
    line_q_roi_mask,
    sector_roi_mask,
)
from sciview.interfaces.theme.app_style import (
    AppStyle,
    apply_info_style,
    apply_subtitle_style,
    apply_title_style,
    setup_splitter_layout,
)
from sciview.masking.io import load_mask_file as backend_load_mask_file
from sciview.processing.angle_conventions import display_chi_to_scianalysis_sector_chi
from sciview.processing.reduction import ReductionBackend, ReductionRequest, save_reduction_result
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION, get_calibration_class as _get_calibration_class
from sciview.settings.app_settings import SPINBOX_CONFIG
from tabs.base_image_tab import BaseImageTab


def _spin(key):
    mn, mx, default, step, decimals = SPINBOX_CONFIG[key]
    if decimals is None:
        w = QSpinBox(); w.setRange(int(mn), int(mx)); w.setSingleStep(int(step)); w.setValue(int(default))
    else:
        w = QDoubleSpinBox(); w.setRange(mn, mx); w.setDecimals(decimals); w.setSingleStep(step); w.setValue(default)
    return w


class ReductionTab(BaseImageTab):
    """Interactive reduction tab with live preview and export."""

    def __init__(self, parent_app):
        super().__init__(parent_app)
        self.backend = ReductionBackend()
        self._current_result = None
        self._overlay_artists = []
        self._q_bounds = {}
        self._last_control_shape = None
        self._custom_calibration = None
        self._custom_calibration_label = "None"
        self._custom_mask = None
        self._custom_mask_label = "None"
        self._building_controls = True
        self._build_ui()
        self._building_controls = False
        self.add_display_hook(self._draw_reduction_overlay, "post")

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        layout_ratios = AppStyle.get_layout_ratios()

        main_splitter = QSplitter(Qt.Horizontal)

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(self._create_image_panel())
        left_splitter.addWidget(self._create_preview_panel())
        setup_splitter_layout(left_splitter, layout_ratios['viz_splitter_ratio'])
        main_splitter.addWidget(left_splitter)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(*([AppStyle.LAYOUT['panel_inner_margin']] * 4))
        right_layout.setSpacing(AppStyle.LAYOUT['section_spacing'])
        right_layout.addWidget(self.make_scrollable_panel(self._create_controls_panel()))
        main_splitter.addWidget(right_panel)

        setup_splitter_layout(main_splitter, layout_ratios['main_splitter_ratio'])
        main_layout.addWidget(main_splitter)

        self.canvas_plot.mpl_connect("motion_notify_event", self.on_mouse_move)

    def _create_preview_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_row = QHBoxLayout()
        title = QLabel("Reduction Preview")
        apply_subtitle_style(title)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(QLabel("Scale"))
        self.plot_scale_combo = QComboBox()
        self.plot_scale_combo.addItems(["linear", "logx", "logy", "loglog"])
        self.plot_scale_combo.currentTextChanged.connect(self._on_parameters_changed)
        self.plot_scale_combo.setMaximumWidth(90)
        title_row.addWidget(self.plot_scale_combo)
        layout.addLayout(title_row)

        self.result_summary = QLabel("No preview yet")
        apply_info_style(self.result_summary)
        layout.addWidget(self.result_summary)

        self.fig_plot, self.ax_plot = plt.subplots(figsize=(6, 4))
        self.fig_plot.subplots_adjust(left=0.10, bottom=0.18, right=0.98, top=0.95)
        self.canvas_plot = FigureCanvas(self.fig_plot)
        layout.addWidget(self.canvas_plot)

        toolbar = NavigationToolbar(self.canvas_plot, self)
        # toolbar.setMaximumHeight(25)
        layout.addWidget(toolbar)

        return panel

    def _create_controls_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(*([AppStyle.LAYOUT['panel_inner_margin']] * 4))
        layout.setSpacing(AppStyle.LAYOUT['section_spacing'])

        title = QLabel("Controls")
        apply_title_style(title)
        layout.addWidget(title)

        source_group = QGroupBox("Sources")
        source_layout = QFormLayout(source_group)
        self.configure_adaptive_form_layout(source_layout)

        self.calibration_source_combo = QComboBox()
        self.calibration_source_combo.addItems(["From calibration tab", "Custom profile"])
        cal_row_widget = QWidget()
        cal_btn_row = QHBoxLayout(cal_row_widget)
        cal_btn_row.setContentsMargins(0, 0, 0, 0)
        cal_btn_row.setSpacing(AppStyle.LAYOUT['section_spacing'])
        cal_btn_row.addWidget(self.calibration_source_combo, stretch=1)
        self.load_calibration_button = QPushButton("Load Calibration")
        self.load_calibration_button.clicked.connect(self._load_custom_calibration)
        cal_btn_row.addWidget(self.load_calibration_button)
        source_layout.addRow("Calibration", cal_row_widget)

        self.mask_source_combo = QComboBox()
        self.mask_source_combo.addItems(["From mask tab", "Custom mask", "No mask"])
        mask_row_widget = QWidget()
        mask_btn_row = QHBoxLayout(mask_row_widget)
        mask_btn_row.setContentsMargins(0, 0, 0, 0)
        mask_btn_row.setSpacing(AppStyle.LAYOUT['section_spacing'])
        mask_btn_row.addWidget(self.mask_source_combo, stretch=1)
        self.load_mask_button = QPushButton("Load Mask")
        self.load_mask_button.clicked.connect(self._load_custom_mask)
        mask_btn_row.addWidget(self.load_mask_button)
        source_layout.addRow("Mask", mask_row_widget)

        self.calibration_status_label = QLabel("Calibration: from calibration tab")
        apply_info_style(self.calibration_status_label)
        source_layout.addRow(self.calibration_status_label)

        self.mask_status_label = QLabel("Mask: from mask tab")
        apply_info_style(self.mask_status_label)
        source_layout.addRow(self.mask_status_label)

        layout.addWidget(source_group)

        common_group = QGroupBox("Common")
        common_layout = QFormLayout(common_group)
        self.configure_adaptive_form_layout(common_layout)
        common_layout.setLabelAlignment(Qt.AlignRight)

        self.auto_update_check = QCheckBox("Auto preview")
        self.auto_update_check.setChecked(True)
        common_layout.addRow(self.auto_update_check)
        layout.addWidget(common_group)

        # Each operation is its own checkable group with its own parameter
        # space, so every option is visible up front instead of hidden behind
        # a dropdown (matching the Transform tab's convention). Checking a
        # group selects it; the others gray out (but stay visible) via Qt's
        # native checkable-groupbox behavior.
        #
        # q min/max are display-only crops applied to the preview plot's x
        # axis (see _apply_display_crop), matching SciAnalysis's own
        # plot_range convention used by batch processing
        # (apply_q_bounds_to_protocol) for these operations — they are never
        # sent to SciAnalysis itself (circular_average_q_bin/sector_average_q_bin
        # always cover the full calibration q range).
        self.circular_group = QGroupBox("Circular Average")
        self.circular_group.setCheckable(True)
        circular_layout = QGridLayout(self.circular_group)
        self.circular_bins_relative_spin = _spin("bins_relative")
        self._add_grid_field(circular_layout, 0, 0, "Bins (relative)", self.circular_bins_relative_spin)
        self.circular_auto_crop_check = QCheckBox("Auto crop to calibration")
        self.circular_auto_crop_check.setChecked(True)
        circular_layout.addWidget(self.circular_auto_crop_check, 0, 2, 1, 2)
        self.circular_q_min_spin = _spin("q_min")
        self._add_grid_field(circular_layout, 1, 0, "q min crop (1/A)", self.circular_q_min_spin)
        self.circular_q_max_spin = _spin("q_max")
        self._add_grid_field(circular_layout, 1, 1, "q max crop (1/A)", self.circular_q_max_spin)
        layout.addWidget(self.circular_group)

        self.sector_group = QGroupBox("Sector Average")
        self.sector_group.setCheckable(True)
        sector_layout = QGridLayout(self.sector_group)
        self.sector_bins_relative_spin = _spin("bins_relative")
        self._add_grid_field(sector_layout, 0, 0, "Bins (relative)", self.sector_bins_relative_spin)
        self.sector_auto_crop_check = QCheckBox("Auto crop to calibration")
        self.sector_auto_crop_check.setChecked(True)
        sector_layout.addWidget(self.sector_auto_crop_check, 0, 2, 1, 2)
        self.sector_start_spin = _spin("sector_start")
        self._add_grid_field(sector_layout, 1, 0, "Angle start (\u00b0)", self.sector_start_spin)
        self.sector_end_spin = _spin("sector_end")
        self._add_grid_field(sector_layout, 1, 1, "Angle end (\u00b0)", self.sector_end_spin)
        self.sector_q_min_spin = _spin("q_min")
        self._add_grid_field(sector_layout, 2, 0, "q min crop (1/A)", self.sector_q_min_spin)
        self.sector_q_max_spin = _spin("q_max")
        self._add_grid_field(sector_layout, 2, 1, "q max crop (1/A)", self.sector_q_max_spin)
        layout.addWidget(self.sector_group)

        self.linecut_q_group = QGroupBox("Line I(q) at Chi")
        self.linecut_q_group.setCheckable(True)
        linecut_q_layout = QGridLayout(self.linecut_q_group)
        self.linecut_q_chi0_spin = _spin("line_chi0")
        self._add_grid_field(linecut_q_layout, 0, 0, "chi0 (\u00b0)", self.linecut_q_chi0_spin)
        self.linecut_q_dq_spin = _spin("line_dq")
        self._add_grid_field(linecut_q_layout, 0, 1, "Half-width dq (1/\u00c5)", self.linecut_q_dq_spin)
        linecut_q_hint = QLabel("chi: 0\u00b0 right, +90\u00b0 up")
        apply_info_style(linecut_q_hint)
        linecut_q_layout.addWidget(linecut_q_hint, 1, 0, 1, 4)
        self.linecut_q_auto_crop_check = QCheckBox("Auto crop to calibration")
        self.linecut_q_auto_crop_check.setChecked(True)
        linecut_q_layout.addWidget(self.linecut_q_auto_crop_check, 2, 0, 1, 4)
        self.linecut_q_q_min_spin = _spin("q_min")
        self._add_grid_field(linecut_q_layout, 3, 0, "q min crop (1/A)", self.linecut_q_q_min_spin)
        self.linecut_q_q_max_spin = _spin("q_max")
        self._add_grid_field(linecut_q_layout, 3, 1, "q max crop (1/A)", self.linecut_q_q_max_spin)
        layout.addWidget(self.linecut_q_group)

        self.linecut_angle_group = QGroupBox("Line I(chi) at Q")
        self.linecut_angle_group.setCheckable(True)
        linecut_angle_layout = QGridLayout(self.linecut_angle_group)
        self.linecut_angle_q0_spin = _spin("line_value")
        self._add_grid_field(linecut_angle_layout, 0, 0, "Reference q0 (1/\u00c5)", self.linecut_angle_q0_spin)
        self.linecut_angle_dq_spin = _spin("line_dq")
        self._add_grid_field(linecut_angle_layout, 0, 1, "Ring width dq (1/\u00c5)", self.linecut_angle_dq_spin)
        layout.addWidget(self.linecut_angle_group)

        self.circular_group.setChecked(True)
        self.sector_group.setChecked(False)
        self.linecut_q_group.setChecked(False)
        self.linecut_angle_group.setChecked(False)

        self._operation_groups = {
            "circular_average": self.circular_group,
            "sector_average": self.sector_group,
            "linecut_q": self.linecut_q_group,
            "linecut_angle": self.linecut_angle_group,
        }
        self._operation_labels = {
            "circular_average": "Circular Average",
            "sector_average": "Sector Average",
            "linecut_q": "Line I(q) at Chi",
            "linecut_angle": "Line I(chi) at Q",
        }
        self._operation_param_widgets = {
            "circular_average": {
                "bins_relative": self.circular_bins_relative_spin,
                "auto_crop": self.circular_auto_crop_check,
                "q_min": self.circular_q_min_spin,
                "q_max": self.circular_q_max_spin,
            },
            "sector_average": {
                "bins_relative": self.sector_bins_relative_spin,
                "angle_start": self.sector_start_spin,
                "angle_end": self.sector_end_spin,
                "auto_crop": self.sector_auto_crop_check,
                "q_min": self.sector_q_min_spin,
                "q_max": self.sector_q_max_spin,
            },
            "linecut_q": {
                "chi0": self.linecut_q_chi0_spin,
                "dq": self.linecut_q_dq_spin,
                "auto_crop": self.linecut_q_auto_crop_check,
                "q_min": self.linecut_q_q_min_spin,
                "q_max": self.linecut_q_q_max_spin,
            },
            "linecut_angle": {
                "q0": self.linecut_angle_q0_spin,
                "dq": self.linecut_angle_dq_spin,
            },
        }

        button_row = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.preview_button.clicked.connect(self.refresh_preview)
        self.export_button = QPushButton("Export Data")
        self.export_button.clicked.connect(self.export_result)
        self.export_recipe_button = QPushButton("Export Recipe")
        self.export_recipe_button.clicked.connect(self.export_recipe)
        self.send_to_batch_button = QPushButton("Send to Batch")
        self.send_to_batch_button.setToolTip("Push current settings as a protocol to the Batch tab")
        self.send_to_batch_button.clicked.connect(self._send_to_batch)
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.export_recipe_button)
        button_row.addWidget(self.send_to_batch_button)
        layout.addLayout(button_row)

        self.status_label = QLabel("Ready")
        apply_info_style(self.status_label)
        layout.addWidget(self.status_label)
        layout.addStretch()

        for operation, group in self._operation_groups.items():
            group.toggled.connect(lambda checked, op=operation: self._on_operation_group_toggled(op, checked))

        for widgets in self._operation_param_widgets.values():
            for widget in widgets.values():
                if hasattr(widget, "stateChanged"):
                    widget.stateChanged.connect(self._on_parameters_changed)
                elif hasattr(widget, "valueChanged"):
                    widget.valueChanged.connect(self._on_parameters_changed)

        self.auto_update_check.stateChanged.connect(self._on_parameters_changed)

        self.calibration_source_combo.currentTextChanged.connect(self._on_source_changed)
        self.mask_source_combo.currentTextChanged.connect(self._on_source_changed)

        self._on_parameters_changed()
        self._refresh_source_status()
        return panel

    @staticmethod
    def _add_grid_field(grid: QGridLayout, row: int, col: int, label_text: str, widget: QWidget) -> None:
        """Place a label+field pair in a 2-column QGridLayout (each column uses 2 grid columns)."""
        grid.addWidget(QLabel(label_text), row, col * 2)
        grid.addWidget(widget, row, col * 2 + 1)

    def _on_operation_group_toggled(self, operation: str, checked: bool):
        if self._building_controls:
            return
        if not checked:
            # Keep exactly one operation selected at all times.
            if not any(group.isChecked() for group in self._operation_groups.values()):
                group = self._operation_groups[operation]
                group.blockSignals(True)
                group.setChecked(True)
                group.blockSignals(False)
            return

        for other_operation, group in self._operation_groups.items():
            if other_operation != operation and group.isChecked():
                group.blockSignals(True)
                group.setChecked(False)
                group.blockSignals(False)

        self._on_parameters_changed()

    def _selected_operation(self):
        for operation, group in self._operation_groups.items():
            if group.isChecked():
                return operation
        return "circular_average"

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


    def _selected_line_mode(self):
        return {"linecut_q": "q", "linecut_angle": "angle"}.get(self._selected_operation(), "q")

    def _use_mask_enabled(self):
        return self.mask_source_combo.currentText() != "No mask"

    def _q_per_pixel(self):
        calibration = self._selected_calibration()
        if calibration is None:
            return None
        getter = getattr(calibration, "get_q_per_pixel", None)
        if getter is None:
            return None
        try:
            dq = float(getter())
            if np.isfinite(dq) and dq > 0:
                return dq
        except Exception:
            return None
        return None

    def _compute_q_bounds(self, image_shape: tuple[int, int]):
        from sciview.processing.batch import compute_q_bounds
        mask = self._get_mask_array(image_shape) if self._use_mask_enabled() else None
        self._q_bounds = compute_q_bounds(self._selected_calibration(), mask)

    def _refresh_auto_q_range(self, image_shape: tuple[int, int]):
        if not self._q_bounds:
            return
        q_min = self._q_bounds["q_min"]
        q_max = self._q_bounds["q_max"]
        for operation in ("circular_average", "sector_average", "linecut_q"):
            widgets = self._operation_param_widgets[operation]
            if not widgets["auto_crop"].isChecked():
                continue
            for key, value in (("q_min", q_min), ("q_max", q_max)):
                widget = widgets[key]
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)

    def _q_to_pixels(self, q_value: float):
        dq = self._q_per_pixel()
        if dq is None or dq <= 0:
            return q_value
        return q_value / dq

    def _active_center(self, image_shape: tuple[int, int]):
        center = self._calibration_center(self._selected_calibration())
        if center is not None:
            return center
        height, width = image_shape
        return max((width - 1) / 2.0, 0.0), max((height - 1) / 2.0, 0.0)

    def _on_source_changed(self, _text: str):
        self._refresh_source_status()
        self._on_parameters_changed()

    def _load_custom_calibration(self):
        file_path, _ = dialog_open_file(
            self,
            "Load Calibration YAML",
            "YAML files (*.yaml *.yml);;All files (*)",
            key="reduction_calibration_open",
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
            self.calibration_source_combo.setCurrentText("Custom profile")
            self._refresh_source_status()
            self.parent_app.show_status(f"Loaded custom calibration: {self._custom_calibration_label}")
            self._on_parameters_changed()
        except Exception as exc:
            self.parent_app.show_status(f"Failed to load custom calibration: {exc}")

    def _load_custom_mask(self):
        file_path, _ = dialog_open_file(
            self,
            "Load Mask",
            "Mask files (*.png *.tif *.tiff *.npy);;All files (*)",
            key="reduction_mask_open",
        )
        if not file_path:
            return

        try:
            self._custom_mask = backend_load_mask_file(file_path)
            self._custom_mask_label = os.path.basename(file_path)
            self.mask_source_combo.setCurrentText("Custom mask")
            self._refresh_source_status()
            self.parent_app.show_status(f"Loaded custom mask: {self._custom_mask_label}")
            self._on_parameters_changed()
        except Exception as exc:
            self.parent_app.show_status(f"Failed to load custom mask: {exc}")

    def _selected_calibration(self):
        if self.calibration_source_combo.currentText() == "Custom profile":
            return self._custom_calibration
        if hasattr(self.parent_app, "get_shared_calibration"):
            return self.parent_app.get_shared_calibration(self.image_data)
        return getattr(self.parent_app, "calibration", None)

    def _selected_mask(self):
        mode = self.mask_source_combo.currentText()
        if mode == "No mask":
            return None
        if mode == "Custom mask":
            return self._custom_mask
        if hasattr(self.parent_app, "get_shared_mask"):
            shared_mask = self.parent_app.get_shared_mask()
            if shared_mask is not None:
                return shared_mask
        # Backward compatibility for older placeholder field.
        return getattr(self.parent_app, "mask", getattr(self.parent_app, "current_mask", None))

    def _calibration_center(self, calibration):
        if calibration is None:
            return None
        x0 = getattr(calibration, "x0", None)
        y0 = getattr(calibration, "y0", None)
        if x0 is None or y0 is None:
            return None
        return float(x0), float(y0)

    def _refresh_source_status(self):
        if hasattr(self.parent_app, "get_shared_calibration"):
            shared_cal = self.parent_app.get_shared_calibration(self.image_data)
        else:
            shared_cal = getattr(self.parent_app, "calibration", None)
        cal = self._selected_calibration()
        mask = self._selected_mask()

        if self.calibration_source_combo.currentText() == "Custom profile":
            cal_text = f"Calibration: custom ({self._custom_calibration_label})"
        elif shared_cal is None:
            cal_text = "Calibration: from calibration tab (not loaded)"
        else:
            cal_text = "Calibration: from calibration tab"

        if self.mask_source_combo.currentText() == "No mask":
            mask_text = "Mask: disabled"
        elif self.mask_source_combo.currentText() == "Custom mask":
            mask_text = f"Mask: custom ({self._custom_mask_label})"
        else:
            mask_text = "Mask: from mask tab" if mask is not None else "Mask: from mask tab (not loaded)"

        self.calibration_status_label.setText(cal_text)
        self.mask_status_label.setText(mask_text)

    def _on_parameters_changed(self, *args):
        if self._building_controls:
            return
        for operation in ("circular_average", "sector_average", "linecut_q"):
            widgets = self._operation_param_widgets[operation]
            manual_crop = not widgets["auto_crop"].isChecked()
            widgets["q_min"].setEnabled(manual_crop)
            widgets["q_max"].setEnabled(manual_crop)
        self.update_plot()

    def _get_image_array(self):
        display_data = self.image_data if self.image_data is not None else getattr(self.parent_app, "image_data", None)
        if display_data is None:
            return None

        img_array, is_valid, error_msg = validate_and_prepare_image_array(display_data, use_converter=True)
        if not is_valid:
            self.parent_app.show_status(error_msg or "Unable to prepare image array for reduction")
            return None

        array = np.asarray(img_array)
        if array.ndim != 2:
            self.parent_app.show_status(f"Reduction requires 2D image data (got {array.ndim}D)")
            return None
        return array

    def _get_mask_array(self, shape: tuple[int, int]):
        from sciview.masking.io import coerce_mask_to_bool
        raw = self._selected_mask()
        result = coerce_mask_to_bool(raw, shape)
        if result is None and raw is not None:
            self.parent_app.show_status("Mask shape does not match the active image; ignoring mask for preview")
        return result

    def _sync_geometry_controls(self, image_shape: tuple[int, int]):
        self._last_control_shape = image_shape

    def _build_request(self):
        image = self._get_image_array()
        if image is None:
            return None

        operation = self._selected_operation()
        mask = self._get_mask_array(image.shape)
        q_min = self._op_float("q_min")
        q_max = self._op_float("q_max")

        kwargs = dict(
            image=image,
            operation=operation,
            center_x=float(self._active_center(image.shape)[0]),
            center_y=float(self._active_center(image.shape)[1]),
            bins_relative=self._op_float("bins_relative"),
            q_min=q_min,
            q_max=q_max,
            radius_max=None,
            angle_start_deg=self._op_float("angle_start", 0.0),
            angle_end_deg=self._op_float("angle_end", 360.0),
            line_chi0_deg=self._op_float("chi0"),
            line_dq=self._op_float("dq", 0.01),
            line_mode=self._selected_line_mode(),
            line_value=self._op_float("q0"),
            use_mask=self._use_mask_enabled(),
            calibration=self._selected_calibration(),
            mask=mask,
            show_region=True,
            metadata={
                "image_shape": tuple(int(v) for v in image.shape),
                "source_path": self.parent_app.get_image_path() if hasattr(self.parent_app, "get_image_path") else None,
                "calibration_source": self.calibration_source_combo.currentText(),
                "mask_source": self.mask_source_combo.currentText(),
                "line_mode": self._selected_line_mode(),
                "q_bounds": dict(self._q_bounds),
            },
        )

        if operation in {"circular_average", "sector_average"} and q_max is not None:
            kwargs["radius_max"] = float(self._q_to_pixels(q_max))

        return ReductionRequest(**kwargs)

    def refresh_preview(self):
        request = self._build_request()
        if request is None:
            self.result_summary.setText("No image loaded")
            self._update_preview_plot(None, message="No image loaded")
            return

        try:
            result = self.backend.run(request)
        except Exception as exc:
            self._current_result = None
            self._update_preview_plot(None, message=f"Preview failed: {exc}")
            self.result_summary.setText(f"Preview failed: {exc}")
            self.status_label.setText(f"Reduction failed: {exc}")
            self.parent_app.show_status(f"Reduction failed: {exc}")
            return

        self._current_result = result
        self._update_preview_plot(result)
        self.result_summary.setText(
            f"{result.operation.replace('_', ' ').title()} points: {int(np.count_nonzero(np.isfinite(result.y)))}"
        )
        self.status_label.setText(
            f"{result.operation.replace('_', ' ').title()} complete: {int(np.count_nonzero(np.isfinite(result.y)))} points"
        )
        self.parent_app.show_status(self.status_label.text())

    def _update_preview_plot(self, result, message: str | None = None):
        self.ax_plot.clear()
        body_font = AppStyle.matplotlib_font_size('body')
        caption_font = AppStyle.matplotlib_font_size('caption')
        small_font = AppStyle.matplotlib_font_size('small')

        if result is None:
            self.ax_plot.text(
                0.5,
                0.5,
                message or "No preview\n\nLoad an image and select an operation.",
                transform=self.ax_plot.transAxes,
                ha="center",
                va="center",
                fontsize=body_font,
            )
            self.ax_plot.set_axis_off()
            self.canvas_plot.draw()
            return

        self.ax_plot.plot(result.x, result.y, color="#2b6cb0", linewidth=1.5)

        scale = self.plot_scale_combo.currentText() if hasattr(self, "plot_scale_combo") else "linear"
        if scale == "logx":
            self.ax_plot.set_xscale("log")
            self.ax_plot.set_yscale("linear")
        elif scale == "logy":
            self.ax_plot.set_xscale("linear")
            self.ax_plot.set_yscale("log")
        elif scale == "loglog":
            self.ax_plot.set_xscale("log")
            self.ax_plot.set_yscale("log")
        else:
            self.ax_plot.set_xscale("linear")
            self.ax_plot.set_yscale("linear")

        self.ax_plot.set_xlabel(result.x_label, fontsize=caption_font)
        self.ax_plot.set_ylabel(result.y_label, fontsize=caption_font)
        self.ax_plot.set_title(result.operation.replace("_", " ").title(), fontsize=body_font)
        self.ax_plot.tick_params(labelsize=small_font)
        self.ax_plot.grid(True, alpha=0.2)
        self.ax_plot.set_axis_on()
        self._apply_display_crop(scale)
        self._apply_display_crop(scale)
        self.canvas_plot.draw()

    def _apply_display_crop(self, scale: str):
        """Crop the preview's x axis to the selected operation's q window,
        matching SciAnalysis's own plot_range convention used by batch
        processing (apply_q_bounds_to_protocol) — circular_average_q_bin /
        sector_average_q_bin / linecut_q always compute over the full
        calibration range regardless of this display-only crop."""
        if self._selected_operation() not in ("circular_average", "sector_average", "linecut_q"):
            return
        q_min = self._op_float("q_min")
        q_max = self._op_float("q_max")
        if q_min is None or q_max is None or q_max <= q_min:
            return
        if scale in ("logx", "loglog") and q_min <= 0:
            return
        self.ax_plot.set_xlim(q_min, q_max)

    def export_result(self):
        if self._current_result is None:
            self.parent_app.show_status("Run preview before export")
            return

        default_name = "reduction.csv"
        if hasattr(self.parent_app, "get_image_path") and self.parent_app.get_image_path():
            base = os.path.splitext(os.path.basename(self.parent_app.get_image_path()))[0]
            default_name = f"{base}_{self._current_result.operation}.csv"

        file_path, _ = dialog_save_file(
            self,
            "Export 1D data",
            default_name,
            "CSV files (*.csv);;Data files (*.dat);;Text files (*.txt);;All files (*)",
            key="reduction_export",
        )
        if not file_path:
            return

        written_path = save_reduction_result(self._current_result, file_path)
        self.parent_app.show_status(f"Reduction 1D data exported to {written_path}")

    def _build_batch_payload(self) -> dict:
        """Build SA-compatible protocol recipe for push to batch.

        Does NOT include plot_range — batch.run_batch injects that from calibration
        at execution time via compute_q_bounds + apply_q_bounds_to_protocol.
        """
        op = self._selected_operation()
        name = self._operation_labels[op]

        if op == "circular_average":
            return {
                "operation": op, "name": name,
                "bins_relative": self._op_float("bins_relative", 1.0),
                "save_results": ["plots", "txt"],
            }

        if op == "sector_average":
            a_start = self._op_float("angle_start", 0.0)
            a_end   = self._op_float("angle_end", 360.0)
            span = (a_end - a_start) % 360.0
            dangle = 360.0 if np.isclose(span, 0.0) else span
            display_angle = (a_start + 0.5 * dangle) % 360.0
            cal = self._selected_calibration()
            angle = float(display_chi_to_scianalysis_sector_chi(display_angle, cal))
            return {
                "operation": op, "name": name,
                "angle":  angle,
                "dangle": float(dangle),
                "bins_relative": self._op_float("bins_relative", 1.0),
                "ylog": True,
                "save_results": ["plots", "txt"],
            }

        if op == "linecut_q":
            return {
                "operation": op, "name": name,
                "chi0": self._op_float("chi0", 0.0),
                "dq":   self._op_float("dq", 0.01),
                "save_results": ["plots", "txt"],
            }

        if op == "linecut_angle":
            return {
                "operation": op, "name": name,
                "q0": self._op_float("q0", 0.1),
                "dq": self._op_float("dq", 0.01),
                "save_results": ["plots", "txt"],
            }

        return {"operation": op, "name": name, "save_results": ["plots", "txt"]}

    def _build_recipe_payload(self) -> dict:
        """Full recipe for Export Recipe: SA-compatible params + context metadata."""
        return {
            **self._build_batch_payload(),
            "q_bounds": dict(self._q_bounds),
            "calibration_source": self.calibration_source_combo.currentText(),
            "mask_source": self.mask_source_combo.currentText(),
            "source_path": self.parent_app.get_image_path() if hasattr(self.parent_app, "get_image_path") else None,
        }

    def export_recipe(self):
        payload = self._build_recipe_payload()
        file_path, _ = dialog_save_file(
            self,
            "Export reduction recipe",
            "reduction_recipe.yaml",
            "YAML files (*.yaml *.yml);;JSON files (*.json);;All files (*)",
            key="reduction_recipe_export",
        )
        if not file_path:
            return

        path = Path(file_path)
        with path.open("w", encoding="utf-8") as handle:
            if path.suffix.lower() == ".json":
                json.dump(payload, handle, indent=2)
            else:
                yaml.safe_dump(payload, handle, sort_keys=False)
        self.parent_app.show_status(f"Reduction recipe exported to {path}")

    def _send_to_batch(self):
        payload = self._build_batch_payload()
        if hasattr(self.parent_app, "push_recipe_to_batch"):
            self.parent_app.push_recipe_to_batch(payload, source="reduction_tab")
        else:
            self.parent_app.show_status("Batch tab not available")

    def _remove_overlay_artists(self):
        if hasattr(self, 'image_viewer'):
            self.image_viewer.clear_overlays(group='reduction')
        self._overlay_artists = []

    def _draw_reduction_overlay(self, viewer):
        self._remove_overlay_artists()

        image = self._get_image_array()
        if image is None:
            return

        operation = self._selected_operation()
        cx, cy = self._active_center(image.shape)
        calibration = self._selected_calibration()
        overlay_note = ""
        q_min = self._op_float("q_min", 0.0)
        q_max = self._op_float("q_max", 0.1)
        styles = OVERLAY_STYLE
        angle_text = chi_convention_text(calibration)

        def _draw_angle_label(
            angle_deg: float,
            text: str,
            q_ref: float,
            radial_offset_px: float = 0.0,
            color: str = "#e5e7eb",
        ):
            point = chi_q_to_pixel(calibration, angle_deg, q_ref)
            if point is not None:
                px, py = point
                if radial_offset_px != 0.0:
                    vx = px - cx
                    vy = py - cy
                    norm = float(np.hypot(vx, vy))
                    if norm > 1e-9:
                        px += radial_offset_px * (vx / norm)
                        py += radial_offset_px * (vy / norm)
            else:
                radius_px = float(self._q_to_pixels(max(0.0, q_ref))) + float(radial_offset_px)
                dx, dy = chi_to_screen_vector(angle_deg, calibration=calibration)
                px = cx + dx * radius_px
                py = cy + dy * radius_px
            label_id = f"reduction-angle-label-{len(self._overlay_artists)}"
            label = viewer.add_text(
                label_id,
                px,
                py,
                text,
                group='reduction',
                color=color,
            )
            self._overlay_artists.append(label)

        def _draw_q_label(angle_deg: float, q_value: float, text: str, color: str = "#e5e7eb"):
            point = chi_q_to_pixel(calibration, angle_deg, q_value)
            if point is not None:
                px, py = point
            else:
                r = float(self._q_to_pixels(max(0.0, q_value)))
                dx, dy = chi_to_screen_vector(angle_deg, calibration=calibration)
                px = cx + dx * r
                py = cy + dy * r
            label_id = f"reduction-q-label-{len(self._overlay_artists)}"
            label = viewer.add_text(
                label_id,
                px,
                py,
                text,
                group='reduction',
                color=color,
                anchor=(0.0, 1.0),
            )
            self._overlay_artists.append(label)

        center_marker = viewer.add_points('reduction-center', [cx], [cy], group='reduction', color="#00d1ff", size=7.0)
        self._overlay_artists.append(center_marker)

        if self._use_mask_enabled():
            mask = self._get_mask_array(image.shape)
            if mask is not None:
                mask_artist = viewer.add_mask_overlay('reduction-mask', mask, group='reduction', color=styles["mask"]["color"], alpha=styles["mask"]["alpha"])
                self._overlay_artists.append(mask_artist)

        if operation == "circular_average":
            radius = float(self._q_to_pixels(q_max))
            circle = viewer.add_circle('reduction-qmax-circle', cx, cy, radius, group='reduction', color=styles["circular"]["edge"], width=1.6)
            self._overlay_artists.append(circle)
            if q_min > 0:
                r_min = float(self._q_to_pixels(q_min))
                circle_min = viewer.add_circle('reduction-qmin-circle', cx, cy, r_min, group='reduction', color=styles["circular"]["edge_soft"], width=1.0)
                self._overlay_artists.append(circle_min)
                _draw_q_label(0.0, q_min, f"qmin={q_min:.3f}")
            _draw_q_label(0.0, q_max, f"qmax={q_max:.3f}")
            overlay_note = f"Circular average: q <= {q_max:.4f} 1/A"
        elif operation == "sector_average":
            start = self._op_float("angle_start", 0.0)
            end = self._op_float("angle_end", 360.0)
            span = (end - start) % 360.0
            dangle = 360.0 if np.isclose(span, 0.0) else span
            center = (start + 0.5 * dangle) % 360.0

            sector_mask = sector_roi_mask(calibration, start, end, q_min, q_max)
            if sector_mask is not None:
                sector_artist = viewer.add_mask_overlay('reduction-sector', sector_mask, group='reduction', color=styles["sector"]["color"], alpha=styles["sector"]["alpha"])
                self._overlay_artists.append(sector_artist)
            else:
                radius = float(self._q_to_pixels(q_max))
                sector_mask = self._screen_sector_mask(image.shape, cx, cy, radius, start, end)
                sector_artist = viewer.add_mask_overlay('reduction-sector-fallback', sector_mask, group='reduction', color=styles["sector"]["color"], alpha=styles["sector"]["alpha"])
                self._overlay_artists.append(sector_artist)

            _draw_angle_label(start, f"{start:.0f}\N{DEGREE SIGN}", q_max)
            _draw_angle_label(end, f"{end:.0f}\N{DEGREE SIGN}", q_max)
            _draw_q_label(center, q_min, f"qmin={q_min:.3f}")
            _draw_q_label(center, q_max, f"qmax={q_max:.3f}")
            overlay_note = f"Sector I(q): {start:.1f}\N{DEGREE SIGN} to {end:.1f}\N{DEGREE SIGN} ({angle_text})"
        else:
            line_mode = self._selected_line_mode()
            if line_mode == "angle":
                q0 = self._op_float("q0", 0.1)
                dq = self._op_float("dq", 0.01)
                r_inner = max(0.0, self._q_to_pixels(max(0.0, q0 - dq)))
                r_outer = max(r_inner + 1e-6, self._q_to_pixels(max(0.0, q0 + dq)))
                ring_mask = self._screen_ring_mask(image.shape, cx, cy, r_inner, r_outer)
                ring_artist = viewer.add_mask_overlay('reduction-line-chi-ring', ring_mask, group='reduction', color=styles["line_chi"]["color"], alpha=styles["line_chi"]["alpha"])
                self._overlay_artists.append(ring_artist)
                _draw_q_label(0.0, max(0.0, q0 - dq), f"q-={max(0.0, q0-dq):.3f}")
                _draw_q_label(0.0, q0 + dq, f"q+={q0+dq:.3f}")
                for ang, txt in ((0.0, "0"), (90.0, "90"), (270.0, "270")):
                    _draw_angle_label(ang, txt, q0 + dq, radial_offset_px=12.0, color="#fdba74")
                overlay_note = f"I(chi) at q: q0={q0:.4f} 1/A, dq={dq:.4f} 1/A"
            else:
                # I(q) along line: radial stripe at azimuthal angle chi0 with half-width dq (Å⁻¹).
                chi0 = self._op_float("chi0", 0.0)
                dq_val = self._op_float("dq", 0.01)
                roi = line_q_roi_mask(calibration, chi0, dq_val, q_min, q_max)
                draw_guides = roi is None
                if roi is not None:
                    roi_artist = viewer.add_mask_overlay('reduction-line-q-roi', roi, group='reduction', color=styles["line_q"]["color"], alpha=styles["line_q"]["alpha"])
                    self._overlay_artists.append(roi_artist)

                # Draw the actual ROI: a radial stripe from beam center at angle chi0.
                # Extend a ray forward and backward from beam center to image edge.
                if draw_guides:
                    h, w = image.shape
                    ray_len = float(np.hypot(w, h))
                    dx, dy = chi_to_screen_vector(chi0, calibration=calibration)
                    # Centerline ray (bidirectional)
                    center_ray = viewer.add_polyline(
                        'reduction-line-q-center',
                        [cx - dx * ray_len, cx + dx * ray_len],
                        [cy - dy * ray_len, cy + dy * ray_len],
                        group='reduction',
                        color=styles["line_q"]["center"],
                        width=1.8,
                    )
                    self._overlay_artists.append(center_ray)

                    # Shaded band: offset perpendicular to chi0 by dq_px on each side
                    dq_px = self._q_to_pixels(dq_val)
                    if dq_px > 0:
                        perp_dx = -dy  # perpendicular unit vector
                        perp_dy = dx
                        for sign in (+1, -1):
                            band_line = viewer.add_polyline(
                                f'reduction-line-q-bound-{sign}',
                                [cx + sign * perp_dx * dq_px - dx * ray_len,
                                 cx + sign * perp_dx * dq_px + dx * ray_len],
                                [cy + sign * perp_dy * dq_px - dy * ray_len,
                                 cy + sign * perp_dy * dq_px + dy * ray_len],
                                group='reduction',
                                color=styles["line_q"]["bounds"],
                                width=1.0,
                            )
                            self._overlay_artists.append(band_line)
                _draw_angle_label(chi0, f"{chi0:.0f}\N{DEGREE SIGN}", q_max, radial_offset_px=10.0, color="#99f6e4")
                _draw_q_label(chi0, q_min, f"qmin={q_min:.3f}")
                _draw_q_label(chi0, q_max, f"qmax={q_max:.3f}")
                overlay_note = (
                    f"I(q) at chi0: chi0={chi0:.1f}\N{DEGREE SIGN}, dq={dq_val:.4f} 1/A "
                    f"({angle_text})"
                )

        if overlay_note:
            note_artist = viewer.add_text(
                'reduction-note',
                8.0,
                18.0,
                overlay_note,
                group='reduction',
                color=styles["labels"]["note_text"],
                anchor=(0.0, 0.0),
            )
            self._overlay_artists.append(note_artist)

    def _screen_ring_mask(self, shape, cx, cy, r_inner, r_outer):
        yy, xx = np.indices(shape)
        rr = np.hypot(xx - float(cx), yy - float(cy))
        return (rr >= float(r_inner)) & (rr <= float(r_outer))

    def _screen_sector_mask(self, shape, cx, cy, radius, start_deg, end_deg):
        yy, xx = np.indices(shape)
        rr = np.hypot(xx - float(cx), yy - float(cy))
        angles = (np.degrees(np.arctan2(float(cy) - yy, xx - float(cx))) + 360.0) % 360.0
        span = (float(end_deg) - float(start_deg)) % 360.0
        if np.isclose(span, 0.0):
            in_angle = np.ones(shape, dtype=bool)
        else:
            center = (float(start_deg) + 0.5 * span) % 360.0
            delta = ((angles - center + 180.0) % 360.0) - 180.0
            in_angle = np.abs(delta) <= 0.5 * span
        return (rr <= float(radius)) & in_angle

    def update_plot(self, image_data=None):
        display_data = image_data if image_data is not None else self.image_data
        if display_data is None and hasattr(self.parent_app, "image_data"):
            display_data = self.parent_app.image_data

        if display_data is None:
            self._current_result = None
            self._update_preview_plot(None)
            return

        self.image_data = display_data
        image_array, is_valid, error_msg = validate_and_prepare_image_array(display_data, use_converter=True)
        if not is_valid:
            self.result_summary.setText(error_msg or "Unable to update reduction display")
            self.parent_app.show_status(error_msg or "Unable to update reduction display")
            return

        self.result_summary.setText(f"Image loaded: {image_array.shape[1]}x{image_array.shape[0]}")

        self._sync_geometry_controls(image_array.shape)
        self._compute_q_bounds(image_array.shape)
        self._refresh_auto_q_range(image_array.shape)
        self._refresh_source_status()
        super().update_plot(display_data)

        if self.auto_update_check.isChecked():
            self.refresh_preview()

    def on_shared_state_activated(self):
        """Refresh reduction state when shared image/calibration/mask changes become active."""
        self.update_plot()

    def _add_tab_specific_status(self, info_lines):
        info_lines.append("")
        info_lines.append("=== REDUCTION STATUS ===")
        info_lines.append(f"Operation: {self._operation_labels[self._selected_operation()]}")
        info_lines.append(f"Mask enabled: {'Yes' if self._use_mask_enabled() else 'No'}")
        q_min = self._op_float("q_min")
        q_max = self._op_float("q_max")
        if q_min is not None and q_max is not None:
            info_lines.append(f"q crop: {q_min:.4f} to {q_max:.4f} 1/A")
        if self._q_bounds:
            info_lines.append(
                f"qx range: {self._q_bounds['qx_min']:.4f} to {self._q_bounds['qx_max']:.4f} 1/A"
            )
            info_lines.append(
                f"qz range: {self._q_bounds['qz_min']:.4f} to {self._q_bounds['qz_max']:.4f} 1/A"
            )
        info_lines.append(f"Calibration source: {self.calibration_source_combo.currentText()}")
        info_lines.append(f"Mask source: {self.mask_source_combo.currentText()}")
        if self._current_result is not None:
            info_lines.append(f"Last preview: {self._current_result.operation}")
            info_lines.append(f"Preview points: {self._current_result.y.size}")
        else:
            info_lines.append("Last preview: None")
