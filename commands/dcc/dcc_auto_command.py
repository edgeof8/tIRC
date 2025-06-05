import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic
    # If direct config manipulation is needed and not exposed via client_logic
    # import config as app_config_direct

logger = logging.getLogger("pyrc.commands.dcc.auto")

class DCCAutoCommandHandler:
    def __init__(self, client_logic: 'IRCClient_Logic'):
        self.client_logic = client_logic
        self.dcc_m = client_logic.dcc_manager
        self.active_context_name = client_logic.context_manager.active_context_name or "Status"
        # dcc_context_name might not be strictly needed if this command doesn't switch context
        # but keeping for consistency if messages are posted to "DCC" window.

    def execute(self, cmd_args: List[str]):
        if not self.dcc_m:
            self.client_logic.add_message("DCC system not available.", "error", context_name=self.active_context_name)
            return
        # No specific DCC enabled check here, as toggling auto-accept might be desired even if DCC is globally off for next session.
        # Or, one could argue it should only be settable if DCC is enabled. For now, allow setting.

        if not cmd_args:
            current_auto_accept = self.dcc_m.dcc_config.get("auto_accept", False)
            self.client_logic.add_message(f"DCC auto-accept is currently {'ON' if current_auto_accept else 'OFF'}.", "system", context_name=self.active_context_name)
        elif len(cmd_args) == 1:
            setting = cmd_args[0].lower()
            new_value_str = ""
            if setting == "on":
                new_value_str = "true"
            elif setting == "off":
                new_value_str = "false"
            else:
                self.client_logic.add_message("Usage: /dcc auto [on|off]", "error", context_name=self.active_context_name)
                return

            try:
                new_bool_val = True if new_value_str == "true" else False
                # Update the live dcc_config dictionary in DCCManager first
                self.dcc_m.dcc_config["auto_accept"] = new_bool_val

                # Persist this change to the INI file.
                if hasattr(self.client_logic, 'app_config') and hasattr(self.client_logic.app_config, 'set_config_value'):
                    if self.client_logic.app_config.set_config_value("DCC", "auto_accept", new_value_str):
                        self.client_logic.add_message(f"DCC auto-accept set to {new_value_str.upper()}. Configuration saved.", "system", context_name=self.active_context_name)
                    else:
                        self.client_logic.add_message(f"DCC auto-accept set to {new_value_str.upper()} for current session. Failed to save to config file.", "warning", context_name=self.active_context_name)
                else:
                    logger.error("Cannot save DCC auto_accept setting: client_logic.app_config.set_config_value not accessible.")
                    self.client_logic.add_message(f"DCC auto-accept set to {new_value_str.upper()} for current session. Config save path unclear.", "warning", context_name=self.active_context_name)

            except Exception as e:
                logger.error(f"Error setting DCC auto_accept: {e}", exc_info=True)
                self.client_logic.add_message(f"Error setting DCC auto-accept: {e}", "error", context_name=self.active_context_name)
        else:
            self.client_logic.add_message("Usage: /dcc auto [on|off]", "error", context_name=self.active_context_name)
