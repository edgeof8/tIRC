# commands/dcc/dcc_cancel_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.dcc.cancel")

COMMAND_DEFINITIONS = [
    {
        "name": "dcc_cancel", # Changed from "cancel" to be DCC specific
        "handler": "handle_dcc_cancel_command",
        "help": {
            "usage": "/dcc_cancel <transfer_id_prefix_or_token_prefix>",
            "description": "Cancels an active DCC transfer by its ID prefix or a pending passive offer by its token prefix.",
            "aliases": ["dccclose", "dccstop"] # dccclose was an alias in original list
        }
    }
]

async def handle_dcc_cancel_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /dcc_cancel command."""
    identifier_prefix = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"
    dcc_ui_context = client.dcc_manager.dcc_ui_context_name if client.dcc_manager else "Status"


    if not identifier_prefix:
        await client.add_message(
            "Usage: /dcc_cancel <transfer_id_prefix_or_token_prefix>",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    if not client.dcc_manager or not client.config.dcc.enabled:
        await client.add_message("DCC system is not enabled.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    # Call DCCManager to handle cancellation
    # This method should search active transfers and pending passive offers
    cancelled = await client.dcc_manager.cancel_transfer_by_id_or_token(identifier_prefix)

    if cancelled:
        await client.add_message(
            f"DCC transfer/offer matching '{identifier_prefix}' cancelled (or was already completed/failed).",
            client.ui.colors.get("system", 0), # Use system color, as it's a confirmation of action
            context_name=dcc_ui_context
        )
        # Optionally switch to DCC context
        if client.context_manager.active_context_name != dcc_ui_context:
            await client.view_manager.switch_active_context(dcc_ui_context) # Corrected call
    else:
        await client.add_message(
            f"No active DCC transfer or pending passive offer found matching prefix '{identifier_prefix}' to cancel.",
            client.ui.colors.get("warning", 0), # Warning as no action was taken
            context_name=active_context_name # Show in current context if nothing found
        )
