# START OF MODIFIED FILE: commands/core/help_command.py
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
    active_context_name = client.context_manager.active_context_name

    if not args_str:
        # logger.debug("--- handle_help_command: General Help ---") # Keep for actual debugging if needed
        client.add_message("\nAvailable commands:", system_color, context_name=active_context_name)

        commands_by_group: Dict[str, List[tuple[str, str]]] = {}
        core_categories = ["core", "channel", "information", "server", "ui", "user", "utility"]

        # logger.debug("Processing core commands from CommandHandler.registered_command_help...")
        for cmd_name, help_data_val in client.command_handler.registered_command_help.items():
            if help_data_val.get("is_alias"):
                continue
            module_path = help_data_val.get("module_path", "core")
            group_key = "core"
            if module_path.startswith("commands."):
                try:
                    category = module_path.split('.')[1].lower()
                    if category in core_categories: group_key = category
                    # logger.debug(f"Help core: cmd='{cmd_name}', module_path='{module_path}', derived_category='{category}', final_group_key='{group_key}'")
                except IndexError:
                    # logger.debug(f"Help core: cmd='{cmd_name}', module_path='{module_path}', IndexError, group_key='{group_key}'")
                    pass

            summary = get_summary_from_help_text(help_data_val["help_text"], is_core_format=True)
            if group_key not in commands_by_group: commands_by_group[group_key] = []
            if not any(c[0] == cmd_name for c in commands_by_group[group_key]):
                 commands_by_group[group_key].append((cmd_name, summary))

