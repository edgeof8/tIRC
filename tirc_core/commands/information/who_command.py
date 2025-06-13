# commands/information/who_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.information.who")

COMMAND_DEFINITIONS = [
    {
        "name": "who",
        "handler": "handle_who_command",
        "help": {
            "usage": "/who [channel|nickname]",
            "description": "Retrieves WHO information for a channel or user.",
            "aliases": []
        }
    }
]

async def handle_who_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /who command."""
    target = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"

    if not target:
        # If no target, use active context if it's a channel, otherwise error
        if active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target = active_context_name
        else:
            await client.add_message("Usage: /who [channel|nickname]", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

    await client.network_handler.send_raw(f"WHO {target}")
    await client.add_status_message(f"Requesting WHO information for {target}...", "system")
    # Server will respond with RPL_WHOREPLY (352) and RPL_ENDOFWHO (315)
    # These are handled by numeric handlers.
