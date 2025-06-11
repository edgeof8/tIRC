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

        SafeCursesUtils._safe_erase(window, "MessagePanelRenderer._draw_messages_erase")
        SafeCursesUtils._safe_bkgd(window, " ", self.colors.get("message_panel_bg", 0), "MessagePanelRenderer._draw_messages_bkgd")
        try:
            max_y, max_x = window.getmaxyx()
        except curses.error as e:
            logger.warning(f"curses.error getting getmaxyx for window in _draw_messages_in_window: {e}. Aborting draw.")
            return
        except Exception as ex:
            logger.error(f"Unexpected error getting getmaxyx for window in _draw_messages_in_window: {ex}", exc_info=True)
            return

        if max_y <= 0 or max_x <= 0:
            return

        if hasattr(context_obj, 'type') and context_obj.type == "dcc_transfers":
            self._draw_dcc_transfer_list(window, context_obj)
            return

        try: # Keep the try block for potential errors during message processing/drawing
            messages_to_draw: List[Tuple[str, Any]] = [] # Use List for the local copy
            if hasattr(context_obj, 'messages') and isinstance(context_obj.messages, Deque):
                messages_to_draw = list(context_obj.messages) # Convert Deque to List for slicing
            logger.debug(f"Context '{getattr(context_obj, 'name', 'Unknown')}' has {len(messages_to_draw)} messages. Messages: {[msg[0][:30] for msg in messages_to_draw]}")
            if not messages_to_draw:
                logger.debug(f"Context '{getattr(context_obj, 'name', 'Unknown')}' has no messages, skipping draw.")
                return

            total_messages = len(messages_to_draw)

            scrollback_offset = 0
            if hasattr(context_obj, 'scrollback_offset') and isinstance(context_obj.scrollback_offset, int):
                scrollback_offset = max(0, context_obj.scrollback_offset)

            visible_lines = max_y

            start_idx = max(0, total_messages - visible_lines - scrollback_offset)
            end_idx = min(total_messages, start_idx + visible_lines)
            logger.debug(f"Context '{getattr(context_obj, 'name', 'Unknown')}': total_messages={total_messages}, visible_lines={visible_lines}, scrollback_offset={scrollback_offset}, start_idx={start_idx}, end_idx={end_idx}")
            if start_idx >= end_idx:
                return

            line_render_idx = 0
            logger.debug(f"Context '{getattr(context_obj, 'name', 'Unknown')}': Drawing messages from index {start_idx} to {end_idx}")
            for text, color_pair_id in messages_to_draw[start_idx:end_idx]: # Iterate over the list slice
                if line_render_idx >= max_y:
                    logger.debug(f"Context '{getattr(context_obj, 'name', 'Unknown')}': line_render_idx={line_render_idx} >= max_y={max_y}, breaking loop.")
                    break

                # Ensure it's a valid curses attribute
                final_color_attr = curses.color_pair(color_pair_id) if color_pair_id is not None else 0

                # Log detailed color information for debugging
                try:
                    fg_color_num, bg_color_num = curses.pair_content(color_pair_id)
                    logger.debug(f"Message '{text[:20]}...' at y={line_render_idx}: color_pair_id={color_pair_id}, fg_num={fg_color_num}, bg_num={bg_color_num}, final_attr={final_color_attr}")
                except curses.error:
                    logger.warning(f"Could not get pair_content for color_pair_id {color_pair_id}. Using default attr.")
                    fg_color_num = -1
                    bg_color_num = -1

                SafeCursesUtils._safe_addstr(
                    window, line_render_idx, 0, text[: max_x], final_color_attr, "message"
                )
                line_render_idx += 1
            logger.debug(f"Context '{getattr(context_obj, 'name', 'Unknown')}': Drew {line_render_idx} messages.")

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
        if window:
            SafeCursesUtils._safe_noutrefresh(window, "MessagePanelRenderer.draw_noutrefresh")

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
            SafeCursesUtils._safe_noutrefresh(top_window, "MessagePanelRenderer.draw_split_top_noutrefresh")

        if bottom_window:
            self._draw_messages_in_window(bottom_window, bottom_context)
            SafeCursesUtils._safe_noutrefresh(bottom_window, "MessagePanelRenderer.draw_split_bottom_noutrefresh")


    def _draw_dcc_transfer_list(self, window: Any, context_obj: Any):
        if not window: return
        if not self.dcc_manager:
            logger.warning("DCCManager not available to MessagePanelRenderer for drawing DCC list.")
            SafeCursesUtils._safe_addstr(window, 0, 0, "[DCC System Error]", self.colors.get("error",0), "dcc_error")
            return

        SafeCursesUtils._safe_erase(window, "MessagePanelRenderer._draw_dcc_erase")
        SafeCursesUtils._safe_bkgd(window, " ", self.colors.get("default", 0), "MessagePanelRenderer._draw_dcc_bkgd")
        try:
            max_y, max_x = window.getmaxyx()
        except curses.error as e:
            logger.warning(f"curses.error getting getmaxyx for window in _draw_dcc_transfer_list: {e}. Aborting draw.")
            return
        except Exception as ex:
            logger.error(f"Unexpected error getting getmaxyx for window in _draw_dcc_transfer_list: {ex}", exc_info=True)
            return

        if max_y <= 0 or max_x <= 0: return

        try: # Keep the try block for potential errors during transfer list processing/drawing
            transfers = self.dcc_manager.get_all_transfers()

            if not transfers:
                SafeCursesUtils._safe_addstr(window, 0, 0, "No active DCC transfers.", self.colors.get("system",0), "dcc_empty")
                return

            total_lines = len(transfers)
            scrollback_offset = 0
            if hasattr(context_obj, 'scrollback_offset') and isinstance(context_obj.scrollback_offset, int):
                scrollback_offset = max(0, context_obj.scrollback_offset)

            visible_lines = max_y

            start_idx = max(0, total_lines - visible_lines - scrollback_offset)
            end_idx = min(total_lines, start_idx + visible_lines)

            if start_idx >= end_idx: return

            line_render_idx = 0
            for transfer in transfers[start_idx:end_idx]:
                if line_render_idx >= max_y: break
                SafeCursesUtils._safe_addstr(
                    window, line_render_idx, 0, str(transfer)[:max_x], self.colors.get("system",0), "dcc_status_line"
                )
                line_render_idx +=1

        except Exception as e:
            logger.error(f"Unexpected error in _draw_dcc_transfer_list: {e}", exc_info=True)
            try:
                SafeCursesUtils._safe_addstr(window, 0, 0, "[Error drawing DCC list]", self.colors.get("error",0), "dcc_draw_error")
            except: pass
