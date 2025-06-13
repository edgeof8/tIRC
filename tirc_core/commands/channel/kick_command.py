# commands/channel/kick_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.channel.kick")

COMMAND_DEFINITIONS = [
    {
        "name": "kick",
        "handler": "handle_kick_command",
        "help": {
            "usage": "/kick <nickname> [channel] [reason]",
            "description": "Kicks <nickname> from [channel] (or current channel) with an optional [reason].",
            "aliases": ["k"]
        }
    }
]

async def handle_kick_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /kick command."""
    parts = args_str.split(" ", 2) # Max 3 parts: nick, optional_channel, optional_reason
    active_context_name = client.context_manager.active_context_name or "Status"

    if not parts or not parts[0]: # Need at least a nickname
        await client.add_message("Usage: /kick <nickname> [channel] [reason]", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    nick_to_kick = parts[0]
    target_channel: Optional[str] = None
    reason: Optional[str] = None

    if len(parts) == 1: # /kick <nick> (use current channel)
        if active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel = active_context_name
        else:
            await client.add_message("Usage: /kick <nickname> [channel] [reason] - No channel specified or active.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return
    elif len(parts) >= 2:
        # /kick <nick> <channel_or_reason> [reason_if_channel_given]
        second_arg = parts[1]
        if second_arg.startswith(("#", "&", "!", "+")) or client.context_manager.get_context(client.context_manager._normalize_context_name(second_arg)):
            target_channel = second_arg
            if len(parts) > 2:
                reason = parts[2]
        elif active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel = active_context_name
            reason = " ".join(parts[1:]) # All remaining parts are reason
        else:
            await client.add_message("Usage: /kick <nickname> [channel] [reason] - Could not determine channel.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

    if not target_channel: # Should be caught
        await client.add_message("Error: No channel specified for /kick.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    normalized_channel = client.context_manager._normalize_context_name(target_channel)

    # Ensure channel context exists (though server will ultimately validate channel)
    if not client.context_manager.get_context(normalized_channel):
        # Let server handle if channel doesn't exist on client side.
        pass

    command = f"KICK {normalized_channel} {nick_to_kick}"
    if reason:
        command += f" :{reason}"
    else: # IRC KICK command requires a reason, even if it's just the kicker's nick.
          # Some servers default it, but best to provide one.
        command += f" :{client.nick or nick_to_kick}" # Use own nick as default reason

    await client.network_handler.send_raw(command)
    logger.info(f"Sent KICK command for {nick_to_kick} from {normalized_channel}. Reason: {reason or (client.nick or nick_to_kick)}")
    await client.add_status_message(f"Attempting to kick {nick_to_kick} from {normalized_channel}...", "system")
    # Server will send KICK message back, handled by membership_handlers.
