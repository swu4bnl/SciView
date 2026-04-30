"""CMS beamline profile and compatibility helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


BEAMLINE_NAME = "CMS (11-BM)"
BEAMLINE_ID = "11bm"
FACILITY = "NSLS-II"

DEFAULT_CALIBRATION: dict[str, float] = {
    "wavelength_A": 0.9184,
    "energy_eV": 12398.425 / 0.9184,
    "pixel_size_um": 172.0,
    "distance_m": 0.261,
    "beam_center_x": 476,
    "beam_center_y": 650,
    "detector_orient_deg": 0,
    "detector_tilt_deg": 0,
    "detector_phi_deg": 0,
}

FILE_PATTERNS: dict[str, list[str]] = {
    "saxs": ["saxs"],
    "waxs": ["waxs"],
    "maxs": ["maxs"],
}

_LEGACY_DETECTOR_CONFIGS: dict[str, dict[str, Any]] = {
    "saxs": {
        "name": "Pilatus2M",
        "available_masks": {
            "dectris_gaps": "Dectris/Pilatus2M_gaps-mask.png",
            "vertical_gaps": "Dectris/Pilatus2M_vertical_gaps-mask.png",
        },
        "default_mask": "Dectris/Pilatus2M_gaps-mask.png",
        "calibration_file": "caliXS.yaml",
        "pixel_size_um": 172.0,
        "default_distance_m": 5.0,
        "beam_center_x": 740,
        "beam_center_y": 1081,
    },
    "waxs": {
        "name": "Pilatus800k",
        "available_masks": {
            "dectris_gaps": "Dectris/Pilatus800k_gaps-mask.png",
            "vertical_gaps": "Dectris/Pilatus800k_vertical_gaps-mask.png",
        },
        "default_mask": "Dectris/Pilatus800k_gaps-mask.png",
        "calibration_file": "caliWS.yaml",
        "pixel_size_um": 172.0,
        "default_distance_m": 0.261,
        "beam_center_x": 476,
        "beam_center_y": 650,
    },
    "maxs": {
        "name": "Pilatus800k2",
        "available_masks": {
            "dectris_gaps": "Dectris/Pilatus800k2_gaps-mask.png",
            "vertical_gaps": "Dectris/Pilatus800k2_vertical_gaps-mask.png",
        },
        "default_mask": "Dectris/Pilatus800k2_gaps-mask.png",
        "calibration_file": "caliMS.yaml",
        "pixel_size_um": 172.0,
        "default_distance_m": 0.220,
        "beam_center_x": 476,
        "beam_center_y": 650,
    },
}

TILED_PROFILES: dict[str, dict[str, Any]] = {
    "cms_raw": {
        "description": "CMS Raw Data",
        "uri": "http://tiled.nsls2.bnl.gov",
        "path": ["cms", "raw"],
        "requires_login": True,
        "default_detectors": {
            "pilatus2m-1_image": "SAXS",
            "pilatus800k-1_image": "WAXS",
            "pilatus800k-2_image": "MAXS",
        },
        "scan_id_range": (-999, 9999999),
        "data_access_path": ["primary", "data", "{detector}"],
        "_note": "4D shape (1, 1, H, W) - accessed via scan.primary.data[detector]",
    },
    "cms_migration": {
        "description": "CMS Migration Data",
        "uri": "http://tiled.nsls2.bnl.gov",
        "path": ["cms", "migration"],
        "requires_login": True,
        "default_detectors": {
            "pilatus2m-1_image": "SAXS",
            "pilatus800k-1_image": "WAXS",
            "pilatus800k-2_image": "MAXS",
        },
        "scan_id_range": (-999, 9999999),
        "data_access_path": ["primary", "{detector}"],
        "_note": "3D shape (1, H, W) - accessed via scan.primary[detector]",
    },
    "cms_old": {
        "description": "CMS Old Data(pre-datasecurity)",
        "uri": "http://tiled.nsls2.bnl.gov",
        "path": ["cms", "raw"],
        "requires_login": True,
        "default_detectors": {
            "pilatus2M_image": "SAXS",
            "pilatus800_image": "WAXS",
            "pilatus8002_image": "MAXS",
        },
        "scan_id_range": (-999, 9999999),
        "data_access_path": ["primary", "data", "{detector}"],
        "_note": "4D shape (1, 1, H, W) - accessed via scan.primary.data[detector]",
    },
    "nsls2_general": {
        "description": "NSLS-II General (test)",
        "uri": "http://tiled.nsls2.bnl.gov",
        "path": [],
        "requires_login": True,
        "default_detectors": {
            "primary": "Primary Detector",
            "detector": "Generic Detector",
        },
        "scan_id_range": (-999, 9999999),
        "data_access_path": ["{detector}"],
        "_note": "Standard tiled structure - accessed via scan[detector]",
    },
}


@dataclass(slots=True)
class CmsProfile:
    """Structured CMS profile loaded from YAML plus compatibility metadata."""

    name: str
    description: str
    detectors: list[dict[str, Any]] = field(default_factory=list)
    workspace_layout: dict[str, Any] = field(default_factory=dict)
    recipes: list[str] = field(default_factory=list)
    filename_patterns: list[str] = field(default_factory=list)
    beamline_name: str = BEAMLINE_NAME
    beamline_id: str = BEAMLINE_ID
    facility: str = FACILITY
    detector_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_calibration: dict[str, float] = field(default_factory=dict)
    tiled_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_profile_path() -> Path:
    return _repo_root() / "examples" / "profile_cms.yaml"


def _merge_detector_configs(profile_detectors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged = {name: dict(config) for name, config in _LEGACY_DETECTOR_CONFIGS.items()}
    for detector in profile_detectors:
        key = str(detector["name"]).lower()
        profile_default = detector.get("default_calibration")
        if key not in merged:
            merged[key] = {
                "name": detector["name"],
                "available_masks": {},
                "default_mask": None,
                "calibration_file": profile_default,
            }
            continue

        merged[key]["profile_default_calibration"] = profile_default
        merged[key]["aliases"] = list(detector.get("aliases", []))
    return merged


def load_cms_profile(profile_path: str | Path | None = None) -> CmsProfile:
    """Load the CMS profile YAML and enrich it with current compatibility data."""

    path = Path(profile_path) if profile_path is not None else _default_profile_path()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    detectors = list(payload.get("detectors", []))
    return CmsProfile(
        name=str(payload.get("name", "CMS")),
        description=str(payload.get("description", "")),
        detectors=detectors,
        workspace_layout=dict(payload.get("workspace_layout", {})),
        recipes=[str(recipe) for recipe in payload.get("recipes", [])],
        filename_patterns=[str(pattern) for pattern in payload.get("filename_patterns", [])],
        detector_configs=_merge_detector_configs(detectors),
        default_calibration=dict(DEFAULT_CALIBRATION),
        tiled_profiles={name: dict(config) for name, config in TILED_PROFILES.items()},
    )


CMS_PROFILE = load_cms_profile()
DETECTOR_CONFIGS = CMS_PROFILE.detector_configs


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