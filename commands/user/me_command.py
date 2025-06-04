# commands/user/me_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic
    from context_manager import ChannelJoinStatus

logger = logging.getLogger("pyrc.commands.user.me")

COMMAND_DEFINITIONS = [
    {
        "name": "me",
        "handler": "handle_me_command",
        "help": {
            "usage": "/me <action text>",
            "description": "Sends an action message (CTCP ACTION) to the current channel or query.",
            "aliases": []
        }
    }
]

def handle_me_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /me command"""
    help_data = client.script_manager.get_help_text_for_command("me")
    usage_msg = help_data["help_text"] if help_data else "Usage: /me <action>"
    error_color_key = "error"

    if not args_str:
        client.add_message(
            usage_msg,
            error_color_key,
            context_name=client.context_manager.active_context_name or "Status",
        )
        return

    action_text = args_str
    current_context_obj = client.context_manager.get_active_context()

    if not current_context_obj:
        client.add_message(
            "Cannot /me: No active context.",
            error_color_key,
            context_name="Status",
        )
        return

    from context_manager import ChannelJoinStatus

    if current_context_obj.type == "channel":
        if (
            hasattr(current_context_obj, "join_status")
            and current_context_obj.join_status == ChannelJoinStatus.FULLY_JOINED
        ):
            client.network_handler.send_raw(
                f"PRIVMSG {current_context_obj.name} :\x01ACTION {action_text}\x01"
            )
        else:
            client.add_message(
                f"Cannot /me: Channel {current_context_obj.name} not fully joined.",
                error_color_key,
                context_name=current_context_obj.name,
            )
    elif current_context_obj.type == "query":
        client.network_handler.send_raw(
            f"PRIVMSG {current_context_obj.name} :\x01ACTION {action_text}\x01"
        )
    else:
        client.add_message(
            "Cannot /me in this window.",
            error_color_key,
            context_name=current_context_obj.name,
        )
