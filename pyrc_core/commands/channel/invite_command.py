import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.channel.invite")

COMMAND_DEFINITIONS = [
    {
        "name": "invite",
        "handler": "handle_invite_command",
        "help": {
            "usage": "/invite <nick> [channel]",
            "description": "Invites a user to a channel. If no channel is specified, uses the current channel.",
            "aliases": ["i"]
        }
    }
]

def handle_invite_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /invite command"""
    help_data = client.script_manager.get_help_text_for_command("invite")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /invite <nick> [channel]"
    )
    parts = client.command_handler._ensure_args(
        args_str, usage_msg, num_expected_parts=1 # Ensures at least a nick is provided
    )
    if not parts:
        return

    invite_args = args_str.split(" ", 1)
    nick = invite_args[0]
    channel_arg = invite_args[1] if len(invite_args) > 1 else None

    # Determine the target channel
    if channel_arg:
        channel_to_invite_to = channel_arg
        if not channel_to_invite_to.startswith("#"):
            channel_to_invite_to = f"#{channel_to_invite_to}"
    else:
        active_ctx_name = client.context_manager.active_context_name
        active_ctx = client.context_manager.get_context(active_ctx_name or "")
        if active_ctx and active_ctx.type == "channel":
            channel_to_invite_to = active_ctx.name
        else:
            client.add_message(
                "No channel specified and current window is not a channel.",
                "error",
                context_name="Status",
            )
            return

    # Final validation of channel_to_invite_to
    if not channel_to_invite_to.startswith("#"):
        client.add_message(
            f"Cannot invite to '{channel_to_invite_to}'. Not a valid channel.",
            "error",
            context_name="Status", # Or active_ctx_name if preferred for this error
        )
        return

    client.add_message(
        f"Inviting {nick} to {channel_to_invite_to}...",
        "system",
        context_name= client.context_manager.active_context_name or "Status"
    )
    client.network_handler.send_raw(f"INVITE {nick} {channel_to_invite_to}")
