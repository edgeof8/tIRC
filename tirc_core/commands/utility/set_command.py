# commands/utility/set_command.py
import logging
from typing import TYPE_CHECKING, Optional, List # Added List

# Specific imports needed for the /set command's logic
# Access config functions and properties via client.config

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    # If _ensure_args is to be called from command_handler instance via client:
    # from pyrc_core.commands.command_handler import CommandHandler

COMMAND_DEFINITIONS = [
    {
        "name": "set",
        "handler": "handle_set_command", # Name of the handler function in this module
        "help": {
            "usage": "/set [<section.key> [<value>]]",
            "description": "Views or modifies client configuration settings. "
                           "Without arguments, lists all settings. "
                           "With <section.key>, shows the value. "
                           "With <section.key> <value>, sets the value.",
            "aliases": ["se"]
        }
    }
]
logger = logging.getLogger("pyrc.commands.set") # Specific logger for this command

async def handle_set_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /set command."""
    # Note: This logic is moved from CommandHandler._handle_set_command
    # 'self' is replaced by 'client' where appropriate.

    help_data = client.script_manager.get_help_text_for_command("set")
    usage_msg = (
        help_data["help_text"]
        if help_data
        else "Usage: /set [<section.key> [<value>]]"
    )
    active_context_name = (
        client.context_manager.active_context_name or "Status"
    )
    # Use semantic color keys directly, as client.add_message now handles resolution
    system_color_key = "system"
    error_color_key = "error"

    stripped_args = args_str.strip()

    if not stripped_args:
        all_settings = client.config.get_all_settings()
        if not all_settings:
            await client.add_message(
                "No settings found.", client.ui.colors.get(system_color_key, 0), context_name=active_context_name
            )
            return

        await client.add_message(
            "Current settings (use /help set for usage):",
            client.ui.colors.get(system_color_key, 0),
            context_name=active_context_name,
        )
        for section, settings_in_section in all_settings.items():
            await client.add_message(
                f"[{section}]", client.ui.colors.get(system_color_key, 0), context_name=active_context_name
            )
            for key, val in settings_in_section.items():
                await client.add_message(
                    f"  {key} = {val}",
                    client.ui.colors.get(system_color_key, 0),
                    context_name=active_context_name,
                )
        return

    parts = stripped_args.split(" ", 1)
    variable_arg = parts[0]

    if len(parts) == 1: # Handle /set <variable>
        section_name_filter: Optional[str] = None
        key_name_filter: str = variable_arg

        if "." in variable_arg:
            try:
                section_name_filter, key_name_filter = variable_arg.split(".", 1)
                if not section_name_filter or not key_name_filter: # Ensure both parts are non-empty
                    raise ValueError("Section or key part is empty.")
            except ValueError:
                await client.add_message(
                    f"Invalid format for variable: '{variable_arg}'. Use 'key' or 'section.key'.",
                    client.ui.colors.get(error_color_key, 0),
                    context_name=active_context_name,
                )
                return

        found_settings_messages = []
        all_current_settings = client.config.get_all_settings() # Fetch all settings

        if section_name_filter: # If 'section.key' was provided
            # Check if the specific section and key exist
            if section_name_filter in all_current_settings and \
               key_name_filter in all_current_settings[section_name_filter]:
                value = all_current_settings[section_name_filter][key_name_filter]
                found_settings_messages.append(
                    f"{section_name_filter}.{key_name_filter} = {value}"
                )
            else: # Specific section.key not found
                await client.add_message(
                    f"Setting '{variable_arg}' not found.",
                    client.ui.colors.get(error_color_key, 0),
                    context_name=active_context_name,
                )
                return # Exit if specific setting not found
        else: # Only 'key' was provided, search in all sections
            for sec, settings_in_sec in all_current_settings.items():
                if key_name_filter in settings_in_sec:
                    found_settings_messages.append(
                        f"{sec}.{key_name_filter} = {settings_in_sec[key_name_filter]}"
                    )

        if not found_settings_messages:
            await client.add_message(
                f"Setting '{key_name_filter}' not found in any section.", # Adjusted message
                client.ui.colors.get(error_color_key, 0),
                context_name=active_context_name,
            )
        else:
            for setting_str in found_settings_messages:
                await client.add_message(
                    setting_str, client.ui.colors.get(system_color_key, 0), context_name=active_context_name
                )
        return

    elif len(parts) == 2: # Handle /set <variable> <value>
        value_arg = parts[1]

        if "." not in variable_arg: # Must be section.key for setting
            await client.add_message(
                "For setting a value, 'section.key' format is required.",
                client.ui.colors.get(error_color_key, 0),
                context_name=active_context_name,
            )
            await client.add_message(
                usage_msg, client.ui.colors.get(error_color_key, 0), context_name=active_context_name
            )
            return

        try:
            section_to_set, key_to_set = variable_arg.split(".", 1)
            if not section_to_set or not key_to_set: # Ensure both parts are non-empty
                raise ValueError("Section or key part is empty for setting.")
        except ValueError:
            await client.add_message(
                f"Invalid format for variable: '{variable_arg}'. Use 'section.key'.",
                client.ui.colors.get(error_color_key, 0),
                context_name=active_context_name,
            )
            return

        if client.config.set_config_value(section_to_set, key_to_set, value_arg):
            await client.add_message(
                f"Set {section_to_set}.{key_to_set} = {value_arg}",
                client.ui.colors.get(system_color_key, 0),
                context_name=active_context_name,
            )
            await client.add_message(
                "Note: Some settings may require an application restart to take full effect.",
                client.ui.colors.get(system_color_key, 0), # Use system color for notes
                context_name=active_context_name,
            )
        else:
            await client.add_message(
                f"Failed to set {section_to_set}.{key_to_set}.", # More specific error
                client.ui.colors.get(error_color_key, 0),
                context_name=active_context_name,
            )
        return

    # Fallback if argument parsing is unexpected (should ideally be caught by _ensure_args if used)
    # However, _ensure_args is not used in this standalone function for now.
    # The logic above should cover all valid /set command forms.
    # If execution reaches here, it's likely an invalid form not caught.
    await client.add_message(
        usage_msg, client.ui.colors.get(error_color_key, 0), context_name=active_context_name
    )
