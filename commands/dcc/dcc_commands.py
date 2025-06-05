import logging
import os
import argparse # For more robust argument parsing
from typing import TYPE_CHECKING, Dict, Any

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc")

def dcc_command_handler(client_logic: 'IRCClient_Logic', args_str: str):
    """Handles the main /dcc command and its subcommands."""

    # Use a simple list of args for now, consider argparse for more complex needs later
    args = args_str.split()

    if not hasattr(client_logic, 'dcc_manager') or not client_logic.dcc_manager:
        client_logic.add_message("DCC system is not initialized or available.", "error", context_name="Status")
        return

    dcc_m = client_logic.dcc_manager
    active_context_name = client_logic.context_manager.active_context_name or "Status"
    dcc_context_name = "DCC"

    if not dcc_m.dcc_config.get("enabled"):
        client_logic.add_message("DCC is currently disabled in the configuration.", "error", context_name=active_context_name)
        return

    if not args:
        client_logic.add_message(
            "Usage: /dcc <send|get|accept|list|close|browse|cancel|resume> [options...]. Try /help dcc for more.",
            "error",
            context_name=active_context_name
        )
        return

    subcommand = args[0].lower()
    cmd_args = args[1:]

    # The "send" subcommand logic has been moved to commands/dcc/dcc_send_command.py
    # The main dcc_command_handler will need to be updated to dispatch to the new handler,
    # or the new command class needs to be registered with the main CommandHandler.
    # For now, this block is removed. A placeholder if statement is used to maintain structure.
    if subcommand == "placeholder_for_removed_send":
        pass
    # The "get" subcommand logic has been moved to commands/dcc/dcc_get_command.py
    elif subcommand == "placeholder_for_removed_get":
        pass
    # The "accept" subcommand logic has been moved to commands/dcc/dcc_accept_command.py
    elif subcommand == "placeholder_for_removed_accept":
        pass
    # The "list" subcommand logic has been moved to commands/dcc/dcc_list_command.py
    elif subcommand == "placeholder_for_removed_list":
        pass
    # The "browse" subcommand logic has been moved to commands/dcc/dcc_browse_command.py
    elif subcommand == "placeholder_for_removed_browse":
        pass
    # The "close" / "cancel" subcommand logic has been moved to commands/dcc/dcc_cancel_command.py
    elif subcommand == "placeholder_for_removed_cancel":
        pass
    elif subcommand == "auto":
        if not cmd_args:
            # Display current status
            current_auto_accept = client_logic.dcc_manager.dcc_config.get("auto_accept", False)
            client_logic.add_message(f"DCC auto-accept is currently {'ON' if current_auto_accept else 'OFF'}.", "system", context_name=active_context_name)
        elif len(cmd_args) == 1:
            setting = cmd_args[0].lower()
            new_value_str = ""
            if setting == "on":
                new_value_str = "true"
            elif setting == "off":
                new_value_str = "false"
            else:
                client_logic.add_message("Usage: /dcc auto [on|off]", "error", context_name=active_context_name)
                return

            try:
                new_bool_val = True if new_value_str == "true" else False
                # Update the live dcc_config dictionary in DCCManager first
                dcc_m.dcc_config["auto_accept"] = new_bool_val

                # Persist this change to the INI file.
                # Accessing config.py's set_config_value directly.
                # This assumes config.py is imported as 'app_config' in irc_client_logic and accessible.
                # A cleaner way might be a dedicated method in IRCClient_Logic to set specific config values.
                # For now, direct access if possible, or a more robust method.

                # Attempt to use the set_config_value from the config module directly
                # Assuming config.py is imported as app_config and IRCClient_Logic might have a reference to it,
                # or we import it here directly (less ideal).
                # Let's assume `client_logic.app_config` exists or `config.set_config_value` is static/module-level.
                # The most robust way is `import config as app_config_direct; app_config_direct.set_config_value(...)`
                # Or if IRCClient_Logic exposes it:

                # To ensure this works, we should rely on config.py's own functions.
                # We need to import config directly in this command module, or ensure client_logic provides a path.
                # For now, let's assume client_logic has an attribute `app_config` that refers to the loaded config module.
                # This was how it was done in `dcc_manager.py` (`getattr(app_config, ...)`).

                # Let's try to use the `set_config_value` from `config.py` which should be available in the project.
                # We need to ensure `config.py` is correctly imported where `set_config_value` is defined.
                # `irc_client_logic.py` imports `import config as app_config`.
                # So, `client_logic.app_config.set_config_value` should work if `app_config` is made an attribute.
                # For now, let's assume a direct import path or a helper method on client_logic.
                # Given the structure, direct import is cleaner if client_logic doesn't expose it.

                # Simplest for now: Assume client_logic has a way to access config.py's function
                # If not, this part will need refinement based on how config saving is centralized.
                # The previous attempt `client_logic.config_module_ref` was a guess.
                # The `set` command itself uses `app_config.set_config_value`.

                # Let's assume `client_logic` has direct access to the `config` module's functions.
                # In `irc_client_logic.py`, `import config as app_config` is used.
                # We can make `app_config` an attribute of `client_logic` or import `config` here.
                # For consistency with how `dcc_manager` accesses config values (`getattr(app_config, ...)`),
                # it's best if `client_logic` provides access to `app_config`.
                # If `client_logic.app_config` is available:
                if hasattr(client_logic, 'app_config') and hasattr(client_logic.app_config, 'set_config_value'):
                    if client_logic.app_config.set_config_value("DCC", "auto_accept", new_value_str):
                        client_logic.add_message(f"DCC auto-accept set to {new_value_str.upper()}. Configuration saved.", "system", context_name=active_context_name)
                    else:
                        client_logic.add_message(f"DCC auto-accept set to {new_value_str.upper()} for current session. Failed to save to config file.", "warning", context_name=active_context_name)
                else:
                    # Fallback if direct access isn't setup as expected.
                    # This indicates a structural issue to be resolved in IRCClient_Logic for config access.
                    logger.error("Cannot save DCC auto_accept setting: client_logic.app_config.set_config_value not accessible.")
                    client_logic.add_message(f"DCC auto-accept set to {new_value_str.upper()} for current session. Config save path unclear.", "warning", context_name=active_context_name)

            except Exception as e:
                logger.error(f"Error setting DCC auto_accept: {e}", exc_info=True)
                client_logic.add_message(f"Error setting DCC auto-accept: {e}", "error", context_name=active_context_name)
        else:
            client_logic.add_message("Usage: /dcc auto [on|off]", "error", context_name=active_context_name)

    elif subcommand == "resume":
        # Usage: /dcc resume <transfer_id_prefix_or_filename>
        parser_resume = argparse.ArgumentParser(prog="/dcc resume", add_help=False)
        parser_resume.add_argument("identifier", help="The transfer ID prefix or filename to resume.")

        try:
            parsed_resume_args = parser_resume.parse_args(cmd_args)
            identifier = parsed_resume_args.identifier

            if hasattr(dcc_m, "attempt_user_resume"):
                result = dcc_m.attempt_user_resume(identifier)
                if result.get("success"):
                    resumed_filename = result.get("filename", identifier)
                    resumed_tid = result.get("transfer_id", "N/A")[:8]
                    client_logic.add_message(f"Attempting to resume DCC SEND for '{resumed_filename}' (New ID: {resumed_tid}).", "system", context_name=dcc_context_name)
                else:
                    client_logic.add_message(f"DCC RESUME for '{identifier}' failed: {result.get('error', 'Unknown error or transfer not found/resumable.')}", "error", context_name=dcc_context_name)
            else:
                client_logic.add_message("DCC RESUME command logic not fully implemented in DCCManager yet.", "error", context_name=dcc_context_name)

            if client_logic.context_manager.active_context_name != dcc_context_name:
                client_logic.switch_active_context(dcc_context_name)

        except SystemExit: # Argparse calls sys.exit()
            client_logic.add_message("Usage: /dcc resume <transfer_id_prefix_or_filename>", "error", context_name=active_context_name)
            return
        except Exception as e:
            logger.error(f"Error parsing /dcc resume arguments: {e}", exc_info=True)
            client_logic.add_message(f"Error in /dcc resume: {e}. Usage: /dcc resume <transfer_id_prefix_or_filename>", "error", context_name=active_context_name)
            return
    else:
        client_logic.add_message(f"Unknown DCC subcommand: {subcommand}. Try /help dcc.", "error", context_name=active_context_name)

COMMAND_DEFINITIONS = [
    {
        "name": "dcc",
        "handler": "dcc_command_handler", # Name of the function in this module
        "help": {
            "usage": "/dcc <subcommand> [args]",
            "description": "Manages DCC file transfers. Subcommands: send, get, accept, list, close, browse, cancel, auto, resume.",
            "aliases": []
        }
    },
    # Help for subcommands can be implicitly handled by the main /dcc help string
    # or CommandHandler could be extended for sub-command help topics.
]
