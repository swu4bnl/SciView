"""
Image Browser Tab Module

This module contains the ImageBrowserApp class which provides comprehensive
image loading, browsing, and management functionality with multiple data sources.
"""

import os
import sys
import time
import numpy as np
import glob
import fnmatch
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QCheckBox, QComboBox, QLineEdit,
    QFileDialog, QMessageBox, QScrollArea, QGridLayout, QSplitter,
    QSizePolicy, QStyle,
)
from PyQt5.QtCore import QSignalBlocker, Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt5.QtGui import QPixmap, QIcon

# Import base class and configuration
from tabs.base_image_tab import BaseImageTab
from sciview.interfaces.theme.app_style import (
    AppStyle,
    apply_info_style,
    apply_title_style,
    apply_toolbar_symbol_button_style,
    setup_splitter_layout,
)
from sciview.interfaces.text import tr
from sciview.interfaces.stable_qt.widgets.image_annotations import ImageAnnotations
from sciview.settings.app_settings import SUPPORTED_FORMATS, IMAGE_BROWSER_SETTINGS

# Import centralized tiled client manager
from sciview.sources.tiled_client import tiled_manager

# Import shared utilities
from sciview.interfaces.stable_qt.utils.image_utils import ImageShapeConverter, ImageCacheManager
from sciview.session.session_cache import choose_path, load_dialog_state, save_dialog_state


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
            tr(
                "image_browser.progress.reading_tile",
                completed=chunks_done,
                total=total_chunks,
            )
            if total_chunks > 1
            else tr("image_browser.progress.reading_image")
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
        self.progress_updated.emit(
            0,
            tr("image_browser.progress.matching_files", count=total_files),
        )
        
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
            self.progress_updated.emit(
                progress,
                tr(
                    "image_browser.progress.added_file",
                    current=i + 1,
                    total=total_files,
                    filename=os.path.basename(file_path),
                ),
            )
    
    def _load_from_tiled(self):
        """Load images from tiled client using scan ID (single or range)"""
        if not self.tiled_manager.is_available():
            import_error = self.tiled_manager.get_import_error() or tr(
                "image_browser.error.unknown_import"
            )
            self.error_occurred.emit(
                tr("image_browser.error.tiled_unavailable", error=import_error)
            )
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
                    self.progress_updated.emit(
                        100,
                        tr(
                            "image_browser.progress.cancelled_range",
                            loaded=loaded_count,
                            skipped=skipped_count,
                            processed=processed_count,
                        ),
                    )
                    break
                
                processed_count += 1
                progress = int((processed_count / total_scans) * 100)
                self.progress_updated.emit(
                    progress,
                    tr(
                        "image_browser.progress.scan_range",
                        scan_id=current_scan_id,
                        loaded=loaded_count,
                        skipped=skipped_count,
                        processed=processed_count,
                    ),
                )
                
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
                self.progress_updated.emit(
                    100,
                    tr(
                        "image_browser.progress.complete_range",
                        loaded=loaded_count,
                        skipped=skipped_count,
                        total=total_scans,
                    ),
                )
            
        else:
            # Load single scan
            try:
                self.progress_updated.emit(
                    10,
                    tr("image_browser.progress.connecting_tiled", profile=profile_name),
                )
                
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
                        self.error_occurred.emit(
                            tr("image_browser.error.scan_not_found", scan_id=scan_id)
                        )
                    else:
                        self.error_occurred.emit(error_msg)
                    return
                
                self.progress_updated.emit(
                    90, tr("image_browser.progress.processing_image")
                )
                
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
                self.progress_updated.emit(
                    100,
                    tr("image_browser.progress.tiled_complete", scan_id=scan_id),
                )
                
            except Exception as e:
                self.error_occurred.emit(
                    tr("image_browser.error.tiled_loading", error=str(e))
                )
                import traceback
                print(f"Detailed tiled error: {traceback.format_exc()}")
    
    def _load_single_file(self):
        """Load a single image file"""
        file_path = self.kwargs['file_path']
        
        try:
            self.progress_updated.emit(
                50,
                tr(
                    "image_browser.progress.loading_file",
                    filename=os.path.basename(file_path),
                ),
            )
            image_data = self._load_image_file(file_path)
            
            if image_data is not None:
                # File loading doesn't have Tiled metadata
                file_metadata = {'source': 'file'}
                self.image_loaded.emit(image_data, file_path, file_metadata)
                self.progress_updated.emit(
                    100, tr("image_browser.progress.file_complete")
                )
            else:
                self.error_occurred.emit(
                    tr("image_browser.error.file_load_failed", path=file_path)
                )
                
        except Exception as e:
            self.error_occurred.emit(
                tr("image_browser.error.loading_file", error=str(e))
            )
    
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
        self._folder_playback_rates = tuple(IMAGE_BROWSER_SETTINGS["playback_rates_fps"])
        self._folder_playback_rate_index = self._folder_playback_rates.index(
            IMAGE_BROWSER_SETTINGS["default_playback_rate_fps"]
        )
        self.folder_refresh_timer = QTimer(self)
        self.folder_refresh_timer.setInterval(2000)
        self.folder_refresh_timer.timeout.connect(self._auto_refresh_folder_browser)
        self._folder_browser_paths = []
        self._folder_browser_dirs: list[str] = []
        self._added_folder_paths: list[str] = []
        self._last_browsed_folder: str = ""
        self._folder_dir_count: int = 0

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
        if hasattr(self.parent_app, 'publish_shared_display_settings'):
            self.parent_app.publish_shared_display_settings(self.display_settings, source_tab=self)

        self._apply_display_settings_to_viewer()

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

        # Right panel: Image loading options
        layout_ratios = AppStyle.get_layout_ratios()
        loading_panel = self._create_loading_panel()
        main_splitter.addWidget(self.make_scrollable_panel(loading_panel))
        # Set main splitter to match other tabs: 3:1 visualization to controls
        setup_splitter_layout(main_splitter, layout_ratios['main_splitter_ratio'])
        
        main_layout.addWidget(main_splitter, 1)

    def _create_loading_panel(self):
        """Create the loading options panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Title
        title = QLabel(tr("image_browser.title"))
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
        self.loading_status_label = QLabel(tr("image_browser.status.ready"))
        apply_info_style(self.loading_status_label)

        return panel

    def _create_folder_loading_tab(self):
        """Create folder browsing tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Folder selection
        folder_layout = QHBoxLayout()
        self.folder_path_combo = QComboBox()
        self.folder_path_combo.setEditable(True)
        self.folder_path_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.folder_path_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.folder_path_combo.setInsertPolicy(QComboBox.NoInsert)
        self.folder_path_combo.setToolTip(tr("image_browser.folder.path.tooltip"))
        self.folder_path_input = self.folder_path_combo.lineEdit()
        self.folder_path_input.setPlaceholderText(
            tr("image_browser.folder.path.placeholder")
        )
        self.folder_path_combo.activated[str].connect(self._go_to_folder)
        folder_layout.addWidget(self.folder_path_combo, 1)
        
        self.folder_up_button = QPushButton()
        self.folder_up_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowUp))
        self.folder_up_button.setToolTip(tr("image_browser.folder.parent.tooltip"))
        apply_toolbar_symbol_button_style(self.folder_up_button)
        self.folder_up_button.clicked.connect(self._navigate_folder_up)
        self.folder_up_button.setEnabled(False)
        folder_layout.addWidget(self.folder_up_button)

        btn_browse_folder = QPushButton()
        btn_browse_folder.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        btn_browse_folder.setToolTip(tr("image_browser.folder.choose.tooltip"))
        btn_browse_folder.clicked.connect(self._browse_folder)
        apply_toolbar_symbol_button_style(btn_browse_folder)
        folder_layout.addWidget(btn_browse_folder)
        self._populate_recent_folders()
        layout.addLayout(folder_layout)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel(tr("image_browser.folder.filter.label")))
        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText(
            tr("image_browser.folder.filter.placeholder")
        )
        filter_layout.addWidget(self.pattern_input, 1)

        filter_layout.addWidget(QLabel(tr("image_browser.folder.sort.label")))
        self.folder_sort_combo = QComboBox()
        self.folder_sort_combo.addItem(
            tr("image_browser.folder.sort.name_ascending"), "name_asc"
        )
        self.folder_sort_combo.addItem(
            tr("image_browser.folder.sort.name_descending"), "name_desc"
        )
        self.folder_sort_combo.addItem(
            tr("image_browser.folder.sort.newest_first"), "mtime_desc"
        )
        self.folder_sort_combo.addItem(
            tr("image_browser.folder.sort.oldest_first"), "mtime_asc"
        )
        filter_layout.addWidget(self.folder_sort_combo)
        layout.addLayout(filter_layout)

        contents_header = QHBoxLayout()
        contents_header.addWidget(QLabel(tr("image_browser.folder.contents.title")))
        contents_header.addStretch()
        self.folder_contents_count_label = QLabel(
            tr("image_browser.folder.contents.empty")
        )
        apply_info_style(self.folder_contents_count_label)
        contents_header.addWidget(self.folder_contents_count_label)

        self.folder_auto_refresh_button = QCheckBox(
            tr("image_browser.folder.auto_refresh.label")
        )
        self.folder_auto_refresh_button.setToolTip(
            tr("image_browser.folder.auto_refresh.tooltip")
        )
        self.folder_auto_refresh_button.setChecked(True)
        self.folder_auto_refresh_button.toggled.connect(self._update_folder_auto_refresh)
        contents_header.addWidget(self.folder_auto_refresh_button)
        layout.addLayout(contents_header)

        self.folder_files_list = QListWidget()
        self.folder_files_list.currentItemChanged.connect(self._open_folder_file)
        self.folder_files_list.itemClicked.connect(self._reopen_folder_file)
        self.folder_files_list.itemDoubleClicked.connect(self._handle_folder_list_double_click)
        self.folder_files_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.folder_files_list.setTextElideMode(Qt.ElideMiddle)
        layout.addWidget(self.folder_files_list, 1)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(AppStyle.LAYOUT['toolbar_spacing'])

        self.folder_play_button = QPushButton("▶")
        self.folder_play_button.setToolTip(tr("image_browser.play.tooltip"))
        apply_toolbar_symbol_button_style(self.folder_play_button)
        self._apply_tool_icon(self.folder_play_button, 'tool_play.svg')
        self.folder_play_button.setCheckable(True)
        self.folder_play_button.clicked.connect(self._toggle_folder_playback)
        controls_layout.addWidget(self.folder_play_button)

        self.folder_playback_speed_button = QPushButton()
        apply_toolbar_symbol_button_style(self.folder_playback_speed_button)
        self._update_folder_playback_speed_button()
        self.folder_playback_speed_button.clicked.connect(self._cycle_folder_playback_speed)
        self.folder_playback_speed_button.hide()
        controls_layout.addWidget(self.folder_playback_speed_button)

        self.folder_loop_button = QPushButton("∞")
        self.folder_loop_button.setToolTip(tr("image_browser.play.repeat.tooltip"))
        self.folder_loop_button.setCheckable(True)
        apply_toolbar_symbol_button_style(self.folder_loop_button)
        self._apply_tool_icon(self.folder_loop_button, 'tool_infinite.svg')
        self.folder_loop_button.hide()
        controls_layout.addWidget(self.folder_loop_button)
        controls_layout.addStretch()

        self.add_all_folder_button = QPushButton()
        self.add_all_folder_button.setToolTip(
            tr("image_browser.batch.add_all.tooltip")
        )
        apply_toolbar_symbol_button_style(self.add_all_folder_button)
        self._apply_tool_icon(self.add_all_folder_button, 'tool_add_all.svg')
        self.add_all_folder_button.clicked.connect(self._load_from_folder)
        controls_layout.addWidget(self.add_all_folder_button)

        self.collection_status_label = QLabel()
        apply_info_style(self.collection_status_label)
        self.collection_status_label.setVisible(False)
        controls_layout.addWidget(self.collection_status_label)

        self.clear_collection_button = QPushButton()
        self.clear_collection_button.setToolTip(
            tr("image_browser.batch.clear.tooltip")
        )
        apply_toolbar_symbol_button_style(self.clear_collection_button)
        self._apply_tool_icon(self.clear_collection_button, 'tool_delete.svg')
        self.clear_collection_button.clicked.connect(self._clear_collected_folders)
        self.clear_collection_button.setEnabled(False)
        self.clear_collection_button.setVisible(False)
        controls_layout.addWidget(self.clear_collection_button)
        layout.addLayout(controls_layout)

        return tab

    def _create_image_browser_panel(self):
        """Create image browser panel with viewer only — nav controls are in the folder toolbar."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # Use base image panel without the redundant 'Raw Image' title and filename label.
        base_image_panel = self._create_image_panel(show_header=False)
        self.annotations = ImageAnnotations(self.image_viewer)
        self.post_display_hooks.append(lambda _viewer: self.annotations.refresh_image())
        self.annotations.drawing_changed.connect(
            lambda enabled: self._stop_folder_playback() if enabled else None
        )
        layout.addWidget(base_image_panel, 1)

        return panel

    # Loading Methods
    def _load_from_folder(self):
        """Keep the current folder's visible images in the shared Batch list."""
        self._stop_folder_playback()
        file_paths = self._get_folder_image_paths()

        if not file_paths:
            QMessageBox.warning(
                self,
                tr("image_browser.error.no_files.title"),
                tr("image_browser.error.no_files.body"),
            )
            return

        for file_path in file_paths:
            path_str = str(file_path)
            if path_str not in self._added_folder_paths:
                self._added_folder_paths.append(path_str)

        self._update_collection_status()
        self._publish_shared_file_list()
        message = tr(
            "image_browser.batch.kept_images",
            count=len(file_paths),
        )
        self.loading_status_label.setText(message)
        self.parent_app.show_status(message)

    def _clear_collected_folders(self) -> None:
        """Clear images kept from previously browsed folders."""
        self._added_folder_paths.clear()
        self._update_collection_status()
        self._publish_shared_file_list()
        self.loading_status_label.setText(
            tr("image_browser.batch.cleared_folders")
        )

    def _update_collection_status(self) -> None:
        count = len(self._added_folder_paths)
        self.collection_status_label.setText(
            tr("image_browser.batch.count", count=count)
        )
        self.collection_status_label.setVisible(count > 0)
        self.clear_collection_button.setEnabled(count > 0)
        self.clear_collection_button.setVisible(count > 0)

    def _on_session_changed(self, session_manager):
        """Handle session changes"""
        # Only update display if we're not in the middle of batch loading
        # This prevents triggering data loads for every reference added
        if not self.is_batch_loading:
            self._update_display()

    def _publish_shared_file_list(self) -> None:
        """Publish the current file-backed image list into app shared state."""
        if not hasattr(self.parent_app, "publish_shared_file_list"):
            return
        self.parent_app.publish_shared_file_list(
            self.get_current_file_list(),
            folder=self.folder_path_input.text().strip() if hasattr(self, "folder_path_input") else "",
            pattern=self.pattern_input.text().strip() if hasattr(self, "pattern_input") else "*",
            source="image_browser",
            source_tab=self,
        )

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
        # Get current image, triggering on-demand loading if needed
        current_image = self.session_manager.get_current_image(
            load_data=True, 
            loader_callback=self._lazy_load_callback
        )
        
        if current_image is None:
            self.image_viewer.clear_image(tr("image_browser.image.empty.viewer"))
            self.annotations.refresh_image()
            self.filename_label.setText(tr("image_browser.image.empty"))
            return
        
        # Check if data is available (might still be None if loading failed)
        if current_image['data'] is None:
            loading_message = tr(
                "image_browser.image.loading",
                filename=current_image["filename"],
            )
            self.image_viewer.clear_image(loading_message)
            self.annotations.refresh_image()
            self.filename_label.setText(loading_message)
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
        self.image_viewer.set_title(filename)
        self.filename_label.setText(
            tr("image_browser.image.filename_source", filename=filename, source=source)
        )
    
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

    def _sync_to_parent(self, show_status: bool = True) -> bool:
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
            return False
        
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

        if show_status:
            self.parent_app.show_status(
                tr(
                    "image_browser.status.synced_image",
                    filename=current_image["filename"],
                )
            )
        return True

    def auto_publish_current_image(self) -> bool:
        """Publish the current browser image when the user leaves the browser tab."""
        current_image = self.session_manager.get_current_image(load_data=False)
        if current_image is None:
            return False
        if getattr(self.parent_app, 'image_path', None) == current_image.get('path'):
            return False
        return self._sync_to_parent(show_status=False)

    def auto_publish_current_file_list(self) -> None:
        """Publish the current browser file-backed list when leaving the tab."""
        self._publish_shared_file_list()

    def get_session_state(self) -> dict:
        """Serialize last-browsed folder + selected file for restart restore."""
        folder = self.folder_path_input.text().strip() if hasattr(self, "folder_path_input") else ""
        current_image = self.session_manager.get_current_image(load_data=False)
        if not folder and current_image is None:
            return {}
        return {
            "folder": folder,
            "last_image_path": current_image.get("path") if current_image else None,
        }

    def restore_session_state(self, state: dict) -> None:
        """Re-open the last-browsed folder/file and re-sync it to other tabs."""
        folder = state.get("folder")
        last_path = state.get("last_image_path")

        if folder:
            self.folder_path_input.setText(folder)
            self._refresh_folder_browser(force=True)

        if not last_path:
            return

        for row in range(self.folder_files_list.count()):
            item = self.folder_files_list.item(row)
            if item.data(Qt.UserRole) == last_path:
                self._select_folder_browser_row(row)
                break
        else:
            self.session_manager.add_image_reference(last_path)

        if self._sync_to_parent(show_status=False):
            self.parent_app.show_status(
                tr(
                    "image_browser.status.restored_image",
                    filename=os.path.basename(last_path),
                )
            )


    def get_current_file_list(self) -> list[str]:
        """Return the current folder's files plus files explicitly kept in Batch."""
        seen: set[str] = set()
        result: list[str] = []

        # The folder browser list — a full scan of the currently selected folder.
        for p in self._folder_browser_paths:
            if os.path.isfile(p) and p not in seen:
                seen.add(p)
                result.append(p)

        # Files explicitly added via "+ Add All", possibly from other folders.
        for p in self._added_folder_paths:
            if os.path.isfile(p) and p not in seen:
                seen.add(p)
                result.append(p)

        return result
    
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

    # Utility methods
    def _browse_folder(self):
        """Browse for folder"""
        folder, _ = choose_path(
            self,
            tr("image_browser.dialog.select_folder.title"),
            mode="directory",
            key="folder_select",
        )
        if folder:
            self._go_to_folder(folder)

    def _preview_folder_files(self):
        """Compatibility wrapper for older callers."""
        self._refresh_folder_browser()

    def _go_to_folder(self, folder_path: str) -> None:
        """Navigate the folder browser to folder_path (button, recent-list, or drill-down)."""
        self.folder_path_input.setText(folder_path)
        self._refresh_folder_browser(force=True)
        self._update_folder_auto_refresh()

    def _navigate_folder_up(self) -> None:
        """Go to the parent of the currently browsed folder."""
        current = self.folder_path_input.text().strip()
        if not current:
            return
        parent = Path(current).parent
        if str(parent) != current:
            self._go_to_folder(str(parent))

    def _handle_folder_list_double_click(self, item) -> None:
        """Descend into a subfolder row."""
        if item is None or item.data(Qt.UserRole + 1) != "dir":
            return
        path = item.data(Qt.UserRole)
        if path:
            self._go_to_folder(path)

    def _add_recent_folder(self, folder_path: str) -> None:
        """Persist folder_path at the front of the recent-folders list."""
        state = load_dialog_state()
        recents = state.get("recent_folders")
        recents = [p for p in recents if isinstance(p, str)] if isinstance(recents, list) else []
        recents = [p for p in recents if p != folder_path]
        recents.insert(0, folder_path)
        max_recent = IMAGE_BROWSER_SETTINGS.get("max_recent_files", 10)
        state["recent_folders"] = recents[:max_recent]
        save_dialog_state(state)
        self._populate_recent_folders()

    def _populate_recent_folders(self) -> None:
        """Populate the editable path control with existing recent folders."""
        state = load_dialog_state()
        recents = state.get("recent_folders")
        recents = [p for p in recents if isinstance(p, str)] if isinstance(recents, list) else []
        recents = [p for p in recents if Path(p).is_dir()]
        current = self.folder_path_input.text() if hasattr(self, "folder_path_input") else ""
        with QSignalBlocker(self.folder_path_combo):
            self.folder_path_combo.clear()
            self.folder_path_combo.addItems(recents)
            self.folder_path_combo.setEditText(current)

    def _get_subfolder_paths(self, folder_path: str) -> list:
        """Return immediate subdirectories of folder_path, sorted by name."""
        if not folder_path:
            return []
        folder = Path(folder_path)
        if not folder.is_dir():
            return []
        try:
            subdirs = [p for p in folder.iterdir() if p.is_dir()]
        except OSError:
            return []
        subdirs.sort(key=lambda p: p.name.lower())
        return subdirs

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

        folder_path = self.folder_path_input.text().strip() if hasattr(self, "folder_path_input") else ""
        if folder_path != self._last_browsed_folder:
            self._last_browsed_folder = folder_path
            if folder_path and Path(folder_path).is_dir():
                self._add_recent_folder(folder_path)

        if hasattr(self, "folder_up_button"):
            parent = Path(folder_path).parent if folder_path else None
            can_go_up = bool(folder_path) and parent is not None and str(parent) != folder_path
            self.folder_up_button.setEnabled(can_go_up)

        file_paths = self._get_folder_image_paths()
        path_strings = [str(path) for path in file_paths]
        subfolders = self._get_subfolder_paths(folder_path)
        subfolder_strings = [str(path) for path in subfolders]

        if not force and path_strings == self._folder_browser_paths and subfolder_strings == self._folder_browser_dirs:
            if self.folder_path_input.text() and hasattr(self, 'loading_status_label'):
                self.loading_status_label.setText(
                    tr("image_browser.folder.status.found_images", count=len(file_paths))
                )
            self._publish_shared_file_list()
            return

        current_item = self.folder_files_list.currentItem()
        current_path = current_item.data(Qt.UserRole) if current_item is not None else None

        with QSignalBlocker(self.folder_files_list):
            self.folder_files_list.clear()
            for subfolder in subfolders:
                item = QListWidgetItem(subfolder.name)
                item.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
                item.setData(Qt.UserRole, str(subfolder))
                item.setData(Qt.UserRole + 1, "dir")
                self.folder_files_list.addItem(item)
            for path in file_paths:
                item = QListWidgetItem(path.name)
                item.setToolTip(path.name)
                item.setData(Qt.UserRole, str(path))
                self.folder_files_list.addItem(item)
            if current_path in path_strings:
                self.folder_files_list.setCurrentRow(len(subfolders) + path_strings.index(current_path))

        self._folder_dir_count = len(subfolders)
        self._folder_browser_dirs = subfolder_strings
        self._folder_browser_paths = path_strings
        image_count_id = (
            "image_browser.folder.count.one_image"
            if len(file_paths) == 1
            else "image_browser.folder.count.images"
        )
        folder_count_id = (
            "image_browser.folder.count.one_folder"
            if len(subfolders) == 1
            else "image_browser.folder.count.folders"
        )
        count_parts = [tr(image_count_id, count=len(file_paths))]
        if subfolders:
            count_parts.append(tr(folder_count_id, count=len(subfolders)))
        self.folder_contents_count_label.setText(" · ".join(count_parts))

        if self.folder_path_input.text() and hasattr(self, 'loading_status_label'):
            self.loading_status_label.setText(
                tr("image_browser.folder.status.found_images", count=len(file_paths))
            )

        self._publish_shared_file_list()

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
        """Show the selected folder image using deferred loading."""
        if item is None or item.data(Qt.UserRole + 1) == "dir":
            return
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

        self.loading_status_label.setText(
            tr(
                "image_browser.folder.status.selected_file",
                filename=os.path.basename(file_path),
            )
        )

    def _reopen_folder_file(self, item) -> None:
        """Reopen a selected folder row after session navigation."""
        if item is None or item.data(Qt.UserRole + 1) == "dir":
            return
        current_image = self.session_manager.get_current_image()
        file_path = item.data(Qt.UserRole)
        if current_image is None or current_image['path'] != file_path:
            self._open_folder_file(item)

    def _toggle_folder_playback(self):
        """Play through the visible folder image list."""
        if self.folder_files_list.count() <= self._folder_dir_count:
            self.folder_play_button.setChecked(False)
            return

        if self.folder_play_button.isChecked():
            if self.folder_files_list.currentRow() < self._folder_dir_count:
                self._select_folder_browser_row(self._folder_dir_count)
            self.folder_playback_speed_button.show()
            self.folder_loop_button.show()
            self._apply_tool_icon(self.folder_play_button, 'tool_pause.svg')
            self.folder_play_button.setToolTip(
                tr("image_browser.play.pause.tooltip")
            )
            self.folder_play_timer.start(self._folder_playback_interval_ms())
        else:
            self._stop_folder_playback()

    def _folder_playback_interval_ms(self) -> int:
        rate = self._folder_playback_rates[self._folder_playback_rate_index]
        return round(1000 / rate)

    def _folder_playback_delay_ms(self, frame_elapsed_ms: float) -> int:
        return max(1, round(self._folder_playback_interval_ms() - frame_elapsed_ms))

    def _cycle_folder_playback_speed(self) -> None:
        """Cycle through configured image playback rates."""
        self._folder_playback_rate_index = (
            self._folder_playback_rate_index + 1
        ) % len(self._folder_playback_rates)
        self._update_folder_playback_speed_button()
        if self.folder_play_timer.isActive():
            self.folder_play_timer.setInterval(self._folder_playback_interval_ms())

    def _update_folder_playback_speed_button(self) -> None:
        speed = tr(
            (
                "image_browser.playback.speed.slow",
                "image_browser.playback.speed.medium",
                "image_browser.playback.speed.fast",
            )[self._folder_playback_rate_index]
        )
        self.folder_playback_speed_button.setAccessibleName(
            tr("image_browser.playback.speed.accessible", speed=speed)
        )
        self.folder_playback_speed_button.setToolTip(
            tr(
                (
                    "image_browser.playback.speed.tooltip.slow",
                    "image_browser.playback.speed.tooltip.medium",
                    "image_browser.playback.speed.tooltip.fast",
                )[self._folder_playback_rate_index]
            )
        )
        self._apply_tool_icon(
            self.folder_playback_speed_button,
            f'tool_speed_{self._folder_playback_rate_index + 1}.svg',
        )

    def _stop_folder_playback(self):
        """Stop folder-list playback and reset the play button."""
        if hasattr(self, 'folder_play_timer'):
            self.folder_play_timer.stop()
        if hasattr(self, 'folder_play_button'):
            self.folder_play_button.setChecked(False)
            self.folder_play_button.setToolTip(tr("image_browser.play.tooltip"))
            self._apply_tool_icon(self.folder_play_button, 'tool_play.svg')

    def _load_browser_icon(self, filename: str):
        workspace_root = getattr(self.parent_app, '_workspace_root', Path(__file__).resolve().parent.parent.parent)
        return AppStyle.load_icon(workspace_root, filename)

    def _apply_tool_icon(self, button, filename: str) -> None:
        icon = self._load_browser_icon(filename)
        if not icon.isNull():
            size = AppStyle.toolbar_symbol_button_size()
            icon_px = max(16, min(size.width() - 8, size.height() - 8))
            button.setIcon(icon)
            button.setIconSize(QSize(icon_px, icon_px))
            button.setText("")

    def refresh_theme(self) -> None:
        """Re-tint toolbar icons for the active dark/light theme."""
        pairs = [
            (
                getattr(self, 'folder_play_button', None),
                'tool_pause.svg' if getattr(self, 'folder_play_button', None) is not None
                and self.folder_play_button.isChecked() else 'tool_play.svg',
            ),
            (getattr(self, 'folder_loop_button', None),    'tool_infinite.svg'),
            (getattr(self, 'add_all_folder_button', None), 'tool_add_all.svg'),
            (getattr(self, 'clear_collection_button', None), 'tool_delete.svg'),
        ]
        for button, filename in pairs:
            if button is not None:
                self._apply_tool_icon(button, filename)
        if getattr(self, 'folder_playback_speed_button', None) is not None:
            self._update_folder_playback_speed_button()

    def _advance_folder_playback(self):
        """Advance to the next visible folder image during playback."""
        started_at = time.perf_counter()
        count = self.folder_files_list.count()
        if count <= self._folder_dir_count:
            self._stop_folder_playback()
            return

        next_row = self.folder_files_list.currentRow() + 1
        if next_row >= count:
            if not self.folder_loop_button.isChecked():
                self._stop_folder_playback()
                return
            next_row = self._folder_dir_count

        self._select_folder_browser_row(next_row)
        frame_elapsed_ms = (time.perf_counter() - started_at) * 1000
        self.folder_play_timer.setInterval(
            self._folder_playback_delay_ms(frame_elapsed_ms)
        )

    def _select_folder_browser_row(self, row):
        """Select and display a row from the visible folder browser list."""
        if self.folder_files_list.item(row) is None:
            return

        self.folder_files_list.setCurrentRow(row)

    def _export_session_list(self):
        """Export session file list"""
        if not self.session_manager.images:
            QMessageBox.information(
                self,
                tr("image_browser.export.empty.title"),
                tr("image_browser.export.empty.body"),
            )
            return
        
        file_path, _ = choose_path(
            self,
            tr("image_browser.export.session_list.title"),
            mode="save", default_name="session_list.txt",
            file_filter=tr("image_browser.export.session_list.filter"),
            key="session_export",
        )
        if file_path:
            with open(file_path, 'w') as f:
                for img in self.session_manager.images:
                    f.write(f"{img['path']}\n")
            self.parent_app.show_status(
                tr("image_browser.export.session_list.complete", path=file_path)
            )

    def _export_session_data(self):
        """Export session data as HDF5 or similar"""
        # Placeholder for data export functionality
        QMessageBox.information(
            self,
            tr("image_browser.export.data.title"),
            tr("image_browser.export.data.unavailable"),
        )

    def _setup_parent_sync(self):
        """Setup synchronization with parent application"""
        # This could include callbacks or signals to keep tabs in sync
        pass

    def _add_tab_specific_status(self, info_lines):
        """Add image browser specific status information"""
        info_lines.append("")
        info_lines.append(tr("image_browser.debug.section_title"))
        info_lines.append(
            tr(
                "image_browser.debug.session_images",
                count=len(self.session_manager.images),
            )
        )
        
        # Cache information
        cache_info = self.session_manager.get_cache_info()
        info_lines.append(
            tr(
                "image_browser.debug.cache_summary",
                cached=cache_info["cached_images"],
                total=cache_info["total_images"],
                limit=cache_info["cache_limit"],
            )
        )
        
        current_image = self.session_manager.get_current_image(load_data=False)
        if current_image:
            info_lines.append(
                tr("image_browser.debug.current_image", filename=current_image["filename"])
            )
            info_lines.append(
                tr("image_browser.debug.source", source=current_image["source"])
            )
            # Show loading mode for developer context
            loading_mode = tr(
                "image_browser.debug.loading_mode.deferred"
                if current_image.get("lazy", False)
                else "image_browser.debug.loading_mode.immediate"
            )
            info_lines.append(
                tr("image_browser.debug.loading_mode.label", mode=loading_mode)
            )
            if current_image['size']:
                info_lines.append(
                    tr(
                        "image_browser.debug.dimensions",
                        width=current_image["size"][0],
                        height=current_image["size"][1],
                    )
                )
        
