import curses

# tirc_core/client/ui_colors.py

# Define the UI color palette using hex codes.
# These will be converted to curses color numbers (0-255) if 256-color support is available.

UI_COLOR_PALETTE = {
    # Base Colors
    "main_background": "#2C003E",  # Dark Purple/Magenta
    "input_background": "#000000", # Pure Black
    "status_background": "#004040",# Dark Cyan/Teal

    # Highlighting System Colors
    "channel": "#00FF00",          # Bright Green
    "nick": "#00FFFF",             # Cyan
    "mode": "#FFFF00",             # Bright Yellow
    "my_message": "#FFA500",       # Orange
    "other_message": "#FFFFFF",    # White
    "system_message": "#C0C0C0",   # Silver/Light Gray
    "error_message": "#FF0000",    # Red
    "highlight_mention": "#FFD700",# Gold
    "timestamp": "#808080",        # Gray
    "server_name": "#ADD8E6",      # Light Blue

    # Sidebar Specifics
    "sidebar_active_fg": "#FFFFFF", # White
    "sidebar_active_bg": "#004040", # Dark Cyan/Teal (same as status_background for consistency)
    "sidebar_unread_fg": "#FFD700", # Gold
    "sidebar_unread_bg": "#2C003E", # Dark Purple/Magenta (same as main_background)
    "status_bar_fg": "#E0E0E0",    # Light Grey
}

# Mapping for 8-color fallback (standard curses colors 0-7)
# 0: Black, 1: Red, 2: Green, 3: Yellow, 4: Blue, 5: Magenta, 6: Cyan, 7: White
FALLBACK_8_COLOR_MAP = {
    "#2C003E": curses.COLOR_BLACK,   # Dark Purple/Magenta -> Black (closest dark)
    "#000000": curses.COLOR_BLACK,   # Pure Black -> Black
    "#004040": curses.COLOR_CYAN,    # Dark Cyan/Teal -> Cyan
    "#00FF00": curses.COLOR_GREEN,   # Bright Green -> Green
    "#00FFFF": curses.COLOR_CYAN,    # Cyan -> Cyan
    "#FFFF00": curses.COLOR_YELLOW,  # Bright Yellow -> Yellow
    "#FFA500": curses.COLOR_YELLOW,  # Orange -> Yellow (closest bright)
    "#FFFFFF": curses.COLOR_WHITE,   # White -> White
    "#C0C0C0": curses.COLOR_WHITE,   # Silver/Light Gray -> White
    "#FF0000": curses.COLOR_RED,     # Red -> Red
    "#FFD700": curses.COLOR_YELLOW,  # Gold -> Yellow
    "#808080": curses.COLOR_WHITE,   # Gray -> White (closest neutral)
    "#ADD8E6": curses.COLOR_CYAN,    # Light Blue -> Cyan (closest bright)
    "#E0E0E0": curses.COLOR_WHITE,   # Light Grey -> White
}
