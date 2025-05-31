# input_handler.py
import curses
from collections import deque
import logging
from typing import TYPE_CHECKING, List

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
        self.command_history: deque[str] = deque(maxlen=20)  # Renamed
        self.history_idx: int = -1  # Renamed, signifies current input line
        self.current_input_snapshot: str = ""  # Stores input before browsing history

        # For enhanced nick tab-completion
        self.tab_completion_candidates: List[str] = []
        self.tab_completion_index: int = -1
        self.last_tab_completed_prefix: str = (
            ""  # Stores the exact prefix that generated the current candidates
        )

    def get_current_input_buffer(self) -> str:
        return self.input_buffer

    def handle_key_press(self, key_code: int):
        # logger.debug(f"Input key_code: {key_code}") # Can be very verbose
        if key_code == curses.ERR:
            return

        ui = self.client_logic.ui
        command_handler = self.client_logic.command_handler

        # Reset tab completion state if a non-Tab key is pressed and a cycle was active
        if key_code != 9:  # Not a TAB key
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
        ]:  # 127 is Backspace on some systems, 8 is Unix backspace
            self.input_buffer = self.input_buffer[:-1]
        elif key_code in [curses.KEY_ENTER, 10, 13]:  # 10 is LF, 13 is CR
            if self.input_buffer:
                command_to_process = self.input_buffer
                command_handler.process_user_command(command_to_process)
                # Add to history if it's not empty and not a duplicate of the last entry
                if command_to_process and (
                    not self.command_history
                    or self.command_history[-1] != command_to_process
                ):
                    self.command_history.append(command_to_process)
                self.input_buffer = ""
                self.history_idx = -1  # Reset to current input line
                self.current_input_snapshot = ""  # Clear snapshot
        elif key_code == curses.KEY_UP:
            if not self.command_history:
                return  # No history, do nothing

            if self.history_idx == -1:  # If on the current input line
                self.current_input_snapshot = self.input_buffer  # Save current input
                # Check command_history again because it might be empty initially
                if self.command_history:
                    self.history_idx = len(self.command_history) - 1  # Move to newest
                    self.input_buffer = self.command_history[self.history_idx]
            elif self.history_idx > 0:  # If in history and not at the oldest
                self.history_idx -= 1
                self.input_buffer = self.command_history[self.history_idx]
            # If self.history_idx is 0 (oldest), do nothing more on UP

        elif key_code == curses.KEY_DOWN:
            if self.history_idx == -1:
                return  # On current input line, do nothing

            # This implies self.command_history is not empty if history_idx is not -1
            if (
                self.history_idx < len(self.command_history) - 1
            ):  # If in history and not at the newest
                self.history_idx += 1
                self.input_buffer = self.command_history[self.history_idx]
            elif (
                self.history_idx == len(self.command_history) - 1
            ):  # If at the newest history item
                self.history_idx = -1  # Move to current input line
                self.input_buffer = self.current_input_snapshot  # Restore snapshot
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
        elif key_code == 21:  # CTRL+U
            current_context = self.client_logic.context_manager.get_context(
                self.client_logic.context_manager.active_context_name or "Status"
            )
            if current_context and current_context.type == "channel":
                # Get total number of users and available display lines
                total_users = len(current_context.users)
                sidebar_height = (
                    self.client_logic.ui._calculate_available_lines_for_user_list()
                )

                if sidebar_height > 0 and total_users > 0:
                    # Calculate new offset with cycling
                    new_offset = (
                        current_context.user_list_scroll_offset + sidebar_height
                    )

                    # If we would scroll past the end, cycle back to the top
                    if new_offset >= total_users:
                        current_context.user_list_scroll_offset = 0
                    else:
                        current_context.user_list_scroll_offset = new_offset

                    self.client_logic.ui_needs_update.set()
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
            self.tab_completion_candidates = (
                []
            )  # Ensure reset if buffer cleared externally
            self.tab_completion_index = -1
            self.last_tab_completed_prefix = ""
            return

        parts = self.input_buffer.split(" ")
        # to_complete is the word fragment we are trying to complete
        to_complete_current_input = parts[-1]
        # prefix_str is everything before the word we are trying to complete
        prefix_str = " ".join(parts[:-1]) + (" " if len(parts) > 1 else "")

        command_handler = self.client_logic.command_handler
        context_manager = self.client_logic.context_manager
        active_context_name = context_manager.active_context_name
        current_user_nick = self.client_logic.nick
        ui_colors = self.client_logic.ui.colors

        # Command completion (first word, starts with /)
        if len(parts) == 1 and self.input_buffer.startswith("/"):
            # For command completion, we don't implement cycling in this iteration.
            # Use existing-like logic: complete if one, show options if many.
            self.tab_completion_candidates = []  # Reset nick completion state
            self.tab_completion_index = -1
            self.last_tab_completed_prefix = ""

            if not to_complete_current_input:
                return  # Nothing to complete for a command yet

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
                # Simple: show options for commands
                self.client_logic.add_message(
                    f"Commands: {' '.join(sorted(cmd_candidates))}",
                    ui_colors["system"],
                    prefix_time=False,
                    context_name=active_context_name,
                )
            # If no candidates, buffer remains unchanged
            self.client_logic.ui_needs_update.set()
            return

        # Nick completion logic starts here
        if not to_complete_current_input and not self.input_buffer.endswith(" "):
            # If to_complete is empty because the last char is not a space,
            # it means we are at the end of a word.
            # If the user presses tab here, they might want to cycle previous candidates for that word.
            # However, if they just typed "Roo" and then space, then tab, to_complete_current_input would be empty.
            # The `last_tab_completed_prefix` check handles this.
            # If `to_complete_current_input` is empty AND `self.last_tab_completed_prefix` is also empty (or different from the word before space)
            # then there's nothing to complete.
            if (
                not self.last_tab_completed_prefix
            ):  # Or some other logic to decide if we should clear
                self.tab_completion_candidates = []
                self.tab_completion_index = -1
                # self.last_tab_completed_prefix = "" # Already empty or will be reset by non-TAB key
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
            # New tab completion sequence or the prefix being completed has changed
            logger.debug(
                f"New tab sequence or prefix changed. Old prefix: '{self.last_tab_completed_prefix}', New to_complete: '{to_complete_current_input}'"
            )
            self.last_tab_completed_prefix = to_complete_current_input  # Store the current thing user is trying to complete
            self.tab_completion_candidates = []
            self.tab_completion_index = -1

            if (
                not self.last_tab_completed_prefix
            ):  # If the part to complete is now empty, nothing to do
                self.client_logic.ui_needs_update.set()
                return

            active_users_nicks = []
            if active_context_name:
                active_ctx_obj = context_manager.get_context(active_context_name)
                if active_ctx_obj and active_ctx_obj.type == "channel":
                    active_users_nicks = list(
                        active_ctx_obj.users.keys()
                    )  # Get just nicks

            # Add current user's nick to the list if not already present (though .users should have it)
            # For safety and to ensure it's always an option if relevant.
            # unique_nicks_for_completion = set(active_users_nicks)
            # if current_user_nick:
            #     unique_nicks_for_completion.add(current_user_nick)
            # Using a list directly from users.keys() should be fine if it includes self.

            # Filter candidates (case-insensitive match)
            self.tab_completion_candidates = sorted(
                [
                    nick
                    for nick in active_users_nicks  # Iterate over original-cased nicks
                    if nick.lower().startswith(self.last_tab_completed_prefix.lower())
                ],
                key=lambda s: s.lower(),
            )  # Sort case-insensitively

            if not self.tab_completion_candidates:
                logger.debug(
                    f"No nick candidates found for '{self.last_tab_completed_prefix}'"
                )
                self.last_tab_completed_prefix = (
                    ""  # Clear if no candidates, so next tab is fresh
                )
                self.client_logic.ui_needs_update.set()
                return

            self.tab_completion_index = 0
            logger.debug(
                f"Found nick candidates for '{self.last_tab_completed_prefix}': {self.tab_completion_candidates}. Starting at index 0."
            )

        # If we have candidates (either new or continuing cycle)
        if self.tab_completion_candidates:
            completed_nick = self.tab_completion_candidates[self.tab_completion_index]

            # Determine suffix: ": " if it's the first word on the line, otherwise a single space.
            # `prefix_str` is empty if `completed_nick` is the first word.
            suffix = ": " if not prefix_str else " "

            self.input_buffer = prefix_str + completed_nick + suffix
            logger.debug(f"Tab completed to: '{self.input_buffer}'")
        else:
            # This case should ideally be caught earlier if no candidates were found initially
            logger.debug(
                "Tab pressed but no candidates available (should have been handled)."
            )
            pass  # Input buffer remains as is

        self.client_logic.ui_needs_update.set()
