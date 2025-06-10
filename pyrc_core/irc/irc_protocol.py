# START OF MODIFIED FILE: irc_protocol.py
import re
import logging
import asyncio
from collections import deque
from typing import Optional, Awaitable, TYPE_CHECKING, Coroutine, Any
import time
from pyrc_core.context_manager import ChannelJoinStatus
from pyrc_core.irc.irc_message import IRCMessage
from pyrc_core.irc.handlers.irc_numeric_handlers import _handle_numeric_command
from pyrc_core.irc.handlers.message_handlers import handle_privmsg, handle_notice
from pyrc_core.irc.handlers.membership_handlers import handle_membership_changes # Assuming this also calls process_trigger_event for relevant types
from pyrc_core.irc.handlers.state_change_handlers import handle_nick_message, handle_mode_message, handle_topic_command_event, handle_chghost_command_event
from pyrc_core.irc.handlers.protocol_flow_handlers import handle_cap_message, handle_ping_command, handle_authenticate_command, handle_unknown_command, handle_error_command

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic


logger = logging.getLogger("pyrc.protocol")

COMMAND_DISPATCH_TABLE = {
    "CAP": handle_cap_message,
    "PING": handle_ping_command,
    "AUTHENTICATE": handle_authenticate_command,
    "PRIVMSG": handle_privmsg,
    "JOIN": handle_membership_changes,
    "PART": handle_membership_changes,
    "QUIT": handle_membership_changes,
    "KICK": handle_membership_changes,
    "NICK": handle_nick_message,
    "MODE": handle_mode_message,
    "TOPIC": handle_topic_command_event,
    "NOTICE": handle_notice,
    "CHGHOST": handle_chghost_command_event,
    "ERROR": handle_error_command,
    # Numeric commands are handled by _handle_numeric_command, which dispatches further
    # We will explicitly map common numerics that were previously in the if/elif chain
    # The _handle_numeric_command function already has its own dispatch table.
    # We just need to make sure the main dispatcher routes to it if the command is a digit.
}

async def handle_server_message(client: "IRCClient_Logic", line: str) -> Optional[Coroutine[Any, Any, None]]:
    logger.debug(f"S << {line.strip()}") # Log all incoming raw lines
    if client is None:
        logger.warning("handle_server_message: Client is None, skipping message processing.")
        return None

    parsed_msg = IRCMessage.parse(line)

    if not parsed_msg:
        logger.error(f"Failed to parse IRC message: {line.strip()}")
        await client.ui.add_message_to_context(f"[UNPARSED] {line.strip()}", client.ui.colors["error"], context_name="Status", prefix_time=False)
        return None

    cmd = parsed_msg.command
    final_trigger_action_to_take: Optional[str] = None

    # Process RAW trigger first
    if hasattr(client, "trigger_manager") and client.trigger_manager:
        raw_data = {
            "event_type": "RAW", "raw_line": line, "timestamp": time.time(),
            "client_nick": client.nick, "prefix": parsed_msg.prefix,
            "command": parsed_msg.command, "params_list": list(parsed_msg.params), # Ensure it's a list
            "trailing": parsed_msg.trailing,
            "numeric": (int(parsed_msg.command) if parsed_msg.command.isdigit() else None),
            "tags": parsed_msg.get_all_tags() # Add tags to RAW event
        }
        if hasattr(client, "trigger_manager") and client.trigger_manager and hasattr(client.trigger_manager, "process_trigger") and callable(client.trigger_manager.process_trigger):
            trigger_result = client.trigger_manager.process_trigger("RAW", raw_data)
            if trigger_result and trigger_result.get("type") == "COMMAND":
                final_trigger_action_to_take = trigger_result.get("content")
        else:
            logger.warning("client.trigger_manager.process_trigger is not defined or trigger_manager is not enabled, skipping RAW trigger processing.")
            final_trigger_action_to_take = None
        # If a RAW trigger produces a command, it takes precedence for now.
        # More sophisticated logic could queue actions or allow multiple.
    # Specific command handlers (which might also call process_trigger_event for specific event types)
    # If a specific handler's trigger also produces a command, it could override the RAW trigger's command.
    # This precedence (specific over RAW) is generally desirable.

    specific_handler_trigger_action: Optional[str] = None

    handler = COMMAND_DISPATCH_TABLE.get(cmd)

    if handler:
        # Check if the handler is one that returns an Optional[str] (trigger action)
        # This is a heuristic based on the original code's specific_handler_trigger_action assignments.
        if handler in [handle_privmsg, handle_membership_changes, handle_nick_message, handle_mode_message, handle_topic_command_event, handle_notice, handle_chghost_command_event]:
            if client:
                specific_handler_trigger_action = await handler(client, parsed_msg, line)
            else:
                logger.warning(f"Client is None, skipping handler {handler.__name__}")
                specific_handler_trigger_action = None
        else:
            await handler(client, parsed_msg, line)
    elif cmd.isdigit():
        await _handle_numeric_command(client, parsed_msg, line)
    else:
        # handle_unknown_command is an async function
        await handle_unknown_command(client, parsed_msg, line)

    # If a specific handler generated a command from its own trigger processing, use that.
    if specific_handler_trigger_action:
        final_trigger_action_to_take = specific_handler_trigger_action

    if final_trigger_action_to_take:
        logger.info(f"Executing trigger-generated command: {final_trigger_action_to_take}")
        await client.command_handler.process_user_command(final_trigger_action_to_take)

    client.ui_needs_update.set() # This is an asyncio.Event, set() is synchronous
    return None
# END OF MODIFIED FILE: irc_protocol.py
