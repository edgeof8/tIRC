# commands/channel/topic_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.channel.topic")

COMMAND_DEFINITIONS = [
    {
        "name": "topic",
        "handler": "handle_topic_command",
        "help": {
            "usage": "/topic [<channel>] [<new_topic>]",
            "description": "Views or sets the topic for a channel. If no channel is given, uses the active channel. If no topic is given, views the current topic.",
            "aliases": ["t"]
        }
    }
]

async def handle_topic_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /topic command."""
    parts = args_str.split(" ", 1)
    target_channel_arg: Optional[str] = None
    new_topic_arg: Optional[str] = None
    active_context_name = client.context_manager.active_context_name or "Status"

    if not args_str: # /topic (view current channel's topic)
        if active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel_arg = active_context_name
        else:
            await client.add_message("Usage: /topic [<channel>] [<new_topic>] - No active channel to view topic for.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return
    elif " " not in args_str and (args_str.startswith(("#", "&", "!", "+")) or client.context_manager.get_context(args_str)):
        # /topic #channel (view specified channel's topic)
        target_channel_arg = args_str
    elif " " not in args_str and not (args_str.startswith(("#", "&", "!", "+")) or client.context_manager.get_context(args_str)):
        # /topic new topic for current channel
        if active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel_arg = active_context_name
            new_topic_arg = args_str # The whole string is the topic
        else:
            await client.add_message("Usage: /topic [<channel>] [<new_topic>] - No active channel to set topic for.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return
    else: # /topic #channel new topic OR /topic new topic (if current is channel)
        target_channel_arg = parts[0]
        new_topic_arg = parts[1] if len(parts) > 1 else None
        # If target_channel_arg is not a channel name, assume it's part of the topic for current channel
        if not (target_channel_arg.startswith(("#", "&", "!", "+")) or client.context_manager.get_context(target_channel_arg)):
            if active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
                new_topic_arg = args_str # Whole string is topic
                target_channel_arg = active_context_name
            else: # Cannot determine target channel
                await client.add_message("Usage: /topic [<channel>] [<new_topic>] - Invalid channel or no active channel.", client.ui.colors.get("error", 0), context_name=active_context_name)
                return

    if not target_channel_arg: # Should be caught by logic above, but defensive
        await client.add_message("Could not determine target channel for /topic.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    normalized_channel = client.context_manager._normalize_context_name(target_channel_arg)
    context = client.context_manager.get_context(normalized_channel)

    if not context or context.type != "channel":
        await client.add_message(f"'{target_channel_arg}' is not a valid channel window.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    if new_topic_arg is not None: # Set topic
        await client.network_handler.send_raw(f"TOPIC {normalized_channel} :{new_topic_arg}")
        logger.info(f"Sent TOPIC command for {normalized_channel} with new topic: {new_topic_arg[:30]}...")
        # Server will send a TOPIC message back confirming the change, which will be displayed.
        # No local echo needed here for setting topic.
    else: # View topic
        await client.network_handler.send_raw(f"TOPIC {normalized_channel}")
        logger.info(f"Sent TOPIC command to view topic for {normalized_channel}.")
        # Server will respond with RPL_TOPIC (332) or RPL_NOTOPIC (331).
        # These are handled by numeric handlers and will display the topic.
