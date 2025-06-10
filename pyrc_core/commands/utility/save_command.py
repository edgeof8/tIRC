# commands/utility/save_command.py
import logging
from typing import TYPE_CHECKING
# Access config functions via client.config

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.save")

COMMAND_DEFINITIONS = [
    {
        "name": "save",
        "handler": "handle_save_command",
        "help": {
            "usage": "/save",
            "description": "Saves the current client configuration to the INI file.",
            "aliases": []
        }
    }
]

async def handle_save_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /save command."""
    if client.config.save_current_config():
        await client.add_message(
            "Configuration saved to pyterm_irc_config.ini.",
            client.ui.colors.get("system", 0),
            context_name=client.context_manager.active_context_name or "Status",
        )
    else:
        await client.add_message(
            "Failed to save configuration.",
            client.ui.colors.get("error", 0),
            context_name=client.context_manager.active_context_name or "Status",
        )
