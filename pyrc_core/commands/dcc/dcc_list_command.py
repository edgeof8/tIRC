# pyrc_core/commands/dcc/dcc_list_command.py
import logging
from typing import TYPE_CHECKING, List, Dict, Any
from .dcc_command_base import DCCCommandHandlerBase

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

class DCCListCommandHandler(DCCCommandHandlerBase):
    """Handles the /dcc list command."""

    async def execute(self, cmd_args: List[str], active_context_name: str, dcc_context_name: str):
        """
        Handles the /dcc list command.
        Retrieves and displays the status of all DCC transfers.
        """
        dcc_m = self.client_logic.dcc_manager
        if not dcc_m:
            await self._handle_dcc_error(f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
            return
        if not dcc_m.dcc_config.enabled:
            await self._handle_dcc_error(f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
            return

        if cmd_args:
            await self.client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", self.client_logic.ui.colors["error"], context_name=active_context_name)
            return

        try:
            transfers = dcc_m.get_all_transfers() # Assuming this is not async
            if not transfers:
                await self.client_logic.add_message(
                    "No active or pending DCC transfers.",
                    self.client_logic.ui.colors["system"],
                    context_name=dcc_context_name,
                )
            else:
                await self.client_logic.add_message(
                    "--- DCC Transfers ---", self.client_logic.ui.colors["system"], context_name=dcc_context_name
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
                    if t.status == t.status.IN_PROGRESS: # Assuming status is an Enum or similar
                        status_line += f", Progress: {progress_percent:.2f}%"
                    elif t.status == t.status.FAILED and t.error_message:
                        status_line += f", Error: {t.error_message}"
                    await self.client_logic.add_message(
                        status_line, self.client_logic.ui.colors["system"], context_name=dcc_context_name
                    )
                await self.client_logic.add_message(
                    "---------------------", self.client_logic.ui.colors["system"], context_name=dcc_context_name
                )

            await self._ensure_dcc_context(dcc_context_name)
        except Exception as e:
            await self._handle_dcc_error(
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
        "handler_class": DCCListCommandHandler
    }
