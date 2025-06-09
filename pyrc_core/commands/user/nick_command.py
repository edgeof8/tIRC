# commands/user/nick_command.py
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.nick")

async def handle_nick_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /nick command"""
    help_data = client.script_manager.get_help_text_for_command("nick")
    usage_msg = help_data["help_text"] if help_data else "Usage: /nick <newnick>"

    # _ensure_args is part of CommandHandler, accessed via client.command_handler
    parts = await client.command_handler._ensure_args(args_str, usage_msg)
    if not parts:
        return
    new_nick = parts[0]
    client.last_attempted_nick_change = new_nick
    await client.network_handler.send_raw(f"NICK {new_nick}")

COMMAND_DEFINITIONS = [
    {
        "name": "nick",
        "handler": "handle_nick_command",
        "help": {
            "usage": "/nick <newnick>",
            "description": "Changes your nickname on the IRC server.",
            "aliases": []
        }
    }
]
