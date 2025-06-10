# pyrc_core/client/dummy_ui.py
import curses # For curses.ERR

class DummyUI:
    def __init__(self):
        self.colors = {"default": 0, "system": 0, "join_part": 0, "nick_change": 0, "my_message": 0, "other_message": 0, "highlight": 0, "error": 0, "status_bar": 0, "sidebar_header": 0, "sidebar_item": 0, "sidebar_user": 0, "input": 0, "pm": 0, "user_prefix": 0, "warning": 0, "info": 0, "debug": 0, "timestamp": 0, "nick": 0, "channel": 0, "query": 0, "status": 0, "list": 0, "list_selected": 0, "list_header": 0, "list_footer": 0, "list_highlight": 0, "list_selected_highlight": 0, "list_selected_header": 0, "list_selected_highlight_footer": 0}
        self.split_mode_active = False
        self.active_split_pane = "top"
        self.top_pane_context_name = ""
        self.bottom_pane_context_name = ""
        self.msg_win_width = 80
        self.msg_win_height = 24

    def refresh_all_windows(self):
        pass

    def scroll_messages(self, direction: str, lines: int = 1):
        pass

    def get_input_char(self) -> int:
        return curses.ERR if curses else -1

    def setup_layout(self):
        pass

    def scroll_user_list(self, direction: str, lines_arg: int = 1):
        pass

    def _calculate_available_lines_for_user_list(self) -> int:
        return 0

    def shutdown(self):
        pass

    async def add_message_to_context(
        self, text: str, color_attr: int, prefix_time: bool, context_name: str
    ):
        """Dummy method for headless UI, does nothing."""
        pass
