"""Reusable Tiled scalar and metadata sub-tabs, separate from SMI interpretation."""
import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLineEdit,
    QTableView, QSplitter, QLabel, QTabWidget,
)
from sciview.interfaces.services.latest_job import LatestJob
from sciview.interfaces.stable_qt.widgets.plot_style import style_plot
from sciview.sources.run_details import read_scalar_columns, read_configuration, scalar_points
from sciview.sources.tiled_client import tiled_manager
from sciview.interfaces.stable_qt.widgets.metadata_view import MetadataView


class ScalarTableModel(QAbstractTableModel):
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.names = list(columns)
        self.rows = max((len(v) for v in columns.values()), default=0)

    def rowCount(self, parent=QModelIndex()): return 0 if parent.isValid() else self.rows
    def columnCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self.names)
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole: return None
        values = self.columns[self.names[index.column()]]
        return str(values[index.row()]) if index.row() < len(values) else ""
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return self.names[section] if orientation == Qt.Horizontal else str(section)


class RunExplorer(QWidget):
    frame_selected = pyqtSignal(str, int)  # stream, acquisition index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.job = LatestJob(self)
        self.profile = self.uid = None
        self.columns = {}
        self._loaded = set()
        self._scalar_streams = {}
        self._guard = False
        root = QVBoxLayout(self)
        row = QHBoxLayout()
        self.stream = QComboBox(); self.stream.currentTextChanged.connect(self.reload_stream)
        row.addWidget(QLabel("Event stream")); row.addWidget(self.stream)
        refresh = QPushButton("Refresh details"); refresh.clicked.connect(self.reload); row.addWidget(refresh)
        self.status = QLabel("Select a run"); self.status.setWordWrap(True); row.addWidget(self.status, 1)
        root.addLayout(row)
        self.tabs = QTabWidget(); root.addWidget(self.tabs)
        scalar = QWidget(); layout = QVBoxLayout(scalar)
        controls = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(["1D curves", "2D parameter map"])
        self.x = QComboBox(); self.y = QComboBox(); self.z = QComboBox()
        for label, widget in (("View", self.mode), ("X", self.x), ("Y", self.y), ("Color / Z", self.z)):
            controls.addWidget(QLabel(label)); controls.addWidget(widget)
            widget.currentTextChanged.connect(self.plot_scalars)
        layout.addLayout(controls)
        split = QSplitter(Qt.Vertical); layout.addWidget(split, 1)
        self.plot = pg.PlotWidget(); split.addWidget(self.plot)
        self.scatter = pg.ScatterPlotItem(size=8, pen=None)
        self.line = self.plot.plot(pen="#1988be")
        self.plot.addItem(self.scatter)
        self.scatter.sigClicked.connect(self.point_clicked)
        self.table = QTableView(); self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda index: self.frame_selected.emit(self.stream.currentText(), index.row()))
        split.addWidget(self.table); split.setSizes([500, 180])
        self.tabs.addTab(scalar, "Scalars")
        metadata = QWidget(); ml = QVBoxLayout(metadata)
        self.section = QComboBox(); self.section.addItems(["Run metadata", "Baseline", "Configuration"])
        self.section.currentIndexChanged.connect(self.load_active)
        ml.addWidget(self.section)
        self.metadata_view = MetadataView(self); ml.addWidget(self.metadata_view, 1)
        self.tabs.addTab(metadata, "Metadata / Baseline / Config")
        self.tabs.currentChanged.connect(self.load_active)
        self.refresh_theme()

    def set_run(self, profile, uid, metadata=None):
        if (profile, uid) == (self.profile, self.uid): return
        self.job.invalidate(); self.profile, self.uid = profile, uid
        self._loaded.clear(); self._scalar_streams.clear(); self.columns = {}; self._documents = {}
        self.status.setText(f"{uid[:12]} · open a section to load details" if uid else "Select a run")
        self.metadata_view.set_document("Run metadata", metadata or {})
        self._guard = True
        self.stream.clear(); self.stream.addItem("primary")
        self._guard = False
        old_model = self.table.model()
        self.table.setModel(ScalarTableModel({}, self.table))
        if old_model is not None: old_model.deleteLater()
        self.scatter.clear(); self.line.clear()
        if self.isVisible(): self.load_active()

    def use_columns(self, stream, streams, columns):
        """Use an already loaded stream snapshot; avoid duplicate I/O for SMI."""
        self._guard = True
        self.stream.clear(); self.stream.addItems(streams); self.stream.setCurrentText(stream)
        self._guard = False
        self.columns = dict(columns)
        n = max((len(v) for v in columns.values()), default=0)
        self.columns["frame"] = np.arange(n, dtype=float)
        self._scalar_streams[stream] = self.columns
        self._loaded.add(("Scalars", stream))
        if self.isVisible(): self.populate_scalars()

    def reload(self):
        self._loaded.clear(); self._scalar_streams.clear(); self.load_active()

    def reload_stream(self, *_):
        if not self._guard: self.load_active()

    def load_active(self, *_):
        if self._guard or not self.uid or not self.isVisible(): return
        section = "Scalars" if self.tabs.currentIndex() == 0 else self.section.currentText()
        stream = self.stream.currentText() or "primary"
        key = (section, stream)
        self.job.invalidate()
        if key in self._loaded:
            if section == "Scalars":
                self.columns = self._scalar_streams[stream]; self.populate_scalars()
            else: self.metadata_view.set_document(section, self._documents[key], identity=(self.uid, key, id(self._documents[key])))
            return
        profile, uid = self.profile, self.uid
        self.status.setText(f"Loading {section} ({stream})…")
        if section != "Scalars": self.metadata_view.set_document(section, {})
        def work():
            catalog = tiled_manager.get_or_load_catalog(profile)
            if catalog is None: raise RuntimeError("Connect to Tiled first")
            run = catalog[uid]
            streams = [str(k) for k in run.keys() if k != "baseline"]
            if section == "Run metadata": data = dict(run.metadata)
            elif section == "Configuration": data = read_configuration(run, stream)
            else:
                derive = None
                if profile == "smi_migration":
                    try:
                        from smi_tiled.derived.virtual_axes import derive_virtual_columns
                        derive = derive_virtual_columns
                    except ImportError: pass
                target = "baseline" if section == "Baseline" else stream
                data = read_scalar_columns(run, target, derive) if target in run else {}
            return streams, data
        def done(payload):
            streams, data = payload
            if section == "Scalars": self.use_columns(stream, streams, data)
            else:
                self._guard = True
                self.stream.clear(); self.stream.addItems(streams); self.stream.setCurrentText(stream)
                self._guard = False
                self._documents[key] = data
                self._loaded.add(key)
                self.metadata_view.set_document(section, data, identity=(uid, key, id(data)))
            self.status.setText(f"{uid[:12]} · {section} · {stream}")
        self.job.submit(work, done, lambda exc: self.status.setText(f"{section}: {exc}"))

    def populate_scalars(self):
        self._guard = True
        numeric = [k for k, v in self.columns.items() if np.issubdtype(np.asarray(v).dtype, np.number)]
        for widget, default in ((self.x, "frame"), (self.y, numeric[0] if numeric else ""), (self.z, numeric[-1] if numeric else "")):
            previous = widget.currentText()
            widget.clear(); widget.addItems(numeric)
            widget.setCurrentText(previous if previous in numeric else default)
        self._guard = False
        old_model = self.table.model()
        self.table.setModel(ScalarTableModel(self.columns, self.table))
        if old_model is not None: old_model.deleteLater()
        self.plot_scalars()

    def plot_scalars(self, *_):
        if self._guard or not self.columns: return
        map_mode = self.mode.currentIndex() == 1
        self.z.setEnabled(map_mode)
        try:
            names = [self.x.currentText(), self.y.currentText()]
            arrays, indices = scalar_points(self.columns, *names, self.z.currentText() if map_mode else None)
            x, y = arrays[:2]
            if map_mode:
                z = arrays[2]
                lo, hi = np.percentile(z, [2, 98]) if len(z) else (0, 1)
                brushes = pg.colormap.get("viridis").mapToQColor(np.clip((z-lo)/max(hi-lo, 1e-30), 0, 1))
                self.line.clear()
            else:
                brushes = "#1988be"
                order = np.argsort(x, kind="stable")
                self.line.setData(x[order], y[order])
            self.scatter.setData(x=x, y=y, data=indices, brush=brushes)
            self.plot.setLabel("bottom", names[0]); self.plot.setLabel("left", names[1])
            title = f"{self.z.currentText()} on ({names[0]}, {names[1]})" if map_mode else f"{names[1]} vs {names[0]}"
            self.plot.setTitle(title)
            self.plot.autoRange()
            self.status.setText(f"{len(indices)} finite points · click a point or double-click a table row to inspect its frame. "
                                + ("2D scatter preserves repeats and irregular positions." if map_mode else ""))
        except (KeyError, ValueError) as exc:
            self.scatter.clear(); self.line.clear(); self.status.setText(str(exc))

    def point_clicked(self, _scatter, points):
        if points: self.frame_selected.emit(self.stream.currentText(), int(points[0].data()))

    def refresh_theme(self):
        if hasattr(self, "plot"):
            colors = style_plot(self.plot.plotItem); self.plot.setBackground(colors["base"])

    def showEvent(self, event):
        super().showEvent(event); self.load_active()
