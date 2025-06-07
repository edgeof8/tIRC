import curses
import time
import logging
from typing import Optional, TYPE_CHECKING, List, Tuple, Any, Deque, Dict
from pyrc_core.context_manager import ChannelJoinStatus
from pyrc_core.client.curses_utils import SafeCursesUtils
from pyrc_core.client.curses_manager import CursesManager
from pyrc_core.client.window_layout_manager import WindowLayoutManager
from pyrc_core.client.message_panel_renderer import MessagePanelRenderer
from pyrc_core.client.sidebar_panel_renderer import SidebarPanelRenderer
from pyrc_core.client.status_bar_renderer import StatusBarRenderer
from pyrc_core.client.input_line_renderer import InputLineRenderer

logger = logging.getLogger("pyrc.ui")

MIN_SIDEBAR_USER_LIST_WIDTH = (
    8  # Minimum practical width to attempt drawing user list items
)


class UIManager:
    def __init__(self, stdscr, client_ref):
        logger.debug("UIManager initializing.")
        self.stdscr = stdscr
        self.client = client_ref
        self.curses_manager = CursesManager(stdscr)
        self.window_layout_manager = WindowLayoutManager()
        self.colors = self.curses_manager.colors
        self.message_panel_renderer = MessagePanelRenderer(self.colors)
        self.sidebar_panel_renderer = SidebarPanelRenderer(self.colors)
        self.status_bar_renderer = StatusBarRenderer(self.colors)
        self.input_line_renderer = InputLineRenderer(self.colors)
        self.height: int = 0
        self.width: int = 0
        self.msg_win: Optional[curses.window] = None
        self.sidebar_win: Optional[curses.window] = None
        self.status_win: Optional[curses.window] = None
        self.input_win: Optional[curses.window] = None
        self.msg_win_top: Optional[curses.window] = None
        self.msg_win_bottom: Optional[curses.window] = None

        self.split_mode_active: bool = False
        self.active_split_pane: str = "top"
        self.top_pane_context_name: str = ""
        self.bottom_pane_context_name: str = ""
        self.sidebar_width: int = 0
        self.msg_win_height: int = 0
        self.msg_win_width: int = 0
        self.ui_is_too_small: bool = False

        self.setup_layout()

    def setup_layout(self):
        term_height, term_width = self.curses_manager.get_dimensions()
        self.height, self.width = term_height, term_width

        (
            self.sidebar_width,
            self.msg_win_height,
            self.msg_win_width,
            total_height_used_by_ui,
        ) = self.window_layout_manager.calculate_and_create_windows(
            term_height, term_width, self.split_mode_active, self.active_split_pane
        )

        if (
            self.msg_win_height <= 0
            or self.msg_win_width <= 0
            or self.sidebar_width <= 0
        ):
            logger.error(
                f"Terminal too small for UI layout: H={self.height}, W={self.width}."
            )
            try:
                self.curses_manager.erase_stdscr()
                self.curses_manager.addstr_stdscr(
                    0,
                    0,
                    "Terminal too small. Please resize.",
                    curses.A_BOLD | self.curses_manager.get_color("error"),
                )
                self.curses_manager.refresh_stdscr()
            except curses.error:
                pass
            raise Exception("Terminal too small to initialize UI.")

        logger.debug(
            f"Setup layout: H={self.height}, W={self.width}, SidebarW={self.sidebar_width}, MsgH={self.msg_win_height}, MsgW={self.msg_win_width}"
        )

        # Get window references from the layout manager
        windows = self.window_layout_manager.get_windows()
        self.msg_win = windows["msg_win"]
        self.msg_win_top = windows["msg_win_top"]
        self.msg_win_bottom = windows["msg_win_bottom"]
        self.sidebar_win = windows["sidebar_win"]
        self.status_win = windows["status_win"]
        self.input_win = windows["input_win"]

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
            self.message_panel_renderer.draw(self.msg_win, current_active_ctx_obj)
        else:
            top_ctx = self.client.context_manager.get_context(
                self.top_pane_context_name
            )
            bottom_ctx = self.client.context_manager.get_context(
                self.bottom_pane_context_name
            )
            self.message_panel_renderer.draw_split(
                self.msg_win_top, top_ctx,
                self.msg_win_bottom, bottom_ctx,
                self.active_split_pane
            )



    def draw_sidebar(self, current_active_ctx_obj, current_active_ctx_name_str):
        if not self.sidebar_win:
            return

        all_context_names = self.client.context_manager.get_all_context_names()
        self.sidebar_panel_renderer.draw(
            self.sidebar_win,
            current_active_ctx_obj,
            all_context_names
        )


    def draw_status_bar(self, current_active_ctx_obj, current_active_ctx_name_str):
        """Draw the status bar"""
        if not self.status_win:
            return

        SafeCursesUtils._draw_window_border_and_bkgd(self.status_win, self.colors["status_bar"])

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
            SafeCursesUtils._safe_addstr(
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

        SafeCursesUtils._draw_window_border_and_bkgd(self.input_win, self.colors.get("input", 0))
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
        SafeCursesUtils._safe_addstr(
            self.input_win,
            0,
            0,
            prompt + display_buffer,
            input_color,
            "draw_input_line_buffer",
        )

        SafeCursesUtils._safe_move(self.input_win, 0, cursor_pos_x, "draw_input_line_cursor")

        try:
            self.input_win.noutrefresh()
        except curses.error as e:
            logger.warning(f"curses.error on noutrefresh in draw_input_line: {e}")

    def refresh_all_windows(self):
        """Refresh all windows in the UI"""
        try:
            new_height, new_width = self.curses_manager.get_dimensions()
        except Exception as e: # Catch generic exception for safety
            logger.error(
                f"Error getting stdscr dimensions in refresh_all_windows: {e}. UI update aborted."
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
                # Delegate window deletion to WindowLayoutManager
                self.window_layout_manager.delete_windows()

                # Explicitly set references to None after delegating deletion
                self.msg_win = self.msg_win_top = self.msg_win_bottom = (
                    self.sidebar_win
                ) = self.status_win = self.input_win = None

                # It's crucial that resizeterm is called if dimensions change.
                if self.height > 0 and self.width > 0:
                    self.curses_manager.resize_term(self.height, self.width)
                else:
                    logger.warning(
                        f"Terminal dimensions are non-positive ({self.height}x{self.width}). Skipping resize."
                    )
                    self.ui_is_too_small = True
                    return

                # Clear and refresh stdscr first
                self.curses_manager.erase_stdscr()
                self.curses_manager.clear_stdscr()
                self.curses_manager.refresh_stdscr()

                # Recreate all windows
                self.setup_layout()

                # Touch all windows and set clearok to mark them for full redraw
                # Iterate through newly created windows
                newly_created_windows = [
                    self.stdscr,
                    self.msg_win,
                    self.msg_win_top,
                    self.msg_win_bottom,
                    self.sidebar_win,
                    self.status_win,
                    self.input_win,
                ]
                for win in newly_created_windows:
                    if win:
                        self.curses_manager.touchwin(win)
                        self.curses_manager.clearok(win, True)

                # Scroll to end of messages on resize
                try:
                    # Scroll all contexts to end after resize
                    all_context_names = (
                        self.client.context_manager.get_all_context_names()
                    )
                    for ctx_name in all_context_names:
                        ctx = self.client.context_manager.get_context(ctx_name)
                        if ctx:
                            ctx.scrollback_offset = (
                                0  # Reset scroll to show latest messages
                            )

                    # Also ensure the active message window scrolls to the bottom if it's not split
                    # If split, the drawing logic handles the viewable part based on offset=0
                    if not self.split_mode_active and self.msg_win:
                        # Ensure scrollok and idlok are true for scrolling to end (might be redundant but safe)
                        self.msg_win.scrollok(True)
                        self.msg_win.idlok(True)
                        self.msg_win.scroll(
                            1000000
                        )  # Attempt to scroll to the very end

                except Exception as e:
                    logger.error(f"Error scrolling messages after resize: {e}")

            except Exception as e:
                logger.error(f"Error during resize handling: {e}", exc_info=True)
                self.ui_is_too_small = True
                return

        # If UI is too small, show message and return
        if self.ui_is_too_small:
            try:
                self.curses_manager.erase_stdscr()
                msg = "Terminal too small. Please resize."
                if self.height > 0 and self.width > 0:
                    msg_y = self.height // 2
                    msg_x = max(0, (self.width - len(msg)) // 2)
                    if msg_x + len(msg) <= self.width:
                        error_attr = self.curses_manager.get_color("error") | curses.A_BOLD
                        self.curses_manager.addstr_stdscr(msg_y, msg_x, msg, error_attr)
                self.curses_manager.refresh_stdscr()
            except Exception as e:
                logger.error(f"Error displaying 'Terminal too small' message: {e}")
            return

        # Get active context info
        try:
            active_ctx_name_snapshot = self.client.context_manager.active_context_name
            active_ctx_obj_snapshot = (
                self.client.context_manager.get_context(active_ctx_name_snapshot)
                if active_ctx_name_snapshot
                else None
            )
        except Exception as e:
            logger.error(f"Error getting active context: {e}")
            active_ctx_name_snapshot = None
            active_ctx_obj_snapshot = None

        # Draw UI components with individual error handling
        self.curses_manager.noutrefresh_stdscr()

        try:
            self.draw_messages(active_ctx_obj_snapshot, active_ctx_name_snapshot)
        except Exception as e:
            logger.error(f"Error drawing messages: {e}")

        try:
            self.draw_sidebar(active_ctx_obj_snapshot, active_ctx_name_snapshot)
        except Exception as e:
            logger.error(f"Error drawing sidebar: {e}")

        try:
            self.draw_status_bar(active_ctx_obj_snapshot, active_ctx_name_snapshot)
        except Exception as e:
            logger.error(f"Error drawing status bar: {e}")

        try:
            self.draw_input_line()
        except Exception as e:
            logger.error(f"Error drawing input line: {e}")

        # Refresh all windows with individual error handling
        try:
            if self.split_mode_active:
                if self.msg_win_top:
                    self.msg_win_top.noutrefresh()
                if self.msg_win_bottom:
                    self.msg_win_bottom.noutrefresh()
            else:
                if self.msg_win:
                    self.msg_win.noutrefresh()
        except curses.error as e:
            logger.error(f"Error refreshing message windows: {e}")

        try:
            if self.sidebar_win:
                self.sidebar_win.noutrefresh()
        except curses.error as e:
            logger.error(f"Error refreshing sidebar: {e}")

        try:
            if self.status_win:
                self.status_win.noutrefresh()
        except curses.error as e:
            logger.error(f"Error refreshing status window: {e}")

        try:
            if self.input_win:
                self.input_win.noutrefresh()
        except curses.error as e:
            logger.error(f"Error refreshing input window: {e}")

        self.curses_manager.update_screen()

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
