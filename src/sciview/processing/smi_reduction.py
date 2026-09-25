"""SMI whole-run request/result adapter, independent of Qt and SciAnalysis."""
from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib
import json
import os

import numpy as np

from sciview.processing.smi_cache import cache_directory

SCHEMA = "sciview.smi.reduction.v1"


@dataclass(frozen=True)
class SmiReductionRequest:
    uid: str
    stream: str = "primary"
    geometry: str = "transmission"
    tiled_uri: str = "https://tiled.nsls2.bnl.gov"
    catalog: str = "smi/migration"
    n_q: int = 2000
    n_chi: int = 360
    n_qxy: int = 500
    n_qz: int = 500
    pixel_splitting: int = 1
    solid_angle: bool = True
    dezinger: float = 3000.0
    dezinger_kernel: int = 5
    saxs_mask: str = ""
    waxs_mask: str = ""
    incident_angle: float | None = None
    saxs_beam_delta: tuple | None = None
    waxs_beam_delta: tuple | None = None
    saxs_distance_delta: float | None = None
    frame_maps: bool = True
    waxs_distance: float | None = None
    shadow: bool = True
    aperture: bool = True
    user_mask_files: dict | None = None
    base_mask_specs: dict | None = None

    def validate(self):
        if not self.uid or Path(self.uid).name != self.uid:
            raise ValueError("A valid run UID is required")
        if self.stream != "primary":
            raise ValueError("smi-tiled currently reduces primary only; select the primary stream")
        if self.geometry not in ("transmission", "grazing"):
            raise ValueError("Unknown geometry")
        if any(not 16 <= v <= 10000 for v in (self.n_q, self.n_chi, self.n_qxy, self.n_qz)):
            raise ValueError("Grid sizes must be between 16 and 10000")
        if not 1 <= self.pixel_splitting <= 8:
            raise ValueError("Pixel splitting must be between 1 and 8")
        if self.dezinger_kernel < 3 or self.dezinger_kernel % 2 != 1:
            raise ValueError("Dezinger kernel must be odd and at least 3")
        if not np.isfinite(self.dezinger) or self.dezinger < 0:
            raise ValueError("Dezinger threshold must be finite and non-negative")
        for delta in (self.saxs_beam_delta, self.waxs_beam_delta):
            if delta is not None and (len(delta) != 2 or not np.isfinite(delta).all()):
                raise ValueError("Beam deltas must contain two finite values")
        for value in (self.incident_angle, self.saxs_distance_delta, self.waxs_distance):
            if value is not None and not np.isfinite(value):
                raise ValueError("Geometry overrides must be finite")
        if self.waxs_distance is not None and self.waxs_distance <= 0:
            raise ValueError("WAXS distance must be positive")
        for path in (self.saxs_mask, self.waxs_mask):
            if path and not Path(path).is_file():
                raise ValueError(f"Mask file not found: {path}")

    def backend_call(self, workdir):
        """Explicit values; None overrides leave metadata/calibrated defaults intact."""
        self.validate()
        common = dict(uid=self.uid, tiled_uri=self.tiled_uri, catalog=self.catalog,
                      pixel_splitting=self.pixel_splitting,
                      dezinger_threshold=self.dezinger if self.dezinger > 0 else None,
                      dezinger_kernel=self.dezinger_kernel, populate_disk_cache=False,
                      # Published backend does not yet reject partially filled
                      # browser image caches. Read raw data from Tiled instead.
                      image_cache_path=None)
        from sciview.processing.smi_geometry import load_mask_spec, compose_mask_spec
        for kind, path in (("saxs", self.saxs_mask), ("waxs", self.waxs_mask)):
            if kind == "saxs" and self.geometry == "grazing": continue
            spec = (load_mask_spec(kind, path) if path else (self.base_mask_specs or {}).get(kind))
            user_file = (self.user_mask_files or {}).get(kind)
            if user_file:
                excluded = np.load(user_file, allow_pickle=False)
                spec = compose_mask_spec(spec if spec is not None else load_mask_spec(kind), excluded, kind)
            if spec is not None: common[kind + "_mask"] = spec
        if self.geometry == "grazing":
            common.update(n_qxy=self.n_qxy, n_qz=self.n_qz, incident_angle_deg=self.incident_angle)
            if self.waxs_distance is not None or self.waxs_beam_delta is not None:
                raise ValueError("Fitted transmission geometry corrections cannot yet be applied to GI; reset them or use transmission")
            return "reduce_smi_gi", common
        common.update(n_q=self.n_q, n_chi=self.n_chi, geometry="transmission",
                      solid_angle_correction=self.solid_angle, build_detector_ds=False,
                      build_frame_qchi=self.frame_maps, frame_qchi_store=str(Path(workdir) / "frames"))
        common["saxs_kwargs"] = {"dynamic_saxs_kwargs": {
            "waxs_shadow": {"enabled": self.shadow}, "aperture": {"enabled": self.aperture}}}
        if self.waxs_distance is not None:
            if self.waxs_distance <= 0: raise ValueError("WAXS distance must be positive")
            common["waxs_kwargs"] = {"sample_distance_mm": self.waxs_distance}
        if self.saxs_beam_delta is not None:
            common["saxs_beam_delta_px"] = tuple(self.saxs_beam_delta)
        if self.waxs_beam_delta is not None:
            common["waxs_beam_delta_px"] = tuple(self.waxs_beam_delta)
        if self.saxs_distance_delta is not None:
            common["saxs_distance_delta_mm"] = self.saxs_distance_delta
        return "reduce_smi_combined", common


def results_directory():
    return Path(os.environ.get("SCIVIEW_SMI_RESULTS_DIR", str(cache_directory() / "sciview_results")))


def json_value(value):
    if isinstance(value, np.generic): return value.item()
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, Path): return str(value)
    raise TypeError(type(value).__name__)


def _array(group, name, values, **kwargs):
    return group.create_dataset(name, data=np.asarray(values), compression="gzip", compression_opts=2, **kwargs)


def _map(group, data, x, y, x_label, y_label, cancel):
    """Persist named-dimension map as (frame?, y, x), one frame at a time."""
    _array(group, "x", x)
    _array(group, "y", y)
    group.attrs.update(x_label=x_label, y_label=y_label)
    shape = tuple(data.shape)
    if len(shape) == 2:
        _array(group, "image", data)
    else:
        ds = group.create_dataset("image", shape=shape, dtype="float64",
                                  chunks=(1, shape[1], shape[2]), compression="gzip", compression_opts=2)
        for i in range(shape[0]):
            if cancel(): raise InterruptedError("Reduction cancelled during result storage")
            ds[i] = np.asarray(data[i])


def save_reduction(result, request, path, *, backend_kwargs=None, cancel=lambda: False):
    """Atomically publish a standalone result. Never overwrite shared raw caches."""
    import h5py
    import smi_tiled
    path = Path(path)
    temporary = path.with_suffix(".partial.h5")
    recipe = asdict(request)
    import uuid
    provenance = dict(recipe=recipe, backend=getattr(smi_tiled, "__version__", "unknown"),
                      resolved=getattr(result, "reduction_parameters", None),
                      backend_kwargs=backend_kwargs or {}, timing=getattr(result, "timing", None))
    # New execution identity, even with identical options (a live source may
    # have grown). Keep a separate reproducible recipe fingerprint.
    scientific_kwargs = {k: v for k, v in (backend_kwargs or {}).items()
                         if k not in ("frame_qchi_store", "image_cache_path", "populate_disk_cache")}
    fingerprint = hashlib.sha256(json.dumps(dict(recipe=recipe, backend=provenance["backend"],
        resolved=provenance["resolved"], backend_kwargs=scientific_kwargs), sort_keys=True, default=json_value).encode()).hexdigest()
    provenance["recipe_fingerprint"] = fingerprint
    revision = uuid.uuid4().hex
    try:
        with h5py.File(temporary, "w") as f:
            f.attrs.update(schema=SCHEMA, uid=request.uid, stream=request.stream,
                           geometry=request.geometry, complete=False,
                           provenance=json.dumps(provenance, default=json_value))
            red = f.create_group("reduction")
            red.attrs.update(_revision=revision, uid=request.uid, q_units="nm^-1")
            maps = f.create_group("maps")
            if request.geometry == "transmission":
                iq = result.merged_iq
                if iq is not None:
                    _array(red, "iq_q", iq["q"].values)
                    for variable in ("I", "saxs_I", "waxs_I", "counts"):
                        if variable in iq: _array(red, "iq_" + variable, iq[variable].transpose("q").values)
                pf = result.per_frame_iq
                if pf is not None and "I" in pf:
                    _array(red, "pf_iq_q", pf["q"].values)
                    _array(red, "pf_iq_I", pf["I"].transpose("frame", "q").values)
                    primary = f.create_group("primary")
                    for name, array in pf.variables.items():
                        if array.dims == ("frame",):
                            values = np.asarray(array.values)
                            if np.issubdtype(values.dtype, np.number):
                                _array(primary, name, values)
                            elif values.dtype.kind in "OSU":
                                strings = np.array([v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)
                                                    for v in values], dtype=object)
                                primary.create_dataset(name, data=strings, dtype=h5py.string_dtype())
                qchi = result.merged_qchi
                if qchi is not None:
                    _map(maps.create_group("merged_qchi"), qchi["intensity"].transpose("chi", "q").data,
                         qchi["q"].values, qchi["chi"].values, "q (nm⁻¹)", "χ (°)", cancel)
                if request.frame_maps:
                    for name in ("saxs", "waxs"):
                        detector = getattr(result, name, None)
                        frames = detector.get("q_chi_frames") if detector else None
                        if frames is not None:
                            _map(maps.create_group(name + "_frames"), frames["intensity"].transpose("frame", "chi", "q").data,
                                 frames["q"].values, frames["chi"].values, "q (nm⁻¹)", "χ (°)", cancel)
            else:
                primary = f.create_group("primary")
                for name, values in (("incident_angle_deg", getattr(result, "alpha_i_deg", None)),
                                     (getattr(result, "scan_motor", "motor"), getattr(result, "scan_motor_values", None))):
                    if values is not None and name not in primary:
                        _array(primary, name, values)
                _map(maps.create_group("gi_merged"), np.asarray(result.summed).T,
                     result.qxy_grid, result.qz_grid, "qxy (nm⁻¹)", "qz (nm⁻¹)", cancel)
                if request.frame_maps and result.q_chi_frames is not None:
                    ds = result.q_chi_frames
                    _map(maps.create_group("gi_frames"), ds["intensity"].transpose("frame", "qz", "qxy").data,
                         result.qxy_grid, result.qz_grid, "qxy (nm⁻¹)", "qz (nm⁻¹)", cancel)
            if cancel(): raise InterruptedError("Reduction cancelled")
            f.attrs["complete"] = True
        temporary.replace(path)
    finally:
        if temporary.exists(): temporary.unlink()
    return path


def describe_result(path):
    import h5py
    with h5py.File(path, "r") as f:
        if f.attrs.get("schema") != SCHEMA or not f.attrs.get("complete"):
            raise ValueError("Not a complete SciView SMI reduction")
        red = f["reduction"]
        labels = {}
        for name, ds in f.get("primary", {}).items():
            if isinstance(ds, h5py.Dataset) and ds.ndim == 1:
                values = ds.asstr()[...] if h5py.check_string_dtype(ds.dtype) else ds[...]
                labels[name] = values
        return dict(path=str(path), uid=str(f.attrs["uid"]), geometry=str(f.attrs["geometry"]),
                    frame_labels=labels,
                    provenance=json.loads(f.attrs["provenance"]),
                    has_iq="iq_I" in red, has_profiles="pf_iq_I" in red,
                    frames=int(red["pf_iq_I"].shape[0]) if "pf_iq_I" in red else 0,
                    maps={k: (int(g["image"].shape[0]) if g["image"].ndim == 3 else 0) for k, g in f["maps"].items()})


def read_curves(path, frame=None):
    import h5py
    with h5py.File(path, "r") as f:
        red = f["reduction"]
        if frame is not None:
            if "pf_iq_I" not in red: return None, {}
            return red["pf_iq_q"][...], {f"Frame {frame}": red["pf_iq_I"][frame]}
        if "iq_I" not in red: return None, {}
        return red["iq_q"][...], {label: red[key][...] for key, label in (
            ("iq_I", "Merged"), ("iq_saxs_I", "SAXS"), ("iq_waxs_I", "WAXS")) if key in red}


def read_map(path, name, frame=0):
    import h5py
    with h5py.File(path, "r") as f:
        g = f["maps"][name]
        ds = g["image"]
        return g["x"][...], g["y"][...], ds[frame] if ds.ndim == 3 else ds[...], str(g.attrs["x_label"]), str(g.attrs["y_label"])


def read_waterfall(path, max_traces=200, max_q=2000):
    """Bound overview payload, retaining acquisition indices for labels/picking."""
    import h5py
    with h5py.File(path, "r") as f:
        red = f["reduction"]
        if "pf_iq_I" not in red:
            return None
        ds = red["pf_iq_I"]
        step = max(1, int(np.ceil(ds.shape[0] / max_traces)))
        qstep = max(1, int(np.ceil(ds.shape[1] / max_q)))
        return red["pf_iq_q"][::qstep], ds[::step, ::qstep], np.arange(0, ds.shape[0], step), ds.shape[0]


def run_job(request_file):
    """Spawned-process entry point. Only complete files are offered to the GUI."""
    import time
    import traceback
    request_file = Path(request_file)
    payload = json.loads(request_file.read_text())
    request = SmiReductionRequest(**payload)
    directory = request_file.parent
    cancel = lambda: (directory / "cancel").exists()
    last = [0.0]
    def emit(event):
        print("SCIVIEW_JOB " + json.dumps(event), flush=True)
    def progress(stage, current, total):
        if cancel(): raise InterruptedError("Reduction cancelled")
        now = time.monotonic()
        if now - last[0] >= .15:
            last[0] = now
            emit(dict(type="progress", stage=stage, current=int(current), total=int(total)))
    try:
        import smi_tiled
        if request.user_mask_files:
            from tiled.client import from_uri
            from sciview.sources.frame_source import TiledFrameSource
            catalog = from_uri(request.tiled_uri, prompt_for_reauthentication=False)
            for part in request.catalog.split("/"): catalog = catalog[part]
            sequence = TiledFrameSource(catalog, "smi_migration").describe(request.uid, "primary")
            for kind, path in request.user_mask_files.items():
                field = "pil2M_image" if kind == "saxs" else "pil900KW_image"
                if field not in sequence.fields: continue
                if tuple(np.load(path, mmap_mode="r").shape) != sequence.fields[field][-2:]:
                    raise ValueError(f"User {kind} mask shape does not match this run")
        name, kwargs = request.backend_call(directory)
        progress("Loading raw data", 0, 0)
        result = getattr(smi_tiled, name)(**kwargs, progress=progress)
        progress("Saving products", 0, 0)
        path = save_reduction(result, request, directory / "result.h5", backend_kwargs=kwargs, cancel=cancel)
        emit(dict(type="result", path=str(path)))
    except InterruptedError as exc:
        emit(dict(type="cancelled", message=str(exc)))
    except Exception as exc:
        traceback.print_exc()
        emit(dict(type="error", message=f"{type(exc).__name__}: {exc}"))


if __name__ == "__main__":
    import sys
    run_job(sys.argv[1])
