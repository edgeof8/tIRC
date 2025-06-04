import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.channel.ban")

COMMAND_DEFINITIONS = [
    {
        "name": "ban",
        "handler": "handle_ban_command",
        "help": {
            "usage": "/ban <nick|hostmask>",
            "description": "Bans a user or hostmask from the current channel.",
            "aliases": []
        }
    },
    {
        "name": "unban",
        "handler": "handle_unban_command",
        "help": {
            "usage": "/unban <hostmask>",
            "description": "Removes a ban (specified by hostmask) from the current channel.",
            "aliases": []
        }
    }
]

def handle_ban_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /ban command"""
    active_ctx = client.context_manager.get_active_context()
    if not active_ctx or active_ctx.type != "channel":
        client.add_message(
            "This command can only be used in a channel.",
            "error",
            context_name="Status",
        )
        return
    channel_name = active_ctx.name

    help_data = client.script_manager.get_help_text_for_command("ban")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /ban <nick|hostmask>"
    )
    parts = client.command_handler._ensure_args(args_str, usage_msg)
    if not parts:
        return
    target_spec = parts[0]

    client.network_handler.send_raw(f"MODE {channel_name} +b {target_spec}")
    client.add_message(
        f"Banning {target_spec} from {channel_name}...",
        "system",
        context_name=channel_name,
    )

def handle_unban_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /unban command"""
    active_ctx = client.context_manager.get_active_context()
    if not active_ctx or active_ctx.type != "channel":
        client.add_message(
            "This command can only be used in a channel.",
            "error",
            context_name="Status",
        )
        return
    channel_name = active_ctx.name

    help_data = client.script_manager.get_help_text_for_command("unban")
    usage_msg = help_data["help_text"] if help_data else "Usage: /unban <hostmask>"
    parts = client.command_handler._ensure_args(args_str, usage_msg)
    if not parts:
        return
    target_spec = parts[0]

    client.network_handler.send_raw(f"MODE {channel_name} -b {target_spec}")
    client.add_message(
        f"Unbanning {target_spec} from {channel_name}...",
        "system",
        context_name=channel_name,
    )
