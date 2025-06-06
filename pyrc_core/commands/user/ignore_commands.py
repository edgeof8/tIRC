# commands/user/ignore_commands.py
import logging
from typing import TYPE_CHECKING, Optional, List
# Access config functions and properties via client.config

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.ignore")

COMMAND_DEFINITIONS = [
    {
        "name": "ignore",
        "handler": "handle_ignore_command",
        "help": {
            "usage": "/ignore <nick|hostmask>",
            "description": "Adds a user/hostmask to the ignore list. Simple nicks are converted to nick!*@*.",
            "aliases": []
        }
    },
    {
        "name": "unignore",
        "handler": "handle_unignore_command",
        "help": {
            "usage": "/unignore <nick|hostmask>",
            "description": "Removes a user/hostmask from the ignore list. Tries to match exact pattern or derived nick!*@*.",
            "aliases": []
        }
    },
    {
        "name": "listignores",
        "handler": "handle_listignores_command",
        "help": {
            "usage": "/listignores",
            "description": "Lists all currently ignored patterns.",
            "aliases": ["ignores"]
        }
    }
]

def handle_ignore_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /ignore command."""
    help_data = client.script_manager.get_help_text_for_command("ignore")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /ignore <nick|hostmask>"
    )
    active_context_name = client.context_manager.active_context_name or "Status"
    system_color_key = "system"
    warning_color_key = "warning"

    parts = client.command_handler._ensure_args(args_str, usage_msg)
    if not parts:
        return

    pattern_to_ignore = parts[0]
    original_arg = pattern_to_ignore # Keep original for messages

    if "!" not in pattern_to_ignore and "@" not in pattern_to_ignore:
        if "*" not in pattern_to_ignore and "?" not in pattern_to_ignore:
            interpreted_pattern = f"{pattern_to_ignore}!*@*"
            client.add_message(
                f"Interpreting '{original_arg}' as hostmask pattern: '{interpreted_pattern}'",
                system_color_key,
                context_name=active_context_name,
            )
            pattern_to_ignore = interpreted_pattern

    if client.config.add_ignore_pattern(pattern_to_ignore): # add_ignore_pattern now handles lowercasing
        client.add_message(
            f"Now ignoring: {pattern_to_ignore}",
            system_color_key,
            context_name=active_context_name,
        )
    else:
        client.add_message(
            f"Pattern '{pattern_to_ignore}' is already in the ignore list or is empty.",
            warning_color_key,
            context_name=active_context_name,
        )

def handle_unignore_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /unignore command."""
    help_data = client.script_manager.get_help_text_for_command("unignore")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /unignore <nick|hostmask>"
    )
    active_context_name = client.context_manager.active_context_name or "Status"
    system_color_key = "system"
    error_color_key = "error"

    parts = client.command_handler._ensure_args(args_str, usage_msg)
    if not parts:
        return

    pattern_to_unignore_arg = parts[0]
    # remove_ignore_pattern handles lowercasing.
    # We attempt to remove the exact arg, and if that fails, a derived hostmask.

    removed = False
    if client.config.remove_ignore_pattern(pattern_to_unignore_arg):
        client.add_message(
            f"Removed from ignore list: {pattern_to_unignore_arg.lower()}", # Show what was actually removed
            system_color_key,
            context_name=active_context_name,
        )
        removed = True
    else:
        # If simple nick and not a pattern, try derived hostmask
        if "!" not in pattern_to_unignore_arg and "@" not in pattern_to_unignore_arg and \
           "*" not in pattern_to_unignore_arg and "?" not in pattern_to_unignore_arg:
            derived_pattern = f"{pattern_to_unignore_arg.lower()}!*@*"
            if client.config.remove_ignore_pattern(derived_pattern):
                client.add_message(
                    f"Removed derived hostmask from ignore list: {derived_pattern}",
                    system_color_key,
                    context_name=active_context_name,
                )
                removed = True

    if not removed:
        client.add_message(
            f"Pattern '{pattern_to_unignore_arg}' (or its derived hostmask) not found in ignore list.",
            error_color_key,
            context_name=active_context_name,
        )

def handle_listignores_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /listignores command."""
    active_context_name = client.context_manager.active_context_name or "Status"
    system_color_key = "system"

    if not client.config.ignored_patterns:
        client.add_message(
            "Ignore list is empty.",
            system_color_key,
            context_name=active_context_name,
        )
        return

    client.add_message(
        "Current ignore patterns:",
        system_color_key,
        context_name=active_context_name,
    )
    for pattern in sorted(list(client.config.ignored_patterns)):
        client.add_message(
            f"- {pattern}",
            system_color_key,
            context_name=active_context_name,
        )
