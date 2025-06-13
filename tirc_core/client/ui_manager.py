import curses
import time
import logging
import asyncio # Import asyncio
from typing import Optional, TYPE_CHECKING, List, Tuple, Any, Deque, Dict
from tirc_core.context_manager import ChannelJoinStatus
from tirc_core.client.curses_utils import SafeCursesUtils
from tirc_core.client.curses_manager import CursesManager
from tirc_core.client.window_layout_manager import WindowLayoutManager
from tirc_core.client.message_panel_renderer import MessagePanelRenderer
from tirc_core.client.sidebar_panel_renderer import SidebarPanelRenderer
from tirc_core.client.status_bar_renderer import StatusBarRenderer
from tirc_core.client.input_line_renderer import InputLineRenderer

logger = logging.getLogger("tirc.ui")

MIN_SIDEBAR_USER_LIST_WIDTH = (
    8  # Minimum practical width to attempt drawing user list items
)


class UIManager:
    def __init__(self, stdscr, client_ref):
        logger.debug("UIManager initializing.")
        self.stdscr = stdscr
        self.client = client_ref # This is IRCClient_Logic
        self.curses_manager = CursesManager(stdscr, client_ref.config) # Pass the config object
        self.colors = self.curses_manager.colors # Get colors from CursesManager
        self.window_layout_manager = WindowLayoutManager(self.colors) # Pass colors to WindowLayoutManager

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
        self.resize_pending: bool = False # Flag for resize event

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
            _
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
            SafeCursesUtils._safe_erase(self.stdscr, "UIManager.setup_layout_too_small_erase")
            SafeCursesUtils._safe_addstr(
                self.stdscr,
                0,
                0,
                "Terminal too small. Please resize.",
                curses.A_BOLD | self.curses_manager.get_color("error"),
                "UIManager.setup_layout_too_small_addstr"
            )
            SafeCursesUtils._safe_refresh(self.stdscr, "UIManager.setup_layout_too_small_refresh")
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

    async def handle_resize(self):
        """Signal that a UI refresh is needed due to resize and set flag."""
        logger.info("UIManager.handle_resize called, setting ui_needs_update and resize_pending flag.")
        # Removed direct curses.resize_term(0,0) call from here.
        # It will be handled by CursesManager.handle_terminal_resize during the main refresh.
        self.resize_pending = True
        self.client.ui_needs_update.set()

    async def refresh_all_windows(self):
        """Refresh all windows in the UI"""
        process_resize_this_call = self.resize_pending

        if process_resize_this_call:
            self.resize_pending = False # Consume the flag
            logger.info("Resize event detected by flag. Performing full resize sequence.")
            try:
                new_height, new_width = self.curses_manager.get_dimensions() # Get new dimensions first
                logger.info(f"New dimensions from get_dimensions: H={new_height}, W={new_width}")

                # Update UIManager's internal dimensions before Curses operations
                self.height = new_height
                self.width = new_width
                self.ui_is_too_small = False # Assume not too small initially

                logger.info("PERFORMING RESIZE OPS (SYNC): Starting.")

                # 1. Delete old windows
                self.window_layout_manager.delete_windows()
                logger.debug("UIManager (SYNC): Existing windows deleted.")

                # 2. Notify Curses of the resize (calls resize_term) and refresh stdscr
                self.curses_manager.handle_terminal_resize(new_height, new_width)
                logger.debug("UIManager (SYNC): Terminal resized and stdscr refreshed via CursesManager.")

                # 3. Re-create layout with new dimensions
                self.setup_layout() # This will use self.height, self.width which are now updated
                logger.debug("UIManager (SYNC): New layout setup complete post-resize.")

                logger.info(f"UIManager state updated to {self.width}x{self.height} after resize ops.")

                self.scroll_messages("end")
                logger.debug("Called scroll_messages('end') after resize.")
                logger.info("PERFORMING RESIZE OPS (SYNC): Finished.")

            except curses.error as e_curses_resize:
                logger.critical(f"Curses error during resize handling: {e_curses_resize}", exc_info=True)
                self.ui_is_too_small = True
            except Exception as e_generic_resize:
                logger.critical(f"Generic error during resize handling: {e_generic_resize}", exc_info=True)
                self.ui_is_too_small = True
        else:
            # Standard refresh if no resize event was pending
            # Check if dimensions changed unexpectedly (e.g., if flag was missed)
            try:
                current_h, current_w = self.curses_manager.get_dimensions()
                if current_h != self.height or current_w != self.width:
                    logger.warning(f"Dimensions changed ({current_w}x{current_h} from {self.width}x{self.height}) without resize_pending flag. Forcing resize path.")
                    self.resize_pending = True # Set flag to re-run with resize logic
                    self.client.ui_needs_update.set() # Ensure it runs again
                    return # Exit this refresh, next one will handle resize
            except curses.error:
                logger.error("Curses error getting dimensions in non-resize path. UI update aborted.")
                return

        # If UI is marked as too small (either from this resize or a previous one)
        if self.ui_is_too_small:
            SafeCursesUtils._safe_erase(self.stdscr, "UIManager.too_small_repeat_erase") # Ensure clean slate
            msg = "Terminal too small. Please resize."
            if self.height > 0 and self.width > 0:
                msg_y = self.height // 2
                msg_x = max(0, (self.width - len(msg)) // 2)
                if msg_x + len(msg) <= self.width: # Check if message can fit
                    error_attr = self.curses_manager.get_color("error") | curses.A_BOLD
                    SafeCursesUtils._safe_addstr(self.stdscr, msg_y, msg_x, msg, error_attr, "UIManager.too_small_repeat_addstr")
            SafeCursesUtils._safe_refresh(self.stdscr, "UIManager.too_small_final_refresh")
            return

        # --- Proceed with drawing individual windows only if UI is not too small ---
            try:
                self.scroll_messages("end") # Removed await
                logger.debug(f"Called scroll_messages('end') after resize.")
            except Exception as e_scroll_end:
                logger.error(f"Error calling scroll_messages('end') after resize: {e_scroll_end}", exc_info=True)

        # If UI is marked as too small (either from this resize or a previous one)
        if self.ui_is_too_small:
            SafeCursesUtils._safe_erase(self.stdscr, "UIManager.too_small_repeat_erase") # Ensure clean slate
            msg = "Terminal too small. Please resize."
            if self.height > 0 and self.width > 0:
                msg_y = self.height // 2
                msg_x = max(0, (self.width - len(msg)) // 2)
                if msg_x + len(msg) <= self.width: # Check if message can fit
                    error_attr = self.curses_manager.get_color("error") | curses.A_BOLD
                    SafeCursesUtils._safe_addstr(self.stdscr, msg_y, msg_x, msg, error_attr, "UIManager.too_small_repeat_addstr")
            SafeCursesUtils._safe_refresh(self.stdscr, "UIManager.too_small_final_refresh")
            return

        # --- Proceed with drawing individual windows only if UI is not too small ---
        active_ctx_name_snapshot = self.client.context_manager.active_context_name
        active_ctx_obj_snapshot = self.client.context_manager.get_context(active_ctx_name_snapshot) if active_ctx_name_snapshot else None

        try:
            SafeCursesUtils._safe_noutrefresh(self.stdscr, "UIManager.refresh_all_windows_noutrefresh_stdscr") # Prepare stdscr for batched update
            self.draw_messages(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_sidebar(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_status_bar(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_input_line()
            self.curses_manager.update_screen() # Perform batched update
        except curses.error as e_draw:
            logger.error(f"Curses error during main window drawing phase: {e_draw}", exc_info=True)
            # Attempt to display a generic UI draw error on stdscr
            SafeCursesUtils._safe_erase(self.stdscr, "UIManager.draw_error_erase")
            draw_error_msg = "UI Draw Error!"
            if self.height > 0 and self.width > 0 :
                err_y = self.height // 2
                err_x = max(0, (self.width - len(draw_error_msg)) // 2)
                if err_x + len(draw_error_msg) <= self.width:
                    SafeCursesUtils._safe_addstr(self.stdscr, err_y, err_x, draw_error_msg, self.curses_manager.get_color("error"), "UIManager.draw_error_addstr")
            SafeCursesUtils._safe_refresh(self.stdscr, "UIManager.draw_error_refresh")
            # No return here, let it fall through if displaying the error fails.
            # The UI might be stuck, but we've logged the core issue.
        except Exception as e_critical_draw:
            logger.critical(f"Unexpected critical error during refresh_all_windows draw phase: {e_critical_draw}", exc_info=True)
            SafeCursesUtils._safe_erase(self.stdscr, "UIManager.critical_error_erase")
            critical_error_msg = "Critical UI Error!"
            if self.height > 0 and self.width > 0:
                err_y = self.height // 2
                err_x = max(0, (self.width - len(critical_error_msg)) // 2)
                if err_x + len(critical_error_msg) <= self.width:
                    SafeCursesUtils._safe_addstr(self.stdscr, err_y, err_x, critical_error_msg, self.curses_manager.get_color("error"), "UIManager.critical_error_addstr")
            SafeCursesUtils._safe_refresh(self.stdscr, "UIManager.critical_error_refresh")
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
