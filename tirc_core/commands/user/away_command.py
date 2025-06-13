# commands/user/away_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.user.away")

COMMAND_DEFINITIONS = [
    {
        "name": "away",
        "handler": "handle_away_command",
        "help": {
            "usage": "/away [message]",
            "description": "Sets your away status. If no message is provided, marks you as no longer away.",
            "aliases": []
        }
    }
]

async def handle_away_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /away command."""
    message = args_str.strip()
    if message:
        await client.network_handler.send_raw(f"AWAY :{message}")
        logger.info(f"Set away status with message: {message}")
        # Some servers might send a RPL_NOWAWAY or similar, or just update WHOIS.
        # Client might need to track its own away status if server doesn't confirm.
        await client.add_status_message(f"You are now marked as away: {message}", "system_highlight")
    else:
        await client.network_handler.send_raw("AWAY")
        logger.info("Cleared away status.")
        await client.add_status_message("You are no longer marked as away.", "system_highlight")
