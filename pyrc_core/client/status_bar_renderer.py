import curses
import logging
from typing import Any, Dict
from pyrc_core.client.curses_utils import SafeCursesUtils

logger = logging.getLogger("pyrc.status_bar_renderer")

class StatusBarRenderer:
    def __init__(self, colors: Dict[str, int]):
        self.colors = colors

    def draw(self, window: Any, status_data: Dict[str, Any]):
        """Draws the status bar content."""
        if not window:
            return

        SafeCursesUtils._safe_erase(window, "StatusBarRenderer.draw_erase")
        SafeCursesUtils._safe_bkgd(window, " ", self.colors["status_bar"], "StatusBarRenderer.draw_bkgd")

        try:
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0:
                return

            status_parts = []

            if "split_mode_active" in status_data and status_data["split_mode_active"]:
                split_info = f"[Split: {status_data.get('active_split_pane', '')}]"
                status_parts.append(split_info)

            if "active_context_name" in status_data and status_data["active_context_name"]:
                context_info = f"[{status_data['active_context_name']}]"
                status_parts.append(context_info)

            if "connected" in status_data:
                if status_data["connected"]:
                    status_parts.append("[Connected]")
                else:
                    status_parts.append("[Disconnected]")

            if "server" in status_data and status_data["server"]:
                server_info = f"[{status_data['server']}]"
                status_parts.append(server_info)

            if "nick" in status_data and status_data["nick"]:
                nick_info = f"[{status_data['nick']}]"
                status_parts.append(nick_info)

            status_line = " ".join(status_parts)

            if len(status_line) > max_x - 2:
                status_line = status_line[: max_x - 5] + "..."

            SafeCursesUtils._safe_addstr(
                window,
                0,
                1,
                status_line,
                self.colors["status_bar"],
                "status_bar_content",
            )

        except curses.error as e:
            logger.warning(f"Error drawing status bar: {e}")
        except Exception as ex:
            logger.error(f"Unexpected error drawing status bar: {ex}", exc_info=True)

        if window:
            SafeCursesUtils._safe_noutrefresh(window, "StatusBarRenderer.draw_noutrefresh")
