# pyrc_core/commands/dcc/dcc_command_base.py
import logging
from typing import List, Dict, Any, cast
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

class DCCCommandHandlerBase:
    """Base class for modular DCC subcommand handlers."""
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client_logic = client_logic
        self.logger = logging.getLogger(f"pyrc.commands.dcc.{type(self).__name__}")

    async def _handle_dcc_error(self, message: str, context_name: str, log_level: int = logging.ERROR, exc_info: bool = False):
        """Helper to log and display DCC command errors."""
        self.logger.log(log_level, message, exc_info=exc_info)
        await self.client_logic.add_message(message, self.client_logic.ui.colors["error"], context_name=context_name)

    async def _ensure_dcc_context(self, dcc_context_name: str):
        """Helper to ensure DCC context is active."""
        if self.client_logic.context_manager.active_context_name != dcc_context_name:
            await self.client_logic.switch_active_context(dcc_context_name)

    async def execute(self, cmd_args: List[str], active_context_name: str, dcc_context_name: str):
        """
        Abstract method to be implemented by each subcommand handler.
        This is the entry point for the command's logic.
        """
        raise NotImplementedError("Subclasses must implement the execute method.")