# pyrc_core/commands/core/help_command.py
import logging
from typing import TYPE_CHECKING, List, Optional, Dict, Any, Union, Tuple

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.help")

COMMAND_DEFINITIONS = [
    {
        "name": "help",
        "handler": "handle_help_command",
        "help": {
            "usage": "/help [command_name|category|script <script_name>]",
            "description": "Displays general help, help for a specific command, category, or script.",
            "aliases": ["h"],
        },
    }
]

def format_help_text_for_display(help_data_from_manager: Dict[str, Any]) -> str:
    help_info = help_data_from_manager.get("help_info")
    if isinstance(help_info, dict):
        usage = help_info.get("usage", "N/A")
        description = help_info.get("description", "No description provided.")
        aliases_list = help_info.get("aliases", [])
        formatted_str = f"Usage: {usage}\n  Description: {description}"
        effective_aliases = aliases_list if aliases_list else help_data_from_manager.get("aliases", [])
        if effective_aliases:
            aliases_display = [f"/{a}" for a in effective_aliases]
            formatted_str += f"\n  Aliases: {', '.join(aliases_display)}"
        return formatted_str
    help_text_str = help_data_from_manager.get("help_text", "No help available.")
    output_lines = [help_text_str]
    manager_aliases = help_data_from_manager.get("aliases", [])
    if manager_aliases and "aliases:" not in help_text_str.lower():
        aliases_display = [f"/{a}" for a in manager_aliases]
        output_lines.append(f"  Aliases: {', '.join(aliases_display)}")
    return "\n".join(output_lines)

def get_summary_from_help_data(help_data_from_manager: Dict[str, Any]) -> str:
    help_info = help_data_from_manager.get("help_info")
    if isinstance(help_info, dict):
        description = help_info.get("description", "")
        if description: return description.split('\n')[0].strip()
        usage = help_info.get("usage", "No summary.")
        return usage.split('\n')[0].strip()
    help_text_str = help_data_from_manager.get("help_text", "No summary.")
    lines = help_text_str.split('\n')
    if len(lines) > 0 and lines[0].lower().startswith("usage:"):
        if len(lines) > 1 and lines[1].strip():
            if lines[1].strip().lower().startswith("description:"):
                 return lines[1].replace("Description:", "").strip().split('\n')[0]
            elif lines[1].startswith("  ") and not lines[1].lower().startswith("aliases:"):
                 return lines[1].strip().split('\n')[0]
        return lines[0].replace("Usage: ", "").strip()
    return lines[0].strip()

async def handle_help_command(client: "IRCClient_Logic", args_str: str):
    system_color = client.ui.colors["system"]
    error_color = client.ui.colors["error"]
    active_context_name = client.context_manager.active_context_name or "Status"
    args = args_str.strip().lower().split()
    target_arg1: Optional[str] = args[0] if len(args) > 0 else None
    target_arg2: Optional[str] = args[1] if len(args) > 1 else None

    # Case 1: General help (no arguments)
    if not target_arg1:
        await client.add_message("\nHelp Categories:", system_color, context_name=active_context_name)
        core_categories_map: Dict[str, str] = {
            "core": "Core Client", "channel": "Channel Ops", "information": "Information",
            "server": "Server/Connection", "ui": "User Interface", "user": "User Interaction", "utility": "Utilities"
        }
        active_core_categories = set()
        for cmd_name_loop, help_data_val_loop in client.command_handler.registered_command_help.items():
            if help_data_val_loop.get("is_alias"): continue
            module_path = help_data_val_loop.get("module_path", "")
            if module_path.startswith("pyrc_core.commands."): # Corrected check
                parts = module_path.split(".")
                if len(parts) > 2: # pyrc_core.commands.CATEGORY.module
                    cat_key = parts[2].lower() # Corrected index
                    if cat_key in core_categories_map:
                        active_core_categories.add(cat_key)
                    else:
                        logger.warning(f"Help: Unmapped category key '{cat_key}' from '{module_path}'. Defaulting to 'core'.")
                        if "core" in core_categories_map: active_core_categories.add("core")
                elif len(parts) == 2 and parts[1] == "commands": # Should not happen
                     logger.warning(f"Help: Module path '{module_path}' too short. Defaulting to 'core'.")
                     if "core" in core_categories_map: active_core_categories.add("core")

        if active_core_categories:
            await client.add_message("\nCore Command Categories:", system_color, context_name=active_context_name)
            for cat_key in sorted(list(active_core_categories)):
                await client.add_message(f"  /help {cat_key}  ({core_categories_map.get(cat_key, cat_key.title())})", system_color, context_name=active_context_name)
        else:
            await client.add_message("\nNo core command categories found (this is unexpected).", system_color, context_name=active_context_name)

        # Get all commands help, then filter for scripts
        all_commands_help = client.command_handler.get_all_commands_help()
        script_names_with_commands = set()
        for cmd_data_val in all_commands_help.values():
            if cmd_data_val.get("source") == "script" and not cmd_data_val.get("is_alias"):
                script_names_with_commands.add(cmd_data_val.get("script_name", "UnknownScript"))

        if script_names_with_commands:
            await client.add_message("\nScript Command Categories:", system_color, context_name=active_context_name)
            for script_name_raw in sorted(list(script_names_with_commands)):
                display_name = script_name_raw.replace("_", " ").title()
                await client.add_message(f"  /help script {script_name_raw}  ({display_name})", system_color, context_name=active_context_name)

        await client.add_message("\nUse /help <category_name>, /help script <script_name>, or /help <command> for more details.", system_color, context_name=active_context_name)
        return

    # Case 2: Help for scripts ("/help script" or "/help script <script_name>")
    if target_arg1 == "script":
        if not target_arg2: # Just "/help script"
            await client.add_message("Usage: /help script <script_name>", error_color, context_name=active_context_name)
            all_commands_help = client.command_handler.get_all_commands_help()
            available_scripts = set()
            for cmd_data_val in all_commands_help.values():
                if cmd_data_val.get("source") == "script" and not cmd_data_val.get("is_alias"):
                    available_scripts.add(cmd_data_val.get("script_name", "UnknownScript"))

            if available_scripts:
                await client.add_message("Available scripts with commands:", system_color, context_name=active_context_name)
                for script_name_key in sorted(list(available_scripts)):
                    await client.add_message(f"  {script_name_key}", system_color, context_name=active_context_name)
            else:
                await client.add_message("No scripts with registered commands found.", system_color, context_name=active_context_name)
            return

        # "/help script <script_name_arg>"
        script_name_arg_lower = target_arg2.lower()
        all_commands_help = client.command_handler.get_all_commands_help()
        commands_for_this_script: Dict[str, Dict[str, Any]] = {}

        found_script_name_display = None
        for cmd_name_key, cmd_data_val in all_commands_help.items():
            if cmd_data_val.get("source") == "script" and \
               cmd_data_val.get("script_name", "").lower() == script_name_arg_lower and \
               not cmd_data_val.get("is_alias"):
                commands_for_this_script[cmd_name_key] = cmd_data_val
                if not found_script_name_display: # Get the display name once
                    found_script_name_display = cmd_data_val.get("script_name", script_name_arg_lower).replace("_", " ").title()

        if commands_for_this_script and found_script_name_display:
            await client.add_message(f"\nCommands from script '{found_script_name_display}':", system_color, context_name=active_context_name)
            for cmd_name, cmd_data_dict in sorted(commands_for_this_script.items()):
                summary = get_summary_from_help_data(cmd_data_dict) # cmd_data_dict is already the help data
                await client.add_message(f"  /{cmd_name}: {summary}", system_color, context_name=active_context_name)
            await client.add_message("\nUse /help <command> for detailed help on a specific command.", system_color, context_name=active_context_name)
        else:
            await client.add_message(f"Script '{target_arg2}' not found or has no registered commands.", error_color, context_name=active_context_name)
        return

    # Case 3: Help for a core category
    core_categories_map_local: Dict[str, str] = {
        "core": "Core Client", "channel": "Channel Ops", "information": "Information",
        "server": "Server/Connection", "ui": "User Interface", "user": "User Interaction", "utility": "Utilities"
    }
    if target_arg1 in core_categories_map_local:
        category_to_list = target_arg1
        commands_to_display: List[Tuple[str, str]] = []
        display_category_name = core_categories_map_local.get(category_to_list, category_to_list.title())
        await client.add_message(f"\n{display_category_name} Commands:", system_color, context_name=active_context_name)

        for cmd_name, help_data_val in client.command_handler.registered_command_help.items():
            if help_data_val.get("is_alias"): continue
            module_path = help_data_val.get("module_path", "")
            cmd_category_key = "core" # Default
            if module_path.startswith("pyrc_core.commands."):
                parts = module_path.split(".")
                if len(parts) > 2: cmd_category_key = parts[2].lower()

            if cmd_category_key == category_to_list:
                help_info_for_summary = help_data_val.get("help_info", help_data_val.get("help_text", ""))
                summary_input_dict = {"help_text": help_data_val.get("help_text", ""), "help_info": help_info_for_summary}
                summary = get_summary_from_help_data(summary_input_dict)
                commands_to_display.append((cmd_name, summary))

        if not commands_to_display:
            await client.add_message(f"No commands found in category '{display_category_name}'.", system_color, context_name=active_context_name)
        else:
            for cmd_name, summary in sorted(commands_to_display):
                 await client.add_message(f"  /{cmd_name}: {summary}", system_color, context_name=active_context_name)
        await client.add_message("\nUse /help <command> for detailed help on a specific command.", system_color, context_name=active_context_name)
        return

    # Case 4: Help for a specific command
    cmd_to_get_help_for = target_arg1
    if cmd_to_get_help_for.startswith("/"):
        cmd_to_get_help_for = cmd_to_get_help_for[1:]

    # Use CommandHandler's method
    help_data = client.command_handler.get_help_text_for_command(cmd_to_get_help_for)
    if help_data:
        source_script_name = help_data.get('script_name', 'Unknown')
        source_type = help_data.get('source', 'unknown') # core, script, ini

        source_info_str = ""
        if source_type == "core":
            source_info_str = "(core command)"
        elif source_type == "script":
            source_info_str = f"(from script: {source_script_name})"
        elif source_type == "ini":
             source_info_str = f"(core_ini: {source_script_name})" # script_name might contain section for ini
        else:
            source_info_str = f"(source: {source_script_name})"


        await client.add_message(f"\nHelp for /{cmd_to_get_help_for} {source_info_str}:", system_color, context_name=active_context_name)
        formatted_help = format_help_text_for_display(help_data)
        await client.add_message(formatted_help, system_color, context_name=active_context_name)
    else:
        await client.add_message(f"No help available for command or category: {cmd_to_get_help_for}", error_color, context_name=active_context_name)
