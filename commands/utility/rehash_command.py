# commands/utility/rehash_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.rehash")

def handle_rehash_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /rehash command."""
    if hasattr(client, "handle_rehash_config"):
        client.handle_rehash_config()
        # Feedback message is handled within IRCClient_Logic.handle_rehash_config
    else:
        logger.error("IRCClient_Logic does not have handle_rehash_config method.")
        client.add_message(
            "Error: Rehash functionality not fully implemented in client logic.",
            "error", # Semantic color key
            context_name=client.context_manager.active_context_name or "Status",
        )
