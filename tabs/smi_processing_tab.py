"""Native SMI processing views embedded in SciView's existing workflow tabs."""
from pathlib import Path
import json

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtWidgets import (
    QWidget, QStackedWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QSplitter,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit, QPushButton,
    QFileDialog, QScrollArea, QTextEdit, QApplication, QSlider, QLabel, QToolTip,
)

from sciview.interfaces.services.latest_job import LatestJob
from sciview.interfaces.stable_qt.widgets.status_label import readable_status
from sciview.processing.smi_reduction import SmiReductionRequest, read_curves, read_map, read_waterfall, results_directory
from sciview.processing.frame_labels import frame_label, waterfall_values
from sciview.interfaces.stable_qt.widgets.plot_style import style_plot


class BackendTab(QStackedWidget):
    """Keep CMS widgets intact; choose a view from explicit source context."""
    def __init__(self, cms, smi):
        super().__init__()
        self.cms, self.smi = cms, smi
        self.addWidget(cms); self.addWidget(smi)

    def set_smi_active(self, active):
        self.setCurrentWidget(self.smi if active else self.cms)

    @property
    def image_data(self):
        return self.cms.image_data

    @image_data.setter
    def image_data(self, value):
        self.cms.image_data = value

    @property
    def image_viewer(self):
        return self.cms.image_viewer if self.currentWidget() is self.cms else None

    def update_plot(self, *args, **kwargs):
        if self.currentWidget() is self.cms:
            self.cms.update_plot(*args, **kwargs)

    def on_shared_state_activated(self):
        if self.currentWidget() is self.cms:
            self.cms.on_shared_state_activated()

    def apply_shared_display_settings(self, settings):
        if self.currentWidget() is self.cms:
            self.cms.apply_shared_display_settings(settings)

    def on_plot_style_changed(self):
        self.cms.on_plot_style_changed()


def _spin(value, low, high, decimals=None):
    widget = QSpinBox() if decimals is None else QDoubleSpinBox()
    widget.setRange(low, high)
    if decimals is not None: widget.setDecimals(decimals)
    widget.setValue(value)
    return widget


class SmiReductionTab(QWidget):
    def __init__(self, app, controller):
        super().__init__()
        self.app, self.controller = app, controller
        self.io = LatestJob(self)
        self.result = None
        self._guard = False
        self._waterfall_data = None
        self._waterfall_lines = []
        self._hover_traces = []
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal); root.addWidget(splitter)
        controls = QWidget(); left = QVBoxLayout(controls)
        self.context = readable_status("Select an SMI run in Tiled Browser")
        left.addWidget(self.context)
        form = QFormLayout()
        self.geometry = QComboBox(); self.geometry.addItems(["Transmission SAXS + WAXS", "Grazing-incidence WAXS"])
        form.addRow("Geometry", self.geometry)
        self.nq = _spin(2000, 16, 10000); self.nchi = _spin(360, 16, 10000)
        self.nqxy = _spin(500, 16, 10000); self.nqz = _spin(500, 16, 10000)
        self.splitting = _spin(1, 1, 8)
        self.dezinger = _spin(3000, 0, 1e9, 1); self.kernel = _spin(5, 3, 31); self.kernel.setSingleStep(2)
        self.solid = QCheckBox("Solid-angle correction"); self.solid.setChecked(True)
        self.frame_maps = QCheckBox("Store per-frame 2D maps"); self.frame_maps.setChecked(True)
        for name, widget in (("n q", self.nq), ("n χ", self.nchi), ("n qxy (GI)", self.nqxy),
                             ("n qz (GI)", self.nqz), ("Pixel splitting", self.splitting),
                             ("Dezinger threshold (0 = off)", self.dezinger), ("Dezinger kernel", self.kernel)):
            form.addRow(name, widget)
        self.incident_auto = QCheckBox("Resolve incident angle automatically"); self.incident_auto.setChecked(True)
        self.incident = _spin(0, -90, 90, 4); self.incident.setEnabled(False)
        self.incident_auto.toggled.connect(lambda checked: self.incident.setEnabled(not checked and self.geometry.currentIndex() == 1))
        form.addRow(self.solid); form.addRow(self.frame_maps); form.addRow(self.incident_auto); form.addRow("Incident angle (GI, °)", self.incident)
        self.saxs_mask = QLineEdit(); self.waxs_mask = QLineEdit()
        for detector, widget in (("SAXS", self.saxs_mask), ("WAXS", self.waxs_mask)):
            widget.setPlaceholderText("Bundled smi-tiled mask (automatic)")
            row = QHBoxLayout(); row.addWidget(widget)
            button = QPushButton("…")
            button.clicked.connect(lambda _checked=False, w=widget: self.choose_mask(w))
            row.addWidget(button); form.addRow(f"{detector} mask JSON", row)
        self.overrides = QCheckBox("Override metadata-relative calibration deltas")
        form.addRow(self.overrides)
        from smi_tiled.defaults import LOADER_DEFAULTS
        self.delta_widgets = []
        for label, default in (("SAXS Δrow (px)", LOADER_DEFAULTS.saxs_row_delta_px),
                               ("SAXS Δcol (px)", LOADER_DEFAULTS.saxs_col_delta_px),
                               ("WAXS Δrow (px)", LOADER_DEFAULTS.waxs_row_delta_px),
                               ("WAXS Δcol (px)", LOADER_DEFAULTS.waxs_col_delta_px),
                               ("SAXS Δdistance (mm)", LOADER_DEFAULTS.saxs_distance_delta_mm)):
            widget = _spin(default, -10000, 10000, 4); widget.setEnabled(False)
            self.delta_widgets.append(widget); form.addRow(label, widget)
        self.overrides.toggled.connect(self._geometry_controls)
        self.geometry.currentIndexChanged.connect(self._geometry_controls)
        left.addLayout(form)
        row = QHBoxLayout()
        self.run_button = QPushButton("Reduce whole primary run")
        self.run_button.clicked.connect(self.run)
        self.cancel_button = QPushButton("Cancel reduction"); self.cancel_button.clicked.connect(controller.cancel)
        row.addWidget(self.run_button); row.addWidget(self.cancel_button); left.addLayout(row)
        self.status = readable_status("Metadata and bundled calibration defaults are used unless explicitly overridden.")
        left.addWidget(self.status)
        self.open_button = QPushButton("Open saved SciView reduction…"); self.open_button.clicked.connect(self.open_result); left.addWidget(self.open_button)
        self.peaks_button = QPushButton("Explore result in Peak Analysis"); self.peaks_button.clicked.connect(self.open_peaks); left.addWidget(self.peaks_button)
        self.provenance = QTextEdit(); self.provenance.setReadOnly(True); self.provenance.setMaximumHeight(180)
        left.addWidget(self.provenance)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(controls); scroll.setMinimumWidth(340); scroll.setMaximumWidth(520)
        splitter.addWidget(scroll)
        visuals = QWidget(); right = QVBoxLayout(visuals)
        row = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(["Merged", "Per-frame"])
        self.presentation = QComboBox(); self.presentation.addItems(["Waterfall", "Single frame"])
        self.spacing = _spin(.05, 0, 10, 3); self.spacing.setSingleStep(.01)
        self.label_signal = QComboBox(); self.label_signal.addItem("frame")
        self.frame = _spin(0, 0, 0)
        self.power = _spin(0, -4, 6, 1); self.power.setPrefix("I × q^")
        self.log_x = QCheckBox("Log q"); self.log_x.setChecked(True)
        self.log_y = QCheckBox("Log I"); self.log_y.setChecked(True)
        for widget in (self.mode, self.frame, self.power, self.log_x, self.log_y): row.addWidget(widget)
        right.addLayout(row)
        label_row = QHBoxLayout()
        for label, widget in (("Per-frame view", self.presentation), ("Offset / trace", self.spacing), ("Frame label", self.label_signal)):
            label_row.addWidget(QLabel(label)); label_row.addWidget(widget)
        right.addLayout(label_row)
        self.trace_label = readable_status("Choose Per-frame for a waterfall; hover over a trace to identify its frame.")
        right.addWidget(self.trace_label)
        self.plot = pg.PlotWidget(title="SMI I(q)"); self.plot.addLegend()
        self.plot.setLabel("bottom", "q", units="nm⁻¹"); self.plot.setLabel("left", "I(q)")
        self.lines = [self.plot.plot(pen=pg.mkPen(color, width=1.5), name=name) for color, name in (("w", "Merged / frame"), ("c", "SAXS"), ("m", "WAXS"))]
        right.addWidget(self.plot)
        self.plot.scene().sigMouseMoved.connect(self.hover_trace)
        splitter.addWidget(visuals); splitter.setStretchFactor(1, 1)
        self.mode.currentIndexChanged.connect(self.render)
        self.frame.valueChanged.connect(self.render)
        self.power.valueChanged.connect(self.render)
        self.presentation.currentIndexChanged.connect(self.render)
        self.spacing.valueChanged.connect(self.render)
        self.label_signal.currentTextChanged.connect(self.render)
        self.log_x.toggled.connect(self.render); self.log_y.toggled.connect(self.render)
        controller.context_changed.connect(self.context_changed)
        controller.result_changed.connect(self.result_changed)
        controller.status_changed.connect(self.status.setText)
        controller.busy_changed.connect(self.update_buttons)
        QApplication.instance().aboutToQuit.connect(self.io.close)
        self._geometry_controls(); self.update_buttons(); self.refresh_theme()

    def _geometry_controls(self, *_):
        gi = self.geometry.currentIndex() == 1
        for widget in (self.nq, self.nchi, self.solid, self.saxs_mask, self.overrides): widget.setEnabled(not gi)
        for widget in (self.nqxy, self.nqz, self.incident_auto): widget.setEnabled(gi)
        self.incident.setEnabled(gi and not self.incident_auto.isChecked())
        for widget in self.delta_widgets: widget.setEnabled(not gi and self.overrides.isChecked())

    def choose_mask(self, widget):
        path, _ = QFileDialog.getOpenFileName(self, "SMI mask specification", "", "JSON (*.json)")
        if path: widget.setText(path)

    def context_changed(self, ref):
        self.context.setText(f"SMI {ref.uid[:12]} · stream {ref.stream}\nWhole-run reduction uses all available SAXS/WAXS detectors, not only the displayed frame." if ref else "Select an SMI run")
        if ref is not None and ref.stream != "primary":
            self.status.setText("Non-primary reduction is not yet supported by smi-tiled. Select primary to process.")
        self.update_buttons()
        if self.result is not None and ref is not None and ref.index <= self.frame.maximum():
            self.frame.setValue(ref.index)

    def update_buttons(self, *_):
        ref = self.controller.ref
        self.run_button.setEnabled(not self.controller.busy and ref is not None and ref.stream == "primary")
        self.cancel_button.setEnabled(self.controller.busy)
        self.peaks_button.setEnabled(self.result is not None and self.result["has_profiles"])

    def run(self):
        ref = self.controller.ref
        if ref is None: return
        gi = self.geometry.currentIndex() == 1
        deltas = [widget.value() for widget in self.delta_widgets]
        use_deltas = self.overrides.isChecked() and not gi
        request = SmiReductionRequest(ref.uid, stream=ref.stream, geometry="grazing" if gi else "transmission",
            n_q=self.nq.value(), n_chi=self.nchi.value(), n_qxy=self.nqxy.value(), n_qz=self.nqz.value(),
            pixel_splitting=self.splitting.value(), solid_angle=self.solid.isChecked(),
            dezinger=self.dezinger.value(), dezinger_kernel=self.kernel.value(),
            saxs_mask=self.saxs_mask.text().strip() if not gi else "", waxs_mask=self.waxs_mask.text().strip(),
            incident_angle=None if self.incident_auto.isChecked() or not gi else self.incident.value(),
            saxs_beam_delta=tuple(deltas[:2]) if use_deltas else None,
            waxs_beam_delta=tuple(deltas[2:4]) if use_deltas else None,
            saxs_distance_delta=deltas[4] if use_deltas else None, frame_maps=self.frame_maps.isChecked())
        try: self.controller.start(request)
        except Exception as exc: self.status.setText(str(exc))

    def open_result(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open SciView SMI result", str(results_directory()), "HDF5 (*.h5)")
        if path: self.controller.open_result(path)

    def result_changed(self, result):
        self.io.invalidate(); self.result = result
        self._waterfall_data = None
        self._guard = True
        self.frame.setMaximum(max(0, result["frames"] - 1) if result else 0)
        self.frame.setValue(0); self.mode.setCurrentIndex(0)
        previous = self.label_signal.currentText()
        self.label_signal.clear(); self.label_signal.addItem("frame")
        if result: self.label_signal.addItems([k for k in result.get("frame_labels", {}) if k != "frame"])
        if self.label_signal.findText(previous) >= 0: self.label_signal.setCurrentText(previous)
        self._guard = False
        self.provenance.setPlainText(json.dumps(result["provenance"], indent=2) if result else "")
        self.update_buttons(); self.render()

    def render(self, *_):
        if self._guard: return
        self.io.invalidate()
        per_frame = self.mode.currentIndex() == 1
        waterfall = per_frame and self.presentation.currentIndex() == 0
        self.presentation.setEnabled(per_frame)
        self.spacing.setEnabled(waterfall)
        self.spacing.setToolTip("Decades per trace in log mode; fraction of robust intensity span in linear mode")
        self.frame.setEnabled(per_frame and not waterfall and self.result is not None and self.result["has_profiles"])
        self.plot.setLogMode(x=self.log_x.isChecked(), y=self.log_y.isChecked() and not waterfall)
        self._clear_waterfall()
        if self.result is None:
            for line in self.lines: line.clear()
            return
        path = self.result["path"]
        if waterfall:
            for line in self.lines: line.clear()
            if self._waterfall_data is not None:
                self._draw_waterfall(self._waterfall_data)
            else:
                self.io.submit(lambda: read_waterfall(path), self._draw_waterfall,
                               lambda exc: self.status.setText(str(exc)))
            return
        index = self.frame.value() if self.mode.currentIndex() else None
        power = self.power.value()
        def apply(payload):
            q, curves = payload
            for line in self.lines: line.clear()
            if q is None:
                self.plot.setTitle("No I(q) product — use Transform for GI maps")
                return
            with np.errstate(divide="ignore", invalid="ignore"):
                for label, values in curves.items():
                    slot = 1 if label == "SAXS" else 2 if label == "WAXS" else 0
                    self.lines[slot].setData(q, values * q**power)
            self.plot.setLabel("left", "I(q)" if power == 0 else f"I(q) × q^{power:g}")
            title = "merged" if index is None else frame_label(index, self.label_signal.currentText(), self.result.get("frame_labels"))
            self.plot.setTitle(f"{self.result['uid'][:12]} · {title} · q in nm⁻¹")
            self.trace_label.setText(title)
            self.refresh_theme()
        self.io.submit(lambda: read_curves(path, index), apply, lambda exc: self.status.setText(str(exc)))

    def _clear_waterfall(self):
        for line in self._waterfall_lines: self.plot.removeItem(line)
        self._waterfall_lines.clear(); self._hover_traces.clear()

    def _draw_waterfall(self, payload):
        self._waterfall_data = payload
        if payload is None:
            self.trace_label.setText("No per-frame I(q) in this result")
            return
        q, intensity, indices, total = payload
        values = waterfall_values(q, intensity, power=self.power.value(),
                                  spacing=self.spacing.value(), logarithmic=self.log_y.isChecked())
        colors = pg.colormap.get("viridis").mapToQColor(np.linspace(.1, .9, len(indices)))
        for i, index in enumerate(indices):
            line = self.plot.plot(q, values[i], pen=pg.mkPen(colors[i], width=1.3))
            line.setClipToView(True)
            self._waterfall_lines.append(line)
            with np.errstate(divide="ignore", invalid="ignore"):
                display_x = np.log10(q) if self.log_x.isChecked() else q
            self._hover_traces.append((display_x, values[i], int(index)))
        scale = "log10(I × q^p)" if self.log_y.isChecked() else "I × q^p"
        self.plot.setLabel("left", f"{scale} + display offset")
        self.plot.setTitle(f"{self.result['uid'][:12]} · per-frame waterfall")
        note = f"{len(indices)} of {total} frames" if len(indices) != total else f"All {total} frames"
        self.trace_label.setText(f"{note} · acquisition order · hover over a trace for {self.label_signal.currentText()} · offsets are display-only")
        self.refresh_theme()

    def hover_trace(self, scene_pos):
        if not self._hover_traces or not self.plot.plotItem.sceneBoundingRect().contains(scene_pos): return
        view = self.plot.plotItem.vb
        point = view.mapSceneToView(scene_pos)
        sx, sy = view.viewPixelSize()
        best = (float("inf"), None)
        for x, y, index in self._hover_traces:
            finite = np.isfinite(x) & np.isfinite(y)
            if not finite.any(): continue
            xf, yf = x[finite], y[finite]
            # Interpolate in displayed coordinates so picking works between q bins.
            if point.x() < xf[0] or point.x() > xf[-1]: continue
            value = np.interp(point.x(), xf, yf)
            distance = abs(value-point.y()) / max(abs(sy), 1e-30)
            if distance < best[0]: best = distance, index
        if best[1] is not None and best[0] < 15:
            text = frame_label(best[1], self.label_signal.currentText(), self.result.get("frame_labels"))
            self.trace_label.setText(text)
            QToolTip.showText(self.plot.mapToGlobal(self.plot.mapFromScene(scene_pos)), text, self.plot)

    def refresh_theme(self):
        if not hasattr(self, "plot"): return
        colors = style_plot(self.plot.plotItem)
        self.plot.setBackground(colors["base"])
        self.lines[0].setPen(pg.mkPen(colors["text"], width=1.5))
        self.lines[1].setPen(pg.mkPen("#168b9c", width=1.5))
        self.lines[2].setPen(pg.mkPen("#b04ab7", width=1.5))

    def open_peaks(self):
        if self.result is None: return
        for i in range(self.app.tab_widget.count()):
            tab = self.app.tab_widget.widget(i)
            if hasattr(tab, "open_smi_cache"):
                tab.load_path(self.result["path"])
                self.app.tab_widget.setCurrentIndex(i)
                return


class SmiTransformTab(QWidget):
    def __init__(self, app, controller):
        super().__init__()
        self.controller, self.result = controller, None
        self.io = LatestJob(self)
        self._guard = False
        self._view_key = None
        self._loaded_map = None
        root = QHBoxLayout(self)
        controls = QVBoxLayout(); root.addLayout(controls)
        self.status = readable_status("Reduce an SMI run in Reduction, or open a saved SciView result there.")
        self.status.setMaximumWidth(400); controls.addWidget(self.status)
        self.product = QComboBox(); controls.addWidget(self.product)
        self.frame = _spin(0, 0, 0); self.frame.setPrefix("Frame "); controls.addWidget(self.frame)
        self.log = QCheckBox("Log intensity"); self.log.setChecked(True); controls.addWidget(self.log)
        self.cmap = QComboBox(); self.cmap.addItems(["viridis", "plasma", "inferno", "magma"]); controls.addWidget(self.cmap)
        self.label_signal = QComboBox(); self.label_signal.addItem("frame")
        controls.addWidget(QLabel("Frame label (primary signal)")); controls.addWidget(self.label_signal)
        self.cursor = readable_status("Move the cursor over the map"); self.cursor.setMaximumWidth(400); controls.addWidget(self.cursor)
        self.raw_button = QPushButton("Open this acquisition frame in raw viewer")
        self.raw_button.clicked.connect(lambda: app.select_smi_frame(self.result["uid"], self.frame.value()) if self.result else None)
        controls.addWidget(self.raw_button); controls.addStretch()
        visuals = QVBoxLayout(); root.addLayout(visuals, 1)
        self.graphics = pg.GraphicsLayoutWidget(); visuals.addWidget(self.graphics, 1)
        self.frame_label = readable_status("Merged map")
        visuals.addWidget(self.frame_label)
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(0); self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self.frame.setValue)
        visuals.addWidget(self.frame_slider)
        self.plot = self.graphics.addPlot(row=0, col=0)
        self.image = pg.ImageItem(axisOrder="row-major"); self.plot.addItem(self.image)
        self.hist = pg.HistogramLUTItem(image=self.image); self.graphics.addItem(self.hist, row=0, col=1)
        self.data = None
        self.graphics.scene().sigMouseMoved.connect(self.mouse_moved)
        self.product.currentIndexChanged.connect(self.render); self.frame.valueChanged.connect(self.render)
        self.log.toggled.connect(self.render); self.cmap.currentTextChanged.connect(self.palette)
        self.label_signal.currentTextChanged.connect(self.update_frame_label)
        controller.result_changed.connect(self.result_changed)
        controller.context_changed.connect(self.context_changed)
        QApplication.instance().aboutToQuit.connect(self.io.close)
        self.palette(); self.raw_button.setEnabled(False); self.refresh_theme()

    def palette(self, *_):
        self.image.setLookupTable(pg.colormap.get(self.cmap.currentText()).getLookupTable(nPts=256))

    def context_changed(self, ref):
        if self.result is not None and ref is not None and ref.index <= self.frame.maximum():
            self.frame.setValue(ref.index)

    def result_changed(self, result):
        self.io.invalidate(); self.result = result; self._view_key = None
        self._loaded_map = None
        self._guard = True
        self.product.clear()
        if result: self.product.addItems(list(result["maps"]))
        previous = self.label_signal.currentText()
        self.label_signal.clear(); self.label_signal.addItem("frame")
        if result: self.label_signal.addItems([k for k in result.get("frame_labels", {}) if k != "frame"])
        if self.label_signal.findText(previous) >= 0: self.label_signal.setCurrentText(previous)
        self._guard = False
        self.render()

    def render(self, *_):
        if self._guard: return
        self.io.invalidate()
        if self.result is None or not self.product.currentText():
            self.image.clear(); self.data = None; self.raw_button.setEnabled(False)
            self.frame_slider.setEnabled(False); self.frame_label.setText("No map loaded")
            self.status.setText("No 2D product loaded. Reduce or open a result in Reduction.")
            return
        name, path = self.product.currentText(), self.result["path"]
        count = self.result["maps"][name]
        self.frame.blockSignals(True); self.frame.setMaximum(max(0, count-1)); self.frame.blockSignals(False)
        self.frame.setEnabled(count > 0); self.raw_button.setEnabled(count > 0)
        self.frame_slider.blockSignals(True)
        self.frame_slider.setMaximum(max(0, count-1)); self.frame_slider.setValue(self.frame.value())
        self.frame_slider.setEnabled(count > 0); self.frame_slider.blockSignals(False)
        index, logarithmic = self.frame.value(), self.log.isChecked()
        key = (path, name)
        def apply(payload):
            x, y, raw, xlabel, ylabel = payload
            if len(x) < 2 or len(y) < 2 or not np.allclose(np.diff(x), np.diff(x)[0]) or not np.allclose(np.diff(y), np.diff(y)[0]):
                raise ValueError("This map needs uniform physical axes; nonuniform coordinates cannot use an image rectangle")
            self.data = (x, y, raw)
            self._loaded_map = (path, name, index, payload)
            with np.errstate(divide="ignore", invalid="ignore"):
                display = np.where(raw > 0, np.log10(raw), np.nan) if logarithmic else raw
            finite = display[np.isfinite(display)]
            lo, hi = np.percentile(finite, [2, 99.5]) if finite.size else (0, 1)
            if hi <= lo: hi = lo + 1
            self.image.setImage(np.asarray(display, dtype="float32"), levels=(lo, hi), autoLevels=False)
            dx, dy = float(x[1]-x[0]), float(y[1]-y[0])
            self.image.setRect(QRectF(float(x[0]-dx/2), float(y[0]-dy/2), len(x)*dx, len(y)*dy))
            self.plot.setLabel("bottom", xlabel); self.plot.setLabel("left", ylabel)
            if key != self._view_key: self.plot.autoRange(); self._view_key = key
            self.status.setText(f"{self.result['uid'][:12]} · {name}" + (f" · frame {index}" if count else " · merged"))
            self.update_frame_label(); self.refresh_theme()
        if self._loaded_map is not None and self._loaded_map[:3] == (path, name, index):
            apply(self._loaded_map[3])
        else:
            self.io.submit(lambda: read_map(path, name, index), apply, lambda exc: self.status.setText(str(exc)))

    def update_frame_label(self, *_):
        if self._guard or self.result is None: return
        name = self.product.currentText()
        count = self.result["maps"].get(name, 0)
        text = frame_label(self.frame.value(), self.label_signal.currentText(), self.result.get("frame_labels")) if count else "Merged (all frames)"
        self.frame_label.setText(f"{text}" + (f" · {self.frame.value()+1}/{count}" if count else ""))
        self.plot.setTitle(text)

    def refresh_theme(self):
        if not hasattr(self, "plot"): return
        colors = style_plot(self.plot)
        self.graphics.setBackground(colors["base"])
        from sciview.interfaces.theme.app_style import AppStyle
        self.hist.axis.setTickFont(AppStyle.make_font("body"))
        self.hist.axis.setPen(colors["text"]); self.hist.axis.setTextPen(colors["text"])

    def mouse_moved(self, pos):
        if self.data is None or not self.plot.sceneBoundingRect().contains(pos): return
        point = self.plot.vb.mapSceneToView(pos)
        x, y, raw = self.data
        ix = int(np.floor((point.x() - x[0])/(x[1]-x[0]) + .5))
        iy = int(np.floor((point.y() - y[0])/(y[1]-y[0]) + .5))
        if 0 <= ix < len(x) and 0 <= iy < len(y):
            self.cursor.setText(f"x={x[ix]:.5g}, y={y[iy]:.5g}\nI={raw[iy, ix]:.6g} (linear intensity)")
