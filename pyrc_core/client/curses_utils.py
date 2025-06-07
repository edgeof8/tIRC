import curses
import logging
from typing import Any

logger = logging.getLogger("pyrc.curses_utils")

class SafeCursesUtils:
    @staticmethod
    def _draw_window_border_and_bkgd(window, color_attr, title=""):
        if not window:
            return
        try:
            window.erase()
            window.bkgd(
                " ", color_attr
            )
            if title:
                max_y, max_x = window.getmaxyx()
                if max_y > 0 and max_x > 0:
                    if 1 < max_x - 1:
                        text_to_render = title[: max_x - 2]
                        SafeCursesUtils._safe_addstr(
                            window, 0, 1, text_to_render, curses.A_BOLD, "border_title"
                        )
        except curses.error as e:
            logger.warning(
                f"curses.error in _draw_window_border_and_bkgd for window {window!r}, title '{title[:30]}...': {e}"
            )
        except Exception as ex:
            logger.error(
                f"Unexpected error in _draw_window_border_and_bkgd: {ex}", exc_info=True
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

        text_to_render = text[: available_width - 1]
        num_chars_to_write = len(text_to_render)

        if num_chars_to_write > 0:
            try:
                window.addnstr(y, x, text_to_render, num_chars_to_write, attr)
            except curses.error as e:
                logger.warning(
                    f"_safe_addstr ({context_info}): curses.error writing '{text_to_render[:30]}...' at y={y},x={x},n={num_chars_to_write} (win_dims {max_y}x{max_x}): {e}"
                )
            except Exception as ex:
                logger.error(
                    f"_safe_addstr ({context_info}): Unexpected error writing '{text_to_render[:30]}...' at y={y},x={x}: {ex}",
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
            if not (0 <= y < max_y): return

            padded_text = text.ljust(max_x)

            window.addstr(y, 0, padded_text, attr)
        except curses.error as e:
            logger.warning(f"curses.error in _draw_full_width_banner for {context_info}: {e}")
