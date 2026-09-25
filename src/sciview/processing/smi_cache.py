"""Read existing smi-browser products without importing Panel or modifying cache files."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np

from sciview.sources.frame_source import normalize_scalars


def cache_directory():
    return Path(os.environ.get("SMI_BROWSER_CACHE_DIR", str(Path(tempfile.gettempdir()) / "smi_browser_cache")))


@dataclass
class CachedProfiles:
    uid: str
    path: Path
    revision: str
    q: np.ndarray
    intensity: np.ndarray
    axes: dict
    peaks: list
    fits: dict
    metadata: dict


def read_profiles(path):
    import h5py
    from smi_tiled.derived.virtual_axes import derive_virtual_columns
    from smi_tiled.derived.peakfit import PeakDef
    path = Path(path)
    with h5py.File(path, "r") as f:
        reduction = f.get("reduction")
        if reduction is None or "pf_iq_I" not in reduction or "pf_iq_q" not in reduction:
            raise ValueError("No cached transmission per-frame I(q). Reduce this scan with smi-tiled first.")
        iq, q = reduction["pf_iq_I"][...], reduction["pf_iq_q"][...]
        if iq.ndim != 2 or q.ndim != 1 or iq.shape[1] != len(q) or not iq.shape[0]:
            raise ValueError("Invalid cached per-frame I(q) dimensions")
        metadata = dict(reduction.attrs)
        uid = str(f.attrs.get("uid", path.stem))
        if f.attrs.get("schema") == "sciview.smi.reduction.v1" and not f.attrs.get("complete"):
            raise ValueError("Reduction artifact is incomplete")
        raw = {k: v[...] for k, v in f.get("primary", {}).items() if isinstance(v, h5py.Dataset)}
        scalars = normalize_scalars(raw, derive_virtual_columns)
        axes = {k: v for k, v in scalars.items() if len(v) == len(iq) and np.issubdtype(v.dtype, np.number)}
        axes["frame"] = np.arange(len(iq), dtype=float)
        peaks, fits = [], {}
        for group in f.get("peakfit", {}).values():
            try:
                key = tuple(json.loads(group.attrs["key_json"]))
                pk = PeakDef(name=str(group.attrs.get("name", f"p{len(peaks)+1}")),
                             q_min=float(key[0]), q_max=float(key[1]),
                             model=key[2], baseline=key[3], link=key[4], bg_factor=float(key[5]))
                result = {k: v[...] for k, v in group.items()}
                if any(np.asarray(v).shape != (len(iq),) for k, v in result.items()
                       if k in ("area", "center", "amplitude", "fwhm", "success")):
                    continue
                peaks.append(pk); fits[pk.key()] = result
            except (KeyError, TypeError, ValueError, IndexError):
                continue
    # Fingerprint actual analysis inputs, including legacy files without revision.
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(q).tobytes())
    digest.update(np.ascontiguousarray(iq).tobytes())
    revision = str(metadata.get("_revision", "legacy")) + ":" + digest.hexdigest()
    if not peaks:
        definitions = path.parent / "peak_defs.json"
        if definitions.exists():
            try:
                for d in json.loads(definitions.read_text()):
                    peaks.append(PeakDef(name=d["name"], q_min=float(d["q_min"]), q_max=float(d["q_max"]),
                        model=d.get("model", "gaussian"), baseline=d.get("baseline", "linear"),
                        link=d.get("link", "linked"), bg_factor=float(d.get("bg", 2.0))))
            except (ValueError, TypeError, KeyError):
                peaks = []
    return CachedProfiles(uid, path, revision, q, iq, axes, peaks, fits, metadata)


def fit_profiles(profiles, peaks, cancel, progress=None):
    from smi_tiled.derived.peakfit import fit_peak_across_frames
    results = dict(profiles.fits)
    for i, peak in enumerate(peaks):
        if cancel.is_set():
            break
        if peak.key() not in results:
            result = fit_peak_across_frames(profiles.q, profiles.intensity, peak, cancel=cancel,
                progress=(lambda done, total: progress(i, done, total)) if progress else None)
            if cancel.is_set():
                break
            results[peak.key()] = result
    return results


def normalized_channel(values, log=False):
    values = np.asarray(values, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        a = np.where(values > 0, np.log10(values), np.nan) if log else values
    finite = a[np.isfinite(a)]
    if not finite.size:
        return np.zeros(a.shape)
    low, high = np.percentile(finite, [2, 99])
    return np.where(np.isfinite(a), np.clip((a - low) / max(high-low, 1e-30), 0, 1), 0)


def compose_channels(channels):
    """Add normalized scalar channels in acquisition order; no implicit gridding."""
    if not channels:
        return np.empty((0, 3))
    rgb = np.zeros((len(channels[0][0]), 3))
    for values, color, gain, logarithmic in channels:
        rgb += normalized_channel(values, logarithmic)[:, None] * np.asarray(color)[None, :] * gain
    return np.clip(rgb, 0, 1)


def save_analysis(profiles, peaks, path):
    """Separate self-describing artifact; never write into the shared raw cache."""
    import h5py
    path = Path(path)
    if path.resolve() == profiles.path.resolve():
        raise ValueError("Analysis export must not overwrite the source reduction cache")
    temporary = path.with_name(path.name + ".partial")
    try:
        with h5py.File(temporary, "w") as f:
            f.attrs.update(schema="sciview.smi.peak-analysis.v1", uid=profiles.uid,
                           stream="primary", reduction_revision=profiles.revision,
                           q_units="nm^-1", source_cache=str(profiles.path))
            f.attrs["peaks_json"] = json.dumps([p.to_provenance() for p in peaks])
            for name, values in profiles.axes.items():
                ds = f.require_group("axes").create_dataset(name.replace("/", "%2F"), data=values)
                ds.attrs["name"] = name
            for i, peak in enumerate(peaks):
                result = profiles.fits.get(peak.key())
                if result is None:
                    continue
                group = f.require_group(f"peakfit/{i}")
                group.attrs["definition"] = json.dumps(peak.to_provenance())
                for name in ("amplitude", "center", "fwhm", "area", "success"):
                    if name in result:
                        group.create_dataset(name, data=result[name])
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
