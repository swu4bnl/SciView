"""Application-level settings that are not beamline profile definitions."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_scianalysis_package_dir() -> Path | None:
    """Return installed SciAnalysis package directory when available."""
    try:
        import SciAnalysis  # type: ignore

        package_file = getattr(SciAnalysis, "__file__", None)
        if package_file:
            return Path(package_file).resolve().parent
    except Exception:
        pass
    return None


def _resolve_scianalysis_path(package_dir: Path | None) -> str:
    """Return optional legacy import path for SciAnalysis when needed."""
    env_path = os.getenv("SCIANA_PATH", "").strip()
    if package_dir is not None:
        # Parent path that contains the SciAnalysis package.
        return str(package_dir.parent)
    return env_path


def _resolve_mask_base_dir(package_dir: Path | None, scianalysis_path: str) -> str:
    """Resolve masks directory from installed package first, then legacy paths."""
    candidates: list[Path] = []
    if package_dir is not None:
        candidates.append(package_dir / "XSAnalysis" / "masks")

    if scianalysis_path:
        legacy_root = Path(scianalysis_path)
        candidates.append(legacy_root / "SciAnalysis" / "XSAnalysis" / "masks")
        candidates.append(legacy_root / "XSAnalysis" / "masks")

    for path in candidates:
        if path.exists():
            return str(path)

    return str(candidates[0]) if candidates else ""


_SCIANALYSIS_PACKAGE_DIR = _resolve_scianalysis_package_dir()
SCIANALYSIS_PATH = _resolve_scianalysis_path(_SCIANALYSIS_PACKAGE_DIR)

# Mask directory within SciAnalysis.
MASK_BASE_DIR = _resolve_mask_base_dir(_SCIANALYSIS_PACKAGE_DIR, SCIANALYSIS_PATH)

# SciAnalysis availability check.
# First try the package-installed version, then fall back to the
# optional beamline file-system path if configured.
try:
    from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv  # noqa: F401

    SCIANALYSIS_AVAILABLE = True
except ImportError:
    try:
        if SCIANALYSIS_PATH and SCIANALYSIS_PATH not in sys.path:
            sys.path.insert(0, SCIANALYSIS_PATH)
        from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv  # noqa: F401

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
