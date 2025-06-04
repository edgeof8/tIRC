# commands/user/query_command.py
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.query")

def handle_query_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /query command"""
    help_data = client.script_manager.get_help_text_for_command("query")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /query <nick> [message]"
    )

    # _ensure_args is part of CommandHandler, accessed via client.command_handler
    # For /query, we need at least one part (the target nick).
    parts = client.command_handler._ensure_args(args_str, usage_msg, num_expected_parts=1)
    if not parts:
        return

    # Unlike /msg, /query uses args_str directly to split, not the 'parts' from _ensure_args
    # because the message part is optional.
    query_parts = args_str.split(" ", 1)
    target_nick = query_parts[0]
    message = query_parts[1] if len(query_parts) > 1 else None

    client.context_manager.create_context(target_nick, context_type="query")
    client.context_manager.set_active_context(target_nick)

    if message:
        client.network_handler.send_raw(f"PRIVMSG {target_nick} :{message}")
        # Message display handled by server echo / MessageHandler
