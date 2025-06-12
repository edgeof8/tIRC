import curses
import logging
from typing import Any

logger = logging.getLogger("pyrc.curses_utils")

class SafeCursesUtils:
    @staticmethod
    def _safe_erase(window: Any, context_info: str = ""):
        """Safely erases the window."""
        if not window:
            logger.debug(f"_safe_erase ({context_info}): Attempted to erase a non-existent window.")
            return
        try:
            # Added pre-check for window validity
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0: return
            window.erase()
        except curses.error as e:
            logger.warning(f"_safe_erase ({context_info}): curses.error erasing window {window!r}: {e}")
        except Exception as ex:
            logger.error(f"_safe_erase ({context_info}): Unexpected error erasing window {window!r}: {ex}", exc_info=True)

    @staticmethod
    def _safe_bkgd(window: Any, char: Any, color_pair_id: int, context_info: str = ""):
        """Safely sets the background character and attribute for the window."""
        if not window:
            logger.debug(f"_safe_bkgd ({context_info}): Attempted to set background on a non-existent window.")
            return
        try:
            # Added pre-check for window validity
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0: return
            attr = curses.color_pair(color_pair_id)
            window.bkgd(char, attr)
        except curses.error as e:
            logger.warning(f"_safe_bkgd ({context_info}): curses.error setting background for window {window!r} with pair_id {color_pair_id}: {e}")
        except Exception as ex:
            logger.error(f"_safe_bkgd ({context_info}): Unexpected error setting background for window {window!r} with pair_id {color_pair_id}: {ex}", exc_info=True)

    @staticmethod
    def _safe_box(window: Any, vertch: Any = 0, horch: Any = 0, context_info: str = ""):
        """Safely draws a border around the window."""
        if not window:
            logger.debug(f"_safe_box ({context_info}): Attempted to draw box on a non-existent window.")
            return
        try:
            # Added pre-check for window validity
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0: return
            # Use default characters if not provided
            if vertch == 0 and horch == 0:
                 window.box()
            else:
                 window.box(vertch, horch)
        except curses.error as e:
            logger.warning(f"_safe_box ({context_info}): curses.error drawing box for window {window!r}: {e}")
        except Exception as ex:
            logger.error(f"_safe_box ({context_info}): Unexpected error drawing box for window {window!r}: {ex}", exc_info=True)

    @staticmethod
    def _safe_noutrefresh(window: Any, context_info: str = ""):
        """Safely marks the window for update without refreshing the screen."""
        if not window:
            logger.debug(f"_safe_noutrefresh ({context_info}): Attempted noutrefresh on a non-existent window.")
            return
        try:
            window.noutrefresh()
        except curses.error as e:
            logger.warning(f"_safe_noutrefresh ({context_info}): curses.error during noutrefresh for window {window!r}: {e}")
        except Exception as ex:
            logger.error(f"_safe_noutrefresh ({context_info}): Unexpected error during noutrefresh for window {window!r}: {ex}", exc_info=True)

    @staticmethod
    def _safe_refresh(window: Any, context_info: str = ""):
        """Safely refreshes the window."""
        if not window:
            logger.debug(f"_safe_refresh ({context_info}): Attempted refresh on a non-existent window.")
            return
        try:
            window.refresh()
        except curses.error as e:
            logger.warning(f"_safe_refresh ({context_info}): curses.error during refresh for window {window!r}: {e}")
        except Exception as ex:
            logger.error(f"_safe_refresh ({context_info}): Unexpected error during refresh for window {window!r}: {ex}", exc_info=True)

    @staticmethod
    def _safe_clear(window: Any, context_info: str = ""):
        """Safely clears the window."""
        if not window:
            logger.debug(f"_safe_clear ({context_info}): Attempted clear on a non-existent window.")
            return
        try:
            # Added pre-check for window validity
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0: return
            window.clear()
        except curses.error as e:
            logger.warning(f"_safe_clear ({context_info}): curses.error during clear for window {window!r}: {e}")
        except Exception as ex:
            logger.error(f"_safe_clear ({context_info}): Unexpected error during clear for window {window!r}: {ex}", exc_info=True)

    @staticmethod
    def _safe_touchwin(window: Any, context_info: str = ""):
        """Safely marks the window as having been changed."""
        if not window:
            logger.debug(f"_safe_touchwin ({context_info}): Attempted touchwin on a non-existent window.")
            return
        try:
            window.touchwin()
        except curses.error as e:
            logger.warning(f"_safe_touchwin ({context_info}): curses.error during touchwin for window {window!r}: {e}")
        except Exception as ex:
            logger.error(f"_safe_touchwin ({context_info}): Unexpected error during touchwin for window {window!r}: {ex}", exc_info=True)

    @staticmethod
    def _safe_clearok(window: Any, flag: bool, context_info: str = ""):
        """Safely sets the clearok flag for the window."""
        if not window:
            logger.debug(f"_safe_clearok ({context_info}): Attempted clearok on a non-existent window.")
            return
        try:
            window.clearok(flag)
        except curses.error as e:
            logger.warning(f"_safe_clearok ({context_info}): curses.error during clearok for window {window!r}: {e}")
        except Exception as ex:
            logger.error(f"_safe_clearok ({context_info}): Unexpected error during clearok for window {window!r}: {ex}", exc_info=True)

    @staticmethod
    def _safe_curs_set(visibility: int, context_info: str = ""):
        """Safely sets the cursor visibility."""
        try:
            curses.curs_set(visibility)
        except curses.error as e:
            logger.warning(f"_safe_curs_set ({context_info}): curses.error setting cursor visibility to {visibility}: {e}")
        except Exception as ex:
            logger.error(f"_safe_curs_set ({context_info}): Unexpected error setting cursor visibility: {ex}", exc_info=True)

    @staticmethod
    def _safe_noecho(context_info: str = ""):
        """Safely disables echoing of characters."""
        try:
            curses.noecho()
        except curses.error as e:
            logger.warning(f"_safe_noecho ({context_info}): curses.error disabling echo: {e}")
        except Exception as ex:
            logger.error(f"_safe_noecho ({context_info}): Unexpected error disabling echo: {ex}", exc_info=True)

    @staticmethod
    def _safe_cbreak(context_info: str = ""):
        """Safely enters cbreak mode."""
        try:
            curses.cbreak()
        except curses.error as e:
            logger.warning(f"_safe_cbreak ({context_info}): curses.error entering cbreak mode: {e}")
        except Exception as ex:
            logger.error(f"_safe_cbreak ({context_info}): Unexpected error entering cbreak mode: {ex}", exc_info=True)

    @staticmethod
    def _safe_keypad(window: Any, enable: bool, context_info: str = ""):
        """Safely enables or disables keypad mode for a window."""
        if not window:
            logger.debug(f"_safe_keypad ({context_info}): Attempted keypad on a non-existent window.")
            return
        try:
            window.keypad(enable)
        except curses.error as e:
            logger.warning(f"_safe_keypad ({context_info}): curses.error setting keypad to {enable} for window {window!r}: {e}")
        except Exception as ex:
            logger.error(f"_safe_keypad ({context_info}): Unexpected error setting keypad: {ex}", exc_info=True)

    @staticmethod
    def _safe_start_color(context_info: str = ""):
        """Safely starts color support."""
        try:
            curses.start_color()
        except curses.error as e:
            logger.warning(f"_safe_start_color ({context_info}): curses.error starting color: {e}")
        except Exception as ex:
            logger.error(f"_safe_start_color ({context_info}): Unexpected error starting color: {ex}", exc_info=True)

    @staticmethod
    def _safe_use_default_colors(context_info: str = ""):
        """Safely uses default terminal colors."""
        try:
            curses.use_default_colors()
        except curses.error as e:
            logger.warning(f"_safe_use_default_colors ({context_info}): curses.error using default colors: {e}")
        except Exception as ex:
            logger.error(f"_safe_use_default_colors ({context_info}): Unexpected error using default colors: {ex}", exc_info=True)

    @staticmethod
    def _safe_init_pair(pair_id: int, fg: int, bg: int, context_info: str = ""):
        """Safely initializes a color pair."""
        try:
            curses.init_pair(pair_id, fg, bg)
        except curses.error as e:
            logger.warning(f"_safe_init_pair ({context_info}): curses.error initializing color pair {pair_id}: {e}")
        except Exception as ex:
            logger.error(f"_safe_init_pair ({context_info}): Unexpected error initializing color pair: {ex}", exc_info=True)

    @staticmethod
    def _safe_doupdate(context_info: str = ""):
        """Safely updates the physical screen."""
        try:
            curses.doupdate()
        except curses.error as e:
            logger.warning(f"_safe_doupdate ({context_info}): curses.error during doupdate: {e}")
        except Exception as ex:
            logger.error(f"_safe_doupdate ({context_info}): Unexpected error during doupdate: {ex}", exc_info=True)

    @staticmethod
    def _safe_endwin(context_info: str = ""):
        """Safely ends the curses session."""
        try:
            curses.endwin()
        except curses.error as e:
            logger.warning(f"_safe_endwin ({context_info}): curses.error ending curses session: {e}")
        except Exception as ex:
            logger.error(f"_safe_endwin ({context_info}): Unexpected error ending curses session: {ex}", exc_info=True)

    @staticmethod
    def _draw_window_border_and_bkgd(window, color_pair_id, title=""):
        if not window:
            return
        try:
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0:
                return
        except curses.error as e:
            logger.warning(
                f"curses.error in _draw_window_border_and_bkgd getmaxyx for window {window!r}: {e}"
            )
            return

        SafeCursesUtils._safe_erase(window, "border_and_bkgd_erase")
        SafeCursesUtils._safe_bkgd(window, " ", color_pair_id, "border_and_bkgd_bkgd")
        SafeCursesUtils._safe_box(window, context_info="border_and_bkgd_box")
        if title:
            if 1 < max_x - 1:
                text_to_render = title[: max_x - 2]
                SafeCursesUtils._safe_addstr(
                    window, 0, 1, text_to_render, curses.A_BOLD, "border_title"
                )

    @staticmethod
    def _safe_addstr(
        window: Any, y: int, x: int, text: str, attr: int, context_info: str = ""
    ):
        """Safely adds a string to a curses window, with coordinate and boundary checks."""
        if not window:
            logger.debug(
                f"_safe_addstr ({context_info}): Attempted to draw on a non-existent window."
            )
            return

        try:
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0:
                return
        except curses.error as e:
            logger.warning(
                f"_safe_addstr ({context_info}): curses.error getting getmaxyx for window {window!r}: {e}"
            )
            return
        except Exception as ex:
            logger.error(
                f"_safe_addstr ({context_info}): Unexpected error getting getmaxyx for window {window!r}: {ex}",
                exc_info=True,
            )
            return

        if not (0 <= y < max_y and 0 <= x < max_x):
            if text:
                logger.debug(
                    f"_safe_addstr ({context_info}): Skipping draw, y={y},x={x} out of bounds for win {max_y}x{max_x}. Text: '{text[:30]}...'"
                )
            return

        available_width = max_x - x
        if available_width <= 0:
            if text:
                logger.debug(
                    f"_safe_addstr ({context_info}): Skipping draw, no available width at x={x} (max_x={max_x}). Text: '{text[:30]}...'"
                )
            return

        text_to_render = text[:available_width]
        # Explicitly encode and decode to handle potential character issues
        try:
            # Attempt to encode to UTF-8 and then decode back.
            # This can sometimes normalize strings for curses.
            processed_text = text_to_render.encode('utf-8', errors='replace').decode('utf-8')
        except Exception as e_encode_decode:
            logger.warning(f"_safe_addstr ({context_info}): Error encoding/decoding text '{text_to_render[:30]}...': {e_encode_decode}. Using original text.")
            processed_text = text_to_render

        num_chars_to_write = len(processed_text) # Use length of processed text

        if num_chars_to_write > 0:
            try:
                window.addstr(y, x, processed_text, attr)
            except curses.error as e:
                logger.warning(
                    f"_safe_addstr ({context_info}): curses.error writing '{processed_text[:30]}...' at y={y},x={x} (win_dims {max_y}x{max_x}): {e}"
                )
            except Exception as ex:
                logger.error(
                    f"_safe_addstr ({context_info}): Unexpected error writing '{processed_text[:30]}...' at y={y},x={x}: {ex}",
                    exc_info=True,
                )

    @staticmethod
    def _safe_hline(
        window: Any,
        y: int,
        x: int,
        char: Any,
        n: int,
        attr: int,
        context_info: str = "",
    ):
        """Safely draws a horizontal line, with coordinate and boundary checks."""
        if not window:
            logger.debug(
                f"_safe_hline ({context_info}): Attempted to draw on a non-existent window."
            )
            return

        try:
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0:
                return
        except curses.error as e:
            logger.warning(
                f"_safe_hline ({context_info}): curses.error getting getmaxyx for window {window!r}: {e}"
            )
            return
        except Exception as ex:
            logger.error(
                f"_safe_hline ({context_info}): Unexpected error getting getmaxyx for window {window!r}: {ex}",
                exc_info=True,
            )
            return

        if not (0 <= y < max_y and 0 <= x < max_x):
            logger.debug(
                f"_safe_hline ({context_info}): Skipping draw, y={y},x={x} out of bounds for win {max_y}x{max_x}."
            )
            return

        actual_n = min(n, max_x - x)
        if actual_n <= 0:
            logger.debug(
                f"_safe_hline ({context_info}): Skipping draw, no available width (n={n}, actual_n={actual_n}) at x={x} for win {max_y}x{max_x}."
            )
            return

        try:
            window.hline(y, x, char, actual_n, attr)
        except curses.error as e:
            logger.warning(
                f"_safe_hline ({context_info}): curses.error drawing hline at y={y},x={x},n={actual_n} (win_dims {max_y}x{max_x}): {e}"
            )
        except Exception as ex:
            logger.error(
                f"_safe_hline ({context_info}): Unexpected error drawing hline at y={y},x={x}: {ex}",
                exc_info=True,
            )

    @staticmethod
    def _safe_move(window: Any, y: int, x: int, context_info: str = ""):
        """Safely moves the cursor in a window, with coordinate checks."""
        if not window:
            logger.debug(
                f"_safe_move ({context_info}): Attempted to move cursor in a non-existent window."
            )
            return

        try:
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0:
                return
        except curses.error as e:
            logger.warning(
                f"_safe_move ({context_info}): curses.error getting getmaxyx for window {window!r}: {e}"
            )
            return
        except Exception as ex:
            logger.error(
                f"_safe_move ({context_info}): Unexpected error getting getmaxyx for window {window!r}: {ex}",
                exc_info=True,
            )
            return

        safe_y = min(y, max_y - 1)
        safe_x = min(x, max_x - 1)

        if not (0 <= safe_y < max_y and 0 <= safe_x < max_x):
            if safe_y < 0 or safe_x < 0:
                logger.debug(
                    f"_safe_move ({context_info}): Skipping move, y={y},x={x} (corrected to {safe_y},{safe_x}) still invalid for win {max_y}x{max_x}."
                )
                return
        try:
            window.move(safe_y, safe_x)
        except curses.error as e:
            logger.warning(
                f"_safe_move ({context_info}): curses.error moving cursor to y={safe_y},x={safe_x} (original y={y},x={x}) (win_dims {max_y}x{max_x}): {e}"
            )
        except Exception as ex:
            logger.error(
                f"_safe_move ({context_info}): Unexpected error moving cursor to y={safe_y},x={safe_x}: {ex}",
                exc_info=True,
            )

    @staticmethod
    def _draw_full_width_banner(
        window: Any, y: int, text: str, attr: int, context_info: str = ""
    ):
        """Helper to draw text on a full-width colored banner."""
        if not window: return
        try:
            max_y, max_x = window.getmaxyx()
            if max_y <= 0 or max_x <= 0:
                logger.debug(f"Skipping banner draw, window dimensions are non-positive ({max_y}x{max_x}).")
                return
        except curses.error as e:
            logger.warning(f"curses.error in _draw_full_width_banner getmaxyx for {context_info}: {e}")
            return
        except Exception as ex:
            logger.error(f"Unexpected error in _draw_full_width_banner getmaxyx: {ex}", exc_info=True)
            return

        if not (0 <= y < max_y): return

        padded_text = text.ljust(max_x)

        SafeCursesUtils._safe_addstr(window, y, 0, padded_text, attr, context_info)
