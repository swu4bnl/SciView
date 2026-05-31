"""Interactive 2D reduction helpers for image data."""

from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from sciview.processing.angle_conventions import (
    DISPLAY_CHI_CONVENTION,
    SCIANALYSIS_CHI_CONVENTION,
    display_chi_to_scianalysis_chi,
    display_chi_to_scianalysis_sector_chi,
)
from sciview.profiles.cms_profile import DEFAULT_CALIBRATION


ReductionOperation = Literal["circular_average", "sector_average", "line_profile"]
LineMode = Literal["q", "angle", "qr", "qz"]

@dataclass(slots=True)
class ReductionRequest:
    """Structured request for a 2D reduction operation."""

    image: np.ndarray | Any
    operation: ReductionOperation
    center_x: float
    center_y: float
    bins: int = 200
    q_min: float | None = None
    q_max: float | None = None
    radius_max: float | None = None
    angle_start_deg: float = 0.0
    angle_end_deg: float = 360.0
    line_start: tuple[float, float] | None = None
    line_end: tuple[float, float] | None = None
    line_chi0_deg: float | None = None
    line_dq: float = 0.01
    line_mode: LineMode = "q"
    line_value: float | None = None
    use_mask: bool = True
    calibration: Any | None = None
    mask: Any | None = None
    show_region: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReductionResult:
    """Result of a 2D reduction operation."""

    operation: ReductionOperation
    x: np.ndarray
    y: np.ndarray
    x_label: str
    y_label: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "x": self.x.tolist(),
            "y": self.y.tolist(),
            "x_label": self.x_label,
            "y_label": self.y_label,
            "metadata": dict(self.metadata),
        }


def _coerce_image_array(image: np.ndarray | Any) -> np.ndarray:
    if hasattr(image, "data") and not isinstance(image, np.ndarray):
        image = image.data
    array = np.asarray(image)
    if array.ndim != 2:
        raise ValueError("Reduction requires a 2D image array")
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


def _angular_span(start_deg: float, end_deg: float) -> float:
    span = (end_deg - start_deg) % 360.0
    return 360.0 if np.isclose(span, 0.0) else span


def _angular_midpoint(start_deg: float, end_deg: float) -> float:
    span = _angular_span(start_deg, end_deg)
    return (start_deg + 0.5 * span) % 360.0


def _infer_line_angle(line_start: tuple[float, float], line_end: tuple[float, float]) -> float:
    dx = line_end[0] - line_start[0]
    dy = line_end[1] - line_start[1]
    return float(np.degrees(np.arctan2(-dy, dx)))


def _load_scianalysis_classes():
    try:
        data_module = import_module("SciAnalysis.XSAnalysis.Data")
    except (Exception, SystemExit):
        return None

    calibration_cls = None
    try:
        rqconv_module = import_module("SciAnalysis.XSAnalysis.DataRQconv")
        calibration_cls = getattr(rqconv_module, "CalibrationRQconv", None)
    except (Exception, SystemExit):
        calibration_cls = None

    if calibration_cls is None:
        calibration_cls = data_module.Calibration

    return calibration_cls, data_module.Data2DScattering, data_module.Mask


def _build_default_calibration(calibration_cls: Any, image_shape: tuple[int, int]):
    calibration = calibration_cls(wavelength_A=DEFAULT_CALIBRATION["wavelength_A"])
    height, width = image_shape
    if hasattr(calibration, "set_image_size"):
        calibration.set_image_size(width, height=height)
    if hasattr(calibration, "set_pixel_size"):
        calibration.set_pixel_size(pixel_size_um=DEFAULT_CALIBRATION["pixel_size_um"])
    if hasattr(calibration, "set_distance"):
        calibration.set_distance(DEFAULT_CALIBRATION["distance_m"])
    if hasattr(calibration, "set_beam_position"):
        calibration.set_beam_position(
            DEFAULT_CALIBRATION["beam_center_x"],
            DEFAULT_CALIBRATION["beam_center_y"],
        )
    if hasattr(calibration, "set_angles"):
        try:
            calibration.set_angles(
                det_orient=DEFAULT_CALIBRATION.get("detector_orient_deg", 0.0),
                det_tilt=DEFAULT_CALIBRATION.get("detector_tilt_deg", 0.0),
                det_phi=DEFAULT_CALIBRATION.get("detector_phi_deg", 0.0),
            )
        except Exception:
            pass
    return calibration


def _wrap_mask(mask: Any | None, mask_cls: Any | None) -> Any | None:
    if mask is None:
        return None
    # Keep existing SciAnalysis-like mask objects, but do not treat ndarray as one.
    if hasattr(mask, "data") and not isinstance(mask, np.ndarray):
        return mask

    array = np.asarray(mask).astype(bool)
    # SciView internal convention: True means masked/excluded.
    # SciAnalysis convention: 1 means valid/non-masked pixel.
    scianalysis_mask = (~array).astype(np.int8)
    if mask_cls is not None:
        try:
            wrapped = mask_cls()
            wrapped.data = scianalysis_mask
            return wrapped
        except Exception:
            pass

    return SimpleNamespace(data=scianalysis_mask)


def _build_scianalysis_data(request: ReductionRequest):
    if request.calibration is None:
        return None

    classes = _load_scianalysis_classes()
    if classes is None:
        return None

    try:
        _calibration_cls, data2d_cls, mask_cls = classes
        image = _coerce_image_array(request.image)
        calibration = request.calibration
        mask = _wrap_mask(request.mask, mask_cls) if request.use_mask else None

        data_2d = data2d_cls(calibration=calibration, mask=mask, name=request.metadata.get("name"))
        data_2d.data = image
        if hasattr(calibration, "set_image_size"):
            calibration.set_image_size(image.shape[1], height=image.shape[0])
        return data_2d
    except (Exception, SystemExit):
        return None


def _result_from_line(operation: ReductionOperation, line: Any, metadata: dict[str, Any]) -> ReductionResult:
    x = np.asarray(getattr(line, "x"), dtype=float)
    y = np.asarray(getattr(line, "y"), dtype=float)
    x_label = str(getattr(line, "x_label", "x"))
    y_label = str(getattr(line, "y_label", "I"))
    payload = dict(metadata)

    for attr in ("x_err", "y_err", "f_chi", "dchi"):
        if hasattr(line, attr):
            value = getattr(line, attr)
            if isinstance(value, np.ndarray):
                payload[attr] = value.tolist()
            else:
                payload[attr] = value

    return ReductionResult(
        operation=operation,
        x=x,
        y=y,
        x_label=x_label,
        y_label=y_label,
        metadata=payload,
    )


def _clip_result_by_q_window(result: ReductionResult, q_min: float | None, q_max: float | None) -> ReductionResult:
    if q_min is None and q_max is None:
        return result

    lower = 0.0 if q_min is None else float(q_min)
    upper = np.inf if q_max is None else float(q_max)
    if upper <= lower:
        return result

    metadata = dict(result.metadata)
    if q_min is not None:
        metadata["q_min"] = lower
    if q_max is not None:
        metadata["q_max"] = upper

    keep = np.isfinite(result.x) & (result.x >= lower) & (result.x <= upper)
    if not np.any(keep):
        return ReductionResult(
            operation=result.operation,
            x=np.asarray([], dtype=float),
            y=np.asarray([], dtype=float),
            x_label=result.x_label,
            y_label=result.y_label,
            metadata=metadata,
        )

    return ReductionResult(
        operation=result.operation,
        x=result.x[keep],
        y=result.y[keep],
        x_label=result.x_label,
        y_label=result.y_label,
        metadata=metadata,
    )


def _valid_pixels(image: np.ndarray, mask: np.ndarray | None, use_mask: bool) -> np.ndarray:
    valid = np.isfinite(image)
    if use_mask and mask is not None:
        valid &= ~mask
    return valid


def _radial_geometry(shape: tuple[int, int], center_x: float, center_y: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    yy, xx = np.indices(shape)
    radius = np.hypot(xx - center_x, yy - center_y)
    angle = (np.degrees(np.arctan2(-(yy - center_y), xx - center_x)) + 360.0) % 360.0
    return xx, radius, angle


def _angle_in_range(angle: np.ndarray, start_deg: float, end_deg: float) -> np.ndarray:
    start = start_deg % 360.0
    end = end_deg % 360.0
    if np.isclose((end - start) % 360.0, 0.0):
        return np.ones_like(angle, dtype=bool)
    if start <= end:
        return (angle >= start) & (angle <= end)
    return (angle >= start) | (angle <= end)


def _histogram_profile(
    radius: np.ndarray,
    image: np.ndarray,
    valid: np.ndarray,
    bins: int,
    radius_max: float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    working_radius = radius[valid]
    working_image = image[valid]

    if working_radius.size == 0:
        raise ValueError("No valid pixels available for reduction")

    max_radius = float(radius_max) if radius_max is not None else float(np.max(working_radius))
    if max_radius <= 0:
        raise ValueError("Reduction radius must be positive")

    edges = np.linspace(0.0, max_radius, int(bins) + 1)
    weighted_sum, _ = np.histogram(working_radius, bins=edges, weights=working_image)
    counts, _ = np.histogram(working_radius, bins=edges)

    profile = np.divide(
        weighted_sum,
        counts,
        out=np.full_like(weighted_sum, np.nan, dtype=float),
        where=counts > 0,
    )
    centers = 0.5 * (edges[:-1] + edges[1:])
    return centers, profile, counts


def _sample_line(image: np.ndarray, start: tuple[float, float], end: tuple[float, float], samples: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x0, y0 = start
    x1, y1 = end
    xs = np.linspace(x0, x1, int(samples))
    ys = np.linspace(y0, y1, int(samples))

    h, w = image.shape
    x_floor = np.floor(xs).astype(int)
    y_floor = np.floor(ys).astype(int)
    x_ceil = x_floor + 1
    y_ceil = y_floor + 1

    valid = (x_floor >= 0) & (y_floor >= 0) & (x_ceil < w) & (y_ceil < h)
    values = np.full(xs.shape, np.nan, dtype=float)

    if np.any(valid):
        xf = xs[valid]
        yf = ys[valid]
        x0v = x_floor[valid]
        y0v = y_floor[valid]
        x1v = x_ceil[valid]
        y1v = y_ceil[valid]

        dx = xf - x0v
        dy = yf - y0v

        top_left = image[y0v, x0v]
        top_right = image[y0v, x1v]
        bottom_left = image[y1v, x0v]
        bottom_right = image[y1v, x1v]

        values[valid] = (
            top_left * (1.0 - dx) * (1.0 - dy)
            + top_right * dx * (1.0 - dy)
            + bottom_left * (1.0 - dx) * dy
            + bottom_right * dx * dy
        )

    distances = np.sqrt((xs - x0) ** 2 + (ys - y0) ** 2)
    return distances, values, valid


class ReductionBackend:
    """Backend for image reduction operations used by the interactive tab."""

    name = "reduction"

    def run(self, request: ReductionRequest) -> ReductionResult:
        image = _coerce_image_array(request.image)
        mask = _coerce_mask_array(request.mask, image.shape)

        if request.bins < 1:
            raise ValueError("Reduction bins must be at least 1")

        scianalysis_data = _build_scianalysis_data(request)
        if scianalysis_data is not None:
            return self._run_scianalysis(scianalysis_data, request)

        if request.operation == "line_profile":
            if request.line_mode != "q":
                raise ValueError("Advanced line modes require SciAnalysis")
            if request.line_start is None or request.line_end is None:
                raise ValueError("Line profile requires line_start and line_end coordinates")

            x, y, valid = _sample_line(image, request.line_start, request.line_end, request.bins)
            if request.use_mask and mask is not None:
                sample_mask = _sample_line(mask.astype(float), request.line_start, request.line_end, request.bins)[1]
                y = np.where(sample_mask >= 0.5, np.nan, y)

            metadata = {
                **dict(request.metadata),
                "line_start": request.line_start,
                "line_end": request.line_end,
                "valid_samples": int(np.count_nonzero(np.isfinite(y))),
            }
            return ReductionResult(
                operation=request.operation,
                x=x,
                y=y,
                x_label="Distance (px)",
                y_label="Intensity",
                metadata=metadata,
            )

        _, radius, angle = _radial_geometry(image.shape, request.center_x, request.center_y)
        valid = _valid_pixels(image, mask, request.use_mask)

        if request.operation == "sector_average":
            valid &= _angle_in_range(angle, request.angle_start_deg, request.angle_end_deg)

        x, y, counts = _histogram_profile(radius, image, valid, request.bins, request.radius_max)
        metadata = {
            **dict(request.metadata),
            "center_x": request.center_x,
            "center_y": request.center_y,
            "radius_max": request.radius_max,
            "angle_start_deg": request.angle_start_deg,
            "angle_end_deg": request.angle_end_deg,
            "valid_bins": int(np.count_nonzero(counts > 0)),
            "total_bins": int(counts.size),
        }
        x_label = "Radius (px)"
        if request.operation == "sector_average":
            metadata["sector"] = {
                "start_deg": request.angle_start_deg,
                "end_deg": request.angle_end_deg,
                "angle_convention": DISPLAY_CHI_CONVENTION,
            }

        return ReductionResult(
            operation=request.operation,
            x=x,
            y=y,
            x_label=x_label,
            y_label="Intensity",
            metadata=metadata,
        )

    def _run_scianalysis(self, data_2d: Any, request: ReductionRequest) -> ReductionResult:
        if request.operation == "circular_average":
            bins_relative = max(0.1, float(request.bins) / 100.0)
            line = data_2d.circular_average_q_bin(bins_relative=bins_relative, error=True)
            metadata = {
                **dict(request.metadata),
                "backend": self.name,
                "bins_relative": bins_relative,
                "q_min": request.q_min,
                "q_max": request.q_max,
                "source": "scianalysis",
            }
            result = _result_from_line(request.operation, line, metadata)
            return _clip_result_by_q_window(result, request.q_min, request.q_max)

        if request.operation == "sector_average":
            start = float(request.angle_start_deg)
            end = float(request.angle_end_deg)
            display_angle = _angular_midpoint(start, end)
            angle = display_chi_to_scianalysis_sector_chi(display_angle, request.calibration)
            dangle = _angular_span(start, end)
            bins_relative = max(0.1, float(request.bins) / 100.0)
            line = data_2d.sector_average_q_bin(angle=angle, dangle=dangle, bins_relative=bins_relative, error=True)
            metadata = {
                **dict(request.metadata),
                "backend": self.name,
                "bins_relative": bins_relative,
                "sector_display_angle_deg": display_angle,
                "sector_display_angle_convention": DISPLAY_CHI_CONVENTION,
                "sector_angle_deg": angle,
                "sector_dangle_deg": dangle,
                "sector_angle_convention": SCIANALYSIS_CHI_CONVENTION,
                "q_min": request.q_min,
                "q_max": request.q_max,
                "source": "scianalysis",
            }
            result = _result_from_line(request.operation, line, metadata)
            return _clip_result_by_q_window(result, request.q_min, request.q_max)

        if request.operation == "line_profile":
            dq = float(request.line_dq)
            mode = request.line_mode

            if mode == "q":
                if request.line_chi0_deg is not None:
                    display_chi0 = float(request.line_chi0_deg)
                elif request.line_start is not None and request.line_end is not None:
                    display_chi0 = _infer_line_angle(request.line_start, request.line_end)
                else:
                    raise ValueError("Line mode 'q' requires line_chi0_deg or line_start+line_end")
                chi0 = display_chi_to_scianalysis_chi(display_chi0)
                line = data_2d.linecut_q(chi0=chi0, dq=dq, show_region=request.show_region)
                metadata = {
                    **dict(request.metadata),
                    "backend": self.name,
                    "line_mode": mode,
                    "line_display_angle_deg": display_chi0,
                    "line_display_angle_convention": DISPLAY_CHI_CONVENTION,
                    "line_angle_deg": chi0,
                    "line_angle_convention": SCIANALYSIS_CHI_CONVENTION,
                    "line_dq": dq,
                    "source": "scianalysis",
                }
                return _result_from_line(request.operation, line, metadata)

            if mode == "angle":
                q0 = float(request.line_value) if request.line_value is not None else 0.1
                line = data_2d.linecut_angle(q0=q0, dq=dq, show_region=request.show_region)
                metadata = {
                    **dict(request.metadata),
                    "backend": self.name,
                    "line_mode": mode,
                    "line_q0": q0,
                    "line_dq": dq,
                    "x_axis": "chi_deg",
                    "x_axis_convention": SCIANALYSIS_CHI_CONVENTION,
                    "source": "scianalysis",
                }
                return _result_from_line(request.operation, line, metadata)

            if mode == "qr":
                qz = float(request.line_value) if request.line_value is not None else 0.0
                line = data_2d.linecut_qr(qz=qz, dq=dq, show_region=request.show_region)
                metadata = {
                    **dict(request.metadata),
                    "backend": self.name,
                    "line_mode": mode,
                    "line_qz": qz,
                    "line_dq": dq,
                    "source": "scianalysis",
                }
                return _result_from_line(request.operation, line, metadata)

            if mode == "qz":
                qr = float(request.line_value) if request.line_value is not None else 0.0
                line = data_2d.linecut_qz(qr=qr, dq=dq, show_region=request.show_region)
                metadata = {
                    **dict(request.metadata),
                    "backend": self.name,
                    "line_mode": mode,
                    "line_qr": qr,
                    "line_dq": dq,
                    "source": "scianalysis",
                }
                return _result_from_line(request.operation, line, metadata)

            raise ValueError(f"Unsupported line mode: {mode}")

        raise ValueError(f"Unsupported reduction operation: {request.operation}")


def save_reduction_result(result: ReductionResult, path: str | Path) -> Path:
    """Persist a reduction result to a CSV file."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    table = np.column_stack([result.x, result.y])
    header_lines = [
        f"operation={result.operation}",
        f"x_label={result.x_label}",
        f"y_label={result.y_label}",
    ]
    x_label_lc = str(result.x_label).strip().lower()
    if x_label_lc in {"angle", "chi"} or result.metadata.get("line_mode") == "angle":
        header_lines.append(f"x_axis_convention={SCIANALYSIS_CHI_CONVENTION}")
    for key, value in result.metadata.items():
        header_lines.append(f"{key}={value}")

    np.savetxt(output_path, table, delimiter=",", header="\n".join(header_lines), comments="# ")
    return output_path
