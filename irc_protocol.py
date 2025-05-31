# irc_protocol.py
import re
import logging
from collections import deque
from config import IRC_MSG_REGEX_PATTERN

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

    client_nick_lower = client.nick.lower() if client.nick else ""
    src_nick_lower = src_nick.lower() if src_nick else ""

    if cmd == "PING":
        ping_param = trailing if trailing else (params[0] if params else "")
        client.network.send_raw(f"PONG :{ping_param}")
        client.add_message(
            f"PONG {ping_param}",
            client.ui.colors["system"],
            prefix_time=False,
            context_name="Status",
        )

    elif cmd == "PRIVMSG":
        target = params[0] if params else None
        message = trailing

        if not target or message is None:
            client.add_message(
                f"[INVALID PRIVMSG] Raw: {line}",
                client.ui.colors["error"],
                context_name="Status",
            )
            logger.warning(f"Invalid PRIVMSG received: {line.strip()}")
            return

        target_lower = target.lower()
        msg_context_name = "Status"

        if target_lower == client_nick_lower:
            msg_context_name = f"Query:{src_nick}"
            if client.context_manager.create_context(msg_context_name, context_type="query"):
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
            # Check for ACTION message (CTCP ACTION)
            if message.startswith("\x01ACTION ") and message.endswith("\x01"):
                action_message = message[len("\x01ACTION "):-1]
                display_message = f"* {src_nick} {action_message}"
                # Use a different color for actions if desired, e.g., same as my_message or other_message
                # For now, let's use the same logic as regular messages, but could be client.ui.colors["action"]
            else:
                display_message = f"<{src_nick}> {message}"


            if client.nick and client.nick.lower() in message.lower() and not (message.startswith("\x01ACTION ") and message.endswith("\x01")): # Highlight non-action messages
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
                f"Received PRIVMSG to non-channel/non-PM target '{target}': {line.strip()}"
            )
            client.add_message(
                f"[{target}] <{src_nick}> {message}",
                client.ui.colors["system"],
                context_name="Status",
            )

    elif cmd == "JOIN":
        joined_channel_raw = trailing if trailing else (params[0] if params else None)
        joined_channel = joined_channel_raw.lstrip(":") if joined_channel_raw else None

        if not joined_channel:
            client.add_message(
                f"[INVALID JOIN] Missing channel. Raw: {line}",
                client.ui.colors["error"],
                context_name="Status",
            )
            logger.warning(f"Invalid JOIN message (no channel): {line.strip()}")
            return

        if client.context_manager.create_context(joined_channel, context_type="channel"):
            logger.debug(f"Ensured channel context exists for JOIN: {joined_channel}")

        if src_nick_lower == client_nick_lower:
            logger.info(f"Successfully joined channel: {joined_channel}")
            client.currently_joined_channels.add(joined_channel)
            logger.debug(f"Added {joined_channel} to currently_joined_channels. Current: {client.currently_joined_channels}")

            client.context_manager.set_active_context(joined_channel)
            joined_ctx = client.context_manager.get_context(joined_channel)
            if joined_ctx:
                joined_ctx.users.clear()
            client.network.send_raw(f"WHO {joined_channel}") # Get user list
            client.network.send_raw(f"MODE {joined_channel}") # Get channel modes
            client.add_message(
                f"You joined {joined_channel}",
                client.ui.colors["join_part"],
                context_name=joined_channel,
            )
        else:
            if client.context_manager.get_context(joined_channel): # Should exist
                client.context_manager.add_user(joined_channel, src_nick)
                client.add_message(
                    f"{src_nick} joined {joined_channel}",
                    client.ui.colors["join_part"],
                    context_name=joined_channel,
                )
            else:
                logger.error(
                    f"JOIN for {src_nick} in {joined_channel}, but context not found for user add."
                )

    elif cmd == "PART":
        parted_channel = params[0] if params else None
        if not parted_channel:
            client.add_message(
                f"[INVALID PART] Missing channel. Raw: {line}",
                client.ui.colors["error"],
                context_name="Status",
            )
            logger.warning(f"Invalid PART message (no channel): {line.strip()}")
            return

        reason = f" ({trailing})" if trailing else ""

        # Ensure context exists, though it should if we were in it or got a PART for it
        part_ctx_exists = client.context_manager.get_context(parted_channel)
        if not part_ctx_exists:
             client.context_manager.create_context(parted_channel, context_type="channel")


        if src_nick_lower == client_nick_lower:
            logger.info(f"We parted channel: {parted_channel}{reason}")
            client.currently_joined_channels.discard(parted_channel)
            logger.debug(f"Removed {parted_channel} from currently_joined_channels. Current: {client.currently_joined_channels}")

            client.add_message(
                f"You left {parted_channel}{reason}",
                client.ui.colors["join_part"],
                context_name=parted_channel,
            )
            parted_ctx = client.context_manager.get_context(parted_channel)
            if parted_ctx:
                parted_ctx.users.clear() # Clear user list for the channel we left

            # If the parted channel was active, switch to another context
            if client.context_manager.active_context_name == parted_channel:
                # Prefer switching to another joined channel if one exists
                other_joined_channels = sorted(list(client.currently_joined_channels))
                if other_joined_channels:
                    client.switch_active_context(other_joined_channels[0])
                elif "Status" in client.context_manager.get_all_context_names():
                    client.switch_active_context("Status")
                else: # Fallback if no status (should not happen)
                    all_ctx_names = client.context_manager.get_all_context_names()
                    if all_ctx_names: client.switch_active_context(all_ctx_names[0])

            # The window for parted_channel remains open unless explicitly closed by /close or /wc
            # The CommandHandler's /close logic will handle actual context removal.

        else:
            parted_ctx = client.context_manager.get_context(parted_channel)
            if parted_ctx:
                if src_nick and client.context_manager.remove_user(parted_channel, src_nick):
                    logger.debug(
                        f"Removed {src_nick} from {parted_channel} user list due to PART."
                    )
                client.add_message(
                    f"{src_nick} left {parted_channel}{reason}",
                    client.ui.colors["join_part"],
                    context_name=parted_channel,
                )
            else:
                logger.info(
                    f"Received PART from {src_nick} for untracked channel {parted_channel}{reason}"
                )
                client.add_message(
                    f"{src_nick} left {parted_channel}{reason} (not our current channel)",
                    client.ui.colors["join_part"],
                    context_name="Status",
                )

    elif cmd == "QUIT":
        reason = f" ({trailing})" if trailing else ""
        display_src_nick = src_nick if src_nick else "Someone"

        for ctx_name, ctx_obj in client.context_manager.contexts.items():
            if (
                ctx_obj.type == "channel"
                and src_nick
                and src_nick in ctx_obj.users
            ):
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
            # client.should_quit = True # No, this is server telling us we quit.
            # Network handler will detect socket close if server disconnects us.

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
                logger.info(f"Attempting to rename query context from {ctx_name} to {new_query_ctx_name} for NICK change.")

                client.context_manager.create_context(new_query_ctx_name, context_type="query", topic=ctx_obj.topic)
                new_query_ctx_obj = client.context_manager.get_context(new_query_ctx_name)

                if new_query_ctx_obj:
                    new_query_ctx_obj.messages = deque(list(ctx_obj.messages), maxlen=client.context_manager.max_history)
                    new_query_ctx_obj.users = set(list(ctx_obj.users))
                    new_query_ctx_obj.unread_count = ctx_obj.unread_count
                    new_query_ctx_obj.scrollback_offset = ctx_obj.scrollback_offset # Preserve scroll

                    was_active = (active_context_before_nick_change == ctx_name)
                    client.context_manager.remove_context(ctx_name)
                    logger.info(f"Successfully renamed query context from {ctx_name} to {new_query_ctx_name}.")

                    if was_active:
                        renamed_query_context_new_name = new_query_ctx_name
                else:
                    logger.error(f"Failed to create/get new query context {new_query_ctx_name} during NICK rename.")
                    client.add_message(
                        nick_change_message,
                        client.ui.colors["nick_change"],
                        context_name=ctx_name, # Message in old context
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

        kick_message = f"{user_kicked} was kicked from {channel_kicked_from} by {src_nick}{reason}"

        # Ensure context exists for the kick message
        if client.context_manager.create_context(channel_kicked_from, context_type="channel"):
             logger.debug(f"Ensured channel context exists for KICK: {channel_kicked_from}")

        client.add_message(kick_message, client.ui.colors["join_part"], context_name=channel_kicked_from)

        kicked_ctx = client.context_manager.get_context(channel_kicked_from)
        if kicked_ctx: # Should exist now
            client.context_manager.remove_user(channel_kicked_from, user_kicked)

        if user_kicked.lower() == client_nick_lower: # We were kicked
            logger.info(f"We were kicked from {channel_kicked_from} by {src_nick}{reason}")
            client.currently_joined_channels.discard(channel_kicked_from)
            logger.debug(f"Removed {channel_kicked_from} from currently_joined_channels due to KICK. Current: {client.currently_joined_channels}")

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
                    if all_ctx_names: client.switch_active_context(all_ctx_names[0])
            # Window remains open unless closed by /close or /wc

    elif cmd.isdigit():
        code = int(cmd)
        msg_info_params = params[1:] if len(params) > 1 else []

        if code == 1: # RPL_WELCOME
            client.nick = params[0] if params else client.initial_nick # Server confirms our nick
            client.add_message(
                f"Welcome to {client.server}: {trailing if trailing else ''}",
                client.ui.colors["system"],
                context_name="Status",
            )
            if client.nickserv_password:
                client.network.send_raw(
                    f"PRIVMSG NickServ :IDENTIFY {client.nick} {client.nickserv_password}"
                )
                client.add_message(
                    f"Attempting to identify with NickServ for {client.nick}...",
                    client.ui.colors["system"],
                    context_name="Status",
                )
            # Initial channel joins are now handled by NetworkHandler after 001
            # based on the list prepared by CommandHandler's /connect

        elif code in [2, 3, 4, 5]:  # RPL_YOURHOST, RPL_CREATED, RPL_MYINFO, RPL_ISUPPORT
            message_content = " ".join(msg_info_params)
            if trailing:
                message_content += f" :{trailing}"
            client.add_message(
                message_content.strip(),
                client.ui.colors["system"],
                prefix_time=False,
                context_name="Status",
            )
        elif code == 331:  # RPL_NOTOPIC
            channel_name = params[1] if len(params) > 1 else "channel"
            if client.context_manager.create_context(channel_name, context_type="channel"):
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
            if client.context_manager.create_context(channel_name, context_type="channel"):
                logger.debug(f"Ensured channel context {channel_name} for RPL_TOPIC.")
            client.context_manager.update_topic(channel_name, topic_text)
            client.add_message(
                f"Topic for {channel_name}: {topic_text}",
                client.ui.colors["system"],
                context_name=channel_name,
            )
        elif code == 353:  # RPL_NAMREPLY
            channel_in_reply = params[2] if len(params) > 2 else None
            if channel_in_reply :
                # Ensure context exists before adding users
                if client.context_manager.create_context(channel_in_reply, context_type="channel"):
                     logger.debug(f"Ensured channel context exists for NAMREPLY: {channel_in_reply}")

                target_ctx_for_names = client.context_manager.get_context(channel_in_reply)
                if target_ctx_for_names: # It should exist now
                    nicks_on_list = trailing.split() if trailing else []
                    for nick_entry in nicks_on_list:
                        actual_nick = nick_entry.lstrip("@+&~%")
                        client.context_manager.add_user(channel_in_reply, actual_nick)
                else:
                    logger.warning(f"RPL_NAMREPLY: Context {channel_in_reply} still not found after create attempt.")
            else:
                logger.warning(
                    f"RPL_NAMREPLY for unknown context: {channel_in_reply}. Raw: {line.strip()}"
                )
        elif code == 366:  # RPL_ENDOFNAMES
            channel_ended = params[1] if len(params) > 1 else "Unknown Channel"
            ctx_for_endofnames = client.context_manager.get_context(channel_ended)
            if ctx_for_endofnames:
                user_count = len(ctx_for_endofnames.users)
                # If we successfully joined this channel, mark it in currently_joined_channels
                # This is a good confirmation point if JOIN message was missed or WHO is slow
                if channel_ended not in client.currently_joined_channels:
                     # Check if this is a channel we intended to join or are already supposed to be in
                     # This can happen if JOIN is processed after NAMES reply due to server timing
                     logger.info(f"RPL_ENDOFNAMES for {channel_ended}. Adding to tracked joined channels.")
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
        elif code == 401: # ERR_NOSUCHNICK
            # Params: <client> <nickname> :No such nick/channel
            nosuch_nick = params[1] if len(params) > 1 else "nick"
            client.add_message(
                f"No such nick: {nosuch_nick}",
                client.ui.colors["error"],
                context_name=client.context_manager.active_context_name or "Status"
            )
        elif code == 403:  # ERR_NOSUCHCHANNEL
            channel_name = params[1] if len(params) > 1 else "channel"
            client.add_message(
                f"Channel {channel_name} does not exist or is invalid.",
                client.ui.colors["error"],
                context_name="Status",
            )
            # If we thought we were in this channel, remove it
            client.currently_joined_channels.discard(channel_name)
            logger.warning(
                f"ERR_NOSUCHCHANNEL ({code}) for {channel_name}: {line.strip()}. Removed from tracked channels."
            )
            # Optionally close the context if it exists and we get this error
            # if client.context_manager.get_context(channel_name):
            # client.command_handler.process_user_command(f"/close {channel_name} No such channel")


        elif code == 433:  # ERR_NICKNAMEINUSE
            failed_nick = params[1] if len(params) > 1 else client.nick
            logger.warning(
                f"ERR_NICKNAMEINUSE ({code}) for {failed_nick}: {line.strip()}"
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
                and not client.network.is_handling_nick_collision # Add a flag to prevent recursion
            ):
                client.network.is_handling_nick_collision = True # Set flag
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
                # client.nick = new_try_nick # Don't update client.nick until server confirms with NICK
            # else: client.network.is_handling_nick_collision = False # Reset if not our initial nick


        elif code in [311, 312, 313, 317, 318, 319, 301, 305, 306, 375, 372, 376]:  # WHOIS, AWAY, MOTD etc.
            display_p_list = params
            if params and params[0].lower() == client_nick_lower: # Often first param is our nick
                display_p_list = params[1:]

            display_p = " ".join(display_p_list)
            display_t = (":" + trailing) if trailing else ""

            # Determine context for these messages
            # WHOIS replies often have target nick as param[1]
            # AWAY replies might be for someone else
            # MOTD goes to Status
            target_context_for_info = "Status"
            if code == 311 and len(params) > 1: # RPL_WHOISUSER, param[1] is the whois'd nick
                # Could open a temp query-like window, or just status for now
                pass # Keep as Status for now

            client.add_message(
                f"[{cmd}] {display_p} {display_t}".strip(),
                client.ui.colors["system"],
                context_name=target_context_for_info,
            )
        else:
            display_params_list = params
            if params and params[0].lower() == client_nick_lower:
                display_params_list = params[1:]

            display_p = " ".join(display_params_list)
            display_t = (":" + trailing) if trailing else ""
            client.add_message(
                f"[{cmd}] {display_p} {display_t}".strip(),
                client.ui.colors["system"],
                context_name="Status",
            )
            logger.debug(f"Received numeric {cmd}: {line.strip()}")

    elif cmd == "MODE":
        mode_target = params[0] if params else None
        mode_changes_list = params[1:] if len(params) > 1 else []

        # Trailing part can also contain parameters for modes (like ban masks or nicks for +/-o)
        # For simple display, concatenate everything after the mode_target
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

        context_for_mode = "Status"
        if (
            mode_target
            and mode_target.startswith("#")
        ):
            if client.context_manager.create_context(mode_target, context_type="channel"): # Ensure context exists
                 logger.debug(f"Ensured channel context exists for MODE: {mode_target}")
            context_for_mode = mode_target
        elif (
            mode_target and client.nick and mode_target.lower() == client.nick.lower()
        ):
            context_for_mode = "Status"

        client.add_message(
            f"[MODE {mode_target}] by {display_src}: {mode_string_for_display.strip()}",
            client.ui.colors["system"],
            context_name=context_for_mode,
        )
        # TODO: Detailed MODE parsing to update channel modes (in Context) and user prefixes (in Context.users)

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
