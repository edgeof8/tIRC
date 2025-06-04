# commands/utility/save_command.py
import logging
from typing import TYPE_CHECKING
from config import save_current_config

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

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

def handle_save_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /save command."""
    # args_str is not used for /save
    if save_current_config():
        client.add_message(
            "Configuration saved to pyterm_irc_config.ini.",
            "system",
            context_name=client.context_manager.active_context_name or "Status",
        )
    else:
        client.add_message(
            "Failed to save configuration.",
            "error",
            context_name=client.context_manager.active_context_name or "Status",
        )
