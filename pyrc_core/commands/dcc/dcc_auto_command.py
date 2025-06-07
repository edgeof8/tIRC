# pyrc_core/commands/dcc/dcc_auto_command.py
import logging
from typing import TYPE_CHECKING, List, Dict, Any

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    # If direct config manipulation is needed and not exposed via client_logic
    # import pyrc_core.app_config as app_config_direct # Keep for now, will be app_config_instance

logger = logging.getLogger("pyrc.commands.dcc.auto")

COMMAND_NAME = "auto"
COMMAND_ALIASES: List[str] = []
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc auto [on|off]",
    "description": "Toggles or sets the global auto-accept feature for incoming DCC offers. Displays current status if no argument.",
    "aliases": "None"
}

def _handle_dcc_error(client_logic: 'IRCClient_Logic', message: str, context_name: str, log_level: int = logging.ERROR, exc_info: bool = False):
    """Helper to log and display DCC command errors."""
    logger.log(log_level, message, exc_info=exc_info)
    client_logic.add_message(message, "error", context_name=context_name)

def handle_dcc_auto_command(client_logic: 'IRCClient_Logic', cmd_args: List[str], active_context_name: str, dcc_context_name: str):
    """
    Handles the /dcc auto command.
    Toggles or sets the DCC auto-accept feature.
    """
    dcc_m = client_logic.dcc_manager
    if not dcc_m:
        _handle_dcc_error(client_logic, f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
        return

    if not cmd_args:
        current_auto_accept = dcc_m.dcc_config.get("auto_accept", False)
        client_logic.add_message(f"DCC auto-accept is currently {'ON' if current_auto_accept else 'OFF'}.", "system", context_name=active_context_name)
    elif len(cmd_args) == 1:
        setting = cmd_args[0].lower()
        new_value_str = ""
        if setting == "on":
            new_value_str = "true"
        elif setting == "off":
            new_value_str = "false"
        else:
            client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", "error", context_name=active_context_name)
            return

        try:
            new_bool_val = True if new_value_str == "true" else False
            # Update the live dcc_config dictionary in DCCManager first
            dcc_m.dcc_config["auto_accept"] = new_bool_val

            # Persist this change to the INI file using the AppConfig instance
            if client_logic.config.set_config_value("DCC", "auto_accept", new_value_str):
                client_logic.add_message(
                    f"DCC auto-accept set to {new_value_str.upper()}. Configuration saved.",
                    "system",
                    context_name=active_context_name
                )
            else:
                client_logic.add_message(
                    f"DCC auto-accept set to {new_value_str.upper()} for current session. Config save failed.",
                    "warning",
                    context_name=active_context_name
                )

        except Exception as e:
            logger.error(f"Error setting DCC auto_accept: {e}", exc_info=True)
            _handle_dcc_error(client_logic, f"Error setting DCC auto-accept: {e}", active_context_name)
    else:
        client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", "error", context_name=active_context_name)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_function": handle_dcc_auto_command
    }
