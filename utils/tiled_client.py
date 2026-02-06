"""
Tiled Client Manager Module

This module provides a reusable, centralized interface for tiled client operations.
It handles authentication, connection persistence, and data loading from beamline
tiled servers in a beamline-agnostic way.
"""

import os
import sys
import numpy as np
from typing import Optional, Dict, Any, Tuple, List

# Try to import tiled for beamline data access
try:
    from tiled.client import from_uri
    TILED_AVAILABLE = True
except ImportError:
    TILED_AVAILABLE = False
    print("Warning: Tiled not available - tiled operations disabled")

# Import configuration
from config.beamline_config import TILED_PROFILES, get_default_tiled_settings


class TiledClientManager:
    """
    Centralized manager for tiled client operations
    
    Provides:
    - Persistent authenticated connections
    - Configuration-driven defaults
    - Beamline-agnostic interface
    - Error handling and validation
    """
    
    def __init__(self):
        self._clients = {}  # Cache for authenticated clients: {profile_name: client}
        self._current_profile = None
        
    def is_available(self) -> bool:
        """Check if tiled is available for use"""
        return TILED_AVAILABLE
    
    def get_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Get all available tiled profiles from configuration"""
        return TILED_PROFILES
    
    def get_default_settings(self) -> Tuple[Optional[str], Optional[str]]:
        """Get default profile and detector from configuration"""
        return get_default_tiled_settings()
    
    def get_or_create_client(self, profile_name: Optional[str] = None) -> Optional[Any]:
        """
        Get existing authenticated client or create new one
        
        Args:
            profile_name: Tiled profile to use, uses default if None
            
        Returns:
            Authenticated tiled client or None if failed
        """
        if not TILED_AVAILABLE:
            return None
        
        # Use default profile if none specified
        if profile_name is None:
            profile_name, _ = get_default_tiled_settings()
            if profile_name is None:
                return None
        
        # Check if we have a cached client for this profile
        if profile_name in self._clients:
            client = self._clients[profile_name]
            if self._is_client_valid(client):
                return client
            else:
                # Remove invalid client
                del self._clients[profile_name]
        
        # Create new client
        return self._create_new_client(profile_name)
    
    def _is_client_valid(self, client) -> bool:
        """Test if client connection is still valid"""
        try:
            # Try a simple operation to verify connection
            if hasattr(client, 'metadata'):
                return True
            return False
        except Exception:
            return False
    
    def _create_new_client(self, profile_name: str) -> Optional[Any]:
        """Create and authenticate new tiled client"""
        if profile_name not in TILED_PROFILES:
            print(f"Error: Unknown tiled profile: {profile_name}")
            return None
        
        profile = TILED_PROFILES[profile_name]
        
        try:
            # Connect to tiled server
            client = from_uri(profile['uri'])
            
            # Login if required
            if profile.get('requires_login', False):
                try:
                    client.login()
                except Exception as e:
                    print(f"Authentication failed for {profile_name}: {e}")
                    return None
            
            # Cache the authenticated client
            self._clients[profile_name] = client
            self._current_profile = profile_name
            
            return client
            
        except Exception as e:
            print(f"Failed to connect to tiled server {profile_name}: {e}")
            return None
    
    def load_image_data(self, scan_id: int, detector: Optional[str] = None, 
                       profile_name: Optional[str] = None) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """
        Load image data from tiled server
        
        Args:
            scan_id: Scan ID to load
            detector: Detector name, uses default if None
            profile_name: Tiled profile to use, uses default if None
            
        Returns:
            Tuple of (image_array, metadata) or (None, error_info)
        """
        if not TILED_AVAILABLE:
            return None, {'error': 'Tiled client not available'}
        
        # Get defaults from configuration
        if profile_name is None:
            profile_name, default_detector = get_default_tiled_settings()
            if profile_name is None:
                return None, {'error': 'No tiled profiles configured'}
        else:
            _, default_detector = get_default_tiled_settings()
        
        if detector is None:
            detector = default_detector
            if detector is None:
                return None, {'error': 'No default detector configured'}
        
        # Get client
        client = self.get_or_create_client(profile_name)
        if client is None:
            return None, {'error': f'Failed to connect to tiled server: {profile_name}'}
        
        try:
            # Get profile configuration
            profile = TILED_PROFILES[profile_name]
            
            # Navigate to the correct catalog path
            catalog = client
            for path_segment in profile['path']:
                catalog = catalog[path_segment]
            
            # Get scan data
            if scan_id not in catalog:
                available_scans = list(catalog.keys())[:10]  # Show first 10 for debugging
                return None, {'error': f'Scan ID {scan_id} not found. Recent scans: {available_scans}'}
            
            scan_data = catalog[scan_id]
            
            # Get start document for metadata
            start_doc = scan_data.start
            metadata = {
                'scan_id': scan_id,
                'detector': detector,
                'uid': start_doc.get('uid', 'unknown'),
                'time': start_doc.get('time', 0),
                'profile': profile_name,
                'plan_name': start_doc.get('plan_name', 'unknown'),
                'uri': profile['uri'],
                'path': profile['path']
            }
            
            # Load image data based on profile structure
            image_array = self._extract_image_data(scan_data, detector, profile)
            
            if image_array is None:
                return None, {'error': f'Failed to extract image data for detector: {detector}'}
            
            return image_array, metadata
            
        except Exception as e:
            return None, {'error': f'Tiled loading error: {str(e)}'}
    
    def _extract_image_data(self, scan_data, detector: str, profile: Dict[str, Any]) -> Optional[np.ndarray]:
        """
        Extract image data from scan by navigating data_access_path from config.
        
        The data_access_path is a list of keys/attributes to navigate, with {detector}
        as a placeholder for the detector name:
        
        Examples:
        - cms/raw:        ['primary', 'data', '{detector}'] -> scan.primary.data[detector]
        - cms/migration:  ['primary', '{detector}']         -> scan.primary[detector]
        - standard tiled: ['{detector}']                    -> scan[detector]
        
        Args:
            scan_data: Root scan object from tiled
            detector: Detector name to substitute for {detector} placeholder
            profile: Profile configuration containing 'data_access_path'
            
        Returns:
            numpy.ndarray or None: Image array, or None if extraction failed
        """
        try:
            # Get data access path from profile (falls back to standard if not specified)
            data_access_path = profile.get('data_access_path', ['{detector}'])
            
            # Replace {detector} placeholder in path
            resolved_path = [p.replace('{detector}', detector) for p in data_access_path]
            
            # Navigate through the path
            current_obj = scan_data
            for i, segment in enumerate(resolved_path):
                # Get available keys for error reporting
                available = []
                if hasattr(current_obj, 'keys'):
                    try:
                        available = list(current_obj.keys())
                    except:
                        available = []
                
                # Try dict-like access first (for primary.data[detector])
                try:
                    if segment in current_obj:
                        current_obj = current_obj[segment]
                        continue
                except (TypeError, KeyError):
                    pass
                
                # Then try attribute access (for scan.primary)
                if hasattr(current_obj, segment):
                    current_obj = getattr(current_obj, segment)
                else:
                    # Build readable path for error message
                    path_so_far = '.'.join(resolved_path[:i]) if i > 0 else 'root'
                    print(f"Error: Cannot access '{segment}' in path {data_access_path}")
                    print(f"  Path so far: {path_so_far}")
                    print(f"  Available at this level: {available}")
                    return None
            
            # Extract the data by calling .read() if available
            if hasattr(current_obj, 'read'):
                image_array = current_obj.read()
            else:
                # If it's already a numpy array
                image_array = current_obj
            
            # Log successful extraction
            path_str = '/'.join(resolved_path)
            print(f"DEBUG: [_extract_image_data] Path '{path_str}' -> shape={image_array.shape}, dtype={image_array.dtype}")
            return image_array
            
        except Exception as e:
            print(f"Error extracting image data from path '{profile.get('data_access_path', 'unknown')}': {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_available_detectors(self, profile_name: Optional[str] = None) -> List[str]:
        """Get list of available detectors for a profile"""
        if profile_name is None:
            profile_name, _ = get_default_tiled_settings()
            if profile_name is None:
                return []
        
        if profile_name in TILED_PROFILES:
            profile = TILED_PROFILES[profile_name]
            return list(profile.get('default_detectors', {}).keys())
        
        return []
    
    def get_profile_info(self, profile_name: Optional[str] = None) -> Dict[str, Any]:
        """Get detailed information about a tiled profile"""
        if profile_name is None:
            profile_name, _ = get_default_tiled_settings()
            if profile_name is None:
                return {}
        
        if profile_name in TILED_PROFILES:
            profile = TILED_PROFILES[profile_name].copy()
            profile['profile_name'] = profile_name
            return profile
        
        return {}
    
    def create_pseudo_path(self, scan_id: int, detector: str, 
                          profile_name: Optional[str] = None) -> str:
        """Create a pseudo file path for tiled data tracking"""
        if profile_name is None:
            profile_name, _ = get_default_tiled_settings()
        
        if profile_name and profile_name in TILED_PROFILES:
            profile = TILED_PROFILES[profile_name]
            return f"tiled://{profile['uri']}/{'/'.join(profile['path'])}/{scan_id}/{detector}"
        
        return f"tiled://unknown/{scan_id}/{detector}"
    
    def clear_cache(self):
        """Clear all cached clients (force re-authentication)"""
        self._clients.clear()
        self._current_profile = None
    
    def get_cached_profiles(self) -> List[str]:
        """Get list of profiles with cached authenticated clients"""
        return list(self._clients.keys())


# Global instance for shared use across the application
tiled_manager = TiledClientManager()