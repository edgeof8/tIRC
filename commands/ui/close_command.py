# commands/ui/close_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic
    from context_manager import Context as CTX_Type # Adjusted import
    from context_manager import ChannelJoinStatus # Added import

logger = logging.getLogger("pyrc.commands.ui.close")

# Helper functions (moved from CommandHandler)
def _close_channel_context(client: "IRCClient_Logic", channel_context: "CTX_Type"):
    """Helper to handle closing (parting) a channel context."""
    if hasattr(channel_context, "join_status"):
        # Need to import ChannelJoinStatus for this comparison
        from context_manager import ChannelJoinStatus
        channel_context.join_status = ChannelJoinStatus.PARTING

    variables = {"nick": client.nick, "channel": channel_context.name}
    part_message = client.script_manager.get_random_part_message_from_scripts(
        variables
    )
    if not part_message:
        part_message = "Leaving"

    client.network_handler.send_raw(
        f"PART {channel_context.name} :{part_message}"
    )
    client.add_message(
        f"Parting {channel_context.name}...",
        "system", # Semantic color key
        context_name=channel_context.name,
    )

def _close_query_or_generic_context(client: "IRCClient_Logic", context_obj: "CTX_Type"):
    """Helper to handle closing a query or generic context."""
    context_name_to_close = context_obj.name
    client.context_manager.remove_context(context_name_to_close)
    client.add_message(
        f"Closed window: {context_name_to_close}",
        "system", # Semantic color key
        context_name="Status",
    )

def handle_close_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /close, /wc, /partchannel command."""
    active_ctx_name = client.context_manager.active_context_name
    if not active_ctx_name:
        client.add_message(
            "No active window to close.",
            "error", # Semantic color key
            context_name="Status",
        )
        return

    current_context = client.context_manager.get_context(active_ctx_name)
    if not current_context:
        logger.error(
            f"/close: Active context '{active_ctx_name}' not found in manager."
        )
        return

    if current_context.type == "channel":
        _close_channel_context(client, current_context)
    elif (
        current_context.type == "query"
        or current_context.type == "generic"
        or current_context.type == "list_results" # Added from original logic
    ):
        _close_query_or_generic_context(client, current_context)
    elif current_context.type == "status":
        client.add_message(
            "Cannot close the Status window.",
            "error", # Semantic color key
            context_name="Status",
        )
