"""Processing provenance shared by notebook results and raw exports."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

GEOMETRY_ANGLES = ("det_orient", "det_tilt", "det_phi", "incident_angle", "sample_normal")


def detector_geometry(calibration: Any) -> tuple[tuple[int, int], dict[str, float]]:
    """Capture detector shape and geometry as plain numbers.

    Raises ValueError when the calibration cannot describe a usable detector.
    """
    try:
        shape = (int(calibration.height), int(calibration.width))
        geometry = {
            "wavelength_A": float(calibration.wavelength_A),
            "pixel_size_um": float(calibration.pixel_size_um),
            "distance_m": float(calibration.distance_m),
            "beam_x": float(calibration.x0),
            "beam_y": float(calibration.y0),
        }
        for name in GEOMETRY_ANGLES:
            if hasattr(calibration, name):
                geometry[name] = float(getattr(calibration, name))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    if min(shape) < 1 or not all(np.isfinite(list(geometry.values()))):
        raise ValueError("Detector dimensions and geometry must be finite.")
    if min(geometry[key] for key in ("wavelength_A", "pixel_size_um", "distance_m")) <= 0:
        raise ValueError("Wavelength, pixel size and distance must be positive.")
    return shape, geometry


def mask_record(mask: np.ndarray | None) -> dict[str, Any] | None:
    if mask is None:
        return None
    return {
        "shape": list(mask.shape), "excluded_pixels": int(mask.sum()),
        "sha256": sha256(mask.tobytes()).hexdigest(),
    }


def software_versions() -> dict[str, str]:
    versions = {"numpy": np.__version__}
    try:
        versions["SciAnalysis"] = version("SciAnalysis")
    except PackageNotFoundError:
        logger.info("SciAnalysis distribution version is not available for this checkout.")
    return versions


def processing_provenance(
    *,
    backend: str,
    parameters: dict[str, Any],
    shape: tuple[int, int],
    calibration: dict[str, float] | None,
    mask: np.ndarray | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Describe one processing run so a saved result can be understood without rerunning it."""
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recipe_version": 1,
        "backend": backend,
        "parameters": parameters,
        "calibration": calibration,
        "shape": list(shape),
        "calibration_source": metadata.get("calibration_source"),
        "mask_source": metadata.get("mask_source"),
        "calibration_label": metadata.get("calibration_label"),
        "mask_label": metadata.get("mask_label"),
        "mask": mask_record(mask),
        "software_versions": software_versions(),
    }
