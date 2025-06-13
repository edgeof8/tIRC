import curses
import logging
from typing import Any, Dict, List, Optional
from tirc_core.client.curses_utils import SafeCursesUtils
from tirc_core.context_manager import ChannelJoinStatus, ContextManager

logger = logging.getLogger("tirc.sidebar_panel_renderer")

MIN_SIDEBAR_USER_LIST_WIDTH = (
    8  # Minimum practical width to attempt drawing user list items
)

class SidebarPanelRenderer:
    def __init__(self, colors: Dict[str, int], context_manager_ref: ContextManager):
        self.colors = colors
        self.context_manager = context_manager_ref

    def draw(self, window: Any, active_context_obj: Any, all_contexts_data: List[str]):
        """Draws the sidebar content, including context list and user list."""
        if not window:
            return

        SafeCursesUtils._safe_erase(window, "SidebarPanelRenderer.draw_erase")
        # The background is set once when the window is created by WindowLayoutManager.

        max_y, max_x = window.getmaxyx()
        if max_y <= 0 or max_x <= 0:
            return

        line_num = self._draw_sidebar_context_list(
            window, max_y, max_x, active_context_obj.name if active_context_obj else "", all_contexts_data
        )

        if active_context_obj and active_context_obj.type == "channel": # Only draw user list for channels
            # The background is set once when the window is created by WindowLayoutManager.

            if line_num > 0 and line_num < max_y:
                SafeCursesUtils._safe_hline(
                    window,
                    line_num,
                    0,
                    curses.ACS_HLINE,
                    max_x,
                    self.colors.get("list_panel_bg", 0), # Use general list panel background for hline
                    "_draw_sidebar_user_list_hline",
                )
                line_num += 1

            if line_num < max_y:
                line_num = self._draw_sidebar_user_list_header(
                    window,
                    line_num,
                    max_y,
                    max_x,
                    active_context_obj,
                    active_context_obj.name if active_context_obj else "",
                )
            if line_num < max_y:
                self._draw_sidebar_user_list_items_and_indicators(
                    window, line_num, max_y, max_x, active_context_obj
                )

        if window:
            SafeCursesUtils._safe_noutrefresh(window, "SidebarPanelRenderer.draw_noutrefresh")

    def _draw_sidebar_context_list(
        self, window: Any, max_y: int, max_x: int, current_active_ctx_name_str: str, all_contexts_names: List[str]
    ) -> int:
        """Draws the list of contexts (windows) in the sidebar. Returns the next line_num."""
        line_num = 0
        SafeCursesUtils._draw_full_width_banner(
            window,
            line_num,
            "Windows:",
            self.colors.get("list_panel_bg", 0), # Use list_panel_bg for the header background
            "_draw_sidebar_context_list_header",
        )
        line_num += 1

        # Sort contexts: Status last, others alphabetically
        status_context_name = "Status"
        dcc_context_name = "DCC"

        regular_contexts = [
            name for name in all_contexts_names if name not in [status_context_name, dcc_context_name]
        ]
        regular_contexts.sort(key=lambda x: x.lower())

        sorted_display_contexts = []
        if status_context_name in all_contexts_names:
            sorted_display_contexts.append(status_context_name)
        sorted_display_contexts.extend(regular_contexts)
        if dcc_context_name in all_contexts_names and dcc_context_name not in sorted_display_contexts:
            sorted_display_contexts.append(dcc_context_name)


        for ctx_name in sorted_display_contexts:
            if line_num >= max_y -1:
                break

            display_name_base = ctx_name[: max_x - 4]
            # Default attribute is the standard item color
            attr = curses.color_pair(self.colors.get("sidebar_item", 0))

            ctx_obj = self.context_manager.get_context(ctx_name)
            unread_count = self.context_manager.get_unread_count(ctx_name) if ctx_obj else 0

            prefix = " "
            status_suffix = ""

            if ctx_obj and ctx_obj.type == "channel" and hasattr(ctx_obj, 'join_status') and ctx_obj.join_status:
                join_status = ctx_obj.join_status
                if join_status in [ChannelJoinStatus.PENDING_INITIAL_JOIN, ChannelJoinStatus.JOIN_COMMAND_SENT, ChannelJoinStatus.SELF_JOIN_RECEIVED]:
                    status_suffix = " (joining...)" if join_status != ChannelJoinStatus.SELF_JOIN_RECEIVED else " (users...)"
                    attr = curses.color_pair(self.colors.get("sidebar_item", 0)) | curses.A_DIM
                elif join_status == ChannelJoinStatus.JOIN_FAILED:
                    status_suffix = " (failed!)"
                    attr = curses.color_pair(self.colors.get("error", 0))

            # Apply specific highlights, overriding previous attributes
            if ctx_name == current_active_ctx_name_str:
                attr = curses.color_pair(self.colors.get("sidebar_active", 0))
                prefix = ">"
            elif unread_count > 0:
                attr = curses.color_pair(self.colors.get("sidebar_unread", 0)) | curses.A_BOLD
                prefix = "*"

            # Draw prefix
            current_x = 0
            SafeCursesUtils._safe_addstr(window, line_num, current_x, prefix, attr, "_draw_sidebar_context_list_prefix")
            current_x += len(prefix)

            # Get the background color of the current line's attribute
            # This is crucial to ensure consistent background when applying specific foregrounds
            attr_id = self.colors.get("sidebar_item", 0) # Default to sidebar_item
            if ctx_name == current_active_ctx_name_str:
                attr_id = self.colors.get("sidebar_active", 0)
            elif unread_count > 0:
                attr_id = self.colors.get("sidebar_unread", 0)
            elif ctx_obj and ctx_obj.type == "channel" and hasattr(ctx_obj, 'join_status') and ctx_obj.join_status == ChannelJoinStatus.JOIN_FAILED:
                attr_id = self.colors.get("error", 0)

            # Get the actual foreground and background colors from the determined attribute ID
            # This is a workaround as curses.color_pair(id) returns an attribute, not just the ID
            # We need the actual background color to combine with new foregrounds
            try:
                _, current_bg_color = curses.pair_content(attr_id)
            except curses.error:
                current_bg_color = curses.COLOR_BLACK # Fallback if pair_content fails

            # Draw context name (channel name might have specific color)
            ctx_name_to_draw = display_name_base
            if ctx_obj and ctx_obj.type == "channel" and ctx_name_to_draw.startswith("#"):
                # Get the foreground color of the 'channel' color pair
                channel_hash_fg = curses.color_content(self.colors.get("channel", 0))[0]

                # Get the background color of the current line's attribute (attr)
                # attr is already curses.color_pair(some_id)
                # We need to extract the background color from 'attr'
                current_attr_pair_id = (attr >> 8) & 0xFF # Extract pair ID from attribute
                try:
                    _, current_bg_color_id = curses.pair_content(current_attr_pair_id)
                except curses.error:
                    current_bg_color_id = curses.COLOR_BLACK # Fallback if pair_content fails

                # Create a new temporary color pair for the '#'
                temp_pair_id = 200 # Use a high ID for temporary pair
                try:
                    curses.init_pair(temp_pair_id, channel_hash_fg, current_bg_color_id)
                    channel_hash_attr = curses.color_pair(temp_pair_id)
                except curses.error as e:
                    logger.error(f"Error initializing temporary color pair {temp_pair_id} for channel hash: {e}. Falling back to main attr.", exc_info=True)
                    channel_hash_attr = attr # Fallback to the main line attribute

                SafeCursesUtils._safe_addstr(window, line_num, current_x, "#", channel_hash_attr, "_draw_sidebar_context_list_channel_hash")
                current_x += 1
                # Draw rest of channel name with the line's main attribute
                SafeCursesUtils._safe_addstr(window, line_num, current_x, ctx_name_to_draw[1:], attr, "_draw_sidebar_context_list_channel_name")
                current_x += len(ctx_name_to_draw) - 1
            else:
                # Draw regular context name
                SafeCursesUtils._safe_addstr(window, line_num, current_x, ctx_name_to_draw, attr, "_draw_sidebar_context_list_name")
                current_x += len(ctx_name_to_draw)

            # Draw status suffix
            if status_suffix:
                SafeCursesUtils._safe_addstr(window, line_num, current_x, status_suffix, attr, "_draw_sidebar_context_list_suffix")
                current_x += len(status_suffix)

            # Draw unread count
            if unread_count > 0 and ctx_name != current_active_ctx_name_str:
                unread_text = f" ({unread_count})"
                SafeCursesUtils._safe_addstr(window, line_num, current_x, unread_text, attr, "_draw_sidebar_context_list_unread")
                current_x += len(unread_text)

            # Fill remaining space with background color
            remaining_width = max_x - current_x
            if remaining_width > 0:
                SafeCursesUtils._safe_addstr(window, line_num, current_x, " " * remaining_width, attr, "_draw_sidebar_context_list_fill")

            line_num += 1

        if line_num < max_y -1:
            line_num += 1
        return line_num


    def _draw_sidebar_user_list_header(
        self,
        window: Any,
        line_num: int,
        max_y: int,
        max_x: int,
        active_ctx_obj_for_users: Any,
        current_active_ctx_name_for_user_header: str,
    ) -> int:
        """Draws the user list header in the sidebar. Returns the next line_num."""
        if not active_ctx_obj_for_users or not hasattr(active_ctx_obj_for_users, 'users'):
            return line_num

        if line_num >= max_y:
            return line_num

        user_count = len(active_ctx_obj_for_users.users)
        user_header_full = (
            f"Users in {current_active_ctx_name_for_user_header} ({user_count})"
        )

        SafeCursesUtils._draw_full_width_banner(
            window,
            line_num,
            user_header_full,
            self.colors.get("list_panel_bg", 0), # Corrected color key
            "_draw_sidebar_user_list_header_text",
        )
        line_num += 1
        return line_num

    def _draw_sidebar_user_list_items_and_indicators(
        self, window: Any, line_num: int, max_y: int, max_x: int, active_ctx_obj_for_users: Any
    ) -> int:
        """Draws the user list items and scroll indicators in the sidebar. Returns the next line_num."""
        if (
            not active_ctx_obj_for_users
            or not hasattr(active_ctx_obj_for_users, "users")
            or not active_ctx_obj_for_users.users
        ):
            return line_num

        current_user_scroll_offset = active_ctx_obj_for_users.user_list_scroll_offset if hasattr(active_ctx_obj_for_users, 'user_list_scroll_offset') else 0
        channel_users_dict = active_ctx_obj_for_users.users

        if max_x < MIN_SIDEBAR_USER_LIST_WIDTH:
            if line_num < max_y:
                SafeCursesUtils._safe_addstr(
                    window,
                    line_num,
                    0,
                    "[Users Hidden]".ljust(max_x),
                    self.colors.get("user_list_panel_bg", 0) | curses.A_DIM,
                    "_draw_sidebar_user_list_too_narrow",
                )
                line_num += 1
            return line_num

        sorted_user_items = sorted(
            channel_users_dict.items(), key=lambda item: item[0].lower()
        )
        total_users = len(sorted_user_items)

        # Calculate available lines for nicks, considering potential indicators
        available_lines_for_user_section = max_y - line_num
        lines_for_nicks = available_lines_for_user_section
        up_indicator_text: Optional[str] = None
        down_indicator_text: Optional[str] = None

        if current_user_scroll_offset > 0:
            if lines_for_nicks > 0:
                up_indicator_text = "^ More"[: max_x -1]
                lines_for_nicks -= 1

        # Check if there are more users below the current view
        if current_user_scroll_offset + lines_for_nicks < total_users:
            if lines_for_nicks > 0:
                down_indicator_text = "v More"[: max_x -1]
                lines_for_nicks -= 1

        lines_for_nicks = max(0, lines_for_nicks)

        if up_indicator_text and line_num < max_y:
            SafeCursesUtils._safe_addstr(
                window,
                line_num,
                0,
                (" " + up_indicator_text).ljust(max_x),
                self.colors.get("list_panel_bg", 0) | curses.A_DIM, # Corrected color key
                "_draw_sidebar_user_list_up_indicator",
            )
            line_num += 1

        start_idx = current_user_scroll_offset
        end_idx = current_user_scroll_offset + lines_for_nicks
        visible_users_page = sorted_user_items[start_idx:end_idx]

        for nick, prefix_str in visible_users_page:
            if line_num >= max_y:
                break

            current_x = 0
            current_x = 0
            # Draw leading space (using the list panel background color)
            list_panel_bg_attr = self.colors.get("list_panel_bg", 0)
            SafeCursesUtils._safe_addstr(window, line_num, current_x, " ", list_panel_bg_attr, "_draw_sidebar_user_list_leading_space")
            current_x += 1

            # Determine the color for the nick based on prefix (mode)
            nick_color_attr = self.colors.get("nick", 0) # Default nick color
            prefix_color_attr = self.colors.get("mode", 0) # Default mode color

            # Draw prefix (e.g., @, +)
            if prefix_str:
                SafeCursesUtils._safe_addstr(window, line_num, current_x, prefix_str, prefix_color_attr, "_draw_sidebar_user_list_prefix")
                current_x += len(prefix_str)

            # Draw nick
            SafeCursesUtils._safe_addstr(window, line_num, current_x, nick, nick_color_attr, "_draw_sidebar_user_list_nick")
            current_x += len(nick)
            # Fill remaining space with the list panel background color
            remaining_width = max_x - current_x
            if remaining_width > 0:
                SafeCursesUtils._safe_addstr(window, line_num, current_x, " " * remaining_width, list_panel_bg_attr, "_draw_sidebar_user_list_fill")

            line_num += 1

        if down_indicator_text and line_num < max_y:
            SafeCursesUtils._safe_addstr(
                window,
                line_num,
                0,
                (" " + down_indicator_text).ljust(max_x),
                self.colors.get("list_panel_bg", 0) | curses.A_DIM, # Corrected color key
                "_draw_sidebar_user_list_down_indicator",
            )
            line_num += 1

        return line_num
