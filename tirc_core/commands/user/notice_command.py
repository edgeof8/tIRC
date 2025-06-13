# commands/user/notice_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.user.notice")

COMMAND_DEFINITIONS = [
    {
        "name": "notice",
        "handler": "handle_notice_command",
        "help": {
            "usage": "/notice <target> <message>",
            "description": "Sends a NOTICE to a user or channel.",
            "aliases": ["no"]
        }
    }
]

async def handle_notice_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /notice <target> <message> command."""
    parts = args_str.split(" ", 1)
    active_context_name = client.context_manager.active_context_name or "Status"

    if len(parts) < 2:
        await client.add_message(
            "Usage: /notice <target> <message>",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    target, message = parts[0], parts[1]

    if not target or not message:
        await client.add_message(
            "Usage: /notice <target> <message>",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    await client.network_handler.send_raw(f"NOTICE {target} :{message}")

    # Echo the sent notice to the Status window or a relevant context
    # Notices are typically less intrusive, so Status window is often appropriate.
    # However, if sending to a channel or user we have a window for, could echo there.
    # For simplicity, let's echo to Status for now, or to the target if it's an open query/channel.

    echo_context_name = "Status" # Default
    normalized_target = client.context_manager._normalize_context_name(target)
    if client.context_manager.get_context(normalized_target):
        echo_context_name = normalized_target


    client_nick = client.nick or "Me" # Fallback
    # Display format for sent notices might differ, e.g., -> Target: Message
    formatted_notice = f"-> {target}: {message}"

    await client.add_message(
        formatted_notice,
        client.ui.colors.get("my_notice_message", client.ui.colors.get("notice_message", 0)), # Use a specific color for self-sent notices
        context_name=echo_context_name,
        is_privmsg_or_notice=True # Indicate it's a user-generated message
    )
    logger.info(f"Sent NOTICE to {target}: {message}")
