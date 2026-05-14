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

# Compatibility shim for environments with older typing_extensions.
try:
    import typing_extensions as _typing_extensions
except Exception:
    _typing_extensions = None

if _typing_extensions is not None and not hasattr(_typing_extensions, "Sentinel"):
    class _CompatSentinel:
        def __init__(self, name: str, module_name: Optional[str] = None):
            self._name = name
            self._module_name = module_name

        def __repr__(self) -> str:
            return self._name

    _typing_extensions.Sentinel = _CompatSentinel

# Try to import tiled for beamline data access
try:
    from tiled.client import from_uri
    from tiled.queries import Key
    TILED_AVAILABLE = True
    TILED_IMPORT_ERROR = None
except ImportError as exc:
    TILED_AVAILABLE = False
    Key = None
    TILED_IMPORT_ERROR = f"Tiled import failed: {exc}"

# Import configuration
from config.beamline_config import TILED_PROFILES, get_default_tiled_settings


class TiledClientManager:
    """
    Centralized manager for tiled client operations
    
    Provides:
    - Persistent authenticated connections
    - Configuration-driven defaults
    - Beamline-agnostic interface
    - Catalog caching for performance (one-time load cost)
    - Scan ID to UID translation using Key queries
    - Error handling and validation
    """
    
    def __init__(self):
        self._clients = {}  # Cache for authenticated clients: {profile_name: client}
        self._catalogs = {}  # Cache for raw catalogs: {profile_name: catalog}
        self._current_profile = None
        
    def is_available(self) -> bool:
        """Check if tiled is available for use"""
        return TILED_AVAILABLE

    def get_import_error(self) -> Optional[str]:
        """Get the tiled import error message when tiled is unavailable."""
        return TILED_IMPORT_ERROR
    
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
    
    def get_or_load_catalog(self, profile_name: Optional[str] = None) -> Optional[Any]:
        """
        Get or load raw catalog for a profile (cached, one-time cost)
        
        This is a performance optimization: instead of navigating catalog path
        every time, we cache it once when user selects a profile from dropdown.
        
        Args:
            profile_name: Tiled profile to use, uses default if None
            
        Returns:
            Catalog object or None if failed
        """
        if not TILED_AVAILABLE:
            return None
        
        # Use default profile if none specified
        if profile_name is None:
            profile_name, _ = get_default_tiled_settings()
            if profile_name is None:
                return None
        
        # Check if already cached
        if profile_name in self._catalogs:
            return self._catalogs[profile_name]
        
        # Get client
        client = self.get_or_create_client(profile_name)
        if client is None:
            return None
        
        try:
            # Get profile configuration
            profile = TILED_PROFILES[profile_name]
            
            # Navigate to the correct catalog path (this is the one-time cost)
            catalog = client
            for path_segment in profile['path']:
                catalog = catalog[path_segment]
            
            # Cache the catalog for reuse
            self._catalogs[profile_name] = catalog
            print(f"DEBUG: [get_or_load_catalog] Loaded and cached catalog for profile '{profile_name}'")
            
            return catalog
            
        except Exception as e:
            print(f"Error loading catalog for profile {profile_name}: {e}")
            return None
    
    def scanid_to_uid(self, scan_id: int, profile_name: Optional[str] = None) -> Optional[str]:
        """
        Translate scan_id to uid using Key queries for fast metadata search
        
        This uses tiled's Key query interface instead of iterating through
        the catalog, which is much faster on large catalogs.
        
        Args:
            scan_id: Scan ID to look up
            profile_name: Tiled profile to use, uses default if None
            
        Returns:
            UID string or None if not found
        """
        if not TILED_AVAILABLE or Key is None:
            return None
        
        # Get catalog
        catalog = self.get_or_load_catalog(profile_name)
        if catalog is None:
            print(f"Error: Cannot load catalog for profile '{profile_name}'")
            return None
        
        try:
            # print(f"[DEBUG] catalog type: {type(catalog)}")
            # print(f"[DEBUG] catalog dir: {dir(catalog)}")
            # print(f"[DEBUG] Attempting catalog.search(Key('scan_id') == {scan_id})")
            # Use Key query to find scan by scan_id
            # Key("scan_id") targets the start.scan_id field
            result = catalog.search(Key("scan_id") == scan_id)
            # print(f"[DEBUG] result type: {type(result)}")
            # print(f"[DEBUG] result dir: {dir(result)}")
            
            # Get last (newest) result
            run = result.values().last()
            if run is None:
                print(f"Debug: Scan ID {scan_id} not found in catalog")
                return None
            
            # Extract UID from metadata
            uid = run.metadata.get("start", {}).get("uid")
            if uid:
                print(f"DEBUG: [scanid_to_uid] Scan {scan_id} -> UID {uid[:8]}...")
            
            return uid
            
        except Exception as e:
            print(f"[DEBUG] Exception in scanid_to_uid: {e}")
            print(f"Error translating scan_id {scan_id} to uid: {e}")
            return None
    
    
    def load_image_data(self, scan_id: int, detector: Optional[str] = None, 
                       profile_name: Optional[str] = None, use_uid_lookup: bool = True) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """
        Load image data from tiled server with performance optimization
        
        Performance strategy:
        1. One-time cost: get_or_load_catalog() caches raw catalog per profile
        2. Use Key queries to translate scan_id to uid (fast metadata search)
        3. Then access data via uid path
        
        Args:
            scan_id: Scan ID to load
            detector: Detector name, uses default if None
            profile_name: Tiled profile to use, uses default if None
            use_uid_lookup: If True, use Key queries for fast metadata lookup (default: True)
            
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
        
        try:
            # Strategy 1: Try UID-based lookup (optimized path)
            if use_uid_lookup and TILED_AVAILABLE and Key is not None:
                uid = self.scanid_to_uid(scan_id, profile_name)
                if uid:
                    return self._load_image_by_uid(uid, detector, profile_name)
            
            # Strategy 2: Fallback to scan_id-based lookup (uses cached catalog)
            print(f"DEBUG: [load_image_data] Falling back to scan_id lookup for scan {scan_id}")
            catalog = self.get_or_load_catalog(profile_name)
            if catalog is None:
                return None, {'error': f'Failed to load catalog for profile: {profile_name}'}
            
            # Get scan data by ID (leverages cached catalog)
            if scan_id not in catalog:
                available_scans = list(catalog.keys())[:10]
                return None, {'error': f'Scan ID {scan_id} not found. Recent: {available_scans}'}
            
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
                'uri': TILED_PROFILES[profile_name]['uri'],
                'path': TILED_PROFILES[profile_name]['path']
            }
            
            # Load image data based on profile structure
            profile = TILED_PROFILES[profile_name]
            image_array = self._extract_image_data(scan_data, detector, profile)
            
            if image_array is None:
                return None, {'error': f'Failed to extract image data for detector: {detector}'}
            
            return image_array, metadata
            
        except Exception as e:
            return None, {'error': f'Tiled loading error: {str(e)}'}
    
    def _load_image_by_uid(self, uid: str, detector: str, profile_name: str) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """
        Load image data using UID (optimized path)
        
        Args:
            uid: Unique ID of the scan
            detector: Detector name
            profile_name: Tiled profile name
            
        Returns:
            Tuple of (image_array, metadata) or (None, error_info)
        """
        try:
            client = self.get_or_create_client(profile_name)
            if client is None:
                return None, {'error': f'Failed to connect to tiled server: {profile_name}'}
            
            profile = TILED_PROFILES[profile_name]
            
            # Access run via uid directly: client[f"path/to/run/{uid}/primary"]
            run = client
            
            # Navigate to the path with uid
            for path_segment in profile['path']:
                run = run[path_segment]
            
            # Access the specific run by uid
            run = run[uid]
            
            # Get start document for metadata
            start_doc = run.start
            scan_id = start_doc.get("scan_id")
            
            metadata = {
                'scan_id': scan_id,
                'detector': detector,
                'uid': uid,
                'time': start_doc.get('time', 0),
                'profile': profile_name,
                'plan_name': start_doc.get('plan_name', 'unknown'),
                'uri': profile['uri'],
                'path': profile['path'],
                'lookup_method': 'uid'
            }
            
            # Load image data
            image_array = self._extract_image_data(run, detector, profile)
            
            if image_array is None:
                return None, {'error': f'Failed to extract image data for detector: {detector}'}
            
            print(f"DEBUG: [_load_image_by_uid] Successfully loaded via UID lookup")
            return image_array, metadata
            
        except Exception as e:
            print(f"Error loading image by UID {uid[:8]}...: {e}")
            return None, {'error': f'UID-based loading failed: {str(e)}'}
    
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