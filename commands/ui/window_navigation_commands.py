# commands/ui/window_navigation_commands.py
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.ui.window_nav")

COMMAND_DEFINITIONS = [
    {
        "name": "nextwindow",
        "handler": "handle_next_window_command",
        "help": {
            "usage": "/nextwindow",
            "description": "Switches to the next window in the cycle.",
            "aliases": ["next"]
        }
    },
    {
        "name": "prevwindow",
        "handler": "handle_prev_window_command",
        "help": {
            "usage": "/prevwindow",
            "description": "Switches to the previous window in the cycle.",
            "aliases": ["prev"]
        }
    },
    {
        "name": "window",
        "handler": "handle_window_command",
        "help": {
            "usage": "/window <name|number>",
            "description": "Switches to the window specified by name or number.",
            "aliases": ["win"]
        }
    },
    {
        "name": "prevchannel",
        "handler": "handle_prev_channel_command",
        "help": {
            "usage": "/prevchannel",
            "description": "Switches to the previously active channel or Status window.",
            "aliases": ["pc"]
        }
    }
]

def handle_next_window_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /next or /nextwindow command"""
    client.switch_active_context("next")

def handle_prev_window_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /prev or /prevwindow command"""
    client.switch_active_context("prev")

def handle_window_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /window or /win command"""
    help_data = client.script_manager.get_help_text_for_command("window")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /window <name|number>"
    )
    parts = client.command_handler._ensure_args(args_str, usage_msg)
    if not parts:
        return
    target = parts[0]
    client.switch_active_context(target)


def handle_prev_channel_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /prevchannel command"""
    client.switch_active_channel("prev")
