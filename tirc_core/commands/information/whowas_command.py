# commands/information/whowas_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.information.whowas")

COMMAND_DEFINITIONS = [
    {
        "name": "whowas",
        "handler": "handle_whowas_command",
        "help": {
            "usage": "/whowas <nickname> [count] [server]",
            "description": "Retrieves WHOWAS information for a nickname that recently disconnected.",
            "aliases": []
        }
    }
]

async def handle_whowas_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /whowas command."""
    parts = args_str.split()
    active_context_name = client.context_manager.active_context_name or "Status"

    if not parts:
        await client.add_message("Usage: /whowas <nickname> [count] [server]", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    nick_to_query = parts[0]
    count_str = parts[1] if len(parts) > 1 else None
    server_str = parts[2] if len(parts) > 2 else None # Server is less commonly used by clients for WHOWAS

    command = f"WHOWAS {nick_to_query}"
    if count_str:
        try:
            # Ensure count is a positive integer if provided
            count = int(count_str)
            if count <= 0:
                await client.add_message("WHOWAS count must be a positive integer.", client.ui.colors.get("error", 0), context_name=active_context_name)
                return
            command += f" {count}"
        except ValueError:
            await client.add_message("Invalid count for WHOWAS. Must be an integer.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

    if server_str: # This parameter is for querying a specific server in a multi-server network, usually not needed.
        command += f" {server_str}"


    if not client.network_handler.connected:
        await client.add_status_message("Not connected to any server.", "error")
        return

    await client.network_handler.send_raw(command)
    await client.add_status_message(f"Requesting WHOWAS information for {nick_to_query}...", "system")
    # Server will respond with RPL_WHOWASUSER (314), RPL_ENDOFWHOWAS (369),
    # and possibly ERR_WASNOSUCHNICK (406). These are handled by numeric handlers.
    # Messages will be added to the active_context_name by the numeric handlers.
