# commands/channel/join_command.py
import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.channel.join")

COMMAND_DEFINITIONS = [
    {
        "name": "join",
        "handler": "handle_join_command",
        "help": {
            "usage": "/join <channel>[,<channel2>...] [key[,key2...]]",
            "description": "Joins one or more IRC channels. Keys can be provided for channels that require them.",
            "aliases": ["j"]
        }
    }
]

async def handle_join_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /join command."""
    parts = args_str.split()
    active_context_name = client.context_manager.active_context_name or "Status"

    if not parts:
        await client.add_message("Usage: /join <channel>[,<channel2>...] [key[,key2...]]", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    channels_str = parts[0]
    keys_str = parts[1] if len(parts) > 1 else None

    raw_channels_to_join: List[str] = [ch.strip() for ch in channels_str.split(',') if ch.strip()]
    keys: List[Optional[str]] = [k.strip() for k in keys_str.split(',')] if keys_str else []

    if not raw_channels_to_join:
        await client.add_message("No valid channel names provided.", client.ui.colors.get("error_message", 0), context_name=active_context_name)
        return

    processed_channels_to_join: List[str] = []
    for ch_name_raw in raw_channels_to_join:
        # Ensure channel name starts with a valid prefix, default to '#'
        if not ch_name_raw.startswith(("#", "&", "!", "+")):
            processed_channels_to_join.append("#" + ch_name_raw)
        else:
            processed_channels_to_join.append(ch_name_raw)

    # Normalize after ensuring prefix, for consistent storage by ContextManager
    channels_to_join_normalized: List[str] = [client.context_manager._normalize_context_name(ch) for ch in processed_channels_to_join]


    # Construct the JOIN command string using the processed (prefixed) names
    join_cmd_channels = ",".join(processed_channels_to_join)
    join_cmd_keys = ",".join(k for k in keys if k) if any(keys) else "" # Join keys if any are non-empty

    command = f"JOIN {join_cmd_channels}"
    if join_cmd_keys:
        command += f" {join_cmd_keys}"

    await client.network_handler.send_raw(command)
    logger.info(f"Sent JOIN command for channels: {join_cmd_channels}, Keys: {join_cmd_keys or 'N/A'}")

    # Create contexts for these channels immediately if they don't exist,
    # so messages related to joining (like MOTD parts if it's the first join) can be buffered.
    # The actual join status will be updated by server messages.
    # Use the normalized names for context creation and status messages.
    first_channel_joined_for_switch: Optional[str] = None
    for i, chan_name_normalized in enumerate(channels_to_join_normalized):
        # Use the corresponding processed (prefixed) name for the status message
        display_chan_name = processed_channels_to_join[i] if i < len(processed_channels_to_join) else chan_name_normalized

        client.context_manager.create_context(chan_name_normalized, context_type="channel")
        await client.add_status_message(f"Attempting to join {display_chan_name}...", "system_message")
        if first_channel_joined_for_switch is None:
            first_channel_joined_for_switch = chan_name_normalized

    # Switch to the first channel being joined.
    if first_channel_joined_for_switch:
        # Ensure the context exists before trying to switch (it should, as we just created it)
        if client.context_manager.get_context(first_channel_joined_for_switch):
            logger.info(f"Switching active context to newly joined channel: {first_channel_joined_for_switch}")
            await client.view_manager.switch_active_context(first_channel_joined_for_switch)
        else:
            logger.warning(f"Could not switch to {first_channel_joined_for_switch}, context not found after creation attempt.")
