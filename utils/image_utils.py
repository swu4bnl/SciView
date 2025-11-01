"""
Utility functions for image handling and processing

This module provides common utilities for image loading, processing,
and data management.
"""

import os
import numpy as np
from typing import Optional, Tuple, Union

# Import configuration
from config.beamline_config import SUPPORTED_FORMATS


def validate_image_path(file_path: str) -> bool:
    """
    Validate that a file path points to a supported image file
    
    Args:
        file_path: Path to the image file
        
    Returns:
        bool: True if file exists and has supported extension
    """
    if not os.path.exists(file_path):
        return False
    
    # Get file extension
    _, ext = os.path.splitext(file_path.lower())
    
    # Check against supported formats
    supported_exts = ['.tiff', '.tif', '.h5', '.dat']
    return ext in supported_exts


def get_image_info(image_data) -> dict:
    """
    Extract basic information from image data
    
    Args:
        image_data: Image data array or Data2DScattering object
        
    Returns:
        dict: Image information including shape, dtype, etc.
    """
    if hasattr(image_data, 'data'):
        # Data2DScattering object
        data = image_data.data
    else:
        # Raw numpy array
        data = image_data
    
    if data is None:
        return {}
    
    info = {
        'shape': data.shape,
        'dtype': str(data.dtype),
        'size_mb': data.nbytes / (1024 * 1024),
        'min_value': float(np.min(data)),
        'max_value': float(np.max(data)),
        'mean_value': float(np.mean(data)),
        'std_value': float(np.std(data))
    }
    
    return info


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        str: Formatted size string
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def safe_float_conversion(value: str, default: float = 0.0) -> float:
    """
    Safely convert string to float with fallback
    
    Args:
        value: String value to convert
        default: Default value if conversion fails
        
    Returns:
        float: Converted value or default
    """
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return default


def validate_coordinate_input(x_text: str, y_text: str) -> Tuple[bool, Optional[Tuple[float, float]], str]:
    """
    Validate coordinate input strings
    
    Args:
        x_text: X coordinate as string
        y_text: Y coordinate as string
        
    Returns:
        tuple: (is_valid, (x, y) or None, error_message)
    """
    try:
        x = float(x_text.strip())
        y = float(y_text.strip())
        
        if not (np.isfinite(x) and np.isfinite(y)):
            return False, None, "Coordinates must be finite numbers"
        
        return True, (x, y), ""
        
    except ValueError:
        return False, None, "Invalid coordinate format"


def create_backup_filename(original_path: str, suffix: str = "_backup") -> str:
    """
    Create a backup filename for a given file path
    
    Args:
        original_path: Original file path
        suffix: Suffix to add before extension
        
    Returns:
        str: Backup file path
    """
    base, ext = os.path.splitext(original_path)
    return f"{base}{suffix}{ext}"


def ensure_directory_exists(file_path: str) -> bool:
    """
    Ensure that the directory for a file path exists
    
    Args:
        file_path: Path to file (directory will be created)
        
    Returns:
        bool: True if directory exists or was created successfully
    """
    try:
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        return True
    except (OSError, PermissionError):
        return False