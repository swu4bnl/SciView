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