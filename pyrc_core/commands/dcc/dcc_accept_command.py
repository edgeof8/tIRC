# pyrc_core/commands/dcc/dcc_accept_command.py
import argparse
import logging
from typing import TYPE_CHECKING, List, Dict, Any

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.accept")

COMMAND_NAME = "accept"
COMMAND_ALIASES: List[str] = []
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc accept <nick> \"<filename>\" <ip> <port> <size>",
    "description": "Accepts an incoming DCC SEND offer from a specified nickname for a given filename, IP, port, and size.",
    "aliases": "None"
}

async def _handle_dcc_error(client_logic: 'IRCClient_Logic', message: str, context_name: str, log_level: int = logging.ERROR, exc_info: bool = False):
    """Helper to log and display DCC command errors."""
    logger.log(log_level, message, exc_info=exc_info)
    await client_logic.add_message(text=message, color_attr=client_logic.ui.colors["error"], context_name=context_name)

async def _ensure_dcc_context(client_logic: 'IRCClient_Logic', dcc_context_name: str):
    """Helper to ensure DCC context is active."""
    if client_logic.context_manager.active_context_name != dcc_context_name:
        await client_logic.switch_active_context(dcc_context_name)

async def handle_dcc_accept_command(client_logic: 'IRCClient_Logic', cmd_args: List[str], active_context_name: str, dcc_context_name: str):
    """
    Handles the /dcc accept command.
    Parses arguments and attempts to accept an incoming DCC offer.
    """
    dcc_m = client_logic.dcc_manager
    if not dcc_m:
        await _handle_dcc_error(client_logic, f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
        return
    if not dcc_m.dcc_config.enabled:
        await _handle_dcc_error(client_logic, f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
        return
    parser = argparse.ArgumentParser(prog=f"/dcc {COMMAND_NAME}", add_help=False)
    parser.add_argument("nick", help="Sender's nickname.")
    parser.add_argument("filename", help="Filename offered (can be quoted).")
    parser.add_argument("ip", help="Sender's IP address.")
    parser.add_argument("port", type=int, help="Sender's port number.")
    parser.add_argument("size", type=int, help="File size in bytes.")

    try:
        parsed_args = parser.parse_args(cmd_args)
        nick = parsed_args.nick
        filename = parsed_args.filename.strip('"')
        ip_str = parsed_args.ip
        port = parsed_args.port
        filesize = parsed_args.size

        if not (0 < port <= 65535):
            await _handle_dcc_error(client_logic, f"Invalid port: {port}. Must be 1-65535.", dcc_context_name)
            return
        if filesize < 0:
            await _handle_dcc_error(client_logic, f"Invalid filesize: {filesize}. Must be non-negative.", dcc_context_name)
            return

        # Get transfer ID using the helper function
        transfer_id = dcc_m.receive_manager.get_transfer_id_by_args(nick, filename, ip_str, port, filesize)
        if not transfer_id:
            await _handle_dcc_error(client_logic, f"No pending DCC transfer found for {nick} '{filename}' at {ip_str}:{port} ({filesize} bytes). It may have expired.", dcc_context_name)
            return

        # Accept the DCC offer using the transfer ID
        success = await dcc_m.receive_manager.accept_dcc_offer(transfer_id)
        if success:
            await client_logic.add_message(text=f"Accepted DCC SEND from {nick} for '{filename}' (ID: {transfer_id[:8]}). Receiving...", color_attr=client_logic.ui.colors["system"], context_name=dcc_context_name)
        else:
            await _handle_dcc_error(client_logic, f"DCC ACCEPT for '{filename}' from {nick} failed. Check logs for details.", dcc_context_name)

        await _ensure_dcc_context(client_logic, dcc_context_name)

    except argparse.ArgumentError as e:
        await _handle_dcc_error(client_logic, f"Error: {e.message}\nUsage: {COMMAND_HELP['usage']}", active_context_name, log_level=logging.WARNING)
    except SystemExit:
        await client_logic.add_message(text=f"Usage: {COMMAND_HELP['usage']}", color_attr=client_logic.ui.colors["error"], context_name=active_context_name)
    except Exception as e:
        await _handle_dcc_error(client_logic, f"Error processing /dcc {COMMAND_NAME}: {e}. Please check format.", dcc_context_name, exc_info=True)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_function": handle_dcc_accept_command
    }
