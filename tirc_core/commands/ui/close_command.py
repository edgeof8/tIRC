# commands/ui/close_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    from pyrc_core.context_manager import Context as CTX_Type
    from pyrc_core.context_manager import ChannelJoinStatus

logger = logging.getLogger("pyrc.commands.ui.close")

COMMAND_DEFINITIONS = [
    {
        "name": "close",
        "handler": "handle_close_command",
        "help": {
            "usage": "/close [context_name]",
            "description": "Closes the specified window or the current window if none is specified. For channels, this parts the channel.",
            "aliases": ["wc", "partchannel"] # partchannel alias might be confusing if it doesn't take a reason like /part
        }
    }
]

async def _close_channel_context(client: "IRCClient_Logic", channel_context: "CTX_Type"):
    if hasattr(channel_context, "join_status"):
        # ChannelJoinStatus is imported at the top of the file
        channel_context.join_status = ChannelJoinStatus.PARTING

    variables = {"nick": client.nick, "channel": channel_context.name}
    part_message = client.script_manager.get_random_part_message_from_scripts(
        variables
    )
    if not part_message:
        part_message = "Leaving"

    await client.network_handler.send_raw(
        f"PART {channel_context.name} :{part_message}"
    )
    await client.add_message(
        f"Parting {channel_context.name}...",
        client.ui.colors.get("system", 0),
        context_name=channel_context.name,
    )

async def _close_query_or_generic_context(client: "IRCClient_Logic", context_obj: "CTX_Type"):
    context_name_to_close = context_obj.name
    # Determine next context to switch to BEFORE removing the current one
    all_contexts = client.context_manager.get_all_context_names()
    next_active_context = "Status" # Default
    if len(all_contexts) > 1: # If more than just the one we're closing
        current_idx = -1
        try:
            # Sort contexts for predictable switching, Status last
            sorted_contexts = sorted([c for c in all_contexts if c != "Status"], key=str.lower)
            if "Status" in all_contexts:
                sorted_contexts.append("Status")

            current_idx = sorted_contexts.index(context_name_to_close)
            if current_idx > 0:
                next_active_context = sorted_contexts[current_idx -1]
            elif len(sorted_contexts) > 1 : # current was first, switch to next (now first)
                next_active_context = sorted_contexts[1] if context_name_to_close == sorted_contexts[0] else sorted_contexts[0]

        except ValueError: # Should not happen if context_name_to_close is in all_contexts
            pass

    client.context_manager.remove_context(context_name_to_close)
    await client.add_message(
        f"Closed window: {context_name_to_close}",
        client.ui.colors.get("system", 0),
        context_name="Status", # Feedback always to status for closed query/generic
    )
    if client.context_manager.active_context_name == context_name_to_close or not client.context_manager.active_context_name:
        await client.switch_active_context(next_active_context)


async def handle_close_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /close, /wc, /partchannel command."""
    context_to_close_name = args_str.strip()

    if not context_to_close_name: # No argument, close current
        active_ctx_name = client.context_manager.active_context_name
        if not active_ctx_name:
            await client.add_message(
                "No active window to close.", client.ui.colors.get("error", 0), context_name="Status"
            )
            return
        context_to_close_name = active_ctx_name
    else: # Argument provided, try to close that specific context
        # Normalize if it's a channel name
        if not context_to_close_name.startswith("#") and client.context_manager.get_context(f"#{context_to_close_name}"):
            context_to_close_name = f"#{context_to_close_name}"
        elif context_to_close_name.startswith("#") and not context_to_close_name.islower(): # Case normalization for channels
            normalized_check = client.context_manager._normalize_context_name(context_to_close_name)
            if client.context_manager.get_context(normalized_check):
                context_to_close_name = normalized_check


    context_to_close = client.context_manager.get_context(context_to_close_name)

    if not context_to_close:
        await client.add_message(
            f"Window '{context_to_close_name}' not found.", client.ui.colors.get("error", 0), context_name="Status"
        )
        return

    if context_to_close.type == "channel":
        await _close_channel_context(client, context_to_close)
    elif (
        context_to_close.type == "query"
        or context_to_close.type == "generic"
        or context_to_close.type == "list_results"
    ):
        await _close_query_or_generic_context(client, context_to_close)
    elif context_to_close.type == "status":
        await client.add_message(
            "Cannot close the Status window.", client.ui.colors.get("error", 0), context_name="Status"
        )
