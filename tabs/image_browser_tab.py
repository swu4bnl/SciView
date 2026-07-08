"""
Image Browser Tab Module

This module contains the ImageBrowserApp class which provides comprehensive
image loading, browsing, and management functionality with multiple data sources.
"""

import os
import sys
import numpy as np
import glob
import fnmatch
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QComboBox, QLineEdit,
    QFileDialog, QMessageBox, QScrollArea, QGridLayout, QTableWidget, QSplitter,
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
from sciview.interfaces.theme.app_style import *
from sciview.settings.app_settings import SUPPORTED_FORMATS

# Import centralized tiled client manager
from sciview.sources.tiled_client import tiled_manager

# Import shared utilities
from sciview.interfaces.stable_qt.utils.image_utils import ImageShapeConverter, ImageCacheManager
from sciview.interfaces.stable_qt.utils.file_dialog_state import (
    dialog_save_file,
    dialog_select_directory,
)


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
    retry_detected = pyqtSignal(int, str)   # attempt number, message

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

    # ------------------------------------------------------------------
    # Tiled progress / retry callbacks (called from worker thread)
    # ------------------------------------------------------------------

    def _tiled_chunk_callback(self, chunks_done: int, total_chunks: int) -> None:
        """Called by TiledClientManager after each chunk download.

        Maps chunk progress (0..total) onto the 10-90 % range of the
        progress bar that is used for single-scan loads so the bar
        advances visibly as tiles arrive.
        """
        if total_chunks > 1:
            pct = 10 + int(chunks_done / total_chunks * 70)
        else:
            pct = 50 if chunks_done == 0 else 80

        label = (
            f"Reading tile {chunks_done}/{total_chunks}…"
            if total_chunks > 1
            else "Reading image data…"
        )
        self.progress_updated.emit(pct, label)

    def _tiled_retry_callback(self, attempt: int, message: str) -> None:
        """Called by TiledClientManager when the HTTP client retries a request."""
        self.retry_detected.emit(attempt, message)
    
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
            import_error = self.tiled_manager.get_import_error() or "unknown import error"
            self.error_occurred.emit(f"Tiled client is not available: {import_error}")
            return
        
        # Use configuration-based defaults from the manager
        default_profile, default_detector = self.tiled_manager.get_default_settings()
        
        profile_name = self.kwargs.get('profile', default_profile)
        scan_id = self.kwargs.get('scan_id')
        scan_range = self.kwargs.get('scan_range')  # Tuple (start, end) if loading range
        detector = self.kwargs.get('detector', default_detector)
        show_progress = self.kwargs.get('show_progress', True)

        # Build callback references (None when progress reporting is disabled)
        progress_cb = self._tiled_chunk_callback if show_progress else None
        retry_cb = self._tiled_retry_callback if show_progress else None

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
                        profile_name=profile_name,
                        progress_callback=progress_cb,
                        retry_callback=retry_cb,
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
                
                # Use centralized tiled manager for loading; pass progress/retry
                # callbacks so the bar advances as tiles arrive.
                image_array, metadata = self.tiled_manager.load_image_data(
                    scan_id=scan_id,
                    detector=detector,
                    profile_name=profile_name,
                    progress_callback=progress_cb,
                    retry_callback=retry_cb,
                )
                
                if image_array is None:
                    error_msg = metadata.get('error', 'Unknown tiled loading error')
                    # Check if it's a "not found" error vs connection error
                    if 'not found' in error_msg.lower():
                        self.error_occurred.emit(f"Scan {scan_id} not found in catalog")
                    else:
                        self.error_occurred.emit(error_msg)
                    return
                
                self.progress_updated.emit(90, "Processing image data...")
                
                # Convert image shape for display compatibility
                image_array = self._convert_image_shape(image_array)
                
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
        
        self.is_batch_loading = False  # Flag to prevent display updates during batch operations
        
        # Tiled manager is kept only for lazy-loading legacy tiled:// session refs.
        self.tiled_manager = tiled_manager

        self.folder_play_timer = QTimer(self)
        self.folder_play_timer.timeout.connect(self._advance_folder_playback)
        self.folder_refresh_timer = QTimer(self)
        self.folder_refresh_timer.setInterval(2000)
        self.folder_refresh_timer.timeout.connect(self._auto_refresh_folder_browser)
        self._folder_browser_paths = []
        
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
        
        folder_panel = self._create_folder_loading_tab()
        
        # Connect filter/sort signals for live folder browsing.
        self.folder_path_input.editingFinished.connect(self._refresh_folder_browser)
        self.folder_path_input.editingFinished.connect(self._update_folder_auto_refresh)
        self.pattern_input.textChanged.connect(self._refresh_folder_browser)
        self.folder_sort_combo.currentIndexChanged.connect(self._refresh_folder_browser)
        layout.addWidget(folder_panel)
        
        # Status label
        self.loading_status_label = QLabel("Ready to load images")
        apply_info_style(self.loading_status_label)
        layout.addWidget(self.loading_status_label)
        
        layout.addStretch()
        return panel

    def _create_folder_loading_tab(self):
        """Create folder browsing tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Folder selection
        folder_layout = QHBoxLayout()
        self.folder_path_input = QLineEdit()
        self.folder_path_input.setPlaceholderText("Select folder...")
        folder_layout.addWidget(self.folder_path_input)
        
        btn_browse_folder = QPushButton("Open Folder")
        btn_browse_folder.clicked.connect(self._browse_folder)
        folder_layout.addWidget(btn_browse_folder)
        layout.addLayout(folder_layout)
        
        layout.addWidget(QLabel("Filename Filter:"))
        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText("optional: saxs, *.tif, sample_*.h5")
        layout.addWidget(self.pattern_input)

        layout.addWidget(QLabel("Sort:"))
        self.folder_sort_combo = QComboBox()
        self.folder_sort_combo.addItem("Name A-Z", "name_asc")
        self.folder_sort_combo.addItem("Name Z-A", "name_desc")
        self.folder_sort_combo.addItem("Newest first", "mtime_desc")
        self.folder_sort_combo.addItem("Oldest first", "mtime_asc")
        layout.addWidget(self.folder_sort_combo)

        layout.addWidget(QLabel("Images:"))
        self.folder_files_list = QListWidget()
        self.folder_files_list.itemClicked.connect(self._open_folder_file)
        self.folder_files_list.itemActivated.connect(self._open_folder_file)
        layout.addWidget(self.folder_files_list, 1)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)
        toolbar_button_style = """
            QPushButton {
                font-size: 18px;
                font-weight: 600;
                min-width: 40px;
                max-width: 40px;
                min-height: 34px;
                max-height: 34px;
                padding: 0;
            }
            QPushButton:checked {
                background-color: #2f7d95;
                color: white;
            }
        """

        self.add_all_folder_button = QPushButton("+")
        self.add_all_folder_button.setToolTip("Add all visible folder images to the session")
        self.add_all_folder_button.setStyleSheet(toolbar_button_style)
        self.add_all_folder_button.clicked.connect(self._load_from_folder)
        controls_layout.addWidget(self.add_all_folder_button)

        self.folder_play_button = QPushButton("▶")
        self.folder_play_button.setToolTip("Play through the visible folder images")
        self.folder_play_button.setStyleSheet(toolbar_button_style)
        self.folder_play_button.setCheckable(True)
        self.folder_play_button.clicked.connect(self._toggle_folder_playback)
        controls_layout.addWidget(self.folder_play_button)

        self.folder_stop_button = QPushButton("■")
        self.folder_stop_button.setToolTip("Stop playback")
        self.folder_stop_button.setStyleSheet(toolbar_button_style)
        self.folder_stop_button.clicked.connect(self._stop_folder_playback)
        controls_layout.addWidget(self.folder_stop_button)

        self.folder_loop_button = QPushButton("∞")
        self.folder_loop_button.setToolTip("Loop playback")
        self.folder_loop_button.setCheckable(True)
        self.folder_loop_button.setStyleSheet(toolbar_button_style)
        controls_layout.addWidget(self.folder_loop_button)

        self.folder_auto_refresh_button = QPushButton("⟳")
        self.folder_auto_refresh_button.setToolTip("Refresh the folder list automatically when new images appear")
        self.folder_auto_refresh_button.setCheckable(True)
        self.folder_auto_refresh_button.setChecked(True)
        self.folder_auto_refresh_button.setStyleSheet(toolbar_button_style)
        self.folder_auto_refresh_button.toggled.connect(self._update_folder_auto_refresh)
        controls_layout.addWidget(self.folder_auto_refresh_button)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
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
    def _load_from_folder(self):
        """Import the current folder browser list as deferred session references."""
        self._stop_folder_playback()
        file_paths = self._get_folder_image_paths()

        if not file_paths:
            QMessageBox.warning(self, "No Files Found", "No supported image files found in this folder")
            return

        self.is_batch_loading = True

        for file_path in file_paths:
            self.session_manager.add_image_reference(str(file_path))

        self.is_batch_loading = False
        self._update_display()

        self.loading_status_label.setText(f"Added {len(file_paths)} files to session")
        self.parent_app.show_status(f"Imported {len(file_paths)} file references from folder")

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
        self.session_table.blockSignals(True)
        self.session_table.setRowCount(len(images))

        try:
            for row, img in enumerate(images):
                # Filename
                self.session_table.setItem(row, 0, QTableWidgetItem(img['filename']))

                # Source
                self.session_table.setItem(row, 1, QTableWidgetItem(img['source']))

                # Size
                size_str = f"{img['size'][0]}x{img['size'][1]}" if img['size'] else "Unknown"
                self.session_table.setItem(row, 2, QTableWidgetItem(size_str))

            current = self.session_manager.current_index
            if 0 <= current < len(images):
                self.session_table.selectRow(current)
            else:
                self.session_table.clearSelection()
        finally:
            self.session_table.blockSignals(False)
        
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
        
        # Publish via centralized shared-state API.
        if hasattr(self.parent_app, 'publish_shared_image'):
            self.parent_app.publish_shared_image(
                image_data_obj,
                image_path=current_image['path'],
                source_tab=self,
            )
        else:
            # Legacy fallback path.
            self.parent_app.image_data = image_data_obj
            self.parent_app.image_path = current_image['path']
        
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
        folder = dialog_select_directory(self, "Select Folder", key="folder_select")
        if folder:
            self.folder_path_input.setText(folder)
            self._refresh_folder_browser(force=True)
            self._update_folder_auto_refresh()

    def _preview_folder_files(self):
        """Compatibility wrapper for older callers."""
        self._refresh_folder_browser()

    def _get_folder_image_paths(self):
        """Return supported image paths from the selected folder after filter and sort."""
        folder_path = self.folder_path_input.text()
        if not folder_path:
            return []

        folder = Path(folder_path)
        if not folder.is_dir():
            return []

        supported_patterns = SUPPORTED_FORMATS['image_files'].split()
        filter_text = self.pattern_input.text().strip()

        file_paths = []
        for path in folder.iterdir():
            if not path.is_file():
                continue

            name = path.name
            if not any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in supported_patterns):
                continue

            if filter_text:
                if any(char in filter_text for char in "*?["):
                    if not fnmatch.fnmatch(name.lower(), filter_text.lower()):
                        continue
                elif filter_text.lower() not in name.lower():
                    continue

            file_paths.append(path)

        sort_mode = self.folder_sort_combo.currentData() if hasattr(self, 'folder_sort_combo') else "name_asc"
        if sort_mode == "name_desc":
            file_paths.sort(key=lambda path: path.name.lower(), reverse=True)
        elif sort_mode == "mtime_desc":
            file_paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        elif sort_mode == "mtime_asc":
            file_paths.sort(key=lambda path: path.stat().st_mtime)
        else:
            file_paths.sort(key=lambda path: path.name.lower())

        return file_paths

    def _refresh_folder_browser(self, *_args, stop_playback=True, force=False):
        """Refresh the folder image list without loading image data."""
        if stop_playback:
            self._stop_folder_playback()

        file_paths = self._get_folder_image_paths()
        path_strings = [str(path) for path in file_paths]

        if not force and path_strings == self._folder_browser_paths:
            if self.folder_path_input.text() and hasattr(self, 'loading_status_label'):
                self.loading_status_label.setText(f"Found {len(file_paths)} images")
            return

        current_item = self.folder_files_list.currentItem()
        current_path = current_item.data(Qt.UserRole) if current_item is not None else None

        self.folder_files_list.clear()

        for path in file_paths:
            item = QListWidgetItem(path.name)
            item.setData(Qt.UserRole, str(path))
            self.folder_files_list.addItem(item)

        self._folder_browser_paths = path_strings

        if current_path in path_strings:
            self.folder_files_list.setCurrentRow(path_strings.index(current_path))

        if self.folder_path_input.text() and hasattr(self, 'loading_status_label'):
            self.loading_status_label.setText(f"Found {len(file_paths)} images")

    def _auto_refresh_folder_browser(self):
        """Poll the selected folder so newly created images appear in the list."""
        if not self.folder_path_input.text():
            self.folder_refresh_timer.stop()
            return

        self._refresh_folder_browser(stop_playback=False)

    def _update_folder_auto_refresh(self):
        """Start or stop folder polling based on the selected folder and checkbox."""
        if (
            hasattr(self, 'folder_auto_refresh_button')
            and self.folder_auto_refresh_button.isChecked()
            and self.folder_path_input.text()
        ):
            self.folder_refresh_timer.start()
        else:
            self.folder_refresh_timer.stop()

    def _open_folder_file(self, item):
        """Show the clicked folder image using deferred loading."""
        file_path = item.data(Qt.UserRole)
        if not file_path:
            return

        existing_index = next(
            (index for index, image in enumerate(self.session_manager.images) if image['path'] == file_path),
            None,
        )

        if existing_index is None:
            self.session_manager.add_image_reference(file_path)
        else:
            self.session_manager.set_current_index(existing_index)

        self.loading_status_label.setText(f"Selected {os.path.basename(file_path)}")

    def _toggle_folder_playback(self):
        """Play through the visible folder image list."""
        if self.folder_files_list.count() == 0:
            self.folder_play_button.setChecked(False)
            return

        if self.folder_play_button.isChecked():
            if self.folder_files_list.currentRow() < 0:
                self._select_folder_browser_row(0)
            self.folder_play_button.setText("⏸")
            self.folder_play_timer.start(500)
        else:
            self._stop_folder_playback()

    def _stop_folder_playback(self):
        """Stop folder-list playback and reset the play button."""
        if hasattr(self, 'folder_play_timer'):
            self.folder_play_timer.stop()
        if hasattr(self, 'folder_play_button'):
            self.folder_play_button.setChecked(False)
            self.folder_play_button.setText("▶")

    def _advance_folder_playback(self):
        """Advance to the next visible folder image during playback."""
        count = self.folder_files_list.count()
        if count == 0:
            self._stop_folder_playback()
            return

        next_row = self.folder_files_list.currentRow() + 1
        if next_row >= count:
            if not self.folder_loop_button.isChecked():
                self._stop_folder_playback()
                return
            next_row = 0

        self._select_folder_browser_row(next_row)

    def _select_folder_browser_row(self, row):
        """Select and display a row from the visible folder browser list."""
        item = self.folder_files_list.item(row)
        if item is None:
            return

        self.folder_files_list.setCurrentRow(row)
        self._open_folder_file(item)

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
        
        file_path, _ = dialog_save_file(
            self,
            "Export Session List",
            "session_list.txt",
            "Text Files (*.txt)",
            key="session_export",
        )
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
        
