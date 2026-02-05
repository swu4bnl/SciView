"""
Global Qt Style Configuration

Centralized styling configuration for the SciAnalysis GUI application.
This module provides consistent styling across all tabs and components.
"""

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt


class AppStyle:
    """Global application styling configuration"""
    
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
    
    # Layout dimensions
    LAYOUT = {
        'main_splitter_ratio': [1000, 500],  # 2:1 visualization to controls
        'viz_splitter_ratio': [400, 150],   # Image to plot ratio
        'controls_splitter_ratio': [100, 120, 180, 80],  # Calibration panels
        'browser_controls_ratio': [240, 360],  # Image browser controls
        'splitter_handle_width': 2,  # Thinner, modern splitter
        'panel_margin': 8,
        'panel_spacing': 6,
        'border_radius': 2,
        'button_height': 32,
        'input_height': 28
    }
    
    # Widget styles
    WIDGET_STYLES = {
        'title_label': """
            font-weight: 600;
            font-size: {title_font};
            color: {text_primary};
            padding: 0px 0px;
            border-bottom: 2px solid {surface_alt};
            margin-bottom: 0px;
        """,
        
        'subtitle_label': """
            font-weight: 500;
            font-size: {subtitle_font};
            color: {text_primary};
            padding: 0px 0px;
            margin-bottom: 0px;
        """,

        'body_text': """
            font-size: {body_font};
            color: {text_primary};
            padding: 6px 0px;
        """,

        'small_text': """
            font-size: {small};
            color: {text_secondary};
            padding: 4px 0px;
        """,

        'info_label': """
            font-size: {body_font};
            color: {text_secondary};
            padding: 4px 0px;
            line-height: 1.4;
        """,
        
        'status_label': """
            font-size: {caption_font};
            color: {text_secondary};
            background-color: {surface};
            padding: 8px 12px;
            border: 1px solid {border};
            border-radius: {border_radius}px;
            margin: 4px 0px;
        """,
        
        'primary_button': """
            QPushButton {{
                background-color: {primary};
                color: white;
                font-weight: 500;
                font-size: {body_font};
                border: none;
                padding: 8px 16px;
                border-radius: {border_radius}px;
                min-height: {button_height}px;
            }}
            QPushButton:hover {{
                background-color: {secondary};
            }}
            QPushButton:pressed {{
                background-color: {secondary};
                transform: translateY(1px);
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
                padding: 6px 12px;
                border-radius: {border_radius}px;
                min-height: 28px;
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
                padding: 12px 20px;
                border-radius: {border_radius}px;
                min-height: 48px;
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
                padding: 6px 8px;
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
                padding: 4px 8px;
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
                margin-top: 12px;
                padding-top: 16px;
                background-color: {surface};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px 0 8px;
                background-color: {surface};
            }}
        """,
        
        'splitter': """
            QSplitter::handle {{
                background-color: {surface_alt};
                border: none;
                border-radius: 2px;
            }}
            QSplitter::handle:horizontal {{
                width: {handle_width}px;
                margin: 2px 0px;
            }}
            QSplitter::handle:vertical {{
                height: {handle_width}px;
                margin: 0px 2px;
            }}
            QSplitter::handle:hover {{
                background-color: {border_active};
            }}
            QSplitter::handle:pressed {{
                background-color: {primary};
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
            
            # Layout
            'handle_width': cls.LAYOUT['splitter_handle_width'],
            'border_radius': cls.LAYOUT['border_radius'],
            'button_height': cls.LAYOUT['button_height'],
            'input_height': cls.LAYOUT['input_height'],
            
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
    def get_layout_ratios(cls):
        """Get standard layout ratios for consistent UI"""
        return cls.LAYOUT


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

def apply_input_style(widget):
    """Apply input field style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('input_field'))

def apply_group_box_style(widget):
    """Apply group box style to a widget"""
    widget.setStyleSheet(AppStyle.format_style('group_box'))

def setup_splitter_layout(splitter, ratios):
    """Setup splitter with consistent ratios and styling"""
    splitter.setSizes(ratios)
    splitter.setHandleWidth(AppStyle.LAYOUT['splitter_handle_width'])