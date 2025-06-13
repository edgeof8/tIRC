# commands/ui/status_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.ui.status")

COMMAND_DEFINITIONS = [
    {
        "name": "status",
        "handler": "handle_status_command",
        "help": {
            "usage": "/status",
            "description": "Switches to the Status window.",
            "aliases": []
        }
    }
]

async def handle_status_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /status command."""
    if client.is_headless:
        await client.add_status_message("Cannot switch to Status window in headless mode.", "error")
        return

    # Ensure Status context exists
    if not client.context_manager.get_context("Status"):
        client.context_manager.create_context("Status", context_type="status")
        logger.info("Status context was missing, created it.")

    await client.view_manager.switch_active_context("Status") # Corrected call
    # UIManager will handle ui_needs_update.set() if the context actually changes.
    # Or ClientViewManager.switch_active_context should set it.
    # Forcing an update here just in case.
    client.ui_needs_update.set()
