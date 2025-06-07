import curses
import logging
from typing import Any, Deque, Tuple, Dict, Optional
from pyrc_core.client.curses_utils import SafeCursesUtils

logger = logging.getLogger("pyrc.message_panel_renderer")

class MessagePanelRenderer:
    def __init__(self, colors: Dict[str, int]):
        self.colors = colors

    def _draw_messages_in_window(self, window: Any, context_obj: Any):
        """Draws messages for a single context into the provided window."""
        if not window or not context_obj:
            return

        try:
            window.erase()
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0:
                return

            # Special handling for DCC windows
            if context_obj.type == "dcc":
                self._draw_dcc_transfer_list(window, context_obj)
                return

            # Regular message display for other contexts
            messages = list(context_obj.messages)  # Convert deque to list for safe slicing
            if not messages:
                return

            # Calculate visible lines based on scrollback
            visible_lines = max_y - 1  # Leave room for border
            total_messages = len(messages)

            # Ensure scrollback_offset is non-negative
            scrollback_offset = max(0, context_obj.scrollback_offset)

            # Calculate start and end indices
            start_idx = max(0, total_messages - visible_lines - scrollback_offset)
            end_idx = min(total_messages, start_idx + visible_lines)

            # Ensure indices are valid
            if start_idx >= total_messages or start_idx >= end_idx:
                return

            # Draw messages
            for i, (text, color_attr) in enumerate(
                messages[start_idx:end_idx], start=1
            ):
                if i > max_y - 1:  # Leave room for border
                    break
                SafeCursesUtils._safe_addstr(
                    window, i, 1, text[: max_x - 2], color_attr, "message"
                )

        except (TypeError, IndexError) as e:
            logger.error(f"Error indexing messages in window: {e}", exc_info=True)
        except curses.error as e:
            logger.error(f"Error drawing messages in window: {e}", exc_info=True)
        except Exception as e:
            logger.error(
                f"Unexpected error in draw (MessagePanelRenderer): {e}", exc_info=True
            )

    def draw(self, window: Any, context_obj: Any):
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
        # Draw top pane
        SafeCursesUtils._draw_window_border_and_bkgd(top_window, self.colors["default"])
        if top_context:
            self._draw_messages_in_window(top_window, top_context)

        # Draw bottom pane
        SafeCursesUtils._draw_window_border_and_bkgd(bottom_window, self.colors["default"])
        if bottom_context:
            self._draw_messages_in_window(bottom_window, bottom_context)

    def _draw_dcc_transfer_list(self, window: Any, context_obj: Any):
        if not window or not context_obj:
            return

        try:
            window.erase()
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0:
                return

            transfers = list(context_obj.dcc_manager.get_transfer_statuses()) # Assuming dcc_manager is accessible via context_obj or passed
            if not transfers:
                SafeCursesUtils._safe_addstr(
                    window,
                    1,
                    1,
                    "No active DCC transfers",
                    self.colors["system"],
                    "dcc_empty",
                )
                return

            visible_lines = max_y - 1
            total_transfers = len(transfers)

            scrollback_offset = max(0, context_obj.scrollback_offset)

            start_idx = max(0, total_transfers - visible_lines - scrollback_offset)
            end_idx = min(total_transfers, start_idx + visible_lines)

            if start_idx >= total_transfers or start_idx >= end_idx:
                return

            for i, status in enumerate(transfers[start_idx:end_idx], start=1):
                if i > max_y - 1:
                    break
                SafeCursesUtils._safe_addstr(
                    window,
                    i,
                    1,
                    status[: max_x - 2],
                    self.colors["system"],
                    "dcc_status",
                )

        except (TypeError, IndexError) as e:
            logger.error(f"Error indexing DCC transfers in window: {e}", exc_info=True)
        except curses.error as e:
            logger.error(f"Error drawing DCC transfer list: {e}", exc_info=True)
        except Exception as e:
            logger.error(
                f"Unexpected error in _draw_dcc_transfer_list: {e}", exc_info=True
            )
