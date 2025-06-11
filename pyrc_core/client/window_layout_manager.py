import curses
import logging
from typing import Optional, Any, Tuple, Dict

logger = logging.getLogger("pyrc.window_layout_manager")

from pyrc_core.client.curses_utils import SafeCursesUtils # Added import

class WindowLayoutManager:
    def __init__(self, colors: Dict[str, int]):
        self.colors = colors
        self.msg_win: Optional[curses.window] = None
        self.sidebar_win: Optional[curses.window] = None
        self.status_win: Optional[curses.window] = None
        self.input_win: Optional[curses.window] = None
        self.msg_win_top: Optional[curses.window] = None
        self.msg_win_bottom: Optional[curses.window] = None

        self.sidebar_width: int = 0
        self.msg_win_height: int = 0
        self.msg_win_width: int = 0

    def calculate_and_create_windows(
        self,
        term_height: int,
        term_width: int,
        split_mode_active: bool,
        active_split_pane: str,
    ) -> Tuple[int, int, int, int]:
        """
        Calculates dimensions and creates/recreates curses window objects.
        Returns (sidebar_width, msg_win_height, msg_win_width, total_height_used_by_ui).
        """
        self.sidebar_width = max(15, min(30, int(term_width * 0.25)))
        self.msg_win_height = term_height - 2  # Account for status and input lines
        self.msg_win_width = term_width - self.sidebar_width

        if (
            self.msg_win_height <= 0
            or self.msg_win_width <= 0
            or self.sidebar_width <= 0
        ):
            logger.error(
                f"Calculated dimensions are non-positive: MsgH={self.msg_win_height}, "
                f"MsgW={self.msg_win_width}, SidebarW={self.sidebar_width}. "
                f"Terminal: {term_height}x{term_width}"
            )
            # Return zeros to indicate failure or too small UI
            return 0, 0, 0, 0

        logger.debug(
            f"Layout calculated: TermH={term_height}, TermW={term_width}, "
            f"SidebarW={self.sidebar_width}, MsgH={self.msg_win_height}, MsgW={self.msg_win_width}"
        )

        try:
            if split_mode_active:
                top_height = self.msg_win_height // 2
                bottom_height = self.msg_win_height - top_height

                self.msg_win_top = curses.newwin(top_height, self.msg_win_width, 0, 0)
                self.msg_win_top.scrollok(True)
                self.msg_win_top.idlok(True)

                self.msg_win_bottom = curses.newwin(
                bottom_height, self.msg_win_width, top_height, 0
                )
                SafeCursesUtils._safe_bkgd(self.msg_win_bottom, " ", self.colors.get("message_panel_bg", 0), "msg_win_bottom_bkgd")
                self.msg_win_bottom.scrollok(True)
                self.msg_win_bottom.idlok(True)

                self.msg_win = (
                    self.msg_win_top
                    if active_split_pane == "top"
                    else self.msg_win_bottom
                )
            else:
                self.msg_win = curses.newwin(
                    self.msg_win_height, self.msg_win_width, 0, 0
                )
                SafeCursesUtils._safe_bkgd(self.msg_win, " ", self.colors.get("message_panel_bg", 0), "msg_win_bkgd")
                self.msg_win.scrollok(True)
                self.msg_win.idlok(True)
                self.msg_win_top = self.msg_win
                self.msg_win_bottom = None

            self.sidebar_win = curses.newwin(
                term_height - 1,
                self.sidebar_width,
                0,
                self.msg_win_width,
            )
            SafeCursesUtils._safe_bkgd(self.sidebar_win, " ", self.colors.get("user_list_panel_bg", 0), "sidebar_win_bkgd")
            self.status_win = curses.newwin(1, term_width, term_height - 2, 0)
            SafeCursesUtils._safe_bkgd(self.status_win, " ", self.colors.get("status_bar", 0), "status_win_bkgd")
            self.input_win = curses.newwin(1, term_width, term_height - 1, 0)
            SafeCursesUtils._safe_bkgd(self.input_win, " ", self.colors.get("input", 0), "input_win_bkgd")
            self.input_win.keypad(True)
            self.input_win.nodelay(True)

            return self.sidebar_width, self.msg_win_height, self.msg_win_width, term_height
        except curses.error as e:
            logger.critical(
                f"Curses error during window creation in WindowLayoutManager: {e}",
                exc_info=True,
            )
            return 0, 0, 0, 0 # Indicate failure

    def get_windows(self) -> Dict[str, Optional[curses.window]]:
        return {
            "msg_win": self.msg_win,
            "msg_win_top": self.msg_win_top,
            "msg_win_bottom": self.msg_win_bottom,
            "sidebar_win": self.sidebar_win,
            "status_win": self.status_win,
            "input_win": self.input_win,
        }

    def get_dimensions(self) -> Tuple[int, int, int]:
        return self.sidebar_width, self.msg_win_height, self.msg_win_width

    def delete_windows(self):
        """Explicitly deletes all window objects to free resources."""
        for win_name in ["msg_win", "msg_win_top", "msg_win_bottom", "sidebar_win", "status_win", "input_win"]:
            win = getattr(self, win_name, None)
            if win:
                try:
                    win.erase()
                    win.refresh()
                    del win
                except curses.error as e:
                    logger.warning(f"Error deleting window {win_name}: {e}")
                except Exception as ex:
                    logger.warning(f"Unexpected error deleting window {win_name}: {ex}")
            setattr(self, win_name, None) # Ensure reference is set to None
