# commands/utility/clear_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.clear")

COMMAND_DEFINITIONS = [
    {
        "name": "clear",
        "handler": "handle_clear_command",
        "help": {
            "usage": "/clear",
            "description": "Clears the message history of the current active window.",
            "aliases": ["c"]
        }
    }
]

async def handle_clear_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /clear command"""
    logger.info(f"--- handle_clear_command EXECUTING for active context: {client.context_manager.active_context_name} ---")
    active_ctx = client.context_manager.get_active_context()
    if active_ctx:
        logger.info(f"Attempting to clear messages for context: {active_ctx.name}. Current message count: {len(active_ctx.messages)}")
        active_ctx.messages.clear()
        client.ui_needs_update.set() # Signal UI to refresh
        logger.info(f"Messages cleared for context: {active_ctx.name}. New message count: {len(active_ctx.messages)}")
        # No confirmation message is typically sent to the UI for /clear itself.
    else:
        logger.warning("/clear command executed but no active context found.")
        await client.add_message("No active window to clear.", client.ui.colors.get("error", 0), context_name="Status")
