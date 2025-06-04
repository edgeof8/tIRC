# commands/ui/status_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.ui.status")

def handle_status_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /status command"""
    client.context_manager.set_active_context("Status")
    # No message is sent on /status, it just changes the active context.
