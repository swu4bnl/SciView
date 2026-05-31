"""SciAnalysis-backed 2D transform helpers for interactive visualization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Literal

import numpy as np

from sciview.processing.angle_conventions import display_angle_map


TransformOperation = Literal["q_image", "q_phi_image", "qx_qz_image"]
TransformRunner = Callable[[Any, "TransformRequest"], Any]


@dataclass(slots=True)
class TransformRequest:
    """Structured request for a 2D transform operation."""

    image: np.ndarray | Any
    operation: TransformOperation
    calibration: Any
    mask: Any | None = None
    use_mask: bool = True
    bins_q: int = 320
    bins_phi: int = 360
    q_min: float | None = None
    q_max: float | None = None
    phi_min_deg: float | None = None
    phi_max_deg: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TransformResult:
    """2D transformed image payload and axis metadata."""

    operation: TransformOperation
    image: np.ndarray
    x_axis: np.ndarray | None = None
    y_axis: np.ndarray | None = None
    x_label: str = "x"
    y_label: str = "y"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "operation": self.operation,
            "image": self.image.tolist(),
            "x_label": self.x_label,
            "y_label": self.y_label,
            "metadata": dict(self.metadata),
        }
        if self.x_axis is not None:
            payload["x_axis"] = self.x_axis.tolist()
        if self.y_axis is not None:
            payload["y_axis"] = self.y_axis.tolist()
        return payload


def _coerce_image_array(image: np.ndarray | Any) -> np.ndarray:
    if hasattr(image, "data") and not isinstance(image, np.ndarray):
        image = image.data
    array = np.asarray(image)
    if array.ndim != 2:
        raise ValueError("Transform requires a 2D image array")
    return array


def _coerce_mask_array(mask: np.ndarray | Any | None, shape: tuple[int, int]) -> np.ndarray | None:
    if mask is None:
        return None

    if hasattr(mask, "data") and not isinstance(mask, np.ndarray):
        mask = mask.data

    array = np.asarray(mask).astype(bool)
    if array.shape != shape:
        raise ValueError(f"Mask shape {array.shape} does not match image shape {shape}")
    return array


def _load_scianalysis_classes():
    try:
        data_module = import_module("SciAnalysis.XSAnalysis.Data")
    except (Exception, SystemExit):
        return None

    return data_module.Data2DScattering, getattr(data_module, "Mask", None)


def _wrap_mask(mask: Any | None, mask_cls: Any | None) -> Any | None:
    if mask is None:
        return None
    if hasattr(mask, "data") and not isinstance(mask, np.ndarray):
        return mask

    array = np.asarray(mask).astype(bool)
    # SciView convention: True is masked (exclude).
    # SciAnalysis convention: 1 is valid (include).
    scianalysis_mask = (~array).astype(np.int8)
    if mask_cls is not None:
        try:
            wrapped = mask_cls()
            wrapped.data = scianalysis_mask
            return wrapped
        except Exception:
            pass

    return SimpleNamespace(data=scianalysis_mask)


def _normalize_axis(axis: Any | None) -> np.ndarray | None:
    if axis is None:
        return None
    arr = np.asarray(axis, dtype=float)
    if arr.ndim != 1:
        return None
    return arr


def _normalize_transform_payload(payload: Any) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None, dict[str, Any]]:
    extra: dict[str, Any] = {}
    image: Any = None
    x_axis: Any = None
    y_axis: Any = None

    if isinstance(payload, dict):
        image = payload.get("image", payload.get("data"))
        x_axis = payload.get("x_axis", payload.get("x"))
        y_axis = payload.get("y_axis", payload.get("y"))
        extra = {k: v for k, v in payload.items() if k not in {"image", "data", "x_axis", "x", "y_axis", "y"}}
    elif isinstance(payload, tuple):
        if len(payload) >= 1:
            image = payload[0]
        if len(payload) >= 2:
            x_axis = payload[1]
        if len(payload) >= 3:
            y_axis = payload[2]
    elif hasattr(payload, "data"):
        image = payload.data
        x_axis = getattr(payload, "x_axis", getattr(payload, "x", None))
        y_axis = getattr(payload, "y_axis", getattr(payload, "y", None))
    else:
        image = payload

    if image is None:
        raise ValueError("SciAnalysis transform returned an empty payload")

    image_array = np.asarray(image, dtype=float)
    if image_array.ndim != 2:
        raise ValueError(f"Transformed payload must be 2D, got shape {image_array.shape}")

    return image_array, _normalize_axis(x_axis), _normalize_axis(y_axis), extra


def _invoke_first_available(data_2d: Any, attempts: list[tuple[str, dict[str, Any]]]) -> tuple[str, Any]:
    method_errors: list[str] = []

    for method_name, kwargs in attempts:
        method = getattr(data_2d, method_name, None)
        if method is None or not callable(method):
            continue

        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        try:
            return method_name, method(**filtered_kwargs)
        except TypeError as exc:
            method_errors.append(f"{method_name}: {exc}")
            continue

    supported = [name for name, _ in attempts]
    details = f" ({'; '.join(method_errors)})" if method_errors else ""
    raise ValueError(f"No supported SciAnalysis transform method found. Tried: {supported}{details}")


class TransformBackend:
    """Backend for SciAnalysis 2D transform operations used by TransformTab."""

    name = "transform"

    def __init__(self, runner_registry: dict[TransformOperation, TransformRunner] | None = None):
        self._runner_registry = dict(runner_registry or {})

    def run(self, request: TransformRequest) -> TransformResult:
        image = _coerce_image_array(request.image)
        mask = _coerce_mask_array(request.mask, image.shape)

        if request.bins_q < 2:
            raise ValueError("bins_q must be at least 2")
        if request.bins_phi < 4:
            raise ValueError("bins_phi must be at least 4")

        classes = _load_scianalysis_classes()
        if classes is None:
            raise RuntimeError("SciAnalysis is not available for transform operations")

        data2d_cls, mask_cls = classes
        wrapped_mask = _wrap_mask(mask, mask_cls) if request.use_mask else None
        data_2d = data2d_cls(calibration=request.calibration, mask=wrapped_mask, name=request.metadata.get("name"))
        data_2d.data = image

        if hasattr(request.calibration, "set_image_size"):
            request.calibration.set_image_size(image.shape[1], height=image.shape[0])

        if request.operation in self._runner_registry:
            method_name = "custom_runner"
            payload = self._runner_registry[request.operation](data_2d, request)
        else:
            method_name, payload = self._run_scianalysis(data_2d, request)

        image_out, x_axis, y_axis, payload_meta = _normalize_transform_payload(payload)

        metadata = {
            **dict(request.metadata),
            "source": "scianalysis",
            "backend": self.name,
            "method": method_name,
            "bins_q": int(request.bins_q),
            "bins_phi": int(request.bins_phi),
            "q_min": request.q_min,
            "q_max": request.q_max,
            "phi_min_deg": request.phi_min_deg,
            "phi_max_deg": request.phi_max_deg,
            **payload_meta,
        }

        x_label, y_label = self._axis_labels(request.operation)
        return TransformResult(
            operation=request.operation,
            image=image_out,
            x_axis=x_axis,
            y_axis=y_axis,
            x_label=x_label,
            y_label=y_label,
            metadata=metadata,
        )

    def _run_scianalysis(self, data_2d: Any, request: TransformRequest) -> tuple[str, Any]:
        if request.operation == "q_image":
            try:
                return _invoke_first_available(
                    data_2d,
                    [
                        (
                            "remesh_q_bin_explicit",
                            {
                                "q_min": request.q_min,
                                "q_max": request.q_max,
                                "bins": request.bins_q,
                            },
                        ),
                        (
                            "remesh_q_bin",
                            {
                                "bins": request.bins_q,
                            },
                        ),
                        (
                            "q_image",
                            {
                                "bins": request.bins_q,
                            },
                        ),
                    ],
                )
            except ValueError:
                return self._run_calibration_fallback(data_2d, request)

        if request.operation == "q_phi_image":
            try:
                return _invoke_first_available(
                    data_2d,
                    [
                        (
                            "remesh_q_phi_explicit",
                            {
                                "q_min": request.q_min,
                                "q_max": request.q_max,
                                "phi_min": request.phi_min_deg,
                                "phi_max": request.phi_max_deg,
                                "bins_q": request.bins_q,
                                "bins_phi": request.bins_phi,
                            },
                        ),
                        (
                            "remesh_q_phi",
                            {
                                "bins_q": request.bins_q,
                                "bins_phi": request.bins_phi,
                            },
                        ),
                        (
                            "q_phi_image",
                            {
                                "bins_q": request.bins_q,
                                "bins_phi": request.bins_phi,
                            },
                        ),
                    ],
                )
            except ValueError:
                return self._run_calibration_fallback(data_2d, request)

        if request.operation == "qx_qz_image":
            try:
                return _invoke_first_available(
                    data_2d,
                    [
                        (
                            "remesh_qxqz",
                            {
                                "bins_q": request.bins_q,
                            },
                        ),
                        (
                            "remesh_q_bin",
                            {
                                "bins": request.bins_q,
                            },
                        ),
                        (
                            "q_image",
                            {
                                "bins": request.bins_q,
                            },
                        ),
                    ],
                )
            except ValueError:
                return self._run_calibration_fallback(data_2d, request)

        raise ValueError(f"Unsupported transform operation: {request.operation}")

    def _run_calibration_fallback(self, data_2d: Any, request: TransformRequest) -> tuple[str, dict[str, Any]]:
        calibration = getattr(data_2d, "calibration", None)
        image = np.asarray(data_2d.data, dtype=float)
        if calibration is None:
            raise ValueError("Calibration is required for transform fallback")

        mask_bool: np.ndarray | None = None
        mask_obj = getattr(data_2d, "mask", None)
        if mask_obj is not None and hasattr(mask_obj, "data"):
            mask_data = np.asarray(mask_obj.data)
            if mask_data.shape == image.shape:
                # SciAnalysis mask convention: 1 valid, 0 masked.
                mask_bool = mask_data <= 0

        if request.operation == "q_phi_image":
            q_map = np.asarray(calibration.q_map(), dtype=float)
            phi_map = np.asarray(display_angle_map(calibration), dtype=float)

            q_valid = np.isfinite(q_map)
            q_min = float(request.q_min) if request.q_min is not None else float(np.nanmin(q_map[q_valid]))
            q_max = float(request.q_max) if request.q_max is not None else float(np.nanmax(q_map[q_valid]))
            phi_min = float(request.phi_min_deg) if request.phi_min_deg is not None else -180.0
            phi_max = float(request.phi_max_deg) if request.phi_max_deg is not None else 180.0

            image_out, q_axis, phi_axis = _bin_weighted_mean_2d(
                values_x=q_map,
                values_y=phi_map,
                intensity=image,
                bins_x=int(request.bins_q),
                bins_y=int(request.bins_phi),
                x_min=q_min,
                x_max=q_max,
                y_min=phi_min,
                y_max=phi_max,
                mask=mask_bool,
            )
            return "calibration_fallback", {
                "image": image_out,
                "x_axis": q_axis,
                "y_axis": phi_axis,
                "fallback": True,
            }

        qx_map = np.asarray(calibration.qx_map(), dtype=float)
        qz_map = np.asarray(calibration.qz_map(), dtype=float)

        x_min = float(np.nanmin(qx_map[np.isfinite(qx_map)]))
        x_max = float(np.nanmax(qx_map[np.isfinite(qx_map)]))
        y_min = float(np.nanmin(qz_map[np.isfinite(qz_map)]))
        y_max = float(np.nanmax(qz_map[np.isfinite(qz_map)]))

        image_out, x_axis, y_axis = _bin_weighted_mean_2d(
            values_x=qx_map,
            values_y=qz_map,
            intensity=image,
            bins_x=int(request.bins_q),
            bins_y=int(request.bins_q),
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            mask=mask_bool,
        )
        return "calibration_fallback", {
            "image": image_out,
            "x_axis": x_axis,
            "y_axis": y_axis,
            "fallback": True,
        }

    def _axis_labels(self, operation: TransformOperation) -> tuple[str, str]:
        if operation == "q_phi_image":
            return "q (1/A)", "chi (deg)"
        if operation == "qx_qz_image":
            return "qx (1/A)", "qz (1/A)"
        return "qx (1/A)", "qz (1/A)"


def save_transform_result(result: TransformResult, path: str | Path) -> Path:
    """Persist a transform result to .npy or .npz."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    suffix = output_path.suffix.lower()
    if suffix == ".npy":
        np.save(output_path, result.image)
        return output_path

    if suffix == ".npz":
        payload: dict[str, Any] = {
            "image": result.image,
            "operation": result.operation,
            "x_label": result.x_label,
            "y_label": result.y_label,
            "metadata_json": json.dumps(result.metadata),
        }
        if result.x_axis is not None:
            payload["x_axis"] = result.x_axis
        if result.y_axis is not None:
            payload["y_axis"] = result.y_axis
        np.savez(output_path, **payload)
        return output_path

    raise ValueError("Transform export supports only .npy and .npz")


def _bin_weighted_mean_2d(
    *,
    values_x: np.ndarray,
    values_y: np.ndarray,
    intensity: np.ndarray,
    bins_x: int,
    bins_y: int,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    mask: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    valid = np.isfinite(values_x) & np.isfinite(values_y) & np.isfinite(intensity)
    if mask is not None and mask.shape == intensity.shape:
        valid &= ~mask

    if not np.any(valid):
        return (
            np.full((bins_y, bins_x), np.nan, dtype=float),
            np.linspace(x_min, x_max, bins_x),
            np.linspace(y_min, y_max, bins_y),
        )

    x = values_x[valid]
    y = values_y[valid]
    z = intensity[valid]

    x_edges = np.linspace(float(x_min), float(x_max), int(bins_x) + 1)
    y_edges = np.linspace(float(y_min), float(y_max), int(bins_y) + 1)

    weighted_sum, _, _ = np.histogram2d(y, x, bins=[y_edges, x_edges], weights=z)
    counts, _, _ = np.histogram2d(y, x, bins=[y_edges, x_edges])
    mean = np.divide(
        weighted_sum,
        counts,
        out=np.full_like(weighted_sum, np.nan, dtype=float),
        where=counts > 0,
    )

    x_axis = 0.5 * (x_edges[:-1] + x_edges[1:])
    y_axis = 0.5 * (y_edges[:-1] + y_edges[1:])
    return mean, x_axis, y_axis
