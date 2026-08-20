"""Batch processing backend: job definitions, per-file dispatch, and QThread runner."""

from __future__ import annotations

import fnmatch
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from sciview.processing.reduction import ReductionBackend, ReductionRequest, save_reduction_result
from sciview.processing.transform import TransformBackend, TransformRequest, save_transform_result
from sciview.interfaces.stable_qt.utils.image_utils import validate_and_prepare_image_array


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

ProtocolKind = Literal["reduction", "transform"]

REDUCTION_OPERATIONS = ("circular_average", "sector_average", "line_profile")
TRANSFORM_OPERATIONS = ("q_image", "q_phi_image", "qr_qz_image")

_OPERATION_KIND: dict[str, ProtocolKind] = {
    **{op: "reduction" for op in REDUCTION_OPERATIONS},
    **{op: "transform" for op in TRANSFORM_OPERATIONS},
}

OUTPUT_FORMATS = ("png", "npz", "csv", "txt")


def operation_kind(operation: str) -> ProtocolKind:
    return _OPERATION_KIND.get(operation, "reduction")


@dataclass
class BatchProtocol:
    """One processing step within a batch job."""

    name: str
    operation: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    source: str = "manual"  # "reduction_tab" | "transform_tab" | "manual"

    def kind(self) -> ProtocolKind:
        return operation_kind(self.operation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "operation": self.operation,
            "params": dict(self.params),
            "enabled": self.enabled,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BatchProtocol":
        return cls(
            name=str(payload.get("name", payload.get("operation", ""))),
            operation=str(payload.get("operation", "")),
            params=dict(payload.get("params", {})),
            enabled=bool(payload.get("enabled", True)),
            source=str(payload.get("source", "manual")),
        )


@dataclass
class BatchFileResult:
    """Outcome for one (file, protocol) pair."""

    file_path: str
    protocol_name: str
    status: Literal["ok", "error", "skipped"]
    output_path: str = ""
    message: str = ""
    elapsed_s: float = 0.0


@dataclass
class BatchJob:
    """Complete specification for a batch run."""

    file_paths: list[str]
    protocols: list[BatchProtocol]
    output_dir: str
    output_formats: list[str] = field(default_factory=lambda: ["png", "npz"])
    calibration: Any | None = None
    mask: Any | None = None
    mirror_input_structure: bool = True
    input_root: str = ""  # used when mirror_input_structure=True


# ---------------------------------------------------------------------------
# Output path helpers
# ---------------------------------------------------------------------------

def resolve_output_dir(
    file_path: str,
    output_dir: str,
    input_root: str = "",
    mirror: bool = True,
) -> Path:
    """Return the output directory for a given input file path."""
    if not mirror or not input_root:
        return Path(output_dir)

    try:
        rel = Path(file_path).parent.relative_to(input_root)
        return Path(output_dir) / rel
    except ValueError:
        return Path(output_dir)


def output_stem(file_path: str, operation: str) -> str:
    return f"{Path(file_path).stem}_{operation}"


# ---------------------------------------------------------------------------
# Image loading (file → numpy array)
# ---------------------------------------------------------------------------

def _load_image_array(file_path: str) -> np.ndarray:
    """Load a raw image file into a 2D float numpy array."""
    from importlib import import_module

    # Try SciAnalysis first for full detector support.
    try:
        data_module = import_module("SciAnalysis.XSAnalysis.Data")
        obj = data_module.Data2DScattering(file_path)
        arr = np.asarray(obj.data if hasattr(obj, "data") else obj, dtype=float)
        if arr.ndim == 2:
            return arr
    except Exception:
        pass

    # Fallback: PIL / tifffile.
    try:
        import tifffile
        arr = tifffile.imread(file_path).astype(float)
        if arr.ndim == 2:
            return arr
        if arr.ndim == 3:
            return arr[0]
    except Exception:
        pass

    try:
        from PIL import Image
        arr = np.asarray(Image.open(file_path), dtype=float)
        if arr.ndim == 2:
            return arr
        return arr[:, :, 0]
    except Exception:
        pass

    raise OSError(f"Could not load image: {file_path}")


# ---------------------------------------------------------------------------
# Per-file dispatchers
# ---------------------------------------------------------------------------

_reduction_backend = ReductionBackend()
_transform_backend = TransformBackend()


def _dispatch_reduction(
    image: np.ndarray,
    file_path: str,
    protocol: BatchProtocol,
    calibration: Any | None,
    mask: np.ndarray | None,
    out_dir: Path,
    formats: list[str],
) -> str:
    """Run one reduction protocol and write outputs. Returns first written path."""
    p = protocol.params
    cx = float(p.get("center_x", image.shape[1] / 2.0))
    cy = float(p.get("center_y", image.shape[0] / 2.0))

    # Resolve center from calibration when available.
    if calibration is not None:
        x0 = getattr(calibration, "x0", None)
        y0 = getattr(calibration, "y0", None)
        if x0 is not None and y0 is not None:
            cx, cy = float(x0), float(y0)

    request = ReductionRequest(
        image=image,
        operation=protocol.operation,
        center_x=cx,
        center_y=cy,
        bins=int(p.get("bins", 256)),
        q_min=float(p.get("q_min", 0.0)) if p.get("q_min") is not None else None,
        q_max=float(p.get("q_max", 2.0)) if p.get("q_max") is not None else None,
        radius_max=float(p.get("radius_max")) if p.get("radius_max") is not None else None,
        angle_start_deg=float(p.get("angle_start_deg", 0.0)),
        angle_end_deg=float(p.get("angle_end_deg", 360.0)),
        line_chi0_deg=float(p.get("line_chi0_deg", 0.0)),
        line_dq=float(p.get("line_dq", 0.01)),
        line_mode=p.get("line_mode", "q"),
        line_value=float(p.get("line_value", 0.0)) if p.get("line_value") is not None else None,
        use_mask=mask is not None,
        calibration=calibration,
        mask=mask,
    )
    result = _reduction_backend.run(request)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / output_stem(file_path, protocol.operation)

    written: list[str] = []
    for fmt in formats:
        if fmt in ("csv", "txt", "dat"):
            out_path = str(stem) + f".{fmt}"
            written.append(save_reduction_result(result, out_path))
        # PNG for 1D curves is not standard; skip silently.

    if not written:
        # Always write CSV as fallback when no matching format is selected.
        out_path = str(stem) + ".csv"
        written.append(save_reduction_result(result, out_path))

    return written[0]


def _dispatch_transform(
    image: np.ndarray,
    file_path: str,
    protocol: BatchProtocol,
    calibration: Any | None,
    mask: np.ndarray | None,
    out_dir: Path,
    formats: list[str],
) -> str:
    """Run one transform protocol and write outputs. Returns first written path."""
    if calibration is None:
        raise ValueError("Calibration is required for transform operations")

    p = protocol.params
    request = TransformRequest(
        image=image,
        operation=protocol.operation,
        calibration=calibration,
        mask=mask,
        use_mask=mask is not None,
        bins_q=int(p.get("bins_q", 320)),
        bins_phi=int(p.get("bins_phi", 360)),
        q_min=float(p.get("q_min", 0.0)) if p.get("q_min") is not None else None,
        q_max=float(p.get("q_max", 2.0)) if p.get("q_max") is not None else None,
        phi_min_deg=float(p.get("phi_min_deg", -180.0)) if p.get("phi_min_deg") is not None else None,
        phi_max_deg=float(p.get("phi_max_deg", 180.0)) if p.get("phi_max_deg") is not None else None,
    )
    result = _transform_backend.run(request)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / output_stem(file_path, protocol.operation)

    written: list[str] = []
    for fmt in formats:
        if fmt in ("npz", "npy"):
            out_path = str(stem) + f".{fmt}"
            written.append(save_transform_result(result, out_path))
        elif fmt == "png":
            out_path = str(stem) + ".png"
            _save_transform_png(result, out_path)
            written.append(out_path)

    if not written:
        out_path = str(stem) + ".npz"
        written.append(save_transform_result(result, out_path))

    return written[0]


def _save_transform_png(result: Any, path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    image = result.image
    finite = image[np.isfinite(image) & (image > 0)]
    vmin = float(np.percentile(finite, 2)) if finite.size else 1.0
    vmax = float(np.percentile(finite, 99)) if finite.size else vmin * 1e3
    norm = LogNorm(vmin=max(vmin, 1e-12), vmax=max(vmax, vmin * 10))

    extent = None
    if result.x_axis is not None and result.y_axis is not None:
        extent = [
            float(result.x_axis[0]), float(result.x_axis[-1]),
            float(result.y_axis[0]), float(result.y_axis[-1]),
        ]

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.imshow(image, origin="lower", cmap="viridis", norm=norm, aspect="auto", extent=extent)
    ax.set_xlabel(result.x_label)
    ax.set_ylabel(result.y_label)
    ax.set_title(result.operation.replace("_", " ").title())
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _get_mask_array(mask: Any | None, shape: tuple[int, int]) -> np.ndarray | None:
    """Coerce mask to bool ndarray, handling SciAnalysis mask objects."""
    if mask is None:
        return None
    if hasattr(mask, "data") and not isinstance(mask, np.ndarray):
        raw = np.asarray(mask.data)
        return (raw <= 0).astype(bool)
    arr = np.asarray(mask)
    result = arr.astype(bool) if arr.dtype == bool else (arr > 0).astype(bool)
    if result.shape != shape:
        return None
    return result


# ---------------------------------------------------------------------------
# File list scanning
# ---------------------------------------------------------------------------

SUPPORTED_IMAGE_EXTS = {".tif", ".tiff", ".h5", ".dat", ".cbf", ".edf"}


def scan_folder(folder: str, pattern: str = "*", recursive: bool = False) -> list[str]:
    """Return sorted list of image files matching *pattern* under *folder*."""
    root = Path(folder)
    if not root.is_dir():
        return []

    glob_fn = root.rglob if recursive else root.glob
    paths: list[str] = []
    for entry in glob_fn("*"):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in SUPPORTED_IMAGE_EXTS:
            continue
        if pattern and pattern not in ("*", "*.*"):
            if not fnmatch.fnmatch(entry.name, pattern):
                continue
        paths.append(str(entry))

    paths.sort()
    return paths


def new_files_in_folder(
    folder: str,
    pattern: str,
    recursive: bool,
    seen: set[str],
    folder_mtime_cache: dict[str, int],
) -> list[str]:
    """Return new files not yet in *seen*, updating *folder_mtime_cache* in-place."""
    root = Path(folder)
    dirs = list(root.rglob("*")) if recursive else [root]
    dirs = [d for d in dirs if (d if isinstance(d, Path) else Path(d)).is_dir()]
    dirs.insert(0, root)

    new: list[str] = []
    for d in dirs:
        d_str = str(d)
        try:
            mtime = os.stat(d_str).st_mtime_ns
        except OSError:
            continue
        prev = folder_mtime_cache.get(d_str)
        folder_mtime_cache[d_str] = mtime
        if prev is not None and mtime <= prev:
            continue
        for entry in os.scandir(d_str):
            if not entry.is_file():
                continue
            if Path(entry.name).suffix.lower() not in SUPPORTED_IMAGE_EXTS:
                continue
            if pattern and pattern not in ("*", "*.*"):
                if not fnmatch.fnmatch(entry.name, pattern):
                    continue
            if entry.path not in seen:
                seen.add(entry.path)
                new.append(entry.path)

    new.sort()
    return new


# ---------------------------------------------------------------------------
# QThread runner
# ---------------------------------------------------------------------------

class BatchRunner(QThread):
    """Run a BatchJob on a worker thread, emitting per-file progress signals."""

    progress = pyqtSignal(int, int, str)          # done, total, current_label
    file_done = pyqtSignal(BatchFileResult)        # one result per (file, protocol)
    status_changed = pyqtSignal(str)               # human-readable status line
    finished_batch = pyqtSignal(int, int)          # ok_count, error_count

    def __init__(self, job: BatchJob, parent=None):
        super().__init__(parent)
        self._job = job
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        job = self._job
        protocols = [p for p in job.protocols if p.enabled]
        files = job.file_paths
        total = len(files) * max(len(protocols), 1)
        done = ok = err = 0

        mask_array: np.ndarray | None = None

        self.status_changed.emit(f"Starting: {len(files)} files × {len(protocols)} protocols")

        for file_path in files:
            if self._stop_requested:
                self.status_changed.emit("Stopped by user")
                break

            # Load image once per file.
            try:
                image = _load_image_array(file_path)
                mask_array = _get_mask_array(job.mask, image.shape)
            except Exception as exc:
                for proto in protocols:
                    done += 1
                    result = BatchFileResult(
                        file_path=file_path,
                        protocol_name=proto.name,
                        status="error",
                        message=f"Load failed: {exc}",
                    )
                    self.file_done.emit(result)
                    err += 1
                self.progress.emit(done, total, os.path.basename(file_path))
                continue

            out_root = resolve_output_dir(
                file_path,
                job.output_dir,
                job.input_root,
                job.mirror_input_structure,
            )

            for proto in protocols:
                if self._stop_requested:
                    break

                label = f"{os.path.basename(file_path)} → {proto.name}"
                self.progress.emit(done, total, label)
                t0 = time.monotonic()

                try:
                    if proto.kind() == "reduction":
                        out_path = _dispatch_reduction(
                            image, file_path, proto, job.calibration, mask_array, out_root, job.output_formats
                        )
                    else:
                        out_path = _dispatch_transform(
                            image, file_path, proto, job.calibration, mask_array, out_root, job.output_formats
                        )
                    result = BatchFileResult(
                        file_path=file_path,
                        protocol_name=proto.name,
                        status="ok",
                        output_path=out_path,
                        elapsed_s=time.monotonic() - t0,
                    )
                    ok += 1
                except Exception as exc:
                    result = BatchFileResult(
                        file_path=file_path,
                        protocol_name=proto.name,
                        status="error",
                        message=str(exc),
                        elapsed_s=time.monotonic() - t0,
                    )
                    err += 1

                done += 1
                self.file_done.emit(result)
                self.progress.emit(done, total, label)

        self.status_changed.emit(f"Done — {ok} succeeded, {err} failed")
        self.finished_batch.emit(ok, err)
