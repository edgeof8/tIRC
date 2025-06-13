# commands/user/whois_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.user.whois")

COMMAND_DEFINITIONS = [
    {
        "name": "whois",
        "handler": "handle_whois_command",
        "help": {
            "usage": "/whois <nickname>",
            "description": "Retrieves WHOIS information for the specified nickname.",
            "aliases": ["w"] # Note: /w is also often /window. Consider if this alias is problematic.
        }
    }
]

async def handle_whois_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /whois command."""
    nick_to_whois = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"

    if not nick_to_whois:
        await client.add_message(
            "Usage: /whois <nickname>",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    if not client.network_handler.connected:
        await client.add_status_message("Not connected to any server.", "error")
        return

    await client.network_handler.send_raw(f"WHOIS {nick_to_whois}")
    await client.add_status_message(f"Requesting WHOIS information for {nick_to_whois}...", "system")
    # Server will respond with RPL_WHOISUSER (311), RPL_WHOISSERVER (312), etc.,
    # and RPL_ENDOFWHOIS (318). These are handled by numeric handlers.
    # Messages will be added to the active_context_name by the numeric handlers.
