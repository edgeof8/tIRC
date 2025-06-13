# commands/ui/close_command.py
import logging
from typing import TYPE_CHECKING, Optional

from tirc_core.context_manager import ChannelJoinStatus

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.ui.close")

COMMAND_DEFINITIONS = [
    {
        "name": "close",
        "handler": "handle_close_command",
        "help": {
            "usage": "/close [context_name]",
            "description": "Closes the specified context (channel/query) or the active one if none specified. Parts channel if applicable.",
            "aliases": ["wc", "leave", "qclose"]
        }
    }
]

async def handle_close_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /close command."""
    context_to_close_arg = args_str.strip()
    current_active_context_name = client.context_manager.active_context_name # This is Optional[str]

    if not context_to_close_arg and current_active_context_name:
        context_to_close_arg = current_active_context_name
    elif not context_to_close_arg and not current_active_context_name:
        await client.add_status_message("No active context to close.", "error")
        return

    if not context_to_close_arg: # Should not happen if logic above is correct
        await client.add_status_message("No context specified to close.", "error")
        return

    context_to_close_normalized = client.context_manager._normalize_context_name(context_to_close_arg)
    context_obj_to_close = client.context_manager.get_context(context_to_close_normalized)

    if not context_obj_to_close:
        await client.add_status_message(f"Context '{context_to_close_arg}' not found.", "error")
        return

    if context_obj_to_close.name.lower() == "status" or \
       (client.dcc_manager and context_obj_to_close.name.lower() == client.dcc_manager.dcc_ui_context_name.lower()):
        await client.add_status_message(f"Cannot close '{context_obj_to_close.name}' window.", "warning")
        return

    part_message = f"Closed by /close command by {client.nick or 'user'}"
    if context_obj_to_close.type == "channel":
        if context_obj_to_close.join_status in [ChannelJoinStatus.FULLY_JOINED, ChannelJoinStatus.SELF_JOIN_RECEIVED, ChannelJoinStatus.JOIN_COMMAND_SENT]:
            logger.info(f"Sending PART for channel '{context_obj_to_close.name}' due to /close command.")
            await client.network_handler.send_raw(f"PART {context_obj_to_close.name} :{part_message}")
        else:
            logger.info(f"Channel '{context_obj_to_close.name}' not fully joined (status: {context_obj_to_close.join_status.name if context_obj_to_close.join_status else 'N/A'}). Not sending PART, just removing context.")

    new_active_target = "Status"

    if current_active_context_name == context_to_close_normalized:
        all_contexts = client.context_manager.get_all_context_names()
        remaining_contexts = [name for name in all_contexts if name != context_to_close_normalized and name.lower() != "status"]

        if remaining_contexts:
            preferred_order = [name for name in remaining_contexts if client.context_manager.get_context_type(name) in ["channel", "query"]]
            if preferred_order:
                new_active_target = preferred_order[0]
            elif client.dcc_manager and client.dcc_manager.dcc_ui_context_name in remaining_contexts:
                new_active_target = client.dcc_manager.dcc_ui_context_name
            elif "Status" in all_contexts and "Status" != context_to_close_normalized :
                 new_active_target = "Status"
            elif remaining_contexts:
                new_active_target = remaining_contexts[0]
        elif "Status" in all_contexts and "Status" != context_to_close_normalized:
            new_active_target = "Status"

    was_removed = client.context_manager.remove_context(context_to_close_normalized)

    if was_removed:
        await client.add_status_message(f"Closed context: {context_to_close_arg}", "system")
        # Check if the current_active_context_name (which is Optional[str]) is still valid before using it in get_context
        is_current_active_still_valid = False
        if current_active_context_name: # Ensure it's not None
            is_current_active_still_valid = client.context_manager.get_context(current_active_context_name) is not None

        if current_active_context_name == context_to_close_normalized or not is_current_active_still_valid:
            logger.info(f"Switching to new active target: {new_active_target} after closing {context_to_close_arg}")
            await client.view_manager.switch_active_context(new_active_target)
        else:
            logger.info(f"Closed non-active context {context_to_close_arg}. Active context remains {current_active_context_name}.")
    else:
        await client.add_status_message(f"Failed to remove context '{context_to_close_arg}'. It might have been closed already.", "warning")

    client.ui_needs_update.set()
