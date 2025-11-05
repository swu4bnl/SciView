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
    QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
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


class ImageLoadWorker(QThread):
    """Background worker for loading images without blocking UI"""
    tiled_manager = tiled_manager

    progress_updated = pyqtSignal(int, str)  # progress, status message
    image_loaded = pyqtSignal(object, str)   # image_data, file_path
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
        """Load images from folder with pattern matching"""
        folder_path = self.kwargs['folder_path']
        pattern = self.kwargs['pattern']
        
        # Find matching files
        search_pattern = os.path.join(folder_path, pattern)
        file_paths = glob.glob(search_pattern)
        file_paths.sort()  # Sort for consistent ordering
        
        total_files = len(file_paths)
        self.progress_updated.emit(0, f"Found {total_files} matching files")
        
        for i, file_path in enumerate(file_paths):
            if self.is_cancelled:
                break
                
            try:
                # Load image data
                image_data = self._load_image_file(file_path)
                if image_data is not None:
                    self.image_loaded.emit(image_data, file_path)
                
                # Update progress
                progress = int((i + 1) * 100 / total_files)
                self.progress_updated.emit(progress, f"Loaded {i+1}/{total_files}: {os.path.basename(file_path)}")
                
            except Exception as e:
                self.error_occurred.emit(f"Error loading {file_path}: {str(e)}")
    
    def _load_from_tiled(self):
        """Load images from tiled client using scan ID"""
        if not self.tiled_manager.is_available():
            self.error_occurred.emit("Tiled client is not available")
            return
        
        # Use configuration-based defaults from the manager
        default_profile, default_detector = self.tiled_manager.get_default_settings()
        
        profile_name = self.kwargs.get('profile', default_profile)
        scan_id = self.kwargs['scan_id']
        detector = self.kwargs.get('detector', default_detector)
        
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
                self.error_occurred.emit(error_msg)
                return
            
            self.progress_updated.emit(80, "Reading image data...")
            
            # Convert image shape for display compatibility
            image_array = self._convert_image_shape(image_array)
            
            self.progress_updated.emit(90, "Processing image data...")
            
            # Create pseudo file path for tracking with metadata
            pseudo_path = self.tiled_manager.create_pseudo_path(scan_id, detector, profile_name)
            
            # Emit the loaded image with metadata
            self.image_loaded.emit(image_array, pseudo_path)
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
                self.image_loaded.emit(image_data, file_path)
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
        Convert image array to standard 2D format for display
        
        Handles various input shapes:
        - (1, 1, H, W) -> (H, W) - Single frame from tiled
        - (N, H, W) -> (H, W) - Time series, take first frame  
        - (H, W, 3) -> (H, W) - RGB to grayscale
        - (H, W, 4) -> (H, W) - RGBA to grayscale
        - (H, W) -> (H, W) - Already 2D, no change
        
        Args:
            image_array: Input image array with arbitrary shape
            
        Returns:
            numpy.ndarray: 2D image array suitable for analysis
        """
        if image_array is None:
            return None
        
        # Convert to numpy array if not already
        if not isinstance(image_array, np.ndarray):
            image_array = np.array(image_array)
        
        original_shape = image_array.shape
        print(f"Converting image shape from {original_shape}")
        
        # Handle different dimensionalities
        if image_array.ndim == 2:
            # Already 2D - perfect
            converted = image_array
            
        elif image_array.ndim == 3:
            # Three possibilities: (N, H, W), (H, W, 3), or (H, W, 4)
            if image_array.shape[2] in [3, 4]:
                # RGB or RGBA image: (H, W, 3/4) -> (H, W)
                if image_array.shape[2] == 3:
                    # RGB to grayscale using standard weights
                    converted = np.dot(image_array[...,:3], [0.2989, 0.5870, 0.1140])
                else:  # RGBA
                    # RGBA to grayscale (ignore alpha channel)
                    converted = np.dot(image_array[...,:3], [0.2989, 0.5870, 0.1140])
            else:
                # Time series or stack: (N, H, W) -> (H, W)
                # Take the first frame
                converted = image_array[0]
                print(f"Time series detected: taking first frame from {image_array.shape[0]} frames")
                
        elif image_array.ndim == 4:
            # Handle 4D arrays: (1, 1, H, W) or (N, 1, H, W) or (1, N, H, W) etc.
            if image_array.shape[0] == 1 and image_array.shape[1] == 1:
                # Single frame: (1, 1, H, W) -> (H, W)
                converted = image_array[0, 0]
            elif image_array.shape[0] == 1:
                # (1, N, H, W) -> take first of N
                converted = image_array[0, 0]
            elif image_array.shape[1] == 1:
                # (N, 1, H, W) -> take first of N  
                converted = image_array[0, 0]
            else:
                # (N, M, H, W) -> take first frame
                converted = image_array[0, 0]
                print(f"4D array detected: taking first frame from shape {original_shape}")
                
        elif image_array.ndim == 5:
            # Handle 5D arrays: take first frame
            converted = image_array[0, 0, 0]
            print(f"5D array detected: taking first frame from shape {original_shape}")
            
        else:
            # Fallback: flatten extra dimensions
            while image_array.ndim > 2:
                image_array = image_array[0]
            converted = image_array
            print(f"High-dimensional array flattened from {original_shape} to {converted.shape}")
        
        # Ensure we have a 2D array
        if converted.ndim != 2:
            raise ValueError(f"Failed to convert to 2D: resulting shape is {converted.shape}")
        
        # Convert data type to float for analysis
        if converted.dtype in [np.uint8, np.uint16, np.uint32]:
            converted = converted.astype(np.float64)
        elif converted.dtype in [np.int8, np.int16, np.int32]:
            converted = converted.astype(np.float64)
        
        print(f"Image conversion complete: {original_shape} -> {converted.shape}, dtype: {converted.dtype}")
        return converted


class ImageSessionManager:
    """Manages the list of images loaded in the current session"""
    
    def __init__(self):
        self.images = []  # List of image metadata dicts
        self.current_index = -1
        self.callbacks = []  # Callbacks for when image list changes
    
    def add_image(self, image_data, file_path, metadata=None):
        """Add an image to the session"""
        image_info = {
            'data': image_data,
            'path': file_path,
            'filename': os.path.basename(file_path),
            'timestamp': np.datetime64('now'),
            'metadata': metadata or {},
            'size': image_data.shape if hasattr(image_data, 'shape') else None,
            'source': self._determine_source(file_path)
        }
        
        self.images.append(image_info)
        self.current_index = len(self.images) - 1
        self._notify_callbacks()
    
    def get_current_image(self):
        """Get the currently selected image"""
        if 0 <= self.current_index < len(self.images):
            return self.images[self.current_index]
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
            self.images.pop(index)
            if self.current_index >= len(self.images):
                self.current_index = len(self.images) - 1
            elif self.current_index > index:
                self.current_index -= 1
            self._notify_callbacks()
    
    def clear_session(self):
        """Clear all images from session"""
        self.images.clear()
        self.current_index = -1
        self._notify_callbacks()
    
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


class ImageBrowserApp(BaseImageTab):
    """Image Browser application widget with multiple loading options"""
    
    def __init__(self, parent_app):
        super().__init__(parent_app)
        
        # Session manager for image tracking
        self.session_manager = ImageSessionManager()
        self.session_manager.add_callback(self._on_session_changed)
        
        # Loading worker
        self.load_worker = None
        
        # Tiled client cache for persistent connections
        self.tiled_manager = tiled_manager
        self.tiled_client = None
        self.current_tiled_profile = None
        
        # Build UI
        self._build_ui()
        
        # Connect to parent app for synchronization
        self._setup_parent_sync()

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
        
        # Tab 2: Tiled client
        tiled_tab = self._create_tiled_loading_tab()
        self.loading_tabs.addTab(tiled_tab, "Tiled")
        if not self.tiled_manager.is_available():
            self.loading_tabs.setTabEnabled(1, False)
        
        # Tab 3: Folder browser
        folder_tab = self._create_folder_loading_tab()
        self.loading_tabs.addTab(folder_tab, "Folder")
        
        layout.addWidget(self.loading_tabs)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
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
        
        # Scan ID input
        layout.addWidget(QLabel("Scan ID:"))
        self.scan_id_input = QSpinBox()
        self.scan_id_input.setRange(-9999999, 9999999)
        # Use configuration-based default instead of hardcoded value
        from config.beamline_config import IMAGE_BROWSER_SETTINGS
        self.scan_id_input.setValue(IMAGE_BROWSER_SETTINGS['default_scan_id'])
        layout.addWidget(self.scan_id_input)
        
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
        self.pattern_input = QLineEdit("*.tif")
        self.pattern_input.setPlaceholderText("e.g., *.tiff, *saxs*.tif, sample_*.h5")
        layout.addWidget(self.pattern_input)
        
        # Preview matching files
        btn_preview = QPushButton("Preview Files")
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
        self.sync_button = QPushButton("Send to Other Tabs")
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
        layout.addWidget(self.session_table)
        
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
        """Load multiple image files"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Load Images", "", SUPPORTED_FORMATS['image_files']
        )
        
        if file_paths:
            for file_path in file_paths:
                self._start_loading('file', file_path=file_path)

    def _load_from_tiled(self):
        """Load image from tiled client"""
        current_data = self.tiled_profile_combo.currentData()
        # Use config-based default instead of hardcoded
        from config.beamline_config import get_default_tiled_settings
        default_profile, _ = get_default_tiled_settings()
        profile = current_data if current_data else default_profile
        scan_id = self.scan_id_input.value()
        detector = self.detector_combo.currentText()
        
        # Extract detector key if it's in "key - description" format
        if ' - ' in detector:
            detector = detector.split(' - ')[0]
        
        self._start_loading('tiled', profile=profile, scan_id=scan_id, detector=detector)

    def _on_profile_changed(self):
        """Handle profile selection change"""
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
        """Load images from folder"""
        #TODO: only load file path list first, then load on demand upon navigation
        folder_path = self.folder_path_input.text()
        pattern = self.pattern_input.text()
        
        if not folder_path or not pattern:
            QMessageBox.warning(self, "Input Required", "Please select folder and pattern")
            return
        
        self._start_loading('folder', folder_path=folder_path, pattern=pattern)

    def _start_loading(self, method, **kwargs):
        """Start background loading operation"""
        if self.load_worker and self.load_worker.isRunning():
            self.load_worker.cancel()
            self.load_worker.wait()
        
        self.load_worker = ImageLoadWorker(method, **kwargs)
        self.load_worker.progress_updated.connect(self._on_loading_progress)
        self.load_worker.image_loaded.connect(self._on_image_loaded)
        self.load_worker.loading_finished.connect(self._on_loading_finished)
        self.load_worker.error_occurred.connect(self._on_loading_error)
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.load_worker.start()

    # Event Handlers
    def _on_loading_progress(self, progress, message):
        """Handle loading progress updates"""
        self.progress_bar.setValue(progress)
        self.loading_status_label.setText(message)

    def _on_image_loaded(self, image_data, file_path):
        """Handle successful image loading"""
        self.session_manager.add_image(image_data, file_path)
        # Use _update_display to properly set self.image_data and display
        self._update_display()

    def _on_loading_finished(self):
        """Handle loading completion"""
        self.progress_bar.setVisible(False)
        self.loading_status_label.setText("Loading complete")

    def _on_loading_error(self, error_message):
        """Handle loading errors"""
        self.progress_bar.setVisible(False)
        self.loading_status_label.setText(f"Error: {error_message}")
        QMessageBox.warning(self, "Loading Error", error_message)

    def _on_session_changed(self, session_manager):
        """Handle session changes"""
        self._update_session_table()
        self._update_navigation_controls()
        # Use _update_display to properly set self.image_data and display
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
        """Update the image display using unified system"""
        current_image = self.session_manager.get_current_image()
        
        if current_image is None:
            self.ax_raw.clear()
            self.ax_raw.text(0.5, 0.5, 'No Image Loaded', 
                        transform=self.ax_raw.transAxes, ha='center', va='center')
            self.current_image_label.setText("No image loaded")
            self.canvas_raw.draw()
            return
        
        # Set the image data for the unified display system
        self.image_data = current_image['data']
        
        # Use the unified display system from base class
        self.update_plot()
        
        # Set title and update current image label
        self.ax_raw.set_title(current_image['filename'], fontsize=10)
        self.current_image_label.setText(f"File: {current_image['filename']} | Source: {current_image['source']}")
        
        # Final canvas refresh
        self.canvas_raw.draw()

    def _sync_to_parent(self):
        """Sync current image to parent application and other tabs"""
        current_image = self.session_manager.get_current_image()
        if current_image is None:
            return
        
        # Convert numpy array to SciAnalysis Data2DScattering object if needed
        try:
            image_data_obj = self._convert_to_scianalysis_format(current_image['data'], current_image['path'])
            
            # Debug: Check what type of object we got
            print(f"DEBUG: Converted image data type: {type(image_data_obj)}")
            if hasattr(image_data_obj, 'circular_average_q_bin'):
                print("DEBUG: Object has circular_average_q_bin method")
            else:
                print("DEBUG: Object missing circular_average_q_bin method")
                # If conversion failed, return the original numpy array and show warning
                if isinstance(current_image['data'], type(image_data_obj)):
                    print("DEBUG: Conversion returned same type - using raw numpy array")
                    image_data_obj = current_image['data']
                
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
            if hasattr(tab, 'image_data') and tab != self:
                tab.image_data = image_data_obj
                if hasattr(tab, 'populate_image_info'):
                    tab.populate_image_info(image_data_obj, current_image['path'])
                if hasattr(tab, 'update_plot'):
                    # Only call update_plot if the object has the required methods
                    if hasattr(image_data_obj, 'circular_average_q_bin'):
                        tab.update_plot()
                    else:
                        print(f"DEBUG: Skipping update_plot for tab {i} - image_data lacks SciAnalysis methods")
        
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
        """Preview files in selected folder"""
        folder_path = self.folder_path_input.text()
        pattern = self.pattern_input.text()
        
        if not folder_path or not pattern:
            return
        
        search_pattern = os.path.join(folder_path, pattern)
        file_paths = glob.glob(search_pattern)
        file_paths.sort()
        
        self.folder_files_list.clear()
        for file_path in file_paths[:self.max_files_input.value()]:
            self.folder_files_list.addItem(os.path.basename(file_path))

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
        
        current_image = self.session_manager.get_current_image()
        if current_image:
            info_lines.append(f"Current: {current_image['filename']}")
            info_lines.append(f"Source: {current_image['source']}")
            if current_image['size']:
                info_lines.append(f"Dimensions: {current_image['size'][0]} x {current_image['size'][1]}")

    def _load_recent_file(self, item):
        """Load a file from recent files list"""
        # Placeholder for recent files functionality
        pass