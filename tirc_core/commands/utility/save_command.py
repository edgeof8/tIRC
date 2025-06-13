# commands/utility/save_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.utility.save")

COMMAND_DEFINITIONS = [
    {
        "name": "save",
        "handler": "handle_save_command",
        "help": {
            "usage": "/save [config|state|triggers|all]",
            "description": "Saves client data. 'config' saves main settings, 'state' saves session state, 'triggers' saves /on events. 'all' or no argument saves everything.",
            "aliases": []
        }
    }
]

async def handle_save_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /save command."""
    target_to_save = args_str.strip().lower()
    if not target_to_save:
        target_to_save = "all" # Default to saving all components

    active_context_name = client.context_manager.active_context_name or "Status"
    saved_components = []
    errors = []

    if target_to_save in ["config", "all"]:
        if hasattr(client.config, 'save_current_config') and callable(client.config.save_current_config):
            if client.config.save_current_config():
                saved_components.append("configuration (tirc_config.ini)")
            else:
                errors.append("configuration (tirc_config.ini)")
        else:
            logger.error("AppConfig does not have a save_current_config method.")
            errors.append("configuration (mechanism unavailable)")

    if target_to_save in ["state", "all"]:
        if client.state_manager:
            # StateManager's _save_state is called by its shutdown or auto-save.
            # For an explicit /save state, we can call it directly.
            # It's a private method, but for a direct user command, this might be acceptable.
            # Alternatively, StateManager could expose a public save() method.
            try:
                client.state_manager._save_state() # Calling private method
                saved_components.append("client state (state.json)")
            except Exception as e:
                logger.error(f"Error explicitly saving client state: {e}", exc_info=True)
                errors.append(f"client state ({e})")
        else:
            errors.append("client state (manager unavailable)")


    if target_to_save in ["triggers", "all"]:
        if client.trigger_manager and client.config.enable_trigger_system:
            try:
                client.trigger_manager._save_triggers_to_file() # Calling private method
                saved_components.append("triggers (triggers.json)")
            except Exception as e:
                logger.error(f"Error saving triggers: {e}", exc_info=True)
                errors.append(f"triggers ({e})")
        elif not client.config.enable_trigger_system:
            # Not an error, just info that triggers aren't saved if system is off
            logger.info("Trigger system is disabled, not saving triggers.")
        else:
            errors.append("triggers (manager unavailable)")

    if saved_components:
        await client.add_status_message(f"Successfully saved: {', '.join(saved_components)}.", "success")

    if errors:
        await client.add_status_message(f"Failed to save: {', '.join(errors)}.", "error")

    if not saved_components and not errors:
        if target_to_save == "all" or target_to_save in ["config", "state", "triggers"]:
             await client.add_status_message(f"No specific action taken for saving '{target_to_save}'. Check component availability or logs.", "warning")
        else:
            await client.add_status_message(f"Unknown save target: '{target_to_save}'. Use 'config', 'state', 'triggers', or 'all'.", "error")
