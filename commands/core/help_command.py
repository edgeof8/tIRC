# commands/core/help_command.py
import logging
from typing import TYPE_CHECKING, List, Optional, Dict, Any

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.help")

COMMAND_DEFINITIONS = [
    {
        "name": "help",
        "handler": "handle_help_command",
        "help": {
            "usage": "/help [command_name]",
            "description": "Displays general help or help for a specific command.",
            "aliases": ["h"]
        }
    }
]

def handle_help_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /help command."""
    system_color = client.ui.colors["system"]
    error_color = client.ui.colors["error"]
    active_context_name = client.context_manager.active_context_name

    if not args_str:
        # Show general help
        client.add_message(
            "\nAvailable commands:",
            system_color,
            context_name=active_context_name,
        )

        # Get all help texts from scripts
        help_texts_from_scripts = client.script_manager.get_all_help_texts()

        # Group commands by script
        commands_by_script: Dict[str, List[tuple[str, str]]] = {}
        for cmd, help_text_data in help_texts_from_scripts.items():
            if isinstance(help_text_data, dict):
                script_name_original = help_text_data.get("script_name", "UnknownScript")
                help_text_str = help_text_data.get("help_text", "")
            else: # Should ideally not happen if script_manager always returns dicts
                script_name_original = "script" # Fallback
                help_text_str = str(help_text_data)

            # If script_name_original is a generic fallback, group under 'core'
            # This helps avoid "Commands from script 'Script':" or "Commands from script 'UnknownScript':"
            # for INI-defined help entries not associated with a specific loaded script module.
            effective_group_name = script_name_original
            if script_name_original.lower() in ["script", "unknownscript", "core_ini_commands"]: # "core_ini_commands" could be a convention from script_manager
                effective_group_name = "core"


            if effective_group_name not in commands_by_script:
                commands_by_script[effective_group_name] = []
            commands_by_script[effective_group_name].append((cmd, help_text_str))

        # --- Merge help from registered_command_help (core commands) ---
        core_help_from_modules = {}
        # Access registered_command_help via client.command_handler
        for cmd_name, help_data_val in client.command_handler.registered_command_help.items():
            if not help_data_val.get("is_alias"):
                usage = help_data_val["help_text"].split('\n')[0]
                desc_parts = help_data_val["help_text"].split('\n  ', 1)
                summary = usage
                if len(desc_parts) > 1 and desc_parts[1]:
                    summary = desc_parts[1].split('\n')[0]

                core_help_from_modules[cmd_name] = {
                    "help_text": summary,
                    "script_name": help_data_val.get("module_path", "core") # Use module_path if available
                }

        if "core" not in commands_by_script:
            commands_by_script["core"] = []

        for cmd, h_data in core_help_from_modules.items():
            # Avoid duplicating if already added (e.g. if help was also in an old ini)
            if not any(c[0] == cmd for c in commands_by_script.get(h_data["script_name"], [])) and \
               not any(c[0] == cmd for c in commands_by_script.get("core", [])): # Check general core too

                # Decide where to put it. If module_path suggests a specific "script" group, use it.
                group_key = "core"
                if h_data["script_name"] != "core" and h_data["script_name"].startswith("commands."):
                    # Attempt to create a more user-friendly group name from module_path
                    # e.g., commands.utility.set_command -> utility
                    try:
                        group_key = h_data["script_name"].split('.')[1] # commands.CATEGORY.module -> CATEGORY
                    except IndexError:
                        group_key = "core_modules" # Fallback if structure is different

                if group_key not in commands_by_script:
                    commands_by_script[group_key] = []
                commands_by_script[group_key].append((cmd, h_data["help_text"]))


        # Display commands grouped by script/category
        sorted_group_names = sorted(commands_by_script.keys(), key=lambda x: (x != "core", x != "core_modules", x))

        for group_name in sorted_group_names:
            commands = commands_by_script[group_name]
            if not commands:
                continue

            display_group_name_final = group_name.replace("_", " ").title()

            if group_name == "core": # For /help itself
                 client.add_message(
                    "\nCore Commands:", system_color, context_name=active_context_name
                )
            # Check if group_name is one of our known command categories (derived from commands.* modules)
            # These categories are like "utility", "ui", "channel", "information", "server", "user".
            # "core_modules" is a fallback if category extraction fails for a commands.* module.
            known_core_categories = ["utility", "ui", "channel", "information", "server", "core_modules", "user"]
            if group_name in known_core_categories:
                 client.add_message(
                    f"\n{display_group_name_final} Commands:", system_color, context_name=active_context_name
                )
            # If not 'core' and not a known core category, it's assumed to be an actual script name
            # (e.g., "Default Fun Commands", "Ai Api Test Script")
            else:
                 client.add_message(
                    f"\nCommands from script '{display_group_name_final}':", system_color, context_name=active_context_name
                )

            for cmd, help_text in sorted(commands):
                summary = help_text.split("\n")[0] # Ensure it's a summary
                client.add_message(
                    f"/{cmd}: {summary}",
                    system_color,
                    context_name=active_context_name,
                )

        # Split-screen command help is now dynamically loaded.
        # The hardcoded section listing them has been removed.

        client.add_message(
            "\nUse /help <command> for detailed help on a specific command.",
            system_color,
            context_name=active_context_name,
        )
        return

    # Show help for specific command
    command_name_from_user = args_str.strip().lower()

    # Access registered_command_help via client.command_handler
    help_data = client.command_handler.registered_command_help.get(command_name_from_user)

    if not help_data: # If not a registered core command, check scripts
        help_data_script = client.script_manager.get_help_text_for_command(command_name_from_user)
        if help_data_script: # Ensure it's not None before trying to use it
             # Adapt script help data to a common format if necessary, or use as is
            help_data = {
                "help_text": help_data_script.get("help_text", "No description available."),
                "is_alias": help_data_script.get("is_alias", False),
                "primary_command": help_data_script.get("primary_command"),
                "script_name": help_data_script.get("script_name", "script") # Default to "script"
            }


    # Removed hardcoded if/elif for "split", "focus", "setpane"
    # Generic logic below will handle them via registered_command_help.

    if help_data:
        if help_data.get("is_alias"):
            primary_cmd = help_data.get("primary_command")
            client.add_message(
                f"(Showing help for '/{primary_cmd}', as '/{command_name_from_user}' is an alias)",
                system_color,
                context_name=active_context_name,
            )

        help_text_content = help_data.get("help_text", "")
        for line in help_text_content.splitlines():
            client.add_message(
                line, system_color, context_name=active_context_name
            )

        script_name_info = help_data.get("script_name")
        module_path_info = help_data.get("module_path")

        if module_path_info and module_path_info.startswith("commands."):
             # Try to get category like "utility" from "commands.utility.set_command"
            category = module_path_info.split('.')[1] if len(module_path_info.split('.')) > 1 else "core"
            client.add_message(
                f"(Core command from: {category.title()})",
                system_color,
                context_name=active_context_name,
            )
        elif script_name_info and script_name_info not in ["core", "UnknownScript"]:
            client.add_message(
                f"(Help from script: {script_name_info})",
                system_color,
                context_name=active_context_name,
            )
    else:
        client.add_message(
            f"No help available for command: {command_name_from_user}",
            error_color,
            context_name=active_context_name,
        )
