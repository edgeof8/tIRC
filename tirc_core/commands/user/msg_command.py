# commands/user/msg_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.user.msg")

COMMAND_DEFINITIONS = [
    {
        "name": "msg",
        "handler": "handle_msg_command",
        "help": {
            "usage": "/msg <target> <message>",
            "description": "Sends a private message to a user or a message to a channel.",
            "aliases": ["m", "say"]
        }
    }
]

async def handle_msg_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /msg <target> <message> command."""
    parts = args_str.split(" ", 1)
    active_context_name = client.context_manager.active_context_name or "Status"

    if len(parts) < 2:
        await client.add_message(
            "Usage: /msg <target> <message>",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    target, message = parts[0], parts[1]

    if not target or not message:
        await client.add_message(
            "Usage: /msg <target> <message>",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    await client.network_handler.send_raw(f"PRIVMSG {target} :{message}")

    # Echo the sent message to the appropriate context
    # If target is a channel, echo to that channel's context.
    # If target is a user (query), echo to that user's query context.
    # The query context should be created if it doesn't exist.

    echo_context_name = target
    is_channel_message = target.startswith(("#", "&", "!", "+"))

    if not is_channel_message: # It's a query
        # Ensure query context exists. ContextManager normalizes the name.
        client.context_manager.create_context(target, context_type="query")
        # The name stored in ContextManager might be normalized (e.g., lowercase)
        # We should use the normalized name for adding the message.
        normalized_target = client.context_manager._normalize_context_name(target)
        echo_context_name = normalized_target


    # Add the message to the local UI for display, formatted with nick
    client_nick = client.nick or "Me" # Fallback to "Me" if nick is somehow None
    formatted_line = f"<{client_nick}> {message}"

    # Determine color based on whether it's a channel message or query
    # Using "my_message" color for all self-sent messages for consistency
    color_pair_id = client.ui.colors.get("my_message", client.ui.colors.get("default", 0))


    await client.add_message(
        formatted_line,
        color_pair_id,
        context_name=echo_context_name,
        is_privmsg_or_notice=True # Indicate it's a user-generated message
    )
    logger.info(f"Sent PRIVMSG to {target}: {message}")
