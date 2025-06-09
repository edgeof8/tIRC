# pyrc_core/commands/dcc/dcc_send_command.py # Pylance re-evaluation
import argparse
import logging
from typing import TYPE_CHECKING, List, Dict, Any

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.send")

COMMAND_NAME = "send"
COMMAND_ALIASES: List[str] = []
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc send [-p] <nick> <filepath ...>",
    "description": "Initiates a DCC file transfer to a specified nickname. Use -p for passive (reverse) DCC.",
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

async def _handle_send_results(client_logic: 'IRCClient_Logic', results: Dict[str, Any], nick: str, dcc_context_name: str):
    """Processes and displays the results of the initiate_sends operation."""
    if results.get("transfers_started"):
        for transfer_info in results["transfers_started"]:
            fn = transfer_info.get("filename", "Unknown file")
            tid = transfer_info.get("transfer_id", "N/A")[:8]
            token_info = ""
            if transfer_info.get("passive") and transfer_info.get("token"): # Check for passive key
                token_info = f" (Passive Offer, token: {transfer_info.get('token')[:8]})"
            await client_logic.add_message(f"DCC SEND of '{fn}' to {nick} initiated (ID: {tid}){token_info}.", client_logic.ui.colors["system"], context_name=dcc_context_name)

    if results.get("files_queued"):
        for queue_info in results["files_queued"]:
            fn = queue_info.get("filename", "Unknown file")
            await client_logic.add_message(f"DCC SEND of '{fn}' to {nick} queued.", client_logic.ui.colors["system"], context_name=dcc_context_name)

    if results.get("errors"):
        for error_info in results["errors"]:
            fn = error_info.get("filename", "Unknown file")
            err = error_info.get("error", "Unknown error")
            await _handle_dcc_error(client_logic, f"DCC SEND for '{fn}' to {nick} failed: {err}", dcc_context_name)

    if not results.get("overall_success", True) and not results.get("transfers_started") and not results.get("files_queued") and not results.get("errors"):
         await _handle_dcc_error(client_logic, f"DCC SEND to {nick} failed: {results.get('error', 'No files processed or unknown error.')}", dcc_context_name)


async def handle_dcc_send_command(client_logic: 'IRCClient_Logic', cmd_args: List[str], active_context_name: str, dcc_context_name: str):
    """
    Handles the /dcc send command.
    Parses arguments, initiates DCC sends, and provides feedback.
    """
    dcc_m = client_logic.dcc_manager
    if not dcc_m:
        await _handle_dcc_error(client_logic, f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
        return
    if not dcc_m.dcc_config.enabled:
        await _handle_dcc_error(client_logic, f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
        return

    parser = argparse.ArgumentParser(prog=f"/dcc {COMMAND_NAME}", add_help=False)
    parser.add_argument("-p", "--passive", action="store_true", help="Initiate a passive (reverse) DCC send.")
    parser.add_argument("nick", help="The recipient's nickname.")
    parser.add_argument("filepath", nargs='+', help="The path(s) to the file(s) to send.")

    try:
        parsed_args = parser.parse_args(cmd_args)
        nick = parsed_args.nick
        filepaths_to_send = parsed_args.filepath
        passive_mode = parsed_args.passive

        results = await dcc_m.initiate_sends(nick, filepaths_to_send, passive=passive_mode)
        await _handle_send_results(client_logic, results, nick, dcc_context_name)
        await _ensure_dcc_context(client_logic, dcc_context_name)

    except argparse.ArgumentError as e:
        await _handle_dcc_error(client_logic, f"Error: {e.message}\nUsage: {COMMAND_HELP['usage']}", active_context_name, log_level=logging.WARNING)
    except SystemExit:
        await client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", client_logic.ui.colors["error"], context_name=active_context_name)
    except Exception as e:
        await _handle_dcc_error(client_logic, f"Error processing /dcc {COMMAND_NAME}: {e}. Check usage.", dcc_context_name, exc_info=True)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_function": handle_dcc_send_command
    }
