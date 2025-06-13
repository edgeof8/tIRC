# commands/ui/window_navigation_commands.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.ui.window_nav")

COMMAND_DEFINITIONS = [
    {
        "name": "window",
        "handler": "handle_window_command",
        "help": {
            "usage": "/window <name|number>",
            "description": "Switches to the specified window by name or number (1-based).",
            "aliases": ["win", "w"]
        }
    },
    {
        "name": "nextwindow",
        "handler": "handle_next_window_command",
        "help": {
            "usage": "/nextwindow",
            "description": "Switches to the next window in the list.",
            "aliases": ["next", "n"] # 'n' is common for next
        }
    },
    {
        "name": "prevwindow",
        "handler": "handle_prev_window_command",
        "help": {
            "usage": "/prevwindow",
            "description": "Switches to the previous window in the list.",
            "aliases": ["prev", "p"] # 'p' is common for previous
        }
    },
    {
        "name": "prevchannel", # Or consider a more generic "prevcontext"
        "handler": "handle_prev_channel_command",
        "help": {
            "usage": "/prevchannel",
            "description": "Switches to the previously active channel or Status window.",
            "aliases": ["pc"]
        }
    }
]

async def handle_window_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /window command."""
    target_window_identifier = args_str.strip()
    if not target_window_identifier:
        await client.add_status_message(
            "Usage: /window <name|number>", "error" # Corrected color_key
        )
        return

    if client.is_headless:
        await client.add_status_message("Window commands are not available in headless mode.", "error")
        return

    # ClientViewManager's switch_active_context handles name, number, or partial name.
    await client.view_manager.switch_active_context(target_window_identifier)
    # ui_needs_update should be set by switch_active_context if successful

async def handle_next_window_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /nextwindow command."""
    if client.is_headless:
        await client.add_status_message("Window commands are not available in headless mode.", "error")
        return
    await client.view_manager.switch_active_context("next")

async def handle_prev_window_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /prevwindow command."""
    if client.is_headless:
        await client.add_status_message("Window commands are not available in headless mode.", "error")
        return
    await client.view_manager.switch_active_context("prev")

async def handle_prev_channel_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /prevchannel command (switches between channels and Status)."""
    if client.is_headless:
        await client.add_status_message("Window commands are not available in headless mode.", "error")
        return
    # ClientViewManager has switch_active_channel for this logic
    await client.view_manager.switch_active_channel("prev")
