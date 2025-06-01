import curses
from collections import deque
import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from irc_client_logic import (
        IRCClient_Logic,
    )
    from command_handler import CommandHandler
    from ui_manager import UIManager

logger = logging.getLogger("pyrc.input")

COMMAND_HISTORY_MAX_SIZE = 100

class InputHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client_logic = client_logic
        self.input_buffer: str = ""
        self.tab_completion_candidates: List[str] = []
        self.tab_completion_index: int = -1
        self.last_tab_completed_prefix: str = (
            ""
        )
        self.command_history: deque = deque(maxlen=COMMAND_HISTORY_MAX_SIZE)
        self.history_idx: int = -1
        self.current_input_snapshot: str = ""

    def get_current_input_buffer(self) -> str:
        return self.input_buffer

    def handle_key_press(self, key_code: int):
        if key_code == curses.ERR:
            return

        ui = self.client_logic.ui
        command_handler = self.client_logic.command_handler

        if key_code != 9:
            if self.tab_completion_candidates:
                logger.debug("Resetting tab completion state due to non-TAB key press.")
                self.tab_completion_candidates = []
                self.tab_completion_index = -1
                self.last_tab_completed_prefix = ""

        if key_code == curses.KEY_RESIZE:
            ui.setup_layout()
        elif key_code in [
            curses.KEY_BACKSPACE,
            127,
            8,
        ]:
            if self.input_buffer:
                was_viewing_history = self.history_idx != -1
                self.input_buffer = self.input_buffer[:-1]
                if was_viewing_history:
                    self.history_idx = -1
                    self.current_input_snapshot = self.input_buffer
        elif key_code in [curses.KEY_ENTER, 10, 13]:
            if self.input_buffer:
                command_to_process = self.input_buffer
                command_handler.process_user_command(command_to_process)
                if command_to_process:
                    if not self.command_history or command_to_process != self.command_history[0]:
                        self.command_history.appendleft(command_to_process)
                self.input_buffer = ""
                self.history_idx = -1
                self.current_input_snapshot = ""
        elif key_code == curses.KEY_UP:
            if self.command_history:
                if self.history_idx == -1:
                    self.current_input_snapshot = self.input_buffer

                self.history_idx += 1
                self.history_idx = min(self.history_idx, len(self.command_history) - 1)

                if 0 <= self.history_idx < len(self.command_history):
                    self.input_buffer = self.command_history[self.history_idx]
        elif key_code == curses.KEY_DOWN:
            if self.history_idx == -1:
                pass
            else:
                self.history_idx -= 1
                if self.history_idx < 0:
                    self.history_idx = -1
                    self.input_buffer = self.current_input_snapshot
                else:
                    self.input_buffer = self.command_history[self.history_idx]
        elif key_code == curses.KEY_PPAGE:
            ui.scroll_messages("up")
        elif key_code == curses.KEY_NPAGE:
            ui.scroll_messages("down")
        elif key_code == curses.KEY_HOME:
            ui.scroll_messages("home")
        elif key_code == curses.KEY_END:
            ui.scroll_messages("end")
        elif key_code == 14:  # CTRL+N
            self.client_logic.switch_active_context("next")
        elif key_code == 16:  # CTRL+P
            self.client_logic.switch_active_context("prev")
        elif key_code == 21:  # CTRL+U
            current_context = self.client_logic.context_manager.get_context(
                self.client_logic.context_manager.active_context_name or "Status"
            )
            if current_context and current_context.type == "channel":
                total_users = len(current_context.users)
                sidebar_height = (
                    self.client_logic.ui._calculate_available_lines_for_user_list()
                )

                if sidebar_height > 0 and total_users > 0:
                    new_offset = (
                        current_context.user_list_scroll_offset + sidebar_height
                    )

                    if new_offset >= total_users:
                        current_context.user_list_scroll_offset = 0
                    else:
                        current_context.user_list_scroll_offset = new_offset

                    self.client_logic.ui_needs_update.set()
        elif key_code == 9:
            self.do_tab_complete()
        elif key_code >= 0:
            try:
                if (
                    key_code <= 255
                ):
                    char_to_add = chr(key_code)
                    was_viewing_history = self.history_idx != -1
                    self.input_buffer += char_to_add
                    if was_viewing_history:
                        self.history_idx = -1
                        self.current_input_snapshot = self.input_buffer
            except (ValueError, Exception) as e:
                logger.warning(f"Could not convert key_code {key_code} to char or other error: {e}")
                pass

        self.client_logic.ui_needs_update.set()

    def do_tab_complete(self):
        if not self.input_buffer:
            self.tab_completion_candidates = (
                []
            )
            self.tab_completion_index = -1
            self.last_tab_completed_prefix = ""
            return

        parts = self.input_buffer.split(" ")
        to_complete_current_input = parts[-1]
        prefix_str = " ".join(parts[:-1]) + (" " if len(parts) > 1 else "")

        command_handler = self.client_logic.command_handler
        context_manager = self.client_logic.context_manager
        active_context_name = context_manager.active_context_name
        current_user_nick = self.client_logic.nick
        ui_colors = self.client_logic.ui.colors

        if len(parts) == 1 and self.input_buffer.startswith("/"):
            self.tab_completion_candidates = []
            self.tab_completion_index = -1
            self.last_tab_completed_prefix = ""

            if not to_complete_current_input:
                return

            available_commands = (
                command_handler.get_available_commands_for_tab_complete()
            )
            cmd_candidates = [
                cmd
                for cmd in available_commands
                if cmd.lower().startswith(to_complete_current_input.lower())
            ]

            if len(cmd_candidates) == 1:
                self.input_buffer = cmd_candidates[0] + " "
            elif len(cmd_candidates) > 1:
                self.client_logic.add_message(
                    f"Commands: {' '.join(sorted(cmd_candidates))}",
                    ui_colors["system"],
                    prefix_time=False,
                    context_name=active_context_name,
                )
            self.client_logic.ui_needs_update.set()
            return

        if not to_complete_current_input and not self.input_buffer.endswith(" "):
            if (
                not self.last_tab_completed_prefix
            ):
                self.tab_completion_candidates = []
                self.tab_completion_index = -1
                return

        # Check if we are continuing a cycle for the *exact same* typed prefix
        if (
            self.tab_completion_candidates
            and to_complete_current_input == self.last_tab_completed_prefix
        ):
            self.tab_completion_index = (self.tab_completion_index + 1) % len(
                self.tab_completion_candidates
            )
            logger.debug(
                f"Continuing tab cycle for '{self.last_tab_completed_prefix}'. Index: {self.tab_completion_index}"
            )
        else:
            logger.debug(
                f"New tab sequence or prefix changed. Old prefix: '{self.last_tab_completed_prefix}', New to_complete: '{to_complete_current_input}'"
            )
            self.last_tab_completed_prefix = to_complete_current_input
            self.tab_completion_candidates = []
            self.tab_completion_index = -1

            if (
                not self.last_tab_completed_prefix
            ):
                self.client_logic.ui_needs_update.set()
                return

            active_users_nicks = []
            if active_context_name:
                active_ctx_obj = context_manager.get_context(active_context_name)
                if active_ctx_obj and active_ctx_obj.type == "channel":
                    active_users_nicks = list(
                        active_ctx_obj.users.keys()
                    )

            self.tab_completion_candidates = sorted(
                [
                    nick
                    for nick in active_users_nicks
                    if nick.lower().startswith(self.last_tab_completed_prefix.lower())
                ],
                key=lambda s: s.lower(),
            )

            if not self.tab_completion_candidates:
                logger.debug(
                    f"No nick candidates found for '{self.last_tab_completed_prefix}'"
                )
                self.last_tab_completed_prefix = (
                    ""
                )
                self.client_logic.ui_needs_update.set()
                return

            self.tab_completion_index = 0
            logger.debug(
                f"Found nick candidates for '{self.last_tab_completed_prefix}': {self.tab_completion_candidates}. Starting at index 0."
            )

        if self.tab_completion_candidates:
            completed_nick = self.tab_completion_candidates[self.tab_completion_index]

            suffix = ": " if not prefix_str else " "

            self.input_buffer = prefix_str + completed_nick + suffix
            logger.debug(f"Tab completed to: '{self.input_buffer}'")
        else:
            logger.debug(
                "Tab pressed but no candidates available (should have been handled)."
            )
            pass

        self.client_logic.ui_needs_update.set()
