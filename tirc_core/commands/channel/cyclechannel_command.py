# commands/channel/cyclechannel_command.py
import logging
import asyncio # For asyncio.sleep
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.channel.cyclechannel")

COMMAND_DEFINITIONS = [
    {
        "name": "cycle", # Changed from "cyclechannel" for brevity, common IRC alias
        "handler": "handle_cycle_command",
        "help": {
            "usage": "/cycle [channel] [reason]",
            "description": "Parts and then rejoins the specified channel (or current channel) with an optional reason.",
            "aliases": ["hop", "rejoin", "cc"] # Common aliases
        }
    }
]

async def handle_cycle_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /cycle command."""
    parts = args_str.split(" ", 1) # Split only once to get channel and optional reason
    active_context_name = client.context_manager.active_context_name or "Status"

    target_channel: Optional[str] = None
    reason: Optional[str] = None # Reason for parting

    if not args_str: # /cycle (current channel)
        if active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel = active_context_name
        else:
            await client.add_message("Usage: /cycle [channel] [reason] - No active channel to cycle.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return
    else: # /cycle #channel [reason] OR /cycle reason (for current channel)
        first_arg = parts[0]
        if first_arg.startswith(("#", "&", "!", "+")) or client.context_manager.get_context(client.context_manager._normalize_context_name(first_arg)):
            target_channel = first_arg
            if len(parts) > 1:
                reason = parts[1]
        elif active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel = active_context_name
            reason = args_str # Whole string is reason
        else:
            await client.add_message("Usage: /cycle [channel] [reason] - Could not determine channel to cycle.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

    if not target_channel: # Should be caught
        await client.add_message("Error: No channel specified to cycle.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    normalized_channel = client.context_manager._normalize_context_name(target_channel)

    # Part command
    part_command_str = f"PART {normalized_channel}"
    if reason:
        part_command_str += f" :{reason}"

    await client.network_handler.send_raw(part_command_str)
    logger.info(f"Sent PART for /cycle on {normalized_channel}. Reason: {reason or 'N/A'}")
    await client.add_status_message(f"Parting from {normalized_channel} for cycle...", "system")

    # Wait a very short moment to allow PART to be processed by server/client logic
    # This is a heuristic. A more robust way might involve waiting for self-part event.
    await asyncio.sleep(0.5) # 500ms delay

    # Join command
    # Keys are not typically needed for a simple rejoin, but if the channel had a key,
    # the client might need to remember it. For /cycle, usually no key is re-specified.
    join_command_str = f"JOIN {normalized_channel}"
    await client.network_handler.send_raw(join_command_str)
    logger.info(f"Sent JOIN for /cycle on {normalized_channel}.")
    await client.add_status_message(f"Rejoining {normalized_channel}...", "system")

    # Context creation and status updates for join are handled by JOIN event handlers.
