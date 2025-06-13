# commands/user/ignore_commands.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.user.ignore")

COMMAND_DEFINITIONS = [
    {
        "name": "ignore",
        "handler": "handle_ignore_command",
        "help": {
            "usage": "/ignore <nick|hostmask>",
            "description": "Adds a user or hostmask to the ignore list. Wildcards * and ? can be used.",
            "aliases": []
        }
    },
    {
        "name": "unignore",
        "handler": "handle_unignore_command",
        "help": {
            "usage": "/unignore <nick|hostmask>",
            "description": "Removes a user or hostmask from the ignore list.",
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

async def handle_ignore_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /ignore command."""
    pattern = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"
    if not pattern:
        await client.add_message("Usage: /ignore <nick|hostmask>", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    if client.config.add_ignore_pattern(pattern):
        await client.add_message(f"Ignoring pattern: {pattern}", client.ui.colors.get("system", 0), context_name=active_context_name)
    else:
        await client.add_message(f"Pattern '{pattern}' is already ignored or could not be added.", client.ui.colors.get("warning", 0), context_name=active_context_name)

async def handle_unignore_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /unignore command."""
    pattern = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"
    if not pattern:
        await client.add_message("Usage: /unignore <nick|hostmask>", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    if client.config.remove_ignore_pattern(pattern):
        await client.add_message(f"Removed ignore pattern: {pattern}", client.ui.colors.get("system", 0), context_name=active_context_name)
    else:
        await client.add_message(f"Pattern '{pattern}' not found in ignore list.", client.ui.colors.get("warning", 0), context_name=active_context_name)

async def handle_listignores_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /listignores command."""
    active_context_name = client.context_manager.active_context_name or "Status"
    ignored_patterns = client.config.ignored_patterns
    if not ignored_patterns:
        await client.add_message("Ignore list is empty.", client.ui.colors.get("system", 0), context_name=active_context_name)
        return

    await client.add_message("--- Ignored Patterns ---", client.ui.colors.get("system_highlight", 0), context_name=active_context_name)
    for pattern in sorted(list(ignored_patterns)):
        await client.add_message(f"- {pattern}", client.ui.colors.get("system", 0), context_name=active_context_name)
