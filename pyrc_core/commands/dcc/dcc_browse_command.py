# pyrc_core/commands/dcc/dcc_browse_command.py
import logging
import os
from typing import TYPE_CHECKING, List, Dict, Any

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.browse")

COMMAND_NAME = "browse"
COMMAND_ALIASES: List[str] = ["dir"]
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc browse [path]",
    "description": "Lists the contents of a local directory. Defaults to the current working directory if no path is provided.",
    "aliases": "dir"
}

async def _handle_dcc_error(client_logic: 'IRCClient_Logic', message: str, context_name: str, log_level: int = logging.ERROR, exc_info: bool = False):
    """Helper to log and display DCC command errors."""
    logger.log(log_level, message, exc_info=exc_info)
    await client_logic.add_message(message, client_logic.ui.colors["error"], context_name=context_name)

async def _ensure_dcc_context(client_logic: 'IRCClient_Logic', dcc_context_name: str):
    """Helper to ensure DCC context is active."""
    if client_logic.context_manager.active_context_name != dcc_context_name:
        await client_logic.switch_active_context(dcc_context_name)

async def handle_dcc_browse_command(client_logic: 'IRCClient_Logic', cmd_args: List[str], active_context_name: str, dcc_context_name: str):
    """
    Handles the /dcc browse command.
    Lists the contents of the specified local directory.
    """
    # No specific DCC config check needed for browse, it's a local FS operation.

    target_dir = " ".join(cmd_args) if cmd_args else "."
    try:
        abs_target_dir = os.path.abspath(target_dir)

        if not os.path.isdir(abs_target_dir):
            await _handle_dcc_error(client_logic, f"Error: '{target_dir}' (abs: {abs_target_dir}) is not a valid directory.", dcc_context_name)
            return

        await client_logic.add_message(f"Contents of '{abs_target_dir}':", client_logic.ui.colors["system"], context_name=dcc_context_name)
        items = []
        for item_name in sorted(os.listdir(abs_target_dir)):
            item_path = os.path.join(abs_target_dir, item_name)
            is_dir_marker = "[D] " if os.path.isdir(item_path) else "[F] "
            items.append(f"  {is_dir_marker}{item_name}")

        if not items:
            await client_logic.add_message("  (Directory is empty)", client_logic.ui.colors["system"], context_name=dcc_context_name)
        else:
            for item_line in items:
                await client_logic.add_message(item_line, client_logic.ui.colors["system"], context_name=dcc_context_name)

        await _ensure_dcc_context(client_logic, dcc_context_name)

    except PermissionError:
        await _handle_dcc_error(client_logic, f"Error browsing '{target_dir}': Permission denied.", dcc_context_name, log_level=logging.WARNING)
    except FileNotFoundError:
        await _handle_dcc_error(client_logic, f"Error browsing '{target_dir}': Directory not found.", dcc_context_name, log_level=logging.WARNING)
    except Exception as e:
        await _handle_dcc_error(client_logic, f"Error processing /dcc {COMMAND_NAME} for '{target_dir}': {e}", dcc_context_name, exc_info=True)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_function": handle_dcc_browse_command
    }
