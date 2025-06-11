import curses
import logging
from typing import Any, Dict, Tuple
from pyrc_core.client.curses_utils import SafeCursesUtils # Import SafeCursesUtils

logger = logging.getLogger("pyrc.curses_manager")

class CursesManager:
    def __init__(self, stdscr: Any):
        self.stdscr = stdscr
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
        SafeCursesUtils._safe_use_default_colors("CursesManager._setup_curses_settings_use_default_colors")

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

        self._init_color_pair("default", COLOR_ID_DEFAULT, curses.COLOR_WHITE, -1)
        self._init_color_pair("system", COLOR_ID_SYSTEM, curses.COLOR_CYAN, -1)
        self._init_color_pair("join_part", COLOR_ID_JOIN_PART, curses.COLOR_GREEN, -1)
        self._init_color_pair(
            "nick_change", COLOR_ID_NICK_CHANGE, curses.COLOR_MAGENTA, -1
        )
        self._init_color_pair(
            "my_message", COLOR_ID_MY_MESSAGE, curses.COLOR_YELLOW, -1
        )
        self._init_color_pair(
            "other_message", COLOR_ID_OTHER_MESSAGE, curses.COLOR_WHITE, -1
        )
        self._init_color_pair(
            "highlight", COLOR_ID_HIGHLIGHT, curses.COLOR_BLACK, curses.COLOR_YELLOW
        )
        self._init_color_pair("error", COLOR_ID_ERROR, curses.COLOR_RED, -1)
        self._init_color_pair(
            "status_bar", COLOR_ID_STATUS_BAR, curses.COLOR_BLACK, curses.COLOR_GREEN
        )
        self._init_color_pair(
            "sidebar_header",
            COLOR_ID_SIDEBAR_HEADER,
            curses.COLOR_BLACK,
            curses.COLOR_CYAN,
        )
        self._init_color_pair(
            "sidebar_item", COLOR_ID_SIDEBAR_USER, curses.COLOR_CYAN, curses.COLOR_BLACK
        )
        self._init_color_pair("input", COLOR_ID_INPUT, curses.COLOR_WHITE, -1)
        self._init_color_pair("pm", COLOR_ID_PM, curses.COLOR_MAGENTA, -1)
        self._init_color_pair("user_prefix", 14, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        self._init_color_pair("list_panel_bg", 15, curses.COLOR_BLUE, curses.COLOR_BLACK)
        self._init_color_pair("user_list_panel_bg", 16, curses.COLOR_GREEN, curses.COLOR_BLACK)

    def _init_color_pair(self, name: str, pair_id: int, fg: int, bg: int):
        SafeCursesUtils._safe_init_pair(pair_id, fg, bg, f"CursesManager._init_color_pair_{name}")
        try:
            self.colors[name] = curses.color_pair(pair_id)
        except curses.error as e:
            logger.warning(f"Curses error getting color pair {pair_id} for '{name}': {e}")
        except Exception as ex:
            logger.error(f"Unexpected error getting color pair {pair_id} for '{name}': {ex}", exc_info=True)

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
