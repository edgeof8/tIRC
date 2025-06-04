import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.channel.simple_modes")

COMMAND_DEFINITIONS = [
    {
        "name": "op",
        "handler": "handle_op_command",
        "help": {
            "usage": "/op <nick>",
            "description": "Grants operator status to <nick> in the current channel.",
            "aliases": ["o"]
        }
    },
    {
        "name": "deop",
        "handler": "handle_deop_command",
        "help": {
            "usage": "/deop <nick>",
            "description": "Removes operator status from <nick> in the current channel.",
            "aliases": ["do"]
        }
    },
    {
        "name": "voice",
        "handler": "handle_voice_command",
        "help": {
            "usage": "/voice <nick>",
            "description": "Grants voice status to <nick> in the current channel.",
            "aliases": ["v"]
        }
    },
    {
        "name": "devoice",
        "handler": "handle_devoice_command",
        "help": {
            "usage": "/devoice <nick>",
            "description": "Removes voice status from <nick> in the current channel.",
            "aliases": ["dv"]
        }
    }
]

def _handle_simple_mode_change(
    client: "IRCClient_Logic",
    args_str: str,
    mode_char: str,
    action: str,
    usage_key: str,
    feedback_verb: str,
):
    """Helper for /op, /deop, /voice, /devoice"""
    active_ctx = client.context_manager.get_active_context()
    if not active_ctx or active_ctx.type != "channel":
        client.add_message(
            "This command can only be used in a channel.",
            "error",
            context_name="Status",
        )
        return
    channel_name = active_ctx.name

    help_data = client.script_manager.get_help_text_for_command(usage_key)
    usage_msg = (
        help_data["help_text"] if help_data else f"Usage: /{usage_key} <nick>"
    )
    parts = client.command_handler._ensure_args(args_str, usage_msg)
    if not parts:
        return
    nick = parts[0]

    client.network_handler.send_raw(
        f"MODE {channel_name} {action}{mode_char} {nick}"
    )
    client.add_message(
        f"{feedback_verb} {nick} in {channel_name}...",
        "system",
        context_name=channel_name,
    )

def handle_op_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /op command"""
    _handle_simple_mode_change(client, args_str, "o", "+", "op", "Opping")

def handle_deop_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /deop command"""
    _handle_simple_mode_change(client, args_str, "o", "-", "deop", "De-opping")

def handle_voice_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /voice command"""
    _handle_simple_mode_change(client, args_str, "v", "+", "voice", "Voicing")

def handle_devoice_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /devoice command"""
    _handle_simple_mode_change(client, args_str, "v", "-", "devoice", "De-voicing")
