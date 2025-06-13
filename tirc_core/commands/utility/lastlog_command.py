# commands/utility/lastlog_command.py
import logging
from typing import TYPE_CHECKING, Optional, List, Tuple, Any

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.lastlog")

COMMAND_DEFINITIONS = [
    {
        "name": "lastlog",
        "handler": "handle_lastlog_command",
        "help": {
            "usage": "/lastlog [pattern]",
            "description": "Searches message history in the current window for a pattern. Shows recent messages if no pattern.",
            "aliases": ["ll"]
        }
    }
]

async def handle_lastlog_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /lastlog command."""
    active_ctx = client.context_manager.get_active_context()
    if not active_ctx:
        await client.add_message("No active window to search.", client.ui.colors.get("error", 0), context_name="Status")
        return

    pattern = args_str.strip()
    messages_to_display: List[Tuple[str, Any]] = []

    # Retrieve all messages for the context
    # The messages are stored as (text, color_pair_id)
    context_messages: Optional[List[Tuple[str, Any]]] = client.context_manager.get_context_messages_raw(active_ctx.name)

    if context_messages is None: # Should not happen if active_ctx exists
        await client.add_message(f"Could not retrieve messages for {active_ctx.name}.", client.ui.colors.get("error", 0), context_name=active_ctx.name)
        return

    if pattern:
        # Search for pattern
        for msg_text, color_pair_id in context_messages:
            if pattern.lower() in msg_text.lower():
                messages_to_display.append((msg_text, color_pair_id))
        if not messages_to_display:
            await client.add_message(f"No messages found matching '{pattern}' in {active_ctx.name}.", client.ui.colors.get("system", 0), context_name=active_ctx.name)
            return
        await client.add_message(f"--- Search results for '{pattern}' in {active_ctx.name} ---", client.ui.colors.get("system_highlight", 0), context_name=active_ctx.name)
    else:
        # Show last N messages (e.g., last 20)
        num_recent_messages = 20
        messages_to_display = list(context_messages)[-num_recent_messages:]
        if not messages_to_display:
            await client.add_message(f"No messages in {active_ctx.name}.", client.ui.colors.get("system", 0), context_name=active_ctx.name)
            return
        await client.add_message(f"--- Last {len(messages_to_display)} messages in {active_ctx.name} ---", client.ui.colors.get("system_highlight", 0), context_name=active_ctx.name)

    for msg_text, color_pair_id in messages_to_display:
        # When re-displaying, we pass the original color_pair_id.
        # The add_message method (and underlying UIManager) will handle converting this pair_id to a curses attribute.
        await client.add_message(msg_text, color_pair_id, context_name=active_ctx.name)
