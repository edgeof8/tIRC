import curses
import logging
from typing import Any, Deque, Tuple, Dict, Optional, TYPE_CHECKING, List # Added List
from pyrc_core.client.curses_utils import SafeCursesUtils

if TYPE_CHECKING:
    from pyrc_core.dcc.dcc_manager import DCCManager

logger = logging.getLogger("pyrc.message_panel_renderer")

class MessagePanelRenderer:
    def __init__(self, colors: Dict[str, int], dcc_manager_ref: "DCCManager"):
        self.colors = colors
        self.dcc_manager = dcc_manager_ref

    def _draw_messages_in_window(self, window: Any, context_obj: Any):
        """Draws messages for a single context into the provided window."""
        if not window or not context_obj:
            return

        try:
            SafeCursesUtils._draw_window_border_and_bkgd(window, self.colors.get("default", 0))
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0:
                return

            if hasattr(context_obj, 'type') and context_obj.type == "dcc_transfers":
                self._draw_dcc_transfer_list(window, context_obj)
                return

            messages_to_draw: List[Tuple[str, Any]] = [] # Use List for the local copy
            if hasattr(context_obj, 'messages') and isinstance(context_obj.messages, Deque):
                messages_to_draw = list(context_obj.messages) # Convert Deque to List for slicing

            if not messages_to_draw:
                return

            total_messages = len(messages_to_draw)

            scrollback_offset = 0
            if hasattr(context_obj, 'scrollback_offset') and isinstance(context_obj.scrollback_offset, int):
                scrollback_offset = max(0, context_obj.scrollback_offset)

            visible_lines = max_y

            start_idx = max(0, total_messages - visible_lines - scrollback_offset)
            end_idx = min(total_messages, start_idx + visible_lines)

            if start_idx >= end_idx:
                return

            line_render_idx = 0
            for text, color_attr in messages_to_draw[start_idx:end_idx]: # Iterate over the list slice
                if line_render_idx >= max_y:
                    break
                SafeCursesUtils._safe_addstr(
                    window, line_render_idx, 0, text[: max_x], color_attr, "message"
                )
                line_render_idx += 1

        except (TypeError, IndexError) as e:
            logger.error(f"Error indexing messages in window for context '{getattr(context_obj, 'name', 'Unknown')}': {e}", exc_info=True)
        except curses.error as e:
            logger.error(f"Curses error drawing messages in window for context '{getattr(context_obj, 'name', 'Unknown')}': {e}", exc_info=True)
        except Exception as e:
            logger.error(
                f"Unexpected error in _draw_messages_in_window for context '{getattr(context_obj, 'name', 'Unknown')}': {e}", exc_info=True
            )


    def draw(self, window: Any, context_obj: Any):
        """Draws messages for a single context. Main entry point for non-split view."""
        self._draw_messages_in_window(window, context_obj)

    def draw_split(
        self,
        top_window: Any,
        top_context: Any,
        bottom_window: Any,
        bottom_context: Any,
        active_pane: str,
    ):
        """Draws messages for split view panes."""
        if top_window:
            self._draw_messages_in_window(top_window, top_context)

        if bottom_window:
            self._draw_messages_in_window(bottom_window, bottom_context)


    def _draw_dcc_transfer_list(self, window: Any, context_obj: Any):
        if not window: return
        if not self.dcc_manager:
            logger.warning("DCCManager not available to MessagePanelRenderer for drawing DCC list.")
            SafeCursesUtils._safe_addstr(window, 0, 0, "[DCC System Error]", self.colors.get("error",0), "dcc_error")
            return

        try:
            SafeCursesUtils._draw_window_border_and_bkgd(window, self.colors.get("default", 0))
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0: return

            transfers_status_lines = self.dcc_manager.get_transfer_statuses()

            if not transfers_status_lines:
                SafeCursesUtils._safe_addstr(window, 0, 0, "No active DCC transfers.", self.colors.get("system",0), "dcc_empty")
                return

            total_lines = len(transfers_status_lines)
            scrollback_offset = 0
            if hasattr(context_obj, 'scrollback_offset') and isinstance(context_obj.scrollback_offset, int):
                scrollback_offset = max(0, context_obj.scrollback_offset)

            visible_lines = max_y

            start_idx = max(0, total_lines - visible_lines - scrollback_offset)
            end_idx = min(total_lines, start_idx + visible_lines)

            if start_idx >= end_idx: return

            line_render_idx = 0
            for status_line in transfers_status_lines[start_idx:end_idx]:
                if line_render_idx >= max_y: break
                SafeCursesUtils._safe_addstr(
                    window, line_render_idx, 0, status_line[:max_x], self.colors.get("system",0), "dcc_status_line"
                )
                line_render_idx +=1

        except Exception as e:
            logger.error(f"Unexpected error in _draw_dcc_transfer_list: {e}", exc_info=True)
            try:
                SafeCursesUtils._safe_addstr(window, 0, 0, "[Error drawing DCC list]", self.colors.get("error",0), "dcc_draw_error")
            except: pass
