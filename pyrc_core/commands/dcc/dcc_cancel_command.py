import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.cancel")

class DCCCancelCommandHandler:
    def __init__(self, client_logic: 'IRCClient_Logic'):
        self.client_logic = client_logic
        self.dcc_m = client_logic.dcc_manager
        self.active_context_name = client_logic.context_manager.active_context_name or "Status"
        self.dcc_context_name = "DCC"

    def execute(self, cmd_args: List[str]):
        if not self.dcc_m:
            self.client_logic.add_message("DCC system not available.", "error", context_name=self.active_context_name)
            return
        if not self.dcc_m.dcc_config.get("enabled"): # Check if DCC is enabled
            self.client_logic.add_message("DCC is currently disabled.", "error", context_name=self.active_context_name)
            return

        if not cmd_args:
            self.client_logic.add_message("Usage: /dcc cancel <transfer_id_prefix_or_token_prefix>", "error", context_name=self.active_context_name)
            return

        identifier_prefix = cmd_args[0]
        cancelled = False

        # Try to cancel an active transfer by ID prefix
        actual_transfer_id_to_cancel = None
        ambiguous_transfer = False
        with self.dcc_m._lock: # Accessing dcc_manager's transfers dict
            possible_matches = []
            for tid in self.dcc_m.transfers.keys():
                if tid.startswith(identifier_prefix):
                    possible_matches.append(tid)

            if len(possible_matches) == 1:
                actual_transfer_id_to_cancel = possible_matches[0]
            elif len(possible_matches) > 1:
                ambiguous_transfer = True

        if ambiguous_transfer:
            self.client_logic.add_message(f"Ambiguous transfer ID prefix '{identifier_prefix}'. Multiple active transfers match.", "error", context_name=self.dcc_context_name)
            return

        if actual_transfer_id_to_cancel:
            if self.dcc_m.cancel_transfer(actual_transfer_id_to_cancel):
                self.client_logic.add_message(f"DCC transfer {actual_transfer_id_to_cancel[:8]} cancellation requested.", "system", context_name=self.dcc_context_name)
                cancelled = True
            # else: DCCManager.cancel_transfer logs failure if ID not found (should not happen here)

        # If not cancelled as an active transfer, try to cancel a pending passive offer
        if not cancelled:
            # DCCManager.cancel_pending_passive_offer now directly uses passive_offer_manager
            if self.dcc_m.cancel_pending_passive_offer(identifier_prefix):
                # Message is handled by cancel_pending_passive_offer in DCCManager (which calls passive_offer_manager)
                cancelled = True

        if not cancelled:
            self.client_logic.add_message(f"No active transfer or pending passive offer found matching ID/token prefix '{identifier_prefix}'.", "error", context_name=self.dcc_context_name)

        if self.client_logic.context_manager.active_context_name != self.dcc_context_name:
            self.client_logic.switch_active_context(self.dcc_context_name)
