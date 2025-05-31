# irc_protocol.py
import re
import logging
from collections import deque
from config import IRC_MSG_REGEX_PATTERN
import time

IRC_MSG_RE = re.compile(IRC_MSG_REGEX_PATTERN)
logger = logging.getLogger("pyrc.protocol")


class IRCMessage:
    def __init__(self, prefix, command, params_str, trailing):
        self.prefix = prefix
        self.command = command
        self.params_str = params_str.strip() if params_str else None
        self.trailing = trailing
        self.params = (
            [p for p in self.params_str.split(" ") if p] if self.params_str else []
        )
        self.source_nick = prefix.split("!")[0] if prefix and "!" in prefix else prefix

    @classmethod
    def parse(cls, line):
        match = IRC_MSG_RE.match(line)
        if not match:
            return None
        return cls(*match.groups())


def _handle_cap_message(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles CAP messages."""
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    cap_subcommand = params[1] if len(params) > 1 else None
    capabilities_str = (
        trailing if trailing else (params[2] if len(params) > 2 else "")
    )

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

    if cap_subcommand == "LS":
        client.handle_cap_ls(capabilities_str)
    elif cap_subcommand == "ACK":
        client.handle_cap_ack(capabilities_str)
    elif cap_subcommand == "NAK":
        client.handle_cap_nak(capabilities_str)
    elif cap_subcommand == "NEW":
        new_caps = set(capabilities_str.split())
        client.supported_caps.update(new_caps)
        client.enabled_caps.update(
            new_caps.intersection(client.desired_caps)
        )
        client.add_message(
            f"CAP NEW: Server now supports {', '.join(new_caps)}. Auto-enabled: {', '.join(client.enabled_caps.intersection(new_caps))}",
            client.ui.colors["system"],
            context_name="Status",
        )
    elif cap_subcommand == "DEL":
        deleted_caps = set(capabilities_str.split())
        client.supported_caps.difference_update(deleted_caps)
        client.enabled_caps.difference_update(deleted_caps)
        client.add_message(
            f"CAP DEL: Server no longer supports {', '.join(deleted_caps)}. Disabled: {', '.join(deleted_caps.intersection(client.enabled_caps))}",
            client.ui.colors["system"],
            context_name="Status",
        )
    else:
        client.add_message(
            f"[CAP] Unknown subcommand: {cap_subcommand} {capabilities_str}",
            client.ui.colors["system"],
            context_name="Status",
        )

def _handle_privmsg(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles PRIVMSG messages."""
    src_nick = parsed_msg.source_nick
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    client_nick_lower = client.nick.lower() if client.nick else ""
    src_nick_lower = src_nick.lower() if src_nick else ""

    target = params[0] if params else None
    message = trailing

    if not target or message is None:
        client.add_message(
            f"[INVALID PRIVMSG] Raw: {raw_line}",
            client.ui.colors["error"],
            context_name="Status",
        )
        logger.warning(f"Invalid PRIVMSG received: {raw_line.strip()}")
        return

    target_lower = target.lower()
    msg_context_name = "Status"

    if target_lower == client_nick_lower:
        msg_context_name = f"Query:{src_nick}"
        if client.context_manager.create_context(
            msg_context_name, context_type="query"
        ):
            logger.debug(
                f"Created query context for PM from {src_nick}: {msg_context_name}"
            )
        client.add_message(
            f"[PM from {src_nick}] {message}",
            client.ui.colors["pm"],
            context_name=msg_context_name,
        )
    elif target.startswith("#"):
        msg_context_name = target
        if client.context_manager.create_context(
            msg_context_name, context_type="channel"
        ):
            logger.debug(
                f"Ensured channel context exists for PRIVMSG: {msg_context_name}"
            )

        color_key = (
            "my_message" if src_nick_lower == client_nick_lower else "other_message"
        )
        if message.startswith("\x01ACTION ") and message.endswith("\x01"):
            action_message = message[len("\x01ACTION ") : -1]
            display_message = f"* {src_nick} {action_message}"
        else:
            display_message = f"<{src_nick}> {message}"

        if (
            client.nick
            and client.nick.lower() in message.lower()
            and not (message.startswith("\x01ACTION ") and message.endswith("\x01"))
        ):
            color_key = "highlight"
            logger.debug(
                f"Highlighting message in {msg_context_name} for nick {client.nick}"
            )
        client.add_message(
            display_message,
            client.ui.colors[color_key],
            context_name=msg_context_name,
        )
    else:
        logger.info(
            f"Received PRIVMSG to non-channel/non-PM target '{target}': {raw_line.strip()}"
        )
        client.add_message(
            f"[{target}] <{src_nick}> {message}",
            client.ui.colors["system"],
            context_name="Status",
        )

def _handle_nick_change(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles NICK messages."""
    src_nick = parsed_msg.source_nick
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    client_nick_lower = client.nick.lower() if client.nick else ""
    # src_nick_lower is not strictly needed here as we operate on src_nick directly for comparisons.

    new_nick = trailing if trailing else (params[0] if params else None)
    if not new_nick or not src_nick:
        client.add_message(
            f"[INVALID NICK] Raw: {raw_line}",
            client.ui.colors["error"],
            context_name="Status",
        )
        logger.warning(f"Invalid NICK message: {raw_line.strip()}")
        return

    nick_change_message = f"{src_nick} is now known as {new_nick}"
    active_context_before_nick_change = client.context_manager.active_context_name
    renamed_query_context_new_name = None

    for ctx_name in list(client.context_manager.contexts.keys()):
        ctx_obj = client.context_manager.get_context(ctx_name)
        if not ctx_obj:
            continue

        if ctx_obj.type == "channel":
            if src_nick in ctx_obj.users:
                client.context_manager.remove_user(ctx_name, src_nick)
                client.context_manager.add_user(ctx_name, new_nick)
                client.add_message(
                    nick_change_message,
                    client.ui.colors["nick_change"],
                    context_name=ctx_name,
                )
        elif ctx_obj.type == "query" and ctx_name == f"Query:{src_nick}":
            new_query_ctx_name = f"Query:{new_nick}"
            logger.info(
                f"Attempting to rename query context from {ctx_name} to {new_query_ctx_name} for NICK change."
            )

            client.context_manager.create_context(
                new_query_ctx_name, context_type="query", topic=ctx_obj.topic
            )
            new_query_ctx_obj = client.context_manager.get_context(
                new_query_ctx_name
            )

            if new_query_ctx_obj:
                source_messages_list = list(ctx_obj.messages)
                max_len = client.context_manager.max_history
                new_query_ctx_obj.messages = deque(
                    source_messages_list, maxlen=max_len
                )
                new_query_ctx_obj.users = set(list(ctx_obj.users))
                new_query_ctx_obj.unread_count = ctx_obj.unread_count
                new_query_ctx_obj.scrollback_offset = (
                    ctx_obj.scrollback_offset
                )  # Preserve scroll

                was_active = active_context_before_nick_change == ctx_name
                client.context_manager.remove_context(ctx_name)
                logger.info(
                    f"Successfully renamed query context from {ctx_name} to {new_query_ctx_name}."
                )

                if was_active:
                    renamed_query_context_new_name = new_query_ctx_name
            else:
                logger.error(
                    f"Failed to create/get new query context {new_query_ctx_name} during NICK rename."
                )
                client.add_message(
                    nick_change_message,
                    client.ui.colors["nick_change"],
                    context_name=ctx_name,  # Message in old context
                )

    if renamed_query_context_new_name:
        client.context_manager.set_active_context(renamed_query_context_new_name)

    if src_nick.lower() == client_nick_lower: # Check against the original client_nick_lower
        logger.info(f"Our nick changed from {client.nick} to {new_nick}.")
        old_nick_for_tracking = client.nick
        client.nick = new_nick
        # Update our own nick in user lists of channels we are in
        for ch_name in client.currently_joined_channels:
            ch_ctx = client.context_manager.get_context(ch_name)
            if ch_ctx and old_nick_for_tracking in ch_ctx.users:
                client.context_manager.remove_user(ch_name, old_nick_for_tracking)
                client.context_manager.add_user(ch_name, new_nick)

        client.add_message(
            nick_change_message,
            client.ui.colors["nick_change"],
            context_name="Status",
        )

def _handle_membership_changes(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles JOIN, PART, QUIT, KICK messages."""
    cmd = parsed_msg.command
    src_nick = parsed_msg.source_nick
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    client_nick_lower = client.nick.lower() if client.nick else ""
    src_nick_lower = src_nick.lower() if src_nick else ""

    if cmd == "JOIN":
        joined_channel_raw = trailing if trailing else (params[0] if params else None)
        joined_channel = joined_channel_raw.lstrip(":") if joined_channel_raw else None

        if not joined_channel:
            client.add_message(
                f"[INVALID JOIN] Missing channel. Raw: {raw_line}",
                client.ui.colors["error"],
                context_name="Status",
            )
            logger.warning(f"Invalid JOIN message (no channel): {raw_line.strip()}")
            return

        if client.context_manager.create_context(
            joined_channel, context_type="channel"
        ):
            logger.debug(f"Ensured channel context exists for JOIN: {joined_channel}")

        if src_nick_lower == client_nick_lower:
            logger.info(f"Successfully joined channel: {joined_channel}")
            client.currently_joined_channels.add(joined_channel)
            logger.debug(
                f"Added {joined_channel} to currently_joined_channels. Current: {client.currently_joined_channels}"
            )

            client.context_manager.set_active_context(joined_channel)
            joined_ctx = client.context_manager.get_context(joined_channel)
            if joined_ctx:
                joined_ctx.users.clear()
            client.network.send_raw(
                f"NAMES {joined_channel}"
            )  # Get user list via NAMES
            client.network.send_raw(f"MODE {joined_channel}")  # Get channel modes
            client.add_message(
                f"You joined {joined_channel}",
                client.ui.colors["join_part"],
                context_name=joined_channel,
            )
        else:  # Another user joined
            if client.context_manager.get_context(joined_channel):  # Should exist
                client.context_manager.add_user(joined_channel, src_nick)
                client.add_message(
                    f"{src_nick} joined {joined_channel}",
                    client.ui.colors["join_part"],
                    context_name=joined_channel,
                )
            else:  # Should not happen if JOIN was for a channel we are in or just created context for
                logger.error(
                    f"JOIN for {src_nick} in {joined_channel}, but context not found for user add."
                )

    elif cmd == "PART":
        parted_channel = params[0] if params else None
        reason_message = (
            f" ({trailing})" if trailing else ""
        )  # Store full reason string with parentheses

        if not parted_channel:
            logger.warning(f"PART command received with no channel: {raw_line.strip()}")
            client.add_message(
                f"[INVALID PART] {raw_line.strip()}", client.ui.colors["error"], "Status"
            )
            return

        part_ctx_exists = client.context_manager.get_context(parted_channel)
        if not part_ctx_exists:
            client.context_manager.create_context(
                parted_channel, context_type="channel"
            )

        if src_nick_lower == client_nick_lower:
            logger.info(f"We parted channel: {parted_channel}{reason_message}")
            client.currently_joined_channels.discard(parted_channel)
            logger.debug(
                f"Removed {parted_channel} from currently_joined_channels. Current: {client.currently_joined_channels}"
            )

            client.add_message(
                f"You left {parted_channel}{reason_message}",
                client.ui.colors["join_part"],
                context_name=parted_channel,
            )
            parted_ctx = client.context_manager.get_context(parted_channel)
            if parted_ctx:
                parted_ctx.users.clear()

            if client.context_manager.active_context_name == parted_channel:
                other_joined_channels = sorted(list(client.currently_joined_channels))
                if other_joined_channels:
                    client.switch_active_context(other_joined_channels[0])
                elif "Status" in client.context_manager.get_all_context_names():
                    client.switch_active_context("Status")
                else:
                    all_ctx_names = client.context_manager.get_all_context_names()
                    if all_ctx_names:
                        client.switch_active_context(all_ctx_names[0])

            logger.debug(
                f"Attempting to remove context for parted channel: {parted_channel}"
            )
            if client.context_manager.remove_context(parted_channel):
                logger.info(
                    f"Successfully removed context for parted channel: {parted_channel}"
                )
            else:
                logger.warning(
                    f"Failed to remove context for parted channel: {parted_channel} (it might have been already removed or never fully existed with normalized name)"
                )

        else: # Another user parted
            parted_ctx = client.context_manager.get_context(parted_channel)
            if parted_ctx:
                if src_nick and client.context_manager.remove_user(
                    parted_channel, src_nick
                ):
                    logger.debug(
                        f"Removed {src_nick} from {parted_channel} user list due to PART."
                    )
                client.add_message(
                    f"{src_nick} left {parted_channel}{reason_message}",
                    client.ui.colors["join_part"],
                    context_name=parted_channel,
                )
            else:
                logger.info(
                    f"Received PART from {src_nick} for untracked channel {parted_channel}{reason_message}"
                )
                client.add_message(
                    f"{src_nick} left {parted_channel}{reason_message} (not our current channel)",
                    client.ui.colors["join_part"],
                    context_name="Status",
                )

    elif cmd == "QUIT":
        reason = f" ({trailing})" if trailing else ""
        display_src_nick = src_nick if src_nick else "Someone"

        for ctx_name, ctx_obj in client.context_manager.contexts.items():
            if ctx_obj.type == "channel" and src_nick and src_nick in ctx_obj.users:
                client.context_manager.remove_user(ctx_name, src_nick)
                client.add_message(
                    f"{display_src_nick} quit{reason}",
                    client.ui.colors["join_part"],
                    context_name=ctx_name,
                )

        if src_nick_lower == client_nick_lower:
            logger.info(
                f"Received QUIT message for our own nick: {client.nick}{reason}"
            )
            client.add_message(
                f"You have quit{reason}",
                client.ui.colors["join_part"],
                context_name="Status",
            )

    elif cmd == "KICK":
        channel_kicked_from = params[0] if len(params) > 0 else None
        user_kicked = params[1] if len(params) > 1 else None
        reason = f" ({trailing})" if trailing else ""

        if not channel_kicked_from or not user_kicked:
            logger.warning(f"Invalid KICK message: {raw_line.strip()}")
            return

        kick_message = (
            f"{user_kicked} was kicked from {channel_kicked_from} by {src_nick}{reason}"
        )

        if client.context_manager.create_context(
            channel_kicked_from, context_type="channel"
        ):
            logger.debug(
                f"Ensured channel context exists for KICK: {channel_kicked_from}"
            )

        client.add_message(
            kick_message,
            client.ui.colors["join_part"],
            context_name=channel_kicked_from,
        )

        kicked_ctx = client.context_manager.get_context(channel_kicked_from)
        if kicked_ctx:
            client.context_manager.remove_user(channel_kicked_from, user_kicked)

        if user_kicked.lower() == client_nick_lower:  # We were kicked
            logger.info(
                f"We were kicked from {channel_kicked_from} by {src_nick}{reason}"
            )
            client.currently_joined_channels.discard(channel_kicked_from)
            logger.debug(
                f"Removed {channel_kicked_from} from currently_joined_channels due to KICK. Current: {client.currently_joined_channels}"
            )

            if kicked_ctx:
                kicked_ctx.users.clear()

            if client.context_manager.active_context_name == channel_kicked_from:
                other_joined_channels = sorted(list(client.currently_joined_channels))
                if other_joined_channels:
                    client.switch_active_context(other_joined_channels[0])
                elif "Status" in client.context_manager.get_all_context_names():
                    client.switch_active_context("Status")
                else:
                    all_ctx_names = client.context_manager.get_all_context_names()
                    if all_ctx_names:
                        client.switch_active_context(all_ctx_names[0])

def _handle_numeric_command(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles numeric IRC replies."""
    code = int(parsed_msg.command)
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    # src_nick = parsed_msg.source_nick # Available if needed
    client_nick_lower = client.nick.lower() if client.nick else ""

    if code == 1:  # RPL_WELCOME
        client.nick = (
            params[0] if params else client.initial_nick
        )  # Server confirms our nick
        client.add_message(
            f"Welcome to {client.server}: {trailing if trailing else ''}",
            client.ui.colors["system"],
            context_name="Status",
        )
        logger.info(f"Received RPL_WELCOME (001). Nick confirmed as {client.nick}.")

        client.handle_cap_end_confirmation()

        if client.cap_negotiation_finished_event.wait(timeout=5.0):
            logger.info(
                "CAP negotiation finished event set, proceeding with post-001 actions."
            )
            if client.initial_channels_list:
                for channel in client.initial_channels_list:
                    client.command_handler.process_user_command(f"/join {channel}")
            elif (
                client.network.channels_to_join_on_connect
            ):
                for channel in client.network.channels_to_join_on_connect:
                    client.command_handler.process_user_command(f"/join {channel}")
                client.network.channels_to_join_on_connect = []

            if client.nickserv_password and not (
                "sasl" in client.enabled_caps
                and client.sasl_authentication_initiated
            ):
                client.command_handler.process_user_command(
                    f"/msg NickServ IDENTIFY {client.nickserv_password}"
                )
        else:
            logger.warning(
                "Timed out waiting for CAP negotiation to finish after 001. Channel joins/NickServ might be delayed or fail."
            )
            client.add_message(
                "Warning: CAP negotiation timed out post-welcome. Some features might be delayed.",
                client.ui.colors["error"],
                context_name="Status",
            )

    elif code == 331:  # RPL_NOTOPIC
        channel_name = params[1] if len(params) > 1 else "channel"
        if client.context_manager.create_context(
            channel_name, context_type="channel"
        ):
            logger.debug(f"Ensured channel context {channel_name} for RPL_NOTOPIC.")
        context = client.context_manager.get_context(channel_name)
        if context:
            context.topic = None
        client.add_message(
            f"No topic set for {channel_name}.",
            client.ui.colors["system"],
            context_name=channel_name,
        )
    elif code == 332:  # RPL_TOPIC
        channel_name = params[1] if len(params) > 1 else "channel"
        topic_text = trailing if trailing else ""
        if client.context_manager.create_context(
            channel_name, context_type="channel"
        ):
            logger.debug(f"Ensured channel context {channel_name} for RPL_TOPIC.")
        client.context_manager.update_topic(channel_name, topic_text)
        client.add_message(
            f"Topic for {channel_name}: {topic_text}",
            client.ui.colors["system"],
            context_name=channel_name,
        )
    elif code == 353:  # RPL_NAMREPLY
        channel_in_reply = params[2] if len(params) > 2 else None
        if channel_in_reply:
            if client.context_manager.create_context(
                channel_in_reply, context_type="channel"
            ):
                logger.debug(
                    f"Ensured channel context exists for NAMREPLY: {channel_in_reply}"
                )

            target_ctx_for_names = client.context_manager.get_context(
                channel_in_reply
            )
            if target_ctx_for_names:
                nicks_on_list = trailing.split() if trailing else []
                for nick_entry in nicks_on_list:
                    prefix_char = ""
                    actual_nick = nick_entry
                    if nick_entry.startswith("@"):
                        prefix_char = "@"
                        actual_nick = nick_entry[1:]
                    elif nick_entry.startswith("+"):
                        prefix_char = "+"
                        actual_nick = nick_entry[1:]
                    elif nick_entry.startswith("%"):
                        prefix_char = "%"
                        actual_nick = nick_entry[1:]
                    elif nick_entry.startswith("&") or nick_entry.startswith("~"):
                        prefix_char = nick_entry[0]
                        actual_nick = nick_entry[1:]
                    client.context_manager.add_user(
                        channel_in_reply, actual_nick, prefix_char
                    )
            else:
                logger.warning(
                    f"RPL_NAMREPLY: Context {channel_in_reply} still not found after create attempt."
                )
        else:
            logger.warning(
                f"RPL_NAMREPLY for unknown context: {channel_in_reply}. Raw: {raw_line.strip()}"
            )
    elif code == 366:  # RPL_ENDOFNAMES
        channel_ended = params[1] if len(params) > 1 else "Unknown Channel"
        ctx_for_endofnames = client.context_manager.get_context(channel_ended)
        if ctx_for_endofnames:
            user_count = len(ctx_for_endofnames.users)
            if channel_ended not in client.currently_joined_channels:
                logger.info(
                    f"RPL_ENDOFNAMES for {channel_ended}. Adding to tracked joined channels."
                )
                client.currently_joined_channels.add(channel_ended)

            logger.info(
                f"RPL_ENDOFNAMES for {channel_ended}. User count: {user_count}. Current joined: {client.currently_joined_channels}"
            )
            client.add_message(
                f"Users in {channel_ended}: {user_count}",
                client.ui.colors["system"],
                context_name=channel_ended,
            )
        else:
            logger.warning(
                f"RPL_ENDOFNAMES for {channel_ended}, but context not found."
            )
            client.add_message(
                f"End of names for {channel_ended} (context not found).",
                client.ui.colors["error"],
                context_name="Status",
            )
    elif code == 401:  # ERR_NOSUCHNICK
        nosuch_nick = params[1] if len(params) > 1 else "nick"
        client.add_message(
            f"No such nick: {nosuch_nick}",
            client.ui.colors["error"],
            context_name=client.context_manager.active_context_name or "Status",
        )
    elif code == 403:  # ERR_NOSUCHCHANNEL
        channel_name = params[1] if len(params) > 1 else "channel"
        client.add_message(
            f"Channel {channel_name} does not exist or is invalid.",
            client.ui.colors["error"],
            context_name="Status",
        )
        client.currently_joined_channels.discard(channel_name)
        logger.warning(
            f"ERR_NOSUCHCHANNEL ({code}) for {channel_name}: {raw_line.strip()}. Removed from tracked channels."
        )
    elif code == 433:  # ERR_NICKNAMEINUSE
        failed_nick = params[1] if len(params) > 1 else client.nick
        logger.warning(
            f"ERR_NICKNAMEINUSE ({code}) for {failed_nick}: {raw_line.strip()}"
        )
        client.add_message(
            f"Nickname {failed_nick} is already in use.",
            client.ui.colors["error"],
            context_name="Status",
        )
        if (
            client.nick
            and client.nick.lower() == failed_nick.lower()
            and client.nick.lower() == client.initial_nick.lower()
            and not client.network.is_handling_nick_collision
        ):
            client.network.is_handling_nick_collision = True
            new_try_nick = f"{client.initial_nick}_"
            logger.info(
                f"Nickname {failed_nick} (initial) in use, trying {new_try_nick}."
            )
            client.add_message(
                f"Trying {new_try_nick} instead.",
                client.ui.colors["system"],
                context_name="Status",
            )
            client.network.send_raw(f"NICK {new_try_nick}")
    elif code == 900:  # RPL_LOGGEDIN
        account_name = params[2] if len(params) > 2 else "your account"
        success_msg = f"Successfully logged in as {account_name} (900)."
        logger.info(f"SASL: {success_msg} Raw: {raw_line.strip()}")
        client.add_message(
            f"SASL: {success_msg}",
            client.ui.colors["system"],
            context_name="Status",
        )
        client.handle_sasl_success(success_msg)
    elif code == 903:  # RPL_SASLSUCCESS
        success_msg = "SASL authentication successful (903)."
        logger.info(f"SASL: {success_msg} Raw: {raw_line.strip()}")
        client.add_message(
            f"SASL: {success_msg}",
            client.ui.colors["system"],
            context_name="Status",
        )
        client.handle_sasl_success(success_msg)
    elif (
        code == 902 or code == 908
    ):  # RPL_SASLMECHS or ERR_SASLMECHS
        mechanisms = (
            trailing if trailing else (params[1] if len(params) > 1 else "unknown")
        )
        logger.info(
            f"SASL: Server indicated mechanisms: {mechanisms} (Code: {code}). Raw: {raw_line.strip()}"
        )
        client.add_message(
            f"SASL: Server mechanisms: {mechanisms}",
            client.ui.colors["system"],
            context_name="Status",
        )
    elif code == 904:  # ERR_SASLFAIL
        reason = trailing if trailing else "SASL authentication failed (904)"
        logger.warning(
            f"SASL: Authentication failed (904). Reason: {reason}. Raw: {raw_line.strip()}"
        )
        client.add_message(
            f"SASL Error: {reason}",
            client.ui.colors["error"],
            context_name="Status",
        )
        client.handle_sasl_failure(reason)
    elif code == 905:  # ERR_SASLTOOLONG
        reason = (
            trailing
            if trailing
            else "SASL message too long / Base64 decoding error (905)"
        )
        logger.warning(
            f"SASL: Authentication failed (905). Reason: {reason}. Raw: {raw_line.strip()}"
        )
        client.add_message(
            f"SASL Error: {reason}",
            client.ui.colors["error"],
            context_name="Status",
        )
        client.handle_sasl_failure(reason)
    elif code == 906:  # ERR_SASLABORTED
        reason = (
            trailing
            if trailing
            else "SASL authentication aborted by server or client (906)"
        )
        logger.warning(
            f"SASL: Authentication aborted (906). Reason: {reason}. Raw: {raw_line.strip()}"
        )
        client.add_message(
            f"SASL Error: {reason}",
            client.ui.colors["error"],
            context_name="Status",
        )
        client.handle_sasl_failure(reason)
    elif code == 907:  # ERR_SASLALREADY
        reason = trailing if trailing else "You have already authenticated (907)"
        logger.warning(
            f"SASL: Already authenticated (907). Reason: {reason}. Raw: {raw_line.strip()}"
        )
        client.add_message(
            f"SASL Warning: {reason}",
            client.ui.colors["warning"],
            context_name="Status",
        )
        if (
            not client.is_sasl_completed()
            or client.sasl_authentication_succeeded is not True
        ):
            logger.error(
                "SASL: Server says already authenticated, but client state disagrees."
            )
            client.handle_sasl_success(reason)
    elif code in [
        311, 312, 313, 317, 318, 319, 301, 305, 306, 375, 372, 376,
    ]:  # WHOIS, AWAY, MOTD etc.
        display_p_list = params
        if (
            params and params[0].lower() == client_nick_lower
        ):
            display_p_list = params[1:]
        display_p = " ".join(display_p_list)
        display_t = (":" + trailing) if trailing else ""
        target_context_for_info = "Status"
        if (
            code == 311 and len(params) > 1
        ):
            pass
        client.add_message(
            f"[{parsed_msg.command}] {display_p} {display_t}".strip(), # Use parsed_msg.command for original numeric string
            client.ui.colors["system"],
            context_name=target_context_for_info,
        )
    else: # Default handler for other numerics
        display_params_list = params
        if params and params[0].lower() == client_nick_lower:
            display_params_list = params[1:]
        display_p = " ".join(display_params_list)
        display_t = (":" + trailing) if trailing else ""
        client.add_message(
            f"[{parsed_msg.command}] {display_p} {display_t}".strip(), # Use parsed_msg.command
            client.ui.colors["system"],
            context_name="Status",
        )
        logger.debug(f"Received numeric {parsed_msg.command}: {raw_line.strip()}")


def _handle_mode_message(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles MODE messages."""
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    src_nick = parsed_msg.source_nick
    # client_nick_lower = client.nick.lower() if client.nick else "" # Defined in main handler if needed by all

    mode_target = params[0] if params else None
    # mode_changes_list = params[1:] if len(params) > 1 else [] # Not directly used like this

    mode_string_for_display = " ".join(params[1:])
    if trailing:
        mode_string_for_display += f" :{trailing}"

    display_src = (
        src_nick
        if src_nick
        else (parsed_msg.prefix if parsed_msg.prefix else "SERVER")
    )
    logger.info(
        f"MODE received: By: {display_src}, Target: {mode_target}, Changes: {mode_string_for_display.strip()}"
    )

    context_for_mode_message = "Status"
    target_is_channel = mode_target and mode_target.startswith("#")

    if target_is_channel:
        if client.context_manager.create_context(
            mode_target, context_type="channel"
        ):
            logger.debug(f"Ensured channel context exists for MODE: {mode_target}")
        context_for_mode_message = mode_target
    elif mode_target and client.nick and mode_target.lower() == client.nick.lower():
        context_for_mode_message = "Status"

    client.add_message(
        f"[MODE {mode_target}] by {display_src}: {mode_string_for_display.strip()}",
        client.ui.colors["system"],
        context_name=context_for_mode_message,
    )

    if target_is_channel and len(params) > 1:
        mode_str = params[1]
        mode_args = params[2:]

        current_op = None
        arg_idx = 0

        for char_idx, char in enumerate(mode_str):
            if char == "+":
                current_op = "+"
            elif char == "-":
                current_op = "-"
            elif current_op and arg_idx < len(mode_args):
                nick_affected = mode_args[arg_idx]
                new_prefix = ""

                if char == "o":
                    if current_op == "+":
                        new_prefix = "@"
                    client.context_manager.update_user_prefix(
                        mode_target,
                        nick_affected,
                        new_prefix if current_op == "-" else new_prefix,
                    )
                    logger.info(
                        f"MODE {current_op}{char} for {nick_affected} in {mode_target}. New prefix: '{new_prefix if current_op == '-' else new_prefix}'"
                    )
                    arg_idx += 1
                elif char == "v":
                    if current_op == "+":
                        current_user_prefix = (
                            client.context_manager.get_user_prefix(
                                mode_target, nick_affected
                            )
                        )
                        if current_user_prefix != "@":
                            new_prefix = "+"
                        else:
                            new_prefix = "@"
                    client.context_manager.update_user_prefix(
                        mode_target,
                        nick_affected,
                        new_prefix if current_op == "-" else new_prefix,
                    )
                    logger.info(
                        f"MODE {current_op}{char} for {nick_affected} in {mode_target}. New prefix: '{new_prefix if current_op == '-' else new_prefix}'"
                    )
                    arg_idx += 1
            elif current_op is None and char not in "+-":
                logger.debug(
                    f"MODE char '{char}' encountered without preceding +/-. Skipping."
                )

def handle_server_message(client, line):
    """
    Processes a raw message line from the IRC server and calls
    appropriate methods on the client object to update state or UI.
    """
    parsed_msg = IRCMessage.parse(line)

    if not parsed_msg:
        logger.error(f"Failed to parse IRC message: {line.strip()}")
        client.add_message(
            f"[UNPARSED] {line}", client.ui.colors["error"], context_name="Status"
        )
        return

    cmd = parsed_msg.command
    src_nick = parsed_msg.source_nick
    params = parsed_msg.params
    trailing = parsed_msg.trailing

    # Define these here for use in handlers that are not yet refactored out
    client_nick_lower = client.nick.lower() if client.nick else ""
    src_nick_lower = src_nick.lower() if src_nick else ""

    # Process RAW trigger first
    raw_data = {
        "event_type": "RAW",
        "raw_line": line,
        "timestamp": time.time(),
        "client_nick": client.nick,
        "prefix": parsed_msg.prefix,
        "command": parsed_msg.command,
        "params_list": parsed_msg.params,
        "trailing": parsed_msg.trailing,
        "numeric": int(parsed_msg.command) if parsed_msg.command.isdigit() else None,
    }
    client.process_trigger_event("RAW", raw_data)

    if cmd == "CAP":
        _handle_cap_message(client, parsed_msg, line)
    elif cmd == "PING":
        ping_param = trailing if trailing else (params[0] if params else "")
        client.network.send_raw(f"PONG :{ping_param}")
        client.add_message(
            f"PONG {ping_param}",
            client.ui.colors["system"],
            prefix_time=False,
            context_name="Status",
        )
    elif cmd == "AUTHENTICATE":
        payload = params[0] if params else ""
        if payload == "+":
            logger.info(f"SASL: Received AUTHENTICATE + challenge. Raw: {line.strip()}")
            client.handle_sasl_authenticate_challenge(payload)
        else:
            logger.warning(
                f"SASL: Received AUTHENTICATE with unexpected payload: '{payload}'. Raw: {line.strip()}"
            )
    elif cmd == "PRIVMSG":
        _handle_privmsg(client, parsed_msg, line)
    elif cmd in ["JOIN", "PART", "QUIT", "KICK"]:
        _handle_membership_changes(client, parsed_msg, line)
    elif cmd == "NICK":
        new_nick = trailing if trailing else (params[0] if params else None)
        if not new_nick or not src_nick:
            client.add_message(
                f"[INVALID NICK] Raw: {line}",
                client.ui.colors["error"],
                context_name="Status",
            )
            logger.warning(f"Invalid NICK message: {line.strip()}")
            return

        nick_change_message = f"{src_nick} is now known as {new_nick}"
        active_context_before_nick_change = client.context_manager.active_context_name
        renamed_query_context_new_name = None

        for ctx_name in list(client.context_manager.contexts.keys()):
            ctx_obj = client.context_manager.get_context(ctx_name)
            if not ctx_obj:
                continue

            if ctx_obj.type == "channel":
                if src_nick in ctx_obj.users:
                    client.context_manager.remove_user(ctx_name, src_nick)
                    client.context_manager.add_user(ctx_name, new_nick)
                    client.add_message(
                        nick_change_message,
                        client.ui.colors["nick_change"],
                        context_name=ctx_name,
                    )
            elif ctx_obj.type == "query" and ctx_name == f"Query:{src_nick}":
                new_query_ctx_name = f"Query:{new_nick}"
                logger.info(
                    f"Attempting to rename query context from {ctx_name} to {new_query_ctx_name} for NICK change."
                )

                client.context_manager.create_context(
                    new_query_ctx_name, context_type="query", topic=ctx_obj.topic
                )
                new_query_ctx_obj = client.context_manager.get_context(
                    new_query_ctx_name
                )

                if new_query_ctx_obj:
                    source_messages_list = list(ctx_obj.messages)
                    max_len = client.context_manager.max_history
                    new_query_ctx_obj.messages = deque(
                        source_messages_list, maxlen=max_len
                    )
                    new_query_ctx_obj.users = set(list(ctx_obj.users))
                    new_query_ctx_obj.unread_count = ctx_obj.unread_count
                    new_query_ctx_obj.scrollback_offset = (
                        ctx_obj.scrollback_offset
                    )  # Preserve scroll

                    was_active = active_context_before_nick_change == ctx_name
                    client.context_manager.remove_context(ctx_name)
                    logger.info(
                        f"Successfully renamed query context from {ctx_name} to {new_query_ctx_name}."
                    )

                    if was_active:
                        renamed_query_context_new_name = new_query_ctx_name
                else:
                    logger.error(
                        f"Failed to create/get new query context {new_query_ctx_name} during NICK rename."
                    )
                    client.add_message(
                        nick_change_message,
                        client.ui.colors["nick_change"],
                        context_name=ctx_name,  # Message in old context
                    )

        if renamed_query_context_new_name:
            client.context_manager.set_active_context(renamed_query_context_new_name)

        if src_nick_lower == client_nick_lower:
            logger.info(f"Our nick changed from {client.nick} to {new_nick}.")
            old_nick_for_tracking = client.nick
            client.nick = new_nick
            # Update our own nick in user lists of channels we are in
            for ch_name in client.currently_joined_channels:
                ch_ctx = client.context_manager.get_context(ch_name)
                if ch_ctx and old_nick_for_tracking in ch_ctx.users:
                    client.context_manager.remove_user(ch_name, old_nick_for_tracking)
                    client.context_manager.add_user(ch_name, new_nick)

            client.add_message(
                nick_change_message,
                client.ui.colors["nick_change"],
                context_name="Status",
            )

    elif cmd == "KICK":
        channel_kicked_from = params[0] if len(params) > 0 else None
        user_kicked = params[1] if len(params) > 1 else None
        reason = f" ({trailing})" if trailing else ""

        if not channel_kicked_from or not user_kicked:
            logger.warning(f"Invalid KICK message: {line.strip()}")
            return

        kick_message = (
            f"{user_kicked} was kicked from {channel_kicked_from} by {src_nick}{reason}"
        )

        # Ensure context exists for the kick message
        if client.context_manager.create_context(
            channel_kicked_from, context_type="channel"
        ):
            logger.debug(
                f"Ensured channel context exists for KICK: {channel_kicked_from}"
            )

        client.add_message(
            kick_message,
            client.ui.colors["join_part"],
            context_name=channel_kicked_from,
        )

        kicked_ctx = client.context_manager.get_context(channel_kicked_from)
        if kicked_ctx:  # Should exist now
            client.context_manager.remove_user(channel_kicked_from, user_kicked)

        if user_kicked.lower() == client_nick_lower:  # We were kicked
            logger.info(
                f"We were kicked from {channel_kicked_from} by {src_nick}{reason}"
            )
            client.currently_joined_channels.discard(channel_kicked_from)
            logger.debug(
                f"Removed {channel_kicked_from} from currently_joined_channels due to KICK. Current: {client.currently_joined_channels}"
            )

            if kicked_ctx:
                kicked_ctx.users.clear()

            if client.context_manager.active_context_name == channel_kicked_from:
                other_joined_channels = sorted(list(client.currently_joined_channels))
                if other_joined_channels:
                    client.switch_active_context(other_joined_channels[0])
                elif "Status" in client.context_manager.get_all_context_names():
                    client.switch_active_context("Status")
                else:
                    all_ctx_names = client.context_manager.get_all_context_names()
                    if all_ctx_names:
                        client.switch_active_context(all_ctx_names[0])
            # Window remains open unless closed by /close or /wc

    elif cmd in ["JOIN", "PART", "QUIT", "KICK"]:
        _handle_membership_changes(client, parsed_msg, line)
    elif cmd == "NICK":
        _handle_nick_change(client, parsed_msg, line)
    elif cmd.isdigit():
        _handle_numeric_command(client, parsed_msg, line)
    elif cmd == "MODE":
        _handle_mode_message(client, parsed_msg, line)
    else:
        display_p = " ".join(params)
        display_t = (":" + trailing) if trailing else ""
        display_src = (
            src_nick
            if src_nick
            else (parsed_msg.prefix if parsed_msg.prefix else "SERVER")
        )
        logger.warning(
            f"Unhandled command '{cmd.upper()}' from '{display_src}': P='{display_p}' T='{display_t}'. Raw: {line.strip()}"
        )
        client.add_message(
            f"[{cmd.upper()}] From: {display_src}, Params: {display_p}, Trailing: {display_t}".strip(),
            client.ui.colors["system"],
            context_name="Status",
        )

    client.ui_needs_update.set()
