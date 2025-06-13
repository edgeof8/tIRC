# commands/dcc/dcc_commands.py
import logging
from typing import TYPE_CHECKING, Optional, List, Dict, Any

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
from tirc_core.commands.dcc.dcc_command_base import DCCCommandHelper # Corrected import

logger = logging.getLogger("tirc.commands.dcc.main")

COMMAND_DEFINITIONS = [
    {
        "name": "dcc",
        "handler": "handle_dcc_command",
        "help": {
            "usage": "/dcc <subcommand> [args...]",
            "description": "Main command for DCC operations. Use /help dcc <subcommand> for details (e.g., /help dcc send).",
            "aliases": [] # Subcommands have their own aliases
        },
        "sub_commands_module": "tirc_core.commands.dcc" # Hint for help system
    }
]

async def handle_dcc_command(client: "IRCClient_Logic", args_str: str):
    """
    Main handler for the /dcc command.
    It dispatches to subcommands like /dcc send, /dcc list, etc.
    If no subcommand is given, or an invalid one, it shows help for /dcc.
    """
    parts = args_str.split(" ", 1)
    subcommand_name = parts[0].lower().strip() if parts else ""
    subcommand_args_str = parts[1] if len(parts) > 1 else ""
    active_context_name = client.context_manager.active_context_name or "Status"

    if not subcommand_name:
        await DCCCommandHelper.show_dcc_help(client, "dcc", active_context_name)
        return

    # Construct the full subcommand (e.g., "dcc_send") to find its handler
    full_subcommand_name = f"dcc_{subcommand_name}"

    # Check if the full_subcommand_name is a registered command
    # The CommandHandler stores primary command names.
    # Aliases are resolved by CommandHandler before calling the handler.
    # So, we need to check if full_subcommand_name is a known primary command.

    command_definition = client.command_handler.get_help_text_for_command(full_subcommand_name)

    if command_definition and command_definition.get("source") == "core": # Check if it's a core command
        # If it's a known DCC subcommand, execute it directly
        # The CommandHandler's process_user_command will find the actual handler.
        # We are essentially re-routing /dcc <subcmd> to /dcc_<subcmd>
        await client.command_handler.process_user_command(f"/{full_subcommand_name} {subcommand_args_str}")
    else:
        await client.add_message(
            f"Unknown DCC subcommand: '{subcommand_name}'. Use /help dcc for available subcommands.",
            client.ui.colors.get("error", 0),
            context_name=active_context_name
        )
        await DCCCommandHelper.show_dcc_help(client, "dcc", active_context_name)
