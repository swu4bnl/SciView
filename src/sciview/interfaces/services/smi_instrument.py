"""Detector-scoped SMI geometry corrections and user exclusions for native tools."""
from dataclasses import asdict
import json
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

from sciview.interfaces.services.latest_job import LatestJob
from sciview.processing.smi_geometry import resolve_geometry, generated_masks, load_mask_spec, detector_kind


class SmiInstrumentController(QObject):
    frame_ready = pyqtSignal(object)
    changed = pyqtSignal()
    status = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.io = LatestJob(self)
        self.ref = None
        self.payload = None
        self.corrections = {}  # detector -> tweaks relative to backend defaults
        self.user_masks = {}   # (detector, raw shape) -> excluded pixels
        self.layers = {}       # native user layers, kept separate from generated masks
        self.combine_methods = {}
        self.base_specs = {}
        self.shadow = True
        self.aperture = True
        self._source = None

    def set_frame(self, ref, array, scalars):
        self.ref = ref
        self.payload = None
        self._source = (ref, array, scalars)
        self.frame_ready.emit(None)
        kind = detector_kind(ref.detector)
        if kind is None or ref.stream != "primary":
            self.io.invalidate()
            self.status.emit("SMI calibration and automatic masks require a primary SAXS/WAXS frame")
            return
        delta = self.corrections.get(kind, (0., 0., 0.))
        base = self.base_specs.get(kind)
        shadow, aperture = self.shadow, self.aperture
        def work():
            from sciview.sources.tiled_client import tiled_manager
            run = tiled_manager.get_or_load_catalog(ref.profile)[ref.uid]
            reference = resolve_geometry(run, ref, array.shape, scalars)
            effective = reference.corrected(delta)
            spec = base if base is not None else load_mask_spec(kind)
            static, dynamic = generated_masks(effective, spec, shadow=shadow, aperture=aperture)
            return dict(ref=ref, array=array, reference=reference, geometry=effective,
                        static=static, dynamic=dynamic, base_spec=spec)
        def apply(payload):
            self.payload = payload
            self.base_specs.setdefault(kind, payload["base_spec"])
            self.frame_ready.emit(payload)
        self.status.emit("Resolving SMI metadata and automatic masks…")
        self.io.submit(work, apply, lambda exc: self.status.emit(f"SMI metadata/mask error: {exc}"))

    def refresh(self):
        if self._source is not None: self.set_frame(*self._source)

    def set_correction(self, kind, delta):
        if len(delta)!=3 or not np.isfinite(delta).all(): raise ValueError("Three finite corrections required")
        if self.payload is not None and self.payload["reference"].detector == kind:
            if self.payload["reference"].distance_mm + delta[2] <= 0:
                raise ValueError("Corrected sample-detector distance must be positive")
        self.corrections[kind] = tuple(float(v) for v in delta)
        self.changed.emit()
        self.refresh()

    def reset_correction(self, kind):
        self.corrections.pop(kind, None); self.changed.emit(); self.refresh()

    def set_user_mask(self, kind, shape, excluded):
        key = (kind, tuple(shape))
        if excluded is None: self.user_masks.pop(key, None)
        else:
            array = np.asarray(excluded, dtype=bool)
            if array.shape != tuple(shape): raise ValueError("User mask shape mismatch")
            self.user_masks[key] = array.copy()
        self.changed.emit()

    def reduction_inputs(self):
        from smi_tiled.defaults import LOADER_DEFAULTS
        out = {}
        if "saxs" in self.corrections:
            dr, dc, dd = self.corrections["saxs"]
            out.update(saxs_beam_delta=(LOADER_DEFAULTS.saxs_row_delta_px+dr, LOADER_DEFAULTS.saxs_col_delta_px+dc),
                       saxs_distance_delta=LOADER_DEFAULTS.saxs_distance_delta_mm+dd)
        if "waxs" in self.corrections:
            dr, dc, dd = self.corrections["waxs"]
            from smi_tiled.integrator import WAXSCalibration
            out.update(waxs_beam_delta=(LOADER_DEFAULTS.waxs_row_delta_px+dr, LOADER_DEFAULTS.waxs_col_delta_px+dc),
                       waxs_distance=WAXSCalibration().sample_distance_mm+dd)
        out.update(shadow=self.shadow, aperture=self.aperture)
        return out

    def save_session(self, path):
        """Portable geometry tweaks plus raster masks; original specs stay lossless."""
        import h5py
        with h5py.File(path, "w") as f:
            f.attrs.update(schema="sciview.smi.instrument.v1", coordinates="raw-row-column",
                           corrections=json.dumps(self.corrections), base_specs=json.dumps(self.base_specs),
                           shadow=self.shadow, aperture=self.aperture)
            for i, ((kind, shape), mask) in enumerate(self.user_masks.items()):
                ds = f.create_dataset(f"user_masks/{i}", data=mask, compression="gzip")
                ds.attrs["detector"] = kind
            for i, ((kind, shape), layers) in enumerate(self.layers.items()):
                group = f.create_group(f"layers/{i}")
                group.attrs["detector"] = kind
                group.attrs["shape"] = shape
                group.attrs["combine"] = self.combine_methods.get((kind, shape), "OR")
                for j, layer in enumerate(layers):
                    ds = group.create_dataset(str(j), data=layer.data, compression="gzip")
                    ds.attrs.update(name=layer.name, visible=layer.visible, source=layer.source)

    def load_session(self, path):
        import h5py
        with h5py.File(path, "r") as f:
            if f.attrs.get("schema") != "sciview.smi.instrument.v1": raise ValueError("Not an SMI instrument session")
            corrections = json.loads(f.attrs["corrections"])
            for kind, delta in corrections.items():
                if kind not in ("saxs", "waxs") or len(delta)!=3 or not np.isfinite(delta).all():
                    raise ValueError("Invalid geometry corrections")
            masks = {}
            for ds in f.get("user_masks", {}).values():
                kind = str(ds.attrs["detector"])
                if kind not in ("saxs", "waxs") or ds.ndim!=2: raise ValueError("Invalid user mask")
                masks[(kind, ds.shape)] = ds[...].astype(bool)
            specs = json.loads(f.attrs["base_specs"])
            from types import SimpleNamespace
            layers = {}
            combine_methods = {}
            for group in f.get("layers", {}).values():
                kind, shape = str(group.attrs["detector"]), tuple(group.attrs["shape"])
                items = []
                for name in sorted(group, key=int):
                    ds = group[name]
                    if ds.shape != shape: raise ValueError("Saved layer shape mismatch")
                    items.append(SimpleNamespace(data=ds[...].astype(bool), name=str(ds.attrs["name"]),
                        visible=bool(ds.attrs["visible"]), source=str(ds.attrs.get("source", "custom"))))
                layers[(kind, shape)] = items
                combine_methods[(kind, shape)] = str(group.attrs.get("combine", "OR"))
            shadow, aperture = bool(f.attrs["shadow"]), bool(f.attrs["aperture"])
        self.corrections, self.user_masks, self.base_specs = corrections, masks, specs
        self.layers = layers; self.shadow, self.aperture = shadow, aperture
        self.combine_methods = combine_methods
        self.changed.emit(); self.refresh()

    def clear_context(self):
        self.io.invalidate(); self.ref = self.payload = self._source = None
        self.frame_ready.emit(None)

    def close(self): self.io.close()
