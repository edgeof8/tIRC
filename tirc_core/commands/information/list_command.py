# commands/information/list_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.information.list")

COMMAND_DEFINITIONS = [
    {
        "name": "list",
        "handler": "handle_list_command",
        "help": {
            "usage": "/list [pattern]",
            "description": "Lists channels on the server, optionally filtered by a pattern.",
            "aliases": []
        }
    }
]

async def handle_list_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /list command."""
    pattern = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"

    # The LIST command itself doesn't create a new persistent context.
    # Results are typically shown in the Status window or a temporary "Server List" window.
    # For simplicity, we'll show it in the Status window.
    # A more advanced implementation might create a temporary, non-joinable context.

    list_results_context = "Status" # Or a dedicated "ServerList" context if one exists/is created

    if pattern:
        await client.network_handler.send_raw(f"LIST {pattern}")
        await client.add_message(f"Requesting channel list matching '{pattern}'...", client.ui.colors.get("system", 0), context_name=list_results_context)
    else:
        await client.network_handler.send_raw("LIST")
        await client.add_message("Requesting full channel list...", client.ui.colors.get("system", 0), context_name=list_results_context)

    # If the results are shown in a different context than active, switch to it.
    if active_context_name != list_results_context:
        # This assumes 'list_results_context' is a valid, existing context name.
        # If "ServerList" is used, ensure it's created by ContextManager.
        await client.view_manager.switch_active_context(list_results_context) # Corrected call

    # Server will respond with RPL_LISTSTART (321), RPL_LIST (322), RPL_LISTEND (323).
    # These are handled by irc_numeric_handlers.py, which should add messages to the appropriate context.
