# commands/dcc/dcc_accept_command.py
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.dcc.accept")

COMMAND_DEFINITIONS = [
    {
        "name": "dcc_accept", # Changed from "accept" to be DCC specific
        "handler": "handle_dcc_accept_command",
        "help": {
            "usage": "/dcc_accept <nick> \"<filename>\" <ip_int_or_str> <port> <size>",
            "description": "Accepts an active DCC SEND offer. Use quotes for filenames with spaces. IP can be integer or dotted decimal.",
            "aliases": ["dccaccept"]
        }
    }
]

async def handle_dcc_accept_command(client: "IRCClient_Logic", args_str: str):
    """
    Handles the /dcc_accept <nick> "<filename>" <ip> <port> <size> command.
    This is for ACTIVE DCC offers where the sender is listening.
    The client (receiver) will connect to the sender.
    """
    parts: List[str] = []
    # active_context_name is defined later, but error messages might need it sooner.
    # Let's define it early. If no context, default to "Status".
    # This is a bit tricky as active_context_name is used before full parsing.
    # For these early error messages, sending to "Status" is safest.
    status_context_for_early_errors = "Status"


    # Custom parser for <nick> "<filename>" <ip> <port> <size>
    temp_args_str = args_str.strip()
    if not temp_args_str:
        await client.add_message("Usage: /dcc_accept <nick> \"<filename>\" <ip> <port> <size>", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
        return

    first_space_idx = temp_args_str.find(" ")
    if first_space_idx == -1: # Only nick provided
        await client.add_message("Usage: /dcc_accept <nick> \"<filename>\" <ip> <port> <size>", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
        return

    parts.append(temp_args_str[:first_space_idx]) # Nick
    remaining_after_nick = temp_args_str[first_space_idx:].strip()

    if not remaining_after_nick.startswith('"'):
        await client.add_message("Filename must be enclosed in quotes.", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
        return

    end_quote_idx = -1
    try:
        end_quote_idx = remaining_after_nick.index('"', 1)
    except ValueError:
        await client.add_message("Malformed filename in quotes.", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
        return

    parts.append(remaining_after_nick[1:end_quote_idx]) # Filename without quotes
    remaining_after_filename = remaining_after_nick[end_quote_idx+1:].strip()

    parts.extend(remaining_after_filename.split())

    # Now define active_context_name for later messages
    active_context_name = client.context_manager.active_context_name or "Status"
    dcc_ui_context = client.dcc_manager.dcc_ui_context_name if client.dcc_manager else "Status"

    if len(parts) != 5:
        await client.add_message("Usage: /dcc_accept <nick> \"<filename>\" <ip> <port> <size>", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    peer_nick, filename, ip_str, port_str, size_str = parts

    try:
        port = int(port_str)
        size = int(size_str)
    except ValueError:
        await client.add_message("Port and size must be integers.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    if not client.dcc_manager or not client.config.dcc.enabled:
        await client.add_message("DCC system is not enabled.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    transfer = await client.dcc_manager.accept_active_offer(peer_nick, filename, ip_str, port, size)

    if transfer:
        await client.add_message(
            f"Attempting to accept active DCC SEND for '{filename}' from {peer_nick} at {ip_str}:{port}. Transfer ID: {transfer.id}",
            client.ui.colors.get("success", 0),
            context_name=dcc_ui_context
        )
        if client.context_manager.active_context_name != dcc_ui_context:
            await client.view_manager.switch_active_context(dcc_ui_context)
    else:
        await client.add_message(
            f"Failed to process /dcc_accept for '{filename}' from {peer_nick}.",
            client.ui.colors.get("error", 0),
            context_name=active_context_name
        )
