import curses
import logging
from typing import Any, Dict
from pyrc_core.client.curses_utils import SafeCursesUtils

logger = logging.getLogger("pyrc.input_line_renderer")

class InputLineRenderer:
    def __init__(self, colors: Dict[str, int]):
        self.colors = colors

    def draw(self, window: Any, input_buffer_str: str, cursor_position_in_buffer: int):
        """Draws the input prompt, current input buffer, and cursor."""
        if not window:
            return

        try:
            max_y, max_x = window.getmaxyx()
        except curses.error as e:
            logger.warning(
                f"curses.error getting getmaxyx for input_win in draw: {e}. Aborting draw."
            )
            return
        except Exception as ex:
            logger.error(
                f"Unexpected error getting getmaxyx for input_win in draw: {ex}",
                exc_info=True,
            )
            return

        if max_y <= 0 or max_x <= 0:
            logger.debug(f"Input line dimensions too small to draw: {max_y}x{max_x}")
            return

        try:
            window.erase()
            # The following direct, buggy call to bkgd is removed. The background is set by WindowLayoutManager.
            # window.bkgd(" ", self.colors.get("input", 0))
        except curses.error as e:
            logger.warning(f"Error erasing input line: {e}")
            return


        try:
            max_y, max_x = window.getmaxyx() # Re-fetch dimensions in case of resize event
        except curses.error as e:
            logger.warning(
                f"curses.error re-getting getmaxyx for input_win in draw: {e}. Aborting draw."
            )
            return
        except Exception as ex:
            logger.error(
                f"Unexpected error re-getting getmaxyx for input_win in draw: {ex}",
                exc_info=True,
            )
            return
        if max_y <= 0 or max_x <= 0:
            return

        prompt = "> "
        available_width = max_x - len(prompt) - 1

        display_buffer = input_buffer_str
        if available_width <= 0:
            display_buffer = ""
        elif len(input_buffer_str) > available_width:
            if available_width > 3:
                display_buffer = "..." + input_buffer_str[-(available_width - 3) :]
            else:
                display_buffer = input_buffer_str[-available_width:]

        # Calculate cursor position relative to the displayed buffer
        # This logic needs to be refined if input_handler tracks cursor in buffer
        # For now, assume cursor_position_in_buffer is 0-indexed relative to full buffer.
        # If the display_buffer is truncated, the cursor position needs adjustment.
        actual_cursor_pos_in_display = cursor_position_in_buffer
        if len(input_buffer_str) > available_width and available_width > 3:
            # If buffer was truncated, adjust cursor position
            if cursor_position_in_buffer < (len(input_buffer_str) - (available_width - 3)):
                actual_cursor_pos_in_display = 0 # Cursor is off-screen left
            else:
                actual_cursor_pos_in_display = cursor_position_in_buffer - (len(input_buffer_str) - (available_width - 3))
        elif len(input_buffer_str) > available_width and available_width <= 3:
             actual_cursor_pos_in_display = cursor_position_in_buffer - (len(input_buffer_str) - available_width)
             actual_cursor_pos_in_display = max(0, actual_cursor_pos_in_display) # Ensure not negative

        cursor_pos_x = len(prompt) + actual_cursor_pos_in_display
        cursor_pos_x = min(cursor_pos_x, max_x - 1) # Ensure cursor stays within bounds

        input_color = self.colors.get("input", 0)
        SafeCursesUtils._safe_addstr(
            window,
            0,
            0,
            prompt + display_buffer,
            input_color,
            "draw_input_line_buffer",
        )

        SafeCursesUtils._safe_move(window, 0, cursor_pos_x, "draw_input_line_cursor")

        SafeCursesUtils._safe_noutrefresh(window, "InputLineRenderer.draw_noutrefresh")
