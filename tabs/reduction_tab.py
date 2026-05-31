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
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Wedge

from sciview.interfaces.stable_qt.utils.file_dialog_state import dialog_open_file, dialog_save_file
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array
from sciview.interfaces.stable_qt.utils.reduction_overlay import (
    OVERLAY_STYLE,
    chi_q_to_pixel,
    chi_convention_text,
    chi_to_screen_vector,
    draw_solid_overlay,
    line_q_roi_mask,
    sector_roi_mask,
)
from sciview.interfaces.theme.app_style import apply_info_style, apply_subtitle_style, apply_title_style
from sciview.masking.io import load_mask_file as backend_load_mask_file
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION
from sciview.processing.reduction import ReductionBackend, ReductionRequest, save_reduction_result
from tabs.base_image_tab import BaseImageTab


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

        main_splitter = QSplitter(Qt.Horizontal)

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(self._create_image_panel())
        left_splitter.addWidget(self._create_preview_panel())
        left_splitter.setSizes([780, 340])
        main_splitter.addWidget(left_splitter)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(2, 2, 2, 2)
        right_layout.setSpacing(6)
        right_layout.addWidget(self._create_controls_panel())
        main_splitter.addWidget(right_panel)

        main_splitter.setSizes([980, 420])
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

        self.fig_plot, self.ax_plot = plt.subplots(figsize=(5.2, 2.8))
        self.fig_plot.subplots_adjust(left=0.10, bottom=0.18, right=0.98, top=0.95)
        self.canvas_plot = FigureCanvas(self.fig_plot)
        layout.addWidget(self.canvas_plot)

        toolbar = NavigationToolbar(self.canvas_plot, self)
        toolbar.setMaximumHeight(25)
        layout.addWidget(toolbar)

        return panel

    def _make_double_spin(self, minimum: float, maximum: float, value: float, step: float = 1.0, decimals: int = 2):
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    def _make_int_spin(self, minimum: int, maximum: int, value: int, step: int = 1):
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    def _create_controls_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)

        title = QLabel("Controls")
        apply_title_style(title)
        layout.addWidget(title)

        source_group = QGroupBox("Sources")
        source_layout = QFormLayout(source_group)

        self.calibration_source_combo = QComboBox()
        self.calibration_source_combo.addItems(["From calibration tab", "Custom profile"])
        cal_row_widget = QWidget()
        cal_btn_row = QHBoxLayout(cal_row_widget)
        cal_btn_row.setContentsMargins(0, 0, 0, 0)
        cal_btn_row.setSpacing(6)
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
        mask_btn_row.setSpacing(6)
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
        common_layout.setLabelAlignment(Qt.AlignRight)

        self.operation_combo = QComboBox()
        self.operation_combo.addItems(["Circular Average", "Sector Average", "Line I(q) at Chi", "Line I(chi) at Q"])
        common_layout.addRow("Operation", self.operation_combo)

        self.auto_update_check = QCheckBox("Auto preview")
        self.auto_update_check.setChecked(True)
        common_layout.addRow(self.auto_update_check)

        self.bins_spin = self._make_int_spin(8, 4096, 256)
        common_layout.addRow("Bins", self.bins_spin)

        self.auto_qrange_check = QCheckBox("Auto q-range")
        self.auto_qrange_check.setChecked(True)
        common_layout.addRow(self.auto_qrange_check)

        self.q_min_spin = self._make_double_spin(0.0, 100.0, 0.0, step=0.01, decimals=4)
        common_layout.addRow("q min (1/A)", self.q_min_spin)

        self.q_max_spin = self._make_double_spin(0.001, 100.0, 2.0, step=0.01, decimals=4)
        common_layout.addRow("q max (1/A)", self.q_max_spin)
        layout.addWidget(common_group)

        self.circular_group = QGroupBox("Circular average")
        circular_layout = QFormLayout(self.circular_group)
        self.circular_hint = QLabel("Uses q max")
        apply_info_style(self.circular_hint)
        circular_layout.addRow(self.circular_hint)
        layout.addWidget(self.circular_group)

        self.sector_group = QGroupBox("Sector average")
        sector_layout = QFormLayout(self.sector_group)
        self.sector_start_spin = self._make_double_spin(0.0, 360.0, 0.0, step=1.0, decimals=1)
        self.sector_end_spin = self._make_double_spin(0.0, 360.0, 30.0, step=1.0, decimals=1)
        self.sector_hint = QLabel("Uses q max")
        apply_info_style(self.sector_hint)
        sector_layout.addRow(self.sector_hint)
        sector_layout.addRow("Angle start", self.sector_start_spin)
        sector_layout.addRow("Angle end", self.sector_end_spin)
        layout.addWidget(self.sector_group)

        self.line_group = QGroupBox("Line Profile")
        line_layout = QFormLayout(self.line_group)

        self.line_value_label = QLabel("Reference")
        apply_info_style(self.line_value_label)
        line_layout.addRow(self.line_value_label)

        self.line_value_spin = self._make_double_spin(-10.0, 10.0, 0.0, step=0.01, decimals=4)
        line_layout.addRow("Reference", self.line_value_spin)

        self.line_chi0_spin = self._make_double_spin(-180.0, 180.0, 0.0, step=1.0, decimals=2)
        self.line_dq_spin = self._make_double_spin(0.0001, 100.0, 0.01, step=0.001, decimals=4)
        self.line_dq_label = QLabel("Half-width dq (1/\u00c5)")
        line_layout.addRow("chi0 (\u00b0)", self.line_chi0_spin)
        self.line_chi0_hint = QLabel("chi: 0 right, +90 up")
        apply_info_style(self.line_chi0_hint)
        line_layout.addRow(self.line_chi0_hint)
        line_layout.addRow(self.line_dq_label, self.line_dq_spin)
        layout.addWidget(self.line_group)

        button_row = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.preview_button.clicked.connect(self.refresh_preview)
        self.export_button = QPushButton("Export Data")
        self.export_button.clicked.connect(self.export_result)
        self.export_recipe_button = QPushButton("Export Recipe")
        self.export_recipe_button.clicked.connect(self.export_recipe)
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.export_recipe_button)
        layout.addLayout(button_row)

        self.status_label = QLabel("Ready")
        apply_info_style(self.status_label)
        layout.addWidget(self.status_label)
        layout.addStretch()

        self.operation_combo.currentTextChanged.connect(self._on_operation_changed)
        for widget in (
            self.auto_update_check,
            self.auto_qrange_check,
            self.bins_spin,
            self.q_min_spin,
            self.q_max_spin,
            self.sector_start_spin,
            self.sector_end_spin,
            self.line_value_spin,
            self.line_chi0_spin,
            self.line_dq_spin,
        ):
            if hasattr(widget, "stateChanged"):
                widget.stateChanged.connect(self._on_parameters_changed)
            elif hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(self._on_parameters_changed)
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._on_parameters_changed)

        self.calibration_source_combo.currentTextChanged.connect(self._on_source_changed)
        self.mask_source_combo.currentTextChanged.connect(self._on_source_changed)

        self._on_operation_changed(self.operation_combo.currentText())
        self._on_line_mode_changed()
        self._refresh_source_status()
        return panel

    def _on_line_mode_changed(self, _text: str | None = None):
        mode = self._selected_line_mode()
        is_line_geom = mode == "q"
        self.line_chi0_spin.setVisible(is_line_geom)
        self.line_chi0_hint.setVisible(is_line_geom)
        self.line_value_spin.setEnabled(not is_line_geom)

        if mode == "q":
            self.line_value_label.setText("Reference")
            self.line_dq_label.setText("Half-width dq (1/\u00c5)")
        elif mode == "angle":
            self.line_value_label.setText("Reference: q0 (1/\u00c5)")
            self.line_dq_label.setText("Ring width dq (1/\u00c5)")
        else:
            self.line_value_label.setText("Reference")
            self.line_dq_label.setText("Half-width dq (1/\u00c5)")

        self._on_parameters_changed()

    def _selected_line_mode(self):
        return {
            "Line I(q) at Chi": "q",
            "Line I(chi) at Q": "angle",
        }.get(self.operation_combo.currentText(), "q")

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

    def _estimate_q_max(self, image_shape: tuple[int, int]):
        calibration = self._selected_calibration()
        if calibration is not None and hasattr(calibration, "q_map"):
            try:
                q_map = np.asarray(calibration.q_map(), dtype=float)
                finite = q_map[np.isfinite(q_map)]
                if finite.size:
                    return float(np.max(finite))
            except Exception:
                pass

        dq = self._q_per_pixel()
        if dq is not None:
            height, width = image_shape
            max_r = float(np.hypot(width, height))
            return max_r * dq

        return 2.0

    def _estimate_q_range(self, image_shape: tuple[int, int]):
        if self._q_bounds:
            q_min = float(self._q_bounds.get("q_min", 0.0))
            q_max = float(self._q_bounds.get("q_max", 0.0))
            if q_max > q_min:
                return q_min, q_max

        q_max = self._estimate_q_max(image_shape)
        return 0.0, q_max

    def _compute_q_bounds(self, image_shape: tuple[int, int]):
        calibration = self._selected_calibration()
        if calibration is None:
            self._q_bounds = {}
            return

        try:
            q_map = np.asarray(calibration.q_map(), dtype=float)
            qx_map = np.asarray(calibration.qx_map(), dtype=float)
            qz_map = np.asarray(calibration.qz_map(), dtype=float)
        except Exception:
            self._q_bounds = {}
            return

        valid = np.isfinite(q_map) & np.isfinite(qx_map) & np.isfinite(qz_map)
        if self._use_mask_enabled():
            mask = self._get_mask_array(image_shape)
            if mask is not None and mask.shape == q_map.shape:
                valid &= ~mask

        if not np.any(valid):
            self._q_bounds = {}
            return

        q_vals = q_map[valid]
        qx_vals = qx_map[valid]
        qz_vals = qz_map[valid]
        self._q_bounds = {
            "q_min": float(np.min(q_vals)),
            "q_max": float(np.max(q_vals)),
            "qx_min": float(np.min(qx_vals)),
            "qx_max": float(np.max(qx_vals)),
            "qz_min": float(np.min(qz_vals)),
            "qz_max": float(np.max(qz_vals)),
        }

    def _refresh_auto_q_range(self, image_shape: tuple[int, int]):
        if not self.auto_qrange_check.isChecked():
            return
        q_min, q_max = self._estimate_q_range(image_shape)
        if q_max <= q_min:
            q_min, q_max = 0.0, max(0.001, q_max)

        self.q_min_spin.blockSignals(True)
        self.q_max_spin.blockSignals(True)
        self.q_min_spin.setValue(max(0.0, q_min))
        self.q_max_spin.setValue(max(q_min + 0.001, q_max))
        self.q_min_spin.blockSignals(False)
        self.q_max_spin.blockSignals(False)

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

    def _try_get_scianalysis_calibration_class(self):
        try:
            rqconv_module = import_module("SciAnalysis.XSAnalysis.DataRQconv")
            calibration_cls = getattr(rqconv_module, "CalibrationRQconv", None)
            if calibration_cls is not None:
                return calibration_cls
        except Exception:
            pass

        try:
            data_module = import_module("SciAnalysis.XSAnalysis.Data")
            return getattr(data_module, "Calibration", None)
        except Exception:
            return None

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
            calibration_cls = self._try_get_scianalysis_calibration_class()
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

    def _on_operation_changed(self, _text: str):
        operation = self._selected_operation()
        self.circular_group.setVisible(operation == "circular_average")
        self.sector_group.setVisible(operation == "sector_average")
        self.line_group.setVisible(operation == "line_profile")
        self._on_line_mode_changed()
        self._on_parameters_changed()

    def _on_parameters_changed(self, *args):
        if self._building_controls:
            return
        manual_q = not self.auto_qrange_check.isChecked()
        self.q_min_spin.setEnabled(manual_q)
        self.q_max_spin.setEnabled(manual_q)
        self.update_plot()

    def _selected_operation(self):
        text = self.operation_combo.currentText()
        return {
            "Circular Average": "circular_average",
            "Sector Average": "sector_average",
            "Line I(q) at Chi": "line_profile",
            "Line I(chi) at Q": "line_profile",
        }[text]

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
        mask = self._selected_mask()
        if mask is None:
            return None

        from_scianalysis_mask = hasattr(mask, "data") and not isinstance(mask, np.ndarray)
        if hasattr(mask, "data") and not isinstance(mask, np.ndarray):
            mask = mask.data

        array_raw = np.asarray(mask)
        if array_raw.dtype == bool:
            array = array_raw
        elif from_scianalysis_mask:
            # SciAnalysis masks use 1 for valid pixels and 0 for masked pixels.
            array = array_raw <= 0
        else:
            array = array_raw.astype(bool)

        if array.shape != shape:
            self.parent_app.show_status("Mask shape does not match the active image; ignoring mask for preview")
            return None
        return np.asarray(array, dtype=bool)

    def _sync_geometry_controls(self, image_shape: tuple[int, int]):
        self._last_control_shape = image_shape

    def _build_request(self):
        image = self._get_image_array()
        if image is None:
            return None

        operation = self._selected_operation()
        mask = self._get_mask_array(image.shape)

        kwargs = dict(
            image=image,
            operation=operation,
            center_x=float(self._active_center(image.shape)[0]),
            center_y=float(self._active_center(image.shape)[1]),
            bins=int(self.bins_spin.value()),
            q_min=float(self.q_min_spin.value()),
            q_max=float(self.q_max_spin.value()),
            radius_max=None,
            angle_start_deg=float(self.sector_start_spin.value()),
            angle_end_deg=float(self.sector_end_spin.value()),
            line_chi0_deg=float(self.line_chi0_spin.value()),
            line_dq=float(self.line_dq_spin.value()),
            line_mode=self._selected_line_mode(),
            line_value=float(self.line_value_spin.value()),
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

        if operation in {"circular_average", "sector_average"}:
            kwargs["radius_max"] = float(self._q_to_pixels(float(self.q_max_spin.value())))

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

        if result is None:
            self.ax_plot.text(
                0.5,
                0.5,
                message or "No preview\n\nLoad an image and select an operation.",
                transform=self.ax_plot.transAxes,
                ha="center",
                va="center",
                fontsize=10,
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

        self.ax_plot.set_xlabel(result.x_label)
        self.ax_plot.set_ylabel(result.y_label)
        self.ax_plot.set_title(result.operation.replace("_", " ").title())
        self.ax_plot.grid(True, alpha=0.2)
        self.ax_plot.set_axis_on()
        self.canvas_plot.draw()

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

    def _build_recipe_payload(self):
        return {
            "operation": self._selected_operation(),
            "bins": int(self.bins_spin.value()),
            "q_min": float(self.q_min_spin.value()),
            "q_max": float(self.q_max_spin.value()),
            "auto_q_range": bool(self.auto_qrange_check.isChecked()),
            "calibration_source": self.calibration_source_combo.currentText(),
            "mask_source": self.mask_source_combo.currentText(),
            "use_mask": self._use_mask_enabled(),
            "line_mode": self._selected_line_mode(),
            "line_value": float(self.line_value_spin.value()),
            "line_dq": float(self.line_dq_spin.value()),
            "line_chi0_deg": float(self.line_chi0_spin.value()),
            "angle_start_deg": float(self.sector_start_spin.value()),
            "angle_end_deg": float(self.sector_end_spin.value()),
            "q_bounds": dict(self._q_bounds),
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

    def _remove_overlay_artists(self):
        for artist in self._overlay_artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._overlay_artists = []

    def _draw_reduction_overlay(self, ax):
        self._remove_overlay_artists()

        image = self._get_image_array()
        if image is None:
            return

        operation = self._selected_operation()
        cx, cy = self._active_center(image.shape)
        calibration = self._selected_calibration()
        overlay_note = ""
        q_min = float(self.q_min_spin.value())
        q_max = float(self.q_max_spin.value())
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
            label = ax.text(
                px,
                py,
                text,
                color=color,
                fontsize=7.6,
                ha="center",
                va="center",
                zorder=8,
                bbox=dict(
                    boxstyle="round,pad=0.14",
                    facecolor=styles["labels"]["box"],
                    alpha=styles["labels"]["box_alpha"],
                    edgecolor="none",
                ),
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
            label = ax.text(
                px,
                py,
                text,
                color=color,
                fontsize=7.4,
                ha="left",
                va="bottom",
                zorder=8,
                bbox=dict(
                    boxstyle="round,pad=0.12",
                    facecolor=styles["labels"]["box"],
                    alpha=styles["labels"]["box_alpha"],
                    edgecolor="none",
                ),
            )
            self._overlay_artists.append(label)

        center_marker = ax.scatter([cx], [cy], c="#00d1ff", s=18, zorder=5)
        self._overlay_artists.append(center_marker)

        if self._use_mask_enabled():
            mask = self._get_mask_array(image.shape)
            if mask is not None:
                mask_artist = draw_solid_overlay(ax, mask, styles["mask"]["color"], styles["mask"]["alpha"])
                self._overlay_artists.append(mask_artist)

        if operation == "circular_average":
            radius = float(self._q_to_pixels(q_max))
            circle = Circle((cx, cy), radius=radius, fill=False, linewidth=1.6, edgecolor=styles["circular"]["edge"])
            ax.add_patch(circle)
            self._overlay_artists.append(circle)
            if q_min > 0:
                r_min = float(self._q_to_pixels(q_min))
                circle_min = Circle(
                    (cx, cy),
                    radius=r_min,
                    fill=False,
                    linewidth=1.0,
                    linestyle=":",
                    edgecolor=styles["circular"]["edge_soft"],
                )
                ax.add_patch(circle_min)
                self._overlay_artists.append(circle_min)
                _draw_q_label(0.0, q_min, f"qmin={q_min:.3f}")
            _draw_q_label(0.0, q_max, f"qmax={q_max:.3f}")
            overlay_note = f"Circular average: q <= {q_max:.4f} 1/A"
        elif operation == "sector_average":
            start = float(self.sector_start_spin.value())
            end = float(self.sector_end_spin.value())
            span = (end - start) % 360.0
            dangle = 360.0 if np.isclose(span, 0.0) else span
            center = (start + 0.5 * dangle) % 360.0

            sector_mask = sector_roi_mask(calibration, start, end, q_min, q_max)
            if sector_mask is not None:
                sector_artist = draw_solid_overlay(ax, sector_mask, styles["sector"]["color"], styles["sector"]["alpha"])
                self._overlay_artists.append(sector_artist)
            else:
                radius = float(self._q_to_pixels(q_max))
                if end <= start:
                    end += 360.0
                wedge = Wedge(
                    (cx, cy),
                    radius,
                    theta1=start,
                    theta2=end,
                    width=None,
                    facecolor=styles["sector"]["color"],
                    alpha=styles["sector"]["alpha"],
                    edgecolor=styles["sector"]["edge"],
                    linewidth=1.4,
                )
                ax.add_patch(wedge)
                self._overlay_artists.append(wedge)

            _draw_angle_label(start, f"{start:.0f}\N{DEGREE SIGN}", q_max)
            _draw_angle_label(end, f"{end:.0f}\N{DEGREE SIGN}", q_max)
            _draw_q_label(center, q_min, f"qmin={q_min:.3f}")
            _draw_q_label(center, q_max, f"qmax={q_max:.3f}")
            overlay_note = f"Sector I(q): {start:.1f}\N{DEGREE SIGN} to {end:.1f}\N{DEGREE SIGN} ({angle_text})"
        else:
            line_mode = self._selected_line_mode()
            if line_mode == "angle":
                q0 = float(self.line_value_spin.value())
                dq = float(self.line_dq_spin.value())
                r_inner = max(0.0, self._q_to_pixels(max(0.0, q0 - dq)))
                r_outer = max(r_inner + 1e-6, self._q_to_pixels(max(0.0, q0 + dq)))
                ring = Wedge(
                    (cx, cy),
                    r_outer,
                    theta1=0.0,
                    theta2=360.0,
                    width=max(0.0, r_outer - r_inner),
                    facecolor=styles["line_chi"]["color"],
                    alpha=styles["line_chi"]["alpha"],
                    edgecolor=styles["line_chi"]["edge"],
                    linewidth=1.4,
                )
                ax.add_patch(ring)
                self._overlay_artists.append(ring)
                _draw_q_label(0.0, max(0.0, q0 - dq), f"q-={max(0.0, q0-dq):.3f}")
                _draw_q_label(0.0, q0 + dq, f"q+={q0+dq:.3f}")
                for ang, txt in ((0.0, "0"), (90.0, "90"), (270.0, "270")):
                    _draw_angle_label(ang, txt, q0 + dq, radial_offset_px=12.0, color="#fdba74")
                overlay_note = f"I(chi) at q: q0={q0:.4f} 1/A, dq={dq:.4f} 1/A"
            else:
                # I(q) along line: radial stripe at azimuthal angle chi0 with half-width dq (Å⁻¹).
                chi0 = float(self.line_chi0_spin.value())
                dq_val = float(self.line_dq_spin.value())
                roi = line_q_roi_mask(calibration, chi0, dq_val, q_min, q_max)
                draw_guides = roi is None
                if roi is not None:
                    roi_artist = draw_solid_overlay(ax, roi, styles["line_q"]["color"], styles["line_q"]["alpha"])
                    self._overlay_artists.append(roi_artist)

                # Draw the actual ROI: a radial stripe from beam center at angle chi0.
                # Extend a ray forward and backward from beam center to image edge.
                if draw_guides:
                    h, w = image.shape
                    ray_len = float(np.hypot(w, h))
                    dx, dy = chi_to_screen_vector(chi0, calibration=calibration)
                    # Centerline ray (bidirectional)
                    center_ray = Line2D(
                        [cx - dx * ray_len, cx + dx * ray_len],
                        [cy - dy * ray_len, cy + dy * ray_len],
                        color=styles["line_q"]["center"], linewidth=1.8, zorder=5,
                    )
                    ax.add_line(center_ray)
                    self._overlay_artists.append(center_ray)

                    # Shaded band: offset perpendicular to chi0 by dq_px on each side
                    dq_px = self._q_to_pixels(dq_val)
                    if dq_px > 0:
                        perp_dx = -dy  # perpendicular unit vector
                        perp_dy = dx
                        for sign in (+1, -1):
                            band_line = Line2D(
                                [cx + sign * perp_dx * dq_px - dx * ray_len,
                                 cx + sign * perp_dx * dq_px + dx * ray_len],
                                [cy + sign * perp_dy * dq_px - dy * ray_len,
                                 cy + sign * perp_dy * dq_px + dy * ray_len],
                                color=styles["line_q"]["bounds"], linewidth=1.0, linestyle=":", alpha=0.75, zorder=4,
                            )
                            ax.add_line(band_line)
                            self._overlay_artists.append(band_line)
                _draw_angle_label(chi0, f"{chi0:.0f}\N{DEGREE SIGN}", q_max, radial_offset_px=10.0, color="#99f6e4")
                _draw_q_label(chi0, q_min, f"qmin={q_min:.3f}")
                _draw_q_label(chi0, q_max, f"qmax={q_max:.3f}")
                overlay_note = (
                    f"I(q) at chi0: chi0={chi0:.1f}\N{DEGREE SIGN}, dq={dq_val:.4f} 1/A "
                    f"({angle_text})"
                )

        if overlay_note:
            note_artist = ax.text(
                0.02,
                0.98,
                overlay_note,
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=8.5,
                color=styles["labels"]["note_text"],
                bbox=dict(
                    boxstyle="round,pad=0.22",
                    facecolor=styles["labels"]["box"],
                    alpha=styles["labels"]["note_box_alpha"],
                    edgecolor="none",
                ),
                zorder=8,
            )
            self._overlay_artists.append(note_artist)

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

    def _add_tab_specific_status(self, info_lines):
        info_lines.append("")
        info_lines.append("=== REDUCTION STATUS ===")
        info_lines.append(f"Operation: {self.operation_combo.currentText()}")
        info_lines.append(f"Mask enabled: {'Yes' if self._use_mask_enabled() else 'No'}")
        info_lines.append(f"q range: {self.q_min_spin.value():.4f} to {self.q_max_spin.value():.4f} 1/A")
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
