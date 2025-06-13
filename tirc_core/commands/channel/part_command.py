# commands/channel/part_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.channel.part")

COMMAND_DEFINITIONS = [
    {
        "name": "part",
        "handler": "handle_part_command",
        "help": {
            "usage": "/part [channel] [reason]",
            "description": "Leaves the specified channel or the current channel if none is given, with an optional reason.",
            "aliases": ["p", "leave"]
        }
    }
]

async def handle_part_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /part command."""
    parts = args_str.split(" ", 1) # Split only once to get channel and optional reason
    active_context_name = client.context_manager.active_context_name or "Status"

    target_channel: Optional[str] = None
    reason: Optional[str] = None

    if not args_str: # /part (current channel)
        if active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel = active_context_name
        else:
            await client.add_message("Usage: /part [channel] [reason] - No active channel to part from.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return
    else: # /part #channel [reason] OR /part reason (for current channel)
        first_arg = parts[0]
        if first_arg.startswith(("#", "&", "!", "+")) or client.context_manager.get_context(client.context_manager._normalize_context_name(first_arg)):
            target_channel = first_arg
            if len(parts) > 1:
                reason = parts[1]
        elif active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel = active_context_name
            reason = args_str # Whole string is reason
        else:
            await client.add_message("Usage: /part [channel] [reason] - Could not determine channel to part.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

    if not target_channel: # Should be caught by logic above
        await client.add_message("Error: No channel specified to part from.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    normalized_channel = client.context_manager._normalize_context_name(target_channel)
    context_to_part = client.context_manager.get_context(normalized_channel)

    if not context_to_part or context_to_part.type != "channel":
        await client.add_message(f"Cannot part '{target_channel}': Not a valid channel window.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    # Check if actually joined before sending PART
    # This check might be redundant if server handles it, but good for client-side feedback.
    # from tirc_core.context_manager import ChannelJoinStatus # Avoid top-level if only here
    # if context_to_part.join_status == ChannelJoinStatus.NOT_JOINED:
    #    await client.add_message(f"You are not in {normalized_channel}.", client.ui.colors.get("warning",0), context_name=active_context_name)
    #    # Still might want to close the window if it's open locally but not joined.
    #    # The /close command handles this better. For /part, assume we intend to send PART to server.

    command = f"PART {normalized_channel}"
    if reason:
        command += f" :{reason}"

    await client.network_handler.send_raw(command)
    logger.info(f"Sent PART command for {normalized_channel}. Reason: {reason or 'N/A'}")

    # The server will send a PART message back. The membership_handler._handle_part
    # will then update the UI, context state (join_status, remove user), and StateManager.
    # It will also handle closing the window if the view_manager is set to do so on self-part.
    # So, no direct UI message or context closing here is strictly needed after sending PART.
    # However, a small status message can be good feedback.
    await client.add_status_message(f"Attempting to part from {normalized_channel}...", "system")
