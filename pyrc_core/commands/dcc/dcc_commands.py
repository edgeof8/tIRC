# pyrc_core/commands/dcc/dcc_commands.py # Pylance re-evaluation
import logging
import importlib
import os
from typing import TYPE_CHECKING, Dict, Any, Callable, List, cast

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.router")

# Dictionary to store DCC subcommand handlers
# Key: subcommand name (str), Value: Dict with 'handler_function', 'help', 'aliases'
_dcc_subcommand_handlers: Dict[str, Dict[str, Any]] = {}
_dcc_subcommand_aliases: Dict[str, str] = {}

def _load_dcc_subcommands():
    """Dynamically loads DCC subcommand handlers from this directory."""
    global _dcc_subcommand_handlers, _dcc_subcommand_aliases
    if _dcc_subcommand_handlers: # Avoid re-loading if already populated
        return

    current_dir = os.path.dirname(os.path.abspath(__file__))
    for filename in os.listdir(current_dir):
        if filename.endswith("_command.py") and filename != "dcc_commands.py" and filename != "dcc_command_base.py":
            module_name = f"pyrc_core.commands.dcc.{filename[:-3]}"
            try:
                module = importlib.import_module(module_name)
                if hasattr(module, "get_dcc_command_handler") and callable(module.get_dcc_command_handler):
                    handler_info = cast(Dict[str, Any], module.get_dcc_command_handler())
                    sub_cmd_name = handler_info["name"].lower()
                    _dcc_subcommand_handlers[sub_cmd_name] = handler_info
                    logger.debug(f"Registered DCC subcommand '{sub_cmd_name}' from {module_name}")
                    for alias in handler_info.get("aliases", []):
                        _dcc_subcommand_aliases[alias.lower()] = sub_cmd_name
                        logger.debug(f"Registered DCC subcommand alias '{alias.lower()}' -> '{sub_cmd_name}'")
            except Exception as e:
                logger.error(f"Failed to load DCC subcommand module {module_name}: {e}", exc_info=True)

_load_dcc_subcommands() # Load them when this module is imported

async def dcc_command_router(client_logic: 'IRCClient_Logic', args_str: str):
    """
    Main dispatcher for /dcc subcommands.
    Routes to the appropriate handler function.
    """
    args = args_str.split()
    active_context_name = client_logic.context_manager.active_context_name or "Status"
    dcc_context_name = "DCC" # Standard context for DCC operations

    # Ensure DCC context exists (important for feedback messages)
    if not client_logic.context_manager.get_context(dcc_context_name):
        client_logic.context_manager.create_context(dcc_context_name, context_type="dcc")


    if not hasattr(client_logic, 'dcc_manager') or not client_logic.dcc_manager:
        await client_logic.add_message("DCC system is not initialized or available.", client_logic.ui.colors["error"], context_name=active_context_name)
        return

    if not args:
        # Display general DCC help or list of subcommands
        help_lines = [
            "Usage: /dcc <subcommand> [options...]",
            "Available subcommands:"
        ]
        for name, info in sorted(_dcc_subcommand_handlers.items()):
            usage_summary = info.get("help", {}).get("usage", f"/dcc {name}")
            help_lines.append(f"  {usage_summary}")
        help_lines.append("Try /dcc <subcommand> --help (or similar if supported by subcommand) or check main /help dcc.")
        for line in help_lines:
            await client_logic.add_message(line, client_logic.ui.colors["system"], context_name=active_context_name)
        return

    subcommand_name_input = args[0].lower()
    cmd_args = args[1:]

    # Resolve alias if any
    actual_subcommand_name = _dcc_subcommand_aliases.get(subcommand_name_input, subcommand_name_input)

    if actual_subcommand_name in _dcc_subcommand_handlers:
        handler_info = _dcc_subcommand_handlers[actual_subcommand_name]
        handler_function: Callable = handler_info["handler_function"]
        try:
            # Pass client_logic, command arguments, active_context_name, and dcc_context_name
            await handler_function(client_logic, cmd_args, active_context_name, dcc_context_name)
        except Exception as e:
            logger.error(f"Error executing DCC subcommand '{actual_subcommand_name}': {e}", exc_info=True)
            await client_logic.add_message(f"Error in /dcc {actual_subcommand_name}: {e}", client_logic.ui.colors["error"], context_name=dcc_context_name)
    else:
        await client_logic.add_message(f"Unknown DCC subcommand: {subcommand_name_input}. Try '/dcc' for a list.", client_logic.ui.colors["error"], context_name=active_context_name)

# This is the main command definition for /dcc itself, registered with the global CommandHandler
COMMAND_DEFINITIONS = [
    {
        "name": "dcc",
        "handler": "dcc_command_router", # Name of the router function in this module
        "help": {
            "usage": "/dcc <subcommand> [args]",
            "description": "Manages DCC file transfers. Use '/dcc' for subcommands.",
            "aliases": [] # Aliases for /dcc itself, if any
        }
    },
]
