import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.information.whowas")

COMMAND_DEFINITIONS = [
    {
        "name": "whowas",
        "handler": "handle_whowas_command",
        "help": {
            "usage": "/whowas <nick> [count] [server]",
            "description": "Shows WHOWAS information for a user, providing historical data about a nickname.",
            "aliases": []
        }
    }
]

async def handle_whowas_command(client: "IRCClient_Logic", args_str: str):
    help_data = client.script_manager.get_help_text_for_command("whowas")
    usage_msg = (
        help_data["help_text"]
        if help_data
        else "Usage: /whowas <nick> [count] [server]"
    )
    parts = await client.command_handler._ensure_args(
        args_str,
        usage_msg,
        num_expected_parts=1,  # Ensure at least the nick is provided
    )
    if not parts:
        return

    split_args = args_str.strip().split(" ", 2)
    nick_arg = split_args[0]
    count_arg: Optional[str] = None
    target_server_arg: Optional[str] = None

    if len(split_args) > 1:
        if split_args[1].isdigit():
            count_arg = split_args[1]
            if len(split_args) > 2:
                target_server_arg = split_args[2]
        else:
            target_server_arg = split_args[1]

    command_parts = ["WHOWAS", nick_arg]
    if count_arg:
        command_parts.append(count_arg)
    if target_server_arg:
        command_parts.append(target_server_arg)

    await client.network_handler.send_raw(" ".join(command_parts))
