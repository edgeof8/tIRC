# commands/user/query_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.user.query")

COMMAND_DEFINITIONS = [
    {
        "name": "query",
        "handler": "handle_query_command",
        "help": {
            "usage": "/query <nickname> [message]",
            "description": "Opens a new query window with the specified nickname and optionally sends a message.",
            "aliases": ["q"]
        }
    }
]

async def handle_query_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /query command."""
    parts = args_str.split(" ", 1)
    target_nick = parts[0]
    message_to_send = parts[1] if len(parts) > 1 else None
    active_context_name = client.context_manager.active_context_name or "Status"

    if not target_nick:
        await client.add_message(
            "Usage: /query <nickname> [message]",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    # Normalize the target nickname (queries are typically case-insensitive in IRC context names)
    target_nick_normalized = client.context_manager._normalize_context_name(target_nick)

    # Create the query context if it doesn't exist
    if not client.context_manager.get_context(target_nick_normalized):
        client.context_manager.create_context(target_nick_normalized, context_type="query")
        await client.add_status_message(f"Opened query window with {target_nick_normalized}", "system")

    # Switch to the query context
    # ClientViewManager's switch_active_context handles this
    await client.view_manager.switch_active_context(target_nick_normalized) # Corrected call

    # If a message was provided, send it
    if message_to_send:
        await client.network_handler.send_raw(f"PRIVMSG {target_nick_normalized} :{message_to_send}")
        # Add the sent message to the query context for local display
        client_own_nick = client.nick or "Me" # Fallback if nick is not yet set
        formatted_sent_message = f"<{client_own_nick}> {message_to_send}"
        await client.add_message(
            formatted_sent_message,
            client.ui.colors.get("my_message", 0), # Use 'my_message' color
            context_name=target_nick_normalized # Add to the query context
        )

    client.ui_needs_update.set() # Ensure UI updates
