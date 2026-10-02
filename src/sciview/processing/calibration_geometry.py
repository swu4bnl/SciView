"""Geometry conversions shared by calibrated views."""

from __future__ import annotations

from typing import Any

import numpy as np

from sciview.processing.angle_conventions import display_angle_map


def q_to_pixel_radius(calibration: Any, q_value: float) -> float | None:
    """Convert a scattering-vector magnitude to radial detector pixels."""
    if calibration is None or not hasattr(calibration, "q_to_angle"):
        return None
    distance_m = getattr(calibration, "distance_m", getattr(calibration, "_distance_m", None))
    pixel_size_um = getattr(calibration, "pixel_size_um", getattr(calibration, "_pixel_size_um", None))
    try:
        angle_deg = float(calibration.q_to_angle(float(q_value)))
        radius = float(distance_m) * np.tan(np.radians(angle_deg)) / (float(pixel_size_um) * 1e-6)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return radius if np.isfinite(radius) and radius >= 0 else None


def chi_q_to_pixel(
    calibration: Any,
    chi_deg: float,
    q_value: float,
) -> tuple[float, float] | None:
    """Find a display pixel location that matches requested (chi, q)."""
    if calibration is None or not hasattr(calibration, "angle_map") or not hasattr(calibration, "q_map"):
        return None

    try:
        q_map = np.asarray(calibration.q_map(), dtype=float)
        angle_map = display_angle_map(calibration)
    except Exception:
        return None

    if angle_map.shape != q_map.shape:
        return None

    valid = np.isfinite(angle_map) & np.isfinite(q_map)
    if not np.any(valid):
        return None

    dq = _q_per_pixel_from_map(q_map, valid, calibration)
    angle_error = np.abs(_angle_delta_deg(angle_map, chi_deg))
    best_angle = float(np.nanmin(angle_error[valid]))
    angle_window = max(2.0, min(15.0, best_angle + 1.0))
    candidates = valid & (angle_error <= angle_window)
    if not np.any(candidates):
        candidates = valid

    q_candidates = q_map[candidates]
    q_clipped = float(np.clip(float(q_value), np.nanmin(q_candidates), np.nanmax(q_candidates)))
    q_error = np.abs(q_map - q_clipped) / dq

    score = np.full(angle_map.shape, np.inf, dtype=float)
    score[candidates] = 0.5 * angle_error[candidates] + q_error[candidates]

    row, column = np.unravel_index(np.argmin(score), score.shape)
    if not np.isfinite(score[row, column]):
        return None
    return float(column), float(row)


def _angle_delta_deg(angle: np.ndarray, reference_deg: float) -> np.ndarray:
    return ((angle - float(reference_deg) + 180.0) % 360.0) - 180.0


def _q_per_pixel_from_map(q_map: np.ndarray, valid: np.ndarray, calibration: Any) -> float:
    getter = getattr(calibration, "get_q_per_pixel", None)
    if getter is not None:
        try:
            dq = float(getter())
            if np.isfinite(dq) and dq > 0:
                return dq
        except Exception:
            pass

    finite_q = q_map[valid]
    if finite_q.size >= 2:
        low, high = np.nanpercentile(finite_q, [5.0, 95.0])
        return max((high - low) / 400.0, 1e-6)
    return 1e-3
