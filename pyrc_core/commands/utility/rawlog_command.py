# commands/utility/rawlog_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.rawlog")

COMMAND_DEFINITIONS = [
    {
        "name": "rawlog",
        "handler": "handle_rawlog_command",
        "help": {
            "usage": "/rawlog [on|off|toggle]",
            "description": "Toggles or sets the display of raw IRC messages in the Status window.",
            "aliases": []
        }
    }
]

def handle_rawlog_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /rawlog [on|off|toggle] command."""
    help_data = client.script_manager.get_help_text_for_command("rawlog")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /rawlog [on|off|toggle]"
    )
    arg = args_str.strip().lower()
    current_status = client.show_raw_log_in_ui
    active_context_name = client.context_manager.active_context_name or "Status"

    if arg == "on":
        client.show_raw_log_in_ui = True
    elif arg == "off":
        client.show_raw_log_in_ui = False
    elif arg == "toggle" or not arg:
        client.show_raw_log_in_ui = not current_status
    else:
        client.add_message(
            usage_msg,
            "error",
            context_name=active_context_name,
        )
        return

    feedback_action = "enabled" if client.show_raw_log_in_ui else "disabled"
    client.add_message(
        f"Raw IRC message logging to UI {feedback_action}.",
        "system",
        context_name=active_context_name,
    )
