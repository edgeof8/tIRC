# ui_manager.py
import curses
import time
import logging  # Added for logging
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

logger = logging.getLogger("pyrc.ui")  # Child logger


class UIManager:
    def __init__(self, stdscr, client_ref):
        logger.debug("UIManager initializing.")
        self.stdscr = stdscr
        self.client = client_ref  # Reference to the main IRCClient_Logic instance
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
        self.current_line_in_history = 0  # For scrollback in message window

        self.colors = {}  # To store color pairs for easy access by name

        self._setup_curses_settings()
        self.setup_layout()  # Initial layout setup

    def _setup_curses_settings(self):
        curses.curs_set(1)
        curses.start_color()
        curses.use_default_colors()

        # Define color pairs and store them
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
        self._init_color_pair(
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
            "sidebar_user", COLOR_ID_SIDEBAR_USER, curses.COLOR_CYAN, -1
        )
        self._init_color_pair("input", COLOR_ID_INPUT, curses.COLOR_WHITE, -1)
        self._init_color_pair("pm", COLOR_ID_PM, curses.COLOR_MAGENTA, -1)

    def _init_color_pair(self, name, pair_id, fg, bg):
        curses.init_pair(pair_id, fg, bg)
        self.colors[name] = curses.color_pair(pair_id)

    def setup_layout(self):
        self.height, self.width = self.stdscr.getmaxyx()

        self.sidebar_width = max(15, min(30, int(self.width * 0.2)))
        self.msg_win_height = self.height - 2  # 1 for status, 1 for input
        self.msg_win_width = self.width - self.sidebar_width

        if (
            self.msg_win_height <= 0
            or self.msg_win_width <= 0
            or self.sidebar_width <= 0
        ):
            # Terminal too small, can't create windows.
            logger.error(
                f"Terminal too small for UI layout: H={self.height}, W={self.width}. Required H>2, W>{self.sidebar_width}."
            )
            # This should ideally be handled more gracefully, e.g., by showing an error.
            # For now, we'll let curses error out if it tries to create a 0-size window.
            # Or, prevent window creation.
            # Ensure add_message is called with context_name if client is already context-aware
            # For now, this early message might go to a default if client.add_message expects it
            try:
                self.stdscr.erase()
                self.stdscr.addstr(
                    0,
                    0,
                    "Terminal too small. Please resize.",
                    curses.A_BOLD | curses.color_pair(COLOR_ID_ERROR),
                )
                self.stdscr.refresh()
            except curses.error:
                pass  # If even this fails, not much we can do.
            # self.client.add_message( # This might fail if client/UI isn't fully up
            #     "Terminal too small!",
            #     self.colors.get("error", curses.color_pair(0)),
            #     context_name="Status",
            # )
            # We should probably raise an exception or signal client to stop if UI can't init
            raise Exception(
                "Terminal too small to initialize UI."
            )  # Or a custom exception

        logger.debug(
            f"Setup layout: H={self.height}, W={self.width}, SidebarW={self.sidebar_width}, MsgH={self.msg_win_height}, MsgW={self.msg_win_width}"
        )

        try:
            self.msg_win = curses.newwin(self.msg_win_height, self.msg_win_width, 0, 0)
            self.msg_win.scrollok(True)
            self.msg_win.idlok(True)
            logger.debug("Message window created.")

            self.sidebar_win = curses.newwin(
                self.height - 1,
                self.sidebar_width,
                0,
                self.msg_win_width,  # Sidebar takes full height - status bar
            )
            logger.debug("Sidebar window created.")

            self.status_win = curses.newwin(1, self.width, self.height - 2, 0)
            logger.debug("Status window created.")

            self.input_win = curses.newwin(1, self.width, self.height - 1, 0)
            self.input_win.keypad(True)
            self.input_win.nodelay(True)  # Non-blocking input
            logger.debug("Input window created.")
        except curses.error as e:
            logger.critical(f"Curses error during window creation: {e}", exc_info=True)
            # This is a critical failure for the UI.
            # Propagate this so the application can handle it (e.g., exit).
            raise Exception(f"Failed to create curses windows: {e}")

    def _draw_window_border_and_bkgd(self, window, color_attr, title=""):
        if not window:
            return
        window.erase()
        window.bkgd(" ", color_attr)
        # window.border() # Optional: draw borders around windows
        if title:
            try:
                window.addstr(
                    0, 1, title[: self.width - 2], curses.A_BOLD
                )  # Example title
            except curses.error as e:
                logger.debug(f"Curses error drawing window title '{title}': {e}")
                pass

    def draw_messages(self):
        if not self.msg_win:
            logger.debug("draw_messages called but msg_win is None.")
            return
        self._draw_window_border_and_bkgd(self.msg_win, self.colors["default"])

        max_y, max_x = self.msg_win.getmaxyx()
        if max_y <= 0 or max_x <= 0:
            logger.debug(
                f"msg_win not usable for drawing messages: max_y={max_y}, max_x={max_x}"
            )
            return  # Window not usable

        active_ctx_name = self.client.active_context_name
        if not active_ctx_name or active_ctx_name not in self.client.contexts:
            logger.warning(
                f"draw_messages called with invalid active_context_name: {active_ctx_name}"
            )
            try:
                self.msg_win.addstr(
                    0,
                    0,
                    f"Error: Context '{active_ctx_name}' not found.",
                    self.colors.get("error", 0),  # curses.color_pair(0) is default
                )
            except curses.error as e:
                logger.debug(f"Curses error adding 'context not found' message: {e}")
                pass
            self.msg_win.noutrefresh()
            return

        active_context_messages = self.client.contexts[active_ctx_name]["messages"]

        # When switching contexts, self.current_line_in_history should be reset or loaded.
        # For now, it's a global scroll for the active window.
        # Let's also consider if the client wants to store scroll position per context.
        # client.contexts[active_ctx_name]["last_read_line_count"] could be used.
        # For simplicity now, current_line_in_history is UIManager's view of active context scroll.

        end_idx = len(active_context_messages) - self.current_line_in_history
        start_idx = max(0, end_idx - max_y)
        lines_to_draw = list(active_context_messages)[start_idx:end_idx]

        for i, (msg_text, color_id_or_attr) in enumerate(lines_to_draw):
            # If color_id_or_attr is an int, assume it's a color pair ID (old way)
            # If it's already an attribute (e.g., from self.colors), use directly
            attr = (
                color_id_or_attr
                if isinstance(color_id_or_attr, int) and color_id_or_attr > 255
                else (
                    curses.color_pair(color_id_or_attr)
                    if isinstance(color_id_or_attr, int)
                    else color_id_or_attr
                )
            )  # Assumes it's already a curses attribute

            try:
                self.msg_win.addstr(i, 0, msg_text[: max_x - 1], attr)
            except curses.error as e:
                # This can happen if a line is exactly max_x and addstr tries to move cursor past window edge
                logger.debug(
                    f"Curses error drawing message line (idx {i}): '{msg_text[:20]}...': {e}"
                )
                try:  # Try to draw truncated version if it failed
                    self.msg_win.addstr(
                        i, 0, msg_text[: max_x - 2], attr
                    )  # Truncate more
                except:
                    pass  # Give up on this line
        self.msg_win.noutrefresh()

    def draw_sidebar(self):
        if not self.sidebar_win:
            logger.debug("draw_sidebar called but sidebar_win is None.")
            return
        self._draw_window_border_and_bkgd(self.sidebar_win, self.colors["sidebar_user"])
        max_y, max_x = self.sidebar_win.getmaxyx()
        if max_y <= 0 or max_x <= 0:
            logger.debug(
                f"sidebar_win not usable for drawing: max_y={max_y}, max_x={max_x}"
            )
            return

        # --- Redraw Sidebar to show Contexts (Windows) and Users for active channel ---
        sidebar_header_color = (
            self.colors.get("sidebar_header", curses.A_NORMAL) | curses.A_BOLD
        )
        default_user_color = self.colors.get("sidebar_user", curses.A_NORMAL)
        highlight_color = self.colors.get(
            "highlight", curses.A_REVERSE
        )  # For active window or unread

        # 1. Draw Contexts List
        contexts_header = "Windows"
        try:
            self.sidebar_win.addstr(
                0, 0, contexts_header[: max_x - 1], sidebar_header_color
            )
            self.sidebar_win.hline(1, 0, curses.ACS_HLINE, max_x)
        except curses.error as e:
            logger.debug(f"Curses error drawing sidebar header/hline: {e}")
            pass

        line_num = 2
        # Ensure a consistent order for contexts, e.g., "Status" first, then sorted.
        context_names_ordered = ["Status"] + sorted(
            [name for name in self.client.contexts.keys() if name != "Status"]
        )

        for i, ctx_name in enumerate(context_names_ordered):
            if line_num >= max_y - 1:  # Leave space for user list header if needed
                break
            if ctx_name not in self.client.contexts:
                continue  # Should not happen

            ctx_data = self.client.contexts[ctx_name]
            display_name = ctx_name[: max_x - 2]  # Truncate if too long

            attr = default_user_color
            prefix = "  "
            if ctx_name == self.client.active_context_name:
                attr = highlight_color  # Highlight active window
                prefix = "* "
            elif ctx_data.get("unread_count", 0) > 0:
                attr = self.colors.get(
                    "highlight", curses.A_BOLD
                )  # Or a different color for unread
                display_name += f" ({ctx_data['unread_count']})"
                display_name = display_name[: max_x - 2]

            try:
                self.sidebar_win.addstr(line_num, 0, prefix + display_name, attr)
            except curses.error as e:
                logger.debug(
                    f"Curses error drawing sidebar context '{display_name}': {e}"
                )
                pass
            line_num += 1

        # 2. Draw User List for Active Channel (if it's a channel)
        active_ctx_name = self.client.active_context_name
        active_ctx_data = self.client.contexts.get(active_ctx_name)

        if active_ctx_data and active_ctx_data["type"] == "channel":
            if (
                line_num < max_y - 2
            ):  # Check if space for user header and at least one user
                line_num += 1  # Blank line separator
                user_header = (
                    f"Users in {active_ctx_name} ({len(active_ctx_data['users'])})"
                )
                try:
                    self.sidebar_win.hline(line_num, 0, curses.ACS_HLINE, max_x)
                    line_num += 1
                    self.sidebar_win.addstr(
                        line_num, 0, user_header[: max_x - 1], sidebar_header_color
                    )
                    line_num += 1
                except curses.error as e:
                    logger.debug(
                        f"Curses error drawing sidebar user header '{user_header}': {e}"
                    )
                    pass

                sorted_users = sorted(list(active_ctx_data["users"]), key=str.lower)
                for user in sorted_users:
                    if line_num >= max_y:
                        break
                    try:
                        self.sidebar_win.addstr(
                            line_num, 1, user[: max_x - 2], default_user_color
                        )
                    except curses.error as e:
                        logger.debug(f"Curses error drawing sidebar user '{user}': {e}")
                        pass
                    line_num += 1

        self.sidebar_win.noutrefresh()

    def draw_status_bar(self):
        if not self.status_win:
            logger.debug("draw_status_bar called but status_win is None.")
            return
        self._draw_window_border_and_bkgd(self.status_win, self.colors["status_bar"])
        max_y, max_x = self.status_win.getmaxyx()
        if max_y <= 0 or max_x <= 0:
            logger.debug(
                f"status_win not usable for drawing: max_y={max_y}, max_x={max_x}"
            )
            return

        active_ctx_name = self.client.active_context_name
        active_ctx_data = self.client.contexts.get(active_ctx_name)

        topic_display = ""
        if (
            active_ctx_data
            and active_ctx_data["type"] == "channel"
            and active_ctx_data["topic"]
        ):
            topic_display = (
                f"Topic: {active_ctx_data['topic'][:30]}..."
                if len(active_ctx_data["topic"]) > 33
                else f"Topic: {active_ctx_data['topic']}"
            )

        # Basic status: Nick@Server [ActiveContextName] SSL Topic...
        status_text = f" {self.client.nick}@{self.client.server}:{self.client.port} "
        status_text += f"[{active_ctx_name}] "
        if self.client.use_ssl:
            status_text += "SSL "
        if topic_display:
            status_text += f"{topic_display} "

        conn_status = "CONNECTED" if self.client.network.connected else "DISCONNECTED"
        if not self.client.network.connected and not self.client.should_quit:
            conn_status = f"RECONNECTING ({self.client.network.reconnect_delay}s)"

        status_len = len(status_text)
        conn_len = len(conn_status)

        try:
            self.status_win.addstr(0, 0, status_text, self.colors["status_bar"])
            if status_len + conn_len < max_x:
                self.status_win.addstr(
                    0,
                    max_x - conn_len - 1,
                    conn_status + " ",
                    self.colors["status_bar"],
                )
        except curses.error as e:
            logger.debug(f"Curses error drawing status bar text: {e}")
            pass
        self.status_win.noutrefresh()

    def draw_input_line(self):
        if not self.input_win:
            logger.debug("draw_input_line called but input_win is None.")
            return
        self._draw_window_border_and_bkgd(self.input_win, self.colors["input"])
        max_y, max_x = self.input_win.getmaxyx()
        if max_y <= 0 or max_x <= 0:
            logger.debug(
                f"input_win not usable for drawing: max_y={max_y}, max_x={max_x}"
            )
            return

        prompt = "> "
        available_width = max_x - len(prompt) - 1

        display_buffer = self.client.input_buffer
        if len(self.client.input_buffer) > available_width:
            display_buffer = "..." + self.client.input_buffer[-(available_width - 3) :]

        try:
            self.input_win.addstr(0, 0, prompt + display_buffer, self.colors["input"])
            self.input_win.move(0, len(prompt) + len(display_buffer))
        except curses.error as e:
            logger.debug(f"Curses error drawing input line/moving cursor: {e}")
            pass
        self.input_win.noutrefresh()

    def refresh_all_windows(self):
        new_height, new_width = self.stdscr.getmaxyx()
        if new_height != self.height or new_width != self.width:
            logger.info(
                f"Terminal resized from {self.width}x{self.height} to {new_width}x{new_height}."
            )
            self.height, self.width = new_height, new_width
            try:
                curses.resizeterm(self.height, self.width)
                self.stdscr.clear()  # Clear main screen before redrawing borders/layout
                self.stdscr.refresh()
                self.setup_layout()  # Recreate windows with new sizes
                logger.debug("Layout re-initialized after resize.")
            except (
                Exception
            ) as e:  # Catch potential errors from setup_layout (e.g. terminal too small again)
                logger.error(f"Error during resize handling: {e}", exc_info=True)
                # If setup_layout fails (e.g. terminal too small), it might raise an exception.
                # We should probably stop the client or show a persistent error.
                # For now, we'll try to continue, but UI might be broken.
                # A more robust solution would be to have setup_layout return a status
                # or for the client to handle this exception from main_curses_wrapper.
                if "Terminal too small" in str(
                    e
                ):  # Check if it's our specific exception
                    # Don't try to draw further if terminal is too small.
                    # The exception from setup_layout should ideally be caught by the main wrapper.
                    return  # Avoid further drawing attempts if layout failed

        self.stdscr.noutrefresh()
        try:
            self.draw_messages()
            self.draw_sidebar()
            self.draw_status_bar()
            self.draw_input_line()
        except curses.error as e:
            # This can happen if windows are not valid (e.g., after a resize to too small)
            logger.error(
                f"Curses error during window drawing: {e}. This might happen if terminal is too small."
            )
            # Attempt to show a minimal error on stdscr if possible
            try:
                self.stdscr.erase()
                self.stdscr.addstr(
                    0, 0, "UI Error. Resize terminal?", self.colors.get("error", 0)
                )
                self.stdscr.refresh()  # Use refresh directly for immediate effect
                return  # Don't doupdate if drawing failed
            except:
                pass  # If even this fails, not much to do.
        except Exception as e:
            logger.critical(
                f"Unexpected error during refresh_all_windows draw phase: {e}",
                exc_info=True,
            )
            # Similar to above, try to show an error.
            try:
                self.stdscr.erase()
                self.stdscr.addstr(
                    0, 0, "Critical UI Error!", self.colors.get("error", 0)
                )
                self.stdscr.refresh()
                return
            except:
                pass

        curses.doupdate()

    def get_input_char(self):
        if not self.input_win:
            logger.warning("get_input_char called but input_win is None.")
            return curses.ERR
        return self.input_win.getch()

    def scroll_messages(self, direction):
        """direction: 'up', 'down', 'home', 'end'"""
        logger.debug(f"Scrolling messages: {direction}")
        if not self.msg_win:
            logger.warning("scroll_messages called but msg_win is None.")
            return

        active_ctx_name = self.client.active_context_name
        if not active_ctx_name or active_ctx_name not in self.client.contexts:
            return

        active_context_messages = self.client.contexts[active_ctx_name]["messages"]
        viewable_lines = self.msg_win_height  # Number of lines visible in msg_win
        history_len = len(active_context_messages)

        # self.current_line_in_history is the number of lines scrolled up from the bottom.
        # 0 means showing the latest messages.
        # Positive value means scrolled up.

        if direction == "up":  # Page Up (scroll older messages into view)
            self.current_line_in_history = min(
                (
                    history_len - viewable_lines + 1
                    if history_len >= viewable_lines
                    else 0
                ),
                self.current_line_in_history + viewable_lines // 2,
            )
        elif direction == "down":  # Page Down
            self.current_line_in_history = max(
                0, self.current_line_in_history - viewable_lines // 2
            )
        elif direction == "home":
            self.current_line_in_history = (
                history_len - viewable_lines + 1 if history_len >= viewable_lines else 0
            )
        elif direction == "end":
            self.current_line_in_history = 0

        self.current_line_in_history = max(
            0, self.current_line_in_history
        )  # Ensure not negative
        if (
            history_len < viewable_lines
        ):  # If history shorter than window, always show from top
            self.current_line_in_history = 0
