# commands/channel/invite_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.channel.invite")

COMMAND_DEFINITIONS = [
    {
        "name": "invite",
        "handler": "handle_invite_command",
        "help": {
            "usage": "/invite <nickname> [channel]",
            "description": "Invites <nickname> to [channel] or the current channel if none is specified.",
            "aliases": ["inv"]
        }
    }
]

async def handle_invite_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /invite command."""
    parts = args_str.split()
    active_context_name = client.context_manager.active_context_name or "Status"

    if not parts: # Need at least a nickname
        await client.add_message("Usage: /invite <nickname> [channel]", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    nick_to_invite = parts[0]
    target_channel: Optional[str] = None

    if len(parts) > 1:
        target_channel = parts[1]
    elif active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
        target_channel = active_context_name
    else:
        await client.add_message("Usage: /invite <nickname> [channel] - No channel specified or active.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    if not target_channel: # Should be caught
        await client.add_message("Error: No channel specified for /invite.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    normalized_channel = client.context_manager._normalize_context_name(target_channel)

    # It's good practice to be in the channel you're inviting someone to,
    # but the server will enforce this.
    # context = client.context_manager.get_context(normalized_channel)
    # if not context or context.type != "channel" or context.join_status != ChannelJoinStatus.JOINED:
    #     await client.add_message(f"You must be in {normalized_channel} to invite someone.", client.ui.colors.get("warning",0), context_name=active_context_name)
    #     return

    await client.network_handler.send_raw(f"INVITE {nick_to_invite} {normalized_channel}")
    logger.info(f"Sent INVITE command for {nick_to_invite} to {normalized_channel}.")
    await client.add_status_message(f"Inviting {nick_to_invite} to {normalized_channel}...", "system")
    # Server responses (RPL_INVITING, ERR_USERONCHANNEL, etc.) handled by numeric handlers.
