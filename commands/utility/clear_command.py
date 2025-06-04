# commands/utility/clear_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.clear")

def handle_clear_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /clear command"""
    current_context = client.context_manager.get_active_context()
    if current_context:
        current_context.messages.clear()
        client.ui_needs_update.set()
    # No message is sent on /clear, it just clears the local buffer.
