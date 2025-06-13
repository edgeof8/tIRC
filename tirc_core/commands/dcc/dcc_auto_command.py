# commands/dcc/dcc_auto_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.dcc.auto")

COMMAND_DEFINITIONS = [
    {
        "name": "dcc_auto", # Changed from "auto" to be DCC specific
        "handler": "handle_dcc_auto_command",
        "help": {
            "usage": "/dcc_auto [on|off|toggle]",
            "description": "Toggles or sets the global auto-accept feature for incoming DCC SEND offers.",
            "aliases": ["dccauto"]
        }
    }
]

async def handle_dcc_auto_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /dcc_auto [on|off|toggle] command."""
    arg = args_str.strip().lower()
    active_context_name = client.context_manager.active_context_name or "Status"

    if not client.dcc_manager:
        await client.add_message("DCC system is not available.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    current_status = client.config.dcc.auto_accept

    if arg == "on":
        client.config.dcc.auto_accept = True
    elif arg == "off":
        client.config.dcc.auto_accept = False
    elif arg == "toggle" or not arg: # Toggle if no arg or "toggle"
        client.config.dcc.auto_accept = not current_status
    else:
        await client.add_message(
            "Usage: /dcc_auto [on|off|toggle]",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    # Save the change to the config file
    if client.config.set_config_value("DCC", "auto_accept", str(client.config.dcc.auto_accept).lower()):
        feedback_action = "enabled" if client.config.dcc.auto_accept else "disabled"
        await client.add_message(
            f"DCC auto-accept {feedback_action}.",
            client.ui.colors.get("system", 0),
            context_name=active_context_name,
        )
        logger.info(f"DCC auto_accept set to {client.config.dcc.auto_accept}")
    else:
        await client.add_message(
            "Failed to save DCC auto-accept setting.",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        # Revert in-memory change if save failed
        client.config.dcc.auto_accept = current_status
