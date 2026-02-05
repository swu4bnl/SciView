"""
Beamline-specific configuration for SciAnalysis GUI

This file contains all beamline-specific settings that can be easily
modified when transferring the software to different beamlines.
"""

import os

# =============================================================================
# BEAMLINE IDENTIFICATION
# =============================================================================
BEAMLINE_NAME = "CMS (11-BM)"
BEAMLINE_ID = "11bm"
FACILITY = "NSLS-II"

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
try:
    import sys
    if SCIANALYSIS_PATH not in sys.path:
        sys.path.insert(0, SCIANALYSIS_PATH)
    from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv
    SCIANALYSIS_AVAILABLE = True
except ImportError:
    print("Warning: SciAnalysis not available - using mock mode")
    SCIANALYSIS_AVAILABLE = False

# =============================================================================
# DETECTOR CONFIGURATIONS
# =============================================================================
DETECTOR_CONFIGS = {
    'saxs': {
        'name': 'Pilatus2M',
        'available_masks': {
            'dectris_gaps': 'Dectris/Pilatus2M_gaps-mask.png',
            'vertical_gaps': 'Dectris/Pilatus2M_vertical_gaps-mask.png',
            # Add more mask options here:
            # 'alt_mask_1': 'path/to/alternative/mask.png',
            # 'alt_mask_2': 'path/to/another/mask.png',
        },
        'default_mask': 'dectris_gaps',  # Which mask to use by default
        'calibration_file': 'caliXS.yaml',
        'pixel_size_um': 172.0,
        'default_distance_m': 5.0,
        'beam_center_x': 740,
        'beam_center_y': 1081
    },
    'waxs': {
        'name': 'Pilatus800k', 
        'available_masks': {
            'dectris_gaps': 'Dectris/Pilatus800k_gaps-mask.png',
            'vertical_gaps': 'Dectris/Pilatus800k_vertical_gaps-mask.png',
            # Add more mask options here:
            # 'alt_mask_1': 'path/to/alternative/mask.png',
        },
        'default_mask': 'dectris_gaps',  # Which mask to use by default
        'calibration_file': 'caliWS.yaml',
        'pixel_size_um': 172.0,
        'default_distance_m': 0.261,
        'beam_center_x': 476,
        'beam_center_y': 650
    },
    'maxs': {
        'name': 'Pilatus800k2',
        'available_masks': {
            'dectris_gaps': 'Dectris/Pilatus800k2_gaps-mask.png',
            'vertical_gaps': 'Dectris/Pilatus800k2_vertical_gaps-mask.png',
            # Add more mask options here:
            # 'alt_mask_1': 'path/to/alternative/mask.png',
        },
        'default_mask': 'dectris_gaps',  # Which mask to use by default
        'calibration_file': 'caliMS.yaml',
        'pixel_size_um': 172.0,
        'default_distance_m': 0.220,
        'beam_center_x': 476,
        'beam_center_y': 650
    }
}

# =============================================================================
# DEFAULT CALIBRATION PARAMETERS
# =============================================================================
DEFAULT_CALIBRATION = {
    'wavelength_A': 0.9184,
    'energy_eV': 12398.425 / 0.9184,  # hc/e conversion
    'pixel_size_um': 172.0,
    'distance_m': 0.261,
    'beam_center_x': 476,
    'beam_center_y': 650,
    'detector_orient_deg': 0,
    'detector_tilt_deg': 0,
    'detector_phi_deg': 0
}

# =============================================================================
# FILE IDENTIFICATION PATTERNS
# =============================================================================
# Patterns used to identify measurement type from filename
FILE_PATTERNS = {
    'saxs': ['saxs'],
    'waxs': ['waxs'], 
    'maxs': ['maxs']
}

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
    'default_window_size': (960, 1080),
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
    'default_scan_id': 2181336  # Generic default scan ID for tiled loading
}

# =============================================================================
# TILED SERVER CONFIGURATION
# =============================================================================

# Get default tiled profile and detector from first available
def get_default_tiled_settings():
    """Get default tiled profile and detector from configuration"""
    if not TILED_PROFILES:
        return None, None
    
    # Get first profile as default
    default_profile_name = list(TILED_PROFILES.keys())[0]
    default_profile = TILED_PROFILES[default_profile_name]
    
    # Get first detector as default
    default_detector = None
    if default_profile.get('default_detectors'):
        default_detector = list(default_profile['default_detectors'].keys())[0]
    
    return default_profile_name, default_detector

TILED_PROFILES = {
    'cms_raw': {
        'description': 'CMS Raw Data',
        'uri': 'http://tiled.nsls2.bnl.gov',
        'path': ['cms', 'raw'],
        'requires_login': True,
        'default_detectors': {
            'pilatus2m-1_image': 'SAXS',
            'pilatus800k-1_image': 'WAXS',
            'pilatus800k-2_image': 'MAXS',
            'primary': 'Primary Detector Data'
        },
        'scan_id_range': (-999, 9999999),
        'data_structure': 'h.primary.data[detector_name].read()'
    },
    'cms_processed': {
        'description': 'Processed Data (test)',
        'uri': 'http://tiled.nsls2.bnl.gov',
        'path': ['cms', 'processed'],
        'requires_login': True,
        'default_detectors': {
            'primary': 'Processed Primary Data',
            'reduced': 'Reduced Data'
        },
        'scan_id_range': (-999, 9999999),
        'data_structure': 'standard'
    },
    'nsls2_general': {
        'description': 'NSLS-II General(test)',
        'uri': 'http://tiled.nsls2.bnl.gov',
        'path': [],
        'requires_login': True,
        'default_detectors': {
            'primary': 'Primary Detector',
            'detector': 'Generic Detector'
        },
        'scan_id_range': (-999, 9999999),
        'data_structure': 'standard'
    }
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def get_detector_config(measurement_type):
    """Get detector configuration for measurement type"""
    return DETECTOR_CONFIGS.get(measurement_type.lower(), DETECTOR_CONFIGS['waxs'])

def identify_measurement_type(filename):
    """
    Identify measurement type from filename
    
    Args:
        filename: Name of the file to analyze
        
    Returns:
        str or None: 'saxs', 'waxs', 'maxs', or None if not identified
    """
    if not filename:
        return None
        
    filename_lower = filename.lower()
    
    for measurement_type, patterns in FILE_PATTERNS.items():
        if any(pattern in filename_lower for pattern in patterns):
            return measurement_type
    
    return None

def get_file_status(filename):
    """
    Get complete file status information including detector config
    
    Args:
        filename: Name of the file to analyze
        
    Returns:
        dict: Complete status information
    """
    measurement_type = identify_measurement_type(filename)
    detector_config = get_detector_config(measurement_type or 'waxs')
    
    return {
        'measurement_type': measurement_type,
        'mask_dir': MASK_BASE_DIR,
        'mask_file': detector_config['mask_file'],
        'custom_mask': detector_config['custom_mask'],
        'calibration_file': detector_config['calibration_file'],
        'detector_name': detector_config['name'],
        'pixel_size_um': detector_config['pixel_size_um'],
        'default_distance_m': detector_config['default_distance_m']
    }