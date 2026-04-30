"""
Image Browser Tab Module

This module contains the ImageBrowserApp class which provides comprehensive
image loading, browsing, and management functionality with multiple data sources.
"""

import os
import sys
import numpy as np
import glob
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QComboBox, QLineEdit, QSpinBox,
    QGroupBox, QTabWidget, QProgressBar, QCheckBox, QSplitter,
    QFileDialog, QMessageBox, QScrollArea, QGridLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap, QIcon

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)

# Import base class and configuration
from tabs.base_image_tab import BaseImageTab
from config.beamline_config import (
    DEFAULT_CALIBRATION, PHYSICAL_CONSTANTS, get_file_status, SUPPORTED_FORMATS,
    SCIANALYSIS_AVAILABLE
)
from config.app_style import *

# Import centralized tiled client manager
from utils.tiled_client import tiled_manager

# Import shared utilities
from utils.image_utils import ImageShapeConverter, ImageCacheManager


# Compatibility shim for older SciAnalysis code paths that still reference
# deprecated NumPy aliases removed in NumPy 2.x.
if not hasattr(np, "float"):
    np.float = float
if not hasattr(np, "int"):
    np.int = int
if not hasattr(np, "bool"):
    np.bool = bool
if not hasattr(np, "complex"):
    np.complex = complex


class ImageLoadWorker(QThread):
    """Background worker for loading images without blocking UI"""
    tiled_manager = tiled_manager

    progress_updated = pyqtSignal(int, str)  # progress, status message
    image_loaded = pyqtSignal(object, str, dict)   # image_data, file_path, metadata
    loading_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)
    
    def __init__(self, load_method, **kwargs):
        super().__init__()
        self.load_method = load_method
        self.kwargs = kwargs
        self.is_cancelled = False
    
    def run(self):
        """Execute the loading operation in background"""
        try:
            if self.load_method == 'folder':
                self._load_from_folder()
            elif self.load_method == 'tiled':
                self._load_from_tiled()
            elif self.load_method == 'file':
                self._load_single_file()
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self.loading_finished.emit()
    
    def cancel(self):
        """Cancel the loading operation"""
        self.is_cancelled = True
    
    def _load_from_folder(self):
        """Load images from folder with pattern matching using deferred loading.
        
        Creates file references without loading data into memory. This allows
        efficient handling of large image collections. Data is loaded on-demand
        when each image is accessed.
        """
        folder_path = self.kwargs['folder_path']
        pattern = self.kwargs['pattern']
        
        # Find matching files
        search_pattern = os.path.join(folder_path, pattern)
        file_paths = glob.glob(search_pattern)
        file_paths.sort()  # Sort for consistent ordering
        
        total_files = len(file_paths)
        self.progress_updated.emit(0, f"Found {total_files} matching files")
        
        # Get parent reference if available to add images to session
        # Note: This worker doesn't directly access session manager
        # Images are added via the image_loaded signal which the parent handles
        for i, file_path in enumerate(file_paths):
            if self.is_cancelled:
                break
            
            # Emit reference without loading data - parent will add as deferred reference
            self.image_loaded.emit(None, file_path)  # None signals this is a reference only
            
            # Update progress
            progress = int((i + 1) * 100 / total_files)
            self.progress_updated.emit(progress, f"Added {i+1}/{total_files}: {os.path.basename(file_path)}")
    
    def _load_from_tiled(self):
        """Load images from tiled client using scan ID (single or range)"""
        if not self.tiled_manager.is_available():
            self.error_occurred.emit("Tiled client is not available")
            return
        
        # Use configuration-based defaults from the manager
        default_profile, default_detector = self.tiled_manager.get_default_settings()
        
        profile_name = self.kwargs.get('profile', default_profile)
        scan_id = self.kwargs.get('scan_id')
        scan_range = self.kwargs.get('scan_range')  # Tuple (start, end) if loading range
        detector = self.kwargs.get('detector', default_detector)
        
        # Determine if loading single scan or range
        if scan_range is not None:
            # Load multiple scans in range
            start_id, end_id = scan_range
            total_scans = end_id - start_id + 1
            loaded_count = 0
            skipped_count = 0
            processed_count = 0
            
            for current_scan_id in range(start_id, end_id + 1):
                if self.is_cancelled:
                    self.progress_updated.emit(100, f"Cancelled: Loaded {loaded_count}, skipped {skipped_count} of {processed_count} scans")
                    break
                
                processed_count += 1
                progress = int((processed_count / total_scans) * 100)
                self.progress_updated.emit(progress, f"Scan {current_scan_id}: loaded={loaded_count}, skipped={skipped_count}/{processed_count}")
                
                try:
                    # Attempt to load this scan
                    image_array, metadata = self.tiled_manager.load_image_data(
                        scan_id=current_scan_id,
                        detector=detector,
                        profile_name=profile_name
                    )
                    
                    if image_array is not None:
                        image_array = self._convert_image_shape(image_array)
                        pseudo_path = self.tiled_manager.create_pseudo_path(current_scan_id, detector, profile_name)
                        
                        # Prepare metadata for session tracking
                        image_metadata = {
                            'scan_id': current_scan_id,
                            'detector': detector,
                            'profile': profile_name,
                            'tiled_metadata': metadata
                        }
                        
                        self.image_loaded.emit(image_array, pseudo_path, image_metadata)
                        loaded_count += 1
                    else:
                        # Scan not found or detector missing - skip quietly
                        skipped_count += 1
                        error_msg = metadata.get('error', 'Unknown')
                        if 'not found' not in error_msg.lower():
                            # Only log non-trivial errors
                            print(f"Skipped scan {current_scan_id}: {error_msg}")
                        
                except Exception as e:
                    skipped_count += 1
                    print(f"Skipped scan {current_scan_id}: {e}")
                    
            if not self.is_cancelled:
                self.progress_updated.emit(100, f"Complete: Loaded {loaded_count}, skipped {skipped_count} of {total_scans} scans")
            
        else:
            # Load single scan
            try:
                self.progress_updated.emit(10, f"Connecting to tiled server: {profile_name}")
                
                # Use centralized tiled manager for loading
                image_array, metadata = self.tiled_manager.load_image_data(
                    scan_id=scan_id,
                    detector=detector,
                    profile_name=profile_name
                )
                
                if image_array is None:
                    error_msg = metadata.get('error', 'Unknown tiled loading error')
                    # Check if it's a "not found" error vs connection error
                    if 'not found' in error_msg.lower():
                        self.error_occurred.emit(f"Scan {scan_id} not found in catalog")
                    else:
                        self.error_occurred.emit(error_msg)
                    return
                
                self.progress_updated.emit(80, "Reading image data...")
                
                # Convert image shape for display compatibility
                image_array = self._convert_image_shape(image_array)
                
                self.progress_updated.emit(90, "Processing image data...")
                
                # Create pseudo file path for tracking with metadata
                pseudo_path = self.tiled_manager.create_pseudo_path(scan_id, detector, profile_name)
                
                # Prepare metadata for session tracking
                image_metadata = {
                    'scan_id': scan_id,
                    'detector': detector,
                    'profile': profile_name,
                    'tiled_metadata': metadata
                }
                
                # Emit the loaded image with metadata
                self.image_loaded.emit(image_array, pseudo_path, image_metadata)
                self.progress_updated.emit(100, f"Tiled loading complete - Scan {scan_id}")
                
            except Exception as e:
                self.error_occurred.emit(f"Tiled loading error: {str(e)}")
                import traceback
                print(f"Detailed tiled error: {traceback.format_exc()}")
    
    def _load_single_file(self):
        """Load a single image file"""
        file_path = self.kwargs['file_path']
        
        try:
            self.progress_updated.emit(50, f"Loading {os.path.basename(file_path)}")
            image_data = self._load_image_file(file_path)
            
            if image_data is not None:
                # File loading doesn't have Tiled metadata
                file_metadata = {'source': 'file'}
                self.image_loaded.emit(image_data, file_path, file_metadata)
                self.progress_updated.emit(100, "File loading complete")
            else:
                self.error_occurred.emit(f"Failed to load image from {file_path}")
                
        except Exception as e:
            self.error_occurred.emit(f"Error loading file: {str(e)}")
    
    def _load_image_file(self, file_path):
        """Load image data from file path with shape conversion"""
        try:
            # Check if SciAnalysis is available for proper loading
            try:
                from SciAnalysis.XSAnalysis.Data import Data2DScattering
                image_data = Data2DScattering(file_path)
                return self._convert_image_shape(image_data.data if hasattr(image_data, 'data') else image_data)
            except ImportError:
                # Fallback to basic image loading
                try:
                    from PIL import Image
                    image_array = np.array(Image.open(file_path))
                    return self._convert_image_shape(image_array)
                except ImportError:
                    # Final fallback using matplotlib
                    import matplotlib.image as mpimg
                    image_array = mpimg.imread(file_path)
                    return self._convert_image_shape(image_array)
        except Exception as e:
            print(f"Error loading image file {file_path}: {e}")
            return None
    
    def _convert_image_shape(self, image_array):
        """
        Convert image array to standard 2D format using shared utility
        
        This method now delegates to the shared ImageShapeConverter utility
        for consistency across all image-loading tabs and applications.
        
        Args:
            image_array: Input image array with arbitrary shape
            
        Returns:
            numpy.ndarray: 2D image array suitable for analysis
        """
        return ImageShapeConverter.convert_to_2d(image_array)


class ImageSessionManager:
    """
    Manages the list of images loaded in the current session.
    
    Combines image metadata tracking with the shared ImageCacheManager
    for deferred data loading and LRU cache eviction.
    
    Features:
    - Lazy loading: images referenced without loading data immediately
    - LRU caching: automatic eviction of least-recently-used images
    - Session tracking: maintains current image index and metadata
    - Callbacks: notifies UI of session changes
    """
    
    def __init__(self, cache_limit: int = 5):
        self.images = []  # List of image metadata dicts
        self.current_index = -1
        self.callbacks = []  # Callbacks for when image list changes
        
        # Use shared cache manager for data caching
        self.cache_manager = ImageCacheManager(cache_limit=cache_limit)
        self.cache_manager.add_callback(self._on_cache_changed)
    
    def add_image(self, image_data, file_path, metadata=None, lazy=False):
        """Add an image to the session with optional deferred data loading.
        
        Args:
            image_data: Image data array. Can be None if lazy=True to defer loading.
            file_path: Path or identifier for the image.
            metadata: Optional metadata dict for image properties.
            lazy: If True, stores only the reference without loading data into memory.
        """
        image_info = {
            'path': file_path,
            'filename': self._extract_display_filename(file_path, metadata),
            'timestamp': np.datetime64('now'),
            'metadata': metadata or {},
            'size': image_data.shape if (image_data is not None and hasattr(image_data, 'shape')) else None,
            'source': self._determine_source(file_path),
            'lazy': lazy,
            'cache_key': file_path  # Use path as cache key
        }
        
        index = len(self.images)
        self.images.append(image_info)
        
        # Add to cache if not lazy
        if not lazy and image_data is not None:
            self.cache_manager.put(file_path, image_data)
        
        self.current_index = index
        self._notify_callbacks()
    
    def add_image_reference(self, file_path, metadata=None, estimated_size=None):
        """Add an image reference without loading data (deferred loading)."""
        self.add_image(None, file_path, metadata=metadata, lazy=True)
        if estimated_size:
            self.images[-1]['size'] = estimated_size
    
    def get_current_image(self, load_data=False, loader_callback=None):
        """Get the currently selected image with optional on-demand loading."""
        if 0 <= self.current_index < len(self.images):
            img = self.images[self.current_index].copy()
            
            # Trigger on-demand loading if data is needed
            if load_data:
                if loader_callback:
                    # Use shared cache manager's get method
                    # The loader_callback will be called if data is not in cache
                    loaded_data = self.cache_manager.get(img['cache_key'], 
                                                        loader_callback=lambda k: loader_callback(img['path'], img['metadata']))
                    if loaded_data is not None:
                        if img['size'] is None and hasattr(loaded_data, 'shape'):
                            img['size'] = loaded_data.shape
                            self.images[self.current_index]['size'] = loaded_data.shape
                        img['data'] = loaded_data
                    else:
                        # Loader returned None (loading failed)
                        img['data'] = None
                else:
                    # No loader callback provided, just try to get from cache
                    img['data'] = self.cache_manager.get(img['cache_key'])
            
            return img
        return None
    
    def set_current_index(self, index):
        """Set the current image by index"""
        if 0 <= index < len(self.images):
            self.current_index = index
            self._notify_callbacks()
            return True
        return False
    
    def remove_image(self, index):
        """Remove an image from the session"""
        if 0 <= index < len(self.images):
            # Remove from cache
            cache_key = self.images[index]['cache_key']
            self.cache_manager.remove(cache_key)
            
            self.images.pop(index)
            if self.current_index >= len(self.images):
                self.current_index = len(self.images) - 1
            elif self.current_index > index:
                self.current_index -= 1
            self._notify_callbacks()
    
    def clear_session(self):
        """Clear all images from session"""
        self.images.clear()
        self.cache_manager.clear()
        self.current_index = -1
        self._notify_callbacks()
    
    def get_cache_info(self):
        """Get cache information from shared cache manager"""
        info = self.cache_manager.get_cache_info()
        info['total_images'] = len(self.images)
        return info
    
    def get_image_list(self):
        """Get list of all images in session"""
        return [img['filename'] for img in self.images]
    
    def add_callback(self, callback):
        """Add callback for session changes"""
        self.callbacks.append(callback)
    
    def _on_cache_changed(self, cache_manager):
        """Handle cache changes from shared manager"""
        # Propagate cache changes to session callbacks
        for callback in self.callbacks:
            try:
                callback(self)
            except Exception as e:
                print(f"Callback error: {e}")
    
    def _notify_callbacks(self):
        """Notify all callbacks of session changes"""
        for callback in self.callbacks:
            try:
                callback(self)
            except Exception as e:
                print(f"Callback error: {e}")
    
    def _determine_source(self, file_path):
        """Determine the source type of the image"""
        if file_path.startswith('tiled://'):
            return 'tiled'
        elif os.path.isfile(file_path):
            return 'file'
        else:
            return 'unknown'
    
    def _extract_display_filename(self, file_path, metadata=None):
        """Extract a meaningful display filename from path and metadata.
        
        For Tiled images, extracts scan ID from metadata.
        For file paths, extracts basename.
        """
        if file_path.startswith('tiled://') and metadata:
            # Extract scan_id from metadata for Tiled images
            scan_id = metadata.get('scan_id')
            detector = metadata.get('detector', 'unknown')
            if scan_id is not None:
                return f"Scan {scan_id} ({detector})"
        
        # Default: use filename for regular files
        return os.path.basename(file_path)


class ImageBrowserApp(BaseImageTab):
    """Image Browser application widget with multiple loading options"""
    
    def __init__(self, parent_app):
        super().__init__(parent_app)
        
        # Session manager for image tracking
        self.session_manager = ImageSessionManager()
        self.session_manager.add_callback(self._on_session_changed)
        
        # Loading worker
        self.load_worker = None
        self.is_batch_loading = False  # Flag to prevent display updates during batch operations
        
        # Tiled client cache for persistent connections
        self.tiled_manager = tiled_manager
        self.tiled_client = None
        self.current_tiled_profile = None
        
        # Monitor timer for automatic loading
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self._monitor_check)
        self.last_loaded_scan_id = None
        self.is_monitoring = False
        
        # Build UI
        self._build_ui()
        
        # Connect to parent app for synchronization
        self._setup_parent_sync()

    def update_display_settings(self, **kwargs):
        """Override to update display settings and refresh current image in browser
        
        When display settings (vmin, vmax, cmap, scale) change, we need to
        refresh the current image being displayed in the image browser.
        """
        self.display_settings.update(kwargs)
        
        # Refresh current image with new display settings
        if hasattr(self, '_update_display'):
            self._update_display()

    def _build_ui(self):
        """Build the main user interface"""
        # Main layout with splitter
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Main horizontal splitter: visualization | controls
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Left panel: Image visualization with navigation
        visualization_panel = self._create_image_browser_panel()
        main_splitter.addWidget(visualization_panel)

        # Right panel: Image loading options (upper) and session management (lower)
        control_splitter = QSplitter(Qt.Vertical)
        loading_panel = self._create_loading_panel()
        control_splitter.addWidget(loading_panel)

        session_panel = self._create_session_panel()
        control_splitter.addWidget(session_panel)

        # Use consistent layout ratios from global style config
        layout_ratios = AppStyle.get_layout_ratios()
        setup_splitter_layout(control_splitter, layout_ratios['browser_controls_ratio'])

        main_splitter.addWidget(control_splitter)
        # Set main splitter to match other tabs: 3:1 visualization to controls
        setup_splitter_layout(main_splitter, layout_ratios['main_splitter_ratio'])
        
        main_layout.addWidget(main_splitter)
        main_layout.addStretch()

    def _create_loading_panel(self):
        """Create the loading options panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Title
        title = QLabel("Image Loading Options")
        apply_title_style(title)
        layout.addWidget(title)
        
        # Loading methods tabs
        self.loading_tabs = QTabWidget()
        
        # Tab 1: File loading
        file_tab = self._create_file_loading_tab()
        self.loading_tabs.addTab(file_tab, "Files")

        # Tab 2: Folder browser
        folder_tab = self._create_folder_loading_tab()
        self.loading_tabs.addTab(folder_tab, "Folder")
        
        # Tab 3: Tiled client
        tiled_tab = self._create_tiled_loading_tab()
        self.loading_tabs.addTab(tiled_tab, "Tiled")
        
        # Tab 4: Tiled monitor
        monitor_tab = self._create_tiled_monitor_tab()
        self.loading_tabs.addTab(monitor_tab, "Tiled Monitor")
        
        # Disable Tiled tabs if Tiled is not available
        if not self.tiled_manager.is_available():
            self.loading_tabs.setTabEnabled(2, False)  # Disable Tiled tab
            self.loading_tabs.setTabEnabled(3, False)  # Disable Tiled Monitor tab
        
        # Connect checkbox signals for UI control disabling
        # When "Load all files" is checked, disable the "Max" field
        self.load_all_checkbox.stateChanged.connect(self._update_folder_controls)
        # When "Load single scan only" is checked, disable the "End" field
        self.single_scan_checkbox.stateChanged.connect(self._update_tiled_controls)
        
        # Set initial states
        self._update_folder_controls()
        self._update_tiled_controls()
        
        layout.addWidget(self.loading_tabs)
        
        # Progress bar and cancel button
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)
        
        self.cancel_load_button = QPushButton("Cancel")
        self.cancel_load_button.setVisible(False)
        self.cancel_load_button.clicked.connect(self._cancel_loading)
        self.cancel_load_button.setMaximumWidth(80)
        progress_layout.addWidget(self.cancel_load_button)
        layout.addLayout(progress_layout)
        
        # Status label
        self.loading_status_label = QLabel("Ready to load images")
        apply_info_style(self.loading_status_label)
        layout.addWidget(self.loading_status_label)
        
        layout.addStretch()
        return panel

    def _create_file_loading_tab(self):
        """Create file loading tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Single file button
        btn_single_file = QPushButton("Load Single Image")
        btn_single_file.clicked.connect(self._load_single_file)
        layout.addWidget(btn_single_file)
        
        # Multiple files button
        btn_multiple_files = QPushButton("Load Multiple Images")
        btn_multiple_files.clicked.connect(self._load_multiple_files)
        layout.addWidget(btn_multiple_files)
        
        # Recent files list
        layout.addWidget(QLabel("Recent Files:"))
        self.recent_files_list = QListWidget()
        self.recent_files_list.setMaximumHeight(150)
        self.recent_files_list.itemDoubleClicked.connect(self._load_recent_file)
        layout.addWidget(self.recent_files_list)
        
        layout.addStretch()
        return tab

    def _create_tiled_loading_tab(self):
        """Create tiled client loading tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Profile selection
        layout.addWidget(QLabel("Tiled Profile:"))
        self.tiled_profile_combo = QComboBox()
        
        # Populate with available profiles
        for profile_name, profile_info in tiled_manager.get_profiles().items():
            self.tiled_profile_combo.addItem(f"{profile_name} - {profile_info['description']}", profile_name)
        
        # Set default to first available profile from config
        default_profile, _ = tiled_manager.get_default_settings()
        
        if default_profile:
            default_index = self.tiled_profile_combo.findData(default_profile)
            if default_index >= 0:
                self.tiled_profile_combo.setCurrentIndex(default_index)
        
        self.tiled_profile_combo.currentTextChanged.connect(self._on_profile_changed)
        layout.addWidget(self.tiled_profile_combo)
        
        # Scan ID range input
        scan_id_layout = QHBoxLayout()
        layout.addWidget(QLabel("Scan ID Range:"))
        
        self.scan_id_start_input = QSpinBox()
        self.scan_id_start_input.setRange(-9999999, 9999999)
        self.scan_id_start_input.setPrefix("Start: ")
        # Use configuration-based default instead of hardcoded value
        from config.beamline_config import IMAGE_BROWSER_SETTINGS
        self.scan_id_start_input.setValue(IMAGE_BROWSER_SETTINGS['default_scan_id'])
        scan_id_layout.addWidget(self.scan_id_start_input)
        
        self.scan_id_end_input = QSpinBox()
        self.scan_id_end_input.setRange(-9999999, 9999999)
        self.scan_id_end_input.setPrefix("End: ")
        self.scan_id_end_input.setValue(IMAGE_BROWSER_SETTINGS['default_scan_id'])
        scan_id_layout.addWidget(self.scan_id_end_input)
        
        layout.addLayout(scan_id_layout)
        
        # Single scan ID checkbox for backward compatibility
        self.single_scan_checkbox = QCheckBox("Load single scan only")
        self.single_scan_checkbox.setChecked(True)
        layout.addWidget(self.single_scan_checkbox)
        
        # Detector selection
        layout.addWidget(QLabel("Detector:"))
        self.detector_combo = QComboBox()
        self._populate_detectors()  # Populate based on current profile
        layout.addWidget(self.detector_combo)
        
        # Load button
        btn_load_tiled = QPushButton("Load from Tiled")
        btn_load_tiled.clicked.connect(self._load_from_tiled)
        layout.addWidget(btn_load_tiled)

        # Connection status
        self.tiled_status_label = QLabel("Status: Ready to connect")
        apply_info_style(self.tiled_status_label)
        layout.addWidget(self.tiled_status_label)
        
        # Profile info display
        self.tiled_info_label = QLabel()
        self.tiled_info_label.setWordWrap(True)
        apply_info_style(self.tiled_info_label)
        self._update_profile_info()
        layout.addWidget(self.tiled_info_label)
        
        layout.addStretch()

        return tab
        

    def _create_tiled_monitor_tab(self):
        """Create tiled monitor tab for live monitoring"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Monitor function controls - separate in a group box
        monitor_group = QGroupBox("Live Monitor Mode")
        monitor_layout = QVBoxLayout()
        
        self.monitor_button = QPushButton("Start Monitor")
        self.monitor_button.setCheckable(True)
        self.monitor_button.clicked.connect(self._toggle_monitor)
        monitor_layout.addWidget(self.monitor_button)
        
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Interval:"))
        self.monitor_interval_input = QSpinBox()
        self.monitor_interval_input.setRange(1, 300)
        self.monitor_interval_input.setValue(5)
        self.monitor_interval_input.setSuffix(" sec")
        interval_layout.addWidget(self.monitor_interval_input)
        interval_layout.addStretch()
        monitor_layout.addLayout(interval_layout)
        
        self.monitor_status_label = QLabel("Monitor: Inactive")
        apply_info_style(self.monitor_status_label)
        monitor_layout.addWidget(self.monitor_status_label)
        
        monitor_group.setLayout(monitor_layout)
        layout.addWidget(monitor_group)
        
        # Connection status
        self.tiled_status_label = QLabel("Status: Ready to connect")
        apply_info_style(self.tiled_status_label)
        layout.addWidget(self.tiled_status_label)
        
        # Profile info display
        self.tiled_info_label = QLabel()
        self.tiled_info_label.setWordWrap(True)
        apply_info_style(self.tiled_info_label)
        self._update_profile_info()
        layout.addWidget(self.tiled_info_label)
        
        layout.addStretch()
        return tab

    def _create_folder_loading_tab(self):
        """Create folder browsing tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Folder selection
        folder_layout = QHBoxLayout()
        self.folder_path_input = QLineEdit()
        self.folder_path_input.setPlaceholderText("Select folder...")
        folder_layout.addWidget(self.folder_path_input)
        
        btn_browse_folder = QPushButton("Browse")
        btn_browse_folder.clicked.connect(self._browse_folder)
        folder_layout.addWidget(btn_browse_folder)
        layout.addLayout(folder_layout)
        
        # File pattern
        layout.addWidget(QLabel("File Pattern:"))
        self.pattern_input = QLineEdit("*.tiff")
        self.pattern_input.setPlaceholderText("e.g., *.tiff, *saxs*.tif, sample_*.h5")
        layout.addWidget(self.pattern_input)
        
        # Preview matching files
        btn_preview = QPushButton("Preview File Names")
        btn_preview.clicked.connect(self._preview_folder_files)
        layout.addWidget(btn_preview)
        
        # File list preview
        self.folder_files_list = QListWidget()
        self.folder_files_list.setMaximumHeight(100)
        layout.addWidget(self.folder_files_list)
        
        # Load options
        load_options_layout = QHBoxLayout()
        self.load_all_checkbox = QCheckBox("Load all files")
        self.load_all_checkbox.setChecked(True)
        load_options_layout.addWidget(self.load_all_checkbox)
        
        self.max_files_input = QSpinBox()
        self.max_files_input.setRange(1, 999999)
        self.max_files_input.setValue(50)
        self.max_files_input.setPrefix("Max: ")
        load_options_layout.addWidget(self.max_files_input)
        layout.addLayout(load_options_layout)
        
        # Load button
        btn_load_folder = QPushButton("Load from Folder")
        btn_load_folder.clicked.connect(self._load_from_folder)
        layout.addWidget(btn_load_folder)
        
        layout.addStretch()
        return tab

    def _create_image_browser_panel(self):
        """Create image browser panel that extends the base image panel with navigation controls"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Navigation header
        header_layout = QHBoxLayout()
        title = QLabel("Image Browser")
        apply_title_style(title)
        header_layout.addWidget(title)
        
        # Navigation controls
        self.prev_button = QPushButton("◀ Prev")
        self.prev_button.clicked.connect(self._prev_image)
        self.prev_button.setEnabled(False)
        header_layout.addWidget(self.prev_button)
        
        self.image_counter_label = QLabel("0 / 0")
        header_layout.addWidget(self.image_counter_label)
        
        self.next_button = QPushButton("Next ▶")
        self.next_button.clicked.connect(self._next_image)
        self.next_button.setEnabled(False)
        header_layout.addWidget(self.next_button)
        
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Current image info
        self.current_image_label = QLabel("No image loaded")
        apply_info_style(self.current_image_label)
        self.current_image_label.setMaximumHeight(30)
        layout.addWidget(self.current_image_label)
        
        # Use the base class image panel
        base_image_panel = self._create_image_panel()
        base_image_panel.setMinimumHeight(400)
        layout.addWidget(base_image_panel)
        
        # Sync button - the only Image Browser specific control
        self.sync_button = QPushButton("Use This Image")
        self.sync_button.setToolTip("Send current image to other tabs in the main application")
        apply_sync_button_style(self.sync_button)
        self.sync_button.setFixedHeight(60)
        self.sync_button.clicked.connect(self._sync_to_parent)
        self.sync_button.setEnabled(False)
        layout.addWidget(self.sync_button)

        return panel

    def _create_session_panel(self):
        """Create session management panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Title and controls
        header_layout = QHBoxLayout()
        title = QLabel("Session Images")
        apply_title_style(title)
        header_layout.addWidget(title)
        
        btn_clear_session = QPushButton("Clear")
        btn_clear_session.clicked.connect(self._clear_session)
        header_layout.addWidget(btn_clear_session)
        layout.addLayout(header_layout)
        
        # Image list table
        self.session_table = QTableWidget()
        self.session_table.setColumnCount(3)
        self.session_table.setHorizontalHeaderLabels(["Filename", "Source", "Size"])
        self.session_table.horizontalHeader().setStretchLastSection(True)
        self.session_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.session_table.itemSelectionChanged.connect(self._on_session_selection_changed)
        self.session_table.setMinimumHeight(250)
        layout.addWidget(self.session_table, 1)
        
        # Session info
        self.session_info_label = QLabel("0 images loaded")
        apply_info_style(self.session_info_label)
        layout.addWidget(self.session_info_label)
        
        # Export options
        export_layout = QHBoxLayout()
        btn_export_list = QPushButton("Export List")
        btn_export_list.clicked.connect(self._export_session_list)
        export_layout.addWidget(btn_export_list)
        
        btn_export_data = QPushButton("Export Data")
        btn_export_data.clicked.connect(self._export_session_data)
        export_layout.addWidget(btn_export_data)
        layout.addLayout(export_layout)

        layout.addStretch()
        
        return panel

    # Loading Methods
    def _load_single_file(self):
        """Load a single image file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Image", "", SUPPORTED_FORMATS['image_files']
        )
        
        if file_path:
            self._start_loading('file', file_path=file_path)

    def _load_multiple_files(self):
        """Load multiple image files with deferred data loading.
        
        Creates references for each selected file without loading data immediately.
        This approach is memory-efficient for large file batches. Data is loaded
        on-demand when the user navigates to each image.
        """
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Load Images", "", SUPPORTED_FORMATS['image_files']
        )
        
        if file_paths:
            # Enter batch loading mode to prevent display updates for each reference
            self.is_batch_loading = True
            
            # Create references without loading data
            for file_path in file_paths:
                self.session_manager.add_image_reference(file_path)
            
            # Exit batch loading mode and trigger final display update
            self.is_batch_loading = False
            self._update_display()
            
            self.loading_status_label.setText(f"Added {len(file_paths)} files to session")
            self.parent_app.show_status(f"Imported {len(file_paths)} file references")

    def _load_from_tiled(self):
        """Load image(s) from tiled client - single or range"""
        current_data = self.tiled_profile_combo.currentData()
        # Use config-based default instead of hardcoded
        from config.beamline_config import get_default_tiled_settings
        default_profile, _ = get_default_tiled_settings()
        profile = current_data if current_data else default_profile
        detector = self.detector_combo.currentText()
        
        # Extract detector key if it's in "key - description" format
        if ' - ' in detector:
            detector = detector.split(' - ')[0]
        
        if self.single_scan_checkbox.isChecked():
            # Load single scan
            scan_id = self.scan_id_start_input.value()
            self._start_loading('tiled', profile=profile, scan_id=scan_id, detector=detector)
        else:
            # Load scan range - use eager loading with skip to avoid adding bad references
            start_id = self.scan_id_start_input.value()
            end_id = self.scan_id_end_input.value()
            
            if start_id > end_id:
                QMessageBox.warning(self, "Invalid Range", "Start scan ID must be <= End scan ID")
                return
            
            # Use worker to load range (it will skip scans without data)
            self._start_loading('tiled', profile=profile, scan_range=(start_id, end_id), detector=detector)

    def _on_profile_changed(self):
        """
        Handle profile selection change
        
        Performance optimization: Load and cache raw catalog once when profile is selected
        This avoids the one-time cost during actual data loading
        """
        profile_name = self.tiled_profile_combo.currentData()
        
        # Preload the raw catalog for this profile (one-time cost at profile selection)
        if profile_name:
            print(f"DEBUG: Preloading catalog for profile '{profile_name}'...")
            catalog = self.tiled_manager.get_or_load_catalog(profile_name)
            if catalog:
                self.parent_app.show_status(f"✓ Catalog cached for '{profile_name}'")
            else:
                self.parent_app.show_status(f"⚠ Could not preload catalog for '{profile_name}'")
        
        # Update UI
        self._populate_detectors()
        self._update_profile_info()
    
    def _populate_detectors(self):
        """Populate detector list based on selected profile"""
        current_data = self.tiled_profile_combo.currentData()
        # Use config-based default instead of hardcoded
        from config.beamline_config import get_default_tiled_settings
        default_profile, _ = get_default_tiled_settings()
        profile_name = current_data if current_data else default_profile
        
        profiles = self.tiled_manager.get_profiles()
        if profile_name in profiles:
            profile = profiles[profile_name]
            self.detector_combo.clear()
            
            for detector_key, detector_desc in profile['default_detectors'].items():
                self.detector_combo.addItem(f"{detector_key} - {detector_desc}")
    
    def _update_profile_info(self):
        """Update profile information display"""
        current_data = self.tiled_profile_combo.currentData()
        # Use config-based default instead of hardcoded
        from config.beamline_config import get_default_tiled_settings
        default_profile, _ = get_default_tiled_settings()
        profile_name = current_data if current_data else default_profile
        
        profiles = self.tiled_manager.get_profiles()
        if profile_name in profiles:
            profile = profiles[profile_name]
            info_text = f"URI: {profile['uri']}\n"
            info_text += f"Path: /{'/'.join(profile['path'])}\n"
            info_text += f"Login required: {'Yes' if profile.get('requires_login') else 'No'}\n"
            info_text += f"Scan range: {profile['scan_id_range'][0]}-{profile['scan_id_range'][1]}"
            self.tiled_info_label.setText(info_text)

    def _load_from_folder(self):
        """Load images from folder with pattern matching and deferred data loading.
        
        Scans folder for matching files and creates references without loading data.
        Ideal for working with large image collections. Data loads on-demand during
        browsing to keep memory footprint minimal.
        """
        folder_path = self.folder_path_input.text()
        pattern = self.pattern_input.text()
        
        if not folder_path or not pattern:
            QMessageBox.warning(self, "Input Required", "Please select folder and pattern")
            return
        
        # Find matching files
        search_pattern = os.path.join(folder_path, pattern)
        file_paths = glob.glob(search_pattern)
        file_paths.sort()  # Sort for consistent ordering
        
        if not file_paths:
            QMessageBox.warning(self, "No Files Found", f"No files matching pattern '{pattern}' found in folder")
            return
        
        # Limit files if needed
        if not self.load_all_checkbox.isChecked():
            max_files = self.max_files_input.value()
            file_paths = file_paths[:max_files]
        
        # Enter batch loading mode to prevent display updates for each reference
        self.is_batch_loading = True
        
        # Create references without loading data
        for file_path in file_paths:
            self.session_manager.add_image_reference(file_path)
        
        # Exit batch loading mode and trigger final display update
        self.is_batch_loading = False
        self._update_display()
        
        self.loading_status_label.setText(f"Added {len(file_paths)} files to session")
        self.parent_app.show_status(f"Imported {len(file_paths)} file references from folder")

    def _start_loading(self, method, **kwargs):
        """Start background loading operation"""
        if self.load_worker and self.load_worker.isRunning():
            self.load_worker.cancel()
            self.load_worker.wait()
        
        # Enter batch loading mode for folder and tiled range operations
        if method in ['folder', 'tiled'] and 'scan_range' in kwargs:
            self.is_batch_loading = True
        
        self.load_worker = ImageLoadWorker(method, **kwargs)
        self.load_worker.progress_updated.connect(self._on_loading_progress)
        self.load_worker.image_loaded.connect(self._on_image_loaded)
        self.load_worker.loading_finished.connect(self._on_loading_finished)
        self.load_worker.error_occurred.connect(self._on_loading_error)
        
        self.progress_bar.setVisible(True)
        self.cancel_load_button.setVisible(True)
        self.progress_bar.setValue(0)
        self.load_worker.start()
    
    def _cancel_loading(self):
        """Cancel the current loading operation"""
        if self.load_worker and self.load_worker.isRunning():
            self.load_worker.cancel()
            self.loading_status_label.setText("Loading cancelled by user")
            self.parent_app.show_status("Loading operation cancelled")

    # Event Handlers
    def _on_loading_progress(self, progress, message):
        """Handle loading progress updates"""
        self.progress_bar.setValue(progress)
        self.loading_status_label.setText(message)

    def _on_image_loaded(self, image_data, file_path, metadata=None):
        """Handle successful image loading - add to session appropriately.
        
        If image_data is None, this is a deferred reference (from folder loading).
        Otherwise, this is actual loaded data from single file or Tiled loading.
        
        Args:
            image_data: The loaded image data array, or None for deferred loading
            file_path: Path or identifier for the image
            metadata: Optional metadata dict (e.g., scan_id, detector for Tiled images)
        """
        if image_data is None:
            # This is a deferred reference - add without data
            self.session_manager.add_image_reference(file_path, metadata=metadata)
        else:
            # This is actual image data - add with data immediately
            self.session_manager.add_image(image_data, file_path, metadata=metadata)
            # Update display for eagerly loaded images
            self._update_display()

    def _on_loading_finished(self):
        """Handle loading completion"""
        self.progress_bar.setVisible(False)
        self.cancel_load_button.setVisible(False)
        self.loading_status_label.setText("Loading complete")
        
        # End batch loading mode and trigger display update for final state
        if self.is_batch_loading:
            self.is_batch_loading = False
            self._update_display()

    def _on_loading_error(self, error_message):
        """Handle loading errors"""
        self.progress_bar.setVisible(False)
        self.cancel_load_button.setVisible(False)
        self.loading_status_label.setText(f"Error: {error_message}")
        QMessageBox.warning(self, "Loading Error", error_message)

    def _on_session_changed(self, session_manager):
        """Handle session changes"""
        self._update_session_table()
        self._update_navigation_controls()
        # Only update display if we're not in the middle of batch loading
        # This prevents triggering data loads for every reference added
        if not self.is_batch_loading:
            self._update_display()

    def _update_session_table(self):
        """Update the session table display"""
        images = self.session_manager.images
        self.session_table.setRowCount(len(images))
        
        for row, img in enumerate(images):
            # Filename
            self.session_table.setItem(row, 0, QTableWidgetItem(img['filename']))
            
            # Source
            self.session_table.setItem(row, 1, QTableWidgetItem(img['source']))
            
            # Size
            size_str = f"{img['size'][0]}x{img['size'][1]}" if img['size'] else "Unknown"
            self.session_table.setItem(row, 2, QTableWidgetItem(size_str))
        
        # Update info label
        self.session_info_label.setText(f"{len(images)} images loaded")

    def _update_navigation_controls(self):
        """Update navigation button states"""
        count = len(self.session_manager.images)
        current = self.session_manager.current_index
        
        self.prev_button.setEnabled(current > 0)
        self.next_button.setEnabled(current < count - 1)
        self.sync_button.setEnabled(count > 0)
        
        if count > 0:
            self.image_counter_label.setText(f"{current + 1} / {count}")
        else:
            self.image_counter_label.setText("0 / 0")

    def _update_display(self):
        """Update the image display with on-demand data loading.
        
        Retrieves the current image with deferred loading support. If the image
        data hasn't been loaded yet, triggers the loader callback to fetch and
        cache it. Displays placeholder while loading is in progress.
        
        MEMORY EFFICIENCY:
        - Passes image data directly to update_plot() without storing in self.image_data
        - This prevents holding unnecessary references and allows proper garbage collection
        - Data is only kept in the session manager's LRU cache, which enforces memory limits
        - Explicitly triggers garbage collection when switching between images
        """
        import gc
        
        # Get current image, triggering on-demand loading if needed
        current_image = self.session_manager.get_current_image(
            load_data=True, 
            loader_callback=self._lazy_load_callback
        )
        
        if current_image is None:
            self.ax_raw.clear()
            self.ax_raw.text(0.5, 0.5, 'No Image Loaded', 
                        transform=self.ax_raw.transAxes, ha='center', va='center')
            self.current_image_label.setText("No image loaded")
            self.canvas_raw.draw()
            return
        
        # Check if data is available (might still be None if loading failed)
        if current_image['data'] is None:
            self.ax_raw.clear()
            self.ax_raw.text(0.5, 0.5, f"Loading: {current_image['filename']}", 
                        transform=self.ax_raw.transAxes, ha='center', va='center')
            self.current_image_label.setText(f"Loading: {current_image['filename']}")
            self.canvas_raw.draw()
            return
        
        # Extract data and other info from current_image dict
        # Do this before calling update_plot to minimize local references
        image_data = current_image['data']
        filename = current_image['filename']
        source = current_image['source']
        
        # Pass image data directly to update_plot() without storing in self.image_data
        # This avoids unnecessary references and improves memory efficiency
        self.update_plot(image_data)
        
        # Set title and update current image label
        self.ax_raw.set_title(filename, fontsize=10)
        self.current_image_label.setText(f"File: {filename} | Source: {source}")
        
        # Final canvas refresh
        self.canvas_raw.draw()
        
        # Explicitly trigger garbage collection to clean up evicted cached images
        # This is important when switching between images in the session
        gc.collect()
    
    def _lazy_load_callback(self, path, metadata):
        """Load image data on-demand when accessed.
        
        Called by the session manager when an image with deferred loading is accessed
        for the first time, or when a cached image has been evicted.
        Handles loading from both file paths and Tiled data sources.
        Result is automatically cached by the session manager.
        
        Args:
            path: File path or Tiled pseudo-path identifier.
            metadata: Metadata dict containing Tiled connection details if applicable.
            
        Returns:
            Loaded image data array (2D), or None if loading fails.
        """
        try:
            if path.startswith('tiled://'):
                # Load from tiled using metadata
                scan_id = metadata.get('scan_id')
                detector = metadata.get('detector')
                profile = metadata.get('profile')
                
                if scan_id is not None:
                    image_array, load_metadata = self.tiled_manager.load_image_data(
                        scan_id=scan_id,
                        detector=detector,
                        profile_name=profile
                    )
                    
                    if image_array is not None:
                        # Use the existing worker's conversion method
                        worker = ImageLoadWorker('file', file_path='')
                        return worker._convert_image_shape(image_array)
                    else:
                        error_msg = load_metadata.get('error', 'Unknown error')
                        print(f"Failed to load tiled scan {scan_id}: {error_msg}")
                        return None
            else:
                # Load from file
                worker = ImageLoadWorker('file', file_path='')
                return worker._load_image_file(path)
                
        except Exception as e:
            print(f"Error in lazy load callback: {e}")
            return None

    def _sync_to_parent(self):
        """Sync current image to parent application and other tabs
        
        IMPORTANT: For compatibility with tabs that expect SciAnalysis objects,
        this method loads the image data into memory (not deferred). The returned
        image from session_manager is a copy, so we must load_data=True to get
        the actual array content.
        """
        # MUST load_data=True to actually get the image data (not just the reference)
        current_image = self.session_manager.get_current_image(
            load_data=True,
            loader_callback=self._lazy_load_callback
        )
        if current_image is None or current_image['data'] is None:
            return
        
        # Convert numpy array to SciAnalysis Data2DScattering object if needed
        try:
            image_data_obj = self._convert_to_scianalysis_format(current_image['data'], current_image['path'])
            
            print(f"DEBUG: Converted image data type: {type(image_data_obj)}")
            if hasattr(image_data_obj, 'circular_average_q_bin'):
                print("DEBUG: Object has SciAnalysis methods")
            else:
                print("DEBUG: Object is numpy array (SciAnalysis not available)")
                
        except Exception as e:
            print(f"DEBUG: Error in SciAnalysis conversion: {e}")
            # Fall back to raw numpy array
            image_data_obj = current_image['data']
        
        # Update parent app state
        self.parent_app.image_data = image_data_obj
        self.parent_app.image_path = current_image['path']
        
        # Trigger updates in other tabs if they exist
        for i in range(self.parent_app.tab_widget.count()):
            tab = self.parent_app.tab_widget.widget(i)
            if tab != self:  # Skip self (Image Browser tab)
                try:
                    # For calibration, mask, and protocol tabs: set self.image_data first
                    # These tabs expect self.image_data to be set before calling update_plot()
                    if hasattr(tab, 'image_data'):
                        tab.image_data = image_data_obj
                    
                    # Call populate_image_info if available
                    if hasattr(tab, 'populate_image_info'):
                        tab.populate_image_info(image_data_obj, current_image['path'])
                    
                    # Call update_plot without parameter (uses self.image_data)
                    # This is compatible with calibration_tab, mask_tab, protocol_preview_tab
                    if hasattr(tab, 'update_plot'):
                        tab.update_plot()
                        
                except Exception as e:
                    print(f"DEBUG: Error updating tab {i}: {e}")
        
        self.parent_app.show_status(f"Synced image: {current_image['filename']}")
    
    def _convert_to_scianalysis_format(self, image_array, image_path):
        """Convert numpy array to SciAnalysis Data2DScattering object using beamline configuration"""
        # First check if SciAnalysis is available
        if not hasattr(self, 'scianalysis_available') or not self.scianalysis_available:
            print("DEBUG: SciAnalysis not available, returning raw numpy array")
            return image_array
        
        # Use the shared method from base class that properly handles measurement type detection
        # and applies the correct beamline configuration (SAXS/WAXS/MAXS)
        try:
            result = self.create_data2d_object(image_array, image_path)
            # print(f"DEBUG: create_data2d_object returned: {type(result)}")
            return result
        except Exception as e:
            print(f"DEBUG: Error in create_data2d_object: {e}")
            return image_array

    # Navigation methods
    def _prev_image(self):
        """Navigate to previous image"""
        if self.session_manager.current_index > 0:
            self.session_manager.set_current_index(self.session_manager.current_index - 1)

    def _next_image(self):
        """Navigate to next image"""
        count = len(self.session_manager.images)
        if self.session_manager.current_index < count - 1:
            self.session_manager.set_current_index(self.session_manager.current_index + 1)

    def _on_session_selection_changed(self):
        """Handle selection change in session table"""
        current_row = self.session_table.currentRow()
        if current_row >= 0:
            self.session_manager.set_current_index(current_row)

    # Utility methods
    def _browse_folder(self):
        """Browse for folder"""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.folder_path_input.setText(folder)

    def _preview_folder_files(self):
        """Preview files in selected folder - fast, no loading"""
        folder_path = self.folder_path_input.text()
        pattern = self.pattern_input.text()
        
        if not folder_path or not pattern:
            return
        
        search_pattern = os.path.join(folder_path, pattern)
        file_paths = glob.glob(search_pattern)
        file_paths.sort()
        
        self.folder_files_list.clear()
        
        # Show limited preview
        max_preview = min(self.max_files_input.value() if not self.load_all_checkbox.isChecked() else len(file_paths), 100)
        
        for file_path in file_paths[:max_preview]:
            self.folder_files_list.addItem(os.path.basename(file_path))
        
        # Show summary
        if len(file_paths) > max_preview:
            self.folder_files_list.addItem(f"... and {len(file_paths) - max_preview} more files")

    def _update_folder_controls(self):
        """Update folder control states based on checkboxes"""
        # When "Load all files" is checked, disable the "Max" field
        is_load_all = self.load_all_checkbox.isChecked()
        self.max_files_input.setEnabled(not is_load_all)

    def _update_tiled_controls(self):
        """Update Tiled control states based on checkboxes"""
        # When "Load single scan only" is checked, disable the "End" field
        is_single_scan = self.single_scan_checkbox.isChecked()
        self.scan_id_end_input.setEnabled(not is_single_scan)

    def _clear_session(self):
        """Clear the session"""
        reply = QMessageBox.question(self, "Clear Session", 
                                   "Are you sure you want to clear all images from the session?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.session_manager.clear_session()

    def _export_session_list(self):
        """Export session file list"""
        if not self.session_manager.images:
            QMessageBox.information(self, "No Data", "No images in session to export")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Session List", "", "Text Files (*.txt)")
        if file_path:
            with open(file_path, 'w') as f:
                for img in self.session_manager.images:
                    f.write(f"{img['path']}\n")
            self.parent_app.show_status(f"Session list exported to {file_path}")

    def _export_session_data(self):
        """Export session data as HDF5 or similar"""
        # Placeholder for data export functionality
        QMessageBox.information(self, "Export Data", "Data export functionality to be implemented")

    def _setup_parent_sync(self):
        """Setup synchronization with parent application"""
        # This could include callbacks or signals to keep tabs in sync
        pass

    def _add_tab_specific_status(self, info_lines):
        """Add image browser specific status information"""
        info_lines.append("")
        info_lines.append("=== IMAGE BROWSER STATUS ===")
        info_lines.append(f"Session images: {len(self.session_manager.images)}")
        
        # Cache information
        cache_info = self.session_manager.get_cache_info()
        info_lines.append(f"Cached in memory: {cache_info['cached_images']}/{cache_info['total_images']} (limit: {cache_info['cache_limit']})")
        
        current_image = self.session_manager.get_current_image(load_data=False)
        if current_image:
            info_lines.append(f"Current: {current_image['filename']}")
            info_lines.append(f"Source: {current_image['source']}")
            # Show loading mode for developer context
            loading_mode = "Deferred (on-demand)" if current_image.get('lazy', False) else "Immediate (preloaded)"
            info_lines.append(f"Loading mode: {loading_mode}")
            if current_image['size']:
                info_lines.append(f"Dimensions: {current_image['size'][0]} x {current_image['size'][1]}")
        
        # Monitor status
        if self.is_monitoring:
            info_lines.append(f"Monitor: Active (last scan: {self.last_loaded_scan_id})")
        else:
            info_lines.append("Monitor: Inactive")

    def _load_recent_file(self, item):
        """Load a file from recent files list"""
        # Placeholder for recent files functionality
        pass
    
    def _toggle_monitor(self):
        """Toggle monitor mode on/off"""
        if self.monitor_button.isChecked():
            # Start monitoring
            self.is_monitoring = True
            interval_sec = self.monitor_interval_input.value()
            self.monitor_timer.start(interval_sec * 1000)  # Convert to milliseconds
            self.monitor_button.setText("Stop Monitor")
            self.monitor_status_label.setText(f"Monitor: Active (checking every {interval_sec}s)")
            self.parent_app.show_status(f"Monitor started - checking for new scans every {interval_sec}s")
        else:
            # Stop monitoring
            self.is_monitoring = False
            self.monitor_timer.stop()
            self.monitor_button.setText("Start Monitor")
            self.monitor_status_label.setText("Monitor: Inactive")
            self.parent_app.show_status("Monitor stopped")
    
    def _monitor_check(self):
        """Check for new scans in monitor mode (loads latest scan with scan_id=-1)"""
        if not self.is_monitoring:
            return
        
        try:
            current_data = self.tiled_profile_combo.currentData()
            from config.beamline_config import get_default_tiled_settings
            default_profile, _ = get_default_tiled_settings()
            profile = current_data if current_data else default_profile
            detector = self.detector_combo.currentText()
            
            # Extract detector key if it's in "key - description" format
            if ' - ' in detector:
                detector = detector.split(' - ')[0]
            
            # Use scan_id = -1 to get latest scan
            scan_id = -1
            
            # Attempt to load the latest scan
            image_array, metadata = self.tiled_manager.load_image_data(
                scan_id=scan_id,
                detector=detector,
                profile_name=profile
            )
            
            if image_array is not None:
                # Get actual scan ID from metadata if available
                actual_scan_id = metadata.get('scan_id', -1)
                
                # Check if this is a new scan (different from last loaded)
                if actual_scan_id != self.last_loaded_scan_id:
                    self.last_loaded_scan_id = actual_scan_id
                    
                    # Convert image shape
                    worker = ImageLoadWorker('file', file_path='')
                    image_array = worker._convert_image_shape(image_array)
                    
                    # Create pseudo path
                    pseudo_path = self.tiled_manager.create_pseudo_path(actual_scan_id, detector, profile)
                    
                    # Add to session
                    self.session_manager.add_image(image_array, pseudo_path, metadata=metadata)
                    
                    self.monitor_status_label.setText(f"Monitor: Active - Loaded scan {actual_scan_id}")
                    self.parent_app.show_status(f"Monitor: Auto-loaded scan {actual_scan_id}")
                else:
                    # Same scan as before, no new data
                    self.monitor_status_label.setText(f"Monitor: Active - No new data (last: {actual_scan_id})")
            else:
                # No data available or error
                error_msg = metadata.get('error', 'Unknown error')
                self.monitor_status_label.setText(f"Monitor: Active - No data available")
                # Don't spam errors, just log
                print(f"Monitor check: {error_msg}")
                
        except Exception as e:
            print(f"Monitor check error: {e}")
            self.monitor_status_label.setText(f"Monitor: Active - Error occurred")