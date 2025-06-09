# pyrc_core/commands/dcc/dcc_resume_command.py # Pylance re-evaluation
import logging
import argparse
from typing import TYPE_CHECKING, List, Dict, Any, cast

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    from pyrc_core.dcc.dcc_transfer import DCCSendTransfer, DCCStatus

logger = logging.getLogger("pyrc.commands.dcc.resume")

COMMAND_NAME = "resume"
COMMAND_ALIASES: List[str] = []
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc resume <transfer_id_prefix_or_filename>",
    "description": "Attempts to resume a previously failed or cancelled DCC file transfer.",
    "aliases": "None" # Explicitly stating no aliases
}

async def _handle_dcc_error(client_logic: 'IRCClient_Logic', message: str, context_name: str, log_level: int = logging.ERROR, exc_info: bool = False):
    """Helper to log and display DCC command errors."""
    logger.log(log_level, message, exc_info=exc_info)
    await client_logic.add_message(message, client_logic.ui.colors["error"], context_name=context_name)

async def _ensure_dcc_context(client_logic: 'IRCClient_Logic', dcc_context_name: str):
    """Helper to ensure DCC context is active."""
    if client_logic.context_manager.active_context_name != dcc_context_name:
        await client_logic.switch_active_context(dcc_context_name)

async def handle_dcc_resume_command(client_logic: 'IRCClient_Logic', cmd_args: List[str], active_context_name: str, dcc_context_name: str):
    """
    Handles the /dcc resume command.
    Attempts to resume a previously failed/cancelled outgoing DCC SEND transfer.
    """
    dcc_m = client_logic.dcc_manager
    if not dcc_m:
        await _handle_dcc_error(client_logic, f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
        return
    if not dcc_m.dcc_config.enabled:
        await _handle_dcc_error(client_logic, f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
        return
    if not dcc_m.dcc_config.resume_enabled:
        await _handle_dcc_error(client_logic, f"DCC resume is disabled in configuration. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
        return

    parser_resume = argparse.ArgumentParser(prog=f"/dcc {COMMAND_NAME}", add_help=False)
    parser_resume.add_argument("identifier", help="The transfer ID prefix or filename to resume.")

    try:
        parsed_resume_args = parser_resume.parse_args(cmd_args)
        identifier = parsed_resume_args.identifier

        if hasattr(dcc_m, "send_manager") and dcc_m.send_manager:
            # First, try to find the transfer by ID prefix or filename
            transfer_to_resume = None
            with dcc_m._lock: # Lock to safely access transfers dict
                # Try exact ID match first
                if identifier in dcc_m.transfers and isinstance(dcc_m.transfers[identifier], DCCSendTransfer):
                    transfer_to_resume = dcc_m.transfers[identifier]
                else:
                    # Try by prefix or filename match
                    matches = [
                        t for t in dcc_m.transfers.values()
                        if isinstance(t, DCCSendTransfer) and
                        (t.id.startswith(identifier) or t.filename.lower() == identifier.lower())
                    ]
                    if len(matches) == 1:
                        transfer_to_resume = matches[0]
                    elif len(matches) > 1:
                        await _handle_dcc_error(
                            client_logic,
                            f"Ambiguous identifier '{identifier}'. Multiple transfers match. Please use a more specific ID prefix.",
                            dcc_context_name,
                        )
                        return

            if not transfer_to_resume:
                await _handle_dcc_error(
                    client_logic,
                    f"No resumable DCC SEND transfer found matching '{identifier}'.",
                    dcc_context_name,
                )
                return

            if transfer_to_resume.status not in [DCCStatus.FAILED, DCCStatus.CANCELLED, DCCStatus.TIMED_OUT]:
                await _handle_dcc_error(
                    client_logic,
                    f"Transfer '{transfer_to_resume.filename}' (ID: {transfer_to_resume.id[:8]}) is not in a resumable state (current status: {transfer_to_resume.status.name}).",
                    dcc_context_name,
                )
                return

            # Now attempt to resume via send_manager
            # The resume_send_transfer method expects the transfer object and the accepted_port
            # However, this command initiates the RESUME, it doesn't accept one.
            # We need to tell the send_manager to *offer* a resume.
            # The _execute_send_operation in send_manager already has resume logic.
            # We should call that, passing the existing transfer object if it has a resume_offset.
            # For now, let's just re-initiate the send. The internal logic will find the offset.
            # For now, let's just re-initiate the send. The internal logic will find the offset.
            await dcc_m.send_manager.resume_send_transfer(cast(DCCSendTransfer, transfer_to_resume), 0)

            resumed_filename = transfer_to_resume.filename
            resumed_tid = transfer_to_resume.id[:8]
            await client_logic.add_message(
                f"Attempting to resume DCC SEND for '{resumed_filename}' (ID: {resumed_tid}).",
                client_logic.ui.colors["system"],
                context_name=dcc_context_name,
            )
            return
        else:
            await _handle_dcc_error(
                client_logic,
                "DCC Send Manager not initialized. Cannot use /dcc resume.",
                dcc_context_name,
            )

        await _ensure_dcc_context(client_logic, dcc_context_name)

    except SystemExit:
        await client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", client_logic.ui.colors["error"], context_name=active_context_name)
    except Exception as e:
        logger.error(f"Error parsing /dcc {COMMAND_NAME} arguments: {e}", exc_info=True)
        await _handle_dcc_error(client_logic, f"Error in /dcc {COMMAND_NAME}: {e}. Usage: {COMMAND_HELP['usage']}", active_context_name)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_function": handle_dcc_resume_command
    }
