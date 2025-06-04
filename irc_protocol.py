import re
import logging
from collections import deque
from typing import Optional
import time
from context_manager import ChannelJoinStatus
from irc_message import IRCMessage
from irc_numeric_handlers import _handle_numeric_command

logger = logging.getLogger("pyrc.protocol")


class IRCProtocolHandler:
    def _handle_privmsg(self, client, parsed_msg: IRCMessage, raw_line: str):
        nick = parsed_msg.source_nick
        source_full_ident = parsed_msg.prefix

        if not nick or not source_full_ident:
            logger.warning(f"PRIVMSG without valid source: {raw_line.strip()}")
            return

        target = parsed_msg.params[0] if parsed_msg.params else None
        message_body = parsed_msg.trailing if parsed_msg.trailing else ""

        if not target:
            logger.warning(f"PRIVMSG without target: {raw_line.strip()}")
            return

        is_channel_msg = target.startswith(("#", "&", "!", "+"))
        is_private_msg_to_me = (
            not is_channel_msg and target.lower() == client.nick.lower()
        )

        target_context_name = target
        display_nick = f"<{nick}>"
        color = client.ui.colors["other_message"]

        if is_private_msg_to_me:
            target_context_name = nick
            client.context_manager.create_context(
                target_context_name, context_type="query"
            )
            display_nick = f"*{nick}*"
            color = client.ui.colors["pm"]
        elif nick.lower() == client.nick.lower() and is_channel_msg:
            color = client.ui.colors["my_message"]

        if (
            client.nick
            and client.nick.lower() in message_body.lower()
            and not (nick.lower() == client.nick.lower())
        ):
            color = client.ui.colors["highlight"]

        formatted_msg = f"{display_nick} {message_body}"

        client.add_message(
            formatted_msg,
            color,
            context_name=target_context_name,
            source_full_ident=source_full_ident,
            is_privmsg_or_notice=True,
        )
        client.process_trigger_event(
            "TEXT",
            {
                "nick": nick,
                "userhost": source_full_ident,
                "target": target,
                "channel": target if is_channel_msg else "",
                "message": message_body,
                "message_words": message_body.split(),
                "client_nick": client.nick,
                "raw_line": raw_line,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "tags": parsed_msg.get_all_tags(),
            },
        )

        # Dispatch PRIVMSG event
        if hasattr(client, "script_manager"):
            event_data = {
                "nick": nick,
                "userhost": source_full_ident,
                "target": target,
                "message": message_body,
                "is_channel_msg": is_channel_msg,
                "client_nick": client.nick,
                "raw_line": raw_line,
                "tags": parsed_msg.get_all_tags(),
            }
            client.script_manager.dispatch_event("PRIVMSG", event_data)

    def _handle_notice(self, client, parsed_msg: IRCMessage, raw_line: str):
        nick = parsed_msg.source_nick
        source_full_ident = parsed_msg.prefix

        target = parsed_msg.params[0] if parsed_msg.params else None
        message_body = parsed_msg.trailing if parsed_msg.trailing else ""

        if not target:
            logger.warning(f"NOTICE without target: {raw_line.strip()}")
            return

        is_channel_notice = target.startswith(("#", "&", "!", "+"))
        display_source = (
            nick
            if nick
            else (
                source_full_ident
                if source_full_ident and "!" not in source_full_ident
                else "Server"
            )
        )

        notice_prefix = f"-{display_source}-"
        target_context_name = "Status"

        if is_channel_notice:
            target_context_name = target
        elif target.lower() == (client.nick.lower() if client.nick else ""):
            if nick and source_full_ident and "!" in source_full_ident:
                target_context_name = nick
                client.context_manager.create_context(
                    target_context_name, context_type="query"
                )
            else:
                target_context_name = "Status"

        formatted_msg = f"{notice_prefix} {message_body}"

        client.add_message(
            formatted_msg,
            client.ui.colors["system"],
            context_name=target_context_name,
            source_full_ident=source_full_ident,
            is_privmsg_or_notice=True,
        )

        # Dispatch NOTICE event
        if hasattr(client, "script_manager"):
            event_data = {
                "nick": nick if nick else "",
                "userhost": source_full_ident if source_full_ident else "",
                "target": target,
                "message": message_body,
                "is_channel_notice": is_channel_notice,
                "client_nick": client.nick,
                "raw_line": raw_line,
                "tags": parsed_msg.get_all_tags(),
            }
            client.script_manager.dispatch_event("NOTICE", event_data)


protocol_handler_instance = IRCProtocolHandler()


def _handle_cap_message(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles CAP messages."""
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    cap_subcommand = params[1] if len(params) > 1 else None
    capabilities_str = trailing if trailing else (params[2] if len(params) > 2 else "")

    if not cap_subcommand:
        logger.warning(f"Malformed CAP message received: {raw_line.strip()}")
        client.add_message(
            f"[Malformed CAP] {raw_line.strip()}",
            client.ui.colors["error"],
            context_name="Status",
        )
        return

    logger.debug(
        f"Received CAP {cap_subcommand} with capabilities: '{capabilities_str}'"
    )

    if not hasattr(client, "cap_negotiator") or not client.cap_negotiator:
        logger.error(
            "CAP message received, but client.cap_negotiator is not initialized."
        )
        client.add_message(
            f"[CAP Error] Negotiator not ready for {cap_subcommand}",
            client.ui.colors["error"],
            "Status",
        )
        return

    if cap_subcommand == "LS":
        client.cap_negotiator.on_cap_ls_received(capabilities_str)
    elif cap_subcommand == "ACK":
        client.cap_negotiator.on_cap_ack_received(capabilities_str)
    elif cap_subcommand == "NAK":
        client.cap_negotiator.on_cap_nak_received(capabilities_str)
    elif cap_subcommand == "NEW":
        client.cap_negotiator.on_cap_new_received(capabilities_str)
    elif cap_subcommand == "DEL":
        client.cap_negotiator.on_cap_del_received(capabilities_str)
    else:
        client.add_message(
            f"[CAP] Unknown subcommand: {cap_subcommand} {capabilities_str}",
            client.ui.colors["system"],
            context_name="Status",
        )


def _handle_nick_message(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles NICK messages."""
    old_nick = parsed_msg.source_nick
    new_nick = parsed_msg.trailing
    source_full_ident = parsed_msg.prefix

    if not old_nick or not new_nick:
        logger.warning(f"Malformed NICK message: {raw_line.strip()}")
        return

    # Check if this is our own nick change
    is_our_nick_change = old_nick.lower() == client.nick.lower()

    if is_our_nick_change:
        # Update our nick
        old_nick = client.nick
        client.nick = new_nick
        logger.info(f"Our nick changed from {old_nick} to {new_nick}")

        # Update nick in all contexts
        for context in client.context_manager.contexts.values():
            if context.type == "channel":
                if old_nick in context.users:
                    context.users[new_nick] = context.users.pop(old_nick)
                    if old_nick in context.user_prefixes:
                        context.user_prefixes[new_nick] = context.user_prefixes.pop(
                            old_nick
                        )

        # Add message to status
        client.add_message(
            f"Nick changed from {old_nick} to {new_nick}",
            client.ui.colors["system"],
            context_name="Status",
        )

        if client.last_attempted_nick_change is not None and \
           client.last_attempted_nick_change.lower() == new_nick.lower():
            logger.info(f"Successful user-initiated nick change to {new_nick} confirmed.")
            client.last_attempted_nick_change = None

        # Dispatch CLIENT_NICK_CHANGED event
        if hasattr(client, "script_manager"):
            event_data = {
                "old_nick": old_nick,
                "new_nick": new_nick,
                "raw_line": raw_line,
                "tags": parsed_msg.get_all_tags(),
            }
            client.script_manager.dispatch_event("CLIENT_NICK_CHANGED", event_data)
    else:
        # Handle other users' nick changes
        for context in client.context_manager.contexts.values():
            if context.type == "channel":
                if old_nick in context.users:
                    context.users[new_nick] = context.users.pop(old_nick)
                    if old_nick in context.user_prefixes:
                        context.user_prefixes[new_nick] = context.user_prefixes.pop(
                            old_nick
                        )

                    # Add message to channel
                    client.add_message(
                        f"{old_nick} is now known as {new_nick}",
                        client.ui.colors["system"],
                        context_name=context.name,
                    )

    # Dispatch general NICK event
    if hasattr(client, "script_manager"):
        event_data = {
            "old_nick": old_nick,
            "new_nick": new_nick,
            "source_userhost": source_full_ident,
            "is_our_nick_change": is_our_nick_change,
            "raw_line": raw_line,
            "tags": parsed_msg.get_all_tags(),
        }
        client.script_manager.dispatch_event("NICK", event_data)


def _handle_join_event(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles JOIN messages."""
    src_nick = parsed_msg.source_nick
    params = parsed_msg.params
    client_nick_lower = client.nick.lower() if client.nick else ""
    src_nick_lower = src_nick.lower() if src_nick else ""

    joined_channel = params[0] if params else None

    if not joined_channel:
        logger.warning(f"JOIN command received with no channel: {raw_line.strip()}")
        client.add_message(
            f"[INVALID JOIN] {raw_line.strip()}", client.ui.colors["error"], "Status"
        )
        return

    # Ensure channel context exists
    created_now = client.context_manager.create_context(
        joined_channel,
        context_type="channel",
        initial_join_status_for_channel=ChannelJoinStatus.JOIN_COMMAND_SENT,
    )
    if created_now:
        logger.debug(
            f"Ensured channel context exists for JOIN: {joined_channel} (created with JOIN_COMMAND_SENT)"
        )

    joined_ctx = client.context_manager.get_context(joined_channel)

    if src_nick_lower == client_nick_lower:
        logger.info(f"Self JOIN received for channel: {joined_channel}")
        if joined_ctx:
            joined_ctx.join_status = ChannelJoinStatus.SELF_JOIN_RECEIVED
            joined_ctx.users.clear()
            logger.debug(f"Set join_status to SELF_JOIN_RECEIVED for {joined_channel}")
        else:
            logger.error(f"Context for {joined_channel} not found after self-JOIN.")

        client.network_handler.send_raw(f"NAMES {joined_channel}")
        client.network_handler.send_raw(f"MODE {joined_channel}")
        client.add_message(
            f"Joining {joined_channel}...",
            client.ui.colors["join_part"],
            context_name=joined_channel,
        )
    else:
        if joined_ctx:
            client.context_manager.add_user(joined_channel, src_nick)
            client.add_message(
                f"{src_nick} joined {joined_channel}",
                client.ui.colors["join_part"],
                context_name=joined_channel,
            )
        else:
            logger.debug(
                f"Received other-JOIN for {joined_channel} by {src_nick}, but no local context exists."
            )

    # Dispatch JOIN event
    if hasattr(client, "script_manager"):
        event_data = {
            "nick": src_nick,
            "channel": joined_channel,
            "is_self": src_nick_lower == client_nick_lower,
            "client_nick": client.nick,
            "raw_line": raw_line,
        }
        client.script_manager.dispatch_event("JOIN", event_data)


def _handle_part_event(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles PART messages."""
    src_nick = parsed_msg.source_nick
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    client_nick_lower = client.nick.lower() if client.nick else ""
    src_nick_lower = src_nick.lower() if src_nick else ""

    parted_channel = params[0] if params else None
    reason_message = f" ({trailing.lstrip(':')})" if trailing else ""

    if not parted_channel:
        logger.warning(f"PART command received with no channel: {raw_line.strip()}")
        client.add_message(
            f"[INVALID PART] {raw_line.strip()}", client.ui.colors["error"], "Status"
        )
        return

    parted_ctx_obj = client.context_manager.get_context(parted_channel)

    if src_nick_lower == client_nick_lower:
        logger.info(f"We parted channel: {parted_channel}{reason_message}")

        if parted_ctx_obj:
            parted_ctx_obj.join_status = ChannelJoinStatus.NOT_JOINED
            parted_ctx_obj.users.clear()
            logger.debug(
                f"Set join_status to NOT_JOINED for parted channel {parted_channel}"
            )

        client.currently_joined_channels.discard(parted_channel)
        client.add_message(
            f"You left {parted_channel}{reason_message}",
            client.ui.colors["join_part"],
            context_name=parted_channel,
        )

        if (
            client.context_manager.active_context_name
            == client.context_manager._normalize_context_name(parted_channel)
        ):
            other_joined_channels = sorted(
                list(client.currently_joined_channels), key=str.lower
            )
            if other_joined_channels:
                client.switch_active_context(other_joined_channels[0])
            elif "Status" in client.context_manager.get_all_context_names():
                client.switch_active_context("Status")
            else:
                all_ctx_names = client.context_manager.get_all_context_names()
                if all_ctx_names:
                    client.switch_active_context(all_ctx_names[0])
    else:
        if parted_ctx_obj:
            client.context_manager.remove_user(parted_channel, src_nick)
            client.add_message(
                f"{src_nick} left {parted_channel}{reason_message}",
                client.ui.colors["join_part"],
                context_name=parted_channel,
            )
        else:
            logger.debug(
                f"Received other-PART for {parted_channel} by {src_nick}, but no local context exists."
            )

    # Dispatch PART event
    if hasattr(client, "script_manager"):
        event_data = {
            "nick": src_nick,
            "channel": parted_channel,
            "reason": trailing.lstrip(":") if trailing else "",
            "is_self": src_nick_lower == client_nick_lower,
            "client_nick": client.nick,
            "raw_line": raw_line,
        }
        client.script_manager.dispatch_event("PART", event_data)


def _handle_quit_event(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles QUIT messages."""
    src_nick = parsed_msg.source_nick
    trailing = parsed_msg.trailing
    client_nick_lower = client.nick.lower() if client.nick else ""
    src_nick_lower = src_nick.lower() if src_nick else ""

    quit_reason = f" ({trailing.lstrip(':')})" if trailing else ""
    display_src_nick = src_nick if src_nick else "Someone"

    if src_nick_lower == client_nick_lower:
        logger.info(
            f"Received QUIT message for our own nick: {client.nick}{quit_reason}. Client is likely shutting down or changing servers."
        )
        return

    logger.info(f"User {display_src_nick} quit from the server{quit_reason}.")
    for ctx_name, ctx_obj in client.context_manager.contexts.items():
        if ctx_obj.type == "channel" and src_nick and src_nick in ctx_obj.users:
            client.context_manager.remove_user(ctx_name, src_nick)
            client.add_message(
                f"{display_src_nick} quit{quit_reason}",
                client.ui.colors["join_part"],
                context_name=ctx_name,
            )

    # Dispatch QUIT event
    if hasattr(client, "script_manager"):
        event_data = {
            "nick": src_nick,
            "reason": trailing.lstrip(":") if trailing else "",
            "client_nick": client.nick,
            "raw_line": raw_line,
        }
        client.script_manager.dispatch_event("QUIT", event_data)


def _handle_kick_event(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles KICK messages."""
    src_nick = parsed_msg.source_nick
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    client_nick_lower = client.nick.lower() if client.nick else ""

    channel_kicked_from = params[0] if len(params) > 0 else None
    user_kicked = params[1] if len(params) > 1 else None
    reason = f" ({trailing.lstrip(':')})" if trailing else ""

    if not channel_kicked_from or not user_kicked:
        logger.warning(f"Invalid KICK message: {raw_line.strip()}")
        return

    kick_message = (
        f"{user_kicked} was kicked from {channel_kicked_from} by {src_nick}{reason}"
    )

    if client.context_manager.create_context(
        channel_kicked_from, context_type="channel"
    ):
        logger.debug(f"Ensured channel context exists for KICK: {channel_kicked_from}")

    client.add_message(
        kick_message, client.ui.colors["join_part"], context_name=channel_kicked_from
    )

    kicked_ctx = client.context_manager.get_context(channel_kicked_from)
    if kicked_ctx:
        client.context_manager.remove_user(channel_kicked_from, user_kicked)

    if user_kicked.lower() == client_nick_lower:
        logger.info(f"We were kicked from {channel_kicked_from} by {src_nick}{reason}")
        client.currently_joined_channels.discard(channel_kicked_from)
        if kicked_ctx:
            kicked_ctx.join_status = ChannelJoinStatus.NOT_JOINED
            kicked_ctx.users.clear()
            logger.debug(
                f"Set join_status to NOT_JOINED for kicked channel {channel_kicked_from}"
            )

        if (
            client.context_manager.active_context_name
            == client.context_manager._normalize_context_name(channel_kicked_from)
        ):
            other_joined_channels = sorted(
                list(client.currently_joined_channels), key=str.lower
            )
            if other_joined_channels:
                client.switch_active_context(other_joined_channels[0])
            elif "Status" in client.context_manager.get_all_context_names():
                client.switch_active_context("Status")
            else:
                all_ctx_names = client.context_manager.get_all_context_names()
                if all_ctx_names:
                    client.switch_active_context(all_ctx_names[0])


def _handle_membership_changes(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles JOIN, PART, QUIT, KICK messages."""
    cmd = parsed_msg.command

    if cmd == "JOIN":
        _handle_join_event(client, parsed_msg, raw_line)
    elif cmd == "PART":
        _handle_part_event(client, parsed_msg, raw_line)
    elif cmd == "QUIT":
        _handle_quit_event(client, parsed_msg, raw_line)
    elif cmd == "KICK":
        _handle_kick_event(client, parsed_msg, raw_line)


def _handle_mode_message(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles MODE messages."""
    source_nick = parsed_msg.source_nick
    source_full_ident = parsed_msg.prefix
    params = parsed_msg.params

    if not params:
        logger.warning(f"MODE without parameters: {raw_line.strip()}")
        return

    target = params[0]
    mode_string = params[1] if len(params) > 1 else ""
    mode_params = params[2:] if len(params) > 2 else []

    # Parse mode changes
    parsed_modes = []
    current_operation = None
    param_index = 0

    for char in mode_string:
        if char in ("+", "-"):
            current_operation = char
            continue

        mode_info = {"operation": current_operation, "mode": char, "param": None}

        # Check if this mode requires a parameter
        if char in ("b", "k", "l", "v", "h", "o", "a", "q"):
            if param_index < len(mode_params):
                mode_info["param"] = mode_params[param_index]
                param_index += 1

        parsed_modes.append(mode_info)

    # Handle channel modes
    if target.startswith(("#", "&", "!", "+")):
        context = client.context_manager.get_context(target)
        if context and context.type == "channel":
            # Update channel modes
            for mode in parsed_modes:
                if mode["operation"] == "+":
                    context.modes.add(mode["mode"])
                elif mode["operation"] == "-":
                    context.modes.discard(mode["mode"])

            # Format mode string for display
            mode_str = mode_string
            if mode_params:
                mode_str += " " + " ".join(mode_params)

            # Add message to channel
            client.add_message(
                f"Mode {target} [{mode_str}] by {source_nick}",
                client.ui.colors["system"],
                context_name=target,
            )

            # Dispatch CHANNEL_MODE_APPLIED event
            if hasattr(client, "script_manager"):
                event_data = {
                    "channel": target,
                    "setter": source_nick,
                    "setter_userhost": source_full_ident,
                    "mode_changes": parsed_modes,
                    "current_modes": list(context.modes),  # Include current modes
                    "raw_line": raw_line,
                    "tags": parsed_msg.get_all_tags(),
                }
                client.script_manager.dispatch_event("CHANNEL_MODE_APPLIED", event_data)

    # Handle user modes
    elif target.lower() == client.nick.lower():
        # Update user modes
        for mode in parsed_modes:
            if mode["operation"] == "+":
                if mode["mode"] not in client.user_modes:
                    client.user_modes.append(mode["mode"])
            elif mode["operation"] == "-":
                if mode["mode"] in client.user_modes:
                    client.user_modes.remove(mode["mode"])

        # Format mode string for display
        mode_str = mode_string
        if mode_params:
            mode_str += " " + " ".join(mode_params)

        # Add message to status
        client.add_message(
            f"Mode {client.nick} [{mode_str}] by {source_nick}",
            client.ui.colors["system"],
            context_name="Status",
        )

    # Dispatch general MODE event
    if hasattr(client, "script_manager"):
        event_data = {
            "target": target,
            "setter": source_nick,
            "setter_userhost": source_full_ident,
            "mode_string": mode_string,
            "mode_params": mode_params,
            "parsed_modes": parsed_modes,
            "raw_line": raw_line,
            "tags": parsed_msg.get_all_tags(),
        }
        client.script_manager.dispatch_event("MODE", event_data)


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
        _handle_cap_message(client, parsed_msg, line)
    elif cmd == "PING":
        ping_param = (
            parsed_msg.trailing
            if parsed_msg.trailing
            else (parsed_msg.params[0] if parsed_msg.params else "")
        )
        client.network_handler.send_raw(f"PONG :{ping_param}")
        logger.debug(f"Responded to PING with PONG {ping_param}")
    elif cmd == "AUTHENTICATE":
        payload = parsed_msg.params[0] if parsed_msg.params else ""
        if not hasattr(client, "sasl_authenticator") or not client.sasl_authenticator:
            logger.error(
                "AUTHENTICATE received, but client.sasl_authenticator is not initialized."
            )
            client.add_message(
                f"[SASL Error] Authenticator not ready for AUTHENTICATE {payload}",
                client.ui.colors["error"],
                "Status",
            )
            return

        if payload == "+":
            logger.info(f"SASL: Received AUTHENTICATE + challenge. Raw: {line.strip()}")
            client.sasl_authenticator.on_authenticate_challenge_received(payload)
        else:
            logger.warning(
                f"SASL: Received AUTHENTICATE with payload other than '+': '{payload}'. This is unusual. Relying on numerics for outcome. Raw: {line.strip()}"
            )
    elif cmd == "PRIVMSG":
        protocol_handler_instance._handle_privmsg(client, parsed_msg, line)
    elif cmd in ["JOIN", "PART", "QUIT", "KICK"]:
        _handle_membership_changes(client, parsed_msg, line)
    elif cmd == "NICK":
        _handle_nick_message(client, parsed_msg, line)
    elif cmd.isdigit():
        _handle_numeric_command(client, parsed_msg, line)
    elif cmd == "MODE":
        _handle_mode_message(client, parsed_msg, line)
    elif cmd == "TOPIC":
        channel = parsed_msg.params[0] if parsed_msg.params else None
        new_topic = parsed_msg.trailing
        if channel:
            if new_topic is not None:
                message = f"Topic for {channel} changed to: {new_topic}"
                if parsed_msg.source_nick:
                    message = f"{parsed_msg.source_nick} changed topic for {channel} to: {new_topic}"
            else:
                message = f"Topic for {channel} cleared."

            client.context_manager.update_topic(
                channel, new_topic if new_topic is not None else ""
            )
            client.add_message(
                message, client.ui.colors["system"], context_name=channel
            )

            # Dispatch TOPIC event
            if hasattr(client, "script_manager"):
                event_data = {
                    "nick": parsed_msg.source_nick,
                    "userhost": parsed_msg.prefix,
                    "channel": channel,
                    "topic": new_topic if new_topic is not None else "",
                    "client_nick": client.nick,
                    "raw_line": line,
                }
                client.script_manager.dispatch_event("TOPIC", event_data)
        else:
            logger.warning(f"Malformed TOPIC message (no channel): {line.strip()}")
    elif cmd == "NOTICE":
        protocol_handler_instance._handle_notice(client, parsed_msg, line)
    elif cmd == "CHGHOST":
        # Handle CHGHOST command (hostname change)
        src_nick = parsed_msg.source_nick
        new_ident = parsed_msg.params[0] if parsed_msg.params else ""
        new_host = parsed_msg.trailing if parsed_msg.trailing else ""

        if src_nick and new_ident and new_host:
            logger.info(f"Host change for {src_nick}: {new_ident}@{new_host}")
            # Update user's ident and host in all contexts where they exist
            for ctx_name, ctx_obj in client.context_manager.contexts.items():
                if ctx_obj.type == "channel" and src_nick in ctx_obj.users:
                    # The user's presence in the channel is already tracked,
                    # we just need to update their ident/host if needed
                    pass

            # Dispatch CHGHOST event
            if hasattr(client, "script_manager"):
                event_data_chghost = {
                    "nick": src_nick,
                    "new_ident": new_ident,
                    "new_host": new_host,
                    "userhost": parsed_msg.prefix,  # The original full userhost before change
                    "client_nick": client.nick,
                    "raw_line": line,
                }
                client.script_manager.dispatch_event("CHGHOST", event_data_chghost)
    else:
        display_p_parts = list(parsed_msg.params)
        if parsed_msg.trailing is not None:
            display_p_parts.append(f":{parsed_msg.trailing}")
        display_p = " ".join(display_p_parts)

        display_src = (
            parsed_msg.source_nick
            if parsed_msg.source_nick
            else (parsed_msg.prefix if parsed_msg.prefix else "SERVER")
        )

        logger.warning(
            f"Unhandled command '{cmd.upper()}' from '{display_src}': {display_p}. Raw: {line.strip()}"
        )
        client.add_message(
            f"[{cmd.upper()}] From: {display_src}, Data: {display_p}".strip(),
            client.ui.colors["system"],
            context_name="Status",
        )

    client.ui_needs_update.set()
