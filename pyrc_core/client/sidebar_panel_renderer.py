import curses
import logging
from typing import Any, Dict, List, Optional # Added Optional
from pyrc_core.client.curses_utils import SafeCursesUtils
from pyrc_core.context_manager import ChannelJoinStatus, ContextManager # Added ContextManager

logger = logging.getLogger("pyrc.sidebar_panel_renderer")

MIN_SIDEBAR_USER_LIST_WIDTH = (
    8  # Minimum practical width to attempt drawing user list items
)

class SidebarPanelRenderer:
    def __init__(self, colors: Dict[str, int], context_manager_ref: ContextManager): # Added context_manager_ref
        self.colors = colors
        self.context_manager = context_manager_ref # Store reference

    def draw(self, window: Any, active_context_obj: Any, all_contexts_data: List[str]):
        """Draws the sidebar content, including context list and user list."""
        if not window:
            return

        try:
            window.erase()
            window.bkgd(" ", self.colors.get("list_panel_bg", 0)) # Use get for safety
        except curses.error as e:
            logger.warning(f"Error erasing/setting bkgd for sidebar: {e}")
            return # If we can't set background, probably can't draw text either

        max_y, max_x = window.getmaxyx()
        if max_y <= 0 or max_x <= 0:
            return

        line_num = self._draw_sidebar_context_list(
            window, max_y, max_x, active_context_obj.name if active_context_obj else "", all_contexts_data
        )

        if active_context_obj and active_context_obj.type == "channel": # Only draw user list for channels
            user_list_bg_color = self.colors.get("user_list_panel_bg", 0) # Use get for safety
            for y_coord in range(line_num, max_y): # Corrected variable name from y to y_coord
                try:
                    if max_x > 0:
                        window.addnstr(y_coord, 0, ' ' * max_x, max_x, user_list_bg_color)
                except curses.error:
                    pass # Ignore errors if drawing background fails (e.g. too small)

            if line_num > 0 and line_num < max_y:
                SafeCursesUtils._safe_hline(
                    window,
                    line_num,
                    0,
                    curses.ACS_HLINE,
                    max_x,
                    self.colors.get("user_list_panel_bg", 0), # Use get for safety
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
            try:
                window.noutrefresh()
            except curses.error as e:
                logger.warning(f"curses.error on noutrefresh in draw (SidebarPanelRenderer): {e}")

    def _draw_sidebar_context_list(
        self, window: Any, max_y: int, max_x: int, current_active_ctx_name_str: str, all_contexts_names: List[str]
    ) -> int: # Renamed all_contexts_data to all_contexts_names
        """Draws the list of contexts (windows) in the sidebar. Returns the next line_num."""
        line_num = 0
        SafeCursesUtils._draw_full_width_banner(
            window,
            line_num,
            "Windows:",
            self.colors.get("list_panel_bg", 0), # Use get for safety
            "_draw_sidebar_context_list_header",
        )
        line_num += 1

        # Sort contexts: Status last, others alphabetically
        status_context_name = "Status"
        dcc_context_name = "DCC" # Assuming "DCC" is the name for DCC context

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
            if line_num >= max_y -1: # Check if space for this item
                break

            display_name_base = ctx_name[: max_x - 4] # Truncate name if too long
            attr = self.colors.get("sidebar_item", 0) # Default attribute

            ctx_obj = self.context_manager.get_context(ctx_name) # Use self.context_manager
            unread_count = self.context_manager.get_unread_count(ctx_name) if ctx_obj else 0

            prefix = " "
            status_suffix = ""

            if ctx_obj and ctx_obj.type == "channel" and hasattr(ctx_obj, 'join_status') and ctx_obj.join_status:
                join_status = ctx_obj.join_status
                if join_status == ChannelJoinStatus.PENDING_INITIAL_JOIN or \
                   join_status == ChannelJoinStatus.JOIN_COMMAND_SENT:
                    status_suffix = " (joining...)"
                    attr = self.colors.get("sidebar_item", 0) | curses.A_DIM
                elif join_status == ChannelJoinStatus.SELF_JOIN_RECEIVED:
                    status_suffix = " (users...)"
                    attr = self.colors.get("sidebar_item", 0) | curses.A_DIM
                elif join_status == ChannelJoinStatus.JOIN_FAILED:
                    status_suffix = " (failed!)"
                    attr = self.colors.get("error", 0)

            if ctx_name == current_active_ctx_name_str:
                attr = self.colors.get("highlight", 0)
                prefix = ">"
            elif unread_count > 0:
                attr = self.colors.get("highlight", 0)
                prefix = "*"
            else: # Ensure non-highlighted items use the panel background
                attr = self.colors.get("list_panel_bg", 0)


            display_name_final = f"{prefix}{display_name_base}{status_suffix}"
            if unread_count > 0 and ctx_name != current_active_ctx_name_str:
                display_name_final += f" ({unread_count})"

            padded_display_line = display_name_final.ljust(max_x)
            SafeCursesUtils._safe_addstr(
                window,
                line_num,
                0, # Start at column 0 for full background
                padded_display_line, # Use padded line
                attr,
                "_draw_sidebar_context_list_item",
            )
            line_num += 1

        if line_num < max_y -1: # Add a gap if there's space before next section
            line_num += 1
        return line_num


    def _draw_sidebar_user_list_header(
        self,
        window: Any,
        line_num: int,
        max_y: int,
        max_x: int,
        active_ctx_obj_for_users: Any, # This is a Context object
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
            self.colors.get("user_list_panel_bg", 0), # Use get for safety
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
                    0, # Start at column 0
                    "[Users Hidden]".ljust(max_x), # Pad to fill width
                    self.colors.get("user_list_panel_bg", 0) | curses.A_DIM, # Use panel bg
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
            if lines_for_nicks > 0: # Need at least 1 line for the indicator itself
                up_indicator_text = "^ More"[: max_x -1] # Truncate if needed
                lines_for_nicks -= 1 # Account for the indicator line

        # Check if there are more users below the current view
        if current_user_scroll_offset + lines_for_nicks < total_users:
            if lines_for_nicks > 0: # Need at least 1 line for this indicator too
                down_indicator_text = "v More"[: max_x -1]
                lines_for_nicks -= 1

        lines_for_nicks = max(0, lines_for_nicks) # Ensure not negative

        if up_indicator_text and line_num < max_y:
            SafeCursesUtils._safe_addstr(
                window,
                line_num,
                0, # Start at column 0
                (" " + up_indicator_text).ljust(max_x), # Pad to fill
                self.colors.get("user_list_panel_bg", 0) | curses.A_DIM, # Use panel bg
                "_draw_sidebar_user_list_up_indicator",
            )
            line_num += 1

        start_idx = current_user_scroll_offset
        end_idx = current_user_scroll_offset + lines_for_nicks # Use calculated lines_for_nicks
        visible_users_page = sorted_user_items[start_idx:end_idx]

        for nick, prefix_str in visible_users_page:
            if line_num >= max_y: # Check if we ran out of space
                break
            display_user_with_prefix = f"{prefix_str}{nick}"
            padded_display_line = (" " + display_user_with_prefix).ljust(max_x) # Pad to fill

            user_color = self.colors.get("user_list_panel_bg", 0) # Default to panel background
            if prefix_str == "@": # Example: highlight ops
                user_color = self.colors.get("user_prefix", user_color) # Use user_prefix if defined, else panel_bg

            SafeCursesUtils._safe_addstr(
                window,
                line_num,
                0, # Start at column 0
                padded_display_line, # Use padded line
                user_color,
                "_draw_sidebar_user_list_item",
            )
            line_num += 1

        if down_indicator_text and line_num < max_y:
            SafeCursesUtils._safe_addstr(
                window,
                line_num,
                0, # Start at column 0
                (" " + down_indicator_text).ljust(max_x), # Pad to fill
                self.colors.get("user_list_panel_bg", 0) | curses.A_DIM, # Use panel bg
                "_draw_sidebar_user_list_down_indicator",
            )
            line_num += 1

        return line_num
