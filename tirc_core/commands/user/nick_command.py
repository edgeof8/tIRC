# commands/user/nick_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.user.nick")

COMMAND_DEFINITIONS = [
    {
        "name": "nick",
        "handler": "handle_nick_command",
        "help": {
            "usage": "/nick <new_nickname>",
            "description": "Changes your nickname on the server.",
            "aliases": ["n"]
        }
    }
]

async def handle_nick_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /nick command."""
    new_nick = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"

    if not new_nick:
        await client.add_message(
            "Usage: /nick <new_nickname>",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    # Basic validation (e.g., length, allowed characters) could be added here
    # For now, assume server will validate.
    if client.network_handler.connected:
        # Store the nick we are attempting to change to, so ERR_NICKNAMEINUSE can check
        client.last_attempted_nick_change = new_nick
        await client.network_handler.send_raw(f"NICK {new_nick}")
        # Confirmation of nick change will come from the server via a NICK message.
        # The NICK message handler in state_change_handlers.py will update client.nick.
        logger.info(f"Sent NICK command to change to: {new_nick}")
        await client.add_status_message(f"Attempting to change nick to {new_nick}...", "system")
    else:
        await client.add_status_message("Not connected to any server.", "error")
