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

        commands_by_group: Dict[str, List[tuple[str, str]]] = {}

        # 1. Process commands from CommandHandler.registered_command_help (dynamically loaded core modules)
        for cmd_name, help_data_val in client.command_handler.registered_command_help.items():
            if help_data_val.get("is_alias"):
                continue

            module_path = help_data_val.get("module_path", "core")
            group_key = "core"  # Default
            if module_path.startswith("commands."):
                parts = module_path.split('.')
                if len(parts) > 1:  # commands.CATEGORY.module
                    group_key = parts[1].lower()  # "utility", "ui", "user", etc.

            full_help_text = help_data_val["help_text"]
            usage_line = full_help_text.split('\n')[0]
            description_part = ""
            if '\n  ' in full_help_text:
                description_parts = full_help_text.split('\n  ', 1)
                if len(description_parts) > 1:
                    description_part = description_parts[1].split('\n')[0]

            summary = description_part if description_part else usage_line

            if group_key not in commands_by_group:
                commands_by_group[group_key] = []
            # Avoid adding if already present from a script that might have registered it (less likely for core)
            if not any(c[0] == cmd_name for c in commands_by_group[group_key]):
                 commands_by_group[group_key].append((cmd_name, summary))


        # 2. Process commands from ScriptManager (scripts)
        script_cmds_data = client.script_manager.get_all_script_commands_with_help()
        for cmd_name, cmd_data_val in script_cmds_data.items():
            script_module_name = cmd_data_val.get("script_name", "UnknownScript")

            help_text_from_script = cmd_data_val.get("help_text", "No description.")
            usage_line_script = help_text_from_script.split('\n')[0]
            description_part_script = ""
            if '\n' in help_text_from_script:
                 parts = help_text_from_script.split('\n', 1)
                 if len(parts) > 1:
                     if parts[1].startswith("  "): # Respect "  " for description indent
                         description_part_script = parts[1].lstrip().split('\n')[0]
                     else: # Assume next line is description start
                         description_part_script = parts[1].split('\n')[0]
            summary_script = description_part_script if description_part_script else usage_line_script

            # Ensure script commands are grouped under their script name
            # And don't override core commands if a script defines a command with the same name
            # by checking if cmd_name is already in any of the core category groups.
            is_core_cmd_already = False
            core_category_keys = ["core", "channel", "information", "server", "ui", "user", "utility", "core_modules"]
            for core_cat_key in core_category_keys:
                if any(c[0] == cmd_name for c in commands_by_group.get(core_cat_key, [])):
                    is_core_cmd_already = True
                    logger.debug(f"Help: Command '{cmd_name}' from script '{script_module_name}' conflicts with a core command. Script help summary not added to general list.")
                    break

            if not is_core_cmd_already:
                if script_module_name not in commands_by_group:
                    commands_by_group[script_module_name] = []
                commands_by_group[script_module_name].append((cmd_name, summary_script))

        # Display logic
        category_display_titles = {
            "core": "Core Commands",
            "channel": "Channel Commands",
            "information": "Information Commands",
            "server": "Server Commands",
            "ui": "Ui Commands",
            "user": "User Commands",
            "utility": "Utility Commands",
            "core_modules": "Core Modules Commands"
        }

        all_group_keys_from_data = list(commands_by_group.keys())

        ordered_category_keys_to_display = []
        processed_keys_for_ordering = set()

        for cat_key_lower in ["core", "channel", "information", "server", "ui", "user", "utility", "core_modules"]:
            if cat_key_lower in all_group_keys_from_data and cat_key_lower not in processed_keys_for_ordering:
                ordered_category_keys_to_display.append(cat_key_lower)
                processed_keys_for_ordering.add(cat_key_lower)

        script_group_keys_to_display = sorted([
            key for key in all_group_keys_from_data
            if key not in processed_keys_for_ordering
        ], key=lambda k: k.lower())

        final_sorted_group_keys_for_display = ordered_category_keys_to_display + script_group_keys_to_display

        for group_key_actual in final_sorted_group_keys_for_display:
            commands = commands_by_group[group_key_actual]
            if not commands:
                continue

            header_text = ""
            group_key_lookup = group_key_actual.lower()

            if group_key_lookup in category_display_titles:
                header_text = f"\n{category_display_titles[group_key_lookup]}:"
            else:
                script_display_name = group_key_actual.replace("_", " ").title()
                header_text = f"\nCommands from script {script_display_name}:"

            client.add_message(header_text, system_color, context_name=active_context_name)

            for cmd, help_text_summary in sorted(commands, key=lambda x: x[0]):
                client.add_message(
                    f"/{cmd}: {help_text_summary}",
                    system_color,
                    context_name=active_context_name,
                )

        client.add_message(
            "\nUse /help <command> for detailed help on a specific command.",
            system_color,
            context_name=active_context_name,
        )
        return

    # Specific command help logic (remains largely the same)
    command_name_from_user = args_str.strip().lower()
    help_data = client.command_handler.registered_command_help.get(command_name_from_user)

    if not help_data:
        help_data_script = client.script_manager.get_help_text_for_command(command_name_from_user)
        if help_data_script:
            help_data = {
                "help_text": help_data_script.get("help_text", "No description available."),
                "is_alias": help_data_script.get("is_alias", False),
                "primary_command": help_data_script.get("primary_command"),
                "script_name": help_data_script.get("script_name", "script"),
                "module_path": help_data_script.get("module_path")
            }

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
            category = module_path_info.split('.')[1].title() if len(module_path_info.split('.')) > 1 else "Core"
            client.add_message(
                f"(Core command from: {category})",
                system_color,
                context_name=active_context_name,
            )
        elif script_name_info and script_name_info not in ["core", "UnknownScript", "script"]:
             script_display_name = script_name_info.replace("_", " ").title()
             client.add_message(
                f"(Help from script: {script_display_name})",
                system_color,
                context_name=active_context_name,
            )
    else:
        client.add_message(
            f"No help available for command: {command_name_from_user}",
            error_color,
            context_name=active_context_name,
        )
