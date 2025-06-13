# tirc_core/irc/irc_protocol.py
import logging
from typing import TYPE_CHECKING, Optional, Dict, Any, Callable, Awaitable

from tirc_core.irc.irc_message import IRCMessage
from tirc_core.irc.handlers import (
    message_handlers,
    membership_handlers,
    state_change_handlers,
    protocol_flow_handlers,
    irc_numeric_handlers,
)

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.protocol")

# Define a type for handler functions
HandlerFunction = Callable[["IRCClient_Logic", IRCMessage, str, list, Optional[str]], Awaitable[None]]


COMMAND_HANDLERS: Dict[str, HandlerFunction] = {
    "PRIVMSG": message_handlers._handle_privmsg,
    "NOTICE": message_handlers._handle_notice,
    "JOIN": membership_handlers._handle_join,
    "PART": membership_handlers._handle_part,
    "QUIT": membership_handlers._handle_quit,
    "KICK": membership_handlers._handle_kick,
    "NICK": state_change_handlers._handle_nick,
    "MODE": state_change_handlers._handle_mode,
    "TOPIC": state_change_handlers._handle_topic,
    "INVITE": state_change_handlers._handle_invite,
    "PING": protocol_flow_handlers._handle_ping,
    "PONG": protocol_flow_handlers._handle_pong,
    "ERROR": protocol_flow_handlers._handle_error,
    "CAP": protocol_flow_handlers._handle_cap,
    "AUTHENTICATE": protocol_flow_handlers._handle_authenticate,
    "CHGHOST": state_change_handlers._handle_chghost,
    # Add other command handlers here as they are implemented
}


async def handle_server_message(client: "IRCClient_Logic", raw_line: str):
    """
    Parses a raw IRC line and dispatches it to the appropriate handler.
    """
    try:
        parsed_msg = IRCMessage.parse(raw_line)
        if not parsed_msg:
            logger.warning(f"Failed to parse raw line: {raw_line.strip()}")
            return
    except Exception as e:
        logger.error(f"Error parsing IRC message '{raw_line.strip()}': {e}", exc_info=True)
        return

    command_upper = parsed_msg.command.upper()
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    active_context_name = client.context_manager.active_context_name or "Status"

    # Log the received message if raw logging is enabled
    if client.show_raw_log_in_ui:
        await client.add_status_message(f"S << {raw_line.strip()}", "system_dim")

    # Dispatch to specific command handler or numeric handler
    if command_upper in COMMAND_HANDLERS:
        handler = COMMAND_HANDLERS[command_upper]
        try:
            await handler(client, parsed_msg, raw_line, list(params), trailing)
        except Exception as e:
            logger.error(f"Error in handler for command {command_upper}: {e}", exc_info=True)
    elif command_upper.isdigit():
        try:
            await irc_numeric_handlers._handle_numeric_command(client, parsed_msg, raw_line, active_context_name)
        except Exception as e:
            logger.error(f"Error in numeric handler for {command_upper}: {e}", exc_info=True)
    else:
        logger.warning(f"No specific handler for command: {command_upper}. Raw: {raw_line.strip()}")
        # Optionally, add to status window for unknown commands
        await client.add_status_message(f"Unknown command from server: {command_upper} - {raw_line.strip()}", "warning")

    # Generic event dispatch for all parsed messages (after specific handling)
    # This allows scripts to react to any message type.
    event_data = {
        "command": command_upper,
        "prefix": parsed_msg.prefix,
        "params": list(params), # Convert tuple to list for mutability if scripts expect it
        "trailing": trailing,
        "tags": parsed_msg.get_all_tags(),
        "active_context_name": active_context_name,
        # client_logic_ref is implicitly available via the API handler in scripts
    }
    # Use a generic event name like "SERVER_MESSAGE_PARSED" or specific if preferred
    await client.event_manager.dispatch_event(f"SERVER_COMMAND_{command_upper}", event_data, raw_line)
