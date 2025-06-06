# commands/user/away_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.away")

COMMAND_DEFINITIONS = [
    {
        "name": "away",
        "handler": "handle_away_command",
        "help": {
            "usage": "/away [message]",
            "description": "Sets your away status with an optional message. If no message is provided, marks you as no longer away.",
            "aliases": []
        }
    }
]

def handle_away_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /away command"""
    if not args_str:
        client.network_handler.send_raw("AWAY")
    else:
        client.network_handler.send_raw(f"AWAY :{args_str}")
