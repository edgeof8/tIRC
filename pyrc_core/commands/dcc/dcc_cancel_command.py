# pyrc_core/commands/dcc/dcc_cancel_command.py
import logging
from typing import TYPE_CHECKING, List, Dict, Any

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.cancel")

COMMAND_NAME = "cancel" # Primary name
COMMAND_ALIASES: List[str] = ["close"] # Aliases
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc cancel <id_or_token_prefix>",
    "description": "Cancels an active transfer by its ID prefix or a pending passive offer by its token prefix.",
    "aliases": "close"
}

def _handle_dcc_error(client_logic: 'IRCClient_Logic', message: str, context_name: str, log_level: int = logging.ERROR, exc_info: bool = False):
    """Helper to log and display DCC command errors."""
    logger.log(log_level, message, exc_info=exc_info)
    client_logic.add_message(message, "error", context_name=context_name)

def _ensure_dcc_context(client_logic: 'IRCClient_Logic', dcc_context_name: str):
    """Helper to ensure DCC context is active."""
    if client_logic.context_manager.active_context_name != dcc_context_name:
        client_logic.switch_active_context(dcc_context_name)

def handle_dcc_cancel_command(client_logic: 'IRCClient_Logic', cmd_args: List[str], active_context_name: str, dcc_context_name: str):
    """
    Handles the /dcc cancel (and /dcc close) command.
    Cancels an active transfer or a pending passive offer.
    """
    dcc_m = client_logic.dcc_manager
    if not dcc_m:
        _handle_dcc_error(client_logic, f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
        return
    if not dcc_m.dcc_config.get("enabled"):
        _handle_dcc_error(client_logic, f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
        return

    if not cmd_args:
        client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", "error", context_name=active_context_name)
        return

    identifier_prefix = cmd_args[0]
    cancelled = False

    # Try to cancel an active transfer by ID prefix
    actual_transfer_id_to_cancel = None
    ambiguous_transfer = False
    with dcc_m._lock:
        possible_matches = [tid for tid in dcc_m.transfers if tid.startswith(identifier_prefix)]
        if len(possible_matches) == 1:
            actual_transfer_id_to_cancel = possible_matches[0]
        elif len(possible_matches) > 1:
            ambiguous_transfer = True

    if ambiguous_transfer:
        _handle_dcc_error(client_logic, f"Ambiguous transfer ID prefix '{identifier_prefix}'. Multiple active transfers match.", dcc_context_name)
        return

    if actual_transfer_id_to_cancel:
        if dcc_m.cancel_transfer(actual_transfer_id_to_cancel):
            client_logic.add_message(f"DCC transfer {actual_transfer_id_to_cancel[:8]} cancellation requested.", "system", context_name=dcc_context_name)
            cancelled = True

    # If not cancelled as an active transfer, try to cancel a pending passive offer
    if not cancelled:
        if dcc_m.cancel_pending_passive_offer(identifier_prefix):
            # Message is handled by cancel_pending_passive_offer in DCCManager
            cancelled = True

    if not cancelled:
        _handle_dcc_error(client_logic, f"No active transfer or pending passive offer found matching ID/token prefix '{identifier_prefix}'.", dcc_context_name)

    _ensure_dcc_context(client_logic, dcc_context_name)


# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_function": handle_dcc_cancel_command
    }
