# commands/dcc/dcc_resume_command.py
import logging
from typing import TYPE_CHECKING, Optional # Added Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.dcc.dcc_send_manager import DCCSendTransfer # For type hint

logger = logging.getLogger("tirc.commands.dcc.resume")

COMMAND_DEFINITIONS = [
    {
        "name": "dcc_resume",
        "handler": "handle_dcc_resume_command",
        "help": {
            "usage": "/dcc_resume <transfer_id_prefix_or_filename>",
            "description": "Attempts to resume a previously failed/cancelled outgoing DCC SEND transfer.",
            "aliases": ["dcccontinue"]
        }
    }
]

async def handle_dcc_resume_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /dcc_resume command."""
    identifier = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"
    dcc_ui_context = client.dcc_manager.dcc_ui_context_name if client.dcc_manager else "Status"

    if not identifier:
        await client.add_message(
            "Usage: /dcc_resume <transfer_id_prefix_or_filename>",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    if not client.dcc_manager or not client.config.dcc.enabled:
        await client.add_message("DCC system is not enabled.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    if not client.dcc_manager.send_manager:
        await client.add_message("DCC SendManager is not available.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    # Find the transfer to resume
    transfer_to_resume: Optional["DCCSendTransfer"] = client.dcc_manager.find_resumable_send_transfer(identifier)

    if not transfer_to_resume:
        await client.add_message(
            f"No resumable DCC SEND transfer found matching '{identifier}'. Only failed or cancelled outgoing transfers can be resumed.",
            client.ui.colors.get("warning", 0),
            context_name=active_context_name,
        )
        return

    # Re-queue the transfer for resumption using its original parameters
    # The queue_send_request method will handle setting its status to RESUMING.
    resumed_transfer_obj = await client.dcc_manager.send_manager.queue_send_request(
        peer_nick=transfer_to_resume.peer_nick,
        local_filepath=transfer_to_resume.local_filepath, # This is a Path object
        passive=transfer_to_resume.is_passive, # Retain original passive flag
        resume_from_id=transfer_to_resume.id # Signal to resume this specific transfer
    )

    if resumed_transfer_obj:
        await client.add_message(
            f"Attempting to resume DCC SEND for '{transfer_to_resume.filename}' to {transfer_to_resume.peer_nick} (ID: {transfer_to_resume.id}).",
            client.ui.colors.get("system", 0),
            context_name=dcc_ui_context
        )
        if client.context_manager.active_context_name != dcc_ui_context:
            await client.view_manager.switch_active_context(dcc_ui_context) # Corrected call
    else:
        # This case should ideally be caught by find_resumable_send_transfer or queue_send_request internal checks
        await client.add_message(
            f"Failed to initiate resume for DCC SEND transfer '{identifier}'. It might no longer be valid or an internal error occurred.",
            client.ui.colors.get("error", 0),
            context_name=active_context_name
        )
