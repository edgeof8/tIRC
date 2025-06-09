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
        self.client = client_ref # This is IRCClient_Logic
        self.curses_manager = CursesManager(stdscr)
        self.window_layout_manager = WindowLayoutManager()
        self.colors = self.curses_manager.colors

        # Pass necessary dependencies to renderers
        self.message_panel_renderer = MessagePanelRenderer(self.colors, self.client.dcc_manager)
        self.sidebar_panel_renderer = SidebarPanelRenderer(self.colors, self.client.context_manager)
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

    def shutdown(self):
        """Cleans up curses resources."""
        logger.info("UIManager shutting down...")
        if self.curses_manager:
            self.curses_manager.cleanup()
        logger.info("UIManager shutdown complete.")

    def setup_layout(self):
        term_height, term_width = self.curses_manager.get_dimensions()
        self.height, self.width = term_height, term_width

        (
            self.sidebar_width,
            self.msg_win_height,
            self.msg_win_width,
            _ # total_height_used_by_ui - remove the unused variable
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
            self.ui_is_too_small = True
            return


        logger.debug(
            f"Setup layout: H={self.height}, W={self.width}, SidebarW={self.sidebar_width}, MsgH={self.msg_win_height}, MsgW={self.msg_win_width}"
        )

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
        except curses.error:
            return 0

        if max_y <= 0:
            return 0

        lines_for_windows_header = 1
        try:
            all_contexts_count = (
                len(self.client.context_manager.get_all_context_names())
                if self.client and self.client.context_manager
                else 0
            )
        except Exception:
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
        if self.ui_is_too_small: return

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
        if self.ui_is_too_small or not self.sidebar_win:
            return

        all_context_names = self.client.context_manager.get_all_context_names()
        self.sidebar_panel_renderer.draw(
            self.sidebar_win,
            current_active_ctx_obj,
            all_context_names
        )


    def draw_status_bar(self, current_active_ctx_obj, current_active_ctx_name_str):
        """Draw the status bar"""
        if self.ui_is_too_small or not self.status_win:
            return

        status_data = {
            "split_mode_active": self.split_mode_active,
            "active_split_pane": self.active_split_pane,
            "active_context_name": current_active_ctx_name_str,
            "connected": self.client.network_handler.connected,
            "server": self.client.server,
            "nick": self.client.nick,
        }
        self.status_bar_renderer.draw(self.status_win, status_data)


    def draw_input_line(self):
        if self.ui_is_too_small or not self.input_win or not self.client.input_handler:
            return

        current_input_buffer = self.client.input_handler.input_buffer
        cursor_pos_in_buffer = len(current_input_buffer)

        self.input_line_renderer.draw(self.input_win, current_input_buffer, cursor_pos_in_buffer)


    def refresh_all_windows(self):
        """Refresh all windows in the UI"""
        try:
            new_height, new_width = self.curses_manager.get_dimensions()
        except curses.error as e:
            logger.error(f"Curses error getting stdscr.getmaxyx() in refresh_all_windows: {e}. UI update aborted.")
            # Potentially can't even clear or show an error if stdscr is fundamentally broken.
            return

        resize_occurred = (new_height != self.height or new_width != self.width)

        if resize_occurred:
            logger.info(f"Terminal resized from {self.width}x{self.height} to {new_width}x{new_height}.")
            self.height, self.width = new_height, new_width
            self.ui_is_too_small = False # Reset flag before attempting layout

            try:
                # It's crucial that resizeterm is called if dimensions change.
                # It can fail if the new dimensions are too small (e.g., 0x0).
                if self.height > 0 and self.width > 0:
                    self.curses_manager.resize_term(self.height, self.width)
                    self.curses_manager.clearok(self.stdscr, True) # Force clear on next refresh after resize
                else:
                    # If terminal is 0x0, resizeterm might error or behave unpredictably.
                    # We'll likely hit the "Terminal too small" in setup_layout.
                    logger.warning(f"Terminal dimensions are non-positive ({self.height}x{self.width}). Skipping resizeterm.")

                self.curses_manager.erase_stdscr() # Add erase for more aggressive clearing
                self.curses_manager.clear_stdscr()
                self.curses_manager.refresh_stdscr() # Refresh stdscr itself after clear before creating subwindows
                self.setup_layout() # This might raise "Terminal too small..."

                # Touch all windows and set clearok to mark them for full redraw after successful layout
                try:
                    self.curses_manager.touchwin(self.stdscr)
                    self.curses_manager.clearok(self.stdscr, True) # Ensure stdscr is also cleared properly on next refresh cycle
                    if self.msg_win:
                        self.curses_manager.touchwin(self.msg_win)
                        self.curses_manager.clearok(self.msg_win, True)
                    if self.msg_win_top:
                        self.curses_manager.touchwin(self.msg_win_top)
                        self.curses_manager.clearok(self.msg_win_top, True)
                    if self.msg_win_bottom:
                        self.curses_manager.touchwin(self.msg_win_bottom)
                        self.curses_manager.clearok(self.msg_win_bottom, True)
                    if self.sidebar_win:
                        self.curses_manager.touchwin(self.sidebar_win)
                        self.curses_manager.clearok(self.sidebar_win, True)
                    if self.status_win:
                        self.curses_manager.touchwin(self.status_win)
                        self.curses_manager.clearok(self.status_win, True)
                    if self.input_win:
                        self.curses_manager.touchwin(self.input_win)
                        self.curses_manager.clearok(self.input_win, True)
                except curses.error as te:
                    logger.warning(f"Curses error during touchwin/clearok operations: {te}")
                except Exception as tex:
                    logger.error(f"Unexpected error during touchwin/clearok operations: {tex}", exc_info=True)

                # Scroll to end of messages on resize to show latest messages
                try:
                    self.scroll_messages("end")
                    logger.debug(f"Called scroll_messages('end') after resize.")
                except Exception as e_scroll_end:
                    logger.error(f"Error calling scroll_messages('end') after resize: {e_scroll_end}", exc_info=True)


            except Exception as e: # Catches exceptions from resizeterm or setup_layout
                logger.error(f"Error during resize handling sequence: {e}", exc_info=True)
                if "Terminal too small" in str(e) or self.height <=0 or self.width <=0 :
                    self.ui_is_too_small = True
                    try:
                        self.curses_manager.erase_stdscr()
                        msg = "Terminal too small. Please resize."
                        # Ensure msg_y and msg_x are valid before trying to draw
                        if self.height > 0 and self.width > 0:
                            msg_y = self.height // 2
                            msg_x = max(0, (self.width - len(msg)) // 2)
                            if msg_x + len(msg) <= self.width: # Check if message can fit
                                error_attr = self.curses_manager.get_color("error") | curses.A_BOLD
                                self.curses_manager.addstr_stdscr(msg_y, msg_x, msg, error_attr)
                        # else: message won't fit, stdscr will be blank
                        self.curses_manager.refresh_stdscr()
                    except curses.error as ce_small_msg:
                        logger.error(f"Curses error displaying 'Terminal too small' message: {ce_small_msg}")
                    except Exception as ex_small_msg:
                        logger.error(f"Unexpected error displaying 'Terminal too small' message: {ex_small_msg}", exc_info=True)
                    return # Do not proceed to draw other windows
                else:
                    # Handle other critical resize errors
                    try:
                        self.curses_manager.erase_stdscr()
                        generic_error_msg = "Resize Error!"
                        if self.height > 0 and self.width > 0:
                            err_y = self.height // 2
                            err_x = max(0, (self.width - len(generic_error_msg)) // 2)
                            if err_x + len(generic_error_msg) <= self.width:
                                self.curses_manager.addstr_stdscr(err_y, err_x, generic_error_msg, self.curses_manager.get_color("error"))
                        self.curses_manager.refresh_stdscr()
                    except curses.error as ce_resize_err:
                        logger.error(f"Curses error displaying 'Resize Error!' message: {ce_resize_err}")
                    except Exception as ex_resize_err:
                        logger.error(f"Unexpected error displaying 'Resize Error!' message: {ex_resize_err}", exc_info=True)
                    return # Do not proceed

        # If UI is marked as too small (either from this resize or a previous one)
        if self.ui_is_too_small:
            # Attempt to re-display the "too small" message if resize didn't just happen,
            # or ensure stdscr is refreshed if it was already set up by the resize block.
            # This covers cases where a refresh is called without a resize but the UI is still too small.
            if not resize_occurred: # If no resize, the message might not have been redrawn
                try:
                    self.curses_manager.erase_stdscr() # Ensure clean slate
                    msg = "Terminal too small. Please resize."
                    if self.height > 0 and self.width > 0:
                        msg_y = self.height // 2
                        msg_x = max(0, (self.width - len(msg)) // 2)
                        if msg_x + len(msg) <= self.width: # Check if message can fit
                            error_attr = self.curses_manager.get_color("error") | curses.A_BOLD
                            self.curses_manager.addstr_stdscr(msg_y, msg_x, msg, error_attr)
                    self.curses_manager.refresh_stdscr()
                except curses.error as ce_small_msg_repeat:
                    logger.error(f"Curses error re-displaying 'Terminal too small' message: {ce_small_msg_repeat}")
                except Exception as ex_small_msg_repeat:
                    logger.error(f"Unexpected error re-displaying 'Terminal too small' message: {ex_small_msg_repeat}", exc_info=True)

            try:
                # If stdscr was touched, doupdate might be needed, or refresh if only stdscr.
                # For simplicity, a refresh on stdscr should be safe.
                self.curses_manager.refresh_stdscr()
            except curses.error as e_doupdate_small:
                 logger.warning(f"Curses error during doupdate/refresh when UI is too small: {e_doupdate_small}")
            except Exception as ex_doupdate_small:
                logger.error(f"Unexpected error during doupdate/refresh when UI is too small: {ex_doupdate_small}", exc_info=True)
            return

        # --- Proceed with drawing individual windows only if UI is not too small ---
        active_ctx_name_snapshot = self.client.context_manager.active_context_name
        active_ctx_obj_snapshot = self.client.context_manager.get_context(active_ctx_name_snapshot) if active_ctx_name_snapshot else None

        try:
            self.curses_manager.noutrefresh_stdscr() # Prepare stdscr for batched update
            self.draw_messages(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_sidebar(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_status_bar(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_input_line()
            self.curses_manager.update_screen() # Perform batched update
        except curses.error as e_draw:
            logger.error(f"Curses error during main window drawing phase: {e_draw}", exc_info=True)
            # Attempt to display a generic UI draw error on stdscr
            try:
                self.curses_manager.erase_stdscr()
                draw_error_msg = "UI Draw Error!"
                if self.height > 0 and self.width > 0 :
                    err_y = self.height // 2
                    err_x = max(0, (self.width - len(draw_error_msg)) // 2)
                    if err_x + len(draw_error_msg) <= self.width:
                        self.curses_manager.addstr_stdscr(err_y, err_x, draw_error_msg, self.curses_manager.get_color("error"))
                self.curses_manager.refresh_stdscr()
            except curses.error as ce_draw_err_msg:
                logger.error(f"Curses error displaying 'UI Draw Error!' message: {ce_draw_err_msg}")
            except Exception as ex_draw_err_msg:
                logger.error(f"Unexpected error displaying 'UI Draw Error!' message: {ex_draw_err_msg}", exc_info=True)
            # No return here, let it fall through if displaying the error fails.
            # The UI might be stuck, but we've logged the core issue.
        except Exception as e_critical_draw:
            logger.critical(f"Unexpected critical error during refresh_all_windows draw phase: {e_critical_draw}", exc_info=True)
            try:
                self.curses_manager.erase_stdscr()
                critical_error_msg = "Critical UI Error!"
                if self.height > 0 and self.width > 0:
                    err_y = self.height // 2
                    err_x = max(0, (self.width - len(critical_error_msg)) // 2)
                    if err_x + len(critical_error_msg) <= self.width:
                        self.curses_manager.addstr_stdscr(err_y, err_x, critical_error_msg, self.curses_manager.get_color("error"))
                self.curses_manager.refresh_stdscr()
            except curses.error as ce_crit_err_msg:
                logger.error(f"Curses error displaying 'Critical UI Error!' message: {ce_crit_err_msg}")
            except Exception as ex_crit_err_msg:
                logger.error(f"Unexpected error displaying 'Critical UI Error!' message: {ex_crit_err_msg}", exc_info=True)

    async def add_message_to_context(
        self, text: str, color_attr: int, prefix_time: bool, context_name: str
    ):
        """Adds a message to the specified context's message history."""
        final_text = text
        if prefix_time:
            timestamp = time.strftime("%H:%M:%S")
            final_text = f"[{timestamp}] {text}"

        self.client.context_manager.add_message_to_context(
            context_name=context_name, text_line=final_text, color_attr=color_attr
        )

    def get_input_char(self):
        if not self.input_win:
            return curses.ERR
        try:
            return self.input_win.getch()
        except curses.error:
            return curses.ERR

    def scroll_messages(self, direction: str, lines: int = 1):
        """Scroll messages in the active window/pane."""
        target_ctx: Optional[Any] = None
        target_win_height = self.msg_win_height

        if not self.split_mode_active:
            target_ctx = self.client.context_manager.get_active_context()
            if self.msg_win:
                try:
                    target_win_height = self.msg_win.getmaxyx()[0]
                except curses.error: pass
        else:
            if self.active_split_pane == "top":
                target_ctx = self.client.context_manager.get_context(self.top_pane_context_name)
                if self.msg_win_top:
                    try:
                        target_win_height = self.msg_win_top.getmaxyx()[0]
                    except curses.error: pass
            else:
                target_ctx = self.client.context_manager.get_context(self.bottom_pane_context_name)
                if self.msg_win_bottom:
                    try:
                        target_win_height = self.msg_win_bottom.getmaxyx()[0]
                    except curses.error: pass

        if target_ctx and hasattr(target_ctx, 'scrollback_offset'):
            page_scroll_amount = max(1, target_win_height - 2)
            if direction == "up":
                target_ctx.scrollback_offset += lines
            elif direction == "down":
                target_ctx.scrollback_offset = max(0, target_ctx.scrollback_offset - lines)
            elif direction == "page_up":
                target_ctx.scrollback_offset += page_scroll_amount
            elif direction == "page_down":
                target_ctx.scrollback_offset = max(0, target_ctx.scrollback_offset - page_scroll_amount)
            elif direction == "home":
                if hasattr(target_ctx, 'messages'):
                    total_messages = len(target_ctx.messages)
                    target_ctx.scrollback_offset = max(0, total_messages - page_scroll_amount)
            elif direction == "end":
                target_ctx.scrollback_offset = 0

            self.client.ui_needs_update.set()

    def scroll_user_list(self, direction: str, lines_arg: Optional[int] = None):
        """Scrolls the user list in the sidebar for the active channel context."""
        if not self.sidebar_win: return

        active_ctx = self.client.context_manager.get_active_context()
        if not active_ctx or active_ctx.type != "channel" or not hasattr(active_ctx, 'users') or not active_ctx.users:
            logger.debug("User list scroll: No active channel context or no users.")
            return

        viewable_nick_lines = self._calculate_available_lines_for_user_list()
        if viewable_nick_lines <= 0:
            logger.debug("User list scroll: No viewable lines for nicks.")
            return

        total_users = len(active_ctx.users)
        current_offset = active_ctx.user_list_scroll_offset if hasattr(active_ctx, 'user_list_scroll_offset') else 0

        max_scroll_offset = max(0, total_users - viewable_nick_lines)
        new_offset = current_offset

        scroll_amount_one_line = 1
        scroll_amount_page = max(1, viewable_nick_lines)

        if direction == "up":
            new_offset = max(0, current_offset - (lines_arg if lines_arg is not None else scroll_amount_one_line))
        elif direction == "down":
            new_offset = min(max_scroll_offset, current_offset + (lines_arg if lines_arg is not None else scroll_amount_one_line))
        elif direction == "pageup":
            new_offset = max(0, current_offset - scroll_amount_page)
        elif direction == "pagedown":
            new_offset = min(max_scroll_offset, current_offset + scroll_amount_page)
        elif direction == "top":
            new_offset = 0
        elif direction == "bottom":
            new_offset = max_scroll_offset
        else:
            logger.warning(f"Unknown user scroll direction: {direction}")
            return

        if hasattr(active_ctx, 'user_list_scroll_offset') and new_offset != current_offset:
            active_ctx.user_list_scroll_offset = new_offset
            logger.debug(f"User list scrolled to offset {new_offset} for context {active_ctx.name}")
            self.client.ui_needs_update.set()
        elif not hasattr(active_ctx, 'user_list_scroll_offset'):
             logger.warning(f"Context {active_ctx.name} missing 'user_list_scroll_offset'. Cannot scroll user list.")
        else:
            logger.debug(f"User list scroll: no change in offset ({current_offset}) for {active_ctx.name}")
