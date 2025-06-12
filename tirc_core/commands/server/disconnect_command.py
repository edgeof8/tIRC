import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.server.disconnect")

COMMAND_DEFINITIONS = [
    {
        "name": "disconnect",
        "handler": "handle_disconnect_command",
        "help": {
            "usage": "/disconnect [reason]",
            "description": "Disconnects from the current server.",
            "aliases": ["d"]
        }
    }
]

async def handle_disconnect_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /disconnect command"""
    reason = args_str if args_str else "Disconnecting"
    await client.add_message(
        f"Disconnecting from server... (Reason: {reason})",
        client.ui.colors["system"],
        context_name="Status"
    )
    logger.info(f"User initiated /disconnect. Reason: {reason}")
    await client.network_handler.disconnect_gracefully(reason)
