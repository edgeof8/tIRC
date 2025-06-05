import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.list")

class DCCListCommandHandler:
    def __init__(self, client_logic: 'IRCClient_Logic'):
        self.client_logic = client_logic
        self.dcc_m = client_logic.dcc_manager
        self.active_context_name = client_logic.context_manager.active_context_name or "Status" # Should not be needed here
        self.dcc_context_name = "DCC"

    def execute(self, cmd_args: List[str]): # cmd_args is not used for list
        if not self.dcc_m:
            self.client_logic.add_message("DCC system not available.", "error", context_name=self.dcc_context_name)
            return
        if not self.dcc_m.dcc_config.get("enabled"):
            self.client_logic.add_message("DCC is currently disabled.", "error", context_name=self.dcc_context_name)
            return

        try:
            statuses = self.dcc_m.get_transfer_statuses()
            self.client_logic.add_message("--- DCC Transfers ---", "system", context_name=self.dcc_context_name)
            for status_line in statuses:
                self.client_logic.add_message(status_line, "system", context_name=self.dcc_context_name)
            self.client_logic.add_message("---------------------", "system", context_name=self.dcc_context_name)

            if self.client_logic.context_manager.active_context_name != self.dcc_context_name:
                self.client_logic.switch_active_context(self.dcc_context_name)
        except Exception as e:
            logger.error(f"Error processing /dcc list: {e}", exc_info=True)
            self.client_logic.add_message(f"Error retrieving DCC status: {e}", "error", context_name=self.dcc_context_name)
