"""Batch processing backend: job definitions, per-file dispatch, and QThread runner."""

from __future__ import annotations

import fnmatch
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np
try:
    from PyQt5.QtCore import QThread, pyqtSignal
except Exception:  # pragma: no cover - fallback for headless/backend-only environments
    class _NoQtSignal:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def emit(self, *args, **kwargs):
            del args, kwargs

    def pyqtSignal(*args, **kwargs):
        del args, kwargs
        return _NoQtSignal()

    class QThread:  # minimal compatibility shim
        def __init__(self, parent=None):
            del parent

        def start(self) -> None:
            self.run()

        def isRunning(self) -> bool:
            return False

        def run(self) -> None:
            return None


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

ProtocolKind = Literal["reduction", "transform"]

REDUCTION_OPERATIONS = ("circular_average", "sector_average", "line_profile")
TRANSFORM_OPERATIONS = ("q_image", "q_phi_image", "qr_qz_image", "thumbnails")

_OPERATION_KIND: dict[str, ProtocolKind] = {
    **{op: "reduction" for op in REDUCTION_OPERATIONS},
    **{op: "transform" for op in TRANSFORM_OPERATIONS},
}

OUTPUT_FORMATS = ("png", "npz", "csv", "txt")  # kept for external callers; not used by run_batch


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
    dirs = list(root.rglob("*")) if recursive else []
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
# Calibration-derived q bounds (mirrors reduction_tab auto-q-range logic)
# ---------------------------------------------------------------------------

def compute_q_bounds(
    calibration: Any,
    mask_array: "np.ndarray | None" = None,
) -> dict[str, float]:
    """Compute q/qx/qz/qr bounds from a calibration object.

    mask_array: optional bool array where True = masked pixel (excluded from bounds).
    Returns an empty dict when calibration is None or no valid pixels remain.
    """
    if calibration is None:
        return {}
    q_map  = np.asarray(calibration.q_map(),  dtype=float)
    qx_map = np.asarray(calibration.qx_map(), dtype=float)
    qz_map = np.asarray(calibration.qz_map(), dtype=float)
    qr_map = np.asarray(calibration.qr_map(), dtype=float)
    valid  = (
        np.isfinite(q_map)  &
        np.isfinite(qx_map) &
        np.isfinite(qz_map) &
        np.isfinite(qr_map)
    )
    if mask_array is not None and mask_array.shape == q_map.shape:
        valid &= ~mask_array  # True=masked → exclude
    if not np.any(valid):
        return {}
    return {
        "q_min":  float(np.min(q_map[valid])),
        "q_max":  float(np.max(q_map[valid])),
        "qx_min": float(np.min(qx_map[valid])),
        "qx_max": float(np.max(qx_map[valid])),
        "qz_min": float(np.min(qz_map[valid])),
        "qz_max": float(np.max(qz_map[valid])),
        "qr_min": float(np.min(qr_map[valid])),
        "qr_max": float(np.max(qr_map[valid])),
    }


def apply_q_bounds_to_protocol(proto: "BatchProtocol", bounds: dict[str, float]) -> "BatchProtocol":
    """Inject calibration-derived plot_range into a protocol's params.

    Protocols carry their recipe settings (bins_relative, ylog, …) but not
    the data-range; this function fills that in at run time from the calibration.
    phi_min / phi_max keys in params are consumed to build the angular part of
    q_phi_image's plot_range and then removed (SA does not accept them).
    """
    if not bounds:
        return proto

    q_min  = bounds["q_min"]
    q_max  = bounds["q_max"]
    qx_min = bounds["qx_min"]
    qx_max = bounds["qx_max"]
    qz_min = bounds["qz_min"]
    qz_max = bounds["qz_max"]

    params = dict(proto.params)
    op     = proto.operation

    if op == "circular_average":
        params["plot_range"] = [q_min, q_max, 0, None]
    elif op == "sector_average":
        params["plot_range"] = [q_min, q_max, None, None]
    elif op in ("q_image",):
        params["plot_range"] = [qx_min, qx_max, qz_min, qz_max]
    elif op == "q_phi_image":
        phi_min = params.pop("phi_min", -180.0)
        phi_max = params.pop("phi_max",  180.0)
        params["plot_range"] = [q_min, q_max, phi_min, phi_max]
    elif op == "qr_qz_image":
        params["plot_range"] = [qx_min, qx_max, qz_min, qz_max]

    return BatchProtocol(
        name=proto.name, operation=proto.operation,
        params=params, enabled=proto.enabled, source=proto.source,
    )


# ---------------------------------------------------------------------------
# Protocol builder registry
# ---------------------------------------------------------------------------
# To add a new protocol: add one @_reg("name") function below.
# Each builder takes only the params dict and passes it directly to the
# SciAnalysis Protocol constructor — no invented or translated parameters.

_PROTOCOL_BUILDERS: dict[str, Callable[[dict], Any]] = {}


def _reg(operation: str) -> Callable:
    """Decorator that registers a protocol builder by operation name."""
    def decorator(fn: Callable) -> Callable:
        _PROTOCOL_BUILDERS[operation] = fn
        return fn
    return decorator


@_reg("circular_average")
def _build_circular_average(p: dict) -> Any:
    from SciAnalysis.XSAnalysis import Protocols
    return Protocols.circular_average(**p)


@_reg("sector_average")
def _build_sector_average(p: dict) -> Any:
    from SciAnalysis.XSAnalysis import Protocols
    return Protocols.sector_average(**p)


@_reg("line_profile")
def _build_line_profile(p: dict) -> Any:
    # line_profile maps to SA's linecut_q; params must use SA names (chi0, dq).
    from SciAnalysis.XSAnalysis import Protocols
    return Protocols.linecut_q(**p)


@_reg("q_image")
def _build_q_image(p: dict) -> Any:
    from SciAnalysis.XSAnalysis import Protocols
    return Protocols.q_image(**p)


@_reg("q_phi_image")
def _build_q_phi_image(p: dict) -> Any:
    from SciAnalysis.XSAnalysis import Protocols
    return Protocols.q_phi_image(**p)


@_reg("qr_qz_image")
def _build_qr_qz_image(p: dict) -> Any:
    # qr_qz_image maps to SA's qr_image.
    from SciAnalysis.XSAnalysis import Protocols
    return Protocols.qr_image(**p)


@_reg("thumbnails")
def _build_thumbnails(p: dict) -> Any:
    from SciAnalysis.XSAnalysis import Protocols
    return Protocols.thumbnails(**p)


def build_protocol(proto: BatchProtocol) -> Any:
    """Build a SciAnalysis protocol object. Raises ValueError for unregistered operations."""
    builder = _PROTOCOL_BUILDERS.get(proto.operation)
    if builder is None:
        raise ValueError(
            f"Unknown protocol operation: '{proto.operation}'. "
            f"Registered operations: {sorted(_PROTOCOL_BUILDERS)}"
        )
    return builder(proto.params)


def _run_file_with_protocol(
    file_path: str,
    sa_proto: Any,
    calibration: Any,
    mask: Any,
    out_dir: Path,
) -> str:
    """Load one file as a numpy array and run one SciAnalysis protocol on it.

    Returns the protocol output directory (out_dir / protocol.name).
    """
    from SciAnalysis.XSAnalysis.Data import Data2DScattering, Mask as SAMask

    # Load via our own loader (guaranteed numpy, handles tiff/h5/etc.).
    # This bypasses SA's file loader which uses the removed np.float in numpy 2.x.
    image = np.asarray(_load_image_array(file_path), dtype=float)

    # Convert mask to SA Mask object so SA's .ravel() works inside protocol methods.
    # coerce_mask_to_bool gives bool where True=masked; SA needs float where 1=valid.
    if mask is not None:
        from sciview.masking.io import coerce_mask_to_bool
        bool_mask = coerce_mask_to_bool(mask)
        if bool_mask is not None:
            sa_mask = SAMask()
            sa_mask.data = (~bool_mask).astype(float)
            mask = sa_mask
        elif not isinstance(mask, SAMask):
            mask = None  # unusable mask — don't pass garbage to SA

    data = Data2DScattering(
        infile=None,
        calibration=calibration,
        mask=mask,
        name=Path(file_path).stem,
    )
    data.data = image
    data.infile = file_path

    # Apply mask to data so 2D transforms (remesh_q_bin, remesh_q_phi, remesh_qr_bin)
    # exclude masked pixels.  1D reductions (circular_average_q_bin etc.) also use
    # mask internally via pixel_list selection, so this is harmless for them.
    if mask is not None and hasattr(mask, 'data'):
        mask_arr = np.asarray(mask.data, dtype=float)
        if mask_arr.shape == image.shape:
            data.data = image * mask_arr

    # Create per-protocol subfolder, matching ProcessorXS.access_dir behaviour.
    proto_out_dir = out_dir / sa_proto.name
    proto_out_dir.mkdir(parents=True, exist_ok=True)
    sa_proto.run(data, str(proto_out_dir), verbosity=0)
    return str(proto_out_dir)


# ---------------------------------------------------------------------------
# Batch execution backend and QThread wrapper
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[int, int, str], None]
FileDoneCallback = Callable[[BatchFileResult], None]
StatusCallback = Callable[[str], None]
StopRequested = Callable[[], bool]


def run_batch(
    job: BatchJob,
    *,
    on_progress: ProgressCallback | None = None,
    on_file_done: FileDoneCallback | None = None,
    on_status: StatusCallback | None = None,
    should_stop: StopRequested | None = None,
) -> tuple[int, int]:
    """Run all enabled protocols on all files using SciAnalysis protocols.

    Raises on import or setup errors so callers see the problem immediately.
    Returns (ok_count, err_count).
    """
    from SciAnalysis.XSAnalysis import Protocols as _SAProtos  # noqa: F401

    # numpy 2.x removed np.float, np.int etc. used by older SA versions.
    if not hasattr(np, 'float'):
        np.float = float  # type: ignore[attr-defined]
    if not hasattr(np, 'int'):
        np.int = int  # type: ignore[attr-defined]

    # Backward-compat patch: older SA calls histogram2d(normed=) which numpy 2.x removed.
    _orig_h2d = np.histogram2d
    def _h2d_compat(*args, normed=None, density=None, **kwargs):
        kwargs["density"] = (density if density is not None else False) if normed is None else normed
        return _orig_h2d(*args, **kwargs)
    np.histogram2d = _h2d_compat

    try:
        import SciAnalysis.tools as _sa_tools
        _orig_suppress = _sa_tools.SUPPRESS_EXCEPTIONS
        _sa_tools.SUPPRESS_EXCEPTIONS = False
    except Exception:
        _sa_tools = None
        _orig_suppress = None

    active = [p for p in job.protocols if p.enabled]
    if not active:
        raise ValueError("No enabled protocols in job")
    if not job.file_paths:
        raise ValueError("No input files in job")

    # Compute q bounds from calibration and inject plot_range into each protocol.
    bounds = compute_q_bounds(job.calibration)
    active = [apply_q_bounds_to_protocol(p, bounds) for p in active]

    sa_protocols = [build_protocol(p) for p in active]

    files = job.file_paths
    total = len(files) * len(active)
    done = ok = err = 0

    def emit_status(msg: str) -> None:
        if on_status: on_status(msg)

    def emit_progress(d: int, t: int, lbl: str) -> None:
        if on_progress: on_progress(d, t, lbl)

    def emit_file_done(r: BatchFileResult) -> None:
        if on_file_done: on_file_done(r)

    def stop_requested() -> bool:
        return should_stop is not None and should_stop()

    emit_status(f"Starting: {len(files)} file(s), {len(active)} protocol(s)")

    for file_path in files:
        if stop_requested():
            emit_status("Stopped by user")
            break

        out_dir = resolve_output_dir(
            file_path, job.output_dir, job.input_root, job.mirror_input_structure,
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        for proto, sa_proto in zip(active, sa_protocols):
            if stop_requested():
                break

            label = f"{os.path.basename(file_path)} → {proto.name}"
            emit_progress(done, total, label)
            t0 = time.monotonic()
            try:
                proto_out = _run_file_with_protocol(
                    file_path, sa_proto, job.calibration, job.mask, out_dir,
                )
                emit_file_done(BatchFileResult(
                    file_path=file_path, protocol_name=proto.name, status="ok",
                    output_path=proto_out, elapsed_s=time.monotonic() - t0,
                ))
                ok += 1
            except Exception as exc:
                emit_file_done(BatchFileResult(
                    file_path=file_path, protocol_name=proto.name, status="error",
                    message=str(exc), elapsed_s=time.monotonic() - t0,
                ))
                err += 1
            done += 1
            emit_progress(done, total, label)

    emit_status(f"Done — {ok} succeeded, {err} failed")
    if _sa_tools is not None:
        _sa_tools.SUPPRESS_EXCEPTIONS = _orig_suppress
    return ok, err


# Backward-compatible alias; callers should prefer run_batch.
execute_batch_job = run_batch



class BatchRunner(QThread):
    """Run a BatchJob on a worker thread, emitting per-file progress signals."""

    progress = pyqtSignal(int, int, str)
    file_done = pyqtSignal(BatchFileResult)
    status_changed = pyqtSignal(str)
    finished_batch = pyqtSignal(int, int)

    def __init__(self, job: BatchJob, parent=None):
        super().__init__(parent)
        self._job = job
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        try:
            ok, err = run_batch(
                self._job,
                on_progress=self.progress.emit,
                on_file_done=self.file_done.emit,
                on_status=self.status_changed.emit,
                should_stop=lambda: self._stop_requested,
            )
        except Exception as exc:
            self.status_changed.emit(f"Batch error: {exc}")
            ok, err = 0, 1
        self.finished_batch.emit(ok, err)

