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


def chi_to_screen_vector(chi_deg: float, calibration: Any | None = None) -> tuple[float, float]:
    """Map display chi (0=right, +90=up) to screen coordinates where y increases down."""
    chi_rad = np.radians(float(chi_deg))
    return float(np.cos(chi_rad)), float(-np.sin(chi_rad))


def chi_convention_text(calibration: Any | None = None) -> str:
    return "chi: 0\u00b0 right, +90\u00b0 up"


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

    if np.isclose(chi, 0.0) or np.isclose(chi, 180.0) or np.isclose(chi, -180.0):
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
