"""Batch processing tab: folder scanning, protocol queue, run management, and output browser."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import yaml
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sciview.interfaces.stable_qt.utils.file_dialog_state import (
    dialog_open_file,
    dialog_save_file,
    dialog_select_directory,
)
from sciview.interfaces.theme.app_style import (
    AppStyle,
    apply_emphasis_button_style,
    apply_info_style,
    apply_subtitle_style,
    apply_title_style,
    setup_splitter_layout,
)
from sciview.processing.batch import (
    REDUCTION_OPERATIONS,
    TRANSFORM_OPERATIONS,
    BatchFileResult,
    BatchJob,
    BatchProtocol,
    BatchRunner,
    new_files_in_folder,
    scan_folder,
)
from tabs.base_image_tab import BaseImageTab


# Default parameter sets shown when a new protocol is added manually.
_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "circular_average": {"bins": 256, "q_min": 0.0, "q_max": 2.0},
    "sector_average":   {"bins": 256, "q_min": 0.0, "q_max": 2.0, "angle_start_deg": 0.0, "angle_end_deg": 30.0},
    "line_profile":     {"bins": 256, "q_min": 0.0, "q_max": 2.0, "line_chi0_deg": 0.0, "line_dq": 0.01, "line_mode": "q"},
    "q_image":          {"bins_q": 320, "q_min": 0.0, "q_max": 2.0},
    "q_phi_image":      {"bins_q": 320, "bins_phi": 360, "q_min": 0.0, "q_max": 2.0},
    "qr_qz_image":      {"bins_q": 320, "q_min": 0.0, "q_max": 2.0},
}

_STATUS_SYMBOL = {"ok": "✓", "error": "✗", "skipped": "—", "running": "⏳"}


class BatchTab(QWidget):
    """Batch processing tab: scan files, configure protocols, run and inspect output."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        self._protocols: list[BatchProtocol] = []
        self._runner: BatchRunner | None = None
        self._monitor_timer = QTimer(self)
        self._monitor_timer.timeout.connect(self._poll_monitor)
        self._monitor_seen: set[str] = set()
        self._monitor_mtime_cache: dict[str, int] = {}
        self._results: list[BatchFileResult] = []

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        main_splitter = QSplitter(Qt.Horizontal)

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(self._create_file_source_panel())
        left_splitter.addWidget(self._create_output_browser_panel())
        setup_splitter_layout(left_splitter, [1, 1])
        main_splitter.addWidget(left_splitter)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(*([AppStyle.LAYOUT["panel_inner_margin"]] * 4))
        right_layout.setSpacing(AppStyle.LAYOUT["section_spacing"])
        right_layout.addWidget(BaseImageTab.make_scrollable_panel(self._create_controls_panel()))
        main_splitter.addWidget(right_panel)

        setup_splitter_layout(main_splitter, AppStyle.get_layout_ratios()["main_splitter_ratio"])
        root.addWidget(main_splitter)

    # ---- left top: file source ----------------------------------------

    def _create_file_source_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(*([AppStyle.LAYOUT["panel_inner_margin"]] * 4))
        layout.setSpacing(AppStyle.LAYOUT["section_spacing"])

        title = QLabel("Input Files")
        apply_title_style(title)
        layout.addWidget(title)

        # Source mode selector -----------------------------------------------
        mode_group = QGroupBox("File Source")
        mode_layout = QFormLayout(mode_group)
        BaseImageTab.configure_adaptive_form_layout(mode_layout)

        self.file_source_combo = QComboBox()
        self.file_source_combo.addItems(["Image Browser", "Custom Folder"])
        self.file_source_combo.currentIndexChanged.connect(self._on_file_source_changed)
        mode_layout.addRow("Source", self.file_source_combo)
        layout.addWidget(mode_group)

        # Browser mode info (read-only, no duplication) ---------------------
        self.browser_info_group = QGroupBox("Image Browser")
        browser_layout = QFormLayout(self.browser_info_group)
        BaseImageTab.configure_adaptive_form_layout(browser_layout)

        self.browser_folder_label = QLabel("—")
        apply_info_style(self.browser_folder_label)
        browser_layout.addRow("Folder:", self.browser_folder_label)

        self.browser_pattern_label = QLabel("—")
        apply_info_style(self.browser_pattern_label)
        browser_layout.addRow("Pattern:", self.browser_pattern_label)

        self.browser_count_label = QLabel("— files available")
        apply_info_style(self.browser_count_label)
        browser_layout.addRow(self.browser_count_label)

        layout.addWidget(self.browser_info_group)

        # Custom folder mode (hidden by default) ----------------------------
        self.custom_folder_group = QGroupBox("Custom Folder")
        custom_layout = QFormLayout(self.custom_folder_group)
        BaseImageTab.configure_adaptive_form_layout(custom_layout)

        path_row = QWidget()
        path_hbox = QHBoxLayout(path_row)
        path_hbox.setContentsMargins(0, 0, 0, 0)
        self.folder_path_input = QLineEdit()
        self.folder_path_input.setPlaceholderText("Select folder…")
        path_hbox.addWidget(self.folder_path_input, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self._browse_input_folder)
        path_hbox.addWidget(btn_browse)
        custom_layout.addRow("Folder", path_row)

        self.pattern_input = QLineEdit("*")
        self.pattern_input.setPlaceholderText("e.g. *.tiff, sample_*.h5")
        custom_layout.addRow("Pattern", self.pattern_input)

        self.recursive_check = QCheckBox("Recursive")
        custom_layout.addRow(self.recursive_check)

        btn_scan = QPushButton("Scan Folder")
        btn_scan.clicked.connect(self._scan_folder)
        apply_emphasis_button_style(btn_scan)
        custom_layout.addRow(btn_scan)

        list_hdr = QHBoxLayout()
        self.file_count_label = QLabel("0 files")
        apply_info_style(self.file_count_label)
        list_hdr.addWidget(self.file_count_label)
        list_hdr.addStretch()
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear_file_list)
        list_hdr.addWidget(btn_clear)
        custom_layout.addRow(list_hdr)

        self.file_list_widget = QListWidget()
        self.file_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        custom_layout.addRow(self.file_list_widget)

        layout.addWidget(self.custom_folder_group)
        self.custom_folder_group.setVisible(False)

        return panel

    # ---- left bottom: output browser ----------------------------------

    def _create_output_browser_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(*([AppStyle.LAYOUT["panel_inner_margin"]] * 4))
        layout.setSpacing(AppStyle.LAYOUT["section_spacing"])

        title_row = QHBoxLayout()
        title = QLabel("Output Log")
        apply_subtitle_style(title)
        title_row.addWidget(title)
        title_row.addStretch()
        btn_clear_log = QPushButton("Clear")
        btn_clear_log.clicked.connect(self._clear_results_table)
        title_row.addWidget(btn_clear_log)
        layout.addLayout(title_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready")
        apply_info_style(self.status_label)
        layout.addWidget(self.status_label)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(["File", "Protocol", "Status", "Time (s)", "Message"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setMinimumHeight(120)
        layout.addWidget(self.results_table, 1)

        return panel

    # ---- right: controls panel ----------------------------------------

    def _create_controls_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(*([AppStyle.LAYOUT["panel_inner_margin"]] * 4))
        layout.setSpacing(AppStyle.LAYOUT["section_spacing"])

        title = QLabel("Batch Controls")
        apply_title_style(title)
        layout.addWidget(title)

        # Sources --------------------------------------------------------
        sources_group = QGroupBox("Sources")
        sources_layout = QFormLayout(sources_group)
        BaseImageTab.configure_adaptive_form_layout(sources_layout)

        self.calibration_source_combo = QComboBox()
        self.calibration_source_combo.addItems(["From calibration tab", "Custom file"])
        sources_layout.addRow("Calibration", self.calibration_source_combo)

        self.mask_source_combo = QComboBox()
        self.mask_source_combo.addItems(["From mask tab", "No mask"])
        sources_layout.addRow("Mask", self.mask_source_combo)

        self.calibration_status_label = QLabel("Calibration: from calibration tab")
        apply_info_style(self.calibration_status_label)
        sources_layout.addRow(self.calibration_status_label)

        self.mask_status_label = QLabel("Mask: from mask tab")
        apply_info_style(self.mask_status_label)
        sources_layout.addRow(self.mask_status_label)

        self.calibration_source_combo.currentTextChanged.connect(self._refresh_source_status)
        self.mask_source_combo.currentTextChanged.connect(self._refresh_source_status)
        layout.addWidget(sources_group)

        # Output ---------------------------------------------------------
        output_group = QGroupBox("Output")
        output_layout = QFormLayout(output_group)
        BaseImageTab.configure_adaptive_form_layout(output_layout)

        out_row = QWidget()
        out_hbox = QHBoxLayout(out_row)
        out_hbox.setContentsMargins(0, 0, 0, 0)
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("Output directory…")
        out_hbox.addWidget(self.output_dir_input, 1)
        btn_browse_out = QPushButton("Browse")
        btn_browse_out.clicked.connect(self._browse_output_dir)
        out_hbox.addWidget(btn_browse_out)
        output_layout.addRow("Output dir", out_row)

        self.mirror_structure_check = QCheckBox("Mirror input subfolder structure")
        self.mirror_structure_check.setChecked(True)
        output_layout.addRow(self.mirror_structure_check)

        fmt_row = QWidget()
        fmt_hbox = QHBoxLayout(fmt_row)
        fmt_hbox.setContentsMargins(0, 0, 0, 0)
        self.fmt_png_check = QCheckBox("png")
        self.fmt_npz_check = QCheckBox("npz")
        self.fmt_npz_check.setChecked(True)
        self.fmt_csv_check = QCheckBox("csv")
        self.fmt_csv_check.setChecked(True)
        self.fmt_txt_check = QCheckBox("txt")
        for cb in (self.fmt_png_check, self.fmt_npz_check, self.fmt_csv_check, self.fmt_txt_check):
            fmt_hbox.addWidget(cb)
        fmt_hbox.addStretch()
        output_layout.addRow("Formats", fmt_row)

        layout.addWidget(output_group)

        # Protocols ------------------------------------------------------
        proto_group = QGroupBox("Protocol Queue")
        proto_vbox = QVBoxLayout(proto_group)

        proto_toolbar = QHBoxLayout()
        self.add_proto_combo = QComboBox()
        all_ops = list(REDUCTION_OPERATIONS) + list(TRANSFORM_OPERATIONS)
        self.add_proto_combo.addItems(all_ops)
        proto_toolbar.addWidget(self.add_proto_combo, 1)
        btn_add_proto = QPushButton("+ Add")
        btn_add_proto.clicked.connect(self._add_protocol_from_combo)
        proto_toolbar.addWidget(btn_add_proto)
        proto_vbox.addLayout(proto_toolbar)

        self.protocol_list = QListWidget()
        self.protocol_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.protocol_list.itemSelectionChanged.connect(self._on_protocol_selection_changed)
        self.protocol_list.model().rowsMoved.connect(self._sync_protocol_order)
        proto_vbox.addWidget(self.protocol_list)

        proto_btn_row = QHBoxLayout()
        self.remove_proto_button = QPushButton("Remove")
        self.remove_proto_button.clicked.connect(self._remove_selected_protocol)
        self.move_up_button = QPushButton("↑")
        self.move_up_button.clicked.connect(self._move_protocol_up)
        self.move_down_button = QPushButton("↓")
        self.move_down_button.clicked.connect(self._move_protocol_down)
        for b in (self.remove_proto_button, self.move_up_button, self.move_down_button):
            proto_btn_row.addWidget(b)
        proto_btn_row.addStretch()
        proto_vbox.addLayout(proto_btn_row)

        layout.addWidget(proto_group)

        # Param editor ---------------------------------------------------
        param_group = QGroupBox("Edit Selected Protocol")
        param_vbox = QVBoxLayout(param_group)
        self.param_name_label = QLabel("No protocol selected")
        apply_info_style(self.param_name_label)
        param_vbox.addWidget(self.param_name_label)
        self.param_editor = QTextEdit()
        self.param_editor.setPlaceholderText("Parameters as YAML key: value pairs")
        self.param_editor.setMaximumHeight(120)
        param_vbox.addWidget(self.param_editor)
        btn_apply_params = QPushButton("Apply Params")
        btn_apply_params.clicked.connect(self._apply_param_edit)
        param_vbox.addWidget(btn_apply_params)
        layout.addWidget(param_group)

        # Recipe import/export ------------------------------------------
        recipe_row = QHBoxLayout()
        btn_load_recipe = QPushButton("Load Recipe")
        btn_load_recipe.clicked.connect(self._load_recipe_file)
        btn_save_recipe = QPushButton("Save Recipe")
        btn_save_recipe.clicked.connect(self._save_recipe_file)
        recipe_row.addWidget(btn_load_recipe)
        recipe_row.addWidget(btn_save_recipe)
        layout.addLayout(recipe_row)

        # Monitor mode --------------------------------------------------
        monitor_group = QGroupBox("Monitor Mode")
        monitor_layout = QFormLayout(monitor_group)
        BaseImageTab.configure_adaptive_form_layout(monitor_layout)

        self.monitor_check = QCheckBox("Watch input folder for new files")
        self.monitor_check.toggled.connect(self._on_monitor_toggled)
        monitor_layout.addRow(self.monitor_check)

        self.monitor_interval_spin = QSpinBox()
        self.monitor_interval_spin.setRange(2, 300)
        self.monitor_interval_spin.setValue(10)
        self.monitor_interval_spin.setSuffix(" s")
        monitor_layout.addRow("Interval", self.monitor_interval_spin)

        self.monitor_status_label = QLabel("Monitoring: off")
        apply_info_style(self.monitor_status_label)
        monitor_layout.addRow(self.monitor_status_label)

        layout.addWidget(monitor_group)

        # Run controls --------------------------------------------------
        run_row = QHBoxLayout()
        self.run_button = QPushButton("Run Batch")
        apply_emphasis_button_style(self.run_button)
        self.run_button.clicked.connect(self._start_batch)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._stop_batch)
        self.stop_button.setEnabled(False)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.stop_button)
        layout.addLayout(run_row)

        layout.addStretch()
        return panel

    # ------------------------------------------------------------------
    # Tab activation
    # ------------------------------------------------------------------

    def showEvent(self, event):
        """Refresh browser-mode status every time the tab becomes visible."""
        super().showEvent(event)
        if self.file_source_combo.currentIndex() == 0:
            self._refresh_file_source_status()

    # ------------------------------------------------------------------
    # File source
    # ------------------------------------------------------------------

    def _on_file_source_changed(self, index: int):
        is_browser = index == 0
        self.browser_info_group.setVisible(is_browser)
        self.custom_folder_group.setVisible(not is_browser)
        if is_browser:
            self._refresh_file_source_status()

    def _find_browser_tab(self):
        """Return the first tab that exposes get_current_file_list."""
        for i in range(self.parent_app.tab_widget.count()):
            tab = self.parent_app.tab_widget.widget(i)
            if hasattr(tab, "get_current_file_list"):
                return tab
        return None

    def _refresh_file_source_status(self):
        """Update browser-mode read-only labels. No file list is copied."""
        browser = self._find_browser_tab()
        if browser is None:
            self.browser_folder_label.setText("—")
            self.browser_pattern_label.setText("—")
            self.browser_count_label.setText("— files available")
            return
        folder_widget = getattr(browser, "folder_path_input", None)
        pattern_widget = getattr(browser, "pattern_input", None)
        folder_text = folder_widget.text() if folder_widget else "—"
        pattern_text = pattern_widget.text() if pattern_widget else "*"
        count = len(browser.get_current_file_list())
        self.browser_folder_label.setText(folder_text or "—")
        self.browser_pattern_label.setText(pattern_text or "*")
        self.browser_count_label.setText(f"{count} files available")

    def _resolve_file_list(self) -> list[str]:
        """Return the live file list from the active source at execution time."""
        if self.file_source_combo.currentIndex() == 0:
            browser = self._find_browser_tab()
            return browser.get_current_file_list() if browser is not None else []
        return [self.file_list_widget.item(i).text() for i in range(self.file_list_widget.count())]

    def _get_input_folder(self) -> str:
        """Return the input folder from the active source."""
        if self.file_source_combo.currentIndex() == 0:
            browser = self._find_browser_tab()
            if browser is not None:
                w = getattr(browser, "folder_path_input", None)
                return w.text().strip() if w else ""
            return ""
        return self.folder_path_input.text().strip()

    def _get_input_pattern(self) -> str:
        """Return the file pattern from the active source."""
        if self.file_source_combo.currentIndex() == 0:
            browser = self._find_browser_tab()
            if browser is not None:
                w = getattr(browser, "pattern_input", None)
                return w.text().strip() if w else "*"
            return "*"
        return self.pattern_input.text().strip() or "*"

    def _get_input_recursive(self) -> bool:
        if self.file_source_combo.currentIndex() == 0:
            return False  # Image Browser doesn't expose a recursive flag
        return self.recursive_check.isChecked()

    def _browse_input_folder(self):
        folder = dialog_select_directory(self, "Select Input Folder", key="batch_input_folder")
        if folder:
            self.folder_path_input.setText(folder)
            if not self.output_dir_input.text():
                self.output_dir_input.setText(str(Path(folder).parent / "analysis"))

    def _browse_output_dir(self):
        folder = dialog_select_directory(self, "Select Output Folder", key="batch_output_folder")
        if folder:
            self.output_dir_input.setText(folder)

    def _scan_folder(self):
        folder = self.folder_path_input.text().strip()
        if not folder or not os.path.isdir(folder):
            self.parent_app.show_status("Batch: enter a valid input folder")
            return
        files = scan_folder(folder, self.pattern_input.text().strip() or "*", self.recursive_check.isChecked())
        self.file_list_widget.clear()
        for f in files:
            self.file_list_widget.addItem(QListWidgetItem(f))
        self.file_count_label.setText(f"{len(files)} files")

    def _clear_file_list(self):
        self.file_list_widget.clear()
        self.file_count_label.setText("0 files")

    # ------------------------------------------------------------------
    # Protocol queue
    # ------------------------------------------------------------------

    def _add_protocol(self, proto: BatchProtocol):
        self._protocols.append(proto)
        item = QListWidgetItem(self._protocol_label(proto))
        item.setCheckState(Qt.Checked if proto.enabled else Qt.Unchecked)
        self.protocol_list.addItem(item)

    def _add_protocol_from_combo(self):
        op = self.add_proto_combo.currentText()
        proto = BatchProtocol(
            name=op,
            operation=op,
            params=dict(_DEFAULT_PARAMS.get(op, {})),
            source="manual",
        )
        self._add_protocol(proto)

    def receive_recipe(self, key: str, payload: dict[str, Any]):
        """Called by the main app when reduction/transform tabs push a recipe."""
        op = payload.get("operation", "")
        if not op:
            return
        params = {k: v for k, v in payload.items() if k not in ("operation", "name", "source_path")}
        proto = BatchProtocol(
            name=payload.get("name", key),
            operation=op,
            params=params,
            source=payload.get("source", "external"),
        )
        # Update existing entry if same name, otherwise append.
        for i, existing in enumerate(self._protocols):
            if existing.name == proto.name:
                self._protocols[i] = proto
                self.protocol_list.item(i).setText(self._protocol_label(proto))
                self.parent_app.show_status(f"Batch: updated protocol '{proto.name}'")
                return
        self._add_protocol(proto)
        self.parent_app.show_status(f"Batch: added protocol '{proto.name}' from {proto.source}")

    def _remove_selected_protocol(self):
        row = self.protocol_list.currentRow()
        if row < 0:
            return
        self.protocol_list.takeItem(row)
        del self._protocols[row]
        self._clear_param_editor()

    def _move_protocol_up(self):
        row = self.protocol_list.currentRow()
        if row <= 0:
            return
        self._protocols[row - 1], self._protocols[row] = self._protocols[row], self._protocols[row - 1]
        item = self.protocol_list.takeItem(row)
        self.protocol_list.insertItem(row - 1, item)
        self.protocol_list.setCurrentRow(row - 1)

    def _move_protocol_down(self):
        row = self.protocol_list.currentRow()
        if row < 0 or row >= len(self._protocols) - 1:
            return
        self._protocols[row], self._protocols[row + 1] = self._protocols[row + 1], self._protocols[row]
        item = self.protocol_list.takeItem(row)
        self.protocol_list.insertItem(row + 1, item)
        self.protocol_list.setCurrentRow(row + 1)

    def _sync_protocol_order(self):
        """Re-align _protocols list after drag-drop reorder."""
        new_order: list[BatchProtocol] = []
        for i in range(self.protocol_list.count()):
            label = self.protocol_list.item(i).text()
            # match by label; fall back to position if ambiguous
            for proto in self._protocols:
                if self._protocol_label(proto) == label and proto not in new_order:
                    new_order.append(proto)
                    break
        if len(new_order) == len(self._protocols):
            self._protocols = new_order

    @staticmethod
    def _protocol_label(proto: BatchProtocol) -> str:
        return f"[{proto.kind()[:3].upper()}] {proto.name}"

    def _on_protocol_selection_changed(self):
        row = self.protocol_list.currentRow()
        if row < 0 or row >= len(self._protocols):
            self._clear_param_editor()
            return
        proto = self._protocols[row]
        self.param_name_label.setText(f"{proto.name}  ({proto.operation})")
        self.param_editor.setPlainText(yaml.safe_dump(proto.params, sort_keys=False))

    def _apply_param_edit(self):
        row = self.protocol_list.currentRow()
        if row < 0 or row >= len(self._protocols):
            return
        try:
            new_params = yaml.safe_load(self.param_editor.toPlainText()) or {}
            if not isinstance(new_params, dict):
                raise ValueError("Params must be a YAML mapping")
            self._protocols[row].params = new_params
            self.protocol_list.item(row).setText(self._protocol_label(self._protocols[row]))
            self.parent_app.show_status("Batch: protocol params updated")
        except Exception as exc:
            self.parent_app.show_status(f"Batch: invalid YAML params — {exc}")

    def _clear_param_editor(self):
        self.param_name_label.setText("No protocol selected")
        self.param_editor.clear()

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def _selected_calibration(self):
        if self.calibration_source_combo.currentText() == "Custom file":
            return getattr(self, "_custom_calibration", None)
        if hasattr(self.parent_app, "get_shared_calibration"):
            return self.parent_app.get_shared_calibration()
        return getattr(self.parent_app, "calibration", None)

    def _selected_mask(self):
        if self.mask_source_combo.currentText() == "No mask":
            return None
        if hasattr(self.parent_app, "get_shared_mask"):
            return self.parent_app.get_shared_mask()
        return getattr(self.parent_app, "mask", None)

    def _refresh_source_status(self, *_):
        cal = self._selected_calibration()
        mask = self._selected_mask()
        src_cal = self.calibration_source_combo.currentText()
        src_mask = self.mask_source_combo.currentText()

        if src_cal == "Custom file":
            lbl = getattr(self, "_custom_calibration_label", "None")
            self.calibration_status_label.setText(f"Calibration: custom ({lbl})")
        else:
            status = "" if cal is not None else " (not loaded)"
            self.calibration_status_label.setText(f"Calibration: from calibration tab{status}")

        if src_mask == "No mask":
            self.mask_status_label.setText("Mask: disabled")
        else:
            status = "" if mask is not None else " (not loaded)"
            self.mask_status_label.setText(f"Mask: from mask tab{status}")

    # ------------------------------------------------------------------
    # Recipe file I/O
    # ------------------------------------------------------------------

    def _save_recipe_file(self):
        payload = {
            "protocols": [p.to_dict() for p in self._protocols],
            "output_formats": self._selected_formats(),
            "mirror_structure": self.mirror_structure_check.isChecked(),
        }
        path, _ = dialog_save_file(
            self,
            "Save Batch Recipe",
            "batch_recipe.yaml",
            "YAML files (*.yaml *.yml);;JSON files (*.json);;All files (*)",
            key="batch_recipe_save",
        )
        if not path:
            return
        p = Path(path)
        with p.open("w", encoding="utf-8") as fh:
            if p.suffix.lower() == ".json":
                json.dump(payload, fh, indent=2)
            else:
                yaml.safe_dump(payload, fh, sort_keys=False)
        self.parent_app.show_status(f"Batch recipe saved to {p}")

    def _load_recipe_file(self):
        path, _ = dialog_open_file(
            self,
            "Load Batch Recipe",
            "YAML/JSON files (*.yaml *.yml *.json);;All files (*)",
            key="batch_recipe_load",
        )
        if not path:
            return
        try:
            raw = Path(path).read_text(encoding="utf-8")
            payload = yaml.safe_load(raw) if path.endswith((".yaml", ".yml")) else json.loads(raw)
            self.protocol_list.clear()
            self._protocols.clear()
            for proto_dict in payload.get("protocols", []):
                self._add_protocol(BatchProtocol.from_dict(proto_dict))
            fmts = payload.get("output_formats", [])
            self.fmt_png_check.setChecked("png" in fmts)
            self.fmt_npz_check.setChecked("npz" in fmts)
            self.fmt_csv_check.setChecked("csv" in fmts)
            self.fmt_txt_check.setChecked("txt" in fmts)
            self.mirror_structure_check.setChecked(bool(payload.get("mirror_structure", True)))
            self.parent_app.show_status(f"Batch recipe loaded: {len(self._protocols)} protocols")
        except Exception as exc:
            self.parent_app.show_status(f"Batch: failed to load recipe — {exc}")

    # ------------------------------------------------------------------
    # Run / Stop
    # ------------------------------------------------------------------

    def _selected_formats(self) -> list[str]:
        fmts = []
        for cb, name in ((self.fmt_png_check, "png"), (self.fmt_npz_check, "npz"),
                         (self.fmt_csv_check, "csv"), (self.fmt_txt_check, "txt")):
            if cb.isChecked():
                fmts.append(name)
        return fmts or ["csv"]

    def _build_job(self, file_list: list[str] | None = None) -> BatchJob | None:
        files = file_list if file_list is not None else self._resolve_file_list()
        if not files:
            self.parent_app.show_status("Batch: no input files")
            return None
        active = [p for p in self._protocols if p.enabled]
        if not active:
            self.parent_app.show_status("Batch: no enabled protocols")
            return None
        output_dir = self.output_dir_input.text().strip()
        if not output_dir:
            # Auto-fill output dir from input folder when not set.
            input_folder = self._get_input_folder()
            if input_folder:
                output_dir = str(Path(input_folder).parent / "analysis")
                self.output_dir_input.setText(output_dir)
        if not output_dir:
            self.parent_app.show_status("Batch: specify an output directory")
            return None
        return BatchJob(
            file_paths=files,
            protocols=active,
            output_dir=output_dir,
            output_formats=self._selected_formats(),
            calibration=self._selected_calibration(),
            mask=self._selected_mask(),
            mirror_input_structure=self.mirror_structure_check.isChecked(),
            input_root=self._get_input_folder(),
        )

    def _start_batch(self, file_list: list[str] | None = None):
        if self._runner is not None and self._runner.isRunning():
            return
        job = self._build_job(file_list)
        if job is None:
            return
        # Sync enabled state from list widget checkboxes before running.
        for i, proto in enumerate(self._protocols):
            item = self.protocol_list.item(i)
            if item is not None:
                proto.enabled = item.checkState() == Qt.Checked

        self._refresh_source_status()
        total = len(job.file_paths) * len(job.protocols)
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(0)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Running…")

        self._runner = BatchRunner(job)
        self._runner.progress.connect(self._on_progress)
        self._runner.file_done.connect(self._on_file_done)
        self._runner.status_changed.connect(self._on_status_changed)
        self._runner.finished_batch.connect(self._on_batch_finished)
        self._runner.start()

    def _stop_batch(self):
        if self._runner is not None:
            self._runner.request_stop()

    def _on_progress(self, done: int, total: int, label: str):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        self.status_label.setText(label)

    def _on_file_done(self, result: BatchFileResult):
        self._results.append(result)
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        self.results_table.setItem(row, 0, QTableWidgetItem(os.path.basename(result.file_path)))
        self.results_table.setItem(row, 1, QTableWidgetItem(result.protocol_name))
        self.results_table.setItem(row, 2, QTableWidgetItem(_STATUS_SYMBOL.get(result.status, result.status)))
        self.results_table.setItem(row, 3, QTableWidgetItem(f"{result.elapsed_s:.2f}"))
        self.results_table.setItem(row, 4, QTableWidgetItem(result.message or result.output_path))
        self.results_table.scrollToBottom()

    def _on_status_changed(self, msg: str):
        self.status_label.setText(msg)

    def _on_batch_finished(self, ok: int, err: int):
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.parent_app.show_status(f"Batch done — {ok} succeeded, {err} failed")

    def _clear_results_table(self):
        self.results_table.setRowCount(0)
        self._results.clear()

    # ------------------------------------------------------------------
    # Monitor mode
    # ------------------------------------------------------------------

    def _on_monitor_toggled(self, checked: bool):
        if checked:
            folder = self._get_input_folder()
            if not folder or not os.path.isdir(folder):
                self.monitor_check.setChecked(False)
                self.parent_app.show_status("Batch monitor: no valid input folder")
                return
            self._monitor_seen = set(self._resolve_file_list())
            self._monitor_mtime_cache = {}
            interval_ms = self.monitor_interval_spin.value() * 1000
            self._monitor_timer.start(interval_ms)
            self.monitor_status_label.setText(f"Monitoring: ON (every {self.monitor_interval_spin.value()} s)")
        else:
            self._monitor_timer.stop()
            self.monitor_status_label.setText("Monitoring: off")

    def _poll_monitor(self):
        folder = self._get_input_folder()
        if not folder or not os.path.isdir(folder):
            return
        new_files = new_files_in_folder(
            folder, self._get_input_pattern(), self._get_input_recursive(),
            self._monitor_seen, self._monitor_mtime_cache,
        )
        if not new_files:
            return
        self.monitor_status_label.setText(
            f"Monitoring: ON \u2014 {len(new_files)} new file(s) at {time.strftime('%H:%M:%S')}"
        )
        self._start_batch(new_files)
