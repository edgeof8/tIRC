# commands/information/names_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.information.names")

COMMAND_DEFINITIONS = [
    {
        "name": "names",
        "handler": "handle_names_command",
        "help": {
            "usage": "/names [channel]",
            "description": "Lists users in the specified channel or the current channel if none is given.",
            "aliases": []
        }
    }
]

async def handle_names_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /names command."""
    target_channel = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"

    if not target_channel:
        if active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel = active_context_name
        else:
            await client.add_message("Usage: /names [channel] - Please specify a channel or be in one.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

    # Normalize channel name
    normalized_channel = client.context_manager._normalize_context_name(target_channel)

    # Send NAMES command to server
    await client.network_handler.send_raw(f"NAMES {normalized_channel}")
    await client.add_status_message(f"Requested user list for {normalized_channel}...", "system")
    # Server will respond with RPL_NAMREPLY (353) and RPL_ENDOFNAMES (366)
    # These are handled by numeric handlers which will populate the UI.
