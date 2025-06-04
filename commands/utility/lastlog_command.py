# commands/utility/lastlog_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.lastlog")

COMMAND_DEFINITIONS = [
    {
        "name": "lastlog",
        "handler": "handle_lastlog_command",
        "help": {
            "usage": "/lastlog <pattern>",
            "description": "Searches the message history of the active window for lines containing <pattern>.",
            "aliases": []
        }
    }
]

def handle_lastlog_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /lastlog command."""
    help_data = client.script_manager.get_help_text_for_command("lastlog")
    usage_msg = help_data["help_text"] if help_data else "Usage: /lastlog <pattern>"
    active_context_obj = client.context_manager.get_active_context()
    active_context_name = client.context_manager.active_context_name or "Status"

    system_color_key = "system"
    error_color_key = "error"

    if not args_str.strip():
        client.add_message(
            usage_msg,
            error_color_key,
            context_name=active_context_name,
        )
        return

    pattern = args_str.strip()

    if not active_context_obj:
        client.add_message(
            "Cannot use /lastlog: No active window.",
            error_color_key,
            context_name="Status", # Error regarding no active window goes to Status
        )
        return

    client.add_message(
        f'Searching lastlog for "{pattern}" in {active_context_obj.name}...',
        system_color_key,
        context_name=active_context_name, # Feedback in the window being searched
    )

    found_matches = False
    messages_to_search = list(active_context_obj.messages)

    for msg_data in messages_to_search:
        if isinstance(msg_data, tuple) and len(msg_data) >= 2:
            msg_text, color_info = msg_data[0], msg_data[1]
            if isinstance(msg_text, str) and pattern.lower() in msg_text.lower():
                client.add_message(
                    f"[LastLog] {msg_text}",
                    color_info,
                    context_name=active_context_name,
                )
                found_matches = True
        else:
            logger.warning(f"Unexpected message format in log buffer for {active_context_name}: {msg_data}")

    if not found_matches:
        client.add_message(
            f'No matches found for "{pattern}" in the current log.',
            system_color_key,
            context_name=active_context_name,
        )
    client.add_message(
        "End of lastlog search.", system_color_key, context_name=active_context_name
    )
