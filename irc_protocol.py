import re
import logging
from collections import deque
from typing import Optional
import time
from context_manager import ChannelJoinStatus
from irc_message import IRCMessage
from irc_numeric_handlers import _handle_numeric_command
from message_handlers import handle_privmsg, handle_notice
from membership_handlers import handle_membership_changes
from state_change_handlers import handle_nick_message, handle_mode_message, handle_topic_command_event, handle_chghost_command_event
from protocol_flow_handlers import handle_cap_message, handle_ping_command, handle_authenticate_command, handle_unknown_command

logger = logging.getLogger("pyrc.protocol")


# _handle_cap_message moved to protocol_flow_handlers.py
# _handle_nick_message and _handle_mode_message moved to state_change_handlers.py


def handle_server_message(client, line: str):  # raw_line is 'line' here
    """
    Processes a raw message line from the IRC server and calls
    appropriate methods on the client object to update state or UI.
    """
    parsed_msg = IRCMessage.parse(line)

    if not parsed_msg:
        logger.error(f"Failed to parse IRC message: {line.strip()}")
        client.add_message(
            f"[UNPARSED] {line.strip()}",
            client.ui.colors["error"],
            context_name="Status",
        )
        return

    cmd = parsed_msg.command

    if hasattr(client, "trigger_manager") and client.trigger_manager:
        raw_data = {
            "event_type": "RAW",
            "raw_line": line,
            "timestamp": time.time(),
            "client_nick": client.nick,
            "prefix": parsed_msg.prefix,
            "command": parsed_msg.command,
            "params_list": parsed_msg.params,
            "trailing": parsed_msg.trailing,
            "numeric": (
                int(parsed_msg.command) if parsed_msg.command.isdigit() else None
            ),
        }
        action_to_take = client.process_trigger_event("RAW", raw_data)
        if action_to_take:
            client.command_handler.process_user_command(action_to_take)

    if cmd == "CAP":
        handle_cap_message(client, parsed_msg, line)
    elif cmd == "PING":
        handle_ping_command(client, parsed_msg, line)
    elif cmd == "AUTHENTICATE":
        handle_authenticate_command(client, parsed_msg, line)
    elif cmd == "PRIVMSG":
        handle_privmsg(client, parsed_msg, line)
    elif cmd in ["JOIN", "PART", "QUIT", "KICK"]:
        handle_membership_changes(client, parsed_msg, line)
    elif cmd == "NICK":
        handle_nick_message(client, parsed_msg, line)
    elif cmd.isdigit():
        _handle_numeric_command(client, parsed_msg, line)
    elif cmd == "MODE":
        handle_mode_message(client, parsed_msg, line)
    elif cmd == "TOPIC":
        handle_topic_command_event(client, parsed_msg, line)
    elif cmd == "NOTICE":
        handle_notice(client, parsed_msg, line)
    elif cmd == "CHGHOST":
        handle_chghost_command_event(client, parsed_msg, line)
    else:
        handle_unknown_command(client, parsed_msg, line)

    client.ui_needs_update.set()
