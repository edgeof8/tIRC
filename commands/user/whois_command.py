# commands/user/whois_command.py
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.whois")

def handle_whois_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /whois command"""
    help_data = client.script_manager.get_help_text_for_command("whois")
    usage_msg = help_data["help_text"] if help_data else "Usage: /whois <nick>"

    # _ensure_args is part of CommandHandler, accessed via client.command_handler
    parts = client.command_handler._ensure_args(args_str, usage_msg)
    if not parts:
        return
    target = parts[0]
    client.network_handler.send_raw(f"WHOIS {target}")
