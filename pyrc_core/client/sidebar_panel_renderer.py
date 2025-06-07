import curses
import logging
from typing import Any, Dict, List
from pyrc_core.client.curses_utils import SafeCursesUtils
from pyrc_core.context_manager import ChannelJoinStatus

logger = logging.getLogger("pyrc.sidebar_panel_renderer")

MIN_SIDEBAR_USER_LIST_WIDTH = (
    8  # Minimum practical width to attempt drawing user list items
)

class SidebarPanelRenderer:
    def __init__(self, colors: Dict[str, int]):
        self.colors = colors

    def draw(self, window: Any, active_context_obj: Any, all_contexts_data: List[str]):
        """Draws the sidebar content, including context list and user list."""
        if not window:
            return

        # Draw background for the entire sidebar with the default panel color
        SafeCursesUtils._draw_window_border_and_bkgd(window, self.colors["list_panel_bg"])

        max_y, max_x = window.getmaxyx()
        if max_y <= 0 or max_x <= 0:
            return

        # Draw context list
        line_num = self._draw_sidebar_context_list(
            window, max_y, max_x, active_context_obj.name if active_context_obj else "", all_contexts_data, active_context_obj
        )

        # Draw user list header and items if applicable
        if active_context_obj and active_context_obj.type != "dcc":
            # Overwrite the background for the user list area
            user_list_bg_color = self.colors["user_list_panel_bg"]
            for y in range(line_num, max_y):
                try:
                    if max_x > 0:
                        window.addnstr(y, 0, ' ' * max_x, max_x, user_list_bg_color)
                except curses.error:
                    pass

            # Draw the separator line
            if line_num > 0 and line_num < max_y:
                SafeCursesUtils._safe_hline(
                    window,
                    line_num,
                    0,
                    curses.ACS_HLINE,
                    max_x,
                    self.colors.get("user_list_panel_bg", 0),
                    "_draw_sidebar_user_list_hline",
                )
                line_num += 1

            # Draw the user list header and items
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

    def _draw_sidebar_context_list(
        self, window: Any, max_y: int, max_x: int, current_active_ctx_name_str: str, all_contexts_data: List[str], active_context_obj: Any
    ) -> int:
        """Draws the list of contexts (windows) in the sidebar. Returns the next line_num."""
        line_num = 0
        SafeCursesUtils._draw_full_width_banner(
            window,
            line_num,
            "Windows:",
            self.colors.get("list_panel_bg", 0),
            "_draw_sidebar_context_list_header",
        )
        line_num += 1

        all_context_names_unsorted = all_contexts_data
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
            # This part needs to be passed from UIManager, or context_obj needs to be richer
            # For now, we'll assume context_obj has join_status and unread_count if it's the active one
            # or we need a way to get individual context objects here.
            # For simplicity in this renderer, we'll assume context_obj is the active one,
            # and for others, we'll just display name and unread count if available.
            # A more robust solution would pass a list of context objects or a ContextManager reference.
            # For now, we'll mock unread_count and join_status for non-active contexts.

            # Placeholder for actual context object retrieval or data passing
            # This is a simplification; in a real app, you'd pass a richer data structure.
            ctx_obj_placeholder = None # This would be the actual context object for ctx_name
            # For now, we'll simulate based on active_context_obj.
            # This is a known limitation for this refactoring step.

            unread_count = 0 # Placeholder
            join_status = None # Placeholder

            # If the current context being drawn is the active one, use its actual properties
            if ctx_name == current_active_ctx_name_str:
                # This logic should ideally be in UIManager, which passes the full context object
                # or a simplified data structure for each context to the renderer.
                # For now, directly accessing client.context_manager is a temporary workaround.
                # This indicates a need for a data layer between UIManager and renderers.
                # For this refactoring step, we'll assume active_context_obj is the one we care about.
                if hasattr(active_context_obj, 'join_status') and active_context_obj.name == ctx_name and active_context_obj is not None:
                    join_status = active_context_obj.join_status
                if hasattr(active_context_obj, 'unread_count') and active_context_obj.name == ctx_name and active_context_obj is not None:
                    unread_count = active_context_obj.unread_count
                # If not the active context, we'd need to fetch its unread_count from client.context_manager
                # This highlights the need for a data provider to the renderers.
                # For now, we'll fetch unread_count for all contexts.
                # This is a temporary deviation from strict SRP for initial refactoring.
                unread_count = self._get_unread_count_for_context(ctx_name)


            prefix = " "
            status_suffix = ""

            if (
                join_status is not None
            ):
                if (
                    join_status == ChannelJoinStatus.PENDING_INITIAL_JOIN
                    or join_status == ChannelJoinStatus.JOIN_COMMAND_SENT
                ):
                    status_suffix = " (joining...)"
                    attr = self.colors.get("sidebar_item", 0) | curses.A_DIM
                elif join_status == ChannelJoinStatus.SELF_JOIN_RECEIVED:
                    status_suffix = " (users...)"
                    attr = self.colors.get("sidebar_item", 0) | curses.A_DIM
                elif join_status == ChannelJoinStatus.JOIN_FAILED:
                    status_suffix = " (failed!)"
                    attr = self.colors.get("error", 0)

            if ctx_name == active_context_name_for_list_highlight:
                attr = self.colors.get("highlight", 0)
                prefix = ">"
            elif unread_count > 0:
                attr = self.colors.get("highlight", 0)
                prefix = "*"
            else:
                attr = self.colors.get("list_panel_bg", 0)

            display_name_final = f"{prefix}{display_name_base}{status_suffix}"
            if unread_count > 0 and ctx_name != active_context_name_for_list_highlight:
                display_name_final += f" ({unread_count})"

            padded_display_line = display_name_final.ljust(max_x)
            SafeCursesUtils._safe_addstr(
                window,
                line_num,
                0,
                padded_display_line,
                attr,
                "_draw_sidebar_context_list_item",
            )
            line_num += 1

        if (
            line_num < max_y - 1
        ):
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
        if not active_ctx_obj_for_users:
            return line_num

        if line_num >= max_y:
            return line_num

        channel_users_dict = active_ctx_obj_for_users.users
        user_count = len(channel_users_dict)
        user_header_full = (
            f"Users in {current_active_ctx_name_for_user_header} ({user_count})"
        )

        SafeCursesUtils._draw_full_width_banner(
            window,
            line_num,
            user_header_full,
            self.colors.get("user_list_panel_bg", 0),
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

        current_user_scroll_offset = active_ctx_obj_for_users.user_list_scroll_offset
        channel_users_dict = active_ctx_obj_for_users.users

        if max_x < MIN_SIDEBAR_USER_LIST_WIDTH:
            if line_num < max_y:
                SafeCursesUtils._safe_addstr(
                    window,
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

        if up_indicator_text and line_num < max_y:
            SafeCursesUtils._safe_addstr(
                window,
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
            padded_display_line = (" " + display_user_with_prefix).ljust(max_x)
            user_color = self.colors.get("sidebar_item", 0)
            if prefix_str == "@":
                user_color = self.colors.get("user_prefix", user_color)

            if not (user_color & curses.A_STANDOUT or user_color & curses.A_BOLD):
                 user_color = self.colors.get("user_list_panel_bg", 0)

            SafeCursesUtils._safe_addstr(
                window,
                line_num,
                0,
                padded_display_line,
                user_color,
                "_draw_sidebar_user_list_item",
            )
            line_num += 1

        if down_indicator_text and line_num < max_y:
            SafeCursesUtils._safe_addstr(
                window,
                line_num,
                1,
                down_indicator_text,
                self.colors.get("sidebar_item", 0) | curses.A_DIM,
                "_draw_sidebar_user_list_down_indicator",
            )
            line_num += 1

        return line_num

    # This method is a temporary placeholder. In a proper refactoring,
    # the UIManager would pass a comprehensive data model to the renderers,
    # or the renderers would receive a reference to a data manager.
    def _get_unread_count_for_context(self, ctx_name: str) -> int:
        # This is a hacky way to get unread count without a direct client ref.
        # In a real scenario, UIManager would fetch all necessary data and pass it.
        # For now, we'll return 0, or you might need to pass client_ref to this renderer.
        # For the purpose of this refactoring, we'll assume 0 for now.
        return 0
