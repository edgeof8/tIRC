# START OF MODIFIED FILE: irc_protocol.py
import re
import logging
from collections import deque
from typing import Optional, TYPE_CHECKING
import time
from pyrc_core.context_manager import ChannelJoinStatus
from pyrc_core.irc.irc_message import IRCMessage
from pyrc_core.irc.handlers.irc_numeric_handlers import _handle_numeric_command
from pyrc_core.irc.handlers.message_handlers import handle_privmsg, handle_notice
from pyrc_core.irc.handlers.membership_handlers import handle_membership_changes # Assuming this also calls process_trigger_event for relevant types
from pyrc_core.irc.handlers.state_change_handlers import handle_nick_message, handle_mode_message, handle_topic_command_event, handle_chghost_command_event
from pyrc_core.irc.handlers.protocol_flow_handlers import handle_cap_message, handle_ping_command, handle_authenticate_command, handle_unknown_command

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic


logger = logging.getLogger("pyrc.protocol")


def handle_server_message(client: "IRCClient_Logic", line: str):
    parsed_msg = IRCMessage.parse(line)

    if not parsed_msg:
        logger.error(f"Failed to parse IRC message: {line.strip()}")
        client.add_message(f"[UNPARSED] {line.strip()}", "error", context_name="Status")
        return

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
        final_trigger_action_to_take = client.process_trigger_event("RAW", raw_data)
        # If a RAW trigger produces a command, it takes precedence for now.
        # More sophisticated logic could queue actions or allow multiple.

    # Specific command handlers (which might also call process_trigger_event for specific event types)
    # If a specific handler's trigger also produces a command, it could override the RAW trigger's command.
    # This precedence (specific over RAW) is generally desirable.

    specific_handler_trigger_action: Optional[str] = None
    if cmd == "CAP":
        handle_cap_message(client, parsed_msg, line)
    elif cmd == "PING":
        handle_ping_command(client, parsed_msg, line)
    elif cmd == "AUTHENTICATE":
        handle_authenticate_command(client, parsed_msg, line)
    elif cmd == "PRIVMSG":
        specific_handler_trigger_action = handle_privmsg(client, parsed_msg, line)
    elif cmd in ["JOIN", "PART", "QUIT", "KICK"]:
        # Modify these handlers to also return Optional[str] if they process triggers
        specific_handler_trigger_action = handle_membership_changes(client, parsed_msg, line)
    elif cmd == "NICK":
        specific_handler_trigger_action = handle_nick_message(client, parsed_msg, line)
    elif cmd.isdigit():
        _handle_numeric_command(client, parsed_msg, line) # Numeric handlers might call process_trigger_event internally
    elif cmd == "MODE":
        specific_handler_trigger_action = handle_mode_message(client, parsed_msg, line)
    elif cmd == "TOPIC":
        specific_handler_trigger_action = handle_topic_command_event(client, parsed_msg, line)
    elif cmd == "NOTICE":
        specific_handler_trigger_action = handle_notice(client, parsed_msg, line)
    elif cmd == "CHGHOST":
        specific_handler_trigger_action = handle_chghost_command_event(client, parsed_msg, line)
    else:
        handle_unknown_command(client, parsed_msg, line)

    # If a specific handler generated a command from its own trigger processing, use that.
    if specific_handler_trigger_action:
        final_trigger_action_to_take = specific_handler_trigger_action

    if final_trigger_action_to_take:
        logger.info(f"Executing trigger-generated command: {final_trigger_action_to_take}")
        client.command_handler.process_user_command(final_trigger_action_to_take)

    client.ui_needs_update.set()

# END OF MODIFIED FILE: irc_protocol.py
