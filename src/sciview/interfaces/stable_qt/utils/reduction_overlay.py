"""Shared overlay geometry and style helpers for reduction visualizations."""

from __future__ import annotations

from typing import Any

import numpy as np

from sciview.processing.angle_conventions import (
    DISPLAY_CHI_CONVENTION,
    display_angle_map,
    display_chi_to_scianalysis_chi,
    display_chi_to_screen_vector,
)

ANGLE_CONVENTION = {
    "chi_offset_deg": 0.0,
    "chi_direction": 1.0,
    "description": DISPLAY_CHI_CONVENTION,
}

OVERLAY_STYLE = {
    "mask": {"color": "#ef4444", "alpha": 0.50},
    "circular": {"edge": "#f59e0b", "edge_soft": "#fbbf24"},
    "sector": {"color": "#ec4899", "alpha": 0.50, "edge": "#db2777"},
    "line_q": {"color": "#10b981", "alpha": 0.50, "center": "#14b8a6", "bounds": "#2dd4bf"},
    "line_chi": {"color": "#f97316", "alpha": 0.45, "edge": "#f97316"},
    "labels": {
        "text": "#e5e7eb",
        "box": "#111827",
        "box_alpha": 0.65,
        "note_text": "#f8fafc",
        "note_box_alpha": 0.78,
    },
}


def draw_solid_overlay(ax: Any, mask: np.ndarray, color: str, alpha: float) -> Any:
    """Draw a binary mask as a solid-color RGBA imshow overlay."""

    import matplotlib.colors as _mcolors

    r, g, b = _mcolors.to_rgb(color)
    rgba = np.zeros((*mask.shape, 4), dtype=np.float32)
    rgba[mask, 0] = r
    rgba[mask, 1] = g
    rgba[mask, 2] = b
    rgba[mask, 3] = float(alpha)
    return ax.imshow(rgba, origin="upper", interpolation="nearest")


def chi_to_screen_vector(chi_deg: float, calibration: Any | None = None) -> tuple[float, float]:
    """Map display chi to a unit vector in image/screen coordinates."""

    return display_chi_to_screen_vector(chi_deg)


def chi_convention_text(calibration: Any | None = None) -> str:
    return "chi: 0 deg=right, +90 deg=up; converted for SciAnalysis"


def _angle_delta_deg(a: np.ndarray, b_deg: float) -> np.ndarray:
    return ((a - float(b_deg) + 180.0) % 360.0) - 180.0


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
        lo, hi = np.nanpercentile(finite_q, [5.0, 95.0])
        return max((hi - lo) / 400.0, 1e-6)
    return 1e-3


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
    ang_err = np.abs(_angle_delta_deg(angle_map, chi_deg))
    best_angle = float(np.nanmin(ang_err[valid]))
    angle_window = max(2.0, min(15.0, best_angle + 1.0))
    candidates = valid & (ang_err <= angle_window)
    if not np.any(candidates):
        candidates = valid

    q_candidates = q_map[candidates]
    q_clipped = float(np.clip(float(q_value), np.nanmin(q_candidates), np.nanmax(q_candidates)))
    q_err = np.abs(q_map - q_clipped) / dq

    score = np.full(angle_map.shape, np.inf, dtype=float)
    score[candidates] = 0.5 * ang_err[candidates] + q_err[candidates]

    iy, ix = np.unravel_index(np.argmin(score), score.shape)
    if not np.isfinite(score[iy, ix]):
        return None
    return float(ix), float(iy)


def sector_roi_mask(
    calibration: Any,
    start_deg: float,
    end_deg: float,
    q_min: float,
    q_max: float,
) -> np.ndarray | None:
    if calibration is None or not hasattr(calibration, "angle_map") or not hasattr(calibration, "q_map"):
        return None

    q_map = np.asarray(calibration.q_map(), dtype=float)
    angle_map = display_angle_map(calibration)

    span = (float(end_deg) - float(start_deg)) % 360.0
    dangle = 360.0 if np.isclose(span, 0.0) else span
    center = (float(start_deg) + 0.5 * dangle) % 360.0

    delta = ((angle_map - center + 180.0) % 360.0) - 180.0
    in_sector = np.abs(delta) <= (0.5 * dangle)
    in_q = (q_map >= float(q_min)) & (q_map <= float(q_max))
    return in_sector & in_q


def line_q_roi_mask(
    calibration: Any,
    chi0_deg: float,
    dq: float,
    q_min: float,
    q_max: float,
) -> np.ndarray | None:
    if calibration is None or not hasattr(calibration, "qx_map") or not hasattr(calibration, "qz_map"):
        return None

    qx = np.asarray(calibration.qx_map(), dtype=float)
    qz = np.asarray(calibration.qz_map(), dtype=float)
    chi = display_chi_to_scianalysis_chi(float(chi0_deg))
    dq_val = float(dq)

    if np.isclose(chi, 0.0):
        roi = np.abs(qx) < dq_val
    elif np.isclose(chi, 90.0) or np.isclose(chi, -90.0):
        roi = np.abs(qz) < dq_val
    else:
        slope = -np.tan(np.pi / 2.0 + np.radians(chi))
        intercept = dq_val / max(abs(np.sin(np.radians(chi))), 1e-12)
        roi = np.abs(qz - slope * qx) < intercept

    if hasattr(calibration, "q_map"):
        q_map = np.asarray(calibration.q_map(), dtype=float)
        roi &= (q_map >= float(q_min)) & (q_map <= float(q_max))

    return roi
