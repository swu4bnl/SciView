"""SMI adapters that retain SciView's native ring picking and raster mask tools."""
from dataclasses import asdict
import json

import numpy as np
from PyQt5.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QPushButton, QHBoxLayout, QFileDialog, QLabel

from tabs.calibration_tab import CalibrationApp
from tabs.mask_tab import MaskApp, MaskLayer
from tabs.base_image_tab import BaseImageTab
from sciview.interfaces.services.latest_job import LatestJob
from sciview.interfaces.stable_qt.widgets.status_label import readable_status
from sciview.processing.smi_geometry import AGB_Q1, fit_ring_points, refine_ring_pixels, calibration_profiles


class InstrumentHost:
    """Prevent native tools from publishing SMI pixels/calibration into CMS state."""
    def __init__(self, app):
        self.app = app
        self.image_data = None
        self.calibration = None
        self.display_settings = app.display_settings
    def show_status(self, message): self.app.show_status(message)
    def get_shared_calibration(self, *args): return None
    def get_shared_mask(self): return None
    def publish_shared_display_settings(self, settings, source_tab=None):
        self.app.publish_shared_display_settings(settings, source_tab=source_tab)
    def get_image_path(self): return None
    def publish_shared_info_text(self, *args, **kwargs): pass


def session_buttons(tab, controller):
    row = QHBoxLayout()
    def save():
        path, _ = QFileDialog.getSaveFileName(tab, "Save SMI calibration and user masks", "smi-instrument.h5", "HDF5 (*.h5)")
        if path:
            try: controller.save_session(path)
            except Exception as exc: controller.status.emit(str(exc))
    def load():
        path, _ = QFileDialog.getOpenFileName(tab, "Load SMI calibration and user masks", "", "HDF5 (*.h5)")
        if path:
            try: controller.load_session(path)
            except Exception as exc: controller.status.emit(str(exc))
    for text, fn in (("Save SMI session", save), ("Load SMI session", load)):
        button = QPushButton(text); button.clicked.connect(fn); row.addWidget(button)
    tab.layout().insertLayout(1, row)


class SmiCalibrationTab(CalibrationApp):
    def __init__(self, app, controller):
        self.instrument = controller
        self.payload = None
        self._profile_signature = None
        self._profile_payload = None
        self.ring_sets = []
        self._smi_guard = True
        super().__init__(InstrumentHost(app))
        self.fit_job = LatestJob(self)
        self.profile_job = LatestJob(self)
        self.banner = readable_status("Select a primary SMI frame. Ring center is the direct-beam center, not the beamstop motor position.")
        self.layout().insertWidget(0, self.banner)
        session_buttons(self, controller)
        row = QHBoxLayout()
        self.ring_mode = QComboBox(); self.ring_mode.addItems(["Center only (unknown ring)", "Known q: center + distance", "AgB order: center + distance"])
        self.ring_q = QDoubleSpinBox(); self.ring_q.setDecimals(6); self.ring_q.setRange(.000001, 1000); self.ring_q.setValue(AGB_Q1); self.ring_q.setSuffix(" nm⁻¹")
        self.ring_order = QSpinBox(); self.ring_order.setRange(1, 100); self.ring_order.setPrefix("AgB order ")
        self.refine = QCheckBox("Refine picks using image intensity"); self.refine.setChecked(True)
        self.fit_button = QPushButton("Fit metadata-relative corrections")
        self.fit_button.clicked.connect(self.fit_calibrant)
        for widget in (self.ring_mode, self.ring_q, self.ring_order, self.refine, self.fit_button): row.addWidget(widget)
        self.layout().insertLayout(2, row)
        rings = QHBoxLayout()
        self.rings_label = QLabel("No rings stored for joint fit")
        for text, callback in (("Store picked ring + q", self.store_ring), ("Fit stored rings jointly", self.fit_joint),
                               ("Clear stored rings", self.clear_stored_rings)):
            button = QPushButton(text); button.clicked.connect(callback); rings.addWidget(button)
        rings.addWidget(self.rings_label); self.layout().insertLayout(3, rings)
        self.apply_button = QPushButton("Apply fitted / edited center and distance to SMI reduction")
        self.apply_button.clicked.connect(self.apply_correction); self.layout().insertWidget(3, self.apply_button)
        reset = QPushButton("Reset to metadata + bundled calibration")
        reset.clicked.connect(lambda: controller.reset_correction(self.payload["reference"].detector) if self.payload else None)
        self.layout().insertWidget(4, reset)
        for widget in (self.spin_orient, self.spin_tilt, self.spin_phi, self.spin_pixel, self.spin_energy_ev, self.spin_wl_ang): widget.setEnabled(False)
        self._smi_guard = False
        controller.frame_ready.connect(self.set_frame)
        controller.status.connect(self.show_status)
        from PyQt5.QtWidgets import QApplication
        QApplication.instance().aboutToQuit.connect(self.fit_job.close)
        QApplication.instance().aboutToQuit.connect(self.profile_job.close)

    def _init_calibration(self):
        self.calibration = None

    def show_status(self, text):
        self.banner.setText(text)

    def set_frame(self, payload):
        self.fit_job.invalidate()
        self.profile_job.invalidate()
        self.payload = payload
        self.fit_button.setEnabled(payload is not None)
        self.apply_button.setEnabled(payload is not None)
        self.setEnabled(payload is not None)
        if payload is None: return
        self._profile_signature = None
        self.clear_stored_rings()
        self._smi_guard = True
        self._calibration_update_timer.stop()
        self.image_data = payload["array"]
        geo = payload["geometry"]
        self.clear_ring_points()
        self.spin_x.blockSignals(True); self.spin_y.blockSignals(True); self.spin_dist.blockSignals(True)
        # WAXS editable values are backend row/col, explicitly mapped to raw x/y.
        x, y = geo.center_xy_raw
        self.spin_x.setValue(x); self.spin_y.setValue(y); self.spin_dist.setValue(geo.distance_mm/1000)
        for widget in (self.spin_x, self.spin_y, self.spin_dist): widget.blockSignals(False)
        for widget, value in ((self.spin_energy_ev, geo.energy_ev), (self.spin_wl_ang, 12398.4198/geo.energy_ev), (self.spin_pixel, geo.pixel_mm*1000)):
            widget.blockSignals(True); widget.setValue(value); widget.blockSignals(False)
        self._smi_guard = False
        self.image_viewer.clear_overlays()
        BaseImageTab.update_plot(self, self.image_data)
        self.banner.setText(f"{geo.detector.upper()} · frame {geo.frame} · metadata-resolved D={geo.distance_mm:.4f} mm, E={geo.energy_ev:.3f} eV\n"
            "Fit tweaks center/distance; energy, detector tilt and WAXS panel geometry are fixed. Ring center does not reposition beamstop motors.")
        self.update_plot_calibration()

    def calculate_ring_center(self):
        if self.payload and self.payload["geometry"].detector == "waxs":
            self.banner.setText("WAXS is a folded arc: use Fit metadata-relative corrections on picked points, not a flat circle fit.")
            return
        super().calculate_ring_center()

    def update_plot(self, image_data=None):
        if self.payload is not None:
            BaseImageTab.update_plot(self, self.image_data)

    def update_plot_calibration(self):
        if self._smi_guard or self.payload is None: return
        self._refresh_calibration_crosshair()
        payload = self.payload
        reference = payload["reference"]
        if reference.detector == "saxs": row, col = self.spin_y.value(), self.spin_x.value()
        else: row, col = self.spin_x.value(), self.spin_y.value()-.08*reference.arc
        delta = (row-reference.row, col-reference.col, self.spin_dist.value()*1000-reference.distance_mm)
        geo = reference.corrected(delta)
        excluded = payload["static"] | payload["dynamic"]
        user = self.instrument.user_masks.get((geo.detector, geo.shape))
        if user is not None: excluded = excluded | user
        signature = (id(payload), delta, id(user))
        if signature == self._profile_signature and self._profile_payload is not None:
            self.draw_profiles(self._profile_payload)
            return
        def apply(profiles):
            self._profile_signature = signature; self._profile_payload = profiles
            self.draw_profiles(profiles)
        self.profile_job.submit(lambda: calibration_profiles(payload["array"], geo, excluded), apply,
                                lambda exc: self.banner.setText(f"Profile preview: {exc}"))

    def draw_profiles(self, profiles):
        q, curves = profiles
        self.ax_plot.clear()
        for name, values in curves.items(): self.ax_plot.plot(q, values, label=name)
        if self.selected_standard:
            for value in self.standards_db.get(self.selected_standard, []):
                self.ax_plot.axvline(value*10, color="magenta", linestyle="--", alpha=.6)
        self.ax_plot.set_xlabel("q (nm⁻¹)"); self.ax_plot.set_ylabel("Mean intensity")
        scale = self.scale_combo.currentText()
        self.ax_plot.set_xscale("log" if scale in ("logx", "loglog") else "linear")
        self.ax_plot.set_yscale("log" if scale in ("logy", "loglog") else "linear")
        self.ax_plot.legend()
        from sciview.interfaces.theme.app_style import AppStyle
        AppStyle.apply_matplotlib_figure_theme(self.fig_plot)
        self.canvas_plot.draw_idle()

    def _get_image_array_for_click_tools(self):
        return self.image_data  # ndarray.data is a memoryview, not a SciAnalysis object

    def clear_stored_rings(self):
        self.ring_sets = []
        if hasattr(self, "rings_label"): self.rings_label.setText("No rings stored for joint fit")

    def store_ring(self):
        if self.payload is None: return
        if self.ring_mode.currentIndex() == 0:
            self.banner.setText("Choose known q or AgB order before storing a ring")
            return
        points = [list(p) for p in self._ring_points if p is not None]
        if len(points)<5:
            self.banner.setText("Pick five or more points on this ring")
            return
        q = self.ring_q.value() if self.ring_mode.currentIndex()==1 else AGB_Q1*self.ring_order.value()
        self.ring_sets.append((points, q))
        self.rings_label.setText(f"{len(self.ring_sets)} rings: " + ", ".join(f"{q:.4g} nm⁻¹" for _, q in self.ring_sets))
        self.clear_ring_points()

    def fit_joint(self):
        if not self.ring_sets:
            self.banner.setText("Store one or more known-q rings first")
            return
        self.fit_calibrant(joint=True)

    def _add_tab_specific_status(self, info_lines):
        if self.payload:
            info_lines.append(json.dumps(self.payload["reference"].metadata, indent=2, default=str))

    def fit_calibrant(self, _checked=False, *, joint=False):
        if self.payload is None: return
        points = [p for p in self._ring_points if p is not None]
        payload = self.payload
        geo = payload["geometry"]
        mode = self.ring_mode.currentIndex()
        expected = None if mode == 0 else self.ring_q.value() if mode == 1 else AGB_Q1*self.ring_order.value()
        refine = self.refine.isChecked()
        ring_sets = list(self.ring_sets) if joint else [(points, expected)]
        mask = payload["static"] | payload["dynamic"]
        user = self.instrument.user_masks.get((geo.detector, geo.shape))
        if user is not None: mask = mask | user
        self.banner.setText("Fitting ring against metadata-resolved geometry…")
        self.fit_button.setEnabled(False)
        def work():
            all_picks, targets = [], []
            for seeds, q in ring_sets:
                picks = refine_ring_pixels(payload["array"], geo, seeds, mask) if refine else seeds
                all_picks.extend(picks); targets.extend([q]*len(picks))
            known = targets if joint else expected
            return fit_ring_points(geo, all_picks, known, fit_distance=joint or mode != 0)
        def done(result):
            self.fit_button.setEnabled(True)
            corrected = geo.corrected(result["delta"])
            x, y = corrected.center_xy_raw
            self.spin_x.setValue(x); self.spin_y.setValue(y); self.spin_dist.setValue(corrected.distance_mm/1000)
            self.banner.setText(f"Fit: Δrow={result['delta'][0]:+.4f} px, Δcol={result['delta'][1]:+.4f} px, "
                f"ΔD={result['delta'][2]:+.4f} mm; q={result['q']:.6g} nm⁻¹; RMS={result['rms']:.4g}; {result['n']} picks. Apply to use these tweaks.")
        def error(exc): self.fit_button.setEnabled(True); self.banner.setText(str(exc))
        self.fit_job.submit(work, done, error)

    def apply_correction(self):
        if self.payload is None: return
        reference = self.payload["reference"]
        if reference.detector == "saxs": row, col = self.spin_y.value(), self.spin_x.value()
        else: row, col = self.spin_x.value(), self.spin_y.value()-.08*reference.arc
        try:
            self.instrument.set_correction(reference.detector, (row-reference.row, col-reference.col, self.spin_dist.value()*1000-reference.distance_mm))
        except ValueError as exc: self.banner.setText(str(exc))

    def export_calibration(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save SMI instrument session", "smi-instrument.h5", "HDF5 (*.h5)")
        if path: self.instrument.save_session(path)

    def export_1d_profiles(self):
        if self._profile_payload is None:
            self.banner.setText("Wait for a calibration profile preview before exporting")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export SMI calibration profiles", "smi-calibration-profiles.csv", "CSV (*.csv)")
        if path:
            q, curves = self._profile_payload
            np.savetxt(path, np.column_stack([q, *curves.values()]), delimiter=",",
                       header=",".join(["q_nm^-1", *curves]), comments="")

    def closeEvent(self, event):
        self.fit_job.close(); self.profile_job.close()
        super().closeEvent(event)


class SmiMaskTab(MaskApp):
    def __init__(self, app, controller):
        self.instrument = controller
        self.payload = None
        self._scope = None
        self._loading = False
        super().__init__(InstrumentHost(app))
        self.banner = readable_status("Draw user exclusions over the generated SMI masks. Default/dynamic masks cannot be erased by user tools.")
        self.layout().insertWidget(0, self.banner)
        session_buttons(self, controller)
        row = QHBoxLayout()
        self.static_visible = QCheckBox("Show static defaults"); self.static_visible.setChecked(True)
        self.dynamic_visible = QCheckBox("Show dynamic exclusions"); self.dynamic_visible.setChecked(True)
        self.shadow = QCheckBox("SAXS WAXS-shadow exclusion"); self.shadow.setChecked(controller.shadow)
        self.aperture = QCheckBox("SAXS aperture exclusion"); self.aperture.setChecked(controller.aperture)
        for widget in (self.static_visible, self.dynamic_visible, self.shadow, self.aperture): row.addWidget(widget)
        self.layout().insertLayout(2, row)
        self.static_visible.toggled.connect(self._refresh_mask_overlay); self.dynamic_visible.toggled.connect(self._refresh_mask_overlay)
        self.shadow.toggled.connect(self.generated_options); self.aperture.toggled.connect(self.generated_options)
        load_spec = QPushButton("Load SMI base-mask JSON…")
        load_spec.clicked.connect(self.choose_spec)
        self.layout().insertWidget(3, load_spec)
        controller.frame_ready.connect(self.set_frame); controller.status.connect(self.show_status)

    def choose_spec(self):
        if self.payload is None: return
        path, _ = QFileDialog.getOpenFileName(self, "SMI base-mask specification", "", "JSON (*.json)")
        if path:
            try:
                from sciview.processing.smi_geometry import load_mask_spec
                kind = self.payload["geometry"].detector
                self.instrument.base_specs[kind] = load_mask_spec(kind, path)
                self.instrument.changed.emit(); self.instrument.refresh()
            except Exception as exc: self.banner.setText(str(exc))

    def _init_calibration(self): self.calibration = None

    def show_status(self, text): self.banner.setText(text)

    def set_frame(self, payload):
        self.payload = payload
        self.setEnabled(payload is not None)
        if payload is None:
            self._set_drawing_enabled_from_session(False)
            return
        geo = payload["geometry"]
        scope = (geo.detector, geo.shape)
        self._set_drawing_enabled_from_session(False)
        self._loading = True
        self.image_data = payload["array"]
        if scope != self._scope or self.mask_layers is not self.instrument.layers.get(scope):
            self._scope = scope
            self.mask_layers = self.instrument.layers.get(scope, [])
            if not self.mask_layers and scope in self.instrument.user_masks:
                self.mask_layers = [MaskLayer(self.instrument.user_masks[scope], "Imported user exclusions")]
            if not self.mask_layers: self.mask_layers = [MaskLayer(np.zeros(geo.shape, bool), "User exclusions")]
            self.instrument.layers[scope] = self.mask_layers
            self.combine_method = self.instrument.combine_methods.get(scope, "OR")
            self.combine_or_radio.blockSignals(True); self.combine_and_radio.blockSignals(True)
            self.combine_or_radio.setChecked(self.combine_method == "OR")
            self.combine_and_radio.setChecked(self.combine_method == "AND")
            self.combine_or_radio.blockSignals(False); self.combine_and_radio.blockSignals(False)
        self._update_layer_list()
        self._loading = False
        self._update_combined_mask()
        self.image_viewer.set_image(self.image_data)
        self._refresh_mask_overlay()
        for widget, value in ((self.shadow, self.instrument.shadow), (self.aperture, self.instrument.aperture)):
            widget.blockSignals(True); widget.setChecked(value); widget.blockSignals(False)
        self.banner.setText(f"{geo.detector.upper()} · frame {geo.frame}: native layers below are USER masks only. "
                            "Static (blue) and dynamic (red) masks are generated separately; hiding them changes display only.")

    def generated_options(self, *_):
        self.instrument.shadow = self.shadow.isChecked()
        self.instrument.aperture = self.aperture.isChecked()
        self.instrument.changed.emit(); self.instrument.refresh()

    def update_plot(self, image_data=None):
        if self.payload is not None and self.image_data is not None:
            if self.image_viewer.source_array is not self.image_data: self.image_viewer.set_image(self.image_data)
            self._refresh_mask_overlay()

    def _update_combined_mask(self):
        super()._update_combined_mask()
        if not self._loading and self._scope is not None:
            self.instrument.layers[self._scope] = self.mask_layers
            self.instrument.combine_methods[self._scope] = self.combine_method
            self.instrument.set_user_mask(*self._scope, self.combined_mask)

    def _refresh_mask_overlay(self, *_):
        super()._refresh_mask_overlay()
        if self.payload is None or not hasattr(self, "static_visible"): return
        for key, mask, visible, color in (("smi-static", self.payload["static"], self.static_visible.isChecked(), "blue"),
                                          ("smi-dynamic", self.payload["dynamic"], self.dynamic_visible.isChecked(), "red")):
            if visible: self.image_viewer.add_mask_overlay(key, mask, group="smi-generated", color=color, alpha=.3)
            else: self.image_viewer.remove_overlay(key)

    def _load_instrument_mask(self, detector_key=None, mask_path=None):
        if hasattr(self, "banner"): self.banner.setText("SMI defaults are generated automatically. Import a custom mask as a user layer instead.")

    def _apply_mask_to_tabs(self):
        self._update_combined_mask()
        self.banner.setText("User exclusions applied to subsequent SMI reductions, layered over static/dynamic masks.")
