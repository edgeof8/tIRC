# START OF MODIFIED FILE: commands/core/help_command.py
import logging
from typing import TYPE_CHECKING, List, Optional, Dict, Any

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

# logger = logging.getLogger("pyrc.commands.help") # Standard logger still useful

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

def get_summary_from_help_text(full_help_text: str, is_core_format: bool) -> str:
    usage_line = full_help_text.split('\n')[0]
    description_part = ""

    if is_core_format and '\n  ' in full_help_text:
        description_parts = full_help_text.split('\n  ', 1)
        if len(description_parts) > 1:
            description_part = description_parts[1].split('\n')[0]
    elif not is_core_format and '\n' in full_help_text:
         parts = full_help_text.split('\n', 1)
         if len(parts) > 1:
             description_part = parts[1].split('\n')[0].lstrip()

    return description_part if description_part else usage_line


def handle_help_command(client: "IRCClient_Logic", args_str: str):
    system_color = client.ui.colors["system"]
    error_color = client.ui.colors["error"]
    active_context_name = client.context_manager.active_context_name or "Status" # Default to Status for diagnostics if needed

    # Use a dedicated context for verbose debug output, or the active one
    debug_context = active_context_name

    if not args_str:
        client.add_message("\nAvailable commands:", system_color, context_name=active_context_name)

        commands_by_group: Dict[str, List[tuple[str, str]]] = {}
        core_categories = ["core", "channel", "information", "server", "ui", "user", "utility"]

        client.add_message(f"DEBUG_HELP: Processing core commands...", "debug", context_name=debug_context)
        for cmd_name, help_data_val in client.command_handler.registered_command_help.items():
            if help_data_val.get("is_alias"):
                continue
            module_path = help_data_val.get("module_path", "core")
            group_key = "core"
            if module_path.startswith("commands."):
                try:
                    category = module_path.split('.')[1].lower()
                    if category in core_categories: group_key = category
                except IndexError: pass

            summary = get_summary_from_help_text(help_data_val["help_text"], is_core_format=True)
            if group_key not in commands_by_group: commands_by_group[group_key] = []
            if not any(c[0] == cmd_name for c in commands_by_group[group_key]):
                 commands_by_group[group_key].append((cmd_name, summary))

        script_cmds_data = client.script_manager.get_all_script_commands_with_help()
        client.add_message(f"DEBUG_HELP: script_cmds_data: {str(script_cmds_data)[:500]}...", "debug", context_name=debug_context)


        for cmd_name, cmd_data_val in script_cmds_data.items():
            script_module_name = cmd_data_val.get("script_name", "UnknownScript")
            client.add_message(f"DEBUG_HELP: ScriptCmd: '{cmd_name}', ScriptName: '{script_module_name}'", "debug", context_name=debug_context)

            summary_script = get_summary_from_help_text(cmd_data_val.get("help_text", "No description."), is_core_format=False)

            is_core_cmd_already = False
            for core_cat_key in core_categories:
                if any(c[0] == cmd_name for c in commands_by_group.get(core_cat_key, [])):
                    is_core_cmd_already = True
                    break

            if not is_core_cmd_already:
                group_key_for_script = script_module_name
                if group_key_for_script not in commands_by_group:
                    commands_by_group[group_key_for_script] = []
                if not any(c[0] == cmd_name for c in commands_by_group[group_key_for_script]):
                    commands_by_group[group_key_for_script].append((cmd_name, summary_script))
                    client.add_message(f"DEBUG_HELP: Added '{cmd_name}' to group '{group_key_for_script}'", "debug", context_name=debug_context)

        category_display_titles = {cat: f"{cat.title()} Commands" for cat in core_categories}
        display_order_keys = core_categories[:]

        script_group_keys_from_data = sorted(
            [key for key in commands_by_group.keys() if key not in core_categories and commands_by_group.get(key)],
            key=lambda k: k.lower()
        )
        display_order_keys.extend(script_group_keys_from_data)
        client.add_message(f"DEBUG_HELP: Final display order: {display_order_keys}", "debug", context_name=debug_context)
        client.add_message(f"DEBUG_HELP: Full commands_by_group: {str(commands_by_group)[:500]}...", "debug", context_name=debug_context)


        for group_key_to_display in display_order_keys:
            commands_in_this_group = commands_by_group.get(group_key_to_display)
            if not commands_in_this_group: continue

            header_text = ""
            if group_key_to_display in category_display_titles:
                header_text = f"\n{category_display_titles[group_key_to_display]}:"
            else:
                script_display_name = group_key_to_display.replace("_", " ").title()
                header_text = f"\nCommands from script {script_display_name}:"

            client.add_message(header_text, system_color, context_name=active_context_name)

            for cmd, help_text_summary in sorted(commands_in_this_group, key=lambda x: x[0]):
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

    # Specific command help logic (ensure typo is fixed)
    command_name_from_user = args_str.strip().lower()
    help_data = client.command_handler.registered_command_help.get(command_name_from_user)

    if not help_data:
        help_data_script = client.script_manager.get_help_text_for_command(command_name_from_user)
        if help_data_script:
            help_data = {
                "help_text": help_data_script.get("help_text", "No description available."),
                "is_alias": help_data_script.get("is_alias", False), # Corrected typo
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
# END OF MODIFIED FILE: commands/core/help_command.py
