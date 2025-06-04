import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.channel.topic")

COMMAND_DEFINITIONS = [
    {
        "name": "topic",
        "handler": "handle_topic_command",
        "help": {
            "usage": "/topic [<channel>] [<new_topic>]",
            "description": "Views or sets the topic for a channel. If no channel is specified, uses the current channel. If no new_topic is specified, views the current topic.",
            "aliases": ["t"]
        }
    }
]

def handle_topic_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /topic command."""
    topic_parts = args_str.split(" ", 1)
    current_active_ctx_name = client.context_manager.active_context_name
    target_channel_ctx_name = current_active_ctx_name
    new_topic = None

    if not target_channel_ctx_name:
        client.add_message(
            "No active window to get/set topic from.",
            "error",
            context_name="Status",
        )
        return

    current_context = client.context_manager.get_context(
        target_channel_ctx_name
    )

    # Determine target channel and new topic based on arguments
    if not args_str.strip(): # /topic (no args)
        if not (current_context and current_context.type == "channel"):
            client.add_message(
                "Not in a channel to get topic. Current window is not a channel.",
                "error",
                context_name=target_channel_ctx_name,
            )
            return
        # Request current topic for the active channel
        # target_channel_ctx_name is already set to current_active_ctx_name
        # new_topic remains None
    elif topic_parts[0].startswith("#"): # /topic #channel [new_topic]
        target_channel_ctx_name = topic_parts[0]
        if len(topic_parts) > 1:
            new_topic = topic_parts[1]
        # If no new_topic, it's a request for topic of specified channel
    else: # /topic new topic for current channel
        if not (current_context and current_context.type == "channel"):
            client.add_message(
                "Not in a channel to set topic. Current window is not a channel.",
                "error",
                context_name=target_channel_ctx_name,
            )
            return
        # target_channel_ctx_name is already current_active_ctx_name
        new_topic = args_str # The whole args_str is the new topic

    # Ensure context exists if a channel name was explicitly provided or derived
    if target_channel_ctx_name.startswith("#"):
        # This will create if not exists, or get existing.
        # For /topic, if we're just viewing, context might not exist yet locally if not joined.
        # If setting, server will handle if channel doesn't exist or we can't set.
        # The original logic did create_context, so we maintain that.
        client.context_manager.create_context(
            target_channel_ctx_name, context_type="channel"
        )

    if new_topic is not None:
        client.network_handler.send_raw(
            f"TOPIC {target_channel_ctx_name} :{new_topic}"
        )
        client.add_message(
            f"Attempting to set topic for {target_channel_ctx_name}...",
            "system",
            context_name=target_channel_ctx_name # Feedback in the target channel
        )
    else:
        # Requesting the topic
        client.network_handler.send_raw(f"TOPIC {target_channel_ctx_name}")
        client.add_message(
            f"Requesting topic for {target_channel_ctx_name}...",
            "system",
            context_name=target_channel_ctx_name # Feedback in the target channel
        )
