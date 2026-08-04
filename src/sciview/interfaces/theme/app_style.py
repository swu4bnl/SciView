"""
Global Qt Style Configuration

Centralized styling configuration for the SciAnalysis GUI application.
This module provides consistent styling across all tabs and components.
"""

from pathlib import Path

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QIcon


class AppStyle:
    """Global application styling configuration"""

    ASSETS_RELATIVE_DIR = Path("src/sciview/interfaces/theme/assets")

    TAB_UI = {
        'icon_size': 18,
        'min_width': 112,
        'min_height': 34,
        'padding_vertical': 5,
        'padding_horizontal': 10,
        'font_size': 12,
    }

    CORNER_BUTTON_UI = {
        'icon_size': 20,
        'button_width': 36,
        'button_height': 30,
        'spacing': 4,
    }

    TOOLBAR_BUTTON_UI = {
        'symbol_width': 36,
        'symbol_height': 34,
        'mask_tool_width': 44,
        'mask_tool_height': 40,
        'mask_tool_icon_size': 28,
        'text_min_width': 64,
        'text_height': 34,
        'symbol_font_size': '20px',
        'text_font_size': '11px',
        'font_weight': 400,
        'padding_horizontal': 8,
    }

    FORM_UI = {
        'section_label_width': 58,
        'field_label_width': 48,
        'input_min_width': 92,
    }

    CORNER_ICON_FILES = {
        'refresh': 'refresh.svg',
        'app_update': 'app_update.svg',
        'sci_update': 'sci_update.svg',
    }

    TAB_ICON_FILES = {
        'image_browser': 'tab_image_browser.svg',
        'tiled_browser': 'tab_tiled_browser.svg',
        'calibration': 'tab_calibration.svg',
        'mask_editing': 'tab_mask_editing.svg',
        'reduction': 'tab_reduction.svg',
        'transform': 'tab_transform.svg',
        'batch': 'tab_batch.svg',
        'info': 'tab_info.svg',
    }
    
    # Modern color scheme - inspired by VS Code Dark and Material Design
    COLORS = {
        'primary': '#0078D4',      # Microsoft Blue
        'secondary': '#106EBE',    # Darker blue
        'accent': '#00BCF2',       # Light blue accent
        'success': '#16C60C',      # Green
        'warning': '#FFB900',      # Orange
        'error': '#D13438',        # Red
        'background': '#FFFFFF',   # White background
        'surface': '#F8F9FA',      # Very light gray
        'surface_alt': '#E9ECEF',  # Light gray
        'border': '#DEE2E6',       # Border gray
        'border_active': '#0078D4', # Active border
        'text_primary': '#212529', # Dark text
        'text_secondary': '#6C757D', # Medium gray text
        'text_muted': '#ADB5BD',   # Light gray text
        'shadow': 'rgba(0, 0, 0, 0.1)' # Subtle shadow
    }
    
    # Typography
    FONTS = {
        'title': '16px',
        'subtitle': '14px', 
        'body': '11px',
        'caption': '10px',
        'small': '9px'
    }
    
    # ---------------------------------------------------------------------------
    # CSS_TOKENS — values injected into QSS WIDGET_STYLES strings.
    # Hot-reloadable: changing these and calling apply_global_style() takes
    # effect instantly without rebuilding any widgets.
    # ---------------------------------------------------------------------------
    CSS_TOKENS: dict = {
        # Text / label spacing
        'label_padding_v': 1,     # vertical padding on text labels
        'label_padding_h': 0,     # horizontal padding on text labels
        # Button spacing
        'btn_padding_v': 3,       # vertical padding on buttons
        'btn_padding_h': 8,       # horizontal padding on buttons
        # Input / combo spacing
        'input_padding_v': 2,     # vertical padding on inputs / combos
        'input_padding_h': 4,     # horizontal padding on inputs / combos
        # GroupBox spacing
        'group_margin_top': 6,    # QGroupBox outer top margin
        'group_padding_top': 10,  # QGroupBox inner top padding
        'group_title_left': 6,    # QGroupBox title indent
        'group_title_padding': 3, # QGroupBox title side padding
        # Dimension hints used as CSS min-height / border-radius
        'border_radius': 2,
        'button_height': 26,
        'input_height': 22,
    }

    # ---------------------------------------------------------------------------
    # LAYOUT — Python construction-time parameters.
    # These are passed to setContentsMargins(), setSpacing(), setHandleWidth(),
    # setMinimumWidth() etc. at widget build time.
    # Changing them requires a tab rebuild (Ctrl+R) to take effect.
    # ---------------------------------------------------------------------------
    LAYOUT: dict = {
        # Splitter ratios
        'main_splitter_ratio': [2, 1],
        'viz_splitter_ratio': [2, 1],
        'controls_splitter_ratio': [1, 1, 2, 1],
        'browser_controls_ratio': [2, 1],
        'tiled_main_splitter_ratio': [1, 2],
        # Tiled browser panel constraints
        'tiled_controls_min_width': 280,
        'tiled_controls_max_width': 460,
        'tiled_metadata_max_height': 72,
        'tiled_results_min_height': 260,
        'tiled_results_column_widths': [70, 100, 150, 95, 85, 120, 60, 145],
        # Mask panel ratios
        'mask_controls_ratio': [10, 15, 12, 10, 10],
        # Splitter handle (also used in CSS via format_style; kept here so
        # setup_splitter_layout can read it for setHandleWidth())
        'splitter_handle_width': 5,
        # Panel minimums
        'control_panel_min_height': 80,
        # Python layout spacing (setContentsMargins / setSpacing)
        'panel_margin': 4,
        'panel_spacing': 3,
        'toolbar_spacing': 4,
        # Image browser specifics
        'image_browser_current_label_max_height': 30,
        'image_browser_sync_button_height': 60,
    }
    
    # Widget styles — padding/margin values come from LAYOUT spacing tokens
    WIDGET_STYLES = {
        'title_label': """
            font-weight: 600;
            font-size: {title_font};
            color: {text_primary};
            padding: {label_padding_v}px {label_padding_h}px;
            border-bottom: 2px solid {surface_alt};
            margin-bottom: 0px;
        """,
        
        'subtitle_label': """
            font-weight: 500;
            font-size: {subtitle_font};
            color: {text_primary};
            padding: {label_padding_v}px {label_padding_h}px;
            margin-bottom: 0px;
        """,

        'body_text': """
            font-size: {body_font};
            color: {text_primary};
            padding: {label_padding_v}px {label_padding_h}px;
        """,

        'small_text': """
            font-size: {small};
            color: {text_secondary};
            padding: {label_padding_v}px {label_padding_h}px;
        """,

        'info_label': """
            font-size: {body_font};
            color: {text_secondary};
            padding: {label_padding_v}px {label_padding_h}px;
            line-height: 1.2;
        """,

        'status_label': """
            font-size: {caption_font};
            color: {text_secondary};
            background-color: {surface};
            padding: {label_padding_v}px {btn_padding_h}px;
            border: 1px solid {border};
            border-radius: {border_radius}px;
            margin: {label_padding_v}px 0px;
        """,

        'primary_button': """
            QPushButton {{
                background-color: {primary};
                color: white;
                font-weight: 500;
                font-size: {body_font};
                border: none;
                padding: {btn_padding_v}px {btn_padding_h}px;
                border-radius: {border_radius}px;
                min-height: {button_height}px;
            }}
            QPushButton:hover {{
                background-color: {secondary};
            }}
            QPushButton:pressed {{
                background-color: {secondary};
            }}
            QPushButton:disabled {{
                background-color: {surface_alt};
                color: {text_muted};
            }}
        """,

        'secondary_button': """
            QPushButton {{
                background-color: {surface};
                color: {text_primary};
                font-size: {body_font};
                border: 1px solid {border};
                padding: {btn_padding_v}px {btn_padding_h}px;
                border-radius: {border_radius}px;
                min-height: {button_height}px;
            }}
            QPushButton:hover {{
                background-color: {surface_alt};
                border-color: {border_active};
            }}
            QPushButton:pressed {{
                background-color: {border};
            }}
        """,

        'sync_button': """
            QPushButton {{
                background-color: {success};
                color: white;
                font-weight: 600;
                font-size: {subtitle_font};
                border: none;
                padding: {btn_padding_v}px {btn_padding_h}px;
                border-radius: {border_radius}px;
                min-height: {button_height}px;
            }}
            QPushButton:hover {{
                background-color: #14B10C;
            }}
            QPushButton:pressed {{
                background-color: #12A00B;
            }}
            QPushButton:disabled {{
                background-color: {surface_alt};
                color: {text_muted};
            }}
        """,

        'input_field': """
            QLineEdit, QSpinBox, QDoubleSpinBox {{
                border: 1px solid {border};
                border-radius: 4px;
                padding: {input_padding_v}px {input_padding_h}px;
                font-size: {body_font};
                background-color: white;
                min-height: {input_height}px;
            }}
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 2px solid {border_active};
                background-color: white;
            }}
            QComboBox {{
                border: 1px solid {border};
                border-radius: 4px;
                padding: {input_padding_v}px {input_padding_h}px;
                font-size: {body_font};
                background-color: white;
                min-height: {input_height}px;
            }}
            QComboBox:focus {{
                border: 2px solid {border_active};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                width: 12px;
                height: 12px;
            }}
        """,

        'group_box': """
            QGroupBox {{
                font-weight: 500;
                font-size: {subtitle_font};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {border_radius}px;
                margin-top: {group_margin_top}px;
                padding-top: {group_padding_top}px;
                background-color: {surface};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {group_title_left}px;
                padding: 0 {group_title_padding}px 0 {group_title_padding}px;
                background-color: {surface};
            }}
        """,
        
        'splitter': """
            QSplitter::handle {{
                background-color: {border};
                border: 1px solid {text_muted};
                border-radius: 2px;
            }}
            QSplitter::handle:horizontal {{
                width: {handle_width}px;
                margin: 1px 0px;
            }}
            QSplitter::handle:vertical {{
                height: {handle_width}px;
                margin: 0px 1px;
            }}
            QSplitter::handle:hover {{
                background-color: {border_active};
                border-color: {border_active};
            }}
            QSplitter::handle:pressed {{
                background-color: {primary};
                border-color: {primary};
            }}
        """,

        'toolbar_symbol_button': """
            QPushButton {{
                background-color: {surface};
                color: {text_primary};
                font-size: {toolbar_symbol_font_size};
                font-weight: {toolbar_font_weight};
                padding: 0;
                border: 1px solid {border};
                border-radius: {border_radius}px;
            }}
            QPushButton:hover {{
                background-color: {surface_alt};
                border-color: {border_active};
            }}
            QPushButton:pressed {{
                background-color: {border};
            }}
            QPushButton:checked {{
                background-color: {border_active};
                color: white;
                border-color: {border_active};
            }}
            QPushButton:disabled {{
                background-color: {surface_alt};
                color: {text_muted};
                border-color: {border};
            }}
        """,

        'toolbar_text_button': """
            QPushButton {{
                background-color: {surface};
                color: {text_primary};
                font-size: {toolbar_text_font_size};
                font-weight: {toolbar_font_weight};
                padding: 0 {toolbar_padding_horizontal}px;
                border: 1px solid {border};
                border-radius: {border_radius}px;
            }}
            QPushButton:hover {{
                background-color: {surface_alt};
                border-color: {border_active};
            }}
            QPushButton:pressed {{
                background-color: {border};
            }}
            QPushButton:checked {{
                background-color: {border_active};
                color: white;
                border-color: {border_active};
            }}
            QPushButton:disabled {{
                background-color: {surface_alt};
                color: {text_muted};
                border-color: {border};
            }}
        """
    }

    @classmethod
    def format_style(cls, style_key, **extra_vars):
        """Format a style string with color and font variables"""
        style = cls.WIDGET_STYLES[style_key]
        
        # Prepare format variables
        format_vars = {
            # Colors
            'primary': cls.COLORS['primary'],
            'secondary': cls.COLORS['secondary'],
            'accent': cls.COLORS['accent'],
            'background': cls.COLORS['background'],
            'surface': cls.COLORS['surface'],
            'border': cls.COLORS['border'],
            'text_primary': cls.COLORS['text_primary'],
            'text_secondary': cls.COLORS['text_secondary'],
            
            # Colors - add new color variables
            'surface_alt': cls.COLORS['surface_alt'],
            'border_active': cls.COLORS['border_active'],
            'text_muted': cls.COLORS['text_muted'],
            'success': cls.COLORS['success'],
            'shadow': cls.COLORS['shadow'],
            
            # Fonts
            'title_font': cls.FONTS['title'],
            'subtitle_font': cls.FONTS['subtitle'],
            'body_font': cls.FONTS['body'],
            'caption_font': cls.FONTS['caption'],
            'small': cls.FONTS['small'],
            
            # LAYOUT: splitter handle width (CSS + Python both need this)
            'handle_width': cls.LAYOUT['splitter_handle_width'],
            # CSS_TOKENS: all spacing / sizing tokens injected into QSS
            **cls.CSS_TOKENS,

            # Toolbar controls
            'toolbar_symbol_font_size': cls.TOOLBAR_BUTTON_UI['symbol_font_size'],
            'toolbar_text_font_size': cls.TOOLBAR_BUTTON_UI['text_font_size'],
            'toolbar_font_weight': cls.TOOLBAR_BUTTON_UI['font_weight'],
            'toolbar_padding_horizontal': cls.TOOLBAR_BUTTON_UI['padding_horizontal'],
            
            # Any extra variables
            **extra_vars
        }
        
        return style.format(**format_vars)

    @classmethod
    def apply_global_style(cls, app):
        """Apply global application stylesheet with modern design"""
        global_style = f"""
            /* Base application styling */
            QMainWindow {{
                background-color: {cls.COLORS['background']};
                color: {cls.COLORS['text_primary']};
                font-size: {cls.FONTS['body']};
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }}
            
            /* Tab widget styling - modern flat design */
            /* Tab widget pane */
            QTabWidget::pane {{
                border: 2px solid {cls.COLORS['border']};
                background-color: {cls.COLORS['background']};
                border-radius: 0px 0px 0px 0px;
                margin-top: 0px;
            }}
            
            /* Tab bar styling */
            /* Tips: border-radius: top-left, top-right, bottom-right, bottom-left */
            QTabBar::tab {{
                background-color: {cls.COLORS['surface']};
                border: 2px solid {cls.COLORS['border']};
                padding: 6px 6px 10px 6px;
                margin-left: 0px;
                margin-right: 0px;
                margin-bottom: -6px;
                font-size: {cls.FONTS['body']};
                font-weight: 500;
                border-radius: 8px 8px 0px 0px;
                min-width: 40px;
            }}
            
            QTabBar::tab:selected {{
                background-color: {cls.COLORS['primary']};
                color: white;
                border-bottom: 2px solid {cls.COLORS['primary']};
            }}
            
            QTabBar::tab:hover:!selected {{
                background-color: {cls.COLORS['surface_alt']};
                border-color: {cls.COLORS['border_active']};
            }}
            
            /* Status bar styling */
            QStatusBar {{
                background-color: {cls.COLORS['surface']};
                border-top: 1px solid {cls.COLORS['border']};
                font-size: {cls.FONTS['caption']};
                color: {cls.COLORS['text_secondary']};
                padding: 4px 8px;
            }}
            
            /* Progress bar styling */
            QProgressBar {{
                border: 1px solid {cls.COLORS['border']};
                border-radius: 4px;
                text-align: center;
                font-size: {cls.FONTS['caption']};
                background-color: {cls.COLORS['surface']};
                height: 20px;
            }}
            
            QProgressBar::chunk {{
                background-color: {cls.COLORS['primary']};
                border-radius: 3px;
                margin: 1px;
            }}
            
            /* List widget styling */
            QListWidget {{
                border: 1px solid {cls.COLORS['border']};
                border-radius: 6px;
                background-color: white;
                alternate-background-color: {cls.COLORS['surface']};
                font-size: {cls.FONTS['body']};
                outline: none;
                padding: 4px;
            }}
            
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 4px;
                margin: 1px 0px;
            }}
            
            QListWidget::item:selected {{
                background-color: {cls.COLORS['primary']};
                color: white;
            }}
            
            QListWidget::item:hover:!selected {{
                background-color: {cls.COLORS['surface_alt']};
            }}
            
            /* Table widget styling */
            QTableWidget {{
                border: 1px solid {cls.COLORS['border']};
                border-radius: 6px;
                gridline-color: {cls.COLORS['border']};
                background-color: white;
                alternate-background-color: {cls.COLORS['surface']};
                font-size: {cls.FONTS['body']};
                outline: none;
            }}
            
            QTableWidget::item {{
                padding: 6px 8px;
                border: none;
            }}
            
            QTableWidget::item:selected {{
                background-color: {cls.COLORS['primary']};
                color: white;
            }}
            
            QTableWidget::item:hover:!selected {{
                background-color: {cls.COLORS['surface_alt']};
            }}
            
            QHeaderView::section {{
                background-color: {cls.COLORS['surface']};
                border: none;
                border-right: 1px solid {cls.COLORS['border']};
                border-bottom: 1px solid {cls.COLORS['border']};
                padding: 6px 8px;
                font-weight: 500;
                font-size: {cls.FONTS['body']};
            }}
            
            /* Scrollbar styling - modern thin scrollbars */
            QScrollBar:vertical {{
                border: none;
                background-color: {cls.COLORS['surface']};
                width: 12px;
                border-radius: 6px;
            }}
            
            QScrollBar::handle:vertical {{
                background-color: {cls.COLORS['border']};
                min-height: 20px;
                border-radius: 6px;
                margin: 2px;
            }}
            
            QScrollBar::handle:vertical:hover {{
                background-color: {cls.COLORS['text_secondary']};
            }}
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
            
            QScrollBar:horizontal {{
                border: none;
                background-color: {cls.COLORS['surface']};
                height: 12px;
                border-radius: 6px;
            }}
            
            QScrollBar::handle:horizontal {{
                background-color: {cls.COLORS['border']};
                min-width: 20px;
                border-radius: 6px;
                margin: 2px;
            }}
            
            QScrollBar::handle:horizontal:hover {{
                background-color: {cls.COLORS['text_secondary']};
            }}
            
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                border: none;
                background: none;
            }}
            
            /* Checkbox styling */
            QCheckBox {{
                font-size: {cls.FONTS['body']};
                spacing: 8px;
                color: {cls.COLORS['text_primary']};
            }}
            
            /* Apply splitter styling globally */
            {cls.format_style('splitter')}
        """
        
        app.setStyleSheet(global_style)

    @classmethod
    def tab_widget_stylesheet(cls):
        """Return stylesheet for top-level tab sizing and typography."""
        return (
            "QTabBar::tab { "
            f"min-width: {cls.TAB_UI['min_width']}px; "
            f"min-height: {cls.TAB_UI['min_height']}px; "
            f"padding: {cls.TAB_UI['padding_vertical']}px {cls.TAB_UI['padding_horizontal']}px; "
            f"font-size: {cls.TAB_UI['font_size']}px; "
            "}"
        )

    @classmethod
    def tab_icon_size(cls):
        """Return standard tab icon size."""
        return QSize(cls.TAB_UI['icon_size'], cls.TAB_UI['icon_size'])

    @classmethod
    def corner_button_icon_size(cls):
        """Return standard corner-button icon size."""
        return QSize(cls.CORNER_BUTTON_UI['icon_size'], cls.CORNER_BUTTON_UI['icon_size'])

    @classmethod
    def corner_button_size(cls):
        """Return standard corner-button size."""
        return QSize(cls.CORNER_BUTTON_UI['button_width'], cls.CORNER_BUTTON_UI['button_height'])

    @classmethod
    def toolbar_symbol_button_size(cls):
        """Return standard square toolbar-symbol button size."""
        return QSize(cls.TOOLBAR_BUTTON_UI['symbol_width'], cls.TOOLBAR_BUTTON_UI['symbol_height'])

    @classmethod
    def mask_tool_button_size(cls):
        """Return larger button size for mask drawing tool icons."""
        return QSize(cls.TOOLBAR_BUTTON_UI['mask_tool_width'], cls.TOOLBAR_BUTTON_UI['mask_tool_height'])

    @classmethod
    def mask_tool_icon_size(cls):
        """Return larger icon size for mask drawing tools."""
        size = cls.TOOLBAR_BUTTON_UI['mask_tool_icon_size']
        return QSize(size, size)

    @classmethod
    def toolbar_text_button_height(cls):
        """Return standard toolbar text-button height."""
        return cls.TOOLBAR_BUTTON_UI['text_height']

    @classmethod
    def toolbar_text_button_min_width(cls):
        """Return standard minimum width for toolbar text buttons."""
        return cls.TOOLBAR_BUTTON_UI['text_min_width']

    @classmethod
    def icon_directory(cls, workspace_root: Path) -> Path:
        """Return absolute icon directory for this workspace."""
        return workspace_root / cls.ASSETS_RELATIVE_DIR

    @classmethod
    def load_icon(cls, workspace_root: Path, filename: str) -> QIcon:
        """Load a themed icon file if available, else return an empty icon."""
        path = cls.icon_directory(workspace_root) / filename
        return QIcon(str(path)) if path.exists() else QIcon()

    @classmethod 
    def get_layout_ratios(cls):
        """Get standard layout ratios for consistent UI"""
        return cls.LAYOUT

    @classmethod
    def apply_gui_settings(cls, gui_settings):
        """Apply optional runtime GUI ratio overrides from configuration."""
        if not gui_settings:
            return

        def _positive_number(value, fallback):
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return fallback
            return parsed if parsed > 0 else fallback

        viz_ratio = _positive_number(gui_settings.get('visualization_ratio'), cls.LAYOUT['main_splitter_ratio'][0])
        ctrl_ratio = _positive_number(gui_settings.get('controls_ratio'), cls.LAYOUT['main_splitter_ratio'][1])
        image_ratio = _positive_number(gui_settings.get('image_plot_ratio'), cls.LAYOUT['viz_splitter_ratio'][0])
        plot_ratio = _positive_number(gui_settings.get('plot_ratio'), cls.LAYOUT['viz_splitter_ratio'][1])

        cls.LAYOUT['main_splitter_ratio'] = [viz_ratio, ctrl_ratio]
        cls.LAYOUT['viz_splitter_ratio'] = [image_ratio, plot_ratio]


# Convenience functions for applying styles
def apply_title_style(widget):
    """Apply title style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('title_label'))

def apply_body_style(widget):
    """Apply body text style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('body_text'))

def apply_small_text_style(widget):
    """Apply small text style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('small_text'))

def apply_subtitle_style(widget):
    """Apply subtitle style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('subtitle_label'))

def apply_info_style(widget):
    """Apply info label style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('info_label'))

def apply_status_style(widget):
    """Apply status label style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('status_label'))

def apply_primary_button_style(widget):
    """Apply primary button style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('primary_button'))

def apply_secondary_button_style(widget):
    """Apply secondary button style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('secondary_button'))

def apply_sync_button_style(widget):
    """Apply sync button style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('sync_button'))

def apply_toolbar_symbol_button_style(widget):
    """Apply standard style and size to a symbol-only toolbar button."""
    widget.setFixedSize(AppStyle.toolbar_symbol_button_size())
    widget.setStyleSheet(AppStyle.format_style('toolbar_symbol_button'))

def apply_toolbar_text_button_style(widget):
    """Apply standard style and size to a compact text toolbar button."""
    widget.setMinimumWidth(AppStyle.toolbar_text_button_min_width())
    widget.setFixedHeight(AppStyle.toolbar_text_button_height())
    widget.setStyleSheet(AppStyle.format_style('toolbar_text_button'))

def apply_input_style(widget):
    """Apply input field style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('input_field'))

def apply_group_box_style(widget):
    """Apply group box style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('group_box'))

def setup_splitter_layout(splitter, ratios):
    """Setup splitter with consistent ratios and responsive stretch behavior."""

    # Normalize user-provided ratios to positive integer stretch factors.
    normalized = []
    for ratio in ratios:
        try:
            value = float(ratio)
        except (TypeError, ValueError):
            value = 1.0

        if value <= 0:
            value = 1.0

        normalized.append(value)

    factors = [max(1, int(round(value * 100))) for value in normalized]

    def _apply_ratio_sizes_from_geometry():
        count = splitter.count()
        if count <= 0:
            return

        if splitter.orientation() == Qt.Horizontal:
            total = splitter.width()
        else:
            total = splitter.height()

        handle_total = splitter.handleWidth() * max(0, count - 1)
        usable = max(1, total - handle_total)
        if usable <= 1:
            return

        ratio_values = normalized[:count]
        if len(ratio_values) < count:
            ratio_values.extend([1.0] * (count - len(ratio_values)))

        ratio_sum = sum(ratio_values)
        if ratio_sum <= 0:
            return

        sizes = [max(1, int(round(usable * (value / ratio_sum)))) for value in ratio_values]
        size_delta = usable - sum(sizes)
        sizes[-1] = max(1, sizes[-1] + size_delta)
        splitter.setSizes(sizes)

    # Apply both initial size hint and stretch factors for resize behavior.
    splitter.setSizes(factors)
    for index, factor in enumerate(factors):
        splitter.setStretchFactor(index, factor)
        splitter.setCollapsible(index, False)

    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(AppStyle.LAYOUT['splitter_handle_width'])

    # Re-apply ratio once geometry is finalized so size hints do not force 1:1 splits.
    _apply_ratio_sizes_from_geometry()
    QTimer.singleShot(0, _apply_ratio_sizes_from_geometry)