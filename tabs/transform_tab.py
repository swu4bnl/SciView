"""Interactive 2D transform tab for SciView."""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import yaml
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.colors import LogNorm
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

from sciview.interfaces.stable_qt.utils.file_dialog_state import dialog_open_file, dialog_save_file
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array
from sciview.interfaces.theme.app_style import apply_info_style, apply_subtitle_style, apply_title_style
from sciview.masking.io import load_mask_file as backend_load_mask_file
from sciview.processing.transform import TransformBackend, TransformRequest, save_transform_result
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION
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
        self._build_ui()
        self._building_controls = False

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        main_splitter = QSplitter(Qt.Horizontal)

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(self._create_image_panel())
        left_splitter.addWidget(self._create_transform_panel())
        left_splitter.setStretchFactor(0, 1)
        left_splitter.setStretchFactor(1, 1)
        left_splitter.setSizes([560, 560])
        main_splitter.addWidget(left_splitter)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(2, 2, 2, 2)
        right_layout.setSpacing(6)
        right_layout.addWidget(self._create_controls_panel())
        main_splitter.addWidget(right_panel)

        main_splitter.setSizes([980, 420])
        main_layout.addWidget(main_splitter)

    def _create_transform_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_row = QHBoxLayout()
        title = QLabel("Transform Preview")
        apply_subtitle_style(title)
        title_row.addWidget(title)
        title_row.addStretch()
        controls_hint = QLabel("Display controls: use vmin/vmax/cmap/scale above")
        apply_info_style(controls_hint)
        title_row.addWidget(controls_hint)
        layout.addLayout(title_row)

        self.result_summary = QLabel("No preview yet")
        apply_info_style(self.result_summary)
        layout.addWidget(self.result_summary)

        self.fig_transform, self.ax_transform = plt.subplots(figsize=(5.2, 3.0))
        self.fig_transform.subplots_adjust(left=0.12, bottom=0.12, right=0.98, top=0.95)
        self.canvas_transform = FigureCanvas(self.fig_transform)
        layout.addWidget(self.canvas_transform)

        toolbar = NavigationToolbar(self.canvas_transform, self)
        toolbar.setMaximumHeight(25)
        layout.addWidget(toolbar)

        return panel

    def _make_double_spin(self, minimum: float, maximum: float, value: float, step: float = 1.0, decimals: int = 3):
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

        transform_group = QGroupBox("Transform")
        transform_layout = QFormLayout(transform_group)
        transform_layout.setLabelAlignment(Qt.AlignRight)

        self.operation_combo = QComboBox()
        self.operation_combo.addItems(["Q Image", "Q-Phi Image", "Qx-Qz Image"])
        transform_layout.addRow("Operation", self.operation_combo)

        self.auto_update_check = QCheckBox("Auto preview")
        self.auto_update_check.setChecked(True)
        transform_layout.addRow(self.auto_update_check)

        self.bins_q_spin = self._make_int_spin(16, 4096, 320)
        transform_layout.addRow("Q bins", self.bins_q_spin)

        self.bins_phi_spin = self._make_int_spin(16, 1440, 360)
        transform_layout.addRow("Phi bins", self.bins_phi_spin)

        self.auto_qrange_check = QCheckBox("Auto q-range")
        self.auto_qrange_check.setChecked(True)
        transform_layout.addRow(self.auto_qrange_check)

        self.q_min_spin = self._make_double_spin(0.0, 100.0, 0.0, step=0.01, decimals=4)
        transform_layout.addRow("q min (1/A)", self.q_min_spin)

        self.q_max_spin = self._make_double_spin(0.001, 100.0, 2.0, step=0.01, decimals=4)
        transform_layout.addRow("q max (1/A)", self.q_max_spin)

        self.phi_min_spin = self._make_double_spin(-360.0, 360.0, -180.0, step=1.0, decimals=2)
        transform_layout.addRow("phi min (deg)", self.phi_min_spin)

        self.phi_max_spin = self._make_double_spin(-360.0, 360.0, 180.0, step=1.0, decimals=2)
        transform_layout.addRow("phi max (deg)", self.phi_max_spin)

        self.operation_hint = QLabel("Q image and Qx-Qz transforms use q binning; Q-Phi uses q and phi bins.")
        apply_info_style(self.operation_hint)
        transform_layout.addRow(self.operation_hint)

        layout.addWidget(transform_group)

        button_row = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.preview_button.clicked.connect(self.refresh_preview)
        self.export_button = QPushButton("Export Transform")
        self.export_button.clicked.connect(self.export_result)
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.export_button)
        layout.addLayout(button_row)

        self.status_label = QLabel("Ready")
        apply_info_style(self.status_label)
        layout.addWidget(self.status_label)
        layout.addStretch()

        self.operation_combo.currentTextChanged.connect(self._on_operation_changed)

        for widget in (
            self.auto_update_check,
            self.auto_qrange_check,
            self.bins_q_spin,
            self.bins_phi_spin,
            self.q_min_spin,
            self.q_max_spin,
            self.phi_min_spin,
            self.phi_max_spin,
        ):
            if hasattr(widget, "stateChanged"):
                widget.stateChanged.connect(self._on_parameters_changed)
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._on_parameters_changed)

        self.calibration_source_combo.currentTextChanged.connect(self._on_source_changed)
        self.mask_source_combo.currentTextChanged.connect(self._on_source_changed)

        self._on_operation_changed(self.operation_combo.currentText())
        self._refresh_source_status()
        return panel

    def _on_source_changed(self, _text: str):
        self._refresh_source_status()
        self._on_parameters_changed()

    def _on_operation_changed(self, _text: str):
        is_qphi = self._selected_operation() == "q_phi_image"
        self.bins_phi_spin.setEnabled(is_qphi)
        self.phi_min_spin.setEnabled(is_qphi)
        self.phi_max_spin.setEnabled(is_qphi)
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
            "Q Image": "q_image",
            "Q-Phi Image": "q_phi_image",
            "Qx-Qz Image": "qx_qz_image",
        }[text]

    def _use_mask_enabled(self):
        return self.mask_source_combo.currentText() != "No mask"

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
        return getattr(self.parent_app, "mask", getattr(self.parent_app, "current_mask", None))

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
            key="transform_calibration_open",
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
            key="transform_mask_open",
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

        if cal is None:
            self.status_label.setText("Calibration required for transform")

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

    def _compute_q_bounds(self, image_shape: tuple[int, int]):
        calibration = self._selected_calibration()
        if calibration is None:
            self._q_bounds = {}
            return

        try:
            q_map = np.asarray(calibration.q_map(), dtype=float)
        except Exception:
            self._q_bounds = {}
            return

        valid = np.isfinite(q_map)
        if self._use_mask_enabled():
            mask = self._get_mask_array(image_shape)
            if mask is not None and mask.shape == q_map.shape:
                valid &= ~mask

        if not np.any(valid):
            self._q_bounds = {}
            return

        q_vals = q_map[valid]
        self._q_bounds = {
            "q_min": float(np.min(q_vals)),
            "q_max": float(np.max(q_vals)),
        }

    def _estimate_q_range(self):
        if self._q_bounds:
            q_min = float(self._q_bounds.get("q_min", 0.0))
            q_max = float(self._q_bounds.get("q_max", 0.0))
            if q_max > q_min:
                return q_min, q_max
        return 0.0, max(0.001, float(self.q_max_spin.value()))

    def _refresh_auto_q_range(self):
        if not self.auto_qrange_check.isChecked():
            return
        q_min, q_max = self._estimate_q_range()
        if q_max <= q_min:
            q_min, q_max = 0.0, max(0.001, q_max)

        self.q_min_spin.blockSignals(True)
        self.q_max_spin.blockSignals(True)
        self.q_min_spin.setValue(max(0.0, q_min))
        self.q_max_spin.setValue(max(q_min + 0.001, q_max))
        self.q_min_spin.blockSignals(False)
        self.q_max_spin.blockSignals(False)

    def _build_request(self):
        image = self._get_image_array()
        if image is None:
            return None

        calibration = self._selected_calibration()
        if calibration is None:
            self.parent_app.show_status("Load calibration before running transform")
            return None

        request = TransformRequest(
            image=image,
            operation=self._selected_operation(),
            calibration=calibration,
            mask=self._get_mask_array(image.shape),
            use_mask=self._use_mask_enabled(),
            bins_q=int(self.bins_q_spin.value()),
            bins_phi=int(self.bins_phi_spin.value()),
            q_min=float(self.q_min_spin.value()),
            q_max=float(self.q_max_spin.value()),
            phi_min_deg=float(self.phi_min_spin.value()),
            phi_max_deg=float(self.phi_max_spin.value()),
            metadata={
                "image_shape": tuple(int(v) for v in image.shape),
                "source_path": self.parent_app.get_image_path() if hasattr(self.parent_app, "get_image_path") else None,
                "calibration_source": self.calibration_source_combo.currentText(),
                "mask_source": self.mask_source_combo.currentText(),
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
            self.status_label.setText(f"Transform failed: {exc}")
            self.parent_app.show_status(f"Transform failed: {exc}")
            return

        self._current_result = result
        self._update_transform_plot(result)
        self.result_summary.setText(
            f"{result.operation.replace('_', ' ').title()} shape: {result.image.shape[1]}x{result.image.shape[0]}"
        )
        self.status_label.setText(
            f"{result.operation.replace('_', ' ').title()} complete: {result.image.shape[1]}x{result.image.shape[0]}"
        )
        self.parent_app.show_status(self.status_label.text())

    def _update_transform_plot(self, result, message: str | None = None):
        if self._transform_colorbar is not None:
            try:
                self._transform_colorbar.remove()
            except Exception:
                pass
            self._transform_colorbar = None

        self.ax_transform.clear()

        if result is None:
            self.ax_transform.text(
                0.5,
                0.5,
                message or "No transform preview\n\nLoad an image and run preview.",
                transform=self.ax_transform.transAxes,
                ha="center",
                va="center",
                fontsize=10,
            )
            self.ax_transform.set_axis_off()
            self.canvas_transform.draw()
            return

        image = np.asarray(result.image, dtype=float)
        finite = image[np.isfinite(image)]
        if finite.size == 0:
            self.ax_transform.text(0.5, 0.5, "No finite transform values", transform=self.ax_transform.transAxes, ha="center", va="center")
            self.ax_transform.set_axis_off()
            self.canvas_transform.draw()
            return

        extent = None
        if result.x_axis is not None and result.y_axis is not None:
            if result.x_axis.size == image.shape[1] and result.y_axis.size == image.shape[0]:
                extent = [
                    float(result.x_axis[0]),
                    float(result.x_axis[-1]),
                    float(result.y_axis[0]),
                    float(result.y_axis[-1]),
                ]

        display_vals = self.get_display_values()
        vmin = display_vals["vmin"]
        vmax = display_vals["vmax"]
        cmap = display_vals["cmap"]
        scale = display_vals["scale"]

        norm = None
        if scale == "log":
            safe_vmin, safe_vmax = self._sanitize_log_limits(image, vmin, vmax)
            if safe_vmin is not None and safe_vmax is not None:
                norm = LogNorm(vmin=safe_vmin, vmax=safe_vmax)

        kwargs = {
            "origin": "lower",
            "cmap": cmap,
            "aspect": "auto",
        }
        if extent is not None:
            kwargs["extent"] = extent
        if norm is not None:
            kwargs["norm"] = norm
        elif scale != "log":
            kwargs["vmin"] = vmin
            kwargs["vmax"] = vmax

        img_artist = self.ax_transform.imshow(image, **kwargs)
        self._transform_colorbar = self.fig_transform.colorbar(img_artist, ax=self.ax_transform, fraction=0.045, pad=0.03)
        self.ax_transform.set_xlabel(result.x_label)
        self.ax_transform.set_ylabel(result.y_label)
        self.ax_transform.set_title(result.operation.replace("_", " ").title())
        self.ax_transform.set_axis_on()
        self.canvas_transform.draw()

    def export_result(self):
        if self._current_result is None:
            self.parent_app.show_status("Run preview before export")
            return

        default_name = "transform_output.npz"
        if hasattr(self.parent_app, "get_image_path") and self.parent_app.get_image_path():
            base = os.path.splitext(os.path.basename(self.parent_app.get_image_path()))[0]
            default_name = f"{base}_{self._current_result.operation}.npz"

        file_path, _ = dialog_save_file(
            self,
            "Export transformed image",
            default_name,
            "NumPy zipped (*.npz);;NumPy array (*.npy);;All files (*)",
            key="transform_export",
        )
        if not file_path:
            return

        written_path = save_transform_result(self._current_result, file_path)
        self.parent_app.show_status(f"Transformed image exported to {written_path}")

    def update_plot(self, image_data=None):
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
            self.refresh_preview()

    def _add_tab_specific_status(self, info_lines):
        info_lines.append("")
        info_lines.append("=== TRANSFORM STATUS ===")
        info_lines.append(f"Operation: {self.operation_combo.currentText()}")
        info_lines.append(f"Mask enabled: {'Yes' if self._use_mask_enabled() else 'No'}")
        info_lines.append(f"q range: {self.q_min_spin.value():.4f} to {self.q_max_spin.value():.4f} 1/A")
        info_lines.append(f"Calibration source: {self.calibration_source_combo.currentText()}")
        info_lines.append(f"Mask source: {self.mask_source_combo.currentText()}")
        if self._current_result is not None:
            info_lines.append(f"Last preview: {self._current_result.operation}")
            info_lines.append(
                f"Preview shape: {self._current_result.image.shape[1]}x{self._current_result.image.shape[0]}"
            )
        else:
            info_lines.append("Last preview: None")
