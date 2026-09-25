"""Native cached-profile exploration; scientific fitting remains in smi-tiled."""
from pathlib import Path
import threading

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter, QLabel,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QFileDialog,
    QSpinBox, QCheckBox, QApplication,
)

from sciview.interfaces.services.latest_job import LatestJob
from sciview.interfaces.theme.app_style import apply_title_style
from sciview.processing.smi_cache import read_profiles, cache_directory, fit_profiles, compose_channels, save_analysis
from smi_tiled.derived.peakfit import PeakDef


class SmiPeakTab(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.profiles = None
        self.regions = []
        self._map_axes = None
        self._guard = False
        self.cancel = threading.Event()
        self.job = LatestJob(self)
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal); root.addWidget(splitter)
        controls = QWidget(); controls.setMaximumWidth(480)
        left = QVBoxLayout(controls)
        title = QLabel("SMI Peak Analysis"); apply_title_style(title); left.addWidget(title)
        self.open_button = QPushButton("Open cached reduction (.h5)")
        self.open_button.clicked.connect(self.choose_cache); left.addWidget(self.open_button)
        self.status = QLabel("Open a cached transmission reduction. q remains in nm⁻¹.")
        self.status.setWordWrap(True); left.addWidget(self.status)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "q min (nm⁻¹)", "q max (nm⁻¹)", "Model", "Baseline", "Link", "BG"])
        for i, width in enumerate((65, 65, 65, 75, 65, 75, 40)):
            self.table.setColumnWidth(i, width)
        self.table.cellChanged.connect(self.definitions_changed); left.addWidget(self.table)
        row = QHBoxLayout()
        for text, callback in (("+ Peak", self.add_peak), ("Remove", self.remove_peak), ("Fit", self.fit), ("Cancel", self.cancel.set)):
            button = QPushButton(text); button.clicked.connect(lambda _checked=False, fn=callback: fn()); row.addWidget(button)
            if text == "Fit": self.fit_button = button
        left.addLayout(row)
        form = QFormLayout()
        self.frame = QSpinBox(); self.frame.valueChanged.connect(self.select_frame)
        self.x = QComboBox(); self.y = QComboBox(); self.y.addItem("none")
        self.peak = QComboBox(); self.parameter = QComboBox()
        self.parameter.addItems(["area", "amplitude", "center", "fwhm"])
        self.mode = QComboBox(); self.mode.addItems(["Single peak", "RGB composite"])
        for label, widget in (("Acquisition frame", self.frame), ("X axis", self.x), ("Y axis", self.y),
                              ("Peak", self.peak), ("Parameter", self.parameter), ("View", self.mode)):
            form.addRow(label, widget)
        left.addLayout(form)
        self.channels = QTableWidget(0, 5)
        self.channels.setHorizontalHeaderLabels(["Use", "Peak area", "Color", "Gain", "Log"])
        for i, width in enumerate((40, 100, 80, 60, 40)):
            self.channels.setColumnWidth(i, width)
        self.channels.cellChanged.connect(self.render_map); left.addWidget(self.channels)
        for widget in (self.x, self.y, self.peak, self.parameter, self.mode):
            widget.currentTextChanged.connect(self.render_map)
        self.follow = QCheckBox("Map selection opens matching raw frame"); self.follow.setChecked(True); left.addWidget(self.follow)
        export = QPushButton("Export peak results (.h5)"); export.clicked.connect(self.export); left.addWidget(export)
        left.addStretch()
        splitter.addWidget(controls)
        visuals = pg.GraphicsLayoutWidget(); splitter.addWidget(visuals); splitter.setStretchFactor(1, 1)
        self.heat = visuals.addPlot(row=0, col=0, title="Per-frame I(q) — drag peak bands")
        self.heat.setToolTip("Drag bands to edit peaks. Double-click a frame row to inspect its raw image.")
        self.heat.setLabel("bottom", "q", units="nm⁻¹"); self.heat.setLabel("left", "acquisition frame")
        self.heat_image = pg.ImageItem(axisOrder="row-major"); self.heat.addItem(self.heat_image)
        self.heat_image.setLookupTable(pg.colormap.get("viridis").getLookupTable(nPts=256))
        self.cursor = pg.InfiniteLine(angle=0, pen="r"); self.heat.addItem(self.cursor)
        self.curve_plot = visuals.addPlot(row=1, col=0, title="Selected frame I(q)")
        self.curve_plot.setLabel("bottom", "q", units="nm⁻¹"); self.curve_plot.setLogMode(y=True)
        self.curve = self.curve_plot.plot(pen="w")
        self.fit_curve = self.curve_plot.plot(pen=pg.mkPen("y", width=2))
        self.map_plot = visuals.addPlot(row=2, col=0, title="Fit parameter map")
        self.scatter = pg.ScatterPlotItem(size=9, pen=None)
        self.map_plot.addItem(self.scatter); self.scatter.sigClicked.connect(self.map_clicked)
        self.heat.scene().sigMouseClicked.connect(self.heat_clicked)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.refresh_theme()

    def refresh_theme(self):
        if not hasattr(self, "map_plot"): return
        from sciview.interfaces.stable_qt.widgets.plot_style import style_plot
        for plot in (self.heat, self.curve_plot, self.map_plot):
            colors = style_plot(plot)
        self.curve.setPen(pg.mkPen(colors["text"], width=1.5))
        self.heat.getViewWidget().setBackground(colors["base"])

    def shutdown(self):
        self.cancel.set(); self.job.close()

    def choose_cache(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open SMI cache", str(cache_directory()), "HDF5 (*.h5 *.hdf5)")
        if path: self.load_path(path)

    def open_smi_cache(self, uid):
        if Path(uid).name != uid:
            self.status.setText("Invalid scan UID"); return
        self.load_path(cache_directory() / f"{uid}.h5")

    def load_path(self, path):
        self.cancel.set()
        self.profiles = None
        self.scatter.clear(); self.curve.clear(); self.fit_curve.clear(); self.heat_image.clear()
        for region in self.regions: self.heat.removeItem(region)
        self.regions = []
        self.status.setText(f"Loading {path}…")
        self.job.submit(lambda: read_profiles(path), self.loaded, self.error)

    def error(self, exc):
        self.fit_button.setEnabled(True)
        self.status.setText(f"{type(exc).__name__}: {exc}")

    def loaded(self, profiles):
        self.profiles = profiles
        self._map_axes = None
        self._guard = True
        try:
            self.frame.setMaximum(len(profiles.intensity)-1); self.frame.setValue(0)
            self.x.clear(); self.x.addItems(list(profiles.axes)); self.x.setCurrentText("frame")
            self.y.clear(); self.y.addItems(["none", *profiles.axes])
            self.table.setRowCount(0)
            for peak in profiles.peaks: self._add_row(peak)
        finally:
            self._guard = False
        iq = profiles.intensity
        row_step, col_step = max(1, int(np.ceil(len(iq)/800))), max(1, int(np.ceil(iq.shape[1]/1200)))
        with np.errstate(divide="ignore", invalid="ignore"):
            image = np.log10(np.where(iq[::row_step, ::col_step] > 0, iq[::row_step, ::col_step], np.nan)).astype("float32")
        finite = image[np.isfinite(image)]
        limits = np.percentile(finite, [2, 99.5]) if finite.size else (0, 1)
        self.heat_image.setImage(image, levels=limits, autoLevels=False)
        self.heat_image.setRect(QRectF(float(profiles.q[0]), 0, float(profiles.q[-1]-profiles.q[0]), len(iq)))
        self.heat.autoRange()
        self.fit_button.setEnabled(True)
        self.status.setText(f"{profiles.uid}: {len(iq)} frames × {len(profiles.q)} q points · primary · nm⁻¹")
        self.definitions_changed(); self.select_frame(0, navigate=False)

    def _add_row(self, peak):
        i = self.table.rowCount(); self.table.insertRow(i)
        for j, value in enumerate((peak.name, peak.q_min, peak.q_max, peak.model, peak.baseline, peak.link, peak.bg_factor)):
            self.table.setItem(i, j, QTableWidgetItem(str(value)))

    def peaks(self):
        peaks = []
        for i in range(self.table.rowCount()):
            values = [self.table.item(i, j).text() for j in range(7)]
            p = PeakDef(values[0], float(values[1]), float(values[2]), values[3], values[4], values[5], float(values[6]))
            if (not np.isfinite([p.q_min, p.q_max, p.bg_factor]).all() or p.q_max <= p.q_min or p.bg_factor <= 0
                    or p.model not in ("gaussian", "lorentzian") or p.baseline not in ("linear", "none")
                    or p.link not in ("independent", "linked", "tracked")):
                raise ValueError("Check peak range, model, baseline, link mode, and BG factor")
            peaks.append(p)
        return peaks

    def add_peak(self):
        if self.profiles is None: return
        q = self.profiles.q
        self._guard = True
        self._add_row(PeakDef(f"p{self.table.rowCount()+1}", float(q[len(q)//3]), float(q[2*len(q)//3]), link="linked"))
        self._guard = False; self.definitions_changed()

    def remove_peak(self):
        i = self.table.currentRow()
        if i < 0: i = self.table.rowCount()-1
        self._guard = True; self.table.removeRow(i); self._guard = False
        self.definitions_changed()

    def definitions_changed(self, *_):
        if self._guard: return
        try: peaks = self.peaks()
        except (ValueError, AttributeError) as exc: self.error(exc); return
        for region in self.regions: self.heat.removeItem(region)
        self.regions = []
        selected = self.peak.currentIndex()
        old_channels = {}
        for i in range(self.channels.rowCount()):
            name = self.channels.item(i, 1)
            if name is not None:
                old_channels[name.text()] = [self.channels.item(i, j).text() for j in (0, 2, 3, 4)]
        self._guard = True
        try:
            self.peak.clear(); self.peak.addItems([p.name for p in peaks]); self.peak.setCurrentIndex(max(0, selected))
            self.channels.setRowCount(len(peaks))
            colors = ["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff"]
            for i, peak in enumerate(peaks):
                region = pg.LinearRegionItem((peak.q_min, peak.q_max))
                region.setZValue(5); self.heat.addItem(region); self.regions.append(region)
                region.sigRegionChangeFinished.connect(lambda r, row=i: self.region_changed(row, r))
                enabled, color, gain, log = old_channels.get(peak.name, ["yes", colors[i % len(colors)], "1", "no"])
                for j, value in enumerate((enabled, peak.name, color, gain, log)):
                    item = QTableWidgetItem(value)
                    if j == 1: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.channels.setItem(i, j, item)
        finally: self._guard = False
        self.render_map()

    def region_changed(self, row, region):
        self._guard = True
        for j, value in enumerate(region.getRegion(), 1): self.table.item(row, j).setText(f"{value:.6g}")
        self._guard = False
        self.render_map()  # new key -> stale old fit is no longer shown

    def fit(self):
        if self.profiles is None: return
        try: peaks = self.peaks()
        except ValueError as exc: self.error(exc); return
        if not peaks: self.status.setText("Add a peak first"); return
        self.cancel.set(); self.cancel = threading.Event()
        cancel, profiles = self.cancel, self.profiles
        self.fit_button.setEnabled(False); self.status.setText("Fitting with smi-tiled…")
        def done(results):
            if profiles is self.profiles:
                profiles.fits = results
                self.status.setText("Fit cancelled" if cancel.is_set() else "Fit complete · cached in this session; Export to save")
                self.fit_button.setEnabled(True); self.render_map()
        self.job.submit(lambda: fit_profiles(profiles, peaks, cancel), done, self.error)

    def select_frame(self, index, navigate=True):
        if self._guard or self.profiles is None: return
        self.frame.blockSignals(True); self.frame.setValue(index); self.frame.blockSignals(False)
        self.cursor.setValue(index + 0.5)
        self.curve.setData(self.profiles.q, self.profiles.intensity[index])
        self._show_fit(index)
        if navigate and self.follow.isChecked() and hasattr(self.app, "select_smi_frame"):
            self.app.select_smi_frame(self.profiles.uid, index)

    def _show_fit(self, index):
        """The backend persists peak parameters, not baseline coefficients."""
        self.fit_curve.clear()
        try:
            peaks = self.peaks()
            selected = self.peak.currentIndex()
            if not 0 <= selected < len(peaks): return
            peak = peaks[selected]
            result = self.profiles.fits.get(peak.key())
            if result is None: return
            ok = bool(result.get("success", np.ones(len(self.profiles.intensity), dtype=bool))[index])
            self.curve_plot.setTitle(f"Frame {index} · {peak.name} · {'accepted fit' if ok else 'no accepted peak'}")
            if not ok or any(k not in result for k in ("amplitude", "center", "fwhm")): return
            amplitude, center, fwhm = (float(result[k][index]) for k in ("amplitude", "center", "fwhm"))
            q = self.profiles.q
            select = (q >= peak.q_min) & (q <= peak.q_max)
            if fwhm <= 0 or not np.isfinite([amplitude, center, fwhm]).all(): return
            if peak.model == "gaussian":
                sigma = fwhm / np.sqrt(8*np.log(2))
                values = amplitude * np.exp(-.5*((q[select]-center)/sigma)**2)
            else:
                gamma = fwhm/2
                values = amplitude * gamma**2 / ((q[select]-center)**2 + gamma**2)
            self.fit_curve.setData(q[select], values)
            self.curve_plot.setTitle(f"Frame {index} · {peak.name} · yellow: fitted peak component (baseline excluded)")
        except (ValueError, KeyError, AttributeError):
            pass

    def heat_clicked(self, event):
        if self.profiles is None or event.button() != Qt.LeftButton or not event.double(): return
        if self.heat.sceneBoundingRect().contains(event.scenePos()):
            point = self.heat.vb.mapSceneToView(event.scenePos())
            self.select_frame(max(0, min(int(point.y()), len(self.profiles.intensity)-1)))

    def map_clicked(self, _item, points):
        if points: self.select_frame(int(points[0].data()))

    def render_map(self, *_):
        if self._guard or self.profiles is None: return
        try:
            peaks = self.peaks()
            x = self.profiles.axes[self.x.currentText()]
            y_name = self.y.currentText()
            is_composite = self.mode.currentIndex() == 1
            if is_composite:
                channels = []
                from PyQt5.QtGui import QColor
                for i, peak in enumerate(peaks):
                    if self.channels.item(i, 0).text().lower() not in ("yes", "true", "1"): continue
                    result = self.profiles.fits.get(peak.key())
                    if result is None: continue
                    color = QColor(self.channels.item(i, 2).text())
                    if not color.isValid(): raise ValueError("Channel color must be a valid color/hex code")
                    gain = float(self.channels.item(i, 3).text())
                    if not np.isfinite(gain) or gain < 0: raise ValueError("Gain must be finite and non-negative")
                    channels.append((result["area"], color.getRgbF()[:3], gain,
                                     self.channels.item(i, 4).text().lower() in ("yes", "true", "1")))
                rgb = compose_channels(channels)
                if not len(rgb): self.scatter.clear(); return
                z = np.max(rgb, axis=1)
                brushes = [pg.mkBrush(*(255*c).astype(int)) for c in rgb]
            else:
                i = self.peak.currentIndex()
                if not 0 <= i < len(peaks): self.scatter.clear(); return
                result = self.profiles.fits.get(peaks[i].key())
                if result is None: self.scatter.clear(); return
                z = np.asarray(result[self.parameter.currentText()])
                finite = z[np.isfinite(z)]
                low, high = np.percentile(finite, [2, 99]) if finite.size else (0, 1)
                normalized = np.nan_to_num(np.clip((z-low)/max(high-low, 1e-30), 0, 1))
                brushes = pg.colormap.get("viridis").mapToQColor(normalized)
            y = z if y_name == "none" else self.profiles.axes[y_name]
            finite = np.isfinite(x) & np.isfinite(y)
            indices = np.flatnonzero(finite)
            self.scatter.setData(x=x[finite], y=y[finite], data=indices,
                                 brush=[brushes[i] for i in indices])
            axes_key = (self.x.currentText(), y_name, is_composite, self.parameter.currentText())
            if axes_key != self._map_axes:
                self.map_plot.autoRange()
                self._map_axes = axes_key
            self._show_fit(self.frame.value())
            self.map_plot.setLabel("bottom", self.x.currentText())
            parameter = self.parameter.currentText()
            units = {"center": "nm⁻¹", "fwhm": "nm⁻¹", "area": "I × nm⁻¹", "amplitude": "I"}
            label = ("RGB brightness" if is_composite else f"{parameter} ({units[parameter]})") if y_name == "none" else y_name
            self.map_plot.setLabel("left", label)
            self.map_plot.setTitle("RGB peak areas (click a point → raw frame)" if is_composite else "Fit parameter (click a point → raw frame)")
        except (ValueError, KeyError, AttributeError) as exc:
            self.error(exc)

    def export(self):
        if self.profiles is None: return
        path, _ = QFileDialog.getSaveFileName(self, "Export analysis", self.profiles.uid + "_peaks.h5", "HDF5 (*.h5)")
        if path:
            try:
                if Path(path).resolve() == self.profiles.path.resolve():
                    raise ValueError("Choose a separate output file; the source reduction cache is read-only")
                profiles, peaks = self.profiles, self.peaks()
                self.job.submit(lambda: save_analysis(profiles, peaks, path),
                                lambda _: self.status.setText(f"Saved {path}"), self.error)
            except Exception as exc: self.error(exc)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
