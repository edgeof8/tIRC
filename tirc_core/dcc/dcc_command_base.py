# tirc_core/commands/dcc/dcc_command_base.py
import logging
from typing import TYPE_CHECKING, List, Optional, Any, Dict # Added Dict

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

# This base class might not be strictly necessary if commands are simple functions.
# However, if DCC commands share significant common logic for parsing,
# state checking, or interacting with DCCManager, a base class can be useful.

class DCCCommandHelper:
    """
    A helper class for DCC commands.
    An instance of this could be passed to DCC command handlers,
    or command handlers could be methods of a class inheriting from this.
    """
    def __init__(self, client: "IRCClient_Logic"):
        self.client = client
        # Initialize a logger specific to the command that uses this helper
        # The actual command name will be filled in by the subclass or calling command
        self.logger = logging.getLogger(f"tirc.commands.dcc.{type(self).__name__}")
        if not self.client.dcc_manager:
            self.logger.error("DCCCommandHelper initialized but DCCManager is not available on the client.")

    async def ensure_dcc_enabled(self) -> bool:
        """Checks if DCC is enabled and sends a message if not."""
        if not self.client.dcc_manager or not self.client.config.dcc.enabled:
            await self.client.add_message(
                "DCC system is not enabled in the configuration.",
                self.client.ui.colors.get("error", 0),
                context_name=self.client.context_manager.active_context_name or "Status"
            )
            return False
        return True

    async def parse_common_dcc_args(self, args_str: str, min_args: int = 0, command_name: str = "dcc_command") -> Optional[List[str]]:
        """
        Basic argument parsing. Returns list of arguments or None if validation fails.
        Sends usage message on failure.
        """
        parts = args_str.split() # Basic split, might need refinement for filenames with spaces
        if len(parts) < min_args:
            help_data = self.client.command_handler.get_help_text_for_command(command_name)
            usage_msg = f"Usage: /{command_name} <params...>" # Default

            if help_data:
                # For script commands that provide a dict help_info
                if help_data.get("help_info") and isinstance(help_data["help_info"], dict):
                    usage_msg = help_data["help_info"].get("usage", usage_msg)
                # For core commands or scripts providing simple string help_text
                # (where usage is typically the first line of the formatted help_text)
                elif help_data.get("help_text") and isinstance(help_data["help_text"], str):
                    first_line_of_help = help_data["help_text"].split('\n')[0]
                    if first_line_of_help.strip().startswith(f"/{command_name}") or first_line_of_help.strip().lower().startswith("usage:"):
                        usage_msg = first_line_of_help.strip()
            else: # No help_data found
                 usage_msg = f"Error: Not enough arguments for /{command_name}. Expected at least {min_args}."


            await self.client.add_message(
                usage_msg,
                self.client.ui.colors.get("error", 0),
                context_name=self.client.context_manager.active_context_name or "Status"
            )
            return None
        return parts

    # Add other common utility methods for DCC commands here, e.g.:
    # - find_transfer_by_identifier
    # - format_transfer_status_for_ui

# Note: If individual DCC command files (like dcc_send_command.py) directly implement
# their handlers as async functions, they might not use this class directly,
# but could call static utility methods from it if any were defined.
# The current structure seems to favor standalone handler functions per command file.
# This helper class is more of a conceptual placeholder unless a different command structure is adopted.
