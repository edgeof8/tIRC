# commands/ui/userlist_scroll_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.ui.userlist_scroll")

COMMAND_DEFINITIONS = [
    {
        "name": "userlistscroll",
        "handler": "handle_userlist_scroll_command",
        "help": {
            "usage": "/userlistscroll [up|down|pageup|pagedown|top|bottom|offset]",
            "description": "Scrolls the user list in the current channel window.",
            "aliases": ["u"]
        }
    }
]

def handle_userlist_scroll_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /userlistscroll or /u command"""
    active_ctx = client.context_manager.get_active_context()
    active_context_name = client.context_manager.active_context_name or "Status"
    error_color_key = "error"

    if not active_ctx or active_ctx.type != "channel":
        client.add_message(
            "User list scroll is only available in channel windows.",
            error_color_key,
            context_name=active_context_name,
        )
        return

    if not args_str: # Default to pagedown if no args
        client.ui.scroll_user_list("pagedown")
    else:
        try:
            arg_lower = args_str.lower()
            if arg_lower in ["up", "down", "pageup", "pagedown", "top", "bottom"]:
                client.ui.scroll_user_list(arg_lower)
            else: # Try to parse as number
                offset = int(args_str)
                if offset > 0:
                    client.ui.scroll_user_list("down", lines_arg=offset)
                elif offset < 0:
                    client.ui.scroll_user_list("up", lines_arg=abs(offset))
                # If offset is 0, do nothing or treat as error? Current scroll_user_list might handle it.
        except ValueError:
            client.add_message(
                f"Invalid argument for userlistscroll: '{args_str}'. Use up, down, pageup, pagedown, top, bottom, or a number.",
                error_color_key,
                context_name=active_ctx.name,
            )
    client.ui_needs_update.set()
