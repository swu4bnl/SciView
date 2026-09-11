"""Batch processing backend: job definitions, per-file dispatch, and QThread runner."""

from __future__ import annotations

import fnmatch
import multiprocessing
import os
import time
from queue import Empty
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np

from sciview.settings.plot_style import PlotStyle

from sciview.processing.angle_conventions import display_chi_to_scianalysis_chi
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
BatchOutputMode = Literal["scianalysis", "preview"]

REDUCTION_OPERATIONS = ("circular_average", "sector_average", "linecut_q", "linecut_angle")
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
    preview_params: dict[str, Any] = field(default_factory=dict)

    def kind(self) -> ProtocolKind:
        return operation_kind(self.operation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "operation": self.operation,
            "params": dict(self.params),
            "preview_params": dict(self.preview_params),
            "enabled": self.enabled,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BatchProtocol":
        return cls(
            name=str(payload.get("name", payload.get("operation", ""))),
            operation=str(payload.get("operation", "")),
            params=dict(payload.get("params", {})),
            preview_params=dict(payload.get("preview_params", {})),
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
    plot_style: dict[str, Any] = field(default_factory=dict)
    output_mode: BatchOutputMode = "scianalysis"
    preview_theme: dict[str, str] = field(default_factory=dict)

    def to_transport(self) -> dict[str, Any]:
        """Serialize a job without pickling live SciAnalysis objects."""
        return {
            "file_paths": list(self.file_paths),
            "protocols": [protocol.to_dict() for protocol in self.protocols],
            "output_dir": self.output_dir,
            "output_formats": list(self.output_formats),
            "calibration": _serialize_calibration(self.calibration),
            "mask": _serialize_mask(self.mask),
            "mirror_input_structure": self.mirror_input_structure,
            "input_root": self.input_root,
            "plot_style": dict(self.plot_style),
            "output_mode": self.output_mode,
            "preview_theme": dict(self.preview_theme),
        }

    @classmethod
    def from_transport(cls, payload: dict[str, Any]) -> "BatchJob":
        return cls(
            file_paths=[str(path) for path in payload.get("file_paths", [])],
            protocols=[BatchProtocol.from_dict(item) for item in payload.get("protocols", [])],
            output_dir=str(payload.get("output_dir", "")),
            output_formats=[str(item) for item in payload.get("output_formats", [])],
            calibration=_deserialize_calibration(payload.get("calibration")),
            mask=payload.get("mask"),
            mirror_input_structure=bool(payload.get("mirror_input_structure", True)),
            input_root=str(payload.get("input_root", "")),
            plot_style=dict(payload.get("plot_style", {})),
            output_mode=str(payload.get("output_mode", "scianalysis")),
            preview_theme=dict(payload.get("preview_theme", {})),
        )


def _serialize_calibration(calibration: Any | None) -> dict[str, Any] | None:
    if calibration is None:
        return None
    return {
        "wavelength_A": float(getattr(calibration, "wavelength_A")),
        "width": int(getattr(calibration, "width", 0) or 0),
        "height": int(getattr(calibration, "height", 0) or 0),
        "pixel_size_um": float(getattr(calibration, "pixel_size_um")),
        "beam_position": [float(getattr(calibration, "x0")), float(getattr(calibration, "y0"))],
        "distance_m": float(getattr(calibration, "distance_m")),
        "det_orient": float(getattr(calibration, "det_orient", 0.0) or 0.0),
        "det_tilt": float(getattr(calibration, "det_tilt", 0.0) or 0.0),
        "det_phi": float(getattr(calibration, "det_phi", 0.0) or 0.0),
    }


def _deserialize_calibration(payload: dict[str, Any] | None) -> Any | None:
    if not payload:
        return None
    from sciview.profiles.cms_profile import get_calibration_class

    calibration = get_calibration_class()(wavelength_A=float(payload["wavelength_A"]))
    width = int(payload.get("width", 0))
    height = int(payload.get("height", 0))
    if width > 0 and height > 0:
        calibration.set_image_size(width, height=height)
    calibration.set_pixel_size(pixel_size_um=float(payload["pixel_size_um"]))
    calibration.set_beam_position(*[float(value) for value in payload["beam_position"]])
    calibration.set_distance(float(payload["distance_m"]))
    if hasattr(calibration, "set_angles"):
        calibration.set_angles(
            det_orient=float(payload.get("det_orient", 0.0)),
            det_tilt=float(payload.get("det_tilt", 0.0)),
            det_phi=float(payload.get("det_phi", 0.0)),
        )
    return calibration


def _serialize_mask(mask: Any | None) -> np.ndarray | None:
    if mask is None:
        return None
    value = mask.data if hasattr(mask, "data") and not isinstance(mask, np.ndarray) else mask
    return np.asarray(value).copy()


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
    image_shape: tuple[int, int] | None = None,
) -> dict[str, float]:
    """Compute q/qx/qz/qr bounds from a calibration object.

    mask_array: optional bool array where True = masked pixel (excluded from bounds).
    Returns an empty dict when calibration is None or no valid pixels remain.
    """
    if calibration is None:
        return {}

    try:
        if image_shape is not None and hasattr(calibration, "set_image_size"):
            h, w = image_shape
            calibration.set_image_size(w, height=h)

        q_fn = getattr(calibration, "q_map", None)
        if q_fn is None:
            return {}
        q_raw = q_fn()
        if q_raw is None:
            return {}
        q_map = np.asarray(q_raw, dtype=float)
        valid = np.isfinite(q_map)

        qx_map = None
        qx_fn = getattr(calibration, "qx_map", None)
        if qx_fn is not None:
            try:
                qx_raw = qx_fn()
                if qx_raw is not None:
                    qx_map = np.asarray(qx_raw, dtype=float)
                    valid &= np.isfinite(qx_map)
            except Exception:
                pass

        qz_map = None
        qz_fn = getattr(calibration, "qz_map", None)
        if qz_fn is not None:
            try:
                qz_raw = qz_fn()
                if qz_raw is not None:
                    qz_map = np.asarray(qz_raw, dtype=float)
                    valid &= np.isfinite(qz_map)
            except Exception:
                pass

        qr_map = None
        qr_fn = getattr(calibration, "qr_map", None)
        if qr_fn is not None:
            try:
                qr_raw = qr_fn()
                if qr_raw is not None:
                    qr_map = np.asarray(qr_raw, dtype=float)
                    valid &= np.isfinite(qr_map)
            except Exception:
                pass

        if mask_array is not None and mask_array.shape == q_map.shape:
            valid &= ~mask_array  # True=masked → exclude

        if not np.any(valid):
            return {}

        return {
            "q_min": float(np.min(q_map[valid])),
            "q_max": float(np.max(q_map[valid])),
            "qx_min": float(np.min(qx_map[valid])) if qx_map is not None else float(np.min(q_map[valid])),
            "qx_max": float(np.max(qx_map[valid])) if qx_map is not None else float(np.max(q_map[valid])),
            "qz_min": float(np.min(qz_map[valid])) if qz_map is not None else 0.0,
            "qz_max": float(np.max(qz_map[valid])) if qz_map is not None else float(np.max(q_map[valid])),
            "qr_min": float(np.min(qr_map[valid])) if qr_map is not None else float(np.min(q_map[valid])),
            "qr_max": float(np.max(qr_map[valid])) if qr_map is not None else float(np.max(q_map[valid])),
        }
    except Exception:
        return {}


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
    qr_min = bounds.get("qr_min", qx_min)
    qr_max = bounds.get("qr_max", qx_max)

    params = dict(proto.params)
    op     = proto.operation

    if op == "circular_average":
        params["plot_range"] = [q_min, q_max, 0, None]
    elif op == "sector_average":
        params["plot_range"] = [q_min, q_max, None, None]
    elif op == "linecut_q":
        params["plot_range"] = [q_min, q_max, 0, None]
    elif op == "linecut_angle":
        params["plot_range"] = [-180, 180, 0, None]
    elif op in ("q_image",):
        params["plot_range"] = [qx_min, qx_max, qz_min, qz_max]
    elif op == "qr_qz_image":
        params["plot_range"] = [qr_min, qr_max, qz_min, qz_max]
    elif op == "q_phi_image":
        phi_min = params.pop("phi_min", -180.0)
        phi_max = params.pop("phi_max",  180.0)
        params["plot_range"] = [q_min, q_max, phi_min, phi_max]

    return BatchProtocol(
        name=proto.name, operation=proto.operation,
        params=params, preview_params=dict(proto.preview_params),
        enabled=proto.enabled, source=proto.source,
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


@_reg("linecut_q")
def _build_linecut_q(p: dict) -> Any:
    from SciAnalysis.XSAnalysis import Protocols
    params = dict(p)
    if "chi0" in params:
        params["chi0"] = display_chi_to_scianalysis_chi(float(params["chi0"]))
    return Protocols.linecut_q(**params)


@_reg("linecut_angle")
def _build_linecut_angle(p: dict) -> Any:
    from SciAnalysis.XSAnalysis import Protocols
    return Protocols.linecut_angle(**p)


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
        bool_mask = coerce_mask_to_bool(mask, shape=image.shape)
        if bool_mask is not None:
            sa_mask = SAMask()
            sa_mask.data = (~bool_mask).astype(float)
            mask = sa_mask
        else:
            mask = None  # mask doesn't match image shape or is unusable

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
    title_size = getattr(sa_proto, "run_args", {}).get("sciview_title_size")
    if title_size is None:
        sa_proto.run(data, str(proto_out_dir), verbosity=0)
    else:
        import matplotlib.pyplot as plt

        original_figtext = plt.figtext

        def styled_figtext(*args, **kwargs):
            kwargs["size"] = title_size
            return original_figtext(*args, **kwargs)

        plt.figtext = styled_figtext
        try:
            sa_proto.run(data, str(proto_out_dir), verbosity=0)
        finally:
            plt.figtext = original_figtext
    return str(proto_out_dir)


def _valid_limits(first: Any, second: Any) -> tuple[float, float] | None:
    if first is None or second is None:
        return None
    first_value = float(first)
    second_value = float(second)
    return (first_value, second_value) if second_value > first_value else None


def _protocol_output_dir_name(operation: str) -> str:
    return "qr_image" if operation == "qr_qz_image" else operation


def _scianalysis_plot_args(protocol: BatchProtocol, style: PlotStyle) -> dict[str, Any]:
    args = style.scianalysis_args(image=protocol.kind() == "transform")
    if protocol.kind() == "reduction":
        scale = str(protocol.preview_params.get("scale", "linear"))
        args["xlog"] = scale in ("logx", "loglog")
        args["ylog"] = scale in ("logy", "loglog")
    return args


def _run_preview_file_with_protocol(
    file_path: str,
    protocol: BatchProtocol,
    calibration: Any,
    mask: Any,
    out_dir: Path,
    style: PlotStyle,
    theme: dict[str, str],
) -> str:
    """Recreate and save the corresponding SciView preview plot."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from sciview.masking.io import coerce_mask_to_bool
    from sciview.processing.plot_rendering import (
        REDUCTION_FIGURE_SIZE,
        TRANSFORM_FIGURE_SIZE,
        create_transform_axes,
        render_reduction_plot,
        render_transform_plot,
    )
    from sciview.processing.reduction import ReductionBackend, ReductionRequest, save_reduction_result
    from sciview.processing.transform import TransformBackend, TransformRequest, save_transform_result

    image = np.asarray(_load_image_array(file_path), dtype=float)
    bool_mask = coerce_mask_to_bool(mask, shape=image.shape)
    params = protocol.params
    preview = protocol.preview_params
    proto_out_dir = out_dir / _protocol_output_dir_name(protocol.operation)
    proto_out_dir.mkdir(parents=True, exist_ok=True)
    output_stem = f"{Path(file_path).stem}_{protocol.operation}"
    output_path = proto_out_dir / f"{output_stem}.png"

    if protocol.kind() == "reduction":
        center_x = float(getattr(calibration, "x0", (image.shape[1] - 1) / 2.0))
        center_y = float(getattr(calibration, "y0", (image.shape[0] - 1) / 2.0))
        if protocol.operation == "sector_average":
            angle = float(params.get("angle", 0.0))
            width = float(params.get("dangle", 360.0))
            angle_start = float(preview.get("angle_start", angle - width / 2.0))
            angle_end = float(preview.get("angle_end", angle + width / 2.0))
        else:
            angle_start = float(preview.get("angle_start", 0.0))
            angle_end = float(preview.get("angle_end", 360.0))
        request = ReductionRequest(
            image=image,
            operation=protocol.operation,
            center_x=center_x,
            center_y=center_y,
            bins_relative=params.get("bins_relative"),
            q_min=preview.get("q_min"),
            q_max=preview.get("q_max"),
            angle_start_deg=angle_start,
            angle_end_deg=angle_end,
            line_chi0_deg=preview.get("chi0", params.get("chi0")),
            line_dq=float(preview.get("dq", params.get("dq", 0.01))),
            line_value=preview.get("q0", params.get("q0")),
            line_mode="angle" if protocol.operation == "linecut_angle" else "q",
            calibration=calibration,
            mask=bool_mask,
            use_mask=bool_mask is not None,
            metadata={"source_path": file_path},
        )
        result = ReductionBackend().run(request)
        save_reduction_result(result, proto_out_dir / f"{output_stem}.csv")
        figure = Figure(figsize=REDUCTION_FIGURE_SIZE, layout="constrained")
        FigureCanvasAgg(figure)
        axis = figure.subplots()
        render_reduction_plot(
            figure,
            axis,
            result,
            style,
            scale=str(preview.get("scale", "logy" if params.get("ylog") else "linear")),
            x_limits=_valid_limits(preview.get("q_min"), preview.get("q_max")),
            theme=theme,
        )
    else:
        if protocol.operation == "thumbnails":
            raise ValueError("Thumbnails do not have a Transform preview")
        request = TransformRequest(
            image=image,
            operation=protocol.operation,
            calibration=calibration,
            mask=bool_mask,
            use_mask=bool_mask is not None,
            bins_relative=params.get("bins_relative"),
            bins_phi=int(params.get("bins_phi", 360)),
            preferred_method=preview.get("transform_method"),
            x_min=preview.get("x_min"),
            x_max=preview.get("x_max"),
            y_min=preview.get("y_min"),
            y_max=preview.get("y_max"),
            metadata={"source_path": file_path},
        )
        result = TransformBackend().run(request)
        save_transform_result(result, proto_out_dir / f"{output_stem}.npz")
        figure = Figure(figsize=TRANSFORM_FIGURE_SIZE, layout="constrained")
        FigureCanvasAgg(figure)
        axis, colorbar_axis = create_transform_axes(figure)
        render_transform_plot(
            figure,
            axis,
            result,
            style,
            colorbar_axis=colorbar_axis,
            scale=str(preview.get("scale", "linear")),
            vmin=preview.get("vmin"),
            vmax=preview.get("vmax"),
            x_limits=_valid_limits(preview.get("x_min"), preview.get("x_max")),
            y_limits=_valid_limits(preview.get("y_min"), preview.get("y_max")),
            theme=theme,
        )

    figure.savefig(
        output_path,
        dpi=style.dpi,
        facecolor=figure.get_facecolor(),
    )
    figure.clear()
    return str(output_path)


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
    if not hasattr(np, 'float'):
        np.float = float  # type: ignore[attr-defined]
    if not hasattr(np, 'int'):
        np.int = int  # type: ignore[attr-defined]
    from SciAnalysis.XSAnalysis import Protocols as _SAProtos  # noqa: F401

    # Backward-compat patch: older SA calls histogram2d(normed=) which numpy 2.x removed.
    _orig_h2d = np.histogram2d
    def _h2d_compat(*args, normed=None, density=None, **kwargs):
        kwargs["density"] = (density if density is not None else False) if normed is None else normed
        return _orig_h2d(*args, **kwargs)
    np.histogram2d = _h2d_compat

    _sa_tools = None
    _orig_suppress = None
    try:
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

        style = PlotStyle.from_dict(job.plot_style)
        if job.output_mode == "preview":
            executables = active
        else:
            active = [
                BatchProtocol(
                    name=proto.name,
                    operation=proto.operation,
                    params={
                        **proto.params,
                        **_scianalysis_plot_args(proto, style),
                    },
                    preview_params=dict(proto.preview_params),
                    enabled=proto.enabled,
                    source=proto.source,
                )
                for proto in active
            ]

            # Compute q bounds from calibration and inject plot_range into each protocol.
            from sciview.masking.io import coerce_mask_to_bool
            bounds = compute_q_bounds(job.calibration, coerce_mask_to_bool(job.mask))
            active = [apply_q_bounds_to_protocol(p, bounds) for p in active]
            executables = [build_protocol(p) for p in active]

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

        mode_label = "matching previews" if job.output_mode == "preview" else "SciAnalysis plots"
        emit_status(
            f"Starting {mode_label}: {len(files)} file(s), {len(active)} protocol(s)"
        )

        for file_path in files:
            if stop_requested():
                emit_status("Stopped by user")
                break

            out_dir = resolve_output_dir(
                file_path, job.output_dir, job.input_root, job.mirror_input_structure,
            )
            out_dir.mkdir(parents=True, exist_ok=True)

            for proto, executable in zip(active, executables):
                if stop_requested():
                    break

                label = f"{os.path.basename(file_path)} → {proto.name}"
                emit_progress(done, total, label)
                t0 = time.monotonic()
                try:
                    if job.output_mode == "preview":
                        proto_out = _run_preview_file_with_protocol(
                            file_path,
                            proto,
                            job.calibration,
                            job.mask,
                            out_dir,
                            style,
                            job.preview_theme,
                        )
                    else:
                        proto_out = _run_file_with_protocol(
                            file_path, executable, job.calibration, job.mask, out_dir,
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
        return ok, err
    finally:
        np.histogram2d = _orig_h2d
        if _sa_tools is not None and _orig_suppress is not None:
            _sa_tools.SUPPRESS_EXCEPTIONS = _orig_suppress


# Backward-compatible alias; callers should prefer run_batch.
execute_batch_job = run_batch


def _batch_process_main(job_payload, message_queue, stop_event) -> None:
    """Child-process entry point; keep Matplotlib state outside the GUI process."""
    os.environ["MPLBACKEND"] = "Agg"
    import matplotlib

    matplotlib.use("Agg", force=True)
    try:
        job = BatchJob.from_transport(job_payload)
        ok, err = run_batch(
            job,
            on_progress=lambda done, total, label: message_queue.put(
                ("progress", (done, total, label))
            ),
            on_file_done=lambda result: message_queue.put(
                ("file_done", result.__dict__)
            ),
            on_status=lambda message: message_queue.put(("status", message)),
            should_stop=stop_event.is_set,
        )
        message_queue.put(("finished", (ok, err)))
    except Exception as exc:
        message_queue.put(("status", f"Batch error: {exc}"))
        message_queue.put(("finished", (0, 1)))



class BatchRunner(QThread):
    """Supervise a spawned BatchJob process and relay its progress signals."""

    progress = pyqtSignal(int, int, str)
    file_done = pyqtSignal(BatchFileResult)
    status_changed = pyqtSignal(str)
    finished_batch = pyqtSignal(int, int)

    def __init__(self, job: BatchJob, parent=None):
        super().__init__(parent)
        self._job = job
        self._stop_requested = False
        self._stop_event = None
        self._process = None

    def request_stop(self) -> None:
        self._stop_requested = True
        if self._stop_event is not None:
            self._stop_event.set()

    def run(self) -> None:
        try:
            context = multiprocessing.get_context("spawn")
            message_queue = context.Queue()
            self._stop_event = context.Event()
            if self._stop_requested:
                self._stop_event.set()
            self._process = context.Process(
                target=_batch_process_main,
                args=(self._job.to_transport(), message_queue, self._stop_event),
                daemon=True,
            )
            self._process.start()
            finished = None
            completed_ok = completed_err = 0
            cancel_requested_at = None
            while self._process.is_alive() or finished is None:
                if self._stop_requested and cancel_requested_at is None:
                    cancel_requested_at = time.monotonic()
                if (
                    cancel_requested_at is not None
                    and self._process.is_alive()
                    and time.monotonic() - cancel_requested_at >= 2.0
                ):
                    self.status_changed.emit("Stopping batch process")
                    self._process.terminate()
                    finished = (completed_ok, completed_err)
                    break
                try:
                    kind, payload = message_queue.get(timeout=0.1)
                except Empty:
                    if not self._process.is_alive():
                        break
                    continue
                if kind == "progress":
                    self.progress.emit(*payload)
                elif kind == "file_done":
                    result = BatchFileResult(**payload)
                    completed_ok += result.status == "ok"
                    completed_err += result.status == "error"
                    self.file_done.emit(result)
                elif kind == "status":
                    self.status_changed.emit(payload)
                elif kind == "finished":
                    finished = payload
            self._process.join()
            if finished is None:
                raise RuntimeError(f"Batch process exited with code {self._process.exitcode}")
            ok, err = finished
        except Exception as exc:
            self.status_changed.emit(f"Batch error: {exc}")
            ok, err = 0, 1
        finally:
            self._process = None
            self._stop_event = None
        self.finished_batch.emit(ok, err)

