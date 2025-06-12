import curses
import logging
import re # Added for regex parsing
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
        # The background is set once when the window is created by WindowLayoutManager.
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

                # New: Parse message text for highlighting
                # This will return a list of (text_segment, color_pair_name)
                parsed_segments = self._parse_message_for_highlighting(text, context_obj)

                current_x = 0
                for segment_text, segment_color_name in parsed_segments:
                    if current_x >= max_x:
                        break # Stop if we've exceeded window width

                    # Get the curses color pair ID from the name
                    segment_color_pair_id = self.colors.get(segment_color_name, self.colors.get("other_message", 0))
                    final_color_attr = segment_color_pair_id

                    # Ensure text fits within remaining width
                    text_to_draw = segment_text[:max_x - current_x]

                    SafeCursesUtils._safe_addstr(
                        window, line_render_idx, current_x, text_to_draw, final_color_attr, "message_segment"
                    )
                    current_x += len(text_to_draw)

                # Fill remaining space on the line with the default message background color
                remaining_width = max_x - current_x
                if remaining_width > 0:
                    default_bg_color_pair_id = self.colors.get("message_panel_bg", self.colors.get("default", 0))
                    SafeCursesUtils._safe_addstr(window, line_render_idx, current_x, " " * remaining_width, default_bg_color_pair_id, "message_fill_bg")

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


    def _parse_message_for_highlighting(self, message_text: str, context_obj: Any) -> List[Tuple[str, str]]:
        """
        Parses a message string to identify and apply specific highlighting.
        Returns a list of (text_segment, color_pair_name) tuples.
        """
        segments: List[Tuple[str, str]] = []
        current_pos = 0
        default_color = "other_message"

        # Determine base color for the message
        message_base_color = default_color
        if hasattr(context_obj, 'type') and context_obj.type == "status":
            message_base_color = "system_message"
        # Add more conditions for 'my_message', 'highlight_mention' etc.
        # This requires knowing the message's origin or if it's a highlight.
        # For now, we'll assume the color_pair_id passed to _draw_messages_in_window
        # already indicates 'my_message' or 'highlight_mention' for the whole line.
        # The current implementation passes a single color_pair_id for the whole line.
        # We need to adjust the message structure to include this information.
        # For now, we'll just apply the default_color and then override for specific patterns.

        # Example: Simple regex for #channels, @nicks, +modes, timestamps, server names
        # This is a simplified example and needs robust regex for real-world IRC parsing.
        # For full implementation, consider a more sophisticated tokenization or regex engine.

        # Regex for common IRC elements
        # This is a basic example and needs refinement for robustness
        # e.g., nicks can have special chars, modes can be complex
        patterns = {
            "channel": r"(#\w+)",
            "nick": r"(@\w+)", # Simplified, needs to match actual nicks
            "mode": r"(\+\w+)", # Simplified, needs to match actual modes
            "timestamp": r"^(\[\d{2}:\d{2}:\d{2}\])", # Matches [HH:MM:SS] at start
            "server_name": r"(\birc\.\w+\.\w+\b|\bserver\.\w+\.\w+\b)", # Basic server name
        }

        # Combine patterns into a single regex for efficient scanning
        combined_pattern = '|'.join(f'(?P<{name}>{pattern})' for name, pattern in patterns.items())

        # Add specific logic for 'my_message' and 'highlight_mention'
        # This information should ideally come with the message object itself,
        # not be inferred from text content alone.
        # For now, I'll assume the message's initial color_pair_id (passed as `color_pair_id` in the original loop)
        # determines if it's 'my_message' or 'highlight_mention'.
        # The `_draw_messages_in_window` function currently passes `color_pair_id` directly.
        # We need to adjust the message structure to include this information.
        # For now, I'll just apply the default_color and then override for specific patterns.

        # If the message is already marked as 'my_message' or 'highlight_mention',
        # the entire message should take that color, overriding other highlights.
        # This logic needs to be applied *before* detailed parsing.
        # For now, I'll just apply the default_color and then override for specific patterns.

        # This function needs to be more sophisticated. It should iterate through the message,
        # find matches, and yield segments.

        # For demonstration, a very basic implementation:
        # It will prioritize the first match found.

        # This is a placeholder. A proper implementation would involve:
        # 1. Iterating through the message.
        # 2. Using regex.finditer to find all matches for all patterns.
        # 3. Sorting matches by start position.
        # 4. Iterating through sorted matches, adding non-matching text as default, then matching text with its specific color.

        # For now, a simplified approach:
        # If the message is a system message, it's all system_message color.
        # Otherwise, it's other_message, with specific overrides.

        # This is a simplified placeholder. The actual implementation will be more complex.
        # The `color_pair_id` passed to `_draw_messages_in_window` should be the *base* color.
        # Then this function will apply specific highlights on top.

        # For now, let's assume the `color_pair_id` passed to `_draw_messages_in_window`
        # is the *semantic name* of the base color (e.g., "my_message", "other_message").
        # This requires a change in how messages are stored and passed.

        # For the purpose of this plan, I will assume `color_pair_id` is the semantic name.
        base_color_name = "other_message" # Default fallback
        # In a real scenario, `color_pair_id` would be the semantic name from the message object.
        # For now, we'll just use the default and apply specific highlights.

        # Simple tokenization for demonstration
        words = message_text.split(' ')
        for word in words:
            if word.startswith('#'):
                segments.append((word + " ", "channel"))
            elif word.startswith('@'):
                segments.append((word + " ", "nick"))
            elif word.startswith('+'):
                segments.append((word + " ", "mode"))
            elif re.match(r"^\[\d{2}:\d{2}:\d{2}\]", word):
                segments.append((word + " ", "timestamp"))
            elif "irc.libera.chat" in word: # Example server name
                segments.append((word + " ", "server_name"))
            else:
                segments.append((word + " ", base_color_name))

        # Remove trailing space from the last segment
        if segments:
            last_text, last_color = segments[-1]
            segments[-1] = (last_text.rstrip(), last_color)

        return segments

    def _draw_dcc_transfer_list(self, window: Any, context_obj: Any):
        if not window: return
        if not self.dcc_manager:
            logger.warning("DCCManager not available to MessagePanelRenderer for drawing DCC list.")
            SafeCursesUtils._safe_addstr(window, 0, 0, "[DCC System Error]", self.colors.get("error_message",0), "dcc_error")
            return

        SafeCursesUtils._safe_erase(window, "MessagePanelRenderer._draw_dcc_erase")
        # Background is set by WindowLayoutManager.
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
                SafeCursesUtils._safe_addstr(window, 0, 0, "No active DCC transfers.", self.colors.get("system_message",0), "dcc_empty")
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
                    window, line_render_idx, 0, str(transfer)[:max_x], self.colors.get("system_message",0), "dcc_status_line"
                )
                line_render_idx +=1

        except Exception as e:
            logger.error(f"Unexpected error in _draw_dcc_transfer_list: {e}", exc_info=True)
            try:
                SafeCursesUtils._safe_addstr(window, 0, 0, "[Error drawing DCC list]", self.colors.get("error_message",0), "dcc_draw_error")
            except: pass
