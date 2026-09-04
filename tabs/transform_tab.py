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
from PyQt5.QtCore import Qt, QTimer
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

from sciview.interfaces.stable_qt.utils.file_dialog_state import dialog_open_file, dialog_save_file
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array
from sciview.interfaces.theme.app_style import (
    AppStyle,
    apply_info_style,
    apply_subtitle_style,
    apply_title_style,
    setup_splitter_layout,
)
from sciview.masking.io import load_mask_file as backend_load_mask_file
from sciview.processing.transform import TransformBackend, TransformRequest, save_transform_result
from sciview.settings.app_settings import SPINBOX_CONFIG


def _spin(key):
    mn, mx, default, step, decimals = SPINBOX_CONFIG[key]
    if decimals is None:
        w = QSpinBox(); w.setRange(int(mn), int(mx)); w.setSingleStep(int(step)); w.setValue(int(default))
    else:
        w = QDoubleSpinBox(); w.setRange(mn, mx); w.setDecimals(decimals); w.setSingleStep(step); w.setValue(default)
    return w
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION, get_calibration_class as _get_calibration_class
from sciview.settings.viewer_config import VIEWER_BEHAVIOR, resolve_matplotlib_colormap
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
        self._preview_delay_ms = 450
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self.refresh_preview)
        self._build_ui()
        self._building_controls = False

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        layout_ratios = AppStyle.get_layout_ratios()

        main_splitter = QSplitter(Qt.Horizontal)

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(self._create_image_panel())
        left_splitter.addWidget(self._create_transform_panel())
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
        layout.addLayout(title_row)

        self.result_summary = QLabel("No preview yet")
        apply_info_style(self.result_summary)
        layout.addWidget(self.result_summary)

        self.fig_transform, self.ax_transform = plt.subplots(figsize=(6, 8))
        self.fig_transform.subplots_adjust(left=0.12, bottom=0.12, right=0.98, top=0.95)
        self.canvas_transform = FigureCanvas(self.fig_transform)
        layout.addWidget(self.canvas_transform)

        toolbar = NavigationToolbar(self.canvas_transform, self)
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

        self.auto_update_check = QCheckBox("Auto preview")
        self.auto_update_check.setChecked(True)
        layout.addWidget(self.auto_update_check)

        # Each transform is its own checkable group with its own parameters, so
        # every option (and what it needs) is visible up front instead of
        # hidden behind a dropdown. Checking a group selects it; the others
        # gray out (but stay visible) via Qt's native checkable-groupbox behavior.
        #
        # All three call SciAnalysis the same way: only bins_relative (plus
        # bins_phi for Q-Phi) is a real SciAnalysis parameter — remesh_q_bin /
        # remesh_q_phi / remesh_qr_bin always cover the full calibration extent.
        # The crop fields below (labeled per operation's own axes) are
        # display-only, applied as matplotlib axis limits in
        # _apply_display_crop, matching SciAnalysis's own universal
        # plot_range=[x_min, x_max, y_min, y_max] convention (Data2D.plot()) —
        # not sent to SciAnalysis here (see _run_scianalysis).
        self.q_image_group = QGroupBox("Q Image")
        self.q_image_group.setCheckable(True)
        q_image_layout = QGridLayout(self.q_image_group)
        self.q_bins_relative_spin = _spin("bins_relative")
        self._add_grid_field(q_image_layout, 0, 0, "Bins (relative)", self.q_bins_relative_spin)
        self.q_auto_crop_check = QCheckBox("Auto crop to calibration")
        self.q_auto_crop_check.setChecked(True)
        q_image_layout.addWidget(self.q_auto_crop_check, 0, 2, 1, 2)
        self.q_x_min_spin = _spin("crop_min")
        self._add_grid_field(q_image_layout, 1, 0, "qx min crop (1/A)", self.q_x_min_spin)
        self.q_x_max_spin = _spin("crop_max")
        self._add_grid_field(q_image_layout, 1, 1, "qx max crop (1/A)", self.q_x_max_spin)
        self.q_y_min_spin = _spin("crop_min")
        self._add_grid_field(q_image_layout, 2, 0, "qz min crop (1/A)", self.q_y_min_spin)
        self.q_y_max_spin = _spin("crop_max")
        self._add_grid_field(q_image_layout, 2, 1, "qz max crop (1/A)", self.q_y_max_spin)
        layout.addWidget(self.q_image_group)

        self.q_phi_group = QGroupBox("Q-Phi Image")
        self.q_phi_group.setCheckable(True)
        q_phi_layout = QGridLayout(self.q_phi_group)
        self.qphi_bins_relative_spin = _spin("bins_relative")
        self._add_grid_field(q_phi_layout, 0, 0, "Bins (relative)", self.qphi_bins_relative_spin)
        self.qphi_bins_phi_spin = _spin("bins_phi")
        self._add_grid_field(q_phi_layout, 0, 1, "Phi bins", self.qphi_bins_phi_spin)
        self.qphi_auto_crop_check = QCheckBox("Auto crop q range to calibration")
        self.qphi_auto_crop_check.setChecked(True)
        q_phi_layout.addWidget(self.qphi_auto_crop_check, 1, 0, 1, 4)
        self.qphi_x_min_spin = _spin("q_min")
        self._add_grid_field(q_phi_layout, 2, 0, "q min crop (1/A)", self.qphi_x_min_spin)
        self.qphi_x_max_spin = _spin("q_max")
        self._add_grid_field(q_phi_layout, 2, 1, "q max crop (1/A)", self.qphi_x_max_spin)
        self.qphi_y_min_spin = _spin("phi_min")
        self._add_grid_field(q_phi_layout, 3, 0, "phi min crop (deg)", self.qphi_y_min_spin)
        self.qphi_y_max_spin = _spin("phi_max")
        self._add_grid_field(q_phi_layout, 3, 1, "phi max crop (deg)", self.qphi_y_max_spin)
        layout.addWidget(self.q_phi_group)

        self.qr_qz_group = QGroupBox("Qr-Qz Image")
        self.qr_qz_group.setCheckable(True)
        qr_qz_layout = QGridLayout(self.qr_qz_group)
        self.qrqz_bins_relative_spin = _spin("bins_relative")
        self._add_grid_field(qr_qz_layout, 0, 0, "Bins (relative)", self.qrqz_bins_relative_spin)
        self.qrqz_auto_crop_check = QCheckBox("Auto crop to calibration")
        self.qrqz_auto_crop_check.setChecked(True)
        qr_qz_layout.addWidget(self.qrqz_auto_crop_check, 0, 2, 1, 2)
        self.qrqz_x_min_spin = _spin("crop_min")
        self._add_grid_field(qr_qz_layout, 1, 0, "qr min crop (1/A)", self.qrqz_x_min_spin)
        self.qrqz_x_max_spin = _spin("crop_max")
        self._add_grid_field(qr_qz_layout, 1, 1, "qr max crop (1/A)", self.qrqz_x_max_spin)
        self.qrqz_y_min_spin = _spin("crop_min")
        self._add_grid_field(qr_qz_layout, 2, 0, "qz min crop (1/A)", self.qrqz_y_min_spin)
        self.qrqz_y_max_spin = _spin("crop_max")
        self._add_grid_field(qr_qz_layout, 2, 1, "qz max crop (1/A)", self.qrqz_y_max_spin)
        layout.addWidget(self.qr_qz_group)

        self.q_image_group.setChecked(True)
        self.q_phi_group.setChecked(False)
        self.qr_qz_group.setChecked(False)

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
            },
            "q_phi_image": {
                "bins_relative": self.qphi_bins_relative_spin,
                "bins_phi": self.qphi_bins_phi_spin,
                "auto_crop": self.qphi_auto_crop_check,
                "x_min": self.qphi_x_min_spin,
                "x_max": self.qphi_x_max_spin,
                "y_min": self.qphi_y_min_spin,
                "y_max": self.qphi_y_max_spin,
            },
            "qr_qz_image": {
                "bins_relative": self.qrqz_bins_relative_spin,
                "auto_crop": self.qrqz_auto_crop_check,
                "x_min": self.qrqz_x_min_spin,
                "x_max": self.qrqz_x_max_spin,
                "y_min": self.qrqz_y_min_spin,
                "y_max": self.qrqz_y_max_spin,
            },
        }

        button_row = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.preview_button.clicked.connect(self.refresh_preview)
        self.export_button = QPushButton("Export Transform")
        self.export_button.clicked.connect(self.export_result)
        self.send_to_batch_button = QPushButton("Send to Batch")
        self.send_to_batch_button.setToolTip("Push current settings as a protocol to the Batch tab")
        self.send_to_batch_button.clicked.connect(self._send_to_batch)
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.send_to_batch_button)
        layout.addLayout(button_row)

        self.status_label = QLabel("Ready")
        apply_info_style(self.status_label)
        layout.addWidget(self.status_label)
        layout.addStretch()

        for operation, group in self._operation_groups.items():
            group.toggled.connect(lambda checked, op=operation: self._on_operation_group_toggled(op, checked))

        self.auto_update_check.stateChanged.connect(self._on_parameters_changed)
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

    @staticmethod
    def _add_grid_field(grid: QGridLayout, row: int, col: int, label_text: str, widget: QWidget) -> None:
        """Place a label+field pair in a 2-column QGridLayout (each column uses 2 grid columns)."""
        grid.addWidget(QLabel(label_text), row, col * 2)
        grid.addWidget(widget, row, col * 2 + 1)

    def _on_source_changed(self, _text: str):
        self._refresh_source_status()
        self._on_parameters_changed()

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

    def _on_parameters_changed(self, *args):
        if self._building_controls:
            return
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
        self.update_plot(schedule_preview=True)

    def _selected_operation(self):
        for operation, group in self._operation_groups.items():
            if group.isChecked():
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
        from sciview.masking.io import coerce_mask_to_bool
        raw = self._selected_mask()
        result = coerce_mask_to_bool(raw, shape)
        if result is None and raw is not None:
            self.parent_app.show_status("Mask shape does not match the active image; ignoring mask for preview")
        return result

    def _compute_q_bounds(self, image_shape: tuple[int, int]):
        from sciview.processing.batch import compute_q_bounds
        mask = self._get_mask_array(image_shape) if self._use_mask_enabled() else None
        self._q_bounds = compute_q_bounds(self._selected_calibration(), mask)

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
            bins_relative=self._op_float("bins_relative", 1.0),
            bins_phi=self._op_int("bins_phi", 360),
            x_min=self._op_float("x_min"),
            x_max=self._op_float("x_max"),
            y_min=self._op_float("y_min"),
            y_max=self._op_float("y_max"),
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
        try:
            self._update_transform_plot(result)
        except Exception as exc:
            # Don't leave the status stuck on "Preview pending..." if rendering itself fails.
            self.result_summary.setText(f"Preview failed: {exc}")
            self.status_label.setText(f"Transform failed: {exc}")
            self.parent_app.show_status(f"Transform failed: {exc}")
            return
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
        body_font = AppStyle.matplotlib_font_size('body')
        caption_font = AppStyle.matplotlib_font_size('caption')
        small_font = AppStyle.matplotlib_font_size('small')

        if result is None:
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
        cmap = resolve_matplotlib_colormap(display_vals["cmap"])
        scale = display_vals["scale"]

        norm = None
        if scale == "log":
            safe_vmin, safe_vmax = self._sanitize_log_limits(image, vmin, vmax)
            if safe_vmin is not None and safe_vmax is not None:
                norm = LogNorm(vmin=safe_vmin, vmax=safe_vmax)

        finite_min = float(np.min(finite))
        finite_max = float(np.max(finite))
        if finite_max <= finite_min:
            finite_max = finite_min + 1.0

        if vmin is None or vmax is None or vmax <= vmin:
            low_q, high_q = VIEWER_BEHAVIOR.auto_level_percentiles
            auto_vmin, auto_vmax = np.percentile(finite, [low_q, high_q])
            vmin = float(auto_vmin)
            vmax = float(auto_vmax)

        if scale == "linear":
            # If global limits are far outside the transform data range, fall back
            # to robust limits so preview remains readable without per-tab tuning.
            range_span = max(finite_max - finite_min, 1e-12)
            visible_span = max(float(vmax) - float(vmin), 1e-12)
            overlap_min = max(float(vmin), finite_min)
            overlap_max = min(float(vmax), finite_max)
            overlap = max(0.0, overlap_max - overlap_min)
            overlap_ratio = overlap / range_span
            span_ratio = visible_span / range_span
            if overlap_ratio < 0.02 or span_ratio > 200.0:
                low_q, high_q = VIEWER_BEHAVIOR.auto_level_percentiles
                auto_vmin, auto_vmax = np.percentile(finite, [low_q, high_q])
                vmin = float(auto_vmin)
                vmax = float(auto_vmax)

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
        self.ax_transform.set_xlabel(result.x_label, fontsize=caption_font)
        self.ax_transform.set_ylabel(result.y_label, fontsize=caption_font)
        self.ax_transform.set_title(result.operation.replace("_", " ").title(), fontsize=body_font)
        self.ax_transform.tick_params(labelsize=small_font)
        self.ax_transform.set_axis_on()
        self._apply_display_crop()
        self.canvas_transform.draw()

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

    def _build_batch_payload(self) -> dict:
        """Build SA-compatible protocol recipe for push to batch.

        Does NOT include plot_range (batch injects it from calibration at run time).
        For q_phi_image the phi range is included as phi_min/phi_max and is consumed
        by apply_q_bounds_to_protocol when building the final plot_range.
        """
        op   = self._selected_operation()
        name = self._operation_labels[op]
        bins_relative = self._op_float("bins_relative", 1.0)

        if op == "q_image":
            return {"operation": op, "name": name, "bins_relative": bins_relative, "save_results": ["plots", "npz"]}

        if op == "q_phi_image":
            return {
                "operation": op, "name": name,
                "bins_relative": bins_relative,
                "phi_min": self._op_float("y_min"),
                "phi_max": self._op_float("y_max"),
                "save_results": ["plots", "npz"],
            }

        if op == "qr_qz_image":
            return {
                "operation": op, "name": name,
                "bins_relative": bins_relative,
                "save_results": ["plots", "npz"],
            }

        return {"operation": op, "name": name, "save_results": ["plots", "npz"]}

    def _build_recipe_payload(self) -> dict:
        """Full recipe for Export Recipe: SA-compatible params + context metadata."""
        return {
            **self._build_batch_payload(),
            "q_bounds": dict(self._q_bounds),
            "calibration_source": self.calibration_source_combo.currentText(),
            "mask_source": self.mask_source_combo.currentText(),
            "source_path": self.parent_app.get_image_path() if hasattr(self.parent_app, "get_image_path") else None,
        }

    def _send_to_batch(self):
        payload = self._build_batch_payload()
        if hasattr(self.parent_app, "push_recipe_to_batch"):
            self.parent_app.push_recipe_to_batch(payload, source="transform_tab")
        else:
            self.parent_app.show_status("Batch tab not available")

    def _schedule_preview(self):
        self.status_label.setText("Preview pending...")
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
        info_lines.append(f"Calibration source: {self.calibration_source_combo.currentText()}")
        info_lines.append(f"Mask source: {self.mask_source_combo.currentText()}")
        if self._current_result is not None:
            info_lines.append(f"Last preview: {self._current_result.operation}")
            info_lines.append(
                f"Preview shape: {self._current_result.image.shape[1]}x{self._current_result.image.shape[0]}"
            )
        else:
            info_lines.append("Last preview: None")
