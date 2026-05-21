"""
Modern Theme for Open-Omniscience GUI Installer
============================================

Beautiful color scheme and styling for the installer.
This provides a modern, professional look with:
- Clean blue primary color scheme
- Proper spacing and padding
- Modern typography
- Status indicators with colors and icons

Author: Open-Omniscience Team
License: GNU GPLv3
"""


class ModernTheme:
    """Modern color theme for the installer."""
    
    # Primary colors - Beautiful blue theme
    PRIMARY = "#3498DB"
    PRIMARY_DARK = "#2980B9"
    PRIMARY_LIGHT = "#5DADE2"
    
    # Accent colors
    SUCCESS = "#27AE60"
    WARNING = "#F39C12"
    ERROR = "#E74C3C"
    INFO = "#16A085"
    
    # Background colors
    BG_PRIMARY = "#ECF0F1"
    BG_SECONDARY = "#FFFFFF"
    BG_TERTIARY = "#F8F9FA"
    
    # Text colors
    TEXT_PRIMARY = "#2C3E50"
    TEXT_SECONDARY = "#7F8C8D"
    TEXT_LIGHT = "#FFFFFF"
    TEXT_DARK = "#2C3E50"
    
    # Border colors
    BORDER_LIGHT = "#BDC3C7"
    BORDER_DARK = "#95A5A6"
    
    # Status colors
    STATUS_SUCCESS = "#27AE60"
    STATUS_WARNING = "#F39C12"
    STATUS_ERROR = "#E74C3C"
    STATUS_INFO = "#3498DB"


def apply_modern_styles(style):
    """Apply modern styles to the ttk Style object."""
    
    # Configure main styles
    style.configure('TFrame', background=ModernTheme.BG_PRIMARY)
    style.configure('TLabel', background=ModernTheme.BG_PRIMARY, 
                   foreground=ModernTheme.TEXT_PRIMARY, font=('Segoe UI', 10))
    
    # Button styles
    style.configure('TButton', font=('Segoe UI', 10), 
                   background=ModernTheme.PRIMARY, foreground=ModernTheme.TEXT_LIGHT,
                   borderwidth=0)
    style.map('TButton', 
             foreground=[('active', ModernTheme.TEXT_LIGHT), ('disabled', ModernTheme.TEXT_SECONDARY)],
             background=[('active', ModernTheme.PRIMARY_DARK), ('disabled', ModernTheme.BORDER_LIGHT)])
    
    # Header style
    style.configure('Header.TLabel', font=('Segoe UI', 16, 'bold'), 
                   background=ModernTheme.BG_PRIMARY, foreground=ModernTheme.PRIMARY)
    
    # Subheader style
    style.configure('Subheader.TLabel', font=('Segoe UI', 12, 'bold'), 
                   background=ModernTheme.BG_PRIMARY, foreground=ModernTheme.TEXT_PRIMARY)
    
    # Status styles
    style.configure('Success.TLabel', font=('Segoe UI', 10), 
                   foreground=ModernTheme.SUCCESS, background=ModernTheme.BG_PRIMARY)
    style.configure('Warning.TLabel', font=('Segoe UI', 10), 
                   foreground=ModernTheme.WARNING, background=ModernTheme.BG_PRIMARY)
    style.configure('Error.TLabel', font=('Segoe UI', 10), 
                   foreground=ModernTheme.ERROR, background=ModernTheme.BG_PRIMARY)
    
    # Entry style
    style.configure('TEntry', fieldbackground=ModernTheme.BG_SECONDARY, 
                   foreground=ModernTheme.TEXT_PRIMARY, insertcolor=ModernTheme.TEXT_PRIMARY)
    
    # Checkbutton and Radiobutton styles
    style.configure('TCheckbutton', background=ModernTheme.BG_PRIMARY, 
                   foreground=ModernTheme.TEXT_PRIMARY)
    style.configure('TRadiobutton', background=ModernTheme.BG_PRIMARY, 
                   foreground=ModernTheme.TEXT_PRIMARY)
    
    # Scrollbar style
    style.configure('TScrollbar', background=ModernTheme.BG_PRIMARY, 
                   troughcolor=ModernTheme.BG_SECONDARY, bordercolor=ModernTheme.BG_PRIMARY)
    
    # Treeview style
    style.configure('Treeview', background=ModernTheme.BG_SECONDARY, 
                   foreground=ModernTheme.TEXT_PRIMARY, fieldbackground=ModernTheme.BG_SECONDARY)
    style.map('Treeview', background=[('selected', ModernTheme.PRIMARY_LIGHT)])


def get_status_color(status):
    """Get color for a status."""
    status_colors = {
        'success': ModernTheme.SUCCESS,
        'warning': ModernTheme.WARNING,
        'error': ModernTheme.ERROR,
        'info': ModernTheme.INFO,
        'pending': ModernTheme.BORDER_LIGHT
    }
    return status_colors.get(status, ModernTheme.BORDER_LIGHT)


def get_status_icon(status):
    """Get icon for a status."""
    status_icons = {
        'success': '✓',
        'warning': '⚠',
        'error': '✗',
        'info': 'ℹ',
        'pending': '○'
    }
    return status_icons.get(status, '○')
