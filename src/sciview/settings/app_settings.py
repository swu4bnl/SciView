"""Application-level settings that are not beamline profile definitions."""

from __future__ import annotations

import os
import sys

# Primary SciAnalysis installation path.
SCIANALYSIS_PATH = os.getenv(
    "SCIANA_PATH",
    "/nsls2/data/cms/legacy/xf11bm/software/SciAnalysis",
)

# Mask directory within SciAnalysis.
MASK_BASE_DIR = os.path.join(
    SCIANALYSIS_PATH,
    "SciAnalysis/XSAnalysis/masks/",
)

# SciAnalysis availability check.
# First try the package-installed version, then fall back to the
# optional beamline file-system path if configured.
try:
    from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv  # noqa: F401

    SCIANALYSIS_AVAILABLE = True
except ImportError:
    try:
        if SCIANALYSIS_PATH not in sys.path:
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
