# commands/utility/rawlog_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.utility.rawlog")

COMMAND_DEFINITIONS = [
    {
        "name": "rawlog",
        "handler": "handle_rawlog_command",
        "help": { # This help will be used if CommandHandler's dynamic help isn't found
            "usage": "/rawlog [on|off|toggle]",
            "description": "Toggles or sets the display of raw IRC messages in the Status window.",
            "aliases": []
        }
    }
]

async def handle_rawlog_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /rawlog command."""
    arg = args_str.strip().lower()
    active_context_name = client.context_manager.active_context_name or "Status" # Ensure active_context_name is defined

    if arg == "on":
        client.show_raw_log_in_ui = True
        await client.add_status_message("Raw IRC message logging to UI: ON", "system")
    elif arg == "off":
        client.show_raw_log_in_ui = False
        await client.add_status_message("Raw IRC message logging to UI: OFF", "system")
    elif arg == "toggle" or not arg: # Toggle if "toggle" or no argument
        client.show_raw_log_in_ui = not client.show_raw_log_in_ui
        state_str = "ON" if client.show_raw_log_in_ui else "OFF"
        await client.add_status_message(f"Raw IRC message logging to UI: {state_str}", "system")
    else:
        # Use CommandHandler to get help, which now includes script command help
        help_info = client.command_handler.get_help_text_for_command("rawlog") # Corrected call
        usage = "/rawlog [on|off|toggle]" # Default usage
        if help_info and isinstance(help_info.get("help_info"), dict):
            usage = help_info["help_info"].get("usage", usage)
        elif help_info and help_info.get("help_text"): # if help_info is a string
             # Try to extract usage from the string if possible, or use default
            first_line = help_info["help_text"].split('\n')[0]
            if "usage:" in first_line.lower():
                usage = first_line

        await client.add_message(
            f"Invalid argument. Usage: {usage}",
            client.ui.colors.get("error", 0),
            context_name=active_context_name
        )
