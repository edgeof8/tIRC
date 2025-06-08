# pyrc_core/commands/dcc/dcc_get_command.py # Pylance re-evaluation
import argparse
import logging
from typing import TYPE_CHECKING, List, Dict, Any

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.get")

COMMAND_NAME = "get"
COMMAND_ALIASES: List[str] = []
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc get <nick> \"<filename>\" --token <token>",
    "description": "Accepts a passive (reverse) DCC SEND offer from a specified nickname and filename, using a provided token.",
    "aliases": "None"
}

async def _handle_dcc_error(client_logic: 'IRCClient_Logic', message: str, context_name: str, log_level: int = logging.ERROR, exc_info: bool = False):
    """Helper to log and display DCC command errors."""
    logger.log(log_level, message, exc_info=exc_info)
    await client_logic.add_message(message, client_logic.ui.colors["error"], context_name=context_name)

async def _ensure_dcc_context(client_logic: 'IRCClient_Logic', dcc_context_name: str):
    """Helper to ensure DCC context is active."""
    if client_logic.context_manager.active_context_name != dcc_context_name:
        await client_logic.switch_active_context(dcc_context_name)

async def handle_dcc_get_command(client_logic: 'IRCClient_Logic', cmd_args: List[str], active_context_name: str, dcc_context_name: str):
    """
    Handles the /dcc get command.
    Parses arguments and attempts to accept a passive DCC offer.
    """
    dcc_m = client_logic.dcc_manager
    if not dcc_m:
        await _handle_dcc_error(client_logic, f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
        return
    if not dcc_m.dcc_config.get("enabled"):
        await _handle_dcc_error(client_logic, f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
        return

    parser = argparse.ArgumentParser(prog=f"/dcc {COMMAND_NAME}", add_help=False)
    parser.add_argument("nick", help="Sender's nickname.")
    parser.add_argument("filename", help="Filename offered (can be quoted).")
    parser.add_argument("--token", required=True, help="The token provided with the passive offer.")

    try:
        parsed_args = parser.parse_args(cmd_args)
        nick = parsed_args.nick
        filename = parsed_args.filename.strip('"')
        token = parsed_args.token

        if hasattr(dcc_m, "accept_passive_offer_by_token"):
            result = dcc_m.accept_passive_offer_by_token(nick, filename, token)
            if result.get("success"):
                await client_logic.add_message(f"Attempting to GET '{filename}' from {nick} via passive DCC (ID: {result.get('transfer_id', 'N/A')[:8]}).", client_logic.ui.colors["system"], context_name=dcc_context_name)
            else:
                await _handle_dcc_error(client_logic, f"DCC GET for '{filename}' from {nick} failed: {result.get('error', 'Unknown error')}", dcc_context_name)
        else:
            await _handle_dcc_error(client_logic, "DCC GET command logic not fully implemented in DCCManager.", dcc_context_name)

        await _ensure_dcc_context(client_logic, dcc_context_name)

    except argparse.ArgumentError as e:
        await _handle_dcc_error(client_logic, f"Error: {e.message}\nUsage: {COMMAND_HELP['usage']}", active_context_name, log_level=logging.WARNING)
    except SystemExit:
        await client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", client_logic.ui.colors["error"], context_name=active_context_name)
    except Exception as e:
        await _handle_dcc_error(client_logic, f"Error processing /dcc {COMMAND_NAME}: {e}. Usage: {COMMAND_HELP['usage']}", dcc_context_name, exc_info=True)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_function": handle_dcc_get_command
    }
