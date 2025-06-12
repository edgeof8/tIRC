import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

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

async def handle_names_command(client: "IRCClient_Logic", args_str: str):
    channel_arg = args_str.strip()

    if channel_arg:
        await client.network_handler.send_raw(f"NAMES {channel_arg}")
        # Determine context for feedback message
        feedback_context_name = "Status"
        target_channel_context = client.context_manager.get_context(
            channel_arg
        )
        if target_channel_context and target_channel_context.type == "channel":
            feedback_context_name = target_channel_context.name

        await client.add_message(
            f"Refreshing names for {channel_arg}...",
            client.ui.colors["system"], # Using semantic color key
            context_name=feedback_context_name,
        )
    else:
        # Behavior for /NAMES without args can vary.
        # This implementation sends NAMES for the current channel if it's active and a channel,
        # otherwise sends a general NAMES command to the server.
        active_context = client.context_manager.get_active_context()
        if active_context and active_context.type == "channel":
            await client.network_handler.send_raw(f"NAMES {active_context.name}")
            await client.add_message(
                f"Refreshing names for current channel {active_context.name}...",
                client.ui.colors["system"],
                context_name=active_context.name,
            )
        else:
            await client.network_handler.send_raw("NAMES")
            await client.add_message(
                "Requesting names (no specific channel)...",
                client.ui.colors["system"],
                context_name="Status",
            )
