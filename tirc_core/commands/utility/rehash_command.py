# commands/utility/rehash_command.py
import logging
from typing import TYPE_CHECKING, cast

from tirc_core.logging.channel_logger import ChannelLoggerManager # Import for re-initialization
from tirc_core.client.ui_manager import UIManager # For cast
from tirc_core.client.curses_manager import CursesManager # For re-initialization

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    # from tirc_core.client.dummy_ui import DummyUI # Not needed for cast target

logger = logging.getLogger("tirc.commands.utility.rehash")

COMMAND_DEFINITIONS = [
    {
        "name": "rehash",
        "handler": "handle_rehash_command",
        "help": {
            "usage": "/rehash",
            "description": "Reloads the client configuration, scripts, and triggers from disk.",
            "aliases": []
        }
    }
]

async def handle_rehash_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /rehash command."""
    active_context_name = client.context_manager.active_context_name or "Status"

    await client.add_status_message("Rehashing configuration, scripts, and triggers...", "system")
    logger.info("Rehash command initiated by user.")

    config_rehashed = False
    if hasattr(client.config, 'rehash') and callable(client.config.rehash):
        if client.config.rehash():
            config_rehashed = True
            logger.info("AppConfig rehashed successfully.")
            if client.channel_logger_manager:
                # Re-initialize ChannelLoggerManager with the new config
                client.channel_logger_manager = ChannelLoggerManager(client.config)
                logger.info("ChannelLoggerManager re-initialized with new config.")
            if client.dcc_manager:
                 client.dcc_manager.dcc_config = client.dcc_manager._load_dcc_config()
                 logger.info("DCC configuration reloaded within DCCManager.")
        else:
            logger.error("Failed to rehash AppConfig.")
            await client.add_status_message("Error rehashing main configuration. Check logs.", "error")
    else:
        logger.error("AppConfig does not have a rehash method.")
        await client.add_status_message("Configuration reloading mechanism not available.", "error")

    scripts_reloaded = False
    if client.script_manager:
        try:
            logger.info("Rehashing scripts...")
            cli_disabled_scripts = set(client.args.disable_script if hasattr(client.args, "disable_script") and client.args.disable_script else [])
            config_disabled_scripts = client.config.disabled_scripts if client.config.disabled_scripts else set()
            client.script_manager.disabled_scripts = cli_disabled_scripts.union(config_disabled_scripts)

            client.script_manager.scripts.clear()
            client.script_manager.event_subscriptions.clear()

            # Clear script commands from CommandHandler
            if hasattr(client.command_handler, 'script_commands'):
                 client.command_handler.script_commands.clear()
            if hasattr(client.command_handler, 'script_command_aliases'):
                 client.command_handler.script_command_aliases.clear()

            client.script_manager.load_scripts()
            scripts_reloaded = True
            logger.info("Scripts rehashed successfully.")
        except Exception as e:
            logger.error(f"Error rehashing scripts: {e}", exc_info=True)
            await client.add_status_message(f"Error reloading scripts: {e}", "error")

    triggers_rehashed = False
    if client.trigger_manager and client.config.enable_trigger_system:
        try:
            logger.info("Rehashing triggers...")
            client.trigger_manager.triggers.clear()
            client.trigger_manager.load_triggers()
            triggers_rehashed = True
            logger.info("Triggers rehashed successfully.")
        except Exception as e:
            logger.error(f"Error rehashing triggers: {e}", exc_info=True)
            await client.add_status_message(f"Error reloading triggers: {e}", "error")
    elif not client.config.enable_trigger_system and client.trigger_manager:
        logger.info("Trigger system is now disabled via rehash. Clearing existing triggers.")
        client.trigger_manager.triggers.clear()
        triggers_rehashed = True

    ui_colors_reinitialized = False
    if not client.is_headless:
        ui_manager_instance = cast(UIManager, client.ui) # Cast to UIManager
        if hasattr(ui_manager_instance, 'curses_manager') and ui_manager_instance.curses_manager:
            try:
                logger.info("Re-initializing UI colors from new configuration...")
                # Re-initialize CursesManager on the UIManager instance
                ui_manager_instance.curses_manager = CursesManager(ui_manager_instance.stdscr, client.config)
                ui_manager_instance.colors = ui_manager_instance.curses_manager.colors

                if hasattr(ui_manager_instance, 'window_layout_manager') and ui_manager_instance.window_layout_manager:
                    ui_manager_instance.window_layout_manager.colors = ui_manager_instance.colors

                ui_colors_reinitialized = True
                logger.info("UI colors re-initialized.")
                client.ui_needs_update.set()
            except Exception as e:
                logger.error(f"Error re-initializing UI colors: {e}", exc_info=True)
                await client.add_status_message(f"Error updating UI colors: {e}", "error")

    summary_parts = []
    if config_rehashed: summary_parts.append("config")
    if scripts_reloaded: summary_parts.append("scripts")
    if triggers_rehashed: summary_parts.append("triggers")
    if ui_colors_reinitialized: summary_parts.append("UI colors")

    if summary_parts:
        await client.add_status_message(f"Rehash complete for: {', '.join(summary_parts)}.", "success")
    else:
        await client.add_status_message("Rehash attempted, but no specific components confirmed reloaded. Check logs.", "warning")

    if not client.is_headless:
        client.ui_needs_update.set()
