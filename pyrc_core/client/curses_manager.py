import curses
import logging
from typing import Any, Dict, Tuple
from pyrc_core.client.curses_utils import SafeCursesUtils
from pyrc_core.app_config import AppConfig
from pyrc_core.config_defs import * # Import all DEFAULT_COLOR_ constants

logger = logging.getLogger("pyrc.curses_manager")

class CursesManager:
    def __init__(self, stdscr: Any, config: AppConfig):
        self.stdscr = stdscr
        self.config = config # Store the AppConfig instance
        self.colors: Dict[str, int] = {}
        self.height: int = 0
        self.width: int = 0
        self._setup_curses_settings()

    def _setup_curses_settings(self):
        SafeCursesUtils._safe_curs_set(1, "CursesManager._setup_curses_settings_curs_set") # Make cursor visible
        SafeCursesUtils._safe_noecho("CursesManager._setup_curses_settings_noecho")    # Don't echo characters typed by user
        SafeCursesUtils._safe_cbreak("CursesManager._setup_curses_settings_cbreak")    # React to keys instantly, without waiting for Enter
        SafeCursesUtils._safe_keypad(self.stdscr, True, "CursesManager._setup_curses_settings_keypad") # Enable special keys (like arrow keys)
        SafeCursesUtils._safe_start_color("CursesManager._setup_curses_settings_start_color")
        # Removed SafeCursesUtils._safe_use_default_colors as it can conflict with explicit background setting.

        # Define color pair IDs locally, as they are internal UI constants
        COLOR_ID_DEFAULT = 1
        COLOR_ID_SYSTEM = 2
        COLOR_ID_JOIN_PART = 3
        COLOR_ID_NICK_CHANGE = 4
        COLOR_ID_MY_MESSAGE = 5
        COLOR_ID_OTHER_MESSAGE = 6
        COLOR_ID_HIGHLIGHT = 7
        COLOR_ID_ERROR = 8
        COLOR_ID_STATUS_BAR = 9
        COLOR_ID_SIDEBAR_HEADER = 10
        COLOR_ID_SIDEBAR_USER = 11
        COLOR_ID_INPUT = 12
        COLOR_ID_PM = 13
        COLOR_ID_MESSAGE_PANEL_BG = 17 # New color ID for message panel background

        # Explicitly define color pair 0 (default pair) as black on blue
        self._init_color_pair("default_pair_0", 0, curses.COLOR_BLACK, curses.COLOR_BLUE)

        # Use DEFAULT_COLOR_ constants from config_defs for foreground colors
        # All backgrounds set to curses.COLOR_BLUE for a consistent dark theme
        self._init_color_pair("default", COLOR_ID_DEFAULT, DEFAULT_COLOR_SYSTEM, curses.COLOR_BLUE) # This is now effectively a duplicate of system
        self._init_color_pair("system", COLOR_ID_SYSTEM, DEFAULT_COLOR_SYSTEM, curses.COLOR_BLUE)
        self._init_color_pair("join_part", COLOR_ID_JOIN_PART, DEFAULT_COLOR_JOIN_PART, curses.COLOR_BLUE)
        self._init_color_pair(
            "nick_change", COLOR_ID_NICK_CHANGE, DEFAULT_COLOR_NICK_CHANGE, curses.COLOR_BLUE
        )
        self._init_color_pair(
            "my_message", COLOR_ID_MY_MESSAGE, DEFAULT_COLOR_MY_MESSAGE, curses.COLOR_BLUE
        )
        self._init_color_pair(
            "other_message", COLOR_ID_OTHER_MESSAGE, DEFAULT_COLOR_OTHER_MESSAGE, curses.COLOR_BLUE
        )
        self._init_color_pair(
            "highlight", COLOR_ID_HIGHLIGHT, DEFAULT_COLOR_HIGHLIGHT, curses.COLOR_BLUE
        )
        self._init_color_pair("error", COLOR_ID_ERROR, DEFAULT_COLOR_ERROR, curses.COLOR_BLUE)
        self._init_color_pair(
            "status_bar", COLOR_ID_STATUS_BAR, DEFAULT_COLOR_STATUS_BAR, curses.COLOR_BLUE
        )
        self._init_color_pair(
            "sidebar_header",
            COLOR_ID_SIDEBAR_HEADER,
            DEFAULT_COLOR_SIDEBAR_HEADER,
            curses.COLOR_BLUE,
        )
        self._init_color_pair(
            "sidebar_item", COLOR_ID_SIDEBAR_USER, DEFAULT_COLOR_SIDEBAR_ITEM, curses.COLOR_BLUE
        )
        self._init_color_pair("input", COLOR_ID_INPUT, DEFAULT_COLOR_INPUT, curses.COLOR_BLUE)
        self._init_color_pair("pm", COLOR_ID_PM, DEFAULT_COLOR_PM, curses.COLOR_BLUE)
        self._init_color_pair("user_prefix", 14, DEFAULT_COLOR_USER_PREFIX, curses.COLOR_BLUE)
        self._init_color_pair("list_panel_bg", 15, DEFAULT_COLOR_LIST, curses.COLOR_BLUE)
        self._init_color_pair("user_list_panel_bg", 16, DEFAULT_COLOR_LIST, curses.COLOR_BLUE)
        self._init_color_pair("message_panel_bg", COLOR_ID_MESSAGE_PANEL_BG, DEFAULT_COLOR_OTHER_MESSAGE, curses.COLOR_BLUE)

    def _init_color_pair(self, name: str, pair_id: int, fg: int, bg: int):
        SafeCursesUtils._safe_init_pair(pair_id, fg, bg, f"CursesManager._init_color_pair_{name}")
        try:
            self.colors[name] = pair_id # Store the raw pair_id, not the attribute
        except Exception as ex:
            logger.error(f"Unexpected error storing color pair ID {pair_id} for '{name}': {ex}", exc_info=True)

    def get_dimensions(self) -> Tuple[int, int]:
        try:
            self.height, self.width = self.stdscr.getmaxyx()
            return self.height, self.width
        except curses.error as e:
            logger.error(f"Curses error getting stdscr dimensions: {e}")
            return 0, 0

    def resize_term(self, height: int, width: int):
        # curses.resizeterm is not consistently available on all platforms (e.g., Windows)
        # We rely on getmaxyx in UIManager to get updated dimensions and subsequent redraws.
        # This method can be a no-op or perform other necessary internal adjustments if needed.
        # For now, we'll just log if it's called.
        logger.debug(f"resize_term called to {height}x{width}. Relying on UIManager for redraw.")

    def update_screen(self):
        SafeCursesUtils._safe_doupdate("CursesManager.update_screen")

    def cleanup(self):
        SafeCursesUtils._safe_endwin("CursesManager.cleanup")
        logger.debug("Curses cleanup complete.")

    def get_color(self, name: str) -> int:
        return self.colors.get(name, 0)

    def noutrefresh_stdscr(self):
        SafeCursesUtils._safe_noutrefresh(self.stdscr, "CursesManager.noutrefresh_stdscr")

    def erase_stdscr(self):
        SafeCursesUtils._safe_erase(self.stdscr, "CursesManager.erase_stdscr")

    def clear_stdscr(self):
        SafeCursesUtils._safe_clear(self.stdscr, "CursesManager.clear_stdscr")

    def refresh_stdscr(self):
        SafeCursesUtils._safe_refresh(self.stdscr, "CursesManager.refresh_stdscr")

    def addstr_stdscr(self, y: int, x: int, text: str, attr: int):
        SafeCursesUtils._safe_addstr(self.stdscr, y, x, text, attr, "CursesManager.addstr_stdscr")

    def touchwin(self, window: Any):
        if window:
            SafeCursesUtils._safe_touchwin(window, f"CursesManager.touchwin_{window!r}")
    def clearok(self, window: Any, flag: bool):
        if window:
            SafeCursesUtils._safe_clearok(window, flag, f"CursesManager.clearok_{window!r}")
