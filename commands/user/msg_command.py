# commands/user/msg_command.py
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.msg")

def handle_msg_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /msg command"""
    help_data = client.script_manager.get_help_text_for_command("msg")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /msg <nick> <message>"
    )
    # _ensure_args is part of CommandHandler, accessed via client.command_handler
    parts = client.command_handler._ensure_args(args_str, usage_msg, num_expected_parts=2)
    if not parts:
        return
    target = parts[0]
    message = parts[1]
    client.network_handler.send_raw(f"PRIVMSG {target} :{message}")
    # The sent message is typically displayed when the server echoes it back
    # or confirmed by the MessageHandler for PRIVMSG sent by the user.
