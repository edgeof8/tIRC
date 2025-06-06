import logging
from typing import TYPE_CHECKING, List, Dict

from pyrc_core.commands.dcc.dcc_command_base import DCCCommandHandler

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.list")

class DCCListCommandHandler(DCCCommandHandler):
    """
    Handles the /dcc list command, displaying current DCC transfer statuses.
    Inherits common DCC command functionality from DCCCommandHandler.
    """
    command_name: str = "list"
    command_aliases: List[str] = ["ls"]
    command_help: Dict[str, str] = {
        "usage": "/dcc list",
        "description": "Displays a list of all active and pending DCC file transfers.",
        "aliases": "ls"
    }

    def __init__(self, client_logic: 'IRCClient_Logic'):
        super().__init__(client_logic)

    def execute(self, cmd_args: List[str]):
        """
        Executes the /dcc list command.
        Retrieves and displays the status of all DCC transfers.
        """
        if not self.check_dcc_available(self.command_name):
            return

        if cmd_args:
            self.client_logic.add_message(f"Usage: {self.command_help['usage']}", "error", context_name=self.active_context_name)
            return

        try:
            statuses = self.dcc_m.get_transfer_statuses()
            self.client_logic.add_message("--- DCC Transfers ---", "system", context_name=self.dcc_context_name)
            for status_line in statuses:
                self.client_logic.add_message(status_line, "system", context_name=self.dcc_context_name)
            self.client_logic.add_message("---------------------", "system", context_name=self.dcc_context_name)

            self.ensure_dcc_context()
        except Exception as e:
            self.handle_error(f"Error retrieving DCC status: {e}", exc_info=True, context_name=self.dcc_context_name)
