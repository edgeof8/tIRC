# commands/user/away_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.away")

def handle_away_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /away command"""
    if not args_str:
        client.network_handler.send_raw("AWAY")
    else:
        client.network_handler.send_raw(f"AWAY :{args_str}")
    # No specific client message needed here, server will send numerics
