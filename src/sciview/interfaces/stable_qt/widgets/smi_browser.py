"""Optional SMI controls embedded in the existing Tiled browser layout."""
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QApplication,
)

from sciview.interfaces.services.latest_job import LatestJob
from sciview.sources.frame_source import FrameRef, TiledFrameSource, search_page
from sciview.sources.tiled_client import tiled_manager


class SmiBrowserControls(QWidget):
    """Own one lazy source; all source/cache operations use the same worker."""
    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.job = LatestJob(self)
        self.source = None
        self.sequence = None
        self.ref = None
        self.order = np.array([], dtype=int)
        self.filters = {}
        self.offset = 0
        self.total = 0
        self._guard = False
        self._source_epoch = 0
        self._worker_epoch = -1
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.previous = QPushButton("Previous page")
        self.next = QPushButton("Next page")
        self.page_label = QLabel("SMI: 25 scans/page")
        self.previous.clicked.connect(lambda: self.search(self.filters, max(0, self.offset - 25)))
        self.next.clicked.connect(lambda: self.search(self.filters, self.offset + 25))
        row.addWidget(self.previous); row.addWidget(self.page_label); row.addWidget(self.next)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.stream = QComboBox(); self.detector = QComboBox(); self.axis = QComboBox()
        for label, widget in (("Stream", self.stream), ("Detector", self.detector), ("Browse axis", self.axis)):
            row.addWidget(QLabel(label)); row.addWidget(widget, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.index = QSpinBox(); self.index.setPrefix("Frame ")
        self.value = QDoubleSpinBox(); self.value.setRange(-1e12, 1e12); self.value.setDecimals(5)
        self.go = QPushButton("Nearest axis value")
        self.cached = QPushButton("Open cached I(q) / Peaks")
        self.cached.clicked.connect(self.open_cached)
        self.go.clicked.connect(self.nearest)
        row.addWidget(self.index); row.addWidget(self.value); row.addWidget(self.go); row.addWidget(self.cached)
        layout.addLayout(row)
        self.note = QLabel("Raw detector coordinates · SMI reduction remains in smi-tiled")
        self.note.setWordWrap(True); layout.addWidget(self.note)
        self.refresh = QPushButton("Refresh run / discard frame cache")
        self.refresh.clicked.connect(self.refresh_run); layout.addWidget(self.refresh)
        self.recent = QPushButton("Browse recent SMI scans (all proposals)")
        self.recent.clicked.connect(lambda: self.tab.smi_search.clear()); layout.addWidget(self.recent)
        self.recent.hide()  # reset/search controls live together in the left panel
        from sciview.interfaces.stable_qt.widgets.status_label import readable_status
        self.scope_note = readable_status(
            "SMI: browse raw frames, then use Reduction to process the whole primary "
            "run with smi-tiled. Transform displays its 2D products, and Peak Analysis "
            "explores per-frame I(q). Calibration and mask drawing adapters are still "
            "in development; bundled or custom SMI mask JSON can be used in Reduction."
        )
        layout.addWidget(self.scope_note)
        self.stream.currentTextChanged.connect(self._stream_changed)
        self.detector.currentTextChanged.connect(self._detector_changed)
        self.axis.currentTextChanged.connect(self._axis_changed)
        self.index.valueChanged.connect(self.select_index)
        QApplication.instance().aboutToQuit.connect(self.job.close)

    def active(self):
        return self.tab._active_profile() == "smi_migration"

    def reset(self):
        self.job.invalidate()
        self._source_epoch += 1
        self.sequence = self.ref = None
        self.order = np.array([], dtype=int)
        self.setVisible(self.active())
        self.tab.measure_type_input.setText("" if self.active() else "measure")
        self.tab.proposal_input.setPlaceholderText("pass-123456 or proposal number" if self.active() else "320406")
        self.previous.setEnabled(False); self.next.setEnabled(False)
        self.tab.live_start_button.setEnabled(not self.active())
        self.tab.live_start_button.setToolTip("Live SMI following is a later milestone" if self.active() else "Listen for new runs")
        self.tab.scan_table.setHorizontalHeaderLabels(
            ["scan_id", "detector", "sample" if self.active() else "filename",
             "plan" if self.active() else "measure_type", "proposal", "project" if self.active() else "alias", "steps", "time"])
        if not self.active() and hasattr(self.tab.parent_app, "_set_smi_processing_scope"):
            self.tab.parent_app.frame_context = None
            controller = getattr(self.tab.parent_app, "smi_processing", None)
            if controller is not None: controller.set_context(None)
            self.tab.parent_app._set_smi_processing_scope(False)

    def refresh_run(self):
        scan = self.tab.current_scan
        if scan is not None:
            self._source_epoch += 1
            self.load(scan, self.stream.currentText(), self.detector.currentText(), self.index.value())

    def _source(self, epoch):
        if self.source is None or self._worker_epoch != epoch:
            catalog = tiled_manager.get_or_load_catalog("smi_migration")
            if catalog is None:
                raise RuntimeError("Connect to SMI first using Login (cached Tiled credentials are supported).")
            try:
                from smi_tiled.derived.virtual_axes import derive_virtual_columns
            except ImportError:
                derive_virtual_columns = None
            self.source = TiledFrameSource(catalog, "smi_migration", derive=derive_virtual_columns)
            self._worker_epoch = epoch
        return self.source

    def error(self, exc):
        self.tab.cancel_button.setEnabled(False)
        self.note.setText(f"SMI: {type(exc).__name__}: {exc}")
        self.tab.search_status_label.setText(str(exc))

    def search(self, filters, offset=0):
        self.clear_results()
        self.filters, self.offset = dict(filters), offset
        epoch = self._source_epoch
        self.note.setText("Searching metadata…")
        self.tab.search_status_label.setText("Loading newest scans…")
        self.tab.cancel_button.setEnabled(True)
        query = dict(filters)
        def work():
            return search_page(self._source(epoch).catalog, "smi_migration", query, offset)
        def done(result):
            self.tab.cancel_button.setEnabled(False)
            self.total = result.total_count
            self.tab._apply_search_result(result)
            self.tab.search_status_label.setText(f"{self.total:,} scans — newest first · page {offset // 25 + 1}")
            if query == self.tab.smi_search.filters():
                self.tab.smi_search.show_count(self.total)
            self.previous.setEnabled(offset > 0)
            self.next.setEnabled(offset + 25 < self.total)
            self.page_label.setText(f"{offset + 1 if self.total else 0}–{min(offset + 25, self.total)} / {self.total}")
            self.note.setText("Select a scan to read one frame. Search loaded metadata only.")
        self.job.submit(work, done, self.error)

    def clear_results(self):
        self.job.invalidate()
        self.sequence = self.ref = None
        self.order = np.array([], dtype=int)
        self.tab.current_scan = None
        self.tab.current_frame_array = self.tab.current_image_array = None
        self.tab.scan_rows = []
        self.tab.scan_table.setRowCount(0)
        self.tab.frame_slider.setEnabled(False)
        self.tab.series_slider.setEnabled(False)
        self.tab.load_button.setEnabled(False)
        self.previous.setEnabled(False); self.next.setEnabled(False)

    def load(self, scan, stream=None, detector=None, index=0):
        epoch = self._source_epoch
        self.ref = None
        self.sequence = None
        self.order = np.array([], dtype=int)
        self.index.setEnabled(False)
        self.tab.frame_slider.setEnabled(False)
        self.tab.cancel_button.setEnabled(True)
        self.note.setText(f"Inspecting {scan.scan_id or scan.uid[:8]}…")
        self.tab.current_scan = scan
        def work():
            source = self._source(epoch)
            sequence = source.describe(scan.uid, stream)
            if not sequence.fields:
                raise ValueError(f"No detector images in stream {sequence.stream}")
            if stream is not None and sequence.stream != stream:
                raise ValueError(f"Stream {stream!r} is unavailable; cannot substitute another stream")
            field = detector if detector in sequence.fields else next(iter(sequence.fields))
            ref = FrameRef("smi_migration", scan.uid, sequence.stream, field,
                           min(index, sequence.count(field) - 1))
            return sequence, ref, source.read_frame(ref)
        def done(payload):
            sequence, ref, array = payload
            self.index.setEnabled(True)
            self.sequence = sequence
            self.tab.current_scan = scan
            self._guard = True
            try:
                self.stream.clear(); self.stream.addItems(sequence.streams); self.stream.setCurrentText(ref.stream)
                self.detector.clear(); self.detector.addItems(list(sequence.fields)); self.detector.setCurrentText(ref.detector)
                self._populate_axes()
            finally:
                self._guard = False
            self._show(ref, array)
        self.job.submit(work, done, self.error)

    def _populate_axes(self):
        old = self.axis.currentText()
        self.axis.clear(); self.axis.addItem("frame")
        self.axis.addItems(list(self.sequence.axes(self.detector.currentText())))
        if self.axis.findText(old) >= 0:
            self.axis.setCurrentText(old)
        self.order = self.sequence.order(self.detector.currentText(), self.axis.currentText())
        self.index.setMaximum(max(0, len(self.order) - 1))
        slider = self.tab.frame_slider
        slider.blockSignals(True)
        slider.setMaximum(max(0, len(self.order) - 1)); slider.setEnabled(len(self.order) > 1)
        slider.blockSignals(False)

    def _stream_changed(self, stream):
        if not self._guard and self.tab.current_scan is not None:
            self.load(self.tab.current_scan, stream, self.detector.currentText())

    def _detector_changed(self, detector):
        if not self._guard and self.tab.current_scan is not None:
            self.load(self.tab.current_scan, self.stream.currentText(), detector)

    def _axis_changed(self, _axis):
        if self._guard or self.sequence is None:
            return
        self.order = self.sequence.order(self.detector.currentText(), self.axis.currentText())
        if self.ref is not None:
            self._sync_position(self.ref.index)
            self._axis_readout(self.ref)

    def _axis_readout(self, ref):
        values = self.sequence.axes(ref.detector).get(self.axis.currentText())
        text = ""
        if values is not None:
            value = values[ref.index]
            unit = " eV" if self.axis.currentText() in ("energy_energy", "fn:eV") else ""
            text = f" · {self.axis.currentText()}={value:.6g}{unit}"
            duplicates = np.flatnonzero(values == value)
            if len(duplicates) > 1:
                occurrence = int(np.flatnonzero(duplicates == ref.index)[0]) + 1
                text += f" · occurrence {occurrence}/{len(duplicates)}"
            if np.isfinite(value): self.value.setValue(float(value))
        self.tab.frame_label.setText(f"{ref.index + 1} / {self.sequence.count(ref.detector)}{text}")

    def _sync_position(self, index):
        self._guard = True
        try:
            self.index.setValue(index)
            positions = np.flatnonzero(self.order == index)
            self.tab.frame_slider.blockSignals(True)
            self.tab.frame_slider.setValue(int(positions[0]) if positions.size else 0)
            self.tab.frame_slider.blockSignals(False)
        finally:
            self._guard = False

    def select_position(self, position):
        if not self._guard and 0 <= position < len(self.order):
            self.select_index(int(self.order[position]))

    def select_index(self, index):
        if self._guard or self.sequence is None:
            return
        ref = FrameRef("smi_migration", self.sequence.uid, self.sequence.stream,
                       self.detector.currentText(), int(index))
        source = self.source
        self.note.setText(f"Loading acquisition frame {index}…")
        self.tab.cancel_button.setEnabled(True)
        self.job.submit(lambda: source.read_frame(ref), lambda a: self._show(ref, a), self.error)

    def nearest(self):
        if self.sequence is None:
            return
        values = self.sequence.axes(self.detector.currentText()).get(self.axis.currentText())
        if values is not None and np.isfinite(values).any():
            distances = np.where(np.isfinite(values), abs(values - self.value.value()), np.inf)
            self.select_index(int(np.argmin(distances)))

    def _show(self, ref, array):
        self.ref = ref
        tab = self.tab
        tab.cancel_button.setEnabled(False)
        tab.current_image_array = None  # never store an eager detector stack
        tab.current_frame_array = tab.image_data = array
        tab.current_image_source = ref.uri
        tab.current_detector = ref.detector
        # Native raw-array viewer, without CMS calibration inference or copying.
        tab.image_viewer.set_image(array)
        tab._apply_display_settings_to_viewer()
        self._sync_position(ref.index)
        self._axis_readout(ref)
        tab.current_image_label.setText(f"SMI {ref.uid[:12]} · {ref.stream}/{ref.detector} · frame {ref.index}")
        self.note.setText("Raw coordinates (x=column, y=row); repeated axis values retain separate frames.")
        if hasattr(tab.parent_app, "publish_frame_context"):
            tab.parent_app.publish_frame_context(ref)

    def open_cached(self):
        app = self.tab.parent_app
        if self.tab.current_scan is None:
            self.error(ValueError("Select a scan first")); return
        for i in range(app.tab_widget.count()):
            widget = app.tab_widget.widget(i)
            if hasattr(widget, "open_smi_cache"):
                controller = getattr(app, "smi_processing", None)
                result = controller.result if controller is not None else None
                if result and result["uid"] == self.tab.current_scan.uid and result["has_profiles"]:
                    widget.load_path(result["path"])
                else:
                    widget.open_smi_cache(self.tab.current_scan.uid)
                app.tab_widget.setCurrentIndex(i)
                return
        self.error(RuntimeError("Peak Analysis requires the optional SMI environment: pixi run -e smi launch-smi"))
