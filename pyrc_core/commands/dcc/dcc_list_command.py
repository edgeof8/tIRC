# pyrc_core/commands/dcc/dcc_list_command.py
import logging
from typing import TYPE_CHECKING, List, Dict, Any

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.list")

COMMAND_NAME = "list"
COMMAND_ALIASES: List[str] = ["ls"]
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc list",
    "description": "Displays a list of all active and pending DCC file transfers.",
    "aliases": "ls"
}

async def _handle_dcc_error(client_logic: 'IRCClient_Logic', message: str, context_name: str, log_level: int = logging.ERROR, exc_info: bool = False):
    """Helper to log and display DCC command errors."""
    logger.log(log_level, message, exc_info=exc_info)
    await client_logic.add_message(message, client_logic.ui.colors["error"], context_name=context_name)

async def _ensure_dcc_context(client_logic: 'IRCClient_Logic', dcc_context_name: str):
    """Helper to ensure DCC context is active."""
    if client_logic.context_manager.active_context_name != dcc_context_name:
        await client_logic.switch_active_context(dcc_context_name)

async def handle_dcc_list_command(client_logic: 'IRCClient_Logic', cmd_args: List[str], active_context_name: str, dcc_context_name: str):
    """
    Handles the /dcc list command.
    Retrieves and displays the status of all DCC transfers.
    """
    dcc_m = client_logic.dcc_manager
    if not dcc_m:
        await _handle_dcc_error(client_logic, f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
        return
    if not dcc_m.dcc_config.enabled:
        await _handle_dcc_error(client_logic, f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
        return

    if cmd_args:
        await client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", client_logic.ui.colors["error"], context_name=active_context_name)
        return

    try:
        transfers = dcc_m.get_all_transfers()
        if not transfers:
            await client_logic.add_message(
                "No active or pending DCC transfers.",
                client_logic.ui.colors["system"],
                context_name=dcc_context_name,
            )
        else:
            await client_logic.add_message(
                "--- DCC Transfers ---", client_logic.ui.colors["system"], context_name=dcc_context_name
            )
            for t in transfers:
                progress_percent = (
                    (t.bytes_transferred / t.file_size * 100)
                    if t.file_size > 0
                    else 0
                )
                status_line = (
                    f"ID: {t.id[:8]}, Type: {t.transfer_type.name}, Peer: {t.peer_nick}, "
                    f"File: {t.filename}, Size: {t.file_size} bytes, "
                    f"Status: {t.status.name}"
                )
                if t.status == t.status.IN_PROGRESS:
                    status_line += f", Progress: {progress_percent:.2f}%"
                elif t.status == t.status.FAILED and t.error_message:
                    status_line += f", Error: {t.error_message}"
                await client_logic.add_message(
                    status_line, client_logic.ui.colors["system"], context_name=dcc_context_name
                )
            await client_logic.add_message(
                "---------------------", client_logic.ui.colors["system"], context_name=dcc_context_name
            )

        await _ensure_dcc_context(client_logic, dcc_context_name)
    except Exception as e:
        await _handle_dcc_error(
            client_logic,
            f"Error retrieving DCC status: {e}",
            dcc_context_name,
            exc_info=True,
        )
# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_function": handle_dcc_list_command
    }
