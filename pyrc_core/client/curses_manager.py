import curses
import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger("pyrc.curses_manager")

class CursesManager:
    def __init__(self, stdscr: Any):
        self.stdscr = stdscr
        self.colors: Dict[str, int] = {}
        self.height: int = 0
        self.width: int = 0
        self._setup_curses_settings()

    def _setup_curses_settings(self):
        curses.curs_set(1)
        curses.start_color()
        curses.use_default_colors()

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
        curses.init_pair(pair_id, fg, bg)
        self.colors[name] = curses.color_pair(pair_id)

    def get_dimensions(self) -> Tuple[int, int]:
        try:
            self.height, self.width = self.stdscr.getmaxyx()
            return self.height, self.width
        except curses.error as e:
            logger.error(f"Curses error getting stdscr dimensions: {e}")
            return 0, 0

    def resize_term(self, height: int, width: int):
        try:
            curses.resize_term(height, width)
            self.stdscr.clearok(True)
        except curses.error as e:
            logger.error(f"Curses error resizing terminal to {height}x{width}: {e}")

    def update_screen(self):
        try:
            curses.doupdate()
        except curses.error as e:
            logger.error(f"Curses error during doupdate: {e}")

    def cleanup(self):
        curses.endwin()
        logger.debug("Curses cleanup complete.")

    def get_color(self, name: str) -> int:
        return self.colors.get(name, 0)

    def noutrefresh_stdscr(self):
        try:
            self.stdscr.noutrefresh()
        except curses.error as e:
            logger.error(f"Error refreshing stdscr: {e}")

    def erase_stdscr(self):
        try:
            self.stdscr.erase()
        except curses.error as e:
            logger.error(f"Error erasing stdscr: {e}")

    def clear_stdscr(self):
        try:
            self.stdscr.clear()
        except curses.error as e:
            logger.error(f"Error clearing stdscr: {e}")

    def refresh_stdscr(self):
        try:
            self.stdscr.refresh()
        except curses.error as e:
            logger.error(f"Error refreshing stdscr: {e}")

    def addstr_stdscr(self, y: int, x: int, text: str, attr: int):
        try:
            self.stdscr.addstr(y, x, text, attr)
        except curses.error as e:
            logger.warning(f"Error adding string to stdscr at {y},{x}: {e}")

    def touchwin(self, window: Any):
        if window:
            try:
                window.touchwin()
            except curses.error as e:
                logger.warning(f"Error touching window {window!r}: {e}")

    def clearok(self, window: Any, flag: bool):
        if window:
            try:
                window.clearok(flag)
            except curses.error as e:
                logger.warning(f"Error setting clearok for window {window!r}: {e}")
