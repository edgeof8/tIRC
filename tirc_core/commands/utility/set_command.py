# commands/utility/set_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.set") # Specific logger for this command

COMMAND_DEFINITIONS = [
    {
        "name": "set",
        "handler": "handle_set_command",
        "help": {
            "usage": "/set [<section.key> [<value>]]",
            "description": "Views or modifies client configuration settings. Saves changes to config file.",
            "aliases": ["se"]
        }
    }
]

async def handle_set_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /set command."""
    parts = args_str.split(" ", 1)
    key_full = parts[0] if parts else None
    value_str = parts[1] if len(parts) > 1 else None
    active_context_name = client.context_manager.active_context_name or "Status"

    if not key_full:
        # Display all settings or a summary
        all_settings = client.config.get_all_settings()
        await client.add_message("--- Current Configuration Settings ---", client.ui.colors.get("system_highlight", 0), context_name=active_context_name)
        for section, keys in all_settings.items():
            await client.add_message(f"[{section}]", client.ui.colors.get("system_highlight", 0), context_name=active_context_name)
            for k, v in keys.items():
                # Mask sensitive values like passwords
                display_v = v
                if "password" in k.lower() or "sasl_password" in k.lower():
                    display_v = "*******" if v else ""
                await client.add_message(f"  {k} = {display_v}", client.ui.colors.get("system", 0), context_name=active_context_name)
        await client.add_message("Use /set <section.key> to view a specific setting, or /set <section.key> <value> to change it.", client.ui.colors.get("info_dim", 0), context_name=active_context_name)
        return

    if "." not in key_full:
        await client.add_message("Invalid format. Use <section.key> (e.g., UI.colorscheme)", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    section, key = key_full.split(".", 1)

    if value_str is None:
        # View a specific setting
        current_value = client.config._get_config_value(section, key, None) # Use internal getter to bypass type conversion for display
        if current_value is not None:
            display_value = current_value
            if "password" in key.lower() or "sasl_password" in key.lower():
                 display_value = "*******" if current_value else ""
            await client.add_message(f"{section}.{key} = {display_value}", client.ui.colors.get("system", 0), context_name=active_context_name)
        else:
            await client.add_message(f"Setting {section}.{key} not found.", client.ui.colors.get("error", 0), context_name=active_context_name)
    else:
        # Modify a setting
        # Note: AppConfig.set_config_value saves immediately.
        # We might want to rehash or notify components if the change is critical.
        if client.config.set_config_value(section, key, value_str):
            await client.add_message(f"Set {section}.{key} to '{value_str}'. Use /rehash if needed.", client.ui.colors.get("success", 0), context_name=active_context_name)
            # Optionally, re-apply the specific setting if possible without full rehash
            # This depends on how AppConfig is structured and used.
            # For example, if it's UI.colorscheme, we might want to tell UIManager to reload colors.
            # For now, a /rehash is the general advice.
        else:
            await client.add_message(f"Failed to set {section}.{key}.", client.ui.colors.get("error", 0), context_name=active_context_name)
