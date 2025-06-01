# ui_manager.py
import curses
import time
import logging
from typing import Optional, TYPE_CHECKING, List, Tuple, Any, Deque, Dict
from context_manager import ChannelJoinStatus # Added import
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
        self.sidebar_width = 0
        self.msg_win_height = 0
        self.msg_win_width = 0

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
        self._init_color_pair( # Used for nick mentions and active window/unread in sidebar
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
                    0,0, "Terminal too small. Please resize.",
                    curses.A_BOLD | self.colors.get("error", curses.color_pair(0)),
                )
                self.stdscr.refresh()
            except curses.error: pass
            raise Exception("Terminal too small to initialize UI.")

        logger.debug(
            f"Setup layout: H={self.height}, W={self.width}, SidebarW={self.sidebar_width}, MsgH={self.msg_win_height}, MsgW={self.msg_win_width}"
        )

        try:
            self.msg_win = curses.newwin(self.msg_win_height, self.msg_win_width, 0, 0)
            self.msg_win.scrollok(True)
            self.msg_win.idlok(True)

            self.sidebar_win = curses.newwin(
                self.height - 1,
                self.sidebar_width, 0, self.msg_win_width,
            )
            self.status_win = curses.newwin(1, self.width, self.height - 2, 0)
            self.input_win = curses.newwin(1, self.width, self.height - 1, 0)
            self.input_win.keypad(True)
            self.input_win.nodelay(True)
        except curses.error as e:
            logger.critical(f"Curses error during window creation: {e}", exc_info=True)
            raise Exception(f"Failed to create curses windows: {e}")

    def _draw_window_border_and_bkgd(self, window, color_attr, title=""):
        if not window: return
        window.erase()
        window.bkgd(" ", color_attr)
        if title:
            try:
                _, win_w = window.getmaxyx()
                window.addstr(0, 1, title[: win_w - 2], curses.A_BOLD)
            except curses.error: pass

    def _calculate_available_lines_for_user_list(self) -> int:
        """
        Calculates the approximate number of lines available purely for listing user nicks
        in the sidebar, after accounting for headers and other elements.
        """
        if not self.sidebar_win:
            return 0
        try:
            max_y, _ = self.sidebar_win.getmaxyx()
        except curses.error: # If window not yet fully initialized or too small
            return 0

        if max_y <= 0:
            return 0

        lines_for_windows_header = 1
        try:
            # This might be called before client.context_manager is fully ready during init
            all_contexts_count = len(self.client.context_manager.get_all_context_names()) if self.client and self.client.context_manager else 0
        except Exception: # Catchall if context_manager or get_all_context_names is problematic early on
            all_contexts_count = 0

        lines_used_by_other_elements = (
            lines_for_windows_header +
            all_contexts_count +
            3  # For gap, hline, and user list header
        )

        available_for_nicks = max_y - lines_used_by_other_elements
        return max(0, available_for_nicks)

    def draw_messages(self, current_active_ctx_obj, current_active_ctx_name_str):
        if not self.msg_win: return
        self._draw_window_border_and_bkgd(self.msg_win, self.colors.get("default",0))
        max_y, max_x = self.msg_win.getmaxyx()
        if max_y <= 0 or max_x <= 0: return

        active_ctx_obj = current_active_ctx_obj

        if not active_ctx_obj:
            active_ctx_name = current_active_ctx_name_str
            try:
                self.msg_win.addstr(0,0, f"Error: Context '{active_ctx_name if active_ctx_name else "None"}' not found.", self.colors.get("error",0))
            except curses.error: pass
            self.msg_win.noutrefresh()
            return

        current_scroll_offset = active_ctx_obj.scrollback_offset
        end_idx = len(active_ctx_obj.messages) - current_scroll_offset
        start_idx = max(0, end_idx - max_y)
        lines_to_draw = list(active_ctx_obj.messages)[start_idx:end_idx]

        for i, (msg_text, color_attr_val) in enumerate(lines_to_draw):
            attr = color_attr_val
            try:
                self.msg_win.addstr(i, 0, msg_text[: max_x -1], attr)
            except curses.error:
                try: self.msg_win.addstr(i, 0, msg_text[: max_x - 2], attr)
                except: pass
        self.msg_win.noutrefresh()

    def _draw_sidebar_context_list(self, max_y: int, max_x: int, current_active_ctx_name_str: str) -> int:
        """Draws the list of contexts (windows) in the sidebar. Returns the next line_num."""
        if not self.sidebar_win:
            return 0
        line_num = 0
        try:
            self.sidebar_win.addstr(line_num, 0, "Windows:", self.colors.get("sidebar_header", 0))
            line_num += 1
        except curses.error: pass

        all_context_names_unsorted = self.client.context_manager.get_all_context_names()
        status_context_name = "Status"
        other_contexts = [name for name in all_context_names_unsorted if name != status_context_name]
        other_contexts.sort(key=lambda x: x.lower())
        all_contexts = other_contexts
        if status_context_name in all_context_names_unsorted:
            all_contexts.append(status_context_name)

        active_context_name_for_list_highlight = current_active_ctx_name_str

        for ctx_name in all_contexts:
            if line_num >= max_y -1 :
                break

            display_name_base = ctx_name[:max_x - 4]
            attr = self.colors.get("sidebar_item", 0)
            ctx_obj = self.client.context_manager.get_context(ctx_name)
            unread_count = self.client.context_manager.get_unread_count(ctx_name)
            prefix = " "
            status_suffix = ""

            if ctx_obj and ctx_obj.type == "channel" and hasattr(ctx_obj, 'join_status'):
                if ctx_obj.join_status == ChannelJoinStatus.PENDING_INITIAL_JOIN or \
                   ctx_obj.join_status == ChannelJoinStatus.JOIN_COMMAND_SENT:
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

            try:
                self.sidebar_win.addstr(line_num, 0, display_name_final[:max_x-1], attr)
                line_num += 1
            except curses.error: pass

        if line_num < max_y -1:
            try:
                line_num += 1
            except curses.error: pass
        return line_num

    def _draw_sidebar_user_list_header(self, line_num: int, max_y: int, max_x: int, active_ctx_obj_for_users, current_active_ctx_name_for_user_header: str) -> int:
        """Draws the user list header in the sidebar. Returns the next line_num."""
        if not self.sidebar_win or not active_ctx_obj_for_users:
            return line_num

        if line_num > 0 and line_num < max_y :
            try:
                self.sidebar_win.hline(line_num -1 , 0, curses.ACS_HLINE, max_x)
            except curses.error: pass

        channel_users_dict = active_ctx_obj_for_users.users
        user_count = len(channel_users_dict)
        user_header_full = f"Users in {current_active_ctx_name_for_user_header} ({user_count})"
        user_header_truncated = user_header_full[:max_x-1]

        if line_num < max_y:
            try:
                self.sidebar_win.addstr(
                    line_num, 0, user_header_truncated, self.colors.get("sidebar_header",0)
                )
                line_num += 1
            except curses.error as e:
                logger.debug(f"Curses error drawing sidebar user header '{user_header_truncated}': {e}")
        return line_num

    def _draw_sidebar_user_list_items_and_indicators(self, line_num: int, max_y: int, max_x: int, active_ctx_obj_for_users) -> int:
        """Draws the user list items and scroll indicators in the sidebar. Returns the next line_num."""
        if not self.sidebar_win or not active_ctx_obj_for_users or not hasattr(active_ctx_obj_for_users, 'users') or not active_ctx_obj_for_users.users:
            return line_num

        current_user_scroll_offset = active_ctx_obj_for_users.user_list_scroll_offset
        channel_users_dict = active_ctx_obj_for_users.users
        sorted_user_items = sorted(channel_users_dict.items(), key=lambda item: item[0].lower())
        total_users = len(sorted_user_items)

        available_lines_for_user_section = max_y - line_num
        lines_for_nicks = available_lines_for_user_section
        up_indicator_text = None
        down_indicator_text = None

        if current_user_scroll_offset > 0:
            if lines_for_nicks > 0:
                up_indicator_text = ("^ More"[:max_x-1])
                lines_for_nicks -= 1

        if current_user_scroll_offset + lines_for_nicks < total_users:
            if lines_for_nicks > 0:
                down_indicator_text = ("v More"[:max_x-1])
                lines_for_nicks -= 1

        lines_for_nicks = max(0, lines_for_nicks)

        if up_indicator_text and line_num < max_y:
            try:
                self.sidebar_win.addstr(line_num, 1, up_indicator_text, self.colors.get("sidebar_item", 0) | curses.A_DIM)
                line_num += 1
            except curses.error: pass

        start_idx = current_user_scroll_offset
        end_idx = current_user_scroll_offset + lines_for_nicks
        visible_users_page = sorted_user_items[start_idx:end_idx]

        for nick, prefix_str in visible_users_page:
            if line_num >= max_y:
                break
            display_user_with_prefix = f"{prefix_str}{nick}"
            user_display_truncated = (" " + display_user_with_prefix)[:max_x-1]
            user_color = self.colors.get("sidebar_item", 0)
            if prefix_str == "@": user_color = self.colors.get("user_prefix", user_color)

            try:
                self.sidebar_win.addstr(line_num, 0, user_display_truncated, user_color)
            except curses.error as e:
                logger.debug(f"Curses error drawing sidebar user '{user_display_truncated}': {e}")
            line_num += 1

        if down_indicator_text and line_num < max_y:
            try:
                self.sidebar_win.addstr(line_num, 1, down_indicator_text, self.colors.get("sidebar_item", 0) | curses.A_DIM)
                line_num += 1
            except curses.error: pass

        return line_num

    def draw_sidebar(self, current_active_ctx_obj, current_active_ctx_name_str):
        if not self.sidebar_win:
            return
        self._draw_window_border_and_bkgd(self.sidebar_win, self.colors.get("sidebar_item", 0))
        max_y, max_x = self.sidebar_win.getmaxyx()
        if max_y <= 0 or max_x <= 0: return

        line_num = self._draw_sidebar_context_list(max_y, max_x, current_active_ctx_name_str)

        active_ctx_obj_for_users = current_active_ctx_obj

        should_show_user_list = False
        if active_ctx_obj_for_users and active_ctx_obj_for_users.type == "channel" and hasattr(active_ctx_obj_for_users, 'join_status'):
            if active_ctx_obj_for_users.join_status in [ChannelJoinStatus.SELF_JOIN_RECEIVED, ChannelJoinStatus.FULLY_JOINED]:
                should_show_user_list = True

        if should_show_user_list:
            if line_num < max_y -1 :
                line_num = self._draw_sidebar_user_list_header(line_num, max_y, max_x, active_ctx_obj_for_users, current_active_ctx_name_str)
                if line_num < max_y: # Check if space remains after header
                    line_num = self._draw_sidebar_user_list_items_and_indicators(line_num, max_y, max_x, active_ctx_obj_for_users)

        self.sidebar_win.noutrefresh()

    def draw_status_bar(self, current_active_ctx_obj, current_active_ctx_name_str):
        if not self.status_win: return
        self._draw_window_border_and_bkgd(self.status_win, self.colors.get("status_bar",0))
        max_y, max_x = self.status_win.getmaxyx()
        if max_y <= 0 or max_x <= 0: return

        active_ctx_obj = current_active_ctx_obj
        active_ctx_name = current_active_ctx_name_str or "N/A"

        topic_display = ""
        if active_ctx_obj and active_ctx_obj.type == "channel" and active_ctx_obj.topic:
            topic_str = active_ctx_obj.topic
            max_topic_len = max_x // 3
            topic_display = f"Topic: {topic_str[:max_topic_len-7]}"
            if len(topic_str) > max_topic_len-7 : topic_display += "..."

        channel_join_status_info = ""
        if active_ctx_obj and active_ctx_obj.type == "channel" and hasattr(active_ctx_obj, 'join_status'):
            if active_ctx_obj.join_status not in [ChannelJoinStatus.FULLY_JOINED, ChannelJoinStatus.NOT_JOINED, None]: # Don't show for fully joined or not applicable
                channel_join_status_info = f" ({active_ctx_obj.join_status.name})"


        status_left = f" {self.client.nick}@{self.client.server}:{self.client.port} [{active_ctx_name}{channel_join_status_info}]"
        if self.client.use_ssl: status_left += " SSL"

        status_right = "CONNECTED" if self.client.network.connected else "DISCONNECTED"
        if not self.client.network.connected and not self.client.should_quit:
            if hasattr(self.client.network, 'reconnect_delay'):
                 status_right = f"RETRY({self.client.network.reconnect_delay}s)"

        full_status_text = status_left
        if topic_display:
            space_for_topic = max_x - (len(status_left) + len(status_right) + 3)
            if space_for_topic > 5:
                actual_topic_display = topic_display[:space_for_topic]
                full_status_text += f" | {actual_topic_display}"

        full_status_text_truncated = full_status_text[:max_x - len(status_right) -1]

        try:
            self.status_win.addstr(0, 0, full_status_text_truncated, self.colors.get("status_bar",0))
            if len(full_status_text_truncated) + len(status_right) < max_x :
                 self.status_win.addstr(0, max_x - len(status_right) -1, " " + status_right, self.colors.get("status_bar",0))
        except curses.error: pass
        self.status_win.noutrefresh()

    def draw_input_line(self):
        if not self.input_win: return
        self._draw_window_border_and_bkgd(self.input_win, self.colors.get("input",0))
        max_y, max_x = self.input_win.getmaxyx()
        if max_y <= 0 or max_x <= 0: return

        prompt = "> "
        available_width = max_x - len(prompt) -1
        current_input_buffer = self.client.input_handler.get_current_input_buffer()

        display_buffer = current_input_buffer
        if available_width <=0: display_buffer = ""
        elif len(current_input_buffer) > available_width:
            if available_width > 3: display_buffer = "..." + current_input_buffer[-(available_width - 3) :]
            else: display_buffer = current_input_buffer[-available_width:]

        cursor_pos_x = len(prompt) + len(display_buffer)
        try:
            self.input_win.addstr(0, 0, prompt + display_buffer, self.colors.get("input",0))
            self.input_win.move(0, min(cursor_pos_x, max_x -1))
        except curses.error: pass
        self.input_win.noutrefresh()

    def refresh_all_windows(self):
        new_height, new_width = self.stdscr.getmaxyx()
        if new_height != self.height or new_width != self.width:
            logger.info(f"Terminal resized from {self.width}x{self.height} to {new_width}x{new_height}.")
            self.height, self.width = new_height, new_width
            try:
                curses.resizeterm(self.height, self.width)
                self.stdscr.clear()
                self.stdscr.refresh()
                self.setup_layout()
            except Exception as e:
                logger.error(f"Error during resize handling: {e}", exc_info=True)
                if "Terminal too small" in str(e): return
                try:
                    self.stdscr.erase()
                    self.stdscr.addstr(0,0, "Resize Error!", self.colors.get("error",0))
                    self.stdscr.refresh()
                except: pass
                return

        active_ctx_name_snapshot = self.client.context_manager.active_context_name
        active_ctx_obj_snapshot = self.client.context_manager.get_context(active_ctx_name_snapshot) if active_ctx_name_snapshot else None

        self.stdscr.noutrefresh()
        try:
            self.draw_messages(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_sidebar(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_status_bar(active_ctx_obj_snapshot, active_ctx_name_snapshot)
            self.draw_input_line()
        except curses.error as e:
            logger.error(f"Curses error during window drawing: {e}.")
            try:
                self.stdscr.erase()
                self.stdscr.addstr(0,0, "UI Draw Error!", self.colors.get("error",0))
                self.stdscr.refresh()
            except: pass
            return
        except Exception as e:
            logger.critical(f"Unexpected error during refresh_all_windows draw phase: {e}", exc_info=True)
            try:
                self.stdscr.erase()
                self.stdscr.addstr(0,0, "Critical UI Error!", self.colors.get("error",0))
                self.stdscr.refresh()
            except: pass
            return
        curses.doupdate()

    def get_input_char(self):
        if not self.input_win: return curses.ERR
        try:
            return self.input_win.getch()
        except curses.error:
            return curses.ERR

    def scroll_messages(self, direction):
        if not self.msg_win: return
        active_ctx_obj = self.client.context_manager.get_active_context()
        if not active_ctx_obj: return

        viewable_lines = self.msg_win_height if self.msg_win_height > 0 else 1
        history_len = len(active_ctx_obj.messages)
        current_offset = active_ctx_obj.scrollback_offset
        new_offset = current_offset
        max_scroll_offset = max(0, history_len - viewable_lines)

        if direction == "up":
            new_offset = min(max_scroll_offset, current_offset + viewable_lines // 2)
        elif direction == "down":
            new_offset = max(0, current_offset - viewable_lines // 2)
        elif direction == "home":
            new_offset = max_scroll_offset
        elif direction == "end":
            new_offset = 0

        new_offset = max(0, min(new_offset, max_scroll_offset))
        if new_offset != current_offset:
            active_ctx_obj.scrollback_offset = new_offset
            self.client.ui_needs_update.set()

    def scroll_user_list(self, direction: str, lines_arg: Optional[int] = None):
        """Scrolls the user list in the sidebar for the active channel context."""
        if not self.sidebar_win: return # Or if not visible

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
        if viewable_nick_lines <= 0: # No space to display users
            logger.debug("User list scroll: No viewable lines for nicks.")
            return

        total_users = len(active_ctx.users)
        current_offset = active_ctx.user_list_scroll_offset

        # Max offset is total users minus the number that can fit on one page
        max_scroll_offset = max(0, total_users - viewable_nick_lines)
        new_offset = current_offset
        scroll_amount = 0

        if direction == "up":
            scroll_amount = lines_arg if lines_arg is not None else max(1, viewable_nick_lines // 2)
            new_offset = max(0, current_offset - scroll_amount)
        elif direction == "down":
            scroll_amount = lines_arg if lines_arg is not None else max(1, viewable_nick_lines // 2)
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
            logger.debug(f"User list scrolled to offset {new_offset} for context {active_ctx.name}")
            self.client.ui_needs_update.set()
        else:
            logger.debug(f"User list scroll: no change in offset ({current_offset}) for {active_ctx.name}")
