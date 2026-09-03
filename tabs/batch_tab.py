"""Batch processing tab - minimal working version."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import yaml
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from sciview.interfaces.stable_qt.utils.file_dialog_state import (
    dialog_open_file, dialog_save_file, dialog_select_directory,
)
from sciview.interfaces.theme.app_style import (
    AppStyle, apply_emphasis_button_style, apply_info_style,
    apply_subtitle_style, apply_title_style, setup_splitter_layout,
)
from sciview.processing.batch import (
    REDUCTION_OPERATIONS, TRANSFORM_OPERATIONS,
    BatchFileResult, BatchJob, BatchProtocol, BatchRunner,
)
from tabs.base_image_tab import BaseImageTab


# Param names match SciAnalysis Protocol __init__ kwargs exactly (ref: runMAXS.py).
# plot_range is NOT stored here — it is injected at run time from calibration.
_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "circular_average": {
        "bins_relative": 1.0,
        "ylog": True,
        "gridlines": True,
        "save_results": ["plots", "txt"],
    },
    "sector_average": {
        "angle": 90.0,     # center angle (deg); 0=horizontal, 90=vertical
        "dangle": 20.0,    # half-width (deg)
        "bins_relative": 1.0,
        "ylog": True,
        "save_results": ["plots", "txt"],
    },
    "line_profile": {
        "chi0": 0.0,       # azimuthal angle (deg)
        "dq": 0.01,        # q half-width (1/Å)
        "save_results": ["plots", "txt"],
    },
    "q_image": {
        # plot_range=[qx_min, qx_max, qz_min, qz_max] injected from calibration at run time
        "save_results": ["plots", "npz"],
    },
    "q_phi_image": {
        "bins_relative": 0.5,
        "phi_min": -180.0,  # consumed by apply_q_bounds_to_protocol → plot_range[2]
        "phi_max":  180.0,  # consumed by apply_q_bounds_to_protocol → plot_range[3]
        "save_results": ["plots", "npz"],
    },
    "qr_qz_image": {
        "bins_relative": 0.5,
        # plot_range=[qx_min, qx_max, qz_min, qz_max] injected from calibration at run time
        "save_results": ["plots", "npz"],
    },
    "thumbnails": {
        "resize": 1,
        "blur": 0.0,
        "ztrim": [0.05, 0.001],
        "save_results": ["plots"],
    },
}

_STATUS_SYMBOL = {"ok": "OK", "error": "ERR", "skipped": "---", "running": "..."}


class BatchTab(QWidget):
    """Minimal batch tab: load files explicitly, configure protocols, run."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        # Batch-owned file list — populated by clicking "Load from Session".
        self._file_paths: list[str] = []

        self._protocols: list[BatchProtocol] = []
        self._runner: BatchRunner | None = None
        self._results: list[BatchFileResult] = []
        self._selected_proto_row: int = -1  # tracks row for auto-save on switch

        self._build_ui()

    # ------------------------------------------------------------------
    # Session helper
    # ------------------------------------------------------------------

    def _find_image_browser(self):
        """Return the tab that owns session_manager, or None."""
        for i in range(self.parent_app.tab_widget.count()):
            tab = self.parent_app.tab_widget.widget(i)
            if hasattr(tab, "session_manager"):
                return tab
        return None

    def _load_from_session(self) -> None:
        """Copy file paths from Image Browser session into Batch's own list."""
        browser = self._find_image_browser()
        if browser is None:
            self.parent_app.show_status("Batch: Image Browser tab not found")
            return

        paths = []
        for img in browser.session_manager.images:
            p = str(img.get("path", "")).strip()
            if p and not p.startswith("tiled://"):
                paths.append(p)

        self._file_paths = paths
        self._file_list_widget.clear()
        for p in paths:
            self._file_list_widget.addItem(os.path.basename(p))

        self._file_count_label.setText(f"{len(paths)} file(s) loaded")
        self.parent_app.show_status(f"Batch: {len(paths)} file(s) loaded from Image Browser session")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        left = QSplitter(Qt.Vertical)
        left.addWidget(self._build_file_panel())
        left.addWidget(self._build_log_panel())
        setup_splitter_layout(left, [1, 1])
        splitter.addWidget(left)

        right_widget = QWidget()
        rl = QVBoxLayout(right_widget)
        m = AppStyle.LAYOUT["panel_inner_margin"]
        rl.setContentsMargins(m, m, m, m)
        rl.setSpacing(AppStyle.LAYOUT["section_spacing"])
        rl.addWidget(BaseImageTab.make_scrollable_panel(self._build_controls_panel()))
        splitter.addWidget(right_widget)

        setup_splitter_layout(splitter, AppStyle.get_layout_ratios()["main_splitter_ratio"])
        root.addWidget(splitter)

    def _build_file_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        m = AppStyle.LAYOUT["panel_inner_margin"]
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(AppStyle.LAYOUT["section_spacing"])

        title = QLabel("Input Files")
        apply_title_style(title)
        lay.addWidget(title)

        group = QGroupBox("File List")
        form = QVBoxLayout(group)

        btn_load = QPushButton("Load Files from Image Browser Session")
        apply_emphasis_button_style(btn_load)
        btn_load.clicked.connect(self._load_from_session)
        form.addWidget(btn_load)

        self._file_count_label = QLabel("0 file(s) loaded — click the button above")
        apply_info_style(self._file_count_label)
        form.addWidget(self._file_count_label)

        self._file_list_widget = QListWidget()
        self._file_list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self._file_list_widget.setMinimumHeight(80)
        form.addWidget(self._file_list_widget)

        lay.addWidget(group)
        lay.addStretch()
        return panel

    def _build_log_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        m = AppStyle.LAYOUT["panel_inner_margin"]
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(AppStyle.LAYOUT["section_spacing"])

        hdr = QHBoxLayout()
        lbl = QLabel("Output Log")
        apply_subtitle_style(lbl)
        hdr.addWidget(lbl)
        hdr.addStretch()
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear_log)
        hdr.addWidget(btn_clear)
        lay.addLayout(hdr)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        lay.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready")
        apply_info_style(self.status_label)
        lay.addWidget(self.status_label)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(
            ["File", "Protocol", "Status", "Time (s)", "Message"]
        )
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setMinimumHeight(120)
        lay.addWidget(self.results_table, 1)
        return panel

    def _build_controls_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        m = AppStyle.LAYOUT["panel_inner_margin"]
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(AppStyle.LAYOUT["section_spacing"])

        title = QLabel("Batch Controls")
        apply_title_style(title)
        lay.addWidget(title)

        # Output directory
        out_group = QGroupBox("Output")
        out_form = QFormLayout(out_group)
        BaseImageTab.configure_adaptive_form_layout(out_form)

        out_row = QWidget()
        oh = QHBoxLayout(out_row)
        oh.setContentsMargins(0, 0, 0, 0)
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("Output directory...")
        oh.addWidget(self.output_dir_input, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self._browse_output)
        oh.addWidget(btn_browse)
        out_form.addRow("Output dir", out_row)

        self.mirror_check = QCheckBox("Mirror input subfolder structure")
        self.mirror_check.setChecked(True)
        out_form.addRow(self.mirror_check)
        lay.addWidget(out_group)

        # Protocol queue
        proto_group = QGroupBox("Protocol Queue")
        pv = QVBoxLayout(proto_group)

        tb = QHBoxLayout()
        self.proto_combo = QComboBox()
        self.proto_combo.addItems(list(REDUCTION_OPERATIONS) + list(TRANSFORM_OPERATIONS))
        tb.addWidget(self.proto_combo, 1)
        btn_add = QPushButton("+ Add")
        btn_add.clicked.connect(self._add_protocol_from_combo)
        tb.addWidget(btn_add)
        pv.addLayout(tb)

        self.protocol_list = QListWidget()
        self.protocol_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.protocol_list.itemSelectionChanged.connect(self._on_protocol_selected)
        self.protocol_list.model().rowsMoved.connect(self._sync_protocol_order)
        pv.addWidget(self.protocol_list)

        br = QHBoxLayout()
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.clicked.connect(self._remove_protocol)
        self.btn_up = QPushButton("↑"); self.btn_up.clicked.connect(self._move_up)
        self.btn_dn = QPushButton("↓"); self.btn_dn.clicked.connect(self._move_down)
        for b in (self.btn_remove, self.btn_up, self.btn_dn):
            br.addWidget(b)
        br.addStretch()
        pv.addLayout(br)
        lay.addWidget(proto_group)

        # Param editor
        pg = QGroupBox("Edit Selected Protocol")
        pgl = QVBoxLayout(pg)
        self.param_name_label = QLabel("No protocol selected")
        apply_info_style(self.param_name_label)
        pgl.addWidget(self.param_name_label)
        self.param_editor = QTextEdit()
        self.param_editor.setPlaceholderText("YAML key: value params")
        self.param_editor.setMaximumHeight(100)
        pgl.addWidget(self.param_editor)
        btn_row = QHBoxLayout()
        btn_apply = QPushButton("Apply Params")
        btn_apply.clicked.connect(self._apply_params)
        btn_row.addWidget(btn_apply)
        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._reset_params)
        btn_row.addWidget(btn_reset)
        pgl.addLayout(btn_row)
        lay.addWidget(pg)

        # Recipe I/O
        rr = QHBoxLayout()
        btn_ld = QPushButton("Load Recipe"); btn_ld.clicked.connect(self._load_recipe)
        btn_sv = QPushButton("Save Recipe"); btn_sv.clicked.connect(self._save_recipe)
        rr.addWidget(btn_ld); rr.addWidget(btn_sv)
        lay.addLayout(rr)

        # Run / Stop
        run_row = QHBoxLayout()
        self.run_button = QPushButton("Run Batch")
        apply_emphasis_button_style(self.run_button)
        self.run_button.clicked.connect(lambda: self._start_batch())
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._stop_batch)
        self.stop_button.setEnabled(False)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.stop_button)
        lay.addLayout(run_row)

        lay.addStretch()
        return panel

    # ------------------------------------------------------------------
    # Protocol queue
    # ------------------------------------------------------------------

    @staticmethod
    def _proto_label(p: BatchProtocol) -> str:
        return f"[{p.kind()[:3].upper()}] {p.name}"

    def _show_protocol_params(self, row: int) -> None:
        if 0 <= row < len(self._protocols):
            proto = self._protocols[row]
            self._selected_proto_row = row
            self.param_name_label.setText(f"{proto.name}  ({proto.operation})")
            self.param_editor.setPlainText(yaml.safe_dump(proto.params, sort_keys=False))

    def _add_protocol(self, proto: BatchProtocol, select: bool = True) -> None:
        self._protocols.append(proto)
        item = QListWidgetItem(self._proto_label(proto))
        item.setCheckState(Qt.Checked)
        self.protocol_list.addItem(item)
        if select:
            new_row = len(self._protocols) - 1
            self.protocol_list.setCurrentRow(new_row)
            self._show_protocol_params(new_row)

    def _add_protocol_from_combo(self) -> None:
        op = self.proto_combo.currentText()
        self._add_protocol(BatchProtocol(
            name=op, operation=op,
            params=dict(_DEFAULT_PARAMS.get(op, {})),
            source="manual",
        ), select=True)

    def receive_recipe(self, key: str, payload: dict[str, Any]) -> None:
        op = payload.get("operation", "")
        if not op:
            return
        # Tabs push SA-compatible params directly; strip routing keys only.
        params = {k: v for k, v in payload.items()
                  if k not in ("operation", "name", "source")}
        proto = BatchProtocol(
            name=payload.get("name", key), operation=op,
            params=params, source=payload.get("source", "external"),
        )
        for i, ex in enumerate(self._protocols):
            if ex.name == proto.name:
                self._protocols[i] = proto
                self.protocol_list.item(i).setText(self._proto_label(proto))
                self.protocol_list.setCurrentRow(i)
                self._show_protocol_params(i)
                self.parent_app.show_status(f"Batch: updated '{proto.name}'")
                return
        self._add_protocol(proto, select=True)
        self.parent_app.show_status(f"Batch: added '{proto.name}'")

    def _remove_protocol(self) -> None:
        row = self.protocol_list.currentRow()
        if row < 0:
            return
        self._selected_proto_row = -1
        self.protocol_list.takeItem(row)
        del self._protocols[row]
        if self._protocols:
            new_row = min(row, len(self._protocols) - 1)
            self.protocol_list.setCurrentRow(new_row)
            self._show_protocol_params(new_row)
        else:
            self.param_name_label.setText("No protocol selected")
            self.param_editor.clear()

    def _move_up(self) -> None:
        row = self.protocol_list.currentRow()
        if row <= 0:
            return
        self._selected_proto_row = -1
        self._protocols[row - 1], self._protocols[row] = self._protocols[row], self._protocols[row - 1]
        item = self.protocol_list.takeItem(row)
        self.protocol_list.insertItem(row - 1, item)
        self.protocol_list.setCurrentRow(row - 1)
        self._show_protocol_params(row - 1)

    def _move_down(self) -> None:
        row = self.protocol_list.currentRow()
        if row < 0 or row >= len(self._protocols) - 1:
            return
        self._selected_proto_row = -1
        self._protocols[row], self._protocols[row + 1] = self._protocols[row + 1], self._protocols[row]
        item = self.protocol_list.takeItem(row)
        self.protocol_list.insertItem(row + 1, item)
        self.protocol_list.setCurrentRow(row + 1)
        self._show_protocol_params(row + 1)

    def _sync_protocol_order(self) -> None:
        new_order: list[BatchProtocol] = []
        for i in range(self.protocol_list.count()):
            label = self.protocol_list.item(i).text()
            for proto in self._protocols:
                if self._proto_label(proto) == label and proto not in new_order:
                    new_order.append(proto)
                    break
        if len(new_order) == len(self._protocols):
            self._protocols = new_order
            row = self.protocol_list.currentRow()
            if 0 <= row < len(self._protocols):
                self._show_protocol_params(row)

    def _on_protocol_selected(self) -> None:
        # Auto-save edits for the protocol that was just deselected.
        prev = self._selected_proto_row
        row = self.protocol_list.currentRow()
        if 0 <= prev < len(self._protocols) and prev != row:
            try:
                saved = yaml.safe_load(self.param_editor.toPlainText()) or {}
                if isinstance(saved, dict):
                    self._protocols[prev].params = saved
            except Exception:
                pass  # skip invalid YAML mid-edit

        if row < 0 or row >= len(self._protocols):
            self._selected_proto_row = -1
            self.param_name_label.setText("No protocol selected")
            self.param_editor.clear()
            return

        self._show_protocol_params(row)

    def _apply_params(self) -> None:
        row = self.protocol_list.currentRow()
        if row < 0 or row >= len(self._protocols):
            return
        try:
            new_params = yaml.safe_load(self.param_editor.toPlainText()) or {}
            if not isinstance(new_params, dict):
                raise ValueError("must be a YAML mapping")
            self._protocols[row].params = new_params
            self._selected_proto_row = row
            self.protocol_list.item(row).setText(self._proto_label(self._protocols[row]))
            self.parent_app.show_status("Batch: params updated")
        except Exception as exc:
            self.parent_app.show_status(f"Batch: invalid YAML \u2014 {exc}")

    def _reset_params(self) -> None:
        """Reset the selected protocol to its registered default params."""
        row = self.protocol_list.currentRow()
        if row < 0 or row >= len(self._protocols):
            return
        proto = self._protocols[row]
        defaults = dict(_DEFAULT_PARAMS.get(proto.operation, {}))
        if not defaults:
            self.parent_app.show_status(f"Batch: no defaults registered for '{proto.operation}'")
            return
        proto.params = defaults
        self._selected_proto_row = row
        self.param_editor.setPlainText(yaml.safe_dump(defaults, sort_keys=False))
        self.parent_app.show_status(f"Batch: reset '{proto.name}' params to defaults")

    # ------------------------------------------------------------------
    # Recipe I/O
    # ------------------------------------------------------------------

    def _selected_formats(self) -> list[str]:
        # Formats are now per-protocol via save_results in params; this is kept for BatchJob compat.
        return []

    def _save_recipe(self) -> None:
        payload = {
            "protocols": [p.to_dict() for p in self._protocols],
            "output_formats": self._selected_formats(),
        }
        path, _ = dialog_save_file(
            self, "Save Batch Recipe", "batch_recipe.yaml",
            "YAML files (*.yaml *.yml);;JSON files (*.json);;All files (*)",
            key="batch_recipe_save",
        )
        if not path:
            return
        p = Path(path)
        with p.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False) if p.suffix.lower() != ".json" else __import__("json").dump(payload, fh, indent=2)
        self.parent_app.show_status(f"Recipe saved to {p.name}")

    def _load_recipe(self) -> None:
        path, _ = dialog_open_file(
            self, "Load Batch Recipe",
            "YAML/JSON files (*.yaml *.yml *.json);;All files (*)",
            key="batch_recipe_load",
        )
        if not path:
            return
        try:
            raw = Path(path).read_text(encoding="utf-8")
            payload = yaml.safe_load(raw) if path.endswith((".yaml", ".yml")) else __import__("json").loads(raw)
            self._selected_proto_row = -1
            self.protocol_list.clear()
            self._protocols.clear()
            for d in payload.get("protocols", []):
                self._add_protocol(BatchProtocol.from_dict(d), select=False)
            if self._protocols:
                self.protocol_list.setCurrentRow(0)
                self._show_protocol_params(0)
            else:
                self.param_name_label.setText("No protocol selected")
                self.param_editor.clear()
            self.parent_app.show_status(f"Recipe loaded: {len(self._protocols)} protocols")
        except Exception as exc:
            self.parent_app.show_status(f"Batch: load failed — {exc}")

    # ------------------------------------------------------------------
    # Run / Stop
    # ------------------------------------------------------------------

    def _browse_output(self) -> None:
        folder = dialog_select_directory(self, "Select Output Folder", key="batch_output_folder")
        if folder:
            self.output_dir_input.setText(folder)

    def _start_batch(self) -> None:
        # Auto-apply any pending param edits for the currently selected protocol.
        self._apply_params()

        if self._runner is not None and self._runner.isRunning():
            return

        if not self._file_paths:
            self.parent_app.show_status(
                "Batch: no files — click 'Load Files from Image Browser Session' first"
            )
            return

        # Sync checkbox enabled state before building job.
        for i, proto in enumerate(self._protocols):
            item = self.protocol_list.item(i)
            if item is not None:
                proto.enabled = item.checkState() == Qt.Checked

        active = [p for p in self._protocols if p.enabled]
        if not active:
            self.parent_app.show_status("Batch: no enabled protocols")
            return

        output_dir = self.output_dir_input.text().strip()
        if not output_dir:
            output_dir = str(Path(self._file_paths[0]).parent.parent / "analysis")
            self.output_dir_input.setText(output_dir)

        cal = getattr(self.parent_app, "calibration", None)
        if hasattr(self.parent_app, "get_shared_calibration"):
            shared_cal = self.parent_app.get_shared_calibration()
            if shared_cal is not None:
                cal = shared_cal

        mask = getattr(self.parent_app, "mask", None)
        if hasattr(self.parent_app, "get_shared_mask"):
            shared_mask = self.parent_app.get_shared_mask()
            if shared_mask is not None:
                mask = shared_mask

        job = BatchJob(
            file_paths=list(self._file_paths),
            protocols=active,
            output_dir=output_dir,
            output_formats=self._selected_formats(),
            calibration=cal,
            mask=mask,
            mirror_input_structure=True,
            input_root=str(Path(self._file_paths[0]).parent),
        )

        total = len(job.file_paths) * max(len(active), 1)
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(0)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Running...")

        self._runner = BatchRunner(job)
        self._runner.progress.connect(self._on_progress)
        self._runner.file_done.connect(self._on_file_done)
        self._runner.status_changed.connect(self.status_label.setText)
        self._runner.finished_batch.connect(self._on_finished)
        self._runner.start()

    def _stop_batch(self) -> None:
        if self._runner is not None:
            self._runner.request_stop()

    def _on_progress(self, done: int, total: int, label: str) -> None:
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        self.status_label.setText(label)

    def _on_file_done(self, result: BatchFileResult) -> None:
        self._results.append(result)
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        self.results_table.setItem(row, 0, QTableWidgetItem(os.path.basename(result.file_path)))
        self.results_table.setItem(row, 1, QTableWidgetItem(result.protocol_name))
        self.results_table.setItem(row, 2, QTableWidgetItem(_STATUS_SYMBOL.get(result.status, result.status)))
        self.results_table.setItem(row, 3, QTableWidgetItem(f"{result.elapsed_s:.2f}"))
        self.results_table.setItem(row, 4, QTableWidgetItem(result.message or result.output_path))
        self.results_table.scrollToBottom()

    def _on_finished(self, ok: int, err: int) -> None:
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.parent_app.show_status(f"Batch done — {ok} succeeded, {err} failed")
        self._save_cookbook()

    def _save_cookbook(self) -> None:
        """Save a complete run record (cookbook) alongside the output for provenance."""
        output_dir = self.output_dir_input.text().strip()
        if not output_dir:
            return
        import datetime
        from sciview.processing.batch import compute_q_bounds
        cal = getattr(self.parent_app, "calibration", None)
        mask = getattr(self.parent_app, "mask", None)
        bounds = compute_q_bounds(cal)  # calibration-derived bounds used for this run
        cookbook = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "sciview_version": getattr(self.parent_app, "_scianalysis_source_mode", "unknown"),
            "input_files": list(self._file_paths),
            "output_dir": output_dir,
            "calibration": {
                "type": type(cal).__name__ if cal is not None else "none",
                "wavelength_A": getattr(cal, "wavelength_A", None),
                "distance_m": getattr(cal, "distance_m", getattr(cal, "_distance_m", None)),
                "pixel_size_um": getattr(cal, "pixel_size_um", getattr(cal, "_pixel_size_um", None)),
                "beam_center_x": getattr(cal, "x0", None),
                "beam_center_y": getattr(cal, "y0", None),
            },
            "q_bounds": bounds,
            "mask": {"type": type(mask).__name__ if mask is not None else "none"},
            "protocols": [
                {"name": p.name, "operation": p.operation, "params": dict(p.params)}
                for p in self._protocols
                if p.enabled
            ],
            "results": [
                {
                    "file": os.path.basename(r.file_path),
                    "protocol": r.protocol_name,
                    "status": r.status,
                    "elapsed_s": r.elapsed_s,
                    "output_path": r.output_path,
                    "message": r.message,
                }
                for r in self._results
            ],
        }
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out = Path(output_dir) / f"batch_cookbook_{ts}.yaml"
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(cookbook, fh, sort_keys=False, allow_unicode=True)
            self.parent_app.show_status(
                f"Batch done — {len([r for r in self._results if r.status=='ok'])} OK  "
                f"| cookbook saved to {out.name}"
            )
        except Exception as exc:
            self.parent_app.show_status(
                f"Batch done — cookbook save failed: {exc}"
            )

    def _clear_log(self) -> None:
        self.results_table.setRowCount(0)
        self._results.clear()
