import logging
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.information_commands_handler")

class InformationCommandsHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic

    def handle_who_command(self, args_str: str):
        target = args_str.strip()
        if not target:
            active_context = self.client.context_manager.get_active_context()
            if active_context and active_context.type == "channel":
                target = active_context.name
                logger.debug(f"/who command using active channel '{target}' as target.")
            else:
                self.client.add_message(
                    self.client.command_handler.COMMAND_USAGE_STRINGS["who"],
                    self.client.ui.colors["error"],
                    context_name="Status"
                )
                return

        if target:
            self.client.network.send_raw(f"WHO {target}")
        else:
            # This case should ideally be caught by the logic above,
            # but as a fallback, show usage if no target could be determined.
            self.client.add_message(
                self.client.command_handler.COMMAND_USAGE_STRINGS["who"],
                self.client.ui.colors["error"],
                context_name="Status"
            )

    def handle_whowas_command(self, args_str: str):
        parts = self.client.command_handler._ensure_args(
            args_str,
            self.client.command_handler.COMMAND_USAGE_STRINGS["whowas"],
            num_expected_parts=1 # Ensure at least the nick is provided
        )
        if not parts:
            return

        # parts[0] will be the rest of the string after the first split by _ensure_args
        # if num_expected_parts was > 1. Here, parts[0] is args_str itself.
        # We need to split args_str further for nick, count, and target_server.

        split_args = args_str.strip().split(" ", 2)
        nick_arg = split_args[0]
        count_arg: Optional[str] = None
        target_server_arg: Optional[str] = None

        if len(split_args) > 1:
            # Try to determine if the second argument is count or target_server
            # A simple heuristic: if it's numeric, assume it's count.
            if split_args[1].isdigit():
                count_arg = split_args[1]
                if len(split_args) > 2:
                    target_server_arg = split_args[2]
            else:
                # If not numeric, assume it's target_server (and no count was given)
                target_server_arg = split_args[1]
                # This also covers if len(split_args) == 2 and split_args[1] is not a digit.

        command_parts = ["WHOWAS", nick_arg]
        if count_arg:
            command_parts.append(count_arg)
        if target_server_arg:
            # If count_arg was not provided but target_server_arg was,
            # WHOWAS expects count to be there if target_server is.
            # However, many servers are lenient.
            # For stricter compliance, one might insert a default count if target_server is present and count isn't.
            # For now, we'll send as parsed.
            command_parts.append(target_server_arg)

        self.client.network.send_raw(" ".join(command_parts))

    def handle_list_command(self, args_str: str):
        pattern = args_str.strip()

        # Placeholder for temporary context logic (Phase 4)
        # For now, self.client.active_list_context_name can be a simple attribute
        # on IRCClient_Logic.

        # Generate a unique name for the list context.
        # This doesn't create a "real" context in ContextManager yet,
        # but provides a unique identifier for numeric handlers to use if they
        # were to create one or direct messages.
        # For now, we'll just use it to signal to numeric handlers.
        # A more robust solution would involve ContextManager.
        import time # Add this import at the top of the file
        self.client.active_list_context_name = f"list-output-{time.time_ns()}"
        logger.debug(f"Set active_list_context_name to {self.client.active_list_context_name} for /list command.")
        # The numeric handlers will still default to "Status" for now,
        # but this attribute is now set for them to potentially use.

        self.client.network.send_raw(f"LIST {pattern}" if pattern else "LIST")

    def handle_names_command(self, args_str: str):
        channel_arg = args_str.strip()

        if channel_arg:
            self.client.network.send_raw(f"NAMES {channel_arg}")
            # Determine context for feedback message
            feedback_context_name = "Status"
            target_channel_context = self.client.context_manager.get_context(channel_arg)
            if target_channel_context and target_channel_context.type == "channel":
                feedback_context_name = target_channel_context.name

            self.client.add_message(
                f"Refreshing names for {channel_arg}...",
                self.client.ui.colors["system"],
                context_name=feedback_context_name
            )
        else:
            self.client.network.send_raw("NAMES")
