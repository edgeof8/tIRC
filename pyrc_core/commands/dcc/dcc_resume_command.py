# pyrc_core/commands/dcc/dcc_resume_command.py
import logging
import argparse
from typing import TYPE_CHECKING, List, Dict, Any

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.resume")

COMMAND_NAME = "resume"
COMMAND_ALIASES: List[str] = []
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc resume <transfer_id_prefix_or_filename>",
    "description": "Attempts to resume a previously failed or cancelled DCC file transfer.",
    "aliases": "None" # Explicitly stating no aliases
}

def _handle_dcc_error(client_logic: 'IRCClient_Logic', message: str, context_name: str, log_level: int = logging.ERROR, exc_info: bool = False):
    """Helper to log and display DCC command errors."""
    logger.log(log_level, message, exc_info=exc_info)
    client_logic.add_message(message, "error", context_name=context_name)

def _ensure_dcc_context(client_logic: 'IRCClient_Logic', dcc_context_name: str):
    """Helper to ensure DCC context is active."""
    if client_logic.context_manager.active_context_name != dcc_context_name:
        client_logic.switch_active_context(dcc_context_name)

def handle_dcc_resume_command(client_logic: 'IRCClient_Logic', cmd_args: List[str], active_context_name: str, dcc_context_name: str):
    """
    Handles the /dcc resume command.
    Attempts to resume a previously failed/cancelled outgoing DCC SEND transfer.
    """
    dcc_m = client_logic.dcc_manager
    if not dcc_m:
        _handle_dcc_error(client_logic, f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
        return
    if not dcc_m.dcc_config.get("enabled"):
        _handle_dcc_error(client_logic, f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
        return
    if not dcc_m.dcc_config.get("resume_enabled"):
        _handle_dcc_error(client_logic, f"DCC resume is disabled in configuration. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
        return

    parser_resume = argparse.ArgumentParser(prog=f"/dcc {COMMAND_NAME}", add_help=False)
    parser_resume.add_argument("identifier", help="The transfer ID prefix or filename to resume.")

    try:
        parsed_resume_args = parser_resume.parse_args(cmd_args)
        identifier = parsed_resume_args.identifier

        if hasattr(dcc_m, "attempt_user_resume"):
            result = dcc_m.attempt_user_resume(identifier)
            if result.get("success"):
                resumed_filename = result.get("filename", identifier)
                resumed_tid = result.get("transfer_id", "N/A")[:8]
                client_logic.add_message(
                    f"Attempting to resume DCC SEND for '{resumed_filename}' (New ID: {resumed_tid}).",
                    "system",
                    context_name=dcc_context_name
                )
            else:
                _handle_dcc_error(
                    client_logic,
                    f"DCC RESUME for '{identifier}' failed: {result.get('error', 'Unknown error or transfer not found/resumable.')}",
                    dcc_context_name
                )
        else:
            _handle_dcc_error(client_logic, "DCC RESUME command logic not fully implemented in DCCManager yet.", dcc_context_name)

        _ensure_dcc_context(client_logic, dcc_context_name)

    except SystemExit:
        client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", "error", context_name=active_context_name)
    except Exception as e:
        logger.error(f"Error parsing /dcc {COMMAND_NAME} arguments: {e}", exc_info=True)
        _handle_dcc_error(client_logic, f"Error in /dcc {COMMAND_NAME}: {e}. Usage: {COMMAND_HELP['usage']}", active_context_name)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_function": handle_dcc_resume_command
    }
