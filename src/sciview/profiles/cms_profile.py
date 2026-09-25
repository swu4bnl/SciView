"""CMS beamline profile loader.

All facility-specific data (beamline identity, default calibration, detector
mask/geometry configs, Tiled server profiles, filename patterns) lives in
data/profile_cms.yaml — the single source of truth. This module only parses
that YAML and exposes it as the stable names other modules import. Adding a
new beamline means adding a new YAML file with the same schema, not editing
this loader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

import yaml

from sciview.settings.app_settings import PHYSICAL_CONSTANTS


def get_calibration_class():
    """Return CalibrationRQconv, falling back to Calibration if DataRQconv is unavailable."""
    try:
        m = import_module("SciAnalysis.XSAnalysis.DataRQconv")
        cls = getattr(m, "CalibrationRQconv", None)
        if cls is not None:
            return cls
    except ImportError:
        pass
    m = import_module("SciAnalysis.XSAnalysis.Data")
    return getattr(m, "Calibration")


@dataclass(slots=True)
class CmsProfile:
    """Beamline profile loaded verbatim from YAML."""

    name: str
    description: str
    beamline_name: str
    beamline_id: str
    facility: str
    default_calibration: dict[str, float] = field(default_factory=dict)
    file_patterns: dict[str, list[str]] = field(default_factory=dict)
    detector_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    tiled_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)


def _default_profile_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "profile_cms.yaml"


def _build_default_calibration(raw: dict[str, Any]) -> dict[str, float]:
    """Fill in energy_eV from wavelength_A rather than storing it twice."""
    calibration = dict(raw)
    wavelength_A = calibration.get("wavelength_A")
    if wavelength_A:
        calibration["energy_eV"] = PHYSICAL_CONSTANTS["hc_over_e_eV_A"] / wavelength_A
    return calibration


def _build_detector_configs(detectors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Key each YAML detector entry by its lowercase name for lookup by measurement type."""
    configs: dict[str, dict[str, Any]] = {}
    for detector in detectors:
        key = str(detector["name"]).lower()
        masks = dict(detector.get("masks", {}))
        default_mask_key = detector.get("default_mask")
        configs[key] = {
            "name": detector.get("display_name", detector["name"]),
            "aliases": list(detector.get("aliases", [])),
            "available_masks": masks,
            "default_mask": masks.get(default_mask_key) if default_mask_key else None,
            "calibration_file": detector.get("calibration_file"),
            "pixel_size_um": detector.get("pixel_size_um"),
            "default_distance_m": detector.get("default_distance_m"),
            "beam_center_x": detector.get("beam_center_x"),
            "beam_center_y": detector.get("beam_center_y"),
        }
    return configs


def load_cms_profile(profile_path: str | Path | None = None) -> CmsProfile:
    """Load a beamline profile YAML in full — nothing beamline-specific is hardcoded here."""

    path = Path(profile_path) if profile_path is not None else _default_profile_path()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    beamline = payload.get("beamline", {})
    return CmsProfile(
        name=str(payload.get("name", "")),
        description=str(payload.get("description", "")),
        beamline_name=str(beamline.get("name", "")),
        beamline_id=str(beamline.get("id", "")),
        facility=str(beamline.get("facility", "")),
        default_calibration=_build_default_calibration(payload.get("default_calibration", {})),
        file_patterns={k: list(v) for k, v in payload.get("file_patterns", {}).items()},
        detector_configs=_build_detector_configs(list(payload.get("detectors", []))),
        tiled_profiles={name: dict(config) for name, config in payload.get("tiled_profiles", {}).items()},
    )


CMS_PROFILE = load_cms_profile()

BEAMLINE_NAME = CMS_PROFILE.beamline_name
BEAMLINE_ID = CMS_PROFILE.beamline_id
FACILITY = CMS_PROFILE.facility
DEFAULT_CALIBRATION = CMS_PROFILE.default_calibration
FILE_PATTERNS = CMS_PROFILE.file_patterns
DETECTOR_CONFIGS = CMS_PROFILE.detector_configs
TILED_PROFILES = CMS_PROFILE.tiled_profiles


def get_default_tiled_settings() -> tuple[str | None, str | None]:
    """Get default tiled profile and detector from configuration."""

    if not TILED_PROFILES:
        return None, None

    default_profile_name = list(TILED_PROFILES.keys())[0]
    default_profile = TILED_PROFILES[default_profile_name]
    default_detector = None
    if default_profile.get("default_detectors"):
        default_detector = list(default_profile["default_detectors"].keys())[0]

    return default_profile_name, default_detector


def get_detector_config(measurement_type: str | None) -> dict[str, Any]:
    """Return detector configuration for a measurement type with WAXS fallback."""

    if measurement_type is None:
        return DETECTOR_CONFIGS["waxs"]
    return DETECTOR_CONFIGS.get(measurement_type.lower(), DETECTOR_CONFIGS["waxs"])


def identify_measurement_type(filename: str | None) -> str | None:
    """Identify measurement type from filename using profile-local patterns."""

    if not filename:
        return None

    filename_lower = filename.lower()
    for measurement_type, patterns in FILE_PATTERNS.items():
        if any(pattern in filename_lower for pattern in patterns):
            return measurement_type
    return None


def get_file_status(filename: str | None, *, mask_dir: str | None = None) -> dict[str, Any]:
    """Return detector-related file status information for compatibility callers."""

    measurement_type = identify_measurement_type(filename)
    detector_config = get_detector_config(measurement_type or "waxs")
    return {
        "measurement_type": measurement_type,
        "mask_dir": mask_dir,
        "mask_file": detector_config.get("default_mask"),
        "calibration_file": detector_config.get("calibration_file"),
        "detector_name": detector_config.get("name"),
        "pixel_size_um": detector_config.get("pixel_size_um"),
        "default_distance_m": detector_config.get("default_distance_m"),
    }
