"""Tiled browser tab for proposal-based metadata search and image display."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Callable

import numpy as np
from PyQt5.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QApplication,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from sciview.interfaces.theme.app_style import (
    AppStyle,
    apply_info_style,
    apply_subtitle_style,
    apply_sync_button_style,
    setup_splitter_layout,
    apply_title_style,
)
from sciview.interfaces.services.image_service import ImageService
from sciview.sources.tiled_source import TiledScanSummary
from tabs.base_image_tab import BaseImageTab


class _OperationWorker(QObject):
    finished = pyqtSignal(int, object, object)
    progress_updated = pyqtSignal(int, str)
    retry_detected = pyqtSignal(int, str)

    def __init__(self, token: int, action: Callable):
        super().__init__()
        self.token = token
        self.action = action

    def run(self) -> None:
        try:
            self.finished.emit(self.token, self.action(), None)
        except Exception as exc:
            self.finished.emit(self.token, None, exc)


class TiledBrowserTab(BaseImageTab):
    """Browse Tiled scans through backend service APIs."""

    def __init__(self, parent_app):
        super().__init__(parent_app)
        self.image_service = ImageService()
        self.scan_rows: list[TiledScanSummary] = []
        self.current_scan: TiledScanSummary | None = None
        self.current_image_array = None
        self.current_frame_array = None
        self.current_image_source = None
        self.current_detector = ""
        self._operation_token = 0
        self._active_thread: QThread | None = None
        self._active_worker: _OperationWorker | None = None

        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._advance_playback)

        self._build_ui()
        self._initialize_defaults()

    def _begin_operation(self, message: str) -> int:
        self._stop_playback()
        self._operation_token += 1
        self.parent_app.show_status(message)
        self.search_status_label.setText(message)
        self.run_search_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        return self._operation_token

    def _finish_operation(self) -> None:
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        self.run_search_button.setEnabled(True)
        self.load_button.setEnabled(self._selected_row() is not None)
        self.cancel_button.setEnabled(False)
        self._active_thread = None
        self._active_worker = None
        self.load_progress_bar.setVisible(False)
        self.load_retry_label.setVisible(False)

    def _run_background(self, message: str, action: Callable, on_success: Callable) -> None:
        token = self._begin_operation(message)
        thread = QThread(self)
        worker = _OperationWorker(token, action)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda done_token, result, error: self._handle_background_result(
            done_token,
            result,
            error,
            on_success,
            thread,
            worker,
        ))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._active_thread = thread
        self._active_worker = worker
        thread.start()

    def _run_background_ex(
        self,
        message: str,
        action_factory: Callable,
        on_success: Callable,
        *,
        on_progress: Callable | None = None,
        on_retry: Callable | None = None,
    ) -> None:
        """Like _run_background but injects progress/retry callbacks into the action.

        *action_factory* is called as ``action_factory(progress_cb, retry_cb)`` where
        each argument is either the corresponding signal emitter or ``None``.
        """
        token = self._begin_operation(message)
        thread = QThread(self)

        # Use mutable boxes so the action closure can capture the signal emitters
        # that are only available after the worker is created.
        prog_emit_box: list = [None]
        retry_emit_box: list = [None]

        def action():
            return action_factory(prog_emit_box[0], retry_emit_box[0])

        worker = _OperationWorker(token, action)
        if on_progress:
            worker.progress_updated.connect(on_progress)
            prog_emit_box[0] = worker.progress_updated.emit
        if on_retry:
            worker.retry_detected.connect(on_retry)
            retry_emit_box[0] = worker.retry_detected.emit
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda done_token, result, error: self._handle_background_result(
            done_token,
            result,
            error,
            on_success,
            thread,
            worker,
        ))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._active_thread = thread
        self._active_worker = worker
        thread.start()

    def _handle_background_result(
        self,
        token: int,
        result,
        error,
        on_success: Callable,
        thread: QThread,
        worker: _OperationWorker,
    ) -> None:
        del thread, worker
        if token != self._operation_token:
            return
        self._finish_operation()
        if error is not None:
            QMessageBox.warning(self, "Tiled operation failed", str(error))
            return
        on_success(result)

    def _cancel_operation(self) -> None:
        self._operation_token += 1
        self._stop_playback()
        self._finish_operation()
        self.parent_app.show_status("Cancelled current Tiled action")
        self.search_status_label.setText("Cancelled current Tiled action")

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        self._main_splitter = splitter
        root.addWidget(splitter)
        layout_cfg = AppStyle.get_layout_ratios()

        controls = QWidget()
        self._controls_panel = controls
        controls.setMinimumWidth(layout_cfg['tiled_controls_min_width'])
        controls.setMaximumWidth(layout_cfg['tiled_controls_max_width'])
        controls.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        controls_layout = QVBoxLayout(controls)
        title = QLabel("Tiled Browser")
        apply_title_style(title)
        controls_layout.addWidget(title)
        controls_layout.addWidget(self._create_connection_group())
        controls_layout.addWidget(self._create_search_group())
        controls_layout.addWidget(self._create_results_group(), 1)
        controls_layout.addWidget(self._create_playback_group())

        viewer = QWidget()
        viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        viewer_layout = QVBoxLayout(viewer)
        subtitle = QLabel("Preview")
        apply_subtitle_style(subtitle)
        viewer_layout.addWidget(subtitle)

        self.current_image_label = QLabel("No scan selected")
        apply_info_style(self.current_image_label)
        viewer_layout.addWidget(self.current_image_label)
        viewer_layout.addWidget(self._create_image_panel(), 1)
        viewer_layout.addWidget(self._create_frame_group())

        self.metadata_text = QTextEdit()
        self.metadata_text.setReadOnly(True)
        self.metadata_text.setMaximumHeight(layout_cfg['tiled_metadata_max_height'])
        apply_info_style(self.metadata_text)
        viewer_layout.addWidget(self.metadata_text)

        self.sync_button = QPushButton("Use This Image")
        self.sync_button.setEnabled(False)
        self.sync_button.clicked.connect(self._sync_to_parent)
        apply_sync_button_style(self.sync_button)
        viewer_layout.addWidget(self.sync_button)

        splitter.addWidget(controls)
        splitter.addWidget(viewer)
        setup_splitter_layout(splitter, layout_cfg['tiled_main_splitter_ratio'])
        QTimer.singleShot(0, self._apply_tiled_splitter_ratio)

    def _apply_tiled_splitter_ratio(self) -> None:
        """Apply configured splitter ratio once widget geometry is finalized."""
        if not hasattr(self, '_main_splitter') or not hasattr(self, '_controls_panel'):
            return

        layout_cfg = AppStyle.get_layout_ratios()
        ratio = layout_cfg['tiled_main_splitter_ratio']
        if not ratio or len(ratio) < 2:
            return

        total = max(self._main_splitter.width(), self.width(), 1)
        ratio_sum = ratio[0] + ratio[1]
        desired_left = int(total * (ratio[0] / ratio_sum))

        left_min = self._controls_panel.minimumWidth()
        left_max = self._controls_panel.maximumWidth()
        left = max(left_min, min(desired_left, left_max))
        right = max(1, total - left)
        self._main_splitter.setSizes([left, right])

    def _create_connection_group(self) -> QWidget:
        group = QGroupBox("1) Connection")
        layout = QFormLayout(group)

        self.catalog_combo = QComboBox()
        self.catalog_combo.currentIndexChanged.connect(self._on_catalog_changed)
        layout.addRow("Catalog:", self.catalog_combo)

        self.auth_status_label = QLabel("Status: Unknown")
        apply_info_style(self.auth_status_label)
        layout.addRow(self.auth_status_label)

        buttons = QHBoxLayout()
        self.auth_button = QPushButton("Log In")
        self.auth_button.clicked.connect(self._handle_login)
        buttons.addWidget(self.auth_button)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._refresh_auth_state)
        buttons.addWidget(self.refresh_button)
        layout.addRow(buttons)
        return group

    def _create_search_group(self) -> QWidget:
        group = QGroupBox("2) Cycle + Proposal")
        layout = QVBoxLayout(group)

        filters = QFormLayout()
        self.cycle_combo = QComboBox()
        self.cycle_combo.setEditable(True)
        self.cycle_combo.addItems(["2026-2", "2026-1", "2025-3", "2025-2", "2025-1"])
        filters.addRow("Cycle:", self.cycle_combo)

        self.proposal_input = QLineEdit()
        self.proposal_input.setPlaceholderText("320406")
        filters.addRow("Proposal ID:", self.proposal_input)

        self.measure_type_input = QLineEdit("measure")
        self.measure_type_input.setPlaceholderText("measure")
        filters.addRow("measure_type:", self.measure_type_input)

        self.sample_savename_input = QLineEdit()
        self.sample_savename_input.setPlaceholderText("AgBH* or re:^AgBH")
        filters.addRow("sample_savename:", self.sample_savename_input)

        self.alias_input = QLineEdit()
        self.alias_input.setPlaceholderText("experiment_alias_directory")
        filters.addRow("alias directory:", self.alias_input)
        layout.addLayout(filters)

        self.run_search_button = QPushButton("Load Matching Entries")
        self.run_search_button.clicked.connect(self._search_scans)
        layout.addWidget(self.run_search_button)

        self.search_status_label = QLabel("Enter cycle and proposal ID, then load matching entries")
        apply_info_style(self.search_status_label)
        layout.addWidget(self.search_status_label)
        return group

    def _create_results_group(self) -> QWidget:
        group = QGroupBox("3) Results")
        layout = QVBoxLayout(group)
        self.scan_table = QTableWidget(0, 8)
        self.scan_table.setHorizontalHeaderLabels(
            [
                "scan_id",
                "detector",
                "filename",
                "measure_type",
                "proposal",
                "alias",
                "steps",
                "time",
            ]
        )
        self.scan_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.scan_table.setSelectionMode(QTableWidget.SingleSelection)
        self.scan_table.itemSelectionChanged.connect(self._on_scan_selected)
        self.scan_table.cellClicked.connect(self._on_scan_clicked)
        self.scan_table.setMinimumWidth(0)
        header = self.scan_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        column_widths = AppStyle.get_layout_ratios()['tiled_results_column_widths']
        for column, width in enumerate(column_widths):
            self.scan_table.setColumnWidth(column, width)
        layout.addWidget(self.scan_table)

        row = QHBoxLayout()
        self.load_button = QPushButton("Load Image + Metadata")
        self.load_button.setEnabled(False)
        self.load_button.clicked.connect(self._load_selected_scan)
        row.addWidget(self.load_button)
        layout.addLayout(row)

        self.load_progress_bar = QProgressBar()
        self.load_progress_bar.setVisible(False)
        layout.addWidget(self.load_progress_bar)

        self.load_retry_label = QLabel()
        self.load_retry_label.setVisible(False)
        apply_info_style(self.load_retry_label)
        layout.addWidget(self.load_retry_label)

        return group

    def _create_playback_group(self) -> QWidget:
        group = QGroupBox("4) Series")
        layout = QVBoxLayout(group)
        self.series_slider = QSlider(Qt.Horizontal)
        self.series_slider.setEnabled(False)
        self.series_slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.series_slider)

        controls = QHBoxLayout()
        self.prev_button = QPushButton("Prev")
        self.prev_button.clicked.connect(self._select_previous)
        controls.addWidget(self.prev_button)

        self.play_button = QPushButton("Play")
        self.play_button.setCheckable(True)
        self.play_button.clicked.connect(self._toggle_playback)
        controls.addWidget(self.play_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._stop_playback)
        controls.addWidget(self.stop_button)

        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self._select_next)
        controls.addWidget(self.next_button)

        self.loop_checkbox = QCheckBox("Loop")
        self.loop_checkbox.setChecked(False)
        controls.addWidget(self.loop_checkbox)

        self.cancel_button = QPushButton("Cancel Action")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_operation)
        controls.addWidget(self.cancel_button)
        layout.addLayout(controls)
        return group

    def _create_frame_group(self) -> QWidget:
        group = QGroupBox("Stacked Frames")
        layout = QHBoxLayout(group)
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self._on_frame_changed)
        layout.addWidget(QLabel("Frame"))
        layout.addWidget(self.frame_slider, 1)
        self.frame_label = QLabel("1 / 1")
        apply_info_style(self.frame_label)
        layout.addWidget(self.frame_label)
        return group

    def _initialize_defaults(self) -> None:
        if not self.image_service.tiled_is_available():
            msg = self.image_service.tiled_import_error() or "Tiled unavailable"
            self.auth_status_label.setText(f"Status: unavailable ({msg})")
            for widget in (self.auth_button, self.refresh_button, self.run_search_button):
                widget.setEnabled(False)
            self.parent_app.show_status(f"Tiled browser disabled: {msg}")
            return

        for catalog in self.image_service.tiled_catalogs():
            label = f"{catalog['catalog_label']} - {catalog['description']}"
            self.catalog_combo.addItem(label, catalog["profile_name"])

        default_profile = self.image_service.tiled_default_profile()
        if default_profile is not None:
            idx = self.catalog_combo.findData(default_profile)
            if idx >= 0:
                self.catalog_combo.setCurrentIndex(idx)

        self._on_catalog_changed()

    def _active_profile(self) -> str | None:
        data = self.catalog_combo.currentData()
        if isinstance(data, str) and data:
            return data
        return self.image_service.tiled_default_profile()

    def _refresh_auth_state(self) -> None:
        profile = self._active_profile()
        if profile is None:
            return
        state = self.image_service.tiled_auth_state(profile)
        if state.authenticated:
            user = state.username or "cached session"
            self.auth_status_label.setText(f"Status: logged in ({user})")
            self.auth_button.setText("Re-Authenticate")
        else:
            suffix = f": {state.error}" if state.error else ""
            self.auth_status_label.setText(f"Status: not logged in{suffix}")
            self.auth_button.setText("Log In")

    def _handle_login(self) -> None:
        profile = self._active_profile()
        if profile is None:
            return
        self.parent_app.show_status("Watch the terminal for any Tiled login prompts")

        def do_login():
            return self.image_service.tiled_authenticate(profile_name=profile, interactive_fallback=True)

        def done(auth):
            self._refresh_auth_state()
            if not auth.authenticated:
                QMessageBox.warning(self, "Login failed", auth.error or "Could not authenticate")

        self._run_background(f"Connecting to Tiled profile {profile}...", do_login, done)

    def _on_catalog_changed(self) -> None:
        self._cancel_operation()
        self._clear_selection()
        self._refresh_auth_state()

    def _clear_selection(self) -> None:
        self.scan_rows = []
        self.scan_table.setRowCount(0)
        self.series_slider.setEnabled(False)
        self.series_slider.setMaximum(0)
        self.current_scan = None
        self.current_image_array = None
        self.current_frame_array = None
        self.current_image_source = None
        self.current_detector = ""
        self.load_button.setEnabled(False)
        self.sync_button.setEnabled(False)
        self.frame_slider.setEnabled(False)
        self.frame_slider.setMaximum(0)
        self.frame_label.setText("1 / 1")
        self.metadata_text.clear()

    def _search_scans(self) -> None:
        profile = self._active_profile()
        if profile is None:
            return
        cycle = self.cycle_combo.currentText().strip()
        proposal_id = self.proposal_input.text().strip()
        if not cycle or not proposal_id:
            QMessageBox.warning(self, "Missing query", "Enter both cycle and proposal ID")
            return

        filters = {
            "cycle": cycle,
            "proposal_id": proposal_id,
            "measure_type": self.measure_type_input.text().strip() or None,
            "sample_savename": self.sample_savename_input.text().strip() or None,
            "experiment_alias_directory": self.alias_input.text().strip() or None,
        }

        def do_search():
            return self.image_service.tiled_search_by_filters(
                profile_name=profile,
                filters=filters,
            )

        self._run_background(f"Searching Tiled for cycle {cycle}, proposal {proposal_id}...", do_search, self._apply_search_result)

    def _apply_search_result(self, result) -> None:
        self.scan_rows = list(result.scans)
        self._populate_scan_table()
        self.series_slider.setEnabled(bool(self.scan_rows))
        self.series_slider.setMaximum(max(len(self.scan_rows) - 1, 0))
        if self.scan_rows:
            self.series_slider.blockSignals(True)
            self.series_slider.setValue(0)
            self.series_slider.blockSignals(False)
            self.scan_table.selectRow(0)
        scan_range = "n/a"
        if result.scan_id_min is not None and result.scan_id_max is not None:
            scan_range = f"{result.scan_id_min} - {result.scan_id_max}"
        status = f"Available scans: {len(self.scan_rows)} of {result.scanned_ids}; scan_id range: {scan_range}"
        self.search_status_label.setText(status)
        self.parent_app.show_status(status)

    def _populate_scan_table(self) -> None:
        self.scan_table.setRowCount(len(self.scan_rows))
        for row_index, scan in enumerate(self.scan_rows):
            timestamp = ""
            if scan.time is not None:
                try:
                    timestamp = datetime.fromtimestamp(float(scan.time)).strftime("%Y-%m-%d %H:%M:%S")
                except (TypeError, ValueError, OSError):
                    timestamp = str(scan.time)
            values = [
                str(scan.scan_id or ""),
                "",
                scan.filename,
                scan.measure_type,
                scan.proposal_id,
                scan.experiment_alias,
                str(scan.n_steps or ""),
                timestamp,
            ]
            for col_index, value in enumerate(values):
                self.scan_table.setItem(row_index, col_index, QTableWidgetItem(value))

            detector_combo = QComboBox()
            detector_combo.addItems(scan.detectors)
            detector_combo.activated.connect(self._on_row_detector_activated)
            self.scan_table.setCellWidget(row_index, 1, detector_combo)

    def _on_scan_selected(self) -> None:
        selected = self.scan_table.selectionModel().selectedRows()
        has_selection = bool(selected)
        self.load_button.setEnabled(has_selection)

    def _on_scan_clicked(self, row: int, column: int) -> None:
        if column == 1:
            return
        self._activate_scan_row(row)

    def _selected_row(self) -> int | None:
        selected = self.scan_table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self.scan_rows):
            return None
        return row

    def _show_selected_metadata(self) -> None:
        row = self._selected_row()
        profile = self._active_profile()
        if row is None or profile is None:
            return
        scan = self.scan_rows[row]
        metadata = scan.metadata
        if scan.scan_id is not None:
            try:
                metadata = self.image_service.tiled_run_metadata(profile, scan.scan_id) or metadata
            except Exception:
                pass
        self.metadata_text.setPlainText(json.dumps(metadata, indent=2, default=str))

    def _load_selected_scan(self) -> None:
        row = self._selected_row()
        if row is not None:
            self._activate_scan_row(row)

    def _activate_scan_row(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self.scan_rows):
            return
        if self._selected_row() != row_index:
            self.scan_table.selectRow(row_index)
        self.series_slider.blockSignals(True)
        self.series_slider.setValue(row_index)
        self.series_slider.blockSignals(False)
        self._show_selected_metadata()
        self._load_scan_row(row_index)

    def _load_scan_row(self, row_index: int) -> None:
        profile = self._active_profile()
        if profile is None or row_index < 0 or row_index >= len(self.scan_rows):
            return
        scan = self.scan_rows[row_index]
        if scan.scan_id is None:
            QMessageBox.warning(self, "Missing scan ID", "Selected row does not have a scan_id")
            return
        detector = self._row_detector(row_index)
        if not detector:
            QMessageBox.warning(self, "Missing detector", "No detector is available for this scan")
            return

        def do_load(progress_cb, retry_cb):
            image_array = self.image_service.tiled_load_array(
                profile_name=profile,
                scan_id=scan.scan_id,
                detector=detector,
                uid=scan.uid,
                progress_callback=progress_cb,
                retry_callback=retry_cb,
            )
            image_ref = self.image_service.tiled_load_ref(
                profile_name=profile,
                scan_id=scan.scan_id,
                detector=detector,
                uid=scan.uid,
            )
            return scan, detector, image_array, image_ref

        self.load_progress_bar.setValue(0)
        self.load_progress_bar.setVisible(True)
        self.load_retry_label.setVisible(False)
        self._run_background_ex(
            f"Loading scan {scan.scan_id} detector {detector}...",
            do_load,
            self._apply_loaded_image,
            on_progress=self._on_load_progress,
            on_retry=self._on_load_retry,
        )

    def _on_load_progress(self, chunks_done: int, total_chunks: int) -> None:
        """Update the progress bar as tiled chunks are downloaded.

        The bar reserves the first 10% for connection overhead and the last 10%
        for post-processing, mapping chunk progress onto the middle 80% range.
        """
        if total_chunks > 0:
            pct = 10 + int((chunks_done / total_chunks) * 80)
        else:
            pct = 50  # indeterminate: show mid-point while total is unknown
        self.load_progress_bar.setValue(pct)

    def _on_load_retry(self, attempt: int, message: str) -> None:
        """Show a transient retry indicator when the HTTP client retries a request."""
        self.load_retry_label.setText(f"⟳ (attempt {attempt}) {message}")
        self.load_retry_label.setVisible(True)

    def _apply_loaded_image(self, payload) -> None:
        scan, detector, image_array, image_ref = payload
        self.current_scan = scan
        self.current_image_array = image_array
        self.current_image_source = image_ref.source_uri
        self.current_detector = detector
        self._configure_frame_slider(image_array)
        display_frame = self._frame_at(image_array, self.frame_slider.value())
        self.current_frame_array = display_frame
        self.image_data = display_frame
        self.update_plot(display_frame)
        self.sync_button.setEnabled(True)
        self.current_image_label.setText(
            f"scan_id={scan.scan_id} detector={detector} sample={scan.sample_name or scan.sample_savename or '?'}"
        )
        self.parent_app.show_status(f"Loaded Tiled scan {scan.scan_id}")

    def _row_detector(self, row_index: int) -> str:
        widget = self.scan_table.cellWidget(row_index, 1)
        if isinstance(widget, QComboBox):
            return widget.currentText()
        scan = self.scan_rows[row_index]
        return scan.detectors[0] if scan.detectors else ""

    def _on_row_detector_activated(self, *_args) -> None:
        self._stop_playback()
        row = self._selected_row()
        if row is not None:
            self._activate_scan_row(row)

    def _frame_count(self, image_array) -> int:
        arr = np.asarray(image_array)
        if arr.ndim <= 2:
            return 1
        return int(np.prod(arr.shape[:-2]))

    def _frame_at(self, image_array, frame_index: int):
        arr = np.asarray(image_array)
        if arr.ndim <= 2:
            return arr
        stack = arr.reshape((-1, arr.shape[-2], arr.shape[-1]))
        safe_index = max(0, min(frame_index, stack.shape[0] - 1))
        return stack[safe_index]

    def _configure_frame_slider(self, image_array) -> None:
        frame_count = self._frame_count(image_array)
        self.frame_slider.blockSignals(True)
        self.frame_slider.setEnabled(frame_count > 1)
        self.frame_slider.setMaximum(max(frame_count - 1, 0))
        self.frame_slider.setValue(0)
        self.frame_slider.blockSignals(False)
        self.frame_label.setText(f"1 / {frame_count}")

    def _on_frame_changed(self, frame_index: int) -> None:
        if self.current_image_array is None:
            return
        frame_count = self._frame_count(self.current_image_array)
        frame = self._frame_at(self.current_image_array, frame_index)
        self.current_frame_array = frame
        self.image_data = frame
        self.frame_label.setText(f"{frame_index + 1} / {frame_count}")
        self.update_plot(frame)

    def _on_slider_changed(self, position: int) -> None:
        if self.scan_rows and 0 <= position < len(self.scan_rows):
            self._activate_scan_row(position)

    def _toggle_playback(self) -> None:
        if not self.scan_rows:
            self.play_button.setChecked(False)
            return
        if self.play_button.isChecked():
            self.play_button.setText("Pause")
            self.play_timer.start(500)
        else:
            self._stop_playback()

    def _stop_playback(self) -> None:
        self.play_timer.stop()
        self.play_button.setChecked(False)
        self.play_button.setText("Play")

    def _advance_playback(self) -> None:
        if not self.scan_rows:
            self._stop_playback()
            return
        next_row = self.series_slider.value() + 1
        if next_row >= len(self.scan_rows):
            if not self.loop_checkbox.isChecked():
                self._stop_playback()
                return
            next_row = 0
        self.series_slider.setValue(next_row)

    def _select_previous(self) -> None:
        if self.scan_rows:
            self.series_slider.setValue(max(0, self.series_slider.value() - 1))

    def _select_next(self) -> None:
        if self.scan_rows:
            self.series_slider.setValue(min(len(self.scan_rows) - 1, self.series_slider.value() + 1))

    def _sync_to_parent(self) -> None:
        if self.current_frame_array is None or self.current_scan is None:
            return
        synthetic_name = f"scan_{self.current_scan.scan_id}.tif"
        image_data_obj = self.create_data2d_object(self.current_frame_array, synthetic_name)

        self.parent_app.image_data = image_data_obj
        self.parent_app.image_path = self.current_image_source
        for index in range(self.parent_app.tab_widget.count()):
            tab = self.parent_app.tab_widget.widget(index)
            if tab is self:
                continue
            if hasattr(tab, "image_data"):
                tab.image_data = image_data_obj
            if hasattr(tab, "populate_image_info") and hasattr(tab, "image_info_text"):
                tab.populate_image_info(image_data_obj, self.current_image_source)
            if hasattr(tab, "update_plot"):
                tab.update_plot()
        self.parent_app.show_status(f"Synced scan {self.current_scan.scan_id} to other tabs")

    def _add_tab_specific_status(self, info_lines):
        if self.current_scan is None:
            return
        info_lines.append("")
        info_lines.append("=== TILED ===")
        info_lines.append(f"Scan ID: {self.current_scan.scan_id}")
        info_lines.append(f"UID: {self.current_scan.uid}")
        info_lines.append(f"Detector: {self.current_detector}")
        info_lines.append(f"Detectors: {', '.join(self.current_scan.detectors)}")
