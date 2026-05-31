"""Application-level settings that are not beamline profile definitions."""

from __future__ import annotations

import os
import sys
import importlib
from pathlib import Path

from .scianalysis_source import (
    SciAnalysisSourceConfig,
    prepare_scianalysis_source,
    resolve_scianalysis_source,
)


_SCIANALYSIS_SOURCE = resolve_scianalysis_source()
prepare_scianalysis_source(_SCIANALYSIS_SOURCE)

SCIANALYSIS_SOURCE_MODE = _SCIANALYSIS_SOURCE.mode
SCIANALYSIS_SOURCE_ROOT = str(_SCIANALYSIS_SOURCE.root) if _SCIANALYSIS_SOURCE.root is not None else ""
SCIANALYSIS_PATH = str(_SCIANALYSIS_SOURCE.import_path) if _SCIANALYSIS_SOURCE.import_path is not None else ""


def _resolve_scianalysis_package_dir() -> Path | None:
    """Return installed SciAnalysis package directory when available."""
    try:
        scianalysis_module = importlib.import_module("SciAnalysis")
        package_file = getattr(scianalysis_module, "__file__", None)
        if package_file:
            return Path(package_file).resolve().parent
    except Exception:
        pass
    return None


def _resolve_mask_base_dir(package_dir: Path | None, source: SciAnalysisSourceConfig) -> str:
    """Resolve masks directory from installed package first, then source checkout paths."""
    candidates: list[Path] = []
    if package_dir is not None:
        candidates.append(package_dir / "XSAnalysis" / "masks")

    if source.root is not None:
        candidates.append(source.root / "SciAnalysis" / "XSAnalysis" / "masks")
        candidates.append(source.root / "XSAnalysis" / "masks")

    for path in candidates:
        if path.exists():
            return str(path)

    return str(candidates[0]) if candidates else ""


_SCIANALYSIS_PACKAGE_DIR = _resolve_scianalysis_package_dir()

# Mask directory within SciAnalysis.
MASK_BASE_DIR = _resolve_mask_base_dir(_SCIANALYSIS_PACKAGE_DIR, _SCIANALYSIS_SOURCE)

# SciAnalysis availability check.
# First try the package-installed version, then fall back to the
# optional beamline file-system path if configured.
try:
    importlib.import_module("SciAnalysis.XSAnalysis.DataRQconv")  # noqa: F401

    SCIANALYSIS_AVAILABLE = True
except ImportError:
    try:
        if SCIANALYSIS_PATH and SCIANALYSIS_PATH not in sys.path:
            sys.path.insert(0, SCIANALYSIS_PATH)
        importlib.import_module("SciAnalysis.XSAnalysis.DataRQconv")  # noqa: F401

        SCIANALYSIS_AVAILABLE = True
    except ImportError:
        print("Warning: SciAnalysis not available - using mock mode")
        SCIANALYSIS_AVAILABLE = False

SUPPORTED_FORMATS = {
    "image_files": "*.tiff *.tif *.h5 *.dat",
    "calibration_files": "*.yaml *.yml",
    "mask_files": "*.png *.tif *.tiff",
}

EXPORT_SETTINGS = {
    "default_format": "yaml",
    "precision": {
        "wavelength": 4,
        "energy": 1,
        "distance": 3,
        "pixel_size": 1,
        "beam_position": 2,
        "angles": 2,
    },
}

GUI_SETTINGS = {
    "default_window_size": (1200, 900),
    "minimum_window_size": (1024, 768),
    "visualization_ratio": 3,
    "controls_ratio": 1,
    "image_plot_ratio": 3,
    "plot_ratio": 1,
}

PHYSICAL_CONSTANTS = {
    "hc_over_e_eV_A": 12398.425,
}

IMAGE_BROWSER_SETTINGS = {
    "default_folder_patterns": ["*.tif", "*.tiff", "*.h5", "*saxs*.tif", "*waxs*.tif"],
    "max_recent_files": 10,
    "default_max_files": 500,
    "default_scan_id": 2334820,
}
