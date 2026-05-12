"""
Beamline-specific configuration for SciAnalysis GUI

This file contains all beamline-specific settings that can be easily
modified when transferring the software to different beamlines.
"""

import os
import sys

# Add src/ to path if not already present (for sciview imports)
_config_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_config_dir)
_src_path = os.path.join(_project_root, 'src')
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from sciview.profiles.cms_profile import (
    BEAMLINE_ID,
    BEAMLINE_NAME,
    CMS_PROFILE,
    DEFAULT_CALIBRATION,
    DETECTOR_CONFIGS,
    FACILITY,
    FILE_PATTERNS,
    TILED_PROFILES,
    get_file_status as get_profile_file_status,
    get_default_tiled_settings,
    get_detector_config,
    identify_measurement_type,
)

# =============================================================================
# BEAMLINE IDENTIFICATION
# =============================================================================
ACTIVE_PROFILE = CMS_PROFILE

# =============================================================================
# SCIANALYSIS PATHS
# =============================================================================
# Primary SciAnalysis installation path
SCIANALYSIS_PATH = os.getenv(
    'SCIANA_PATH',
    "/nsls2/data/cms/legacy/xf11bm/software/SciAnalysis"
)

# Mask directory within SciAnalysis
MASK_BASE_DIR = os.path.join(
    SCIANALYSIS_PATH, 
    "SciAnalysis/XSAnalysis/masks/"
)

# SciAnalysis availability check
# First try the package-installed version (conda-forge: scitoolsscianalysis),
# then fall back to the NSLS-II file-system path.
try:
    import sys
    from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv
    SCIANALYSIS_AVAILABLE = True
except ImportError:
    try:
        import sys
        if SCIANALYSIS_PATH not in sys.path:
            sys.path.insert(0, SCIANALYSIS_PATH)
        from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv
        SCIANALYSIS_AVAILABLE = True
    except ImportError:
        print("Warning: SciAnalysis not available - using mock mode")
        SCIANALYSIS_AVAILABLE = False

# Detector/default/tiled profile data now live in sciview.profiles.cms_profile.

# =============================================================================
# SUPPORTED FILE FORMATS
# =============================================================================
SUPPORTED_FORMATS = {
    'image_files': "*.tiff *.tif *.h5 *.dat",
    'calibration_files': "*.yaml *.yml",
    'mask_files': "*.png *.tif *.tiff"
}

# =============================================================================
# EXPORT SETTINGS
# =============================================================================
EXPORT_SETTINGS = {
    'default_format': 'yaml',
    'precision': {
        'wavelength': 4,
        'energy': 1,
        'distance': 3,
        'pixel_size': 1,
        'beam_position': 2,
        'angles': 2
    }
}

# =============================================================================
# GUI LAYOUT PREFERENCES
# =============================================================================
GUI_SETTINGS = {
    'default_window_size': (1200, 900),
    'minimum_window_size': (1024, 768),
    'visualization_ratio': 3,  # relative to controls
    'controls_ratio': 1,
    'image_plot_ratio': 3,     # image:plot = 3:1
    'plot_ratio': 1
}

# =============================================================================
# PHYSICAL CONSTANTS
# =============================================================================
PHYSICAL_CONSTANTS = {
    'hc_over_e_eV_A': 12398.425  # hc/e in eV·Å
}

# =============================================================================
# IMAGE BROWSER SETTINGS
# =============================================================================
IMAGE_BROWSER_SETTINGS = {
    'default_folder_patterns': ['*.tif', '*.tiff', '*.h5', '*saxs*.tif', '*waxs*.tif'],
    'max_recent_files': 10,
    'default_max_files': 500,
    'default_scan_id': 2334820  # Generic default scan ID for tiled loading
}

# Tiled profiles now come from the backend CMS profile module.

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def get_file_status(filename):
    """
    Get complete file status information including detector config
    
    Args:
        filename: Name of the file to analyze
        
    Returns:
        dict: Complete status information
    """
    return get_profile_file_status(filename, mask_dir=MASK_BASE_DIR)