"""
Tab modules for SciAnalysis GUI

This package contains individual tab implementations
for different analysis and calibration functions.
"""

# Import tab classes when available
try:
    from .calibration_tab import CalibrationApp
except ImportError:
    # Handle missing dependencies gracefully
    CalibrationApp = None

try:
    from .image_browser_tab import ImageBrowserApp
except ImportError:
    # Handle missing dependencies gracefully
    ImageBrowserApp = None

try:
    from .mask_tab import MaskApp
except ImportError:
    # Handle missing dependencies gracefully
    MaskApp = None

try:
    from .reduction_tab import ReductionTab
except ImportError:
    # Handle missing dependencies gracefully
    ReductionTab = None

try:
    from .transform_tab import TransformTab
except ImportError:
    # Handle missing dependencies gracefully
    TransformTab = None