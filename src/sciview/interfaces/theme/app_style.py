"""
Global Qt Style Configuration

Centralized styling configuration for the SciAnalysis GUI application.
This module provides consistent styling across all tabs and components.
"""

from pathlib import Path
import xml.etree.ElementTree as ET

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PyQt5.QtSvg import QSvgRenderer


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
        'family': "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        'scale_pct': 125,
        'h1': '18px',
        'h2': '15px',
        'h3': '13px',
        'body': '11px',
        'caption': '10px',
        'small': '9px'
    }

    FONT_ROLE_PROPERTY = "sciview_font_role"
    THEME_KEY_PROPERTY = "sciview_theme_key"

    FONT_ROLE_MAP = {
        'title': ('h1', 600),
        'subtitle': ('h2', 500),
        'section': ('h3', 500),
        'body': ('body', 400),
        'info': ('body', 400),
        'status': ('caption', 400),
        'button': ('body', 500),
        'toolbar_symbol': ('h3', 600),
        'toolbar_text': ('small', 400),
        'input': ('body', 400),
        'group_box': ('h3', 500),
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
        return ""

    @classmethod
    def apply_global_style(cls, app):
        """Apply global application stylesheet with Qt defaults."""
        app.setStyleSheet("")
        cls.refresh_runtime_theme(app, clear_widget_styles=True)

    @classmethod
    def tab_widget_stylesheet(cls):
        """Return stylesheet for top-level tab sizing and typography."""
        return ""

    @classmethod
    def tab_font(cls):
        """Return the native tab-bar font, aligned with H2 section headings."""
        return cls.make_font('h2', weight=500)

    @classmethod
    def tab_min_height(cls):
        """Return a native-friendly tab height derived from the H2 font size."""
        return max(cls.TAB_UI['min_height'], cls.font_px('h2') + (cls.TAB_UI['padding_vertical'] * 2) + 6)

    @classmethod
    def tab_icon_size(cls):
        """Return standard tab icon size."""
        size = max(cls.TAB_UI['icon_size'], cls.font_px('h2'))
        return QSize(size, size)

    @classmethod
    def corner_button_icon_size(cls):
        """Return standard corner-button icon size."""
        size = max(cls.CORNER_BUTTON_UI['icon_size'], cls.font_px('caption') + 8)
        return QSize(size, size)

    @classmethod
    def corner_button_size(cls):
        """Return standard corner-button size."""
        height = max(cls.CORNER_BUTTON_UI['button_height'], cls.tab_min_height() - 4)
        width = max(cls.CORNER_BUTTON_UI['button_width'], height)
        return QSize(width, height)

    @classmethod
    def toolbar_symbol_button_size(cls):
        """Return standard square toolbar-symbol button size."""
        size = max(cls.TOOLBAR_BUTTON_UI['symbol_width'], cls.font_px('body') + 18)
        return QSize(size, max(cls.TOOLBAR_BUTTON_UI['symbol_height'], size - 2))

    @classmethod
    def mask_tool_button_size(cls):
        """Return larger button size for mask drawing tool icons."""
        width = max(cls.TOOLBAR_BUTTON_UI['mask_tool_width'], cls.font_px('body') + 24)
        height = max(cls.TOOLBAR_BUTTON_UI['mask_tool_height'], cls.font_px('body') + 20)
        return QSize(width, height)

    @classmethod
    def mask_tool_icon_size(cls):
        """Return larger icon size for mask drawing tools."""
        size = max(cls.TOOLBAR_BUTTON_UI['mask_tool_icon_size'], cls.font_px('body') + 6)
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
        if not path.exists():
            return QIcon()
        if path.suffix.lower() != '.svg':
            return QIcon(str(path))

        icon = QIcon()
        colors = cls.theme_colors()
        for size in (16, 18, 20, 22, 24, 28, 32):
            icon.addPixmap(cls._render_svg_pixmap(path, size, colors['icon']))
            icon.addPixmap(cls._render_svg_pixmap(path, size, colors['muted']), QIcon.Disabled)
        return icon

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

    @classmethod
    def current_theme_key(cls, app=None):
        """Return the active theme key recorded on the QApplication."""
        app = app or QApplication.instance()
        return app.property(cls.THEME_KEY_PROPERTY) if app is not None else None

    @classmethod
    def theme_is_dark(cls, app=None):
        """Return True when the current theme should be treated as dark."""
        theme_key = str(cls.current_theme_key(app) or '').lower()
        if any(token in theme_key for token in ('qdarkstyle', 'qdarktheme:dark', 'dark_')):
            return True

        app = app or QApplication.instance()
        if app is None:
            return False
        return app.palette().color(QPalette.Window).lightness() < 128

    @classmethod
    def theme_colors(cls, app=None):
        """Return theme-derived colors for icons and plotting surfaces."""
        app = app or QApplication.instance()
        theme_key = str(cls.current_theme_key(app) or '')
        if app is None:
            return {
                'window': QColor('#f5f5f5'),
                'base': QColor('#ffffff'),
                'text': QColor('#202020'),
                'muted': QColor('#808080'),
                'grid': QColor('#c0c0c0'),
                'accent': QColor('#308cc6'),
                'border': QColor('#a0a0a0'),
                'control_bg': QColor('#ffffff'),
                'control_hover': QColor('#f0f4f8'),
                'checked_fg': QColor('#ffffff'),
                'icon': QColor('#202020'),
            }

        material_theme = cls._qt_material_theme_values(theme_key)
        if material_theme is not None:
            accent = QColor(material_theme.get('primaryColor', cls.COLORS['accent']))
            window = QColor(material_theme.get('secondaryColor', '#f5f5f5'))
            base = QColor(material_theme.get('secondaryDarkColor', material_theme.get('secondaryLightColor', '#ffffff')))
            text_name = material_theme.get('secondaryTextColor' if cls.theme_is_dark(app) else 'primaryTextColor', '#202020')
            text = QColor(text_name)
            muted = QColor(material_theme.get('secondaryLightColor' if cls.theme_is_dark(app) else 'secondaryTextColor', '#808080'))
            grid = QColor(material_theme.get('secondaryLightColor' if cls.theme_is_dark(app) else 'secondaryDarkColor', '#c0c0c0'))
            control_bg = QColor(material_theme.get('secondaryDarkColor' if cls.theme_is_dark(app) else 'secondaryColor', window.name()))
            control_hover = QColor(material_theme.get('secondaryLightColor' if cls.theme_is_dark(app) else 'secondaryDarkColor', control_bg.name()))
            border = QColor(material_theme.get('primaryLightColor', accent.name()))
            checked_fg = QColor(material_theme.get('primaryTextColor', '#ffffff'))

            return {
                'window': window,
                'base': base,
                'text': text,
                'muted': muted,
                'grid': grid,
                'accent': accent,
                'border': border,
                'control_bg': control_bg,
                'control_hover': control_hover,
                'checked_fg': checked_fg,
                'icon': text,
            }

        palette = app.palette()
        if cls.theme_is_dark(app):
            window = palette.color(QPalette.Window)
            text = palette.color(QPalette.WindowText)
            if window.lightness() >= 128:
                window = QColor('#232629')
            if text.lightness() <= 128:
                text = QColor('#f2f2f2')
            base = palette.color(QPalette.Base)
            if base.lightness() >= 128:
                base = QColor('#1b1e20')
            muted = palette.color(QPalette.Disabled, QPalette.WindowText)
            if muted.lightness() <= 96:
                muted = QColor('#9aa0a6')
            grid = QColor('#5f6368')
        else:
            window = palette.color(QPalette.Window)
            base = palette.color(QPalette.Base)
            text = palette.color(QPalette.WindowText)
            muted = palette.color(QPalette.Disabled, QPalette.WindowText)
            grid = palette.color(QPalette.Mid)

        accent = palette.color(QPalette.Highlight)
        if not accent.isValid():
            accent = QColor(cls.COLORS['accent'])
        border = accent if cls.theme_is_dark(app) else palette.color(QPalette.Mid)
        control_bg = base if cls.theme_is_dark(app) else window
        control_hover = control_bg.lighter(115) if cls.theme_is_dark(app) else control_bg.darker(104)
        checked_fg = QColor('#ffffff') if accent.lightness() < 170 else QColor('#111111')

        return {
            'window': window,
            'base': base,
            'text': text,
            'muted': muted,
            'grid': grid,
            'accent': accent,
            'border': border,
            'control_bg': control_bg,
            'control_hover': control_hover,
            'checked_fg': checked_fg,
            'icon': text,
        }

    @classmethod
    def compact_button_stylesheet(cls):
        """Return a small explicit style for compact toolbar buttons."""
        colors = cls.theme_colors()
        return (
            "QPushButton, QToolButton {"
            f"color: {colors['text'].name()};"
            f"background-color: {colors['control_bg'].name()};"
            f"border: 1px solid {colors['border'].name()};"
            "border-radius: 4px;"
            "padding: 0px;"
            "margin: 0px;"
            "}"
            "QPushButton:hover, QToolButton:hover {"
            f"background-color: {colors['control_hover'].name()};"
            f"border-color: {colors['accent'].name()};"
            "}"
            "QPushButton:checked, QToolButton:checked, QPushButton:pressed, QToolButton:pressed {"
            f"background-color: {colors['accent'].name()};"
            f"color: {colors['checked_fg'].name()};"
            f"border-color: {colors['accent'].name()};"
            "}"
            "QPushButton:disabled, QToolButton:disabled {"
            f"color: {colors['muted'].name()};"
            f"border-color: {colors['muted'].name()};"
            "}"
        )

    @classmethod
    def qt_material_readability_stylesheet(cls, app=None):
        """Return dark-theme overrides for qt-material input/widget readability."""
        app = app or QApplication.instance()
        theme_key = str(cls.current_theme_key(app) or '')
        if not theme_key.startswith('qt-material:') or not cls.theme_is_dark(app):
            return ""

        colors = cls.theme_colors(app)
        text = colors['text'].name()
        muted = colors['muted'].name()
        base = colors['base'].name()
        window = colors['window'].name()
        border = colors['border'].name()
        accent = colors['accent'].name()
        checked_fg = colors['checked_fg'].name()

        return (
            "QWidget {"
            f"color: {text};"
            "}"
            "QLabel, QGroupBox, QCheckBox, QRadioButton, QMenu, QMenu::item {"
            f"color: {text};"
            "}"
            "QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QSpinBox, QDoubleSpinBox, QComboBox {"
            f"color: {text};"
            f"background-color: {base};"
            f"selection-color: {checked_fg};"
            f"selection-background-color: {accent};"
            f"border: 1px solid {border};"
            "}"
            "QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QAbstractSpinBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {"
            f"color: {muted};"
            f"border: 1px solid {muted};"
            "}"
            "QComboBox QAbstractItemView, QListView, QListWidget, QTreeView, QTableView, QHeaderView::section {"
            f"color: {text};"
            f"background-color: {window};"
            f"selection-color: {checked_fg};"
            f"selection-background-color: {accent};"
            "}"
        )

    @classmethod
    def font_px(cls, token_name, fallback=None):
        """Return a font size token as integer pixels."""
        raw_value = cls.FONTS.get(token_name, fallback if fallback is not None else '11px')
        try:
            base_px = int(str(raw_value).replace('px', '').strip())
        except ValueError:
            base_px = int(str(fallback if fallback is not None else '11px').replace('px', '').strip())
        return max(1, int(round(base_px * cls.font_scale_factor())))

    @classmethod
    def font_scale_factor(cls):
        """Return the configured global font scaling factor."""
        raw_scale = cls.FONTS.get('scale_pct', 100)
        try:
            scale_pct = float(raw_scale)
        except (TypeError, ValueError):
            scale_pct = 100.0
        if scale_pct <= 0:
            scale_pct = 100.0
        return scale_pct / 100.0

    @classmethod
    def make_font(cls, token_name, weight=400):
        """Build a QFont from the configured token and optional weight."""
        font = QFont()
        family = cls.effective_font_family()
        if family:
            font.setFamily(family.split(',')[0].strip().strip("'\""))
        font.setPixelSize(cls.font_px(token_name))
        font.setWeight(weight)
        return font

    @classmethod
    def effective_font_family(cls, app=None):
        """Return the active font family with theme-specific overrides."""
        theme_key = str(cls.current_theme_key(app) or '')
        if theme_key.startswith('qt-material:'):
            return 'Consolas'
        return str(cls.FONTS.get('family', '')).strip()

    @classmethod
    def matplotlib_font_size(cls, token_name, fallback=None):
        """Return a scaled Matplotlib-friendly font size in points."""
        px_size = cls.font_px(token_name, fallback=fallback)
        return max(1.0, round(px_size * 0.75, 1))

    @classmethod
    def apply_matplotlib_figure_theme(cls, figure):
        """Apply theme-derived colors to a Matplotlib figure and its axes."""
        colors = cls.theme_colors()
        text_color = colors['text'].name()
        base_color = colors['base'].name()
        window_color = colors['window'].name()
        grid_color = colors['grid'].name()

        figure.patch.set_facecolor(window_color)
        for axis in figure.axes:
            axis.set_facecolor(base_color)
            axis.title.set_color(text_color)
            axis.xaxis.label.set_color(text_color)
            axis.yaxis.label.set_color(text_color)
            axis.tick_params(colors=text_color, labelcolor=text_color)
            for spine in axis.spines.values():
                spine.set_color(grid_color)
            for line in axis.get_xgridlines() + axis.get_ygridlines():
                line.set_color(grid_color)
                line.set_alpha(0.35)

        if getattr(figure, 'canvas', None) is not None:
            figure.canvas.draw_idle()

    @classmethod
    def refresh_runtime_theme(cls, app=None, clear_widget_styles=False):
        """Re-apply fonts and theme-aware visuals to live widgets."""
        app = app or QApplication.instance()
        if app is None:
            return

        app.setFont(cls.make_font('body'))
        for widget in app.allWidgets():
            if clear_widget_styles and widget.styleSheet():
                widget.setStyleSheet("")
            cls.apply_font_role(widget)
            if hasattr(widget, 'refresh_theme'):
                widget.refresh_theme()
            elif hasattr(widget, 'figure'):
                cls.apply_matplotlib_figure_theme(widget.figure)

    @classmethod
    def set_font_role(cls, widget, role_name):
        """Record and apply a semantic font role for a widget."""
        widget.setProperty(cls.FONT_ROLE_PROPERTY, role_name)
        cls.apply_font_role(widget)

    @classmethod
    def apply_font_role(cls, widget):
        """Apply a configured font role to a widget if one is registered."""
        role_name = widget.property(cls.FONT_ROLE_PROPERTY)
        if not role_name:
            return

        token_name, weight = cls.FONT_ROLE_MAP.get(role_name, ('body', 400))
        widget.setFont(cls.make_font(token_name, weight=weight))

    @classmethod
    def _render_svg_pixmap(cls, path: Path, size: int, color: QColor) -> QPixmap:
        """Render an SVG icon to a tinted pixmap for the active theme."""
        renderer = QSvgRenderer(str(path))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), color)
        painter.end()
        return pixmap

    @classmethod
    def _qt_material_theme_values(cls, theme_key: str):
        """Return key colors from a qt-material XML theme when active."""
        if not theme_key.startswith('qt-material:'):
            return None

        theme_name = theme_key.split(':', 1)[1]
        try:
            qt_material = __import__('qt_material')
            theme_path = Path(qt_material.__file__).resolve().parent / 'themes' / theme_name
            root = ET.fromstring(theme_path.read_text(encoding='utf-8'))
        except Exception:
            return None

        values = {}
        for color_node in root.findall('color'):
            name = color_node.attrib.get('name')
            if name and color_node.text:
                values[name] = color_node.text.strip()
        return values


# Convenience functions for applying styles
def apply_title_style(widget):
    """Apply title style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'title')

def apply_body_style(widget):
    """Apply body text style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'body')

def apply_small_text_style(widget):
    """Apply small text style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'small')

def apply_subtitle_style(widget):
    """Apply subtitle style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'subtitle')

def apply_info_style(widget):
    """Apply info label style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'info')

def apply_status_style(widget):
    """Apply status label style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'status')

def apply_primary_button_style(widget):
    """Apply primary button style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'button')

def apply_secondary_button_style(widget):
    """Apply secondary button style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'button')

def apply_sync_button_style(widget):
    """Apply sync button style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'button')

def apply_toolbar_symbol_button_style(widget):
    """Apply standard style and size to a symbol-only toolbar button."""
    widget.setFixedSize(AppStyle.toolbar_symbol_button_size())
    widget.setStyleSheet(AppStyle.compact_button_stylesheet())
    widget.setMinimumSize(AppStyle.toolbar_symbol_button_size())
    widget.setFont(AppStyle.make_font('h3', weight=600))
    widget.setProperty(AppStyle.FONT_ROLE_PROPERTY, 'toolbar_symbol')

def apply_toolbar_text_button_style(widget):
    """Apply standard style and size to a compact text toolbar button."""
    widget.setMinimumWidth(AppStyle.toolbar_text_button_min_width())
    widget.setFixedHeight(AppStyle.toolbar_text_button_height())
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'toolbar_text')

def apply_input_style(widget):
    """Apply input field style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'input')

def apply_group_box_style(widget):
    """Apply group box style to a widget"""
    widget.setStyleSheet("")
    AppStyle.set_font_role(widget, 'group_box')

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