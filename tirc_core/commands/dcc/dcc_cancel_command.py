# pyrc_core/commands/dcc/dcc_cancel_command.py
import logging
from typing import TYPE_CHECKING, List, Dict, Any
from .dcc_command_base import DCCCommandHandlerBase

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

class DCCCancelCommandHandler(DCCCommandHandlerBase):
    """Handles the /dcc cancel (and /dcc close) command."""

    async def execute(self, cmd_args: List[str], active_context_name: str, dcc_context_name: str):
        """
        Handles the /dcc cancel (and /dcc close) command.
        Cancels an active transfer or a pending passive offer.
        """
        dcc_m = self.client_logic.dcc_manager
        if not dcc_m:
            await self._handle_dcc_error(f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
            return
        if not dcc_m.dcc_config.enabled:
            await self._handle_dcc_error(f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
            return

        if not cmd_args:
            await self.client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", self.client_logic.ui.colors["error"], context_name=active_context_name)
            return

        identifier_prefix = cmd_args[0]
        cancelled = False

        # Try to cancel an active transfer by ID prefix
        actual_transfer_id_to_cancel = None
        ambiguous_transfer = False
        # Assuming dcc_m._lock is an asyncio.Lock or similar if used in async context
        # If it's a threading.Lock, it should be handled carefully in async code.
        # For simplicity, direct access if lock is primarily for synchronous parts of dcc_m.
        # If dcc_m.transfers is frequently modified by other async tasks, a proper async lock is needed.

        # Simplified access for now, assuming _lock protects synchronous modifications or is an asyncio.Lock
        # If dcc_m.transfers is a shared mutable collection, ensure thread/task safety.
        # For this refactoring, we'll assume the original lock mechanism is appropriate.
        # If dcc_m._lock is a threading.Lock, it might block. If it's an asyncio.Lock:
        # async with dcc_m._lock:
        #     possible_matches = [tid for tid in dcc_m.transfers if tid.startswith(identifier_prefix)]
        # else, direct access if safe:
        possible_matches = [tid for tid in dcc_m.transfers if tid.startswith(identifier_prefix)]


        if len(possible_matches) == 1:
            actual_transfer_id_to_cancel = possible_matches[0]
        elif len(possible_matches) > 1:
            ambiguous_transfer = True

        if ambiguous_transfer:
            await self._handle_dcc_error(f"Ambiguous transfer ID prefix '{identifier_prefix}'. Multiple active transfers match.", dcc_context_name)
            return

        if actual_transfer_id_to_cancel:
            if dcc_m.cancel_transfer(actual_transfer_id_to_cancel): # Assuming cancel_transfer is not async
                await self.client_logic.add_message(f"DCC transfer {actual_transfer_id_to_cancel[:8]} cancellation requested.", self.client_logic.ui.colors["system"], context_name=dcc_context_name)
                cancelled = True

        # If not cancelled as an active transfer, try to cancel a pending passive offer
        if not cancelled:
            # Assuming cancel_offer_by_prefix is not async
            actual_token, _ = dcc_m.passive_offer_manager.cancel_offer_by_prefix(identifier_prefix)
            if actual_token:
                await self.client_logic.add_message(f"Cancelled pending passive offer with token {actual_token[:8]}...", self.client_logic.ui.colors["system"], context_name=dcc_context_name)
                cancelled = True

        if not cancelled:
            await self._handle_dcc_error(f"No active transfer or pending passive offer found matching ID/token prefix '{identifier_prefix}'.", dcc_context_name)

        await self._ensure_dcc_context(dcc_context_name)


# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_class": DCCCancelCommandHandler
    }
