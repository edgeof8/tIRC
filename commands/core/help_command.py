# START OF MODIFIED FILE: commands/core/help_command.py
import logging
from typing import TYPE_CHECKING, List, Optional, Dict, Any, Union, Tuple

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

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
    """
    Formats the structured help data obtained from ScriptManager/CommandHandler
    into a user-friendly display string.
    'help_data_from_manager' is the dict returned by get_help_text_for_command.
    It contains 'help_text' (already formatted string from dict or original string)
    and 'help_info' (the original dict or string).
    """
    help_info = help_data_from_manager.get("help_info")

    if isinstance(help_info, dict):
        usage = help_info.get("usage", "N/A")
        description = help_info.get("description", "No description provided.")
        aliases_list = help_info.get("aliases", []) # Aliases from the help_info dict

        formatted_str = f"Usage: {usage}\n  Description: {description}"
        # Use aliases from help_info if they exist, otherwise from the main help_data_from_manager
        effective_aliases = aliases_list if aliases_list else help_data_from_manager.get("aliases", [])

        if effective_aliases:
            aliases_display = [f"/{a}" for a in effective_aliases]
            formatted_str += f"\n  Aliases: {', '.join(aliases_display)}"
        return formatted_str

    help_text_str = help_data_from_manager.get("help_text", "No help available.")
    output_lines = [help_text_str]
    manager_aliases = help_data_from_manager.get("aliases", [])
    if manager_aliases:
        # Check if "Aliases: " is already in the help_text_str to avoid duplication
        # This is a simple check; more robust parsing might be needed if formats vary widely.
        if "aliases:" not in help_text_str.lower():
            aliases_display = [f"/{a}" for a in manager_aliases]
            output_lines.append(f"  Aliases: {', '.join(aliases_display)}")

    return "\n".join(output_lines)

def get_summary_from_help_data(help_data_from_manager: Dict[str, Any]) -> str:
    """
    Extracts a summary from the structured help data obtained from ScriptManager/CommandHandler.
    """
    help_info = help_data_from_manager.get("help_info")

    if isinstance(help_info, dict):
        description = help_info.get("description", "")
        if description:
            return description.split('\n')[0].strip()
        usage = help_info.get("usage", "No summary.")
        return usage.split('\n')[0].strip()

    help_text_str = help_data_from_manager.get("help_text", "No summary.")
    lines = help_text_str.split('\n')

    # Try to get a meaningful summary from potentially multi-line help_text
    if len(lines) > 0 and lines[0].lower().startswith("usage:"):
        # If usage is short, use it. If description follows, prefer that.
        if len(lines) > 1 and lines[1].strip(): # Check if there's a second line
            # Check if the second line looks like a description (e.g., indented or starts with "Description:")
            # This is heuristic.
            if lines[1].strip().lower().startswith("description:"):
                 return lines[1].replace("Description:", "").strip().split('\n')[0]
            elif lines[1].startswith("  ") and not lines[1].lower().startswith("aliases:"): # Core command style
                 return lines[1].strip().split('\n')[0]
        return lines[0].replace("Usage: ", "").strip() # Fallback to usage content
    return lines[0].strip() # Default to the first line

def handle_help_command(client: "IRCClient_Logic", args_str: str):
    system_color = client.ui.colors["system"]
    error_color = client.ui.colors["error"]
    active_context_name = client.context_manager.active_context_name or "Status"

    args = args_str.strip().lower().split()

    target_arg1: Optional[str] = args[0] if len(args) > 0 else None
    target_arg2: Optional[str] = args[1] if len(args) > 1 else None

    if not target_arg1:
        client.add_message("\nHelp Categories:", system_color, context_name=active_context_name)
        core_categories_map: Dict[str, str] = {
            "core": "Core Client", "channel": "Channel Ops", "information": "Information",
            "server": "Server/Connection", "ui": "User Interface", "user": "User Interaction", "utility": "Utilities"
        }
        active_core_categories = set()
        for cmd_name_loop, help_data_val_loop in client.command_handler.registered_command_help.items():
            if help_data_val_loop.get("is_alias"): continue
            module_path = help_data_val_loop.get("module_path", "core")
            if module_path.startswith("commands."):
                try:
                    cat_key = module_path.split(".")[1].lower()
                    if cat_key in core_categories_map: active_core_categories.add(cat_key)
                except IndexError:
                    if "core" in core_categories_map: active_core_categories.add("core")
            elif module_path == "core": # Default for commands not in subdirs
                 if "core" in core_categories_map: active_core_categories.add("core")

        if active_core_categories:
             client.add_message("\nCore Command Categories:", system_color, context_name=active_context_name)
             for cat_key in sorted(list(active_core_categories)):
                 client.add_message(f"  /help {cat_key}  ({core_categories_map.get(cat_key, cat_key.title())})", system_color, context_name=active_context_name)

        script_commands_by_script = client.script_manager.get_all_script_commands_with_help()
        if script_commands_by_script:
            client.add_message("\nScript Command Categories:", system_color, context_name=active_context_name)
            for script_name_raw in sorted(script_commands_by_script.keys()):
                display_name = script_name_raw.replace("_", " ").title()
                client.add_message(f"  /help script {script_name_raw}  ({display_name})", system_color, context_name=active_context_name)

        client.add_message("\nUse /help <category_name>, /help script <script_name>, or /help <command> for more details.", system_color, context_name=active_context_name)
        return

    is_script_category_help = target_arg1 == "script"

    if is_script_category_help:
        if not target_arg2:
            client.add_message("Usage: /help script <script_name>", error_color, context_name=active_context_name)
            return
        category_to_list = target_arg2
    elif target_arg1 in ["core", "channel", "information", "server", "ui", "user", "utility"]:
        category_to_list = target_arg1
    else: # Argument is likely a command name for specific help
        cmd_to_get_help_for = target_arg1
        if cmd_to_get_help_for.startswith("/"):
            cmd_to_get_help_for = cmd_to_get_help_for[1:]

        # First, check core commands (which includes aliases resolved by CommandHandler)
        # ScriptManager.get_help_text_for_command handles both core and script, prioritizing script.
        # We need to ensure core command help is also checked if script manager doesn't find it.

        # Let ScriptManager try first, as it has combined knowledge
        help_data = client.script_manager.get_help_text_for_command(cmd_to_get_help_for)

        if help_data:
            source_info = f"(from script: {help_data.get('script_name', 'Unknown')})" if help_data.get('script_name') != 'core' else "(core command)"
            client.add_message(f"\nHelp for /{cmd_to_get_help_for} {source_info}:", system_color, context_name=active_context_name)
            formatted_help = format_help_text_for_display(help_data)
            client.add_message(formatted_help, system_color, context_name=active_context_name)
        else:
            client.add_message(f"No help available for command or category: {cmd_to_get_help_for}", error_color, context_name=active_context_name)
        return

    # This block is for listing commands within a category
    commands_to_display: List[Tuple[str, str]] = []
    if is_script_category_help:
        script_commands = client.script_manager.get_all_script_commands_with_help()
        normalized_category_key = category_to_list # Already lowercased by initial arg processing

        found_script_name_key = None
        for sn_key in script_commands.keys():
            if sn_key.lower() == normalized_category_key:
                found_script_name_key = sn_key
                break

        if found_script_name_key and found_script_name_key in script_commands:
            script_display_name = found_script_name_key.replace("_", " ").title()
            client.add_message(f"\nCommands from script '{script_display_name}':", system_color, context_name=active_context_name)
            for cmd_name, cmd_data_dict in sorted(script_commands[found_script_name_key].items()):
                summary = get_summary_from_help_data(cmd_data_dict)
                commands_to_display.append((cmd_name, summary))
        else:
            client.add_message(f"Script category '{category_to_list}' not found.", error_color, context_name=active_context_name)
            return
    else: # Core category
        if category_to_list == "core":
            client.add_message(f"\nCore Commands:", system_color, context_name=active_context_name)
            for cmd_name, help_data_val in client.command_handler.registered_command_help.items():
                if help_data_val.get("is_alias"): continue
                if help_data_val.get("script_name") == "core":
                    summary_input_dict = {"help_text": help_data_val["help_text"], "help_info": help_data_val["help_text"]}
                    summary = get_summary_from_help_data(summary_input_dict)
                    commands_to_display.append((cmd_name, summary))
        else:
            client.add_message(f"\n{category_to_list.title()} Commands:", system_color, context_name=active_context_name)
            for cmd_name, help_data_val in client.command_handler.registered_command_help.items():
                if help_data_val.get("is_alias"): continue
                module_path = help_data_val.get("module_path", "core")
                cmd_category_key = "core"
                if module_path.startswith("commands."):
                    try:
                        cmd_category_key = module_path.split(".")[1].lower()
                    except IndexError:
                        pass
                if cmd_category_key == category_to_list:
                    summary_input_dict = {"help_text": help_data_val["help_text"], "help_info": help_data_val["help_text"]}
                    summary = get_summary_from_help_data(summary_input_dict)
                    commands_to_display.append((cmd_name, summary))

    if not commands_to_display:
        client.add_message(f"No commands found in category '{category_to_list}'.", system_color, context_name=active_context_name)
    else:
        for cmd_name, summary in sorted(commands_to_display):
             client.add_message(f"  /{cmd_name}: {summary}", system_color, context_name=active_context_name)
    client.add_message("\nUse /help <command> for detailed help on a specific command.", system_color, context_name=active_context_name)

# END OF MODIFIED FILE: commands/core/help_command.py
