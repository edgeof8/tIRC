import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.channel.cyclechannel")

COMMAND_DEFINITIONS = [
    {
        "name": "cyclechannel",
        "handler": "handle_cyclechannel_command",
        "help": {
            "usage": "/cyclechannel",
            "description": "Parts and then rejoins the current channel.",
            "aliases": ["cc"]
        }
    }
]

async def handle_cyclechannel_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /cyclechannel command"""
    # args_str is not used for /cyclechannel, but kept for consistency with handler signature

    current_active_context_name = client.context_manager.active_context_name or "Status"
    current_context = client.context_manager.get_context(current_active_context_name)

    if not current_context or current_context.type != "channel":
        await client.add_message(
            "Not in a channel to cycle.",
            client.ui.colors["error"],
            context_name=current_active_context_name,
        )
        return

    channel = current_context.name

    await client.add_message(
        f"Cycling channel {channel}...",
        client.ui.colors["system"],
        context_name=channel
    )
    await client.network_handler.send_raw(f"PART {channel}")
    await client.network_handler.send_raw(f"JOIN {channel}")
