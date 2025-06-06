# commands/user/notice_command.py
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.notice")

def handle_notice_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /notice command"""
    help_data = client.script_manager.get_help_text_for_command("notice")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /notice <target> <message>"
    )
    # _ensure_args is part of CommandHandler, accessed via client.command_handler
    parts = client.command_handler._ensure_args(args_str, usage_msg, num_expected_parts=2)
    if not parts:
        return
    target = parts[0]
    message = parts[1]
    client.network_handler.send_raw(f"NOTICE {target} :{message}")
    # Client-side display of the notice is handled by MessageHandler when the server confirms/sends it.
