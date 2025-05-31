# input_handler.py
import curses
from collections import deque
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import (
        IRCClient_Logic,
    )  # To avoid circular import for type hinting
    from command_handler import CommandHandler
    from ui_manager import UIManager

logger = logging.getLogger("pyrc.input")


class InputHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client_logic = client_logic
        self.input_buffer: str = ""
        self.partial_input_history: deque[str] = deque(maxlen=20)
        self.partial_input_history_idx: int = -1

    def get_current_input_buffer(self) -> str:
        return self.input_buffer

    def handle_key_press(self, key_code: int):
        # logger.debug(f"Input key_code: {key_code}") # Can be very verbose
        if key_code == curses.ERR:
            return

        ui = self.client_logic.ui
        command_handler = self.client_logic.command_handler

        if key_code == curses.KEY_RESIZE:
            ui.setup_layout()
        elif key_code in [
            curses.KEY_BACKSPACE,
            127,
            8,
        ]:  # 127 is Backspace on some systems, 8 is Unix backspace
            self.input_buffer = self.input_buffer[:-1]
        elif key_code in [curses.KEY_ENTER, 10, 13]:  # 10 is LF, 13 is CR
            if self.input_buffer:
                command_to_process = self.input_buffer
                # Use CommandHandler from client_logic
                command_handler.process_user_command(command_to_process)
                if command_to_process:  # Use the copy for history
                    if (
                        not self.partial_input_history
                        or self.partial_input_history[-1] != command_to_process
                    ):
                        self.partial_input_history.append(command_to_process)
                self.input_buffer = ""
                self.partial_input_history_idx = -1
        elif key_code == curses.KEY_UP:
            if self.partial_input_history:
                if self.partial_input_history_idx == -1:  # First press UP
                    self.partial_input_history_idx = len(self.partial_input_history) - 1
                elif self.partial_input_history_idx > 0:
                    self.partial_input_history_idx -= 1

                if (
                    0
                    <= self.partial_input_history_idx
                    < len(self.partial_input_history)
                ):
                    self.input_buffer = self.partial_input_history[
                        self.partial_input_history_idx
                    ]
        elif key_code == curses.KEY_DOWN:
            if self.partial_input_history and self.partial_input_history_idx != -1:
                if self.partial_input_history_idx < len(self.partial_input_history) - 1:
                    self.partial_input_history_idx += 1
                    self.input_buffer = self.partial_input_history[
                        self.partial_input_history_idx
                    ]
                else:  # Reached end of history, clear buffer
                    self.partial_input_history_idx = -1
                    self.input_buffer = ""
        elif key_code == curses.KEY_PPAGE:  # Page Up
            ui.scroll_messages("up")
        elif key_code == curses.KEY_NPAGE:  # Page Down
            ui.scroll_messages("down")
        elif key_code == curses.KEY_HOME:
            ui.scroll_messages("home")
        elif key_code == curses.KEY_END:
            ui.scroll_messages("end")
        elif key_code == 14:  # CTRL+N
            self.client_logic.switch_active_context("next")
        elif key_code == 16:  # CTRL+P
            self.client_logic.switch_active_context("prev")
        elif key_code == 9:  # TAB
            self.do_tab_complete()
        elif key_code >= 0:  # Printable characters (basic check)
            try:
                if (
                    key_code <= 255
                ):  # Basic ASCII check, might need refinement for unicode
                    self.input_buffer += chr(key_code)
            except (ValueError, Exception) as e:
                logger.warning(f"Could not convert key_code {key_code} to char: {e}")
                pass  # Ignore if character conversion fails

        self.client_logic.ui_needs_update.set()

    def do_tab_complete(self):
        if not self.input_buffer:
            return

        parts = self.input_buffer.split(" ")
        to_complete = parts[-1]
        prefix_str = " ".join(parts[:-1]) + (" " if len(parts) > 1 else "")

        if not to_complete:
            return

        candidates = []
        # Accessing client_logic attributes
        command_handler = self.client_logic.command_handler
        context_manager = self.client_logic.context_manager  # Use ContextManager
        active_context_name = context_manager.active_context_name
        current_nick = (
            self.client_logic.nick
        )  # nick is still a direct attribute of IRCClient_Logic
        ui_colors = self.client_logic.ui.colors

        if len(parts) == 1 and self.input_buffer.startswith("/"):
            # Command completion
            available_commands = (
                command_handler.get_available_commands_for_tab_complete()
            )
            candidates = [
                cmd
                for cmd in available_commands
                if cmd.lower().startswith(to_complete.lower())
            ]
        else:
            # Nick completion
            active_users = []
            if active_context_name:  # Check if active_context_name is not None
                active_ctx_obj = context_manager.get_context(active_context_name)
                if active_ctx_obj and active_ctx_obj.type == "channel":
                    active_users = list(active_ctx_obj.users)

            # Ensure current_nick is in the list for completion
            unique_nicks_set = set(active_users)
            if current_nick:
                unique_nicks_set.add(current_nick)

            candidates = [
                nick
                for nick in sorted(list(unique_nicks_set))
                if nick.lower().startswith(to_complete.lower())
            ]

        if len(candidates) == 1:
            self.input_buffer = prefix_str + candidates[0] + " "
        elif len(candidates) > 1:
            # Find common prefix among candidates (case-insensitive search, case-preserving completion)
            # This logic is a bit simplified for now, might need more robust common prefix finding
            # For now, we'll use the original logic's approach for common prefix

            sorted_candidates_lower = sorted(list(set(c.lower() for c in candidates)))
            if not sorted_candidates_lower:
                return

            common_prefix_lower = sorted_candidates_lower[0]
            for cand_lower in sorted_candidates_lower[1:]:
                while not cand_lower.startswith(common_prefix_lower):
                    common_prefix_lower = common_prefix_lower[:-1]
                    if not common_prefix_lower:
                        break
                if not common_prefix_lower:
                    break

            original_cased_common_prefix = ""
            if common_prefix_lower:
                # Find an original candidate that matches the common_prefix_lower to get the casing
                for (
                    original_cand
                ) in candidates:  # Iterate through original candidates to preserve case
                    if original_cand.lower().startswith(common_prefix_lower):
                        original_cased_common_prefix = original_cand[
                            : len(common_prefix_lower)
                        ]
                        break

            if original_cased_common_prefix and len(original_cased_common_prefix) > len(
                to_complete
            ):
                self.input_buffer = prefix_str + original_cased_common_prefix
            else:
                # If no further common prefix or only one option after prefix, show options
                self.client_logic.add_message(
                    f"Options: {' '.join(sorted(list(set(candidates))))}",
                    ui_colors["system"],
                    prefix_time=False,
                    # active_context_name could be None, add_message handles this
                    context_name=active_context_name,
                )
        # If no candidates, buffer remains unchanged.
        self.client_logic.ui_needs_update.set()
