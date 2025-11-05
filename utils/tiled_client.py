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
        """Extract image data from scan based on profile structure"""
        try:
            if profile.get('data_structure') == 'h.primary.data[detector_name].read()':
                # Specific data structure: h.primary.data['detector_name'].read()
                if not hasattr(scan_data, 'primary'):
                    print("Error: No primary data stream found")
                    return None
                
                primary_data = scan_data.primary
                if not hasattr(primary_data, 'data'):
                    print("Error: No data found in primary stream")
                    return None
                
                if detector not in primary_data.data:
                    available_detectors = list(primary_data.data.keys())
                    print(f"Error: Detector '{detector}' not found. Available: {available_detectors}")
                    return None
                
                image_array = primary_data.data[detector].read()
                
            else:
                # Standard tiled structure
                if detector in scan_data:
                    detector_data = scan_data[detector]
                    if hasattr(detector_data, 'read'):
                        image_array = detector_data.read()
                    else:
                        print(f"Error: Cannot read data from detector: {detector}")
                        return None
                else:
                    available_streams = list(scan_data.keys()) if hasattr(scan_data, 'keys') else []
                    print(f"Error: Detector '{detector}' not found. Available: {available_streams}")
                    return None
            
            return image_array
            
        except Exception as e:
            print(f"Error extracting image data: {e}")
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