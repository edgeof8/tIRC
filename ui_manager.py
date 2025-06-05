import curses
import time
import logging
from typing import Optional, TYPE_CHECKING, List, Tuple, Any, Deque, Dict
from context_manager import ChannelJoinStatus  # Added import
from config import (
    COLOR_ID_DEFAULT,
    COLOR_ID_SYSTEM,
    COLOR_ID_JOIN_PART,
    COLOR_ID_NICK_CHANGE,
    COLOR_ID_MY_MESSAGE,
    COLOR_ID_OTHER_MESSAGE,
    COLOR_ID_HIGHLIGHT,
    COLOR_ID_ERROR,
    COLOR_ID_STATUS_BAR,
    COLOR_ID_SIDEBAR_HEADER,
    COLOR_ID_SIDEBAR_USER,
    COLOR_ID_INPUT,
    COLOR_ID_PM,
)

logger = logging.getLogger("pyrc.ui")

MIN_SIDEBAR_USER_LIST_WIDTH = (
    8  # Minimum practical width to attempt drawing user list items
)


class UIManager:
    def __init__(self, stdscr, client_ref):
        logger.debug("UIManager initializing.")
        self.stdscr = stdscr
        self.client = client_ref
        self.height, self.width = 0, 0
        self.msg_win, self.sidebar_win, self.status_win, self.input_win = (
            None,
            None,
            None,
            None,
        )
        # Add split-screen related attributes with proper type hints
        self.msg_win_top: Optional[curses.window] = None
        self.msg_win_bottom: Optional[curses.window] = None
        self.split_mode_active: bool = False
        self.active_split_pane: str = "top"  # Can be "top" or "bottom"
        self.top_pane_context_name: str = ""  # Initialize with empty string
        self.bottom_pane_context_name: str = ""  # Initialize with empty string
        self.sidebar_width = 0
        self.msg_win_height = 0
        self.msg_win_width = 0
        self.ui_is_too_small = False  # Flag to indicate if UI is too small to render

        self.colors = {}

        self._setup_curses_settings()
        self.setup_layout()

    def _setup_curses_settings(self):
        curses.curs_set(1)
        curses.start_color()
        curses.use_default_colors()

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
        self._init_color_pair(  # Used for nick mentions and active window/unread in sidebar
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
            "sidebar_item", COLOR_ID_SIDEBAR_USER, curses.COLOR_CYAN, -1
        )
        self._init_color_pair("input", COLOR_ID_INPUT, curses.COLOR_WHITE, -1)
        self._init_color_pair("pm", COLOR_ID_PM, curses.COLOR_MAGENTA, -1)
        self._init_color_pair("user_prefix", 14, curses.COLOR_YELLOW, -1)

    def _init_color_pair(self, name, pair_id, fg, bg):
        curses.init_pair(pair_id, fg, bg)
        self.colors[name] = curses.color_pair(pair_id)

    def setup_layout(self):
        self.height, self.width = self.stdscr.getmaxyx()

        self.sidebar_width = max(15, min(30, int(self.width * 0.25)))
        self.msg_win_height = self.height - 2
        self.msg_win_width = self.width - self.sidebar_width

        if (
            self.msg_win_height <= 0
            or self.msg_win_width <= 0
            or self.sidebar_width <= 0
        ):
            logger.error(
                f"Terminal too small for UI layout: H={self.height}, W={self.width}."
            )
            try:
                self.stdscr.erase()
                self.stdscr.addstr(
                    0,
                    0,
                    "Terminal too small. Please resize.",
                    curses.A_BOLD | self.colors.get("error", curses.color_pair(0)),
                )
                self.stdscr.refresh()
            except curses.error:
                pass
            raise Exception("Terminal too small to initialize UI.")

        logger.debug(
            f"Setup layout: H={self.height}, W={self.width}, SidebarW={self.sidebar_width}, MsgH={self.msg_win_height}, MsgW={self.msg_win_width}"
        )

        try:
            if self.split_mode_active:
                # Calculate heights for split windows (50/50 split)
                top_height = self.msg_win_height // 2
                bottom_height = self.msg_win_height - top_height

                # Create top message window
                self.msg_win_top = curses.newwin(top_height, self.msg_win_width, 0, 0)
                self.msg_win_top.scrollok(True)
                self.msg_win_top.idlok(True)

                # Create bottom message window
                self.msg_win_bottom = curses.newwin(
                    bottom_height, self.msg_win_width, top_height, 0
                )
                self.msg_win_bottom.scrollok(True)
                self.msg_win_bottom.idlok(True)

                # Set msg_win to the active pane for backward compatibility
                self.msg_win = (
                    self.msg_win_top
                    if self.active_split_pane == "top"
                    else self.msg_win_bottom
                )
            else:
                # Create single message window
                self.msg_win = curses.newwin(
                    self.msg_win_height, self.msg_win_width, 0, 0
                )
                self.msg_win.scrollok(True)
                self.msg_win.idlok(True)
                self.msg_win_top = self.msg_win
                self.msg_win_bottom = None

            self.sidebar_win = curses.newwin(
                self.height - 1,
                self.sidebar_width,
                0,
                self.msg_win_width,
            )
            self.status_win = curses.newwin(1, self.width, self.height - 2, 0)
            self.input_win = curses.newwin(1, self.width, self.height - 1, 0)
            self.input_win.keypad(True)
            self.input_win.nodelay(True)
        except curses.error as e:
            logger.critical(
                f"Curses error during window creation. Calculated dimensions: "
                f"MsgH={self.msg_win_height}, MsgW={self.msg_win_width}, "
                f"SidebarH={self.height - 1}, SidebarW={self.sidebar_width}, "
                f"StatusH=1, StatusW={self.width}, InputH=1, InputW={self.width}. Error: {e}",
                exc_info=True,
            )
            raise Exception(f"Failed to create curses windows: {e}")

    def _draw_window_border_and_bkgd(self, window, color_attr, title=""):
        if not window:
            return
        try:
            window.erase()
            window.bkgd(
                " ", color_attr
            )  # This can also raise curses.error if window is invalid
            if title:
                max_y, max_x = window.getmaxyx()
                if max_y > 0 and max_x > 0:  # Ensure window has some dimension
                    if 1 < max_x - 1:  # Check if there's space for title and padding
                        text_to_render = title[: max_x - 2]
                        self._safe_addstr(
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

    def _safe_addstr(
        self, window: Any, y: int, x: int, text: str, attr: int, context_info: str = ""
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
            # This can happen if the window object is invalid (e.g., already deleted or never properly created)
            logger.warning(
                f"_safe_addstr ({context_info}): curses.error getting getmaxyx for window {window!r}: {e}"
            )
            return
        except Exception as ex:  # Catch other unexpected errors
            logger.error(
                f"_safe_addstr ({context_info}): Unexpected error getting getmaxyx for window {window!r}: {ex}",
                exc_info=True,
            )
            return

        if not (0 <= y < max_y and 0 <= x < max_x):
            # Log only if text is non-empty, to avoid spamming for intentional empty writes if any
            if text:
                logger.debug(
                    f"_safe_addstr ({context_info}): Skipping draw, y={y},x={x} out of bounds for win {max_y}x{max_x}. Text: '{text[:30]}...'"
                )
            return

        available_width = max_x - x
        if available_width <= 0:
            if text:  # Log only if there was something to draw
                logger.debug(
                    f"_safe_addstr ({context_info}): Skipping draw, no available width at x={x} (max_x={max_x}). Text: '{text[:30]}...'"
                )
            return

        # Truncate text to fit available width, leaving one character margin
        text_to_render = text[: available_width - 1]
        num_chars_to_write = len(text_to_render)

        if num_chars_to_write > 0:
            try:
                window.addnstr(y, x, text_to_render, num_chars_to_write, attr)
            except curses.error as e:
                logger.warning(
                    f"_safe_addstr ({context_info}): curses.error writing '{text_to_render[:30]}...' at y={y},x={x},n={num_chars_to_write} (win_dims {max_y}x{max_x}): {e}"
                )
            except Exception as ex:  # Catch other unexpected errors during addstr
                logger.error(
                    f"_safe_addstr ({context_info}): Unexpected error writing '{text_to_render[:30]}...' at y={y},x={x}: {ex}",
                    exc_info=True,
                )

    def _safe_hline(
        self,
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

        # Ensure n does not exceed available width
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

    def _safe_move(self, window: Any, y: int, x: int, context_info: str = ""):
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

        # Curses allows moving cursor to max_y-1, max_x-1.
        # Moving to y=max_y or x=max_x is an error.
        safe_y = min(y, max_y - 1)
        safe_x = min(x, max_x - 1)

        if not (0 <= safe_y < max_y and 0 <= safe_x < max_x):
            # This case should ideally not be hit if y,x are derived from len(text) within bounds,
            # but as a safeguard if raw coords are passed.
            logger.debug(
                f"_safe_move ({context_info}): Corrected cursor move from y={y},x={x} to y={safe_y},x={safe_x} for win {max_y}x{max_x}. Original was out of bounds."
            )
            # We still attempt the move with corrected coordinates if they are now valid.
            # If max_y or max_x is 0, safe_y/safe_x could be -1.
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

    def _calculate_available_lines_for_user_list(self) -> int:
        """
        Calculates the approximate number of lines available purely for listing user nicks
        in the sidebar, after accounting for headers and other elements.
        """
        if not self.sidebar_win:
            return 0
        try:
            max_y, _ = self.sidebar_win.getmaxyx()
        except curses.error:  # If window not yet fully initialized or too small
            return 0

        if max_y <= 0:
            return 0

        lines_for_windows_header = 1
        try:
            # This might be called before client.context_manager is fully ready during init
            all_contexts_count = (
                len(self.client.context_manager.get_all_context_names())
                if self.client and self.client.context_manager
                else 0
            )
        except (
            Exception
        ):  # Catchall if context_manager or get_all_context_names is problematic early on
            all_contexts_count = 0

        lines_used_by_other_elements = (
            lines_for_windows_header
            + all_contexts_count
            + 3  # For gap, hline, and user list header
        )

        available_for_nicks = max_y - lines_used_by_other_elements
        return max(0, available_for_nicks)

    def draw_messages(self, current_active_ctx_obj, current_active_ctx_name_str):
        """Draw messages in the message window(s)"""
        if not self.split_mode_active:
            # Single window mode - use the original behavior
            self._draw_window_border_and_bkgd(self.msg_win, self.colors["default"])
            self._draw_messages_in_window(self.msg_win, current_active_ctx_obj)
        else:
            # Split window mode
            # Draw top pane
            self._draw_window_border_and_bkgd(self.msg_win_top, self.colors["default"])
            top_ctx = self.client.context_manager.get_context(
                self.top_pane_context_name
            )
            if top_ctx:
                self._draw_messages_in_window(self.msg_win_top, top_ctx)

            # Draw bottom pane
            self._draw_window_border_and_bkgd(
                self.msg_win_bottom, self.colors["default"]
            )
            bottom_ctx = self.client.context_manager.get_context(
                self.bottom_pane_context_name
            )
            if bottom_ctx:
                self._draw_messages_in_window(self.msg_win_bottom, bottom_ctx)

    def _draw_messages_in_window(self, window, context_obj):
        """Helper method to draw messages or specific content in a window based on context type."""
        if not window or not context_obj:
            return

        if context_obj.type == "dcc_transfers":
            self._draw_dcc_transfer_list(window, context_obj)
        else:
            # Existing message drawing logic
            try:
                max_y, max_x = window.getmaxyx()
                messages = list(context_obj.messages)  # Convert to list to support slicing
                scrollback_offset = context_obj.scrollback_offset

                available_lines = max_y - 2  # Leave room for border
                if available_lines <= 0:
                    return

                start_idx = max(0, len(messages) - available_lines - scrollback_offset)
                # Ensure end_idx doesn't exceed length of messages after adjusting for scrollback
                end_idx = max(0, len(messages) - scrollback_offset)

                # We want to display messages from start_idx up to end_idx, but only 'available_lines' number of them.
                # So, the actual slice should be messages[start_idx : start_idx + available_lines]
                # but we must also ensure that start_idx + available_lines does not exceed len(messages)
                # The current logic with start_idx and end_idx for slicing messages[start_idx:end_idx]
                # and then breaking if i >= available_lines seems okay.

                visible_messages = messages[start_idx:end_idx]

                for i, msg_tuple in enumerate(visible_messages):
                    if i >= available_lines: # Should not happen if start_idx and end_idx are calculated correctly relative to available_lines
                        break

                    y_pos = i + 1 # Start drawing from the first line inside the border

                    # Handle both tuple and dict message formats (though Context.messages should be Tuple[str, Any])
                    if isinstance(msg_tuple, tuple) and len(msg_tuple) >= 2:
                        text, color_attr = msg_tuple[0], msg_tuple[1]
                    elif isinstance(msg_tuple, dict): # Fallback, ideally not used
                        text = msg_tuple.get("text", "")
                        color_attr = msg_tuple.get("color_attr", self.colors.get("default", 0))
                    else: # Malformed message, skip or log
                        logger.warning(f"Skipping malformed message in context '{context_obj.name}': {msg_tuple}")
                        continue

                    # Truncate text to fit window width
                    # max_x is full window width. Content area is max_x - 2 (for borders).
                    # We draw at x=1, so available text width is (max_x - 1) - 1 = max_x - 2.
                    max_text_len = max_x - 2
                    if max_text_len <=0: continue # No space to draw text

                    display_text = text
                    if len(text) > max_text_len:
                        display_text = text[:max_text_len - 3] + "..." if max_text_len > 3 else text[:max_text_len]

                    self._safe_addstr(window, y_pos, 1, display_text, color_attr, f"msg_ctx_{context_obj.name}")

            except curses.error as e:
                logger.warning(f"Error drawing messages in window for context '{context_obj.name}': {e}")
            except Exception as ex:
                logger.error(f"Unexpected error drawing messages for context '{context_obj.name}': {ex}", exc_info=True)

    def _draw_dcc_transfer_list(self, window, context_obj):
        """Draws the DCC transfer list in the provided window."""
        if not window or not self.client.dcc_manager:
            return

        try:
            max_y, max_x = window.getmaxyx()
            available_lines = max_y - 2  # Leave room for border
            if available_lines <= 0:
                return

            transfer_statuses = self.client.dcc_manager.get_transfer_statuses()

            # For now, display the most recent 'available_lines'.
            # Scrollback for DCC list can be added later if context_obj.scrollback_offset is used.
            start_idx = max(0, len(transfer_statuses) - available_lines)

            lines_to_display = transfer_statuses[start_idx:]

            for i, status_line in enumerate(lines_to_display):
                if i >= available_lines:
                    break

                y_pos = i + 1 # Start below the border

                # Truncate status_line to fit window width
                max_text_len = max_x - 2 # Leave room for border
                if max_text_len <=0: continue

                display_text = status_line
                if len(status_line) > max_text_len:
                    display_text = status_line[:max_text_len - 3] + "..." if max_text_len > 3 else status_line[:max_text_len]

                # Use a default system color for DCC status lines
                color_attr = self.colors.get("system", self.colors.get("default", 0))
                self._safe_addstr(window, y_pos, 1, display_text, color_attr, f"dcc_status_{context_obj.name}")

        except curses.error as e:
            logger.warning(f"Error drawing DCC transfer list in window: {e}")
        except Exception as ex:
            logger.error(f"Unexpected error drawing DCC transfer list: {ex}", exc_info=True)

    def _draw_sidebar_context_list(
        self, max_y: int, max_x: int, current_active_ctx_name_str: str
    ) -> int:
        """Draws the list of contexts (windows) in the sidebar. Returns the next line_num."""
        if not self.sidebar_win:
            return 0
        line_num = 0
        self._safe_addstr(
            self.sidebar_win,
            line_num,
            0,
            "Windows:",
            self.colors.get("sidebar_header", 0),
            "_draw_sidebar_context_list_header",
        )
        line_num += 1  # Increment even if addstr fails, to maintain logical flow, assuming _safe_addstr prevents crash

        all_context_names_unsorted = self.client.context_manager.get_all_context_names()
        status_context_name = "Status"
        other_contexts = [
            name for name in all_context_names_unsorted if name != status_context_name
        ]
        other_contexts.sort(key=lambda x: x.lower())
        all_contexts = other_contexts
        if status_context_name in all_context_names_unsorted:
            all_contexts.append(status_context_name)

        active_context_name_for_list_highlight = current_active_ctx_name_str

        for ctx_name in all_contexts:
            if line_num >= max_y - 1:
                break

            display_name_base = ctx_name[: max_x - 4]
            attr = self.colors.get("sidebar_item", 0)
            ctx_obj = self.client.context_manager.get_context(ctx_name)
            unread_count = self.client.context_manager.get_unread_count(ctx_name)
            prefix = " "
            status_suffix = ""

            if (
                ctx_obj
                and ctx_obj.type == "channel"
                and hasattr(ctx_obj, "join_status")
            ):
                if (
                    ctx_obj.join_status == ChannelJoinStatus.PENDING_INITIAL_JOIN
                    or ctx_obj.join_status == ChannelJoinStatus.JOIN_COMMAND_SENT
                ):
                    status_suffix = " (joining...)"
                    attr = self.colors.get("sidebar_item", 0) | curses.A_DIM
                elif ctx_obj.join_status == ChannelJoinStatus.SELF_JOIN_RECEIVED:
                    status_suffix = " (users...)"
                    attr = self.colors.get("sidebar_item", 0) | curses.A_DIM
                elif ctx_obj.join_status == ChannelJoinStatus.JOIN_FAILED:
                    status_suffix = " (failed!)"
                    attr = self.colors.get("error", 0)

            if ctx_name == active_context_name_for_list_highlight:
                attr = self.colors.get("highlight", 0)
                prefix = ">"
            elif unread_count > 0:
                attr = self.colors.get("highlight", 0)
                prefix = "*"

            display_name_final = f"{prefix}{display_name_base}{status_suffix}"
            if unread_count > 0 and ctx_name != active_context_name_for_list_highlight:
                display_name_final += f" ({unread_count})"

            self._safe_addstr(
                self.sidebar_win,
                line_num,
                0,
                display_name_final,
                attr,
                "_draw_sidebar_context_list_item",
            )
            line_num += 1

        # This gap increment seems to be for spacing, ensure it doesn't push line_num out of bounds for next header
        if (
            line_num < max_y - 1
        ):  # Check before incrementing for a potential hline or next header
            line_num += 1
        return line_num

    def _draw_sidebar_user_list_header(
        self,
        line_num: int,
        max_y: int,
        max_x: int,
        active_ctx_obj_for_users,
        current_active_ctx_name_for_user_header: str,
    ) -> int:
        """Draws the user list header in the sidebar. Returns the next line_num."""
        if not self.sidebar_win or not active_ctx_obj_for_users:
            return line_num

        # Draw hline separator if there's space and it's not the very first line
        # The line_num passed here is where the hline should be drawn.
        # The original code had `line_num -1`. If line_num is the start of this section,
        # hline should be at `line_num` and header text at `line_num + 1`.
        # Let's adjust to draw hline at current `line_num`, then increment, then draw text.
        if line_num > 0 and line_num < max_y:  # Ensure hline is within bounds
            self._safe_hline(
                self.sidebar_win,
                line_num,
                0,
                curses.ACS_HLINE,
                max_x,
                0,
                "_draw_sidebar_user_list_hline",
            )
            line_num += 1  # Increment after drawing hline

        if line_num >= max_y:  # No space left for header text
            return line_num

        channel_users_dict = active_ctx_obj_for_users.users
        user_count = len(channel_users_dict)
        user_header_full = (
            f"Users in {current_active_ctx_name_for_user_header} ({user_count})"
        )

        self._safe_addstr(
            self.sidebar_win,
            line_num,
            0,
            user_header_full,
            self.colors.get("sidebar_header", 0),
            "_draw_sidebar_user_list_header_text",
        )
        line_num += 1
        return line_num

    def _draw_sidebar_user_list_items_and_indicators(
        self, line_num: int, max_y: int, max_x: int, active_ctx_obj_for_users
    ) -> int:
        """Draws the user list items and scroll indicators in the sidebar. Returns the next line_num."""
        if (
            not self.sidebar_win
            or not active_ctx_obj_for_users
            or not hasattr(active_ctx_obj_for_users, "users")
            or not active_ctx_obj_for_users.users
        ):
            return line_num

        current_user_scroll_offset = active_ctx_obj_for_users.user_list_scroll_offset
        channel_users_dict = active_ctx_obj_for_users.users

        # Check if sidebar is too narrow to meaningfully display user list
        if max_x < MIN_SIDEBAR_USER_LIST_WIDTH:
            if line_num < max_y:  # Ensure there's at least one line to draw the message
                self._safe_addstr(
                    self.sidebar_win,
                    line_num,
                    0,
                    "[Users Hidden]",
                    self.colors.get("sidebar_item", 0) | curses.A_DIM,
                    "_draw_sidebar_user_list_too_narrow",
                )
                line_num += 1
            return line_num

        sorted_user_items = sorted(
            channel_users_dict.items(), key=lambda item: item[0].lower()
        )
        total_users = len(sorted_user_items)

        available_lines_for_user_section = max_y - line_num
        lines_for_nicks = available_lines_for_user_section
        up_indicator_text = None
        down_indicator_text = None

        if current_user_scroll_offset > 0:
            if lines_for_nicks > 0:
                up_indicator_text = "^ More"[: max_x - 1]
                lines_for_nicks -= 1

        if current_user_scroll_offset + lines_for_nicks < total_users:
            if lines_for_nicks > 0:
                down_indicator_text = "v More"[: max_x - 1]
                lines_for_nicks -= 1

        lines_for_nicks = max(0, lines_for_nicks)

        if up_indicator_text and line_num < max_y:  # Check space for indicator
            self._safe_addstr(
                self.sidebar_win,
                line_num,
                1,
                up_indicator_text,
                self.colors.get("sidebar_item", 0) | curses.A_DIM,
                "_draw_sidebar_user_list_up_indicator",
            )
            line_num += 1

        start_idx = current_user_scroll_offset
        end_idx = current_user_scroll_offset + lines_for_nicks
        visible_users_page = sorted_user_items[start_idx:end_idx]

        for nick, prefix_str in visible_users_page:
            if line_num >= max_y:
                break
            display_user_with_prefix = f"{prefix_str}{nick}"
            user_display_truncated = (" " + display_user_with_prefix)[: max_x - 1]
            user_color = self.colors.get("sidebar_item", 0)
            if prefix_str == "@":
                user_color = self.colors.get("user_prefix", user_color)

            self._safe_addstr(
                self.sidebar_win,
                line_num,
                0,
                " " + display_user_with_prefix,
                user_color,
                "_draw_sidebar_user_list_item",
            )
            line_num += 1

        if down_indicator_text and line_num < max_y:  # Check space for indicator
            self._safe_addstr(
                self.sidebar_win,
                line_num,
                1,
                down_indicator_text,
                self.colors.get("sidebar_item", 0) | curses.A_DIM,
                "_draw_sidebar_user_list_down_indicator",
            )
            line_num += 1

        return line_num

    def draw_sidebar(self, current_active_ctx_obj, current_active_ctx_name_str):
        if not self.sidebar_win:
            return

        # Attempt to get dimensions first; if this fails, window is likely unusable
        try:
            max_y, max_x = self.sidebar_win.getmaxyx()
        except curses.error as e:
            logger.warning(
                f"curses.error getting getmaxyx for sidebar_win in draw_sidebar: {e}. Aborting draw."
            )
            return
        except Exception as ex:
            logger.error(
                f"Unexpected error getting getmaxyx for sidebar_win in draw_sidebar: {ex}",
                exc_info=True,
            )
            return

        if max_y <= 0 or max_x <= 0:
            logger.debug(f"Sidebar dimensions too small to draw: {max_y}x{max_x}")
            return

        self._draw_window_border_and_bkgd(
            self.sidebar_win, self.colors.get("sidebar_item", 0)
        )
        # Note: _draw_window_border_and_bkgd itself now uses getmaxyx internally for title.

        line_num = self._draw_sidebar_context_list(
            max_y, max_x, current_active_ctx_name_str
        )

        active_ctx_obj_for_users = current_active_ctx_obj

        should_show_user_list = False
        if (
            active_ctx_obj_for_users
            and active_ctx_obj_for_users.type == "channel"
            and hasattr(active_ctx_obj_for_users, "join_status")
        ):
            if active_ctx_obj_for_users.join_status in [
                ChannelJoinStatus.SELF_JOIN_RECEIVED,
                ChannelJoinStatus.FULLY_JOINED,
            ]:
                should_show_user_list = True

        if should_show_user_list:
            if line_num < max_y - 1:
                line_num = self._draw_sidebar_user_list_header(
                    line_num,
                    max_y,
                    max_x,
                    active_ctx_obj_for_users,
                    current_active_ctx_name_str,
                )
                if line_num < max_y:  # Check if space remains after header
                    line_num = self._draw_sidebar_user_list_items_and_indicators(
                        line_num, max_y, max_x, active_ctx_obj_for_users
                    )
        try:
            self.sidebar_win.noutrefresh()
        except curses.error as e:
            logger.warning(f"curses.error on noutrefresh in draw_sidebar: {e}")

    def draw_status_bar(self, current_active_ctx_obj, current_active_ctx_name_str):
        """Draw the status bar"""
        if not self.status_win:
            return

        self._draw_window_border_and_bkgd(self.status_win, self.colors["status_bar"])

        try:
            max_y, max_x = self.status_win.getmaxyx()
            if max_y <= 0 or max_x <= 0:
                return

            # Build status line components
            status_parts = []

            # Add split-screen info if active
            if self.split_mode_active:
                split_info = f"[Split: {self.active_split_pane}]"
                status_parts.append(split_info)

            # Add active context info
            if current_active_ctx_name_str:
                context_info = f"[{current_active_ctx_name_str}]"
                status_parts.append(context_info)

            # Add network status if available
            if hasattr(self.client, "network") and self.client.network:
                if self.client.network.connected:
                    status_parts.append("[Connected]")
                else:
                    status_parts.append("[Disconnected]")

            # Add server info if available
            if hasattr(self.client, "network") and self.client.network:
                server = getattr(self.client.network, "server", None)
                if server:
                    server_info = f"[{server}]"
                    status_parts.append(server_info)

            # Add nick info if available
            if hasattr(self.client, "network") and self.client.network:
                nick = getattr(self.client.network, "nick", None)
                if nick:
                    nick_info = f"[{nick}]"
                    status_parts.append(nick_info)

            # Join all parts with spaces
            status_line = " ".join(status_parts)

            # Truncate if too long
            if len(status_line) > max_x - 2:
                status_line = status_line[: max_x - 5] + "..."

            # Draw the status line
            self._safe_addstr(
                self.status_win,
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

    def draw_input_line(self):
        if not self.input_win:
            return

        try:
            max_y, max_x = self.input_win.getmaxyx()
        except curses.error as e:
            logger.warning(
                f"curses.error getting getmaxyx for input_win in draw_input_line: {e}. Aborting draw."
            )
            return
        except Exception as ex:
            logger.error(
                f"Unexpected error getting getmaxyx for input_win in draw_input_line: {ex}",
                exc_info=True,
            )
            return

        if max_y <= 0 or max_x <= 0:
            logger.debug(f"Input line dimensions too small to draw: {max_y}x{max_x}")
            return

        self._draw_window_border_and_bkgd(self.input_win, self.colors.get("input", 0))
        # Re-fetch max_y, max_x after border draw
        try:
            max_y, max_x = self.input_win.getmaxyx()
        except curses.error as e:
            logger.warning(
                f"curses.error re-getting getmaxyx for input_win in draw_input_line: {e}. Aborting draw."
            )
            return
        except Exception as ex:
            logger.error(
                f"Unexpected error re-getting getmaxyx for input_win in draw_input_line: {ex}",
                exc_info=True,
            )
            return
        if max_y <= 0 or max_x <= 0:
            return  # Check again

        prompt = "> "
        available_width = max_x - len(prompt) - 1
        current_input_buffer = self.client.input_handler.get_current_input_buffer()

        display_buffer = current_input_buffer
        if available_width <= 0:
            display_buffer = ""
        elif len(current_input_buffer) > available_width:
            if available_width > 3:
                display_buffer = "..." + current_input_buffer[-(available_width - 3) :]
            else:
                display_buffer = current_input_buffer[-available_width:]

        cursor_pos_x = len(prompt) + len(
            display_buffer
        )  # This is ideal cursor position

        input_color = self.colors.get("input", 0)
        self._safe_addstr(
            self.input_win,
            0,
            0,
            prompt + display_buffer,
            input_color,
            "draw_input_line_buffer",
        )

        self._safe_move(self.input_win, 0, cursor_pos_x, "draw_input_line_cursor")

        try:
            self.input_win.noutrefresh()
        except curses.error as e:
            logger.warning(f"curses.error on noutrefresh in draw_input_line: {e}")

    def refresh_all_windows(self):
        """Refresh all windows in the UI"""
        try:
            new_height, new_width = self.stdscr.getmaxyx()
        except curses.error as e:
            logger.error(
                f"Curses error getting stdscr.getmaxyx() in refresh_all_windows: {e}. UI update aborted."
            )
            return

        resize_occurred = new_height != self.height or new_width != self.width

        if resize_occurred:
            logger.info(
                f"Terminal resized from {self.width}x{self.height} to {new_width}x{new_height}."
            )
            self.height, self.width = new_height, new_width
            self.ui_is_too_small = False  # Reset flag before attempting layout

            try:
                # It's crucial that resizeterm is called if dimensions change.
                if self.height > 0 and self.width > 0:
                    curses.resizeterm(self.height, self.width)
                    self.stdscr.clearok(
                        True
                    )  # Force clear on next refresh after resize
                else:
                    logger.warning(
                        f"Terminal dimensions are non-positive ({self.height}x{self.width}). Skipping resizeterm."
                    )

                self.stdscr.erase()
                self.stdscr.clear()
                self.stdscr.refresh()
                self.setup_layout()

                # Touch all windows and set clearok to mark them for full redraw
                try:
                    self.stdscr.touchwin()
                    self.stdscr.clearok(True)
                    if self.split_mode_active:
                        if self.msg_win_top:
                            self.msg_win_top.touchwin()
                            self.msg_win_top.clearok(True)
                        if self.msg_win_bottom:
                            self.msg_win_bottom.touchwin()
                            self.msg_win_bottom.clearok(True)
                    else:
                        if self.msg_win:
                            self.msg_win.touchwin()
                            self.msg_win.clearok(True)
                    if self.sidebar_win:
                        self.sidebar_win.touchwin()
                        self.sidebar_win.clearok(True)
                    if self.status_win:
                        self.status_win.touchwin()
                        self.status_win.clearok(True)
                    if self.input_win:
                        self.input_win.touchwin()
                        self.input_win.clearok(True)
                except curses.error as te:
                    logger.warning(
                        f"Curses error during touchwin/clearok operations: {te}"
                    )
                except Exception as tex:
                    logger.error(
                        f"Unexpected error during touchwin/clearok operations: {tex}",
                        exc_info=True,
                    )

                # Scroll to end of messages on resize
                try:
                    self.scroll_messages("end")
                    logger.debug("Called scroll_messages('end') after resize.")
                except Exception as e_scroll_end:
                    logger.error(
                        f"Error calling scroll_messages('end') after resize: {e_scroll_end}",
                        exc_info=True,
                    )

            except Exception as e:
                logger.error(
                    f"Error during resize handling sequence: {e}", exc_info=True
                )
                if (
                    "Terminal too small" in str(e)
                    or self.height <= 0
                    or self.width <= 0
                ):
                    self.ui_is_too_small = True
                    try:
                        self.stdscr.erase()
                        msg = "Terminal too small. Please resize."
                        if self.height > 0 and self.width > 0:
                            msg_y = self.height // 2
                            msg_x = max(0, (self.width - len(msg)) // 2)
                            if msg_x + len(msg) <= self.width:
                                error_attr = self.colors.get(
                                    "error", curses.A_BOLD | curses.color_pair(0)
                                )
                                self.stdscr.addstr(msg_y, msg_x, msg, error_attr)
                        self.stdscr.refresh()
                    except curses.error as ce_small_msg:
                        logger.error(
                            f"Curses error displaying 'Terminal too small' message: {ce_small_msg}"
                        )
                    except Exception as ex_small_msg:
                        logger.error(
                            f"Unexpected error displaying 'Terminal too small' message: {ex_small_msg}",
                            exc_info=True,
                        )
                    return
                else:
                    try:
                        self.stdscr.erase()
                        generic_error_msg = "Resize Error!"
                        if self.height > 0 and self.width > 0:
                            err_y = self.height // 2
                            err_x = max(0, (self.width - len(generic_error_msg)) // 2)
                            if err_x + len(generic_error_msg) <= self.width:
                                self.stdscr.addstr(
                                    err_y,
                                    err_x,
                                    generic_error_msg,
                                    self.colors.get("error", curses.color_pair(0)),
                                )
                        self.stdscr.refresh()
                    except curses.error as ce_resize_err:
                        logger.error(
                            f"Curses error displaying 'Resize Error!' message: {ce_resize_err}"
                        )
                    except Exception as ex_resize_err:
                        logger.error(
                            f"Unexpected error displaying 'Resize Error!' message: {ex_resize_err}",
                            exc_info=True,
                        )
                    return

        # If UI is too small, show message and return
        if self.ui_is_too_small:
            if not resize_occurred:
                try:
                    self.stdscr.erase()
                    msg = "Terminal too small. Please resize."
                    if self.height > 0 and self.width > 0:
                        msg_y = self.height // 2
                        msg_x = max(0, (self.width - len(msg)) // 2)
                        if msg_x + len(msg) <= self.width:
                            error_attr = self.colors.get(
                                "error", curses.A_BOLD | curses.color_pair(0)
                            )
                            self.stdscr.addstr(msg_y, msg_x, msg, error_attr)
                    self.stdscr.refresh()
                except curses.error as ce_small_msg_repeat:
                    logger.error(
                        f"Curses error re-displaying 'Terminal too small' message: {ce_small_msg_repeat}"
                    )
                except Exception as ex_small_msg_repeat:
                    logger.error(
                        f"Unexpected error re-displaying 'Terminal too small' message: {ex_small_msg_repeat}",
                        exc_info=True,
                    )
            return

        # Get active context info
        active_ctx_name_snapshot = self.client.context_manager.active_context_name
        active_ctx_obj_snapshot = (
            self.client.context_manager.get_context(active_ctx_name_snapshot)
            if active_ctx_name_snapshot
            else None
        )

        try:
            self.stdscr.noutrefresh()
            self.draw_messages(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_sidebar(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_status_bar(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_input_line()

            # Refresh all windows
            if self.split_mode_active:
                if self.msg_win_top:
                    self.msg_win_top.noutrefresh()
                if self.msg_win_bottom:
                    self.msg_win_bottom.noutrefresh()
            else:
                if self.msg_win:
                    self.msg_win.noutrefresh()
            if self.sidebar_win:
                self.sidebar_win.noutrefresh()
            if self.status_win:
                self.status_win.noutrefresh()
            if self.input_win:
                self.input_win.noutrefresh()

            curses.doupdate()
        except curses.error as e_draw:
            logger.error(
                f"Curses error during main window drawing phase: {e_draw}",
                exc_info=True,
            )
            try:
                self.stdscr.erase()
                draw_error_msg = "UI Draw Error!"
                if self.height > 0 and self.width > 0:
                    err_y = self.height // 2
                    err_x = max(0, (self.width - len(draw_error_msg)) // 2)
                    if err_x + len(draw_error_msg) <= self.width:
                        self.stdscr.addstr(
                            err_y,
                            err_x,
                            draw_error_msg,
                            self.colors.get("error", curses.color_pair(0)),
                        )
                self.stdscr.refresh()
            except curses.error as ce_draw_err_msg:
                logger.error(
                    f"Curses error displaying 'UI Draw Error!' message: {ce_draw_err_msg}"
                )
            except Exception as ex_draw_err_msg:
                logger.error(
                    f"Unexpected error displaying 'UI Draw Error!' message: {ex_draw_err_msg}",
                    exc_info=True,
                )
        except Exception as e_critical_draw:
            logger.critical(
                f"Unexpected critical error during refresh_all_windows draw phase: {e_critical_draw}",
                exc_info=True,
            )
            try:
                self.stdscr.erase()
                critical_error_msg = "Critical UI Error!"
                if self.height > 0 and self.width > 0:
                    err_y = self.height // 2
                    err_x = max(0, (self.width - len(critical_error_msg)) // 2)
                    if err_x + len(critical_error_msg) <= self.width:
                        self.stdscr.addstr(
                            err_y,
                            err_x,
                            critical_error_msg,
                            self.colors.get("error", curses.color_pair(0)),
                        )
                self.stdscr.refresh()
            except curses.error as ce_crit_err_msg:
                logger.error(
                    f"Curses error displaying 'Critical UI Error!' message: {ce_crit_err_msg}"
                )
            except Exception as ex_crit_err_msg:
                logger.error(
                    f"Unexpected error displaying 'Critical UI Error!' message: {ex_crit_err_msg}",
                    exc_info=True,
                )

    def get_input_char(self):
        if not self.input_win:
            return curses.ERR
        try:
            return self.input_win.getch()
        except curses.error:
            return curses.ERR

    def scroll_messages(self, direction):
        """Scroll messages in the active window"""
        if not self.split_mode_active:
            # Single window mode - scroll the active context
            active_ctx = self.client.context_manager.get_active_context()
            if active_ctx:
                if direction == "up":
                    active_ctx.scrollback_offset += 1
                elif direction == "down":
                    active_ctx.scrollback_offset = max(
                        0, active_ctx.scrollback_offset - 1
                    )
                elif direction == "page_up":
                    active_ctx.scrollback_offset += self.msg_win_height - 2
                elif direction == "page_down":
                    active_ctx.scrollback_offset = max(
                        0, active_ctx.scrollback_offset - (self.msg_win_height - 2)
                    )
        else:
            # Split window mode - scroll the active pane
            if self.active_split_pane == "top":
                ctx = self.client.context_manager.get_context(
                    self.top_pane_context_name
                )
                window = self.msg_win_top
            else:
                ctx = self.client.context_manager.get_context(
                    self.bottom_pane_context_name
                )
                window = self.msg_win_bottom

            if ctx and window:
                max_y, _ = window.getmaxyx()
                if direction == "up":
                    ctx.scrollback_offset += 1
                elif direction == "down":
                    ctx.scrollback_offset = max(0, ctx.scrollback_offset - 1)
                elif direction == "page_up":
                    ctx.scrollback_offset += max_y - 2
                elif direction == "page_down":
                    ctx.scrollback_offset = max(0, ctx.scrollback_offset - (max_y - 2))

    def scroll_user_list(self, direction: str, lines_arg: Optional[int] = None):
        """Scrolls the user list in the sidebar for the active channel context."""
        if not self.sidebar_win:
            return  # Or if not visible

        active_ctx = self.client.context_manager.get_active_context()
        if not active_ctx or active_ctx.type != "channel" or not active_ctx.users:
            logger.debug("User list scroll: No active channel context or no users.")
            return

        # Use the helper to estimate viewable lines for nicks,
        # this is for pageup/pagedown calculations primarily.
        # The actual number of nicks displayed in draw_sidebar might slightly differ
        # due to indicator space.
        # For scroll amount, viewable_user_lines should be the number of nicks that *can* be shown.
        # Let's use _calculate_available_lines_for_user_list() as the basis for page size.
        viewable_nick_lines = self._calculate_available_lines_for_user_list()
        if viewable_nick_lines <= 0:  # No space to display users
            logger.debug("User list scroll: No viewable lines for nicks.")
            return

        total_users = len(active_ctx.users)
        current_offset = active_ctx.user_list_scroll_offset

        # Max offset is total users minus the number that can fit on one page
        max_scroll_offset = max(0, total_users - viewable_nick_lines)
        new_offset = current_offset
        scroll_amount = 0

        if direction == "up":
            scroll_amount = (
                lines_arg if lines_arg is not None else max(1, viewable_nick_lines // 2)
            )
            new_offset = max(0, current_offset - scroll_amount)
        elif direction == "down":
            scroll_amount = (
                lines_arg if lines_arg is not None else max(1, viewable_nick_lines // 2)
            )
            new_offset = min(max_scroll_offset, current_offset + scroll_amount)
        elif direction == "pageup":
            scroll_amount = viewable_nick_lines
            new_offset = max(0, current_offset - scroll_amount)
        elif direction == "pagedown":
            scroll_amount = viewable_nick_lines
            new_offset = min(max_scroll_offset, current_offset + scroll_amount)
        elif direction == "top":
            new_offset = 0
        elif direction == "bottom":
            new_offset = max_scroll_offset
        else:
            logger.warning(f"Unknown user scroll direction: {direction}")
            return

        # Ensure new_offset is within valid bounds again, especially if viewable_nick_lines was small
        new_offset = max(0, min(new_offset, max_scroll_offset))

        if new_offset != current_offset:
            active_ctx.user_list_scroll_offset = new_offset
            logger.debug(
                f"User list scrolled to offset {new_offset} for context {active_ctx.name}"
            )
            self.client.ui_needs_update.set()
        else:
            logger.debug(
                f"User list scroll: no change in offset ({current_offset}) for {active_ctx.name}"
            )
