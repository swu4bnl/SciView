"""Angle convention helpers shared by reduction backends and overlays."""

from __future__ import annotations

from typing import Any

import numpy as np


DISPLAY_CHI_CONVENTION = "display chi_deg: 0=right, +90=up (counterclockwise)"
SCIANALYSIS_CHI_CONVENTION = "SciAnalysis chi_deg: 0=vertical/up, +90=right, -90=left"


def normalize_angle_deg(angle_deg: float, signed: bool = False) -> float:
    """Normalize degrees to [0, 360) or [-180, 180)."""

    angle = float(angle_deg) % 360.0
    if signed and angle >= 180.0:
        angle -= 360.0
    return angle


def display_chi_to_scianalysis_chi(display_chi_deg: float) -> float:
    """Convert natural display chi to SciAnalysis' vertical-first chi."""

    return normalize_angle_deg(90.0 - float(display_chi_deg), signed=True)


def display_chi_to_scianalysis_sector_chi(display_chi_deg: float, calibration: Any | None) -> float:
    """Convert display chi for SciAnalysis sector-average calls.

    Plain SciAnalysis ``Calibration.angle_map`` is vertical-first. RQconv's
    ``angle_map`` is already standard phi, so sector averaging should receive
    the same angle the user sees in the display.
    """

    if calibration is not None and type(calibration).__name__ == "CalibrationRQconv":
        return normalize_angle_deg(display_chi_deg, signed=True)
    return display_chi_to_scianalysis_chi(display_chi_deg)


def scianalysis_chi_to_display_chi(scianalysis_chi_deg: float) -> float:
    """Convert SciAnalysis' vertical-first chi to natural display chi."""

    return normalize_angle_deg(90.0 - float(scianalysis_chi_deg), signed=True)


def display_chi_to_screen_vector(display_chi_deg: float) -> tuple[float, float]:
    """Map display chi to a unit vector in image coordinates where y increases down."""

    chi_rad = np.radians(float(display_chi_deg))
    return float(np.cos(chi_rad)), float(-np.sin(chi_rad))


def display_angle_map(calibration: Any) -> np.ndarray:
    """Return calibration.angle_map() expressed in the display chi convention."""

    angle_map = np.asarray(calibration.angle_map(), dtype=float)
    if type(calibration).__name__ == "CalibrationRQconv":
        return angle_map
    return 90.0 - angle_map
