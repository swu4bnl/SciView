"""
Utility functions for image handling and processing

This module provides common utilities for image loading, processing,
and data management.
"""

import os
import numpy as np
from typing import Optional, Tuple, Union

# Import configuration
from sciview.settings.app_settings import SUPPORTED_FORMATS


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


def validate_and_prepare_image_array(image_data, use_converter=True):
    """
    Validate and prepare image array for display, handling multiple input types.
    
    This comprehensive function handles:
    - SciAnalysis Data2DScattering objects (.data attribute extraction)
    - Tiled/memoryview (lazy-loaded) data
    - Stacked arrays (3D, 4D, 5D) - converts to 2D
    - Regular numpy arrays
    - Returns display-ready array or None with error message
    
    Args:
        image_data: Input image data (various types: ndarray, Data2DScattering, memoryview, etc.)
        use_converter: If True and array is not 2D, use ImageShapeConverter to convert (default: True)
        
    Returns:
        tuple: (display_array, is_valid, error_message)
            - display_array: 2D numpy array ready for imshow, or None if invalid
            - is_valid: Boolean success flag
            - error_message: String explaining any issues
    """
    if image_data is None:
        return None, False, "No image data provided"
    
    # Step 1: Extract data from wrapper objects (SciAnalysis, etc.)
    extracted_data = image_data
    
    # Handle SciAnalysis Data2DScattering object
    if hasattr(image_data, 'data'):
        extracted_data = image_data.data
        if extracted_data is None:
            return None, False, "SciAnalysis object has no data"
    
    # Step 2: Validate extracted data has array-like interface
    if not (hasattr(extracted_data, 'shape') and hasattr(extracted_data, 'ndim')):
        return None, False, f"Invalid data type (not array-like): {type(extracted_data).__name__}"
    
    # Step 3: Check for empty arrays (use shape to avoid .size issues with memoryview)
    try:
        if np.prod(extracted_data.shape) == 0:
            return None, False, f"Empty array with shape {extracted_data.shape}"
    except Exception:
        return None, False, f"Cannot determine array size from shape {extracted_data.shape}"
    
    # Step 4: Handle dimensionality
    if extracted_data.ndim == 2:
        # Always normalize to ndarray so downstream code can rely on NumPy APIs.
        try:
            normalized = np.asarray(extracted_data)
        except Exception as e:
            return None, False, f"Failed to convert 2D data to ndarray: {e}"
        return normalized, True, ""
    
    elif extracted_data.ndim > 2:
        # Multi-dimensional array (3D, 4D, 5D from stacked images, tiled, time series, etc.)
        if use_converter:
            try:
                converted = ImageShapeConverter.convert_to_2d(extracted_data)
                if converted is not None and converted.ndim == 2:
                    return converted, True, f"Converted {extracted_data.ndim}D array to 2D (shape={converted.shape})"
                else:
                    return None, False, f"Conversion failed for {extracted_data.ndim}D array"
            except Exception as e:
                return None, False, f"Error converting array: {str(e)}"
        else:
            return None, False, f"Array is {extracted_data.ndim}D, need 2D (use_converter=False)"
    
    else:  # ndim < 2
        return None, False, f"Array is {extracted_data.ndim}D, need at least 2D (shape={extracted_data.shape})"


class ImageShapeConverter:
    """
    Utility class for converting image arrays to standard 2D format
    
    Handles various input shapes and formats:
    - Multi-dimensional arrays → (H, W)
    - RGB/RGBA → Grayscale
    - Data type preservation (critical for memory efficiency)
    - Array view creation instead of copies where possible
    
    This class is reusable across all image-loading tabs and applications.
    """
    
    @staticmethod
    def convert_to_2d(image_array: np.ndarray) -> np.ndarray:
        """
        Convert image array to standard 2D format for display
        
        Handles various input shapes:
        - (1, 1, H, W) -> (H, W) - Single frame from tiled
        - (N, H, W) -> (H, W) - Time series, take first frame  
        - (H, W, 3) -> (H, W) - RGB to grayscale
        - (H, W, 4) -> (H, W) - RGBA to grayscale
        - (H, W) -> (H, W) - Already 2D, no change
        
        MEMORY EFFICIENCY:
        - Preserves original dtype (uint16/uint32) to avoid 4x memory inflation
        - Uses array views (reshape) instead of copies where possible
        - Avoids unnecessary temporary arrays
        
        Args:
            image_array: Input image array with arbitrary shape
            
        Returns:
            numpy.ndarray: 2D image array in original dtype
            
        Raises:
            ValueError: If conversion results in non-2D array
        """
        if image_array is None:
            return None
        
        # Convert to numpy array if not already
        if not isinstance(image_array, np.ndarray):
            image_array = np.array(image_array)
        
        original_shape = image_array.shape
        
        # Handle different dimensionalities
        if image_array.ndim == 2:
            # Already 2D - perfect, no conversion needed
            converted = image_array
            
        elif image_array.ndim == 3:
            # Three possibilities: (N, H, W), (H, W, 3), or (H, W, 4)
            if image_array.shape[2] in [3, 4]:
                # RGB or RGBA image: (H, W, 3/4) -> (H, W)
                # Note: np.dot creates temp array, unavoidable
                if image_array.shape[2] == 3:
                    # RGB to grayscale using standard weights
                    converted = np.dot(image_array[...,:3], [0.2989, 0.5870, 0.1140])
                else:  # RGBA
                    # RGBA to grayscale (ignore alpha channel)
                    converted = np.dot(image_array[...,:3], [0.2989, 0.5870, 0.1140])
            else:
                # Time series or stack: (N, H, W) -> (H, W)
                # Take the first frame - array view
                converted = image_array[0]
                
        elif image_array.ndim == 4:
            # Handle 4D arrays: (1, 1, H, W) or (N, 1, H, W) or (1, N, H, W) etc.
            if image_array.shape[0] == 1 and image_array.shape[1] == 1:
                # Single frame: (1, 1, H, W) -> (H, W)
                # Use reshape for view instead of indexing (which creates copies)
                converted = image_array.reshape(image_array.shape[2:])
            elif image_array.shape[0] == 1:
                # (1, N, H, W) -> take first
                converted = image_array[0, 0]
            elif image_array.shape[1] == 1:
                # (N, 1, H, W) -> take first
                converted = image_array[:, 0]
                converted = converted[0]
            else:
                # (N, M, H, W) -> take first frame
                converted = image_array[0, 0]
                
        elif image_array.ndim == 5:
            # Handle 5D arrays: try to extract 2D frame intelligently
            # Common pattern: (N, M, frames, H, W) where most dimensions are 1
            shape = image_array.shape
            
            # Find the two largest dimensions (likely H and W)
            dims_by_size = sorted(enumerate(shape), key=lambda x: x[1], reverse=True)
            
            if len(dims_by_size) >= 2:
                # Take the two largest dimensions and flatten everything else
                largest_idx = dims_by_size[0][0]
                second_largest_idx = dims_by_size[1][0]
                
                # Try to extract a 2D slice
                try:
                    converted = image_array.reshape(image_array.shape[largest_idx], image_array.shape[second_largest_idx])
                except:
                    # Fallback: take first elements of small dimensions and last large dimension
                    converted = image_array[0, 0, 0, :, :]
            else:
                converted = image_array[0, 0, 0]
            
        else:
            # Fallback: flatten extra dimensions using reshape for views
            try:
                temp = image_array
                while temp.ndim > 2:
                    if temp.ndim == 1:
                        # Can't go further with 1D
                        break
                    new_shape = (-1,) + temp.shape[1:]
                    temp = temp.reshape(new_shape)[0]
                converted = temp
            except Exception as e:
                # Last resort: just try to reshape to 2D
                try:
                    # Try to find two non-1 dimensions
                    non_one_dims = [i for i, s in enumerate(image_array.shape) if s > 1]
                    if len(non_one_dims) >= 2:
                        # Reshape to the two largest dimensions
                        converted = image_array.reshape(image_array.shape[non_one_dims[0]], 
                                                       image_array.shape[non_one_dims[1]])
                    else:
                        # Fall back to flattening to largest two dimensions
                        converted = image_array.reshape(-1, -1) if image_array.size > 0 else None
                except:
                    raise ValueError(f"Cannot convert array with shape {image_array.shape} to 2D: {e}")
        
        # Handle None case
        if converted is None:
            raise ValueError(f"Conversion resulted in None for input shape {image_array.shape}")
        
        # Ensure we have a 2D array
        if converted.ndim != 2:
            # One more attempt: if we have extra dimensions, try to flatten them
            if converted.ndim > 2:
                converted = converted.reshape(converted.shape[0], -1)
            elif converted.ndim == 1:
                # Cannot convert 1D to 2D meaningfully
                raise ValueError(f"Failed to convert to 2D: resulting shape is {converted.shape} - input too small")
            else:
                raise ValueError(f"Failed to convert to 2D: resulting shape is {converted.shape}")
        
        return converted


class ImageCacheManager:
    """
    Manages cached image data with LRU (Least Recently Used) eviction
    
    Features:
    - LRU cache eviction to limit memory usage
    - Configurable cache size
    - On-demand data loading support
    - Automatic cleanup and garbage collection
    
    This class is reusable across all tabs that need to cache image data.
    
    Example usage:
        cache = ImageCacheManager(cache_limit=5)
        cache.add_callback(self._on_cache_changed)
        cache.put('image_key', image_data)
        data = cache.get('image_key')
    """
    
    def __init__(self, cache_limit: int = 5):
        """
        Initialize cache manager
        
        Args:
            cache_limit: Maximum number of items to cache (default: 5)
        """
        self.data_cache = {}  # {key: data}
        self.cache_limit = cache_limit
        self.cache_access_order = []  # Track LRU order
        self.callbacks = []  # Callbacks for cache changes
    
    def get(self, key: str, loader_callback=None) -> Optional[np.ndarray]:
        """
        Get cached data, loading on-demand if callback provided
        
        Args:
            key: Cache key (e.g., file path or scan ID)
            loader_callback: Optional callback to load data if not cached
                           Signature: loader_callback(key) -> data
                           
        Returns:
            Cached data or None if not found and no loader provided
        """
        # Check if already cached
        if key in self.data_cache:
            self._track_access(key)
            return self.data_cache[key]
        
        # Try to load on-demand if callback provided
        if loader_callback:
            try:
                data = loader_callback(key)
                if data is not None:
                    self.put(key, data)
                    return data
            except Exception as e:
                print(f"Error loading data for {key}: {e}")
        
        return None
    
    def put(self, key: str, data: np.ndarray) -> None:
        """
        Add data to cache
        
        Args:
            key: Cache key
            data: Data to cache
        """
        if data is None:
            return
        
        self.data_cache[key] = data
        self._track_access(key)
        self._trim_cache()
        self._notify_callbacks()
    
    def remove(self, key: str) -> None:
        """Remove item from cache"""
        if key in self.data_cache:
            del self.data_cache[key]
            if key in self.cache_access_order:
                self.cache_access_order.remove(key)
            self._notify_callbacks()
    
    def clear(self) -> None:
        """Clear all cached data"""
        self.data_cache.clear()
        self.cache_access_order.clear()
        self._notify_callbacks()
    
    def get_cache_info(self) -> dict:
        """Get cache status information"""
        return {
            'cached_items': len(self.data_cache),
            'cache_limit': self.cache_limit,
            'memory_mb': sum(d.nbytes / (1024 * 1024) for d in self.data_cache.values()) if self.data_cache else 0
        }
    
    def add_callback(self, callback) -> None:
        """Add callback for cache changes"""
        self.callbacks.append(callback)
    
    def _track_access(self, key: str) -> None:
        """Track access for LRU eviction"""
        if key in self.cache_access_order:
            self.cache_access_order.remove(key)
        self.cache_access_order.append(key)
    
    def _trim_cache(self) -> None:
        """Remove least recently used items when exceeding limit"""
        import gc
        
        while len(self.data_cache) > self.cache_limit:
            if self.cache_access_order:
                # Remove least recently used
                lru_key = self.cache_access_order.pop(0)
                if lru_key in self.data_cache:
                    del self.data_cache[lru_key]
            else:
                # Fallback
                self.data_cache.pop(next(iter(self.data_cache)))
        
        # Explicitly trigger GC for evicted items
        gc.collect()
    
    def _notify_callbacks(self) -> None:
        """Notify all callbacks of cache changes"""
        for callback in self.callbacks:
            try:
                callback(self)
            except Exception as e:
                print(f"Cache callback error: {e}")