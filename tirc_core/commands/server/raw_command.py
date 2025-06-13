# commands/server/raw_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.server.raw")

COMMAND_DEFINITIONS = [
    {
        "name": "raw",
        "handler": "handle_raw_command",
        "help": {
            "usage": "/raw <irc command>",
            "description": "Sends a raw command directly to the IRC server.",
            "aliases": ["quote", "r"]
        }
    }
]

async def handle_raw_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /raw command."""
    if not args_str:
        await client.add_message(
            "Usage: /raw <irc command>",
            client.ui.colors.get("error", 0),
            context_name=client.context_manager.active_context_name or "Status",
        )
        return

    if not client.network_handler.connected:
        await client.add_status_message("Not connected to any server.", "error")
        return

    await client.network_handler.send_raw(args_str)
    # No local echo for /raw by default, as server responses will appear.
    # User can use /rawlog on to see their raw commands if desired.
    logger.info(f"Sent RAW command: {args_str}")
