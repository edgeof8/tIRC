import logging
import os
from typing import TYPE_CHECKING, List, Dict

from pyrc_core.commands.dcc.dcc_command_base import DCCCommandHandler
from pyrc_core.client.irc_client_logic import IRCClient_Logic

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.browse")

class DCCBrowseCommandHandler(DCCCommandHandler):
    """
    Handles the /dcc browse command, allowing local directory listing.
    Inherits common DCC command functionality from DCCCommandHandler.
    """
    command_name: str = "browse"
    command_aliases: List[str] = ["dir"]
    command_help: Dict[str, str] = {
        "usage": "/dcc browse [path]",
        "description": "Lists the contents of a local directory. Defaults to the current working directory if no path is provided.",
        "aliases": "dir"
    }

    def __init__(self, client_logic: 'IRCClient_Logic'):
        super().__init__(client_logic)
        # dcc_m is not strictly needed for browse, but keeping pattern if future DCC interactions arise
        # self.dcc_m = client_logic.dcc_manager # Handled by base class now

    def execute(self, cmd_args: List[str]):
        """
        Executes the /dcc browse command.
        Lists the contents of the specified local directory.
        """
        # No specific DCC config check needed for browse, it's a local FS operation.

        target_dir = " ".join(cmd_args) if cmd_args else "."
        try:
            # Security: Ensure target_dir is not attempting to escape a sandboxed environment if one were intended.
            # For now, os.path.abspath provides some normalization.
            # If DCC had a specific "browseable root", validation against that would be needed here.
            abs_target_dir = os.path.abspath(target_dir)

            if not os.path.isdir(abs_target_dir):
                self.handle_error(f"Error: '{target_dir}' (abs: {abs_target_dir}) is not a valid directory.", context_name=self.dcc_context_name)
                return

            self.client_logic.add_message(f"Contents of '{abs_target_dir}':", "system", context_name=self.dcc_context_name)
            items = []
            for item_name in sorted(os.listdir(abs_target_dir)):
                item_path = os.path.join(abs_target_dir, item_name)
                is_dir_marker = "[D] " if os.path.isdir(item_path) else "[F] "
                items.append(f"  {is_dir_marker}{item_name}")

            if not items:
                self.client_logic.add_message("  (Directory is empty)", "system", context_name=self.dcc_context_name)
            else:
                for item_line in items:
                    self.client_logic.add_message(item_line, "system", context_name=self.dcc_context_name)

            self.ensure_dcc_context()

        except PermissionError:
            self.handle_error(f"Error browsing '{target_dir}': Permission denied.", log_level=logging.WARNING, context_name=self.dcc_context_name)
        except FileNotFoundError:
            self.handle_error(f"Error browsing '{target_dir}': Directory not found.", log_level=logging.WARNING, context_name=self.dcc_context_name)
        except Exception as e:
            self.handle_error(f"Error processing /dcc {self.command_name} for '{target_dir}': {e}", exc_info=True, context_name=self.dcc_context_name)
