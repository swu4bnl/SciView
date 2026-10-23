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
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QCheckBox, QComboBox, QLineEdit,
    QFileDialog, QMessageBox, QScrollArea, QSplitter,
    QSizePolicy, QStyle, QSlider,
)
from PyQt5.QtCore import QEvent, QSignalBlocker, Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt5.QtGui import QIcon, QPainter, QPixmap

# Import base class and configuration
from tabs.base_image_tab import BaseImageTab
from sciview.interfaces.theme.app_style import (
    AppStyle,
    apply_info_style,
    apply_title_style,
    apply_toolbar_symbol_button_style,
    apply_toolbar_text_button_style,
    setup_splitter_layout,
)
from sciview.interfaces.text import tr
from sciview.interfaces.stable_qt.widgets.image_annotations import ImageAnnotations
from sciview.settings.app_settings import SUPPORTED_FORMATS, IMAGE_BROWSER_SETTINGS
from sciview.core.image_collection import (
    COLOR_MANAGED_COMPARISON_MODES,
    ComparisonDisplay,
    ComparisonMode,
    ImageCollection,
    ImageReference,
    compare_image_arrays,
)
from sciview.settings.viewer_config import DIVERGING_IMAGE_COLORMAPS

# Import centralized tiled client manager
from sciview.sources.tiled_client import tiled_manager

# Import shared utilities
from sciview.interfaces.services.image_service import ImageService
from sciview.sources.filesystem_source import FolderListing, list_folder
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
        self.collection = ImageCollection()
        self.callbacks = []  # Callbacks for when image list changes
        self._pinned_data = None
        
        # Use shared cache manager for data caching
        self.cache_manager = ImageCacheManager(cache_limit=cache_limit)

    @property
    def images(self):
        """References in collection order."""
        return self.collection.references

    @property
    def current_index(self):
        return self.collection.current_index

    @current_index.setter
    def current_index(self, index):
        self.collection.current_index = index
    
    def add_image(self, image_data, file_path, metadata=None, lazy=False):
        """Add an image to the session with optional deferred data loading.
        
        Args:
            image_data: Image data array. Can be None if lazy=True to defer loading.
            file_path: Path or identifier for the image.
            metadata: Optional metadata dict for image properties.
            lazy: If True, stores only the reference without loading data into memory.
        """
        path = str(file_path)
        reference = ImageReference(
            path=path,
            filename=self._extract_display_filename(path, metadata),
            metadata=metadata or {},
            size=tuple(image_data.shape) if image_data is not None and hasattr(image_data, 'shape') else None,
            source=self._determine_source(path),
            lazy=lazy,
            cache_key=path,
        )
        self.collection.add(reference)
        
        # Add to cache if not lazy
        if not lazy and image_data is not None:
            self.cache_manager.put(path, image_data)
        
        self._notify_callbacks()
    
    def add_image_reference(self, file_path, metadata=None, estimated_size=None):
        """Add an image reference without loading data (deferred loading)."""
        self.add_image(None, file_path, metadata=metadata, lazy=True)
        if estimated_size:
            self.images[-1].size = tuple(estimated_size)
    
    def get_current_image(self, load_data=False, loader_callback=None):
        """Get the currently selected image with optional on-demand loading."""
        reference = self.collection.current_reference
        if reference is not None:
            img = {
                'path': reference.path,
                'filename': reference.filename,
                'timestamp': reference.timestamp,
                'metadata': reference.metadata,
                'size': reference.size,
                'source': reference.source,
                'lazy': reference.lazy,
                'cache_key': reference.cache_key,
            }
            
            # Trigger on-demand loading if data is needed
            if load_data:
                if loader_callback:
                    # Use shared cache manager's get method
                    # The loader_callback will be called if data is not in cache
                    loaded_data = self.cache_manager.get(img['cache_key'],
                                                        loader_callback=lambda k: loader_callback(img['path'], img['metadata']))
                    if loaded_data is not None:
                        if img['size'] is None and hasattr(loaded_data, 'shape'):
                            img['size'] = tuple(loaded_data.shape)
                            reference.size = tuple(loaded_data.shape)
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
        if self.collection.select(index):
            self._notify_callbacks()
            return True
        return False
    
    def remove_image(self, index):
        """Remove an image from the session"""
        if 0 <= index < len(self.images):
            # Remove from cache
            removed = self.collection.remove(index)
            if removed is not None:
                self.cache_manager.remove(removed.cache_key)
                if self.collection.pinned_path is None:
                    self._pinned_data = None
            self._notify_callbacks()
    
    def clear_session(self):
        """Clear all images from session"""
        self.collection.clear()
        self._pinned_data = None
        self.cache_manager.clear()
        self._notify_callbacks()
    
    def get_cache_info(self):
        """Get cache information from shared cache manager"""
        info = self.cache_manager.get_cache_info()
        info['total_images'] = len(self.images)
        return info
    
    def get_image_list(self):
        """Get list of all images in session"""
        return [reference.filename for reference in self.images]

    def pin_current(self, loader_callback=None):
        """Pin the active image and retain its data independently of LRU eviction."""
        current = self.get_current_image(load_data=True, loader_callback=loader_callback)
        if current is None or current.get('data') is None:
            return None
        if not self.collection.pin_current():
            return None
        self._pinned_data = current['data']
        self._notify_callbacks()
        return self.get_pinned_image()

    def get_pinned_image(self):
        """Return the pinned reference and its retained array, if available."""
        reference = self.collection.pinned_reference
        if reference is None or self._pinned_data is None:
            return None
        return {
            'path': reference.path,
            'filename': reference.filename,
            'metadata': reference.metadata,
            'size': reference.size,
            'source': reference.source,
            'data': self._pinned_data,
        }

    def unpin(self):
        """Clear the pinned image reference."""
        self.collection.unpin()
        self._pinned_data = None
        self._notify_callbacks()
    
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
        self._hold_shows_selected = False
        self._updating_comparison_display = False
        self._comparison_display_mode: ComparisonMode | None = None
        self._comparison_auto_pending = False
        self._folder_playback_rates = tuple(IMAGE_BROWSER_SETTINGS["playback_rates_fps"])
        self._folder_playback_rate_index = self._folder_playback_rates.index(
            IMAGE_BROWSER_SETTINGS["default_playback_rate_fps"]
        )
        self.folder_refresh_timer = QTimer(self)
        self.folder_refresh_timer.setInterval(2000)
        self.folder_refresh_timer.timeout.connect(self._auto_refresh_folder_browser)
        self._folder_browser_paths = []
        self._folder_listing_key: tuple | None = None
        self._folder_list_image_paths = []
        self._folder_browser_dirs: list[str] = []
        self._added_folder_paths: list[str] = []
        self._last_browsed_folder: str = ""
        self._folder_dir_count: int = 0

        # Build UI
        self._build_ui()
        self.image_viewer.comparison_opacity_adjusted.connect(
            self._adjust_overlay_opacity_from_canvas
        )
        
        # Connect to parent app for synchronization
        self._setup_parent_sync()

    def update_display_settings(self, **kwargs):
        """Route toolbox display edits to the active view.

        Calculated comparison views keep their own display settings so a signed
        difference cannot change shared settings used by other tabs.
        """
        if self._active_comparison_display() is not None:
            self._update_comparison_display(**kwargs)
            return
        self.display_settings.update(kwargs)
        if hasattr(self.parent_app, 'publish_shared_display_settings'):
            self.parent_app.publish_shared_display_settings(self.display_settings, source_tab=self)

        if self.session_manager.collection.pinned_path is not None:
            self._update_display()
        else:
            self._apply_display_settings_to_viewer()

    def get_display_values(self):
        display = self._active_comparison_display()
        if display is None:
            return super().get_display_values()
        vmin, vmax = display.levels if display.levels is not None else (None, None)
        return {
            'vmin': vmin,
            'vmax': vmax,
            'cmap': display.colormap,
            'scale': display.scale,
        }

    def sync_display_controls(self):
        super().sync_display_controls()
        if not hasattr(self, 'vmin_input'):
            return
        mode = self._comparison_display_mode
        self.img_scale_combo.setEnabled(mode != ComparisonMode.DIFFERENCE)
        if mode is None:
            return
        values = self.get_display_values()
        controls = (self.vmin_input, self.vmax_input, self.cmap_selector, self.img_scale_combo)
        blockers = [QSignalBlocker(control) for control in controls]
        for field, value in ((self.vmin_input, values['vmin']), (self.vmax_input, values['vmax'])):
            field.setText("" if value is None else format(value, ".6g"))
        self.cmap_selector.setCurrentText(values['cmap'])
        self.img_scale_combo.setCurrentIndex(self.img_scale_combo.findData(values['scale']))
        del blockers

    def _on_viewer_levels_changed(self, vmin: float, vmax: float) -> None:
        if self._updating_comparison_display:
            return
        if self._active_comparison_display() is None:
            super()._on_viewer_levels_changed(vmin, vmax)
            return
        self._update_comparison_display(vmin=vmin, vmax=vmax)

    def _on_viewer_colormap_changed(self, colormap: str) -> None:
        if self._active_comparison_display() is None:
            super()._on_viewer_colormap_changed(colormap)
            return
        self._update_comparison_display(cmap=colormap)

    def _active_comparison_display(self) -> ComparisonDisplay | None:
        if self._comparison_display_mode is None:
            return None
        return self.session_manager.collection.comparison_displays.get(
            self._comparison_display_mode
        )

    def _update_comparison_display(self, **kwargs) -> None:
        mode = self._comparison_display_mode
        display = self._active_comparison_display()
        levels = display.levels
        if 'vmin' in kwargs or 'vmax' in kwargs:
            if mode == ComparisonMode.DIFFERENCE:
                # Keep signed differences centered on zero, following the edited bound.
                limit = max(abs(float(kwargs.get(bound, 0.0))) for bound in ('vmin', 'vmax'))
                levels = (-limit, limit)
            else:
                previous = levels if levels is not None else (None, None)
                low = kwargs.get('vmin', previous[0])
                high = kwargs.get('vmax', previous[1])
                if low is not None and high is not None:
                    levels = (float(low), float(high))
        try:
            self.session_manager.collection.set_comparison_display(
                mode,
                ComparisonDisplay(
                    colormap=kwargs.get('cmap', display.colormap),
                    scale=kwargs.get('scale', display.scale),
                    levels=levels,
                ),
            )
        except (TypeError, ValueError) as error:
            self.parent_app.show_status(
                tr("image_browser.compare.invalid_display", error=str(error))
            )
        self.sync_display_controls()
        self._apply_display_settings_to_viewer()

    def _active_display_levels(self, mode: ComparisonMode) -> tuple[float, float] | None:
        display = self.session_manager.collection.comparison_displays.get(mode)
        return display.levels if display is not None else None

    def _set_comparison_display_mode(self, mode: ComparisonMode | None) -> None:
        self._comparison_display_mode = mode
        self.image_viewer.set_auto_levels_handler(
            self._request_comparison_auto if mode is not None else None
        )
        self.sync_display_controls()

    def _request_comparison_auto(self) -> None:
        self._comparison_auto_pending = True
        self._update_display()

    def _auto_comparison_display(
        self,
        mode: ComparisonMode,
        values: np.ndarray,
    ) -> None:
        """Choose display settings suited to the data shown by a comparison view."""
        collection = self.session_manager.collection
        display = collection.comparison_displays.get(mode)
        colormap = display.colormap if display is not None else self.display_settings['cmap']
        scale = display.scale if display is not None else self.display_settings['scale']
        if mode == ComparisonMode.DIFFERENCE:
            if colormap not in DIVERGING_IMAGE_COLORMAPS:
                colormap = DIVERGING_IMAGE_COLORMAPS[0]
            scale = 'linear'
            robust = self.image_viewer.auto_levels_for_array(values, scale)
            limit = max(abs(robust[0]), abs(robust[1])) if robust is not None else 0.0
            levels = (-limit, limit) if limit > 0 else (-1.0, 1.0)
        else:
            levels = self.image_viewer.auto_levels_for_array(values, scale)
        collection.set_comparison_display(
            mode,
            ComparisonDisplay(colormap=colormap, scale=scale, levels=levels),
        )

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
        self.folder_files_list.currentItemChanged.connect(
            lambda _current, _previous: self._update_comparison_controls()
        )
        self.folder_files_list.itemClicked.connect(self._reopen_folder_file)
        self.folder_files_list.itemDoubleClicked.connect(self._handle_folder_list_double_click)
        self.folder_files_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.folder_files_list.setTextElideMode(Qt.ElideMiddle)
        # Every row is one line with one icon; uniform sizes avoid measuring
        # each row, which keeps folders with many thousands of files responsive.
        self.folder_files_list.setUniformItemSizes(True)
        self.folder_files_list.setIconSize(AppStyle.corner_button_icon_size())
        self._file_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        self._pin_icon = self._emoji_icon("📌")
        self._pin_preview_icon = self._emoji_icon("📌", opacity=0.35)
        self._pin_hover_row = -1
        self.folder_files_list.viewport().setMouseTracking(True)
        self.folder_files_list.viewport().installEventFilter(self)
        self.folder_files_list.installEventFilter(self)
        self.folder_files_list.setToolTip(tr("image_browser.compare.pin.hint"))
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

        self.comparison_buttons = {}
        for mode, text, tooltip_id in (
            ("split", tr("image_browser.compare.mode.split.short"), "image_browser.compare.mode.split.tooltip"),
            ("opacity", tr("image_browser.compare.mode.opacity.short"), "image_browser.compare.mode.opacity.tooltip"),
            ("add", tr("image_browser.compare.mode.add.short"), "image_browser.compare.mode.add.tooltip"),
            ("difference", tr("image_browser.compare.mode.difference.short"), "image_browser.compare.mode.difference.tooltip"),
        ):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setAccessibleName(
                tr(f"image_browser.compare.mode.{mode}")
            )
            button.setToolTip(tr(tooltip_id))
            apply_toolbar_text_button_style(button)
            button.hide()
            controls_layout.addWidget(button)
            self.comparison_buttons[mode] = button

        for mode, button in self.comparison_buttons.items():
            button.clicked.connect(
                lambda _checked=False, selected_mode=mode:
                self._set_comparison_mode(selected_mode)
            )

        self.comparison_parameter_label = QLabel()
        apply_info_style(self.comparison_parameter_label)
        self.comparison_parameter_label.hide()
        controls_layout.addWidget(self.comparison_parameter_label)

        self.comparison_parameter_slider = QSlider(Qt.Horizontal)
        self.comparison_parameter_slider.setRange(0, 100)
        self.comparison_parameter_slider.setValue(50)
        self.comparison_parameter_slider.setAccessibleName(
            tr("image_browser.compare.parameter")
        )
        self.comparison_parameter_slider.setMinimumWidth(
            AppStyle.compact_input_min_width()
        )
        self.comparison_parameter_slider.valueChanged.connect(
            self._on_comparison_parameter_changed
        )
        self.comparison_parameter_slider.hide()
        self.comparison_parameter_slider.setToolTip(
            tr("image_browser.compare.opacity.tooltip")
        )
        controls_layout.addStretch()

        self.save_calculated_button = QPushButton()
        self.save_calculated_button.setAccessibleName(
            tr("image_browser.compare.save.accessible")
        )
        apply_toolbar_symbol_button_style(self.save_calculated_button)
        self._apply_tool_icon(self.save_calculated_button, 'viewer_save.svg')
        self.save_calculated_button.clicked.connect(self._save_calculated_image)
        self.save_calculated_button.hide()
        controls_layout.addWidget(self.save_calculated_button)

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

        self.comparison_settings_widget = QWidget()
        comparison_settings_layout = QHBoxLayout(self.comparison_settings_widget)
        comparison_settings_layout.setContentsMargins(0, 0, 0, 0)
        comparison_settings_layout.setSpacing(AppStyle.LAYOUT["toolbar_spacing"])
        comparison_settings_layout.addWidget(self.comparison_parameter_label)
        comparison_settings_layout.addWidget(self.comparison_parameter_slider, 1)
        self.comparison_settings_widget.hide()
        layout.addWidget(self.comparison_settings_widget)
        self._update_comparison_controls()

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
        layout.addWidget(base_image_panel, 1)
        return panel

    def _toggle_selected_pinned_image(self) -> None:
        item = self.folder_files_list.currentItem()
        if item is None or item.data(Qt.UserRole + 1) == "dir":
            return
        file_path = item.data(Qt.UserRole)
        if not file_path:
            return

        previous_pinned_path = self.session_manager.collection.pinned_path
        if previous_pinned_path == file_path:
            self.session_manager.unpin()
            self._hold_shows_selected = False
        else:
            existing_index = next(
                (index for index, image in enumerate(self.session_manager.images)
                 if image.path == file_path),
                None,
            )
            if existing_index is None:
                self.session_manager.add_image_reference(file_path)
            else:
                self.session_manager.set_current_index(existing_index)
            pinned = self.session_manager.pin_current(self._lazy_load_callback)
            if pinned is None:
                self.parent_app.show_status(
                    tr("image_browser.compare.pin_failed")
                )
                return
        # Not forced: pinning only rebuilds the list when the pinned file lives
        # outside the folder; otherwise just the row markers change.
        self._refresh_folder_browser(stop_playback=False)
        self._refresh_file_row_markers((previous_pinned_path, file_path))
        self._update_comparison_controls()
        self._update_display()

    def _emoji_icon(self, text: str, opacity: float = 1.0) -> QIcon:
        """Render a symbol into the list's icon slot so all rows share one column."""
        size = self.folder_files_list.iconSize()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setOpacity(opacity)
        font = painter.font()
        font.setPixelSize(round(size.height() * 0.8))
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
        painter.end()
        return QIcon(pixmap)

    def _pin_target_row(self, pos) -> int:
        """Return the file row whose leading pin slot contains ``pos``, else -1."""
        item = self.folder_files_list.itemAt(pos)
        if item is None or item.data(Qt.UserRole + 1) == "dir":
            return -1
        rect = self.folder_files_list.visualItemRect(item)
        slot_width = self.folder_files_list.iconSize().width() + AppStyle.control_px(12)
        if pos.x() > rect.left() + slot_width:
            return -1
        return self.folder_files_list.row(item)

    def _set_pin_hover_row(self, row: int) -> None:
        if row == self._pin_hover_row:
            return
        previous_row = self._pin_hover_row
        self._pin_hover_row = row
        viewport = self.folder_files_list.viewport()
        if row >= 0:
            viewport.setCursor(Qt.PointingHandCursor)
        else:
            viewport.unsetCursor()
        pinned_path = self.session_manager.collection.pinned_path
        for changed_row in (previous_row, row):
            if changed_row >= 0:
                self._apply_file_row_marker(changed_row, pinned_path)

    def _set_hold_shows_selected(self, held: bool) -> None:
        """Show the selected file while held; otherwise rest on the pinned image."""
        if held == self._hold_shows_selected:
            return
        self._hold_shows_selected = held
        if self.session_manager.collection.pinned_path is not None:
            self._update_display()

    def eventFilter(self, watched, event):
        if watched is self.folder_files_list and event.type() in (
            QEvent.KeyPress,
            QEvent.KeyRelease,
        ):
            if event.key() == Qt.Key_Space and not event.modifiers():
                if not event.isAutoRepeat():
                    self._set_hold_shows_selected(
                        event.type() == QEvent.KeyPress
                    )
                event.accept()
                return True
        if watched is self.folder_files_list.viewport():
            if event.type() == QEvent.MouseMove:
                self._set_pin_hover_row(self._pin_target_row(event.pos()))
            elif event.type() == QEvent.Leave:
                self._set_pin_hover_row(-1)
            elif (
                event.type() == QEvent.MouseButtonRelease
                and event.button() == Qt.LeftButton
            ):
                self._set_hold_shows_selected(False)
            elif (
                event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
            ):
                item = self.folder_files_list.itemAt(event.pos())
                if item is not None and item.data(Qt.UserRole + 1) != "dir":
                    if self._pin_target_row(event.pos()) >= 0:
                        self.folder_files_list.setCurrentItem(item)
                        self._toggle_selected_pinned_image()
                        event.accept()
                        return True
                    # Selecting the row on press renders it; release restores A.
                    self._hold_shows_selected = True
                    if item is self.folder_files_list.currentItem():
                        self._update_display()
        return super().eventFilter(watched, event)

    def _update_comparison_controls(self) -> None:
        pinned = self.session_manager.get_pinned_image()
        current = self.session_manager.collection.current_reference
        current_path = current.path if current is not None else None
        selected_item = self.folder_files_list.currentItem()
        has_selected_image = (
            selected_item is not None
            and selected_item.data(Qt.UserRole + 1) != "dir"
            and bool(selected_item.data(Qt.UserRole))
        )
        comparison_available = (
            pinned is not None
            and current is not None
            and current.path != pinned["path"]
            and has_selected_image
            and selected_item.data(Qt.UserRole) == current.path
        )
        for button in self.comparison_buttons.values():
            button.setVisible(comparison_available)
        mode = self.session_manager.collection.comparison_mode
        self.save_calculated_button.setVisible(
            comparison_available and mode in COLOR_MANAGED_COMPARISON_MODES
        )
        if not comparison_available:
            self.comparison_parameter_label.hide()
            self.comparison_parameter_slider.hide()
            self.comparison_settings_widget.hide()
            self.folder_play_button.setVisible(bool(self._folder_browser_paths))
            return

        self.folder_play_button.setVisible(bool(self._folder_browser_paths))
        for mode_name, button in self.comparison_buttons.items():
            button.setChecked(mode.value == mode_name)
        if mode == ComparisonMode.FLICKER:
            self.comparison_parameter_label.setText(
                tr("image_browser.compare.hold.hint")
            )
            self.comparison_parameter_label.setToolTip(
                tr("image_browser.compare.hold.tooltip")
            )
            self.comparison_parameter_label.show()
            self.comparison_parameter_slider.hide()
            self.comparison_settings_widget.hide()
            return
        self.comparison_parameter_label.setToolTip("")
        has_parameter_control = mode in COLOR_MANAGED_COMPARISON_MODES
        self.comparison_parameter_label.setVisible(has_parameter_control)
        self.comparison_parameter_slider.setVisible(has_parameter_control)
        self.comparison_settings_widget.setVisible(has_parameter_control)
        if not has_parameter_control:
            return
        percent = self._comparison_b_percentage(mode)
        accessible_name_id, tooltip_id = {
            ComparisonMode.OPACITY: (
                "image_browser.compare.parameter",
                "image_browser.compare.opacity.tooltip",
            ),
            ComparisonMode.ADD: (
                "image_browser.compare.add.parameter",
                "image_browser.compare.mode.add.tooltip",
            ),
            ComparisonMode.DIFFERENCE: (
                "image_browser.compare.difference.parameter",
                "image_browser.compare.mode.difference.tooltip",
            ),
        }[mode]
        self.comparison_parameter_label.setText(
            self._comparison_parameter_text(mode, percent)
        )
        with QSignalBlocker(self.comparison_parameter_slider):
            self.comparison_parameter_slider.setValue(percent)
        self.comparison_parameter_slider.setAccessibleName(tr(accessible_name_id))
        self.comparison_parameter_slider.setToolTip(tr(tooltip_id))
        self.save_calculated_button.setToolTip(
            tr(
                "image_browser.compare.save.tooltip",
                formula=self.session_manager.collection.comparison_formula(),
            )
        )

    def _save_calculated_image(self) -> None:
        """Save the calculated comparison as a float TIFF in the browsed folder."""
        collection = self.session_manager.collection
        pinned = self.session_manager.get_pinned_image()
        current = self.session_manager.get_current_image(
            load_data=True,
            loader_callback=self._lazy_load_callback,
        )
        if pinned is None or current is None or current["data"] is None:
            return
        try:
            data = collection.calculate_comparison(pinned["data"], current["data"])
        except ValueError as error:
            QMessageBox.warning(
                self,
                tr("image_browser.compare.save.title"),
                tr("image_browser.compare.save.failed", error=str(error)),
            )
            return

        folder = self.folder_path_input.text().strip()
        if not Path(folder).is_dir():
            folder = str(Path(current["path"]).parent)
        file_path, _ = choose_path(
            self,
            tr("image_browser.compare.save.title"),
            mode="save",
            default_name=collection.suggest_comparison_filename(
                pinned["filename"], current["filename"]
            ),
            file_filter=tr("image_browser.compare.save.filter"),
            key="calculated_image",
            start_dir=folder,
        )
        if not file_path:
            return
        target = Path(file_path)
        if not target.suffix:
            target = target.with_suffix(".tiff")
        description = (
            f"SciView calculated image: {collection.comparison_formula()}; "
            f"A={pinned['path']}; B={current['path']}"
        )
        try:
            saved = ImageService().save_array(target, data, description=description)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                tr("image_browser.compare.save.title"),
                tr("image_browser.compare.save.failed", error=str(error)),
            )
            return
        self.parent_app.show_status(
            tr("image_browser.compare.save.complete", path=str(saved))
        )
        self._refresh_folder_browser(stop_playback=False, force=True)

    def _comparison_b_percentage(self, mode: ComparisonMode) -> int:
        """Return the selected image's percentage contribution for ``mode``."""
        collection = self.session_manager.collection
        if mode == ComparisonMode.OPACITY:
            return round(collection.opacity * 100)
        if mode == ComparisonMode.ADD:
            return collection.add_b_percentage
        return collection.subtract_b_percentage

    @staticmethod
    def _comparison_parameter_text(mode: ComparisonMode, percent: int) -> str:
        if mode == ComparisonMode.OPACITY:
            return tr(
                "image_browser.compare.opacity",
                reference_percent=100 - percent,
                percent=percent,
            )
        if mode == ComparisonMode.ADD:
            return tr("image_browser.compare.add.label", percent=percent)
        return tr("image_browser.compare.difference.label", percent=percent)

    def _folder_row_for_path(self, path: str | None) -> int:
        if path is None:
            return -1
        try:
            return self._folder_dir_count + self._folder_list_image_paths.index(path)
        except ValueError:
            return -1

    def _refresh_file_row_markers(self, paths) -> None:
        """Update only the rows for ``paths`` (e.g. the old and new pinned file)."""
        pinned_path = self.session_manager.collection.pinned_path
        for path in paths:
            row = self._folder_row_for_path(path)
            if row >= 0:
                self._apply_file_row_marker(row, pinned_path)

    def _apply_file_row_marker(self, row: int, pinned_path: str | None) -> None:
        item = self.folder_files_list.item(row)
        if item is None or item.data(Qt.UserRole + 1) == "dir":
            return
        file_path = item.data(Qt.UserRole)
        if file_path == pinned_path:
            item.setIcon(self._pin_icon)
            item.setToolTip(tr("image_browser.compare.reference_row.tooltip"))
        else:
            item.setIcon(
                self._pin_preview_icon if row == self._pin_hover_row else self._file_icon
            )
            item.setToolTip(item.text())

    def _set_comparison_mode(self, mode_name: str) -> None:
        mode = ComparisonMode(mode_name)
        collection = self.session_manager.collection
        if collection.comparison_mode == mode:
            # Clicking the active operation again returns to hold-to-compare.
            mode = ComparisonMode.FLICKER
        collection.comparison_mode = mode
        self._comparison_auto_pending = mode in COLOR_MANAGED_COMPARISON_MODES
        self._update_comparison_controls()
        self._update_display()

    def _adjust_overlay_opacity_from_canvas(self, wheel_delta: int) -> None:
        if self.session_manager.collection.comparison_mode != ComparisonMode.OPACITY:
            return
        step = 5 if wheel_delta > 0 else -5
        self.comparison_parameter_slider.setValue(
            self.comparison_parameter_slider.value() + step
        )

    def _on_comparison_parameter_changed(self, value: int) -> None:
        collection = self.session_manager.collection
        mode = collection.comparison_mode
        if mode == ComparisonMode.OPACITY:
            collection.set_opacity(value / 100.0)
        elif mode == ComparisonMode.ADD:
            collection.set_add_b_percentage(value)
        elif mode == ComparisonMode.DIFFERENCE:
            collection.set_subtract_b_percentage(value)
        else:
            return
        self.comparison_parameter_label.setText(
            self._comparison_parameter_text(mode, value)
        )
        self._update_display()

    def _on_split_divider_changed(self, x: float) -> None:
        reference = self.session_manager.get_pinned_image()
        if reference is None or reference["data"].shape[1] == 0:
            return
        fraction = min(max(x / reference["data"].shape[1], 0.0), 1.0)
        self.session_manager.collection.set_split_fraction(fraction)
        self._update_display()

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

        already_added = set(self._added_folder_paths)
        for file_path in file_paths:
            path_str = str(file_path)
            if path_str not in already_added:
                already_added.add(path_str)
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
        self._update_comparison_controls()
        
        if current_image is None:
            self._set_comparison_display_mode(None)
            self.image_viewer.clear_overlays(group="image-comparison")
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
            self._set_comparison_display_mode(None)
            self.image_viewer.clear_overlays(group="image-comparison")
            self.image_viewer.clear_image(loading_message)
            self.annotations.refresh_image()
            self.filename_label.setText(loading_message)
            return
        
        # Extract data and other info from current_image dict
        # Do this before calling update_plot to minimize local references
        image_data = current_image['data']
        filename = current_image['filename']
        source = current_image['source']
        displayed_data = image_data
        title = tr("image_browser.compare.current_label", filename=filename)
        pinned_image = self.session_manager.get_pinned_image()
        mode = self.session_manager.collection.comparison_mode
        comparison_available = (
            pinned_image is not None and pinned_image["path"] != current_image["path"]
        )
        if comparison_available:
            try:
                if mode != ComparisonMode.FLICKER:
                    self._validate_comparison_metadata(pinned_image, current_image)
            except ValueError as error:
                self.image_viewer.clear_comparison_overlay()
                self.parent_app.show_status(
                    tr("image_browser.compare.incompatible", error=str(error))
                )
                comparison_available = False

        if not comparison_available:
            self.save_calculated_button.hide()
            self.image_viewer.remove_overlay("comparison-divider")
            self.image_viewer.clear_comparison_overlay()
            self.image_viewer.clear_overlays(group="image-comparison")
            title = tr("image_browser.compare.current_label", filename=filename)
        else:
            try:
                if mode == ComparisonMode.FLICKER:
                    # Rest on the pinned image; holding a file or playback shows it.
                    if not (
                        self._hold_shows_selected
                        or self.folder_play_timer.isActive()
                    ):
                        displayed_data = pinned_image["data"]
                        title = tr(
                            "image_browser.compare.reference_label",
                            filename=pinned_image["filename"],
                        )
                    else:
                        title = tr(
                            "image_browser.compare.current_label",
                            filename=filename,
                        )
                elif mode == ComparisonMode.SPLIT:
                    displayed_data = compare_image_arrays(
                        pinned_image["data"],
                        image_data,
                        mode,
                        split_fraction=self.session_manager.collection.split_fraction,
                    )
                    title = tr(
                        "image_browser.compare.split_title",
                        reference=pinned_image["filename"],
                        current=filename,
                    )
                elif mode == ComparisonMode.OPACITY:
                    if (
                        np.asarray(pinned_image["data"]).ndim != 2
                        or np.asarray(image_data).ndim != 2
                        or pinned_image["data"].shape != image_data.shape
                    ):
                        raise ValueError(
                            "Overlay images must have matching two-dimensional shapes."
                        )
                    displayed_data = image_data
                    title = tr(
                        "image_browser.compare.overlay_title",
                        reference=pinned_image["filename"],
                        current=filename,
                        reference_percent=100 - self._comparison_b_percentage(mode),
                        percent=self._comparison_b_percentage(mode),
                    )
                elif mode == ComparisonMode.ADD:
                    displayed_data = compare_image_arrays(
                        pinned_image["data"],
                        image_data,
                        mode,
                        current_weight=(
                            self.session_manager.collection.add_b_percentage / 100.0
                        ),
                    )
                    title = tr(
                        "image_browser.compare.add_title",
                        reference=pinned_image["filename"],
                        current=filename,
                        coefficient=format(
                            self.session_manager.collection.add_b_percentage / 100.0,
                            ".2f",
                        ),
                    )
                else:
                    weight = self.session_manager.collection.subtract_b_percentage / 100.0
                    displayed_data = compare_image_arrays(
                        pinned_image["data"],
                        image_data,
                        mode,
                        current_weight=weight,
                    )
                    title = tr(
                        "image_browser.compare.difference_title",
                        reference=pinned_image["filename"],
                        current=filename,
                        coefficient=format(weight, ".2f"),
                    )
            except ValueError as error:
                self.image_viewer.remove_overlay("comparison-divider")
                self.image_viewer.clear_comparison_overlay()
                self.image_viewer.clear_overlays(group="image-comparison")
                self.save_calculated_button.hide()
                self.parent_app.show_status(
                    tr("image_browser.compare.incompatible", error=str(error))
                )
                title = tr("image_browser.compare.current_label", filename=filename)
                comparison_available = False

        display_mode = (
            mode
            if comparison_available and mode in COLOR_MANAGED_COMPARISON_MODES
            else None
        )
        if display_mode is not None and (
            self._comparison_auto_pending
            or self._active_display_levels(display_mode) is None
        ):
            auto_values = (
                np.concatenate(
                    (np.ravel(pinned_image["data"]), np.ravel(image_data))
                )
                if display_mode == ComparisonMode.OPACITY
                else displayed_data
            )
            self._auto_comparison_display(display_mode, auto_values)
        self._comparison_auto_pending = False
        self._set_comparison_display_mode(display_mode)

        self._updating_comparison_display = display_mode is not None
        try:
            self.update_plot(displayed_data)
            if display_mode == ComparisonMode.OPACITY:
                self.image_viewer.set_comparison_overlay(
                    pinned_image["data"],
                    1.0 - self.session_manager.collection.opacity,
                )
        finally:
            self._updating_comparison_display = False

        if not (comparison_available and mode == ComparisonMode.SPLIT):
            self.image_viewer.clear_overlays(group="image-comparison")
        else:
            # Keep the divider item alive so an active mouse drag continues;
            # side labels only make sense where both images share the canvas.
            width = image_data.shape[1]
            self.image_viewer.set_vertical_divider(
                "comparison-divider",
                width * self.session_manager.collection.split_fraction,
                self._on_split_divider_changed,
                group="image-comparison",
            )
            self.image_viewer.set_text_overlay(
                "comparison-label-a",
                1.0,
                1.0,
                tr("image_browser.compare.reference_marker"),
                group="image-comparison",
            )
            self.image_viewer.set_text_overlay(
                "comparison-label-b",
                max(1.0, width - 1.0),
                1.0,
                tr("image_browser.compare.current_marker"),
                group="image-comparison",
                anchor=(1.0, 0.0),
            )

        self.image_viewer.set_title(title)
        self.filename_label.setText(
            tr(
                "image_browser.image.filename_source",
                filename=title,
                source=source,
            )
        )

    @staticmethod
    def _validate_comparison_metadata(reference: dict, current: dict) -> None:
        """Reject known detector or coordinate-frame mismatches without resampling."""
        reference_metadata = reference.get("metadata", {})
        current_metadata = current.get("metadata", {})
        for key in ("detector", "profile", "coordinate_frame", "pixel_size_um"):
            reference_value = reference_metadata.get(key)
            current_value = current_metadata.get(key)
            if reference_value is not None or current_value is not None:
                if reference_value != current_value:
                    raise ValueError(
                        "Images have different or incomplete pixel-coordinate metadata."
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

        # The folder browser list was just read from disk, so its files exist.
        for p in self._folder_browser_paths:
            if p not in seen:
                seen.add(p)
                result.append(p)

        # Files explicitly added via "+ Add All", possibly from other folders.
        for p in self._added_folder_paths:
            if p not in seen and os.path.isfile(p):
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

    def _list_current_folder(self) -> FolderListing:
        """Read the selected folder once, applying the filter and sort controls."""
        folder_path = self.folder_path_input.text().strip()
        empty = FolderListing(directory=Path(folder_path), file_names=(), subfolder_names=())
        if not folder_path or not Path(folder_path).is_dir():
            return empty
        sort_mode = (
            self.folder_sort_combo.currentData()
            if hasattr(self, 'folder_sort_combo')
            else "name_asc"
        ) or "name_asc"
        try:
            return list_folder(
                folder_path,
                patterns=SUPPORTED_FORMATS['image_files'].split(),
                name_filter=self.pattern_input.text(),
                sort_by="mtime" if sort_mode.startswith("mtime") else "name",
                descending=sort_mode.endswith("_desc"),
            )
        except OSError:
            return empty

    def _get_folder_image_paths(self):
        """Return supported image paths from the selected folder after filter and sort."""
        return list(self._list_current_folder().files)

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

        listing = self._list_current_folder()
        pinned_reference = self.session_manager.collection.pinned_reference
        pinned_outside_folder = None
        if pinned_reference is not None:
            pinned_name = Path(pinned_reference.path).name
            in_folder = (
                pinned_name in listing.file_names
                and str(listing.directory / pinned_name) == pinned_reference.path
            )
            if not in_folder:
                pinned_outside_folder = pinned_reference.path
        # Polling compares plain names first; building 10,000+ paths for an
        # unchanged folder would otherwise dominate each auto-refresh.
        listing_key = (
            str(listing.directory),
            listing.file_names,
            listing.subfolder_names,
            pinned_outside_folder,
        )
        if not force and listing_key == self._folder_listing_key:
            if self.folder_path_input.text() and hasattr(self, 'loading_status_label'):
                self.loading_status_label.setText(
                    tr(
                        "image_browser.folder.status.found_images",
                        count=len(listing.file_names),
                    )
                )
            # Nothing changed, so other tabs already hold this list.
            return
        self._folder_listing_key = listing_key

        directory_text = str(listing.directory)
        path_strings = [
            os.path.join(directory_text, name) for name in listing.file_names
        ]
        display_image_paths = list(path_strings)
        if pinned_outside_folder is not None:
            display_image_paths.append(pinned_outside_folder)
        subfolder_strings = [
            os.path.join(directory_text, name) for name in listing.subfolder_names
        ]

        current_item = self.folder_files_list.currentItem()
        current_path = current_item.data(Qt.UserRole) if current_item is not None else None

        folder_icon = self.style().standardIcon(QStyle.SP_DirIcon)
        with QSignalBlocker(self.folder_files_list):
            self.folder_files_list.clear()
            self._pin_hover_row = -1
            for name, subfolder_path in zip(listing.subfolder_names, subfolder_strings):
                item = QListWidgetItem(folder_icon, name)
                item.setData(Qt.UserRole, subfolder_path)
                item.setData(Qt.UserRole + 1, "dir")
                self.folder_files_list.addItem(item)
            for name, file_path in zip(listing.file_names, path_strings):
                item = QListWidgetItem(self._file_icon, name)
                item.setData(Qt.UserRole, file_path)
                item.setToolTip(name)
                self.folder_files_list.addItem(item)
            if pinned_outside_folder is not None:
                pinned_item = QListWidgetItem(pinned_reference.filename)
                pinned_item.setData(Qt.UserRole, pinned_reference.path)
                self.folder_files_list.addItem(pinned_item)
            if current_path in display_image_paths:
                self.folder_files_list.setCurrentRow(
                    len(subfolder_strings) + display_image_paths.index(current_path)
                )

        self._folder_dir_count = len(subfolder_strings)
        self._folder_browser_dirs = subfolder_strings
        self._folder_browser_paths = path_strings
        self._folder_list_image_paths = display_image_paths
        # New rows already show the plain file icon; only the pinned row differs.
        self._refresh_file_row_markers(
            (pinned_reference.path,) if pinned_reference is not None else ()
        )
        self._update_comparison_controls()
        file_count = len(path_strings)
        folder_count = len(subfolder_strings)
        image_count_id = (
            "image_browser.folder.count.one_image"
            if file_count == 1
            else "image_browser.folder.count.images"
        )
        folder_count_id = (
            "image_browser.folder.count.one_folder"
            if folder_count == 1
            else "image_browser.folder.count.folders"
        )
        count_parts = [tr(image_count_id, count=file_count)]
        if folder_count:
            count_parts.append(tr(folder_count_id, count=folder_count))
        self.folder_contents_count_label.setText(" · ".join(count_parts))

        if self.folder_path_input.text() and hasattr(self, 'loading_status_label'):
            self.loading_status_label.setText(
                tr("image_browser.folder.status.found_images", count=file_count)
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
            (
                index for index, image in enumerate(self.session_manager.images)
                if image.path == file_path
            ),
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
        self._update_comparison_controls()

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
        if not self._folder_browser_paths:
            self.folder_play_button.setChecked(False)
            return

        if self.folder_play_button.isChecked():
            folder_image_end = self._folder_dir_count + len(self._folder_browser_paths)
            if not self._folder_dir_count <= self.folder_files_list.currentRow() < folder_image_end:
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
        was_playing = False
        if hasattr(self, 'folder_play_timer'):
            was_playing = self.folder_play_timer.isActive()
            self.folder_play_timer.stop()
        if hasattr(self, 'folder_play_button'):
            self.folder_play_button.setChecked(False)
            self.folder_play_button.setToolTip(tr("image_browser.play.tooltip"))
            self._apply_tool_icon(self.folder_play_button, 'tool_play.svg')
        if was_playing and self.session_manager.collection.pinned_path is not None:
            self._update_display()

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
            (getattr(self, 'save_calculated_button', None), 'viewer_save.svg'),
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
        folder_image_end = self._folder_dir_count + len(self._folder_browser_paths)
        if not self._folder_browser_paths:
            self._stop_folder_playback()
            return

        next_row = self.folder_files_list.currentRow() + 1
        if next_row >= folder_image_end:
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
                    f.write(f"{img.path}\n")
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
        
