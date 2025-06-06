import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.channel.kick")

COMMAND_DEFINITIONS = [
    {
        "name": "kick",
        "handler": "handle_kick_command",
        "help": {
            "usage": "/kick <nick> [reason]",
            "description": "Kicks a user from the current channel.",
            "aliases": ["k"]
        }
    }
]

def handle_kick_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /kick command"""
    help_data = client.script_manager.get_help_text_for_command("kick")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /kick <nick> [reason]"
    )
    parts = client.command_handler._ensure_args(
        args_str, usage_msg, num_expected_parts=1 # Ensures at least a nick is provided
    )
    if not parts:
        return

    kick_args = args_str.split(" ", 1)
    target = kick_args[0]
    reason = kick_args[1] if len(kick_args) > 1 else None

    current_active_context_name = client.context_manager.active_context_name or "Status"
    current_context = client.context_manager.get_context(current_active_context_name)

    if not current_context or current_context.type != "channel":
        client.add_message(
            "Not in a channel to kick from.",
            "error",
            context_name=current_active_context_name,
        )
        return

    channel_name = current_context.name
    kick_message = f"Kicking {target} from {channel_name}"
    if reason:
        kick_message += f" (Reason: {reason})"
    else:
        kick_message += "..."

    client.add_message(kick_message, "system", context_name=channel_name)

    if reason:
        client.network_handler.send_raw(
            f"KICK {channel_name} {target} :{reason}"
        )
    else:
        client.network_handler.send_raw(
            f"KICK {channel_name} {target}"
        )
