# commands/user/query_command.py
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.query")

COMMAND_DEFINITIONS = [
    {
        "name": "query",
        "handler": "handle_query_command",
        "help": {
            "usage": "/query <nick> [message]",
            "description": "Opens a query window with <nick> and optionally sends an initial message.",
            "aliases": []
        }
    }
]

def handle_query_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /query command"""
    help_data = client.script_manager.get_help_text_for_command("query")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /query <nick> [message]"
    )
    parts = client.command_handler._ensure_args(args_str, usage_msg, num_expected_parts=1)
    if not parts:
        return

    query_parts = args_str.split(" ", 1)
    target_nick = query_parts[0]
    message = query_parts[1] if len(query_parts) > 1 else None

    client.context_manager.create_context(target_nick, context_type="query")
    client.context_manager.set_active_context(target_nick) # Switch to the new query window

    if message:
        client.network_handler.send_raw(f"PRIVMSG {target_nick} :{message}")
