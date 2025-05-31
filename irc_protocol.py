# irc_protocol.py
import re
import logging  # Added for logging
from collections import deque # For NICK query context message copying
from config import IRC_MSG_REGEX_PATTERN

IRC_MSG_RE = re.compile(IRC_MSG_REGEX_PATTERN)
logger = logging.getLogger("pyrc.protocol")  # Child logger


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

    # --- For detailed regex debugging (usually commented out) ---
    # client.add_message(f"[RECV RAW] Line: '{line}'", client.ui.colors['system'])
    # if parsed_msg:
    #     client.add_message(f"[RECV PARSED] Pfx:'{parsed_msg.prefix}' Cmd:'{parsed_msg.command}' PrmsStr:'{parsed_msg.params_str}' Params:{parsed_msg.params} Trl:'{parsed_msg.trailing}' SrcNick:'{parsed_msg.source_nick}'", client.ui.colors['system'])
    # else:
    #     client.add_message(f"[RECV NO PARSE] Line: '{line}'", client.ui.colors['error'])
    #     return # If no parse, can't continue
    # --- End Regex Debug Block ---

    if not parsed_msg:
        logger.error(f"Failed to parse IRC message: {line.strip()}")
        client.add_message(
            f"[UNPARSED] {line}", client.ui.colors["error"], context_name="Status"
        )
        return

    # Log parsed message for debugging if needed (can be verbose)
    # logger.debug(f"Parsed IRC: Pfx='{parsed_msg.prefix}' Cmd='{parsed_msg.command}' ParamsStr='{parsed_msg.params_str}' Trail='{parsed_msg.trailing}' SrcNick='{parsed_msg.source_nick}'")

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
        msg_context_name = "Status"  # Default context for PRIVMSG if not channel or PM

        if target_lower == client_nick_lower:  # PM to us
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
        elif target.startswith("#"):  # Channel message
            msg_context_name = target
            if client.context_manager.create_context(
                msg_context_name, context_type="channel"
            ):  # Ensure context exists
                logger.debug(
                    f"Ensured channel context exists for PRIVMSG: {msg_context_name}"
                )

            color_key = (
                "my_message" if src_nick_lower == client_nick_lower else "other_message"
            )
            if (
                client.nick and client.nick.lower() in message.lower()
            ):  # Highlight if our nick is mentioned
                color_key = "highlight"
                logger.debug(
                    f"Highlighting message in {msg_context_name} for nick {client.nick}"
                )
            client.add_message(
                f"<{src_nick}> {message}",
                client.ui.colors[color_key],
                context_name=msg_context_name,
            )
        else:  # Other PRIVMSG, e.g. to services or unknown targets
            logger.info(
                f"Received PRIVMSG to non-channel/non-PM target '{target}': {line.strip()}"
            )
            client.add_message(
                f"[{target}] <{src_nick}> {message}",
                client.ui.colors["system"],
                context_name="Status",  # Log to status for now
            )

    elif cmd == "JOIN":
        # JOIN format: :nick!user@host JOIN #channel
        # Or on some servers: :nick!user@host JOIN :#channel (trailing can be the channel)
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

        if src_nick_lower == client_nick_lower:  # We joined
            logger.info(f"Successfully joined channel: {joined_channel}")
            client.context_manager.set_active_context(joined_channel) # Use manager to set active context
            joined_ctx = client.context_manager.get_context(joined_channel)
            if joined_ctx:
                joined_ctx.users.clear()  # Clear old user list on rejoin
                logger.debug(
                    f"Cleared user list for {joined_channel} on our join, sending WHO."
                )
            else:
                logger.error(f"JOIN: Context {joined_channel} not found after create for clearing users.")
            client.network.send_raw(f"WHO {joined_channel}")
            client.add_message(
                f"You joined {joined_channel}",
                client.ui.colors["join_part"],
                context_name=joined_channel,
            )
        else:  # Someone else joined a channel
            # Add user to the specific channel's user list
            if client.context_manager.get_context(joined_channel):
                client.context_manager.add_user(joined_channel, src_nick)
                logger.debug(f"Added user {src_nick} to {joined_channel} user list.")
                client.add_message(
                    f"{src_nick} joined {joined_channel}",
                    client.ui.colors["join_part"],
                    context_name=joined_channel,
                )
            else:  # Should not happen if _create_context was called
                logger.error(
                    f"JOIN for {src_nick} in {joined_channel}, but context not found for user add."
                )
                client.add_message(
                    f"{src_nick} joined {joined_channel} (context not found for user add?)",
                    client.ui.colors["error"],
                    context_name="Status",  # Log to status as error
                )

    elif cmd == "PART":
        # PART format: :nick!user@host PART #channel [:reason]
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
        if client.context_manager.create_context(
            parted_channel, context_type="channel"
        ):  # Ensure context exists, though it should
            logger.debug(f"Ensured channel context exists for PART: {parted_channel}")

        if src_nick_lower == client_nick_lower:  # We parted
            logger.info(f"We parted channel: {parted_channel}{reason}")
            client.add_message(
                f"You left {parted_channel}{reason}",
                client.ui.colors["join_part"],
                context_name=parted_channel,  # Message to the channel we just left
            )
            parted_ctx = client.context_manager.get_context(parted_channel)
            if parted_ctx:
                parted_ctx.users.clear()
                logger.debug(f"Cleared user list for {parted_channel} on our part.")
                # parted_ctx.active_join = False # If such an attribute existed on Context
            if client.context_manager.active_context_name == parted_channel: # Check active context via manager
                client.context_manager.set_active_context("Status") # Switch via manager
                logger.debug(
                    f"Active context was {parted_channel}, switched to Status."
                )
        else:  # Someone else parted
            parted_ctx = client.context_manager.get_context(parted_channel)
            if parted_ctx:
                if src_nick and client.context_manager.remove_user(parted_channel, src_nick):
                    logger.debug(
                        f"Removed {src_nick} from {parted_channel} user list due to PART."
                    )
                elif src_nick: # remove_user returned False, meaning user wasn't there
                    logger.warning(
                        f"{src_nick} PARTed {parted_channel}, but was not in local user list (via context_manager)."
                    )
                client.add_message(
                    f"{src_nick} left {parted_channel}{reason}",
                    client.ui.colors["join_part"],
                    context_name=parted_channel,
                )
            else:  # PART from a channel we aren't tracking? Log to status.
                logger.info(
                    f"Received PART from {src_nick} for untracked channel {parted_channel}{reason}"
                )
                client.add_message(
                    f"{src_nick} left {parted_channel}{reason} (not our current channel)",
                    client.ui.colors[
                        "join_part"
                    ],  # Still join_part color, but to Status
                    context_name="Status",
                )

    elif cmd == "QUIT":
        reason = f" ({trailing})" if trailing else ""
        display_src_nick = (
            src_nick if src_nick else "Someone"
        )  # Should always have src_nick for QUIT

        # Announce quit in all relevant channel contexts
        for ctx_name, ctx_obj in client.context_manager.contexts.items():
            if (
                ctx_obj.type == "channel"
                and src_nick
                and src_nick in ctx_obj.users # Check directly on context object's users set
            ):
                # ctx_obj.users.remove(src_nick) # Or use manager method
                client.context_manager.remove_user(ctx_name, src_nick)
                client.add_message(
                    f"{display_src_nick} quit{reason}",
                    client.ui.colors["join_part"],
                    context_name=ctx_name,
                )
                logger.debug(
                    f"Processed QUIT for {display_src_nick} in context {ctx_name}."
                )

        # If it's our own QUIT, the main loop handles full shutdown.
        # If it's our own QUIT from the server (e.g. killed), this might be the first sign.
        if src_nick_lower == client_nick_lower:
            logger.info(
                f"Received QUIT message for our own nick: {client.nick}{reason}"
            )
            # client.should_quit = True # This might be too aggressive if server initiated the QUIT (e.g. KICK/KILL)
            # The network handler usually sets connected = False on socket close/error.
            client.add_message(
                f"You have quit{reason}",  # Or "Disconnected by server..." if not user-initiated
                client.ui.colors["join_part"],
                context_name="Status",
            )

    elif cmd == "NICK":
        # NICK format: :oldnick!user@host NICK newnick
        new_nick = trailing if trailing else (params[0] if params else None)
        if not new_nick or not src_nick:  # src_nick is the old nickname here
            client.add_message(
                f"[INVALID NICK] Raw: {line}",
                client.ui.colors["error"],
                context_name="Status",
            )
            logger.warning(f"Invalid NICK message: {line.strip()}")
            return

        # Announce nick change in all relevant channel contexts
        nick_change_message = f"{src_nick} is now known as {new_nick}"
        active_context_before_nick_change = client.context_manager.active_context_name
        renamed_query_context_new_name = None

        # Iterate over a copy of keys if removing/renaming contexts inside the loop
        for ctx_name in list(client.context_manager.contexts.keys()):
            ctx_obj = client.context_manager.get_context(ctx_name)
            if not ctx_obj: # Context might have been removed (e.g. renamed query)
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
                    logger.debug(
                        f"Processed NICK change for {src_nick} to {new_nick} in channel context {ctx_name}."
                    )
            elif ctx_obj.type == "query" and ctx_name == f"Query:{src_nick}":
                new_query_ctx_name = f"Query:{new_nick}"
                logger.info(f"Attempting to rename query context from {ctx_name} to {new_query_ctx_name} for NICK change.")

                # Create the new context (or get if exists)
                client.context_manager.create_context(new_query_ctx_name, context_type="query", topic=ctx_obj.topic)
                new_query_ctx_obj = client.context_manager.get_context(new_query_ctx_name)

                if new_query_ctx_obj:
                    # Copy messages from old to new (ensure new deque has correct maxlen)
                    new_query_ctx_obj.messages = deque(list(ctx_obj.messages), maxlen=client.context_manager.max_history)
                    new_query_ctx_obj.users = set(list(ctx_obj.users)) # Copy users if any
                    new_query_ctx_obj.unread_count = ctx_obj.unread_count # Copy unread count

                    was_active = (active_context_before_nick_change == ctx_name)
                    client.context_manager.remove_context(ctx_name) # Remove old context
                    logger.info(f"Successfully renamed query context from {ctx_name} to {new_query_ctx_name}.")

                    if was_active:
                        renamed_query_context_new_name = new_query_ctx_name # Mark to set active later
                else:
                    logger.error(f"Failed to create/get new query context {new_query_ctx_name} during NICK rename. Old context {ctx_name} messaged instead.")
                    # Fallback: Message in the old query window if rename failed
                    client.add_message(
                        nick_change_message,
                        client.ui.colors["nick_change"],
                        context_name=ctx_name,
                    )
                logger.debug(
                    f"Processed NICK change for {src_nick} to {new_nick} involving query context {ctx_name}."
                )

        if renamed_query_context_new_name:
            client.context_manager.set_active_context(renamed_query_context_new_name)
            logger.debug(f"Restored active context to renamed query: {renamed_query_context_new_name}")


        # If it's our own nick changing
        if src_nick_lower == client_nick_lower:
            logger.info(f"Our nick changed from {client.nick} to {new_nick}.")
            client.nick = new_nick
            # Add to status as well for clarity
            client.add_message(
                nick_change_message,  # Uses old src_nick and new_nick
                client.ui.colors["nick_change"],
                context_name="Status",
            )

    elif cmd.isdigit():
        code = int(cmd)
        msg_info_params = params[1:] if len(params) > 1 else []

        if code == 1:
            client.nick = params[0] if params else client.initial_nick
            client.add_message(
                f"Welcome to {client.server}: {trailing if trailing else ''}",
                client.ui.colors["system"],
                context_name="Status",
            )
            # Attempt NickServ identification if password is provided
            if client.nickserv_password:
                client.network.send_raw(
                    f"PRIVMSG NickServ :IDENTIFY {client.nick} {client.nickserv_password}"
                )
                client.add_message(
                    f"Attempting to identify with NickServ for {client.nick}...",
                    client.ui.colors["system"],
                    context_name="Status",
                )
        elif code in [2, 3, 4]:  # RPL_YOURHOST, RPL_CREATED, RPL_MYINFO
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
            # Params: <client> <channel> :No topic is set
            channel_name = params[1] if len(params) > 1 else "channel"
            if client.context_manager.create_context(
                channel_name, context_type="channel"
            ):  # Ensure context exists
                logger.debug(f"Ensured channel context {channel_name} for RPL_NOTOPIC.")
            # Ensure context exists via context_manager before trying to access client.contexts directly
            context = client.context_manager.get_context(channel_name)
            if context:
                context.topic = None # Explicitly set topic to None
            else: # Should not happen if create_context succeeded or context already existed
                logger.error(f"RPL_NOTOPIC: Context {channel_name} not found after create/get attempt.")
            logger.info(f"RPL_NOTOPIC for {channel_name}.")
            client.add_message(
                f"No topic set for {channel_name}.",
                client.ui.colors["system"],
                context_name=channel_name,
            )
        elif code == 332:  # RPL_TOPIC
            # Params: <client> <channel> :<topic>
            channel_name = params[1] if len(params) > 1 else "channel"
            topic_text = trailing if trailing else ""
            if client.context_manager.create_context(
                channel_name, context_type="channel"
            ):  # Ensure context exists
                logger.debug(f"Ensured channel context {channel_name} for RPL_TOPIC.")
            # Update topic via ContextManager method
            if client.context_manager.update_topic(channel_name, topic_text):
                logger.info(
                    f"RPL_TOPIC for {channel_name}: {topic_text[:50]}..."
                ) # Log truncated topic
            else: # Should not happen if create_context succeeded or context already existed
                 logger.error(f"RPL_TOPIC: Failed to update topic for {channel_name} after create/get attempt.")
            client.add_message(
                f"Topic for {channel_name}: {topic_text}",
                client.ui.colors["system"],
                context_name=channel_name,
            )
        elif code == 353:  # RPL_NAMREPLY
            # Params: <client> <symbol> <channel> :<nick list>
            # Symbol can be = (public), * (private), @ (secret)
            channel_in_reply = params[2] if len(params) > 2 else None
            if channel_in_reply and client.context_manager.get_context(channel_in_reply):
                nicks_on_list = trailing.split() if trailing else []
                for nick_entry in nicks_on_list:
                    actual_nick = nick_entry.lstrip(
                        "@+&~%"
                    )  # Remove prefixes like @ for op, + for voice
                    client.context_manager.add_user(channel_in_reply, actual_nick)
                    # logger.debug(f"RPL_NAMREPLY: Added {actual_nick} to {channel_in_reply}") # Can be verbose
            else:
                logger.warning(
                    f"RPL_NAMREPLY for non-existent or unknown context: {channel_in_reply}. Raw: {line.strip()}"
                )
            # No message added to UI for 353 itself, 366 handles summary.
        elif code == 366:  # RPL_ENDOFNAMES
            # Params: <client> <channel> :End of /NAMES list.
            channel_ended = params[1] if len(params) > 1 else "Unknown Channel"
            if client.context_manager.get_context(channel_ended):
                user_count = len(client.context_manager.get_users(channel_ended))
                logger.info(
                    f"RPL_ENDOFNAMES for {channel_ended}. User count: {user_count}"
                )
                client.add_message(
                    f"Users in {channel_ended}: {user_count}",
                    client.ui.colors["system"],
                    context_name=channel_ended,
                )
            else:  # Should not happen if context was created on JOIN
                logger.warning(
                    f"RPL_ENDOFNAMES for {channel_ended}, but context not found."
                )
                client.add_message(
                    f"End of names for {channel_ended} (context not found).",
                    client.ui.colors["error"],
                    context_name="Status",
                )
        elif code == 403:  # ERR_NOSUCHCHANNEL
            # Params: <client> <channel name> :No such channel
            channel_name = params[1] if len(params) > 1 else "channel"
            client.add_message(
                f"Channel {channel_name} does not exist or is invalid.",
                client.ui.colors["error"],
                context_name="Status",  # Or active context if trying to join? For now, Status.
            )
            logger.warning(
                f"ERR_NOSUCHCHANNEL ({code}) for {channel_name}: {line.strip()}"
            )
        elif code == 433:  # ERR_NICKNAMEINUSE
            # Params: <client> <nick> :Nickname is already in use.
            failed_nick = (
                params[1] if len(params) > 1 else client.nick
            )  # Nick that failed
            logger.warning(
                f"ERR_NICKNAMEINUSE ({code}) for {failed_nick}: {line.strip()}"
            )
            client.add_message(
                f"Nickname {failed_nick} is already in use.",
                client.ui.colors["error"],
                context_name="Status",
            )
            # Only auto-retry if it's our *current* nick that failed and it matches initial_nick.
            # This prevents runaway retries if user manually changes to an in-use nick.
            if (
                client.nick
                and client.nick.lower() == failed_nick.lower()
                and client.nick.lower() == client.initial_nick.lower()
            ):
                new_try_nick = f"{client.initial_nick}_"
                logger.info(
                    f"Nickname {failed_nick} (initial) in use, trying {new_try_nick}."
                )
                # Update client.nick immediately so subsequent logic uses the new one
                # client.nick = new_try_nick # This is risky if server NICK fails again.
                # Best to let server confirm NICK change via NICK command from server.
                # For now, just send NICK command.
                client.add_message(
                    f"Trying {new_try_nick} instead.",
                    client.ui.colors["system"],
                    context_name="Status",
                )
                client.network.send_raw(f"NICK {new_try_nick}")
            # If user manually did /NICK badnick, and it fails with 433, they get the error message.
            # client.nick remains what it was before the failed /NICK attempt.
            # Server will send a NICK message if it succeeds.
        elif code in [311, 312, 313, 318, 319]:  # WHOIS replies
            # These are typically multi-line and specific to a WHOIS query.
            # For now, just dump to Status. Could be a dedicated WHOIS context later.
            display_p = " ".join(params[1:])  # Nick is usually params[0]
            display_t = (":" + trailing) if trailing else ""
            client.add_message(
                f"[WHOIS {params[1]}] {display_p} {display_t}".strip(),
                client.ui.colors["system"],
                context_name="Status",
            )
        else:  # Other unhandled numeric replies
            # Params usually start with client's own nick, so skip it for display if present
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
        mode_params_from_trailing = (
            trailing.split() if trailing else []
        )  # Trailing might contain params for modes

        full_mode_string = " ".join(mode_changes_list)
        if mode_params_from_trailing:  # Usually modes like +b nick!user@host
            full_mode_string += " " + " ".join(mode_params_from_trailing)

        display_src = (
            src_nick
            if src_nick
            else (parsed_msg.prefix if parsed_msg.prefix else "SERVER")
        )
        logger.info(
            f"MODE received: By: {display_src}, Target: {mode_target}, Changes: {full_mode_string.strip()}"
        )
        # MODE <target> <modes> [mode params]
        # Target can be a channel or a user.
        # This can be complex. For now, display in relevant context if channel, else Status.
        context_for_mode = "Status"
        if (
            mode_target
            and mode_target.startswith("#")
            and client.context_manager.get_context(mode_target)
        ):
            context_for_mode = mode_target
        elif (
            mode_target and mode_target.lower() == client_nick_lower
        ):  # Mode on self (e.g. +i)
            context_for_mode = (
                "Status"  # User modes usually shown in Status or globally
            )

        client.add_message(
            f"[MODE] By: {display_src}, Target: {mode_target}, Changes: {full_mode_string.strip()}",
            client.ui.colors["system"],
            context_name=context_for_mode,
        )
        # TODO: Parse mode_changes to update user modes (e.g. @o, +v) in channel user lists
        # or client's own user modes. This is non-trivial.
        # Example: +o nick1 -v nick2
        # Need to track ops, voice, etc. per user in channel contexts.

    else:  # Unhandled non-numeric commands
        display_p = " ".join(params)
        display_t = (":" + trailing) if trailing else ""
        display_src = (
            src_nick
            if src_nick
            else (
                parsed_msg.prefix if parsed_msg.prefix else "SERVER"
            )  # Fallback to full prefix if no nick
        )
        logger.warning(
            f"Unhandled command '{cmd.upper()}' from '{display_src}': P='{display_p}' T='{display_t}'. Raw: {line.strip()}"
        )
        # Default to "Status" context for unknown commands
        client.add_message(
            f"[{cmd.upper()}] From: {display_src}, Params: {display_p}, Trailing: {display_t}".strip(),
            client.ui.colors["system"],  # Use system color, could be error color too
            context_name="Status",
        )

    client.ui_needs_update.set()
