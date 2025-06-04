import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.information.names")

COMMAND_DEFINITIONS = [
    {
        "name": "names",
        "handler": "handle_names_command",
        "help": {
            "usage": "/names [channel]",
            "description": "Shows the list of users in a channel. If no channel is specified, it may list users in the current channel or all visible users depending on the server.",
            "aliases": []
        }
    }
]

def handle_names_command(client: "IRCClient_Logic", args_str: str):
    channel_arg = args_str.strip()

    if channel_arg:
        client.network_handler.send_raw(f"NAMES {channel_arg}")
        # Determine context for feedback message
        feedback_context_name = "Status"
        target_channel_context = client.context_manager.get_context(
            channel_arg
        )
        if target_channel_context and target_channel_context.type == "channel":
            feedback_context_name = target_channel_context.name

        client.add_message(
            f"Refreshing names for {channel_arg}...",
            "system", # Using semantic color key
            context_name=feedback_context_name,
        )
    else:
        # Behavior for /NAMES without args can vary. Some servers list all users on all common channels.
        # Others might use the current active channel if it's a channel context.
        # For simplicity, sending plain NAMES and letting server decide.
        # Could add logic to use active channel if desired.
        active_context = client.context_manager.get_active_context()
        if active_context and active_context.type == "channel":
             client.network_handler.send_raw(f"NAMES {active_context.name}")
             client.add_message(
                f"Refreshing names for current channel {active_context.name}...",
                "system",
                context_name=active_context.name,
            )
        else:
            client.network_handler.send_raw("NAMES")
            client.add_message(
                "Requesting names (no specific channel)...", # Using semantic color key
                "system",
                context_name="Status",
            )
