import logging
from typing import TYPE_CHECKING, Optional, List

from pyrc_core.context_manager import ChannelJoinStatus, Context

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.channel.join")

COMMAND_DEFINITIONS = [
    {
        "name": "join",
        "handler": "handle_join_command",
        "help": {
            "usage": "/join <channel> [#channel2 ...]",
            "description": "Joins the specified IRC channel(s).",
            "aliases": ["j"]
        }
    }
]

async def handle_join_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /join command"""
    help_data = client.script_manager.get_help_text_for_command("join")
    usage_msg = help_data["help_text"] if help_data else "Usage: /join <channel>"
    parts = await client.command_handler._ensure_args(args_str, usage_msg)
    if not parts:
        return
    channel_name_arg = parts[0]
    target_channel_name = (
        channel_name_arg
        if channel_name_arg.startswith("#")
        else f"#{channel_name_arg}"
    )

    client.last_join_command_target = target_channel_name

    ctx = client.context_manager.get_context(target_channel_name)
    if not ctx:
        client.context_manager.create_context(
            target_channel_name,
            context_type="channel",
            initial_join_status_for_channel=ChannelJoinStatus.JOIN_COMMAND_SENT,
        )
        logger.info(
            f"/join: Created context for {target_channel_name} with status JOIN_COMMAND_SENT."
        )
    elif ctx.type == "channel":
        if hasattr(ctx, "join_status"): # Check if context is a channel context with join_status
            ctx.join_status = ChannelJoinStatus.JOIN_COMMAND_SENT
        logger.info(
            f"/join: Updated context for {target_channel_name} to status JOIN_COMMAND_SENT."
        )
    else:
        await client.add_message(
            f"Cannot join '{target_channel_name}': A non-channel window with this name already exists.",
            client.ui.colors["error"], # Use semantic color key
            context_name=client.context_manager.active_context_name or "Status",
        )
        return

    await client.network_handler.send_raw(f"JOIN {target_channel_name}")
    # Set the new channel as the active context and trigger UI update
    client.context_manager.set_active_context(target_channel_name)
    client.ui_needs_update.set()
    logger.info(f"/join: Set active context to {target_channel_name} and requested UI update.")
