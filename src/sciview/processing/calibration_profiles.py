"""Fast calibration-preview 1D profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from sciview.processing.angle_conventions import DISPLAY_CHI_CONVENTION, display_angle_map


@dataclass(slots=True)
class CalibrationProfile:
    """One 1D calibration preview curve."""

    x: np.ndarray
    y: np.ndarray
    x_label: str = "q"
    y_label: str = "I(q)"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CalibrationProfileSet:
    """Circular and cardinal-sector profiles used by the calibration tab."""

    circular: CalibrationProfile
    horizontal_0: CalibrationProfile
    horizontal_180: CalibrationProfile
    vertical_90: CalibrationProfile
    vertical_270: CalibrationProfile
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, CalibrationProfile]:
        return {
            "Circular Avg": self.circular,
            "Horizontal 0deg": self.horizontal_0,
            "Horizontal 180deg": self.horizontal_180,
            "Vertical 90deg": self.vertical_90,
            "Vertical 270deg": self.vertical_270,
        }


def compute_calibration_profiles(
    *,
    image: np.ndarray | Any,
    calibration: Any,
    mask: np.ndarray | Any | None = None,
    use_mask: bool = False,
    bins: int = 600,
    sector_dangle_deg: float = 5.0,
) -> CalibrationProfileSet:
    """Compute calibration preview profiles from q and display-angle maps.

    This is intended for interactive feedback while tuning calibration geometry.
    It avoids repeated SciAnalysis 1D reductions by calculating the q map and
    display-angle map once, then histogramming the circular and sector profiles.
    """

    image_array = _coerce_2d_array(image, "image")
    q_map = np.asarray(calibration.q_map(), dtype=float)
    angle_map = _display_angle_map_after_q_map(calibration)
    if q_map.shape != image_array.shape or angle_map.shape != image_array.shape:
        raise ValueError("Calibration maps must match image shape")

    mask_array = _coerce_mask(mask, image_array.shape) if use_mask else None
    valid = np.isfinite(image_array) & np.isfinite(q_map) & np.isfinite(angle_map)
    if mask_array is not None:
        valid &= ~mask_array
    if not np.any(valid):
        raise ValueError("No valid pixels available for calibration profiles")

    q_values = q_map[valid]
    q_min = float(np.nanmin(q_values))
    q_max = float(np.nanmax(q_values))
    if not np.isfinite(q_min) or not np.isfinite(q_max) or q_max <= q_min:
        raise ValueError("Calibration q range is invalid")

    edges = np.linspace(q_min, q_max, int(bins) + 1)
    q_axis = 0.5 * (edges[:-1] + edges[1:])
    bin_index = np.searchsorted(edges, q_values, side="right") - 1
    bin_index = np.clip(bin_index, 0, int(bins) - 1)
    intensity = image_array[valid]
    angle_values = np.mod(angle_map[valid], 360.0)

    circular = _profile_from_bins(bin_index, intensity, int(bins), q_axis, name="Circular Avg")
    horizontal_0 = _profile_for_sector(bin_index, intensity, angle_values, int(bins), q_axis, 0.0, sector_dangle_deg)
    horizontal_180 = _profile_for_sector(bin_index, intensity, angle_values, int(bins), q_axis, 180.0, sector_dangle_deg)
    vertical_90 = _profile_for_sector(bin_index, intensity, angle_values, int(bins), q_axis, 90.0, sector_dangle_deg)
    vertical_270 = _profile_for_sector(bin_index, intensity, angle_values, int(bins), q_axis, -90.0, sector_dangle_deg)

    return CalibrationProfileSet(
        circular=circular,
        horizontal_0=horizontal_0,
        horizontal_180=horizontal_180,
        vertical_90=vertical_90,
        vertical_270=vertical_270,
        metadata={
            "bins": int(bins),
            "q_min": q_min,
            "q_max": q_max,
            "sector_dangle_deg": float(sector_dangle_deg),
            "angle_convention": DISPLAY_CHI_CONVENTION,
            "source": "numpy",
        },
    )


def _coerce_2d_array(value: np.ndarray | Any, label: str) -> np.ndarray:
    if hasattr(value, "data") and not isinstance(value, np.ndarray):
        value = value.data
    array = np.asarray(value, dtype=float)
    if array.ndim != 2:
        raise ValueError(f"Calibration profile {label} must be 2D")
    return array


def _coerce_mask(mask: np.ndarray | Any | None, shape: tuple[int, int]) -> np.ndarray | None:
    if mask is None:
        return None
    if hasattr(mask, "data") and not isinstance(mask, np.ndarray):
        mask = mask.data
    array = np.asarray(mask).astype(bool)
    if array.shape != shape:
        raise ValueError(f"Mask shape {array.shape} does not match image shape {shape}")
    return array


def _display_angle_map_after_q_map(calibration: Any) -> np.ndarray:
    if type(calibration).__name__ == "CalibrationRQconv":
        cached_angle_map = getattr(calibration, "angle_map_data", None)
        if cached_angle_map is not None:
            return np.asarray(cached_angle_map, dtype=float)
    return np.asarray(display_angle_map(calibration), dtype=float)


def _profile_from_bins(
    bin_index: np.ndarray,
    intensity: np.ndarray,
    bins: int,
    q_axis: np.ndarray,
    *,
    name: str,
) -> CalibrationProfile:
    weighted_sum = np.bincount(bin_index, weights=intensity, minlength=bins).astype(float)
    counts = np.bincount(bin_index, minlength=bins).astype(float)
    profile = np.divide(
        weighted_sum,
        counts,
        out=np.full(weighted_sum.shape, np.nan, dtype=float),
        where=counts > 0,
    )
    return CalibrationProfile(
        x=q_axis,
        y=profile,
        metadata={"name": name, "valid_bins": int(np.count_nonzero(counts > 0))},
    )


def _profile_for_sector(
    bin_index: np.ndarray,
    intensity: np.ndarray,
    angle_map: np.ndarray,
    bins: int,
    q_axis: np.ndarray,
    center_deg: float,
    dangle_deg: float,
) -> CalibrationProfile:
    sector = _angle_distance_deg(angle_map, center_deg) <= float(dangle_deg) / 2.0
    return _profile_from_bins(
        bin_index[sector],
        intensity[sector],
        bins,
        q_axis,
        name=f"Sector {center_deg:g}deg",
    )


def _angle_distance_deg(angle_map: np.ndarray, center_deg: float) -> np.ndarray:
    return np.abs((angle_map - float(center_deg) + 180.0) % 360.0 - 180.0)