# commands/channel/mode_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.channel.mode")

COMMAND_DEFINITIONS = [
    {
        "name": "mode",
        "handler": "handle_mode_command",
        "help": {
            "usage": "/mode [<channel|nickname>] [<modes> [<parameters>...]]",
            "description": "Sets or views channel or user modes. If no arguments, views modes for current channel. If only channel/nick, views modes for that target.",
            "aliases": []
        }
    }
]

async def handle_mode_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /mode command."""
    parts = args_str.split()
    active_context_name = client.context_manager.active_context_name or "Status"

    target: Optional[str] = None
    modes_and_params: Optional[str] = None

    if not parts: # /mode (current channel)
        if active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target = active_context_name
        else:
            await client.add_message("Usage: /mode [<channel|nickname>] [<modes> [<parameters>...]] - No active channel to view modes for.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return
    elif len(parts) == 1: # /mode <target> (view modes for target)
        target = parts[0]
    else: # /mode <target> <modes_and_params>
        target = parts[0]
        modes_and_params = " ".join(parts[1:])

    if not target: # Should be caught
        await client.add_message("Error: No target specified for /mode.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    # Normalize target if it's a channel
    # User nicks are case-insensitive on some networks but preserved on others.
    # The server will handle nick normalization.
    if target.startswith(("#", "&", "!", "+")):
        normalized_target = client.context_manager._normalize_context_name(target)
    else:
        normalized_target = target # Assume it's a nickname, server handles case

    command = f"MODE {normalized_target}"
    if modes_and_params:
        command += f" {modes_and_params}"

    await client.network_handler.send_raw(command)
    action = "Setting" if modes_and_params else "Viewing"
    logger.info(f"Sent MODE command for {normalized_target}. Action: {action}. Params: {modes_and_params or 'N/A'}")
    await client.add_status_message(f"{action} modes for {normalized_target}...", "system")
    # Server responses (RPL_CHANNELMODEIS, RPL_UMODEIS, MODE messages) are handled by numeric/command handlers.
