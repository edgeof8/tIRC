# commands/user/ignore_commands.py
import logging
from typing import TYPE_CHECKING, Optional, List
from config import add_ignore_pattern, remove_ignore_pattern, IGNORED_PATTERNS

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.ignore")

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
    # Ensure client.command_handler._ensure_args is used correctly
    # If it's just ensuring args_str is present, this is fine.
    # If it modifies pattern_to_ignore, ensure that's intended.

    # Logic for interpreting as hostmask pattern
    if "!" not in pattern_to_ignore and "@" not in pattern_to_ignore:
        if "*" not in pattern_to_ignore and "?" not in pattern_to_ignore:
            interpreted_pattern = f"{pattern_to_ignore}!*@*"
            client.add_message(
                f"Interpreting '{pattern_to_ignore}' as hostmask pattern: '{interpreted_pattern}'",
                system_color_key,
                context_name=active_context_name,
            )
            pattern_to_ignore = interpreted_pattern # Use the interpreted pattern

    if add_ignore_pattern(pattern_to_ignore):
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
    attempted_patterns = [pattern_to_unignore_arg.lower()]

    # Logic for deriving hostmask pattern if simple nick provided
    if "!" not in pattern_to_unignore_arg and "@" not in pattern_to_unignore_arg:
        if "*" not in pattern_to_unignore_arg and "?" not in pattern_to_unignore_arg:
            attempted_patterns.append(f"{pattern_to_unignore_arg.lower()}!*@*")

    removed = False
    for p_attempt in attempted_patterns:
        if remove_ignore_pattern(p_attempt):
            client.add_message(
                f"Removed from ignore list: {p_attempt}",
                system_color_key,
                context_name=active_context_name,
            )
            removed = True
            break

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

    if not IGNORED_PATTERNS:
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
    for pattern in sorted(list(IGNORED_PATTERNS)): # Ensure it's a list for sorting
        client.add_message(
            f"- {pattern}",
            system_color_key,
            context_name=active_context_name,
        )
