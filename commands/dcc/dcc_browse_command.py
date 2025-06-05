import logging
import os
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.browse")

class DCCBrowseCommandHandler:
    def __init__(self, client_logic: 'IRCClient_Logic'):
        self.client_logic = client_logic
        # dcc_m is not strictly needed for browse, but keeping pattern if future DCC interactions arise
        self.dcc_m = client_logic.dcc_manager
        self.dcc_context_name = "DCC" # Or a more general context if preferred for browse

    def execute(self, cmd_args: List[str]):
        # No specific DCC config check needed for browse, it's a local FS operation.

        target_dir = " ".join(cmd_args) if cmd_args else "."
        try:
            # Security: Ensure target_dir is not attempting to escape a sandboxed environment if one were intended.
            # For now, os.path.abspath provides some normalization.
            # If DCC had a specific "browseable root", validation against that would be needed here.
            abs_target_dir = os.path.abspath(target_dir)

            if not os.path.isdir(abs_target_dir):
                self.client_logic.add_message(f"Error: '{target_dir}' (abs: {abs_target_dir}) is not a valid directory.", "error", context_name=self.dcc_context_name)
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

        except PermissionError:
            logger.warning(f"Permission denied browsing '{target_dir}' (abs: {abs_target_dir}).")
            self.client_logic.add_message(f"Error browsing '{target_dir}': Permission denied.", "error", context_name=self.dcc_context_name)
        except FileNotFoundError:
            logger.warning(f"Directory not found for browsing '{target_dir}' (abs: {abs_target_dir}).")
            self.client_logic.add_message(f"Error browsing '{target_dir}': Directory not found.", "error", context_name=self.dcc_context_name)
        except Exception as e:
            logger.error(f"Error processing /dcc browse for '{target_dir}': {e}", exc_info=True)
            self.client_logic.add_message(f"Error browsing '{target_dir}': {e}", "error", context_name=self.dcc_context_name)

        # Switch context if needed, though browse might be less DCC-specific
        if self.client_logic.context_manager.active_context_name != self.dcc_context_name:
            self.client_logic.switch_active_context(self.dcc_context_name)
