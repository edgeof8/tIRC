# commands/utility/rehash_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.rehash")

COMMAND_DEFINITIONS = [
    {
        "name": "rehash",
        "handler": "handle_rehash_command",
        "help": {
            "usage": "/rehash",
            "description": "Reloads the client configuration from the INI file.",
            "aliases": []
        }
    }
]

async def handle_rehash_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /rehash command."""
    if hasattr(client, "rehash_configuration"):
        await client.rehash_configuration()
        # Feedback message is handled within IRCClient_Logic.rehash_configuration
    else:
        logger.error("IRCClient_Logic does not have handle_rehash_config method.")
        await client.add_message(
            "Error: Rehash functionality not fully implemented in client logic.",
            client.ui.colors.get("error", 0),
            context_name=client.context_manager.active_context_name or "Status",
        )
