# commands/ui/status_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.ui.status")

COMMAND_DEFINITIONS = [
    {
        "name": "status",
        "handler": "handle_status_command",
        "help": {
            "usage": "/status",
            "description": "Switches to the Status window.",
            "aliases": []
        }
    }
]

def handle_status_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /status command"""
    client.context_manager.set_active_context("Status")
    client.ui_needs_update.set()
