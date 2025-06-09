import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.information.list")

COMMAND_DEFINITIONS = [
    {
        "name": "list",
        "handler": "handle_list_command",
        "help": {
            "usage": "/list [pattern]",
            "description": "Lists channels on the server, optionally filtering by a pattern. Results appear in a new temporary window.",
            "aliases": []
        }
    }
]

async def handle_list_command(client: "IRCClient_Logic", args_str: str):
    pattern = args_str.strip()

    unique_list_context_name = f"##LIST_RESULTS_{time.time_ns()}##"
    logger.debug(
        f"Generated unique context name for /list: {unique_list_context_name}"
    )

    created = client.context_manager.create_context(
        unique_list_context_name, context_type="list_results"
    )

    if created:
        logger.info(
            f"Created temporary context '{unique_list_context_name}' for /list results."
        )
        client.active_list_context_name = unique_list_context_name
        logger.debug(
            f"Set active_list_context_name to {client.active_list_context_name}"
        )

        # Try to switch focus to the new temporary context.
        # Note: switch_active_context now returns bool, but original logic didn't use it directly
        # for changing behavior beyond logging.
        # The command_handler.py version of switch_active_context might have side effects like messages.
        # For now, just calling it as it was.
        await client.switch_active_context(unique_list_context_name)
        # The original logic for client.add_message on failure to switch is complex
        # and tied to the UIManager. For now, we assume switch_active_context handles
        # user feedback internally if it fails, or that the UI updates regardless.
        # If specific error messaging is needed here for failed switch, it would be:
        # if not client.context_manager.get_context(unique_list_context_name) or \
        #    client.context_manager.active_context_name != unique_list_context_name:
        #    client.add_message("Error: Could not switch to list results window.", "error", context_name="Status")

    else:
        logger.error(
            f"Failed to create temporary context '{unique_list_context_name}' for /list. Output will go to Status."
        )
        client.active_list_context_name = None
        await client.add_message(
            "Error: Could not create list results window. Output will appear in Status.",
            client.ui.colors["error"],
            context_name="Status"
        )

    await client.network_handler.send_raw(f"LIST {pattern}" if pattern else "LIST")
