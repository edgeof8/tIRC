import asyncio
from typing import TYPE_CHECKING, List, Dict, Any, Optional

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

async def handle_script_command(client: "IRCClient_Logic", args_str: str, context_name: Optional[str] = None) -> None:
    """
    Handles the /script command for managing scripts.
    Usage: /script [list|load <name>|unload <name>|reload <name>]
    """
    args = args_str.split()
    subcommand = args[0].lower() if args else "list" # Default to list if no subcommand

    script_manager = client.script_manager

    # Determine the effective context name to use for messages
    effective_context = context_name if context_name is not None else (client.context_manager.active_context_name or "Status")

    if subcommand == "list":
        loaded_scripts = script_manager.get_loaded_scripts()
        disabled_scripts = script_manager.get_disabled_scripts()
        all_script_files = []
        if client.script_manager.scripts_dir and os.path.exists(client.script_manager.scripts_dir):
            all_script_files = [
                f[:-3] for f in os.listdir(client.script_manager.scripts_dir)
                if f.endswith(".py") and not f.startswith("__")
            ]

        message = "--- Script Status ---"
        await client.add_message(message, client.ui.colors.get("info_dim", 0), effective_context)

        # Create a set of all known scripts from files for comprehensive listing
        known_scripts = set(all_script_files)
        # Add any scripts that might be in loaded_scripts or disabled_scripts but not in files (e.g. if a file was deleted)
        known_scripts.update(loaded_scripts)
        known_scripts.update(disabled_scripts)


        if not known_scripts:
            await client.add_message("No scripts found.", client.ui.colors.get("info_dim", 0), effective_context)
            return

        for script_name in sorted(list(known_scripts)):
            status = "Unknown"
            color_key = "info_dim"
            if script_name in loaded_scripts:
                status = "Loaded"
                color_key = "success"
            elif script_name in disabled_scripts:
                status = "Disabled"
                color_key = "warning"
            elif script_name in all_script_files: # Found in directory but not loaded/disabled
                # Could be an error during load, or never attempted
                # For now, let's assume it might have had an error or is new
                status = "Not Loaded (Available)"
                color_key = "info"


            # A more robust check for error status would require ScriptManager to track load errors per script.
            # For now, we infer based on presence in lists.
            # Example: if script_manager.get_script_load_error(script_name): status = "Error"

            await client.add_message(f"- {script_name}: {status}", client.ui.colors.get(color_key, 0), effective_context)

    elif subcommand in ["load", "unload", "reload"]:
        if len(args) < 2:
            await client.add_message(f"Usage: /script {subcommand} <script_name>", client.ui.colors.get("error", 0), effective_context)
            return
        script_name_to_manage = args[1]

        if subcommand == "load":
            if script_manager.is_script_enabled(script_name_to_manage):
                await client.add_message(f"Script '{script_name_to_manage}' is already loaded.", client.ui.colors.get("warning", 0), effective_context)
            elif script_name_to_manage not in script_manager.get_disabled_scripts():
                 await client.add_message(f"Script '{script_name_to_manage}' is not disabled or does not exist. Cannot load.", client.ui.colors.get("error", 0), effective_context)
            else:
                success = script_manager.enable_script(script_name_to_manage)
                if success:
                    await client.add_message(f"Script '{script_name_to_manage}' loaded successfully.", client.ui.colors.get("success", 0), effective_context)
                else:
                    await client.add_message(f"Failed to load script '{script_name_to_manage}'. Check logs for details.", client.ui.colors.get("error", 0), effective_context)

        elif subcommand == "unload":
            if not script_manager.is_script_enabled(script_name_to_manage):
                await client.add_message(f"Script '{script_name_to_manage}' is not currently loaded or does not exist.", client.ui.colors.get("error", 0), effective_context)
            else:
                success = script_manager.disable_script(script_name_to_manage)
                if success:
                    await client.add_message(f"Script '{script_name_to_manage}' unloaded and disabled for this session.", client.ui.colors.get("success", 0), effective_context)
                else:
                    # This case should ideally not happen if is_script_enabled was true
                    await client.add_message(f"Failed to unload script '{script_name_to_manage}'.", client.ui.colors.get("error", 0), effective_context)

        elif subcommand == "reload":
            if not script_manager.is_script_enabled(script_name_to_manage) and script_name_to_manage not in script_manager.get_disabled_scripts():
                await client.add_message(f"Script '{script_name_to_manage}' does not exist or was never loaded. Cannot reload.", client.ui.colors.get("error", 0), effective_context)
                return

            # If script is disabled, enable it first to attempt reload
            if script_name_to_manage in script_manager.get_disabled_scripts():
                if not script_manager.enable_script(script_name_to_manage):
                    await client.add_message(f"Failed to enable script '{script_name_to_manage}' before reloading. Check logs.", client.ui.colors.get("error", 0), effective_context)
                    return
                await client.add_message(f"Script '{script_name_to_manage}' was disabled, attempting to enable and reload...", client.ui.colors.get("info", 0), effective_context)


            success = script_manager.reload_script(script_name_to_manage)
            if success:
                await client.add_message(f"Script '{script_name_to_manage}' reloaded successfully.", client.ui.colors.get("success", 0), effective_context)
            else:
                await client.add_message(f"Failed to reload script '{script_name_to_manage}'. It may now be unloaded. Check logs.", client.ui.colors.get("error", 0), effective_context)
    else:
        await client.add_message(f"Unknown /script subcommand: {subcommand}. Supported: list, load, unload, reload.", client.ui.colors.get("error", 0), effective_context)

# Command registration data
COMMAND_INFO = {
    "script": {
        "handler": handle_script_command,
        "help_text": {
            "usage": "/script [list|load <name>|unload <name>|reload <name>]",
            "description": "Manages PyRC scripts. Lists scripts or performs actions.",
            "long_description": (
                "The /script command allows runtime management of PyRC's Python scripts.\n"
                "Subcommands:\n"
                "  list          - Lists all found scripts and their current status (Loaded, Disabled, Not Loaded).\n"
                "  load <name>   - Loads a script that is currently disabled. The script must exist in the scripts directory.\n"
                "  unload <name> - Unloads an active script and disables it for the current session. The script's event handlers and commands will be removed.\n"
                "  reload <name> - Unloads and then immediately reloads a script. Useful for applying changes to a script without restarting PyRC. If the script was disabled, it will be enabled and reloaded."
            ),
            "examples": [
                "/script list",
                "/script load my_utility_script",
                "/script unload old_feature_script",
                "/script reload event_handler_script"
            ]
        },
        "aliases": ["scripts"],
        "category": "utility" # Assuming a 'utility' category exists or is appropriate
    }
}

# This function will be called by the command handler to register commands
def register_commands(command_handler) -> None:
    for cmd_name, cmd_data in COMMAND_INFO.items():
        command_handler.register_command(
            cmd_name,
            cmd_data["handler"],
            cmd_data["help_text"],
            aliases=cmd_data.get("aliases", []),
            category=cmd_data.get("category", "utility")
        )

# Need to import os for listdir in handle_script_command's list subcommand
import os
