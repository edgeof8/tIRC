# commands/ui/userlist_scroll_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.ui.userlist_scroll")

COMMAND_DEFINITIONS = [
    {
        "name": "userlistscroll",
        "handler": "handle_userlist_scroll_command",
        "help": {
            "usage": "/userlistscroll <up|down|pageup|pagedown|top|bottom> [lines]",
            "description": "Scrolls the user list in the sidebar of the active channel window.",
            "aliases": ["us", "ulscroll", "scrollusers"]
        }
    }
]

async def handle_userlist_scroll_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /userlistscroll command."""
    if client.is_headless or not hasattr(client, 'ui'):
        await client.add_status_message("User list scrolling is not available in this mode.", "error")
        return

    parts = args_str.strip().lower().split()
    direction: Optional[str] = None
    lines: Optional[int] = None
    active_context_name = client.context_manager.active_context_name or "Status"

    if not parts:
        await client.add_status_message(
            "Usage: /userlistscroll <up|down|pageup|pagedown|top|bottom> [lines]", "error" # Corrected color_key
        )
        return

    direction = parts[0]
    valid_directions = ["up", "down", "pageup", "pagedown", "top", "bottom"]
    if direction not in valid_directions:
        await client.add_message(
            f"Invalid scroll direction '{direction}'. Must be one of: {', '.join(valid_directions)}.",
            client.ui.colors.get("error", 0),
            context_name=active_context_name
        )
        return

    if len(parts) > 1:
        try:
            lines = int(parts[1])
        except ValueError:
            await client.add_message(
                f"Invalid line count '{parts[1]}'. Must be an integer.",
                client.ui.colors.get("error", 0),
                context_name=active_context_name
            )
            return

    # The scroll_user_list method is on UIManager (client.ui) and is synchronous
    if hasattr(client.ui, 'scroll_user_list') and callable(client.ui.scroll_user_list):
        client.ui.scroll_user_list(direction, lines_arg=lines) # Removed await, lines_arg is Optional[int]
        # UIManager.scroll_user_list should set client.ui_needs_update.set()
    else:
        logger.warning("UIManager does not have a callable scroll_user_list method.")
        await client.add_status_message("UI component for user list scrolling not available.", "error")
