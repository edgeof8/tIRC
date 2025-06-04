import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

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

def handle_disconnect_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /disconnect command"""
    reason = args_str if args_str else "Disconnecting"
    client.add_message(
        f"Disconnecting from server... (Reason: {reason})",
        "system",
        context_name="Status"
    )
    logger.info(f"User initiated /disconnect. Reason: {reason}")
    client.network_handler.disconnect_gracefully(reason)
