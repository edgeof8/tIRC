# irc_protocol.py
import re
import logging
from collections import deque
from typing import Optional # Added Optional
import time
from context_manager import ChannelJoinStatus # Added import
from irc_message import IRCMessage
from irc_numeric_handlers import _handle_numeric_command

logger = logging.getLogger("pyrc.protocol")


class IRCProtocolHandler:
    def _handle_privmsg(self, client, parsed_msg: IRCMessage, raw_line: str):
        nick = parsed_msg.source_nick
        # parsed_msg.prefix should be the full nick!user@host
        source_full_ident = parsed_msg.prefix

        if not nick or not source_full_ident: # Should not happen for valid PRIVMSG
            logger.warning(f"PRIVMSG without valid source: {raw_line.strip()}")
            return

        target = parsed_msg.params[0] if parsed_msg.params else None
        message_body = parsed_msg.trailing if parsed_msg.trailing else ""

        if not target:
            logger.warning(f"PRIVMSG without target: {raw_line.strip()}")
            return

        # Determine context and color
        is_channel_msg = target.startswith(("#", "&", "!", "+"))
        is_private_msg_to_me = not is_channel_msg and target.lower() == client.nick.lower()

        target_context_name = target
        display_nick = f"<{nick}>"
        color = client.ui.colors["other_message"]

        if is_private_msg_to_me:
            target_context_name = nick # Context for PM is the sender's nick
            client.context_manager.create_context(target_context_name, context_type="query")
            display_nick = f"*{nick}*" # Indicate PM
            color = client.ui.colors["pm"]
        elif nick.lower() == client.nick.lower() and is_channel_msg: # My message to a channel
            color = client.ui.colors["my_message"]
            # display_nick = f"<{client.nick}>" # Already handled by nick variable

        # Highlight check
        if client.nick and client.nick.lower() in message_body.lower() and not (nick.lower() == client.nick.lower()):
            color = client.ui.colors["highlight"]
            # Potentially add a notification sound/visual cue here in the future

        formatted_msg = f"{display_nick} {message_body}"

        client.add_message(
            formatted_msg,
            color,
            context_name=target_context_name,
            source_full_ident=source_full_ident, # Pass the full ident
            is_privmsg_or_notice=True           # Mark as a user message
        )
        # ... (trigger processing for TEXT event)
        client.process_trigger_event("TEXT", {
            "nick": nick, "userhost": source_full_ident, "target": target, "channel": target if is_channel_msg else "",
            "message": message_body, "message_words": message_body.split(), "client_nick": client.nick,
            "raw_line": raw_line, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        })

    def _handle_notice(self, client, parsed_msg: IRCMessage, raw_line: str):
        nick = parsed_msg.source_nick # Could be server name or user nick
        source_full_ident = parsed_msg.prefix # nick!user@host or servername

        target = parsed_msg.params[0] if parsed_msg.params else None
        message_body = parsed_msg.trailing if parsed_msg.trailing else ""

        if not target:
            logger.warning(f"NOTICE without target: {raw_line.strip()}")
            return

        is_channel_notice = target.startswith(("#", "&", "!", "+"))
        display_source = nick if nick else (source_full_ident if source_full_ident and '!' not in source_full_ident else "Server")

        notice_prefix = f"-{display_source}-"
        target_context_name = "Status" # Default for notices unless they are to a channel/me

        if is_channel_notice:
            target_context_name = target
        elif target.lower() == (client.nick.lower() if client.nick else ""): # Notice to me
            if nick and source_full_ident and '!' in source_full_ident: # If from a user
                target_context_name = nick
                client.context_manager.create_context(target_context_name, context_type="query")
            else: # Notice from server to me, keep in Status
                target_context_name = "Status"

        formatted_msg = f"{notice_prefix} {message_body}"

        client.add_message(
            formatted_msg,
            client.ui.colors["system"], # Or a dedicated notice color
            context_name=target_context_name,
            source_full_ident=source_full_ident,
            is_privmsg_or_notice=True # Mark as a message type that can be ignored
        )
        client.process_trigger_event("NOTICE", {
            "nick": nick if nick else "", "userhost": source_full_ident if source_full_ident else "", "target": target,
            "channel": target if is_channel_notice else "", "message": message_body, "message_words": message_body.split(),
            "client_nick": client.nick, "raw_line": raw_line, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        })

protocol_handler_instance = IRCProtocolHandler()


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

    # Ensure client has cap_negotiator attribute
    if not hasattr(client, 'cap_negotiator') or not client.cap_negotiator:
        logger.error("CAP message received, but client.cap_negotiator is not initialized.")
        client.add_message(f"[CAP Error] Negotiator not ready for {cap_subcommand}", client.ui.colors["error"], "Status")
        return

    if cap_subcommand == "LS":
        client.cap_negotiator.on_cap_ls_received(capabilities_str)
    elif cap_subcommand == "ACK":
        client.cap_negotiator.on_cap_ack_received(capabilities_str)
    elif cap_subcommand == "NAK":
        client.cap_negotiator.on_cap_nak_received(capabilities_str)
    elif cap_subcommand == "NEW":
        client.cap_negotiator.on_cap_new_received(capabilities_str)
        # Messages are now handled within CapNegotiator
    elif cap_subcommand == "DEL":
        client.cap_negotiator.on_cap_del_received(capabilities_str)
        # Messages are now handled within CapNegotiator
    else:
        client.add_message(
            f"[CAP] Unknown subcommand: {cap_subcommand} {capabilities_str}",
            client.ui.colors["system"],
            context_name="Status",
        )

# Removed old _handle_privmsg function

def _handle_nick_change(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles NICK messages."""
    src_nick = parsed_msg.source_nick # This is the *old* nick
    params = parsed_msg.params
    trailing = parsed_msg.trailing

    # The new nick is in the trailing part or the first parameter if no trailing.
    new_nick = trailing if trailing else (params[0] if params else None)

    if not new_nick or not src_nick:
        client.add_message(
            f"[INVALID NICK] Raw: {raw_line.strip()}",
            client.ui.colors["error"],
            context_name="Status",
        )
        logger.warning(f"Invalid NICK message (missing new_nick or src_nick): {raw_line.strip()}")
        return

    nick_change_message = f"{src_nick} is now known as {new_nick}"
    active_context_before_nick_change = client.context_manager.active_context_name
    renamed_query_context_new_name = None # If active query window is renamed

    # Iterate over a copy of keys if modifying the dictionary (contexts)
    for ctx_name in list(client.context_manager.contexts.keys()):
        ctx_obj = client.context_manager.get_context(ctx_name)
        if not ctx_obj: continue

        if ctx_obj.type == "channel":
            if src_nick in ctx_obj.users: # Check if old nick was in this channel's user list
                # Update user list: remove old, add new (preserving prefix if possible, though NICK doesn't carry prefix)
                prefix = ctx_obj.users.get(src_nick, "") # Get old prefix
                client.context_manager.remove_user(ctx_name, src_nick)
                client.context_manager.add_user(ctx_name, new_nick, prefix) # Add new nick with old prefix
                client.add_message(
                    nick_change_message,
                    client.ui.colors["nick_change"],
                    context_name=ctx_name,
                )
        elif ctx_obj.type == "query" and ctx_name == f"Query:{src_nick}":
            # Rename the query context
            new_query_ctx_name = f"Query:{new_nick}"
            logger.info(f"Renaming query context from {ctx_name} to {new_query_ctx_name} for NICK change.")

            # Create new context, copy messages, users, topic, scroll etc.
            if client.context_manager.create_context(new_query_ctx_name, context_type="query", topic=ctx_obj.topic):
                new_query_ctx_obj = client.context_manager.get_context(new_query_ctx_name)
                if new_query_ctx_obj:
                    # Copy messages
                    new_query_ctx_obj.messages = deque(list(ctx_obj.messages), maxlen=client.context_manager.max_history)
                    # Copy users (though query windows usually just have the target user implicitly)
                    new_query_ctx_obj.users = ctx_obj.users.copy() # Should be empty or just the target
                    new_query_ctx_obj.unread_count = ctx_obj.unread_count
                    new_query_ctx_obj.scrollback_offset = ctx_obj.scrollback_offset
                    new_query_ctx_obj.user_list_scroll_offset = ctx_obj.user_list_scroll_offset # Though not used for query

                    was_active = (active_context_before_nick_change == ctx_name)
                    client.context_manager.remove_context(ctx_name) # Remove old query context
                    logger.info(f"Successfully renamed query context from {ctx_name} to {new_query_ctx_name}.")
                    if was_active:
                        renamed_query_context_new_name = new_query_ctx_name # Flag to set new one active
                else: # Should not happen if create_context returned True
                    logger.error(f"Failed to get new query context {new_query_ctx_name} after creation during NICK rename.")
                    client.add_message(nick_change_message, client.ui.colors["nick_change"], context_name=ctx_name) # Message in old context
            else: # Failed to create new context (e.g., name collision, though unlikely for Query:NewNick)
                 logger.error(f"Failed to create new query context {new_query_ctx_name} during NICK rename.")
                 client.add_message(nick_change_message, client.ui.colors["nick_change"], context_name=ctx_name) # Message in old context


    if renamed_query_context_new_name: # If the active query window was renamed
        client.context_manager.set_active_context(renamed_query_context_new_name)

    # If it's our own nick changing
    if src_nick.lower() == (client.nick.lower() if client.nick else ""):
        logger.info(f"Our nick changed from {client.nick} to {new_nick}.")
        old_nick_for_tracking = client.nick # Store our old nick
        client.nick = new_nick # Update our main nick variable

        # Update our nick in all channel user lists where we were present
        for ch_name_iter in client.currently_joined_channels: # Iterate over channels we think we are in
            ch_ctx = client.context_manager.get_context(ch_name_iter)
            if ch_ctx and old_nick_for_tracking in ch_ctx.users:
                prefix = ch_ctx.users.get(old_nick_for_tracking, "")
                client.context_manager.remove_user(ch_name_iter, old_nick_for_tracking)
                client.context_manager.add_user(ch_name_iter, new_nick, prefix)

        client.add_message(
            nick_change_message, # "You are now known as NewNick" or similar can be added in add_message or here
            client.ui.colors["nick_change"],
            context_name="Status", # Own nick changes often go to Status
        )
        # Also display in active context if it's a channel/query where the change is relevant
        if client.context_manager.active_context_name and client.context_manager.active_context_name != "Status":
             client.add_message(nick_change_message, client.ui.colors["nick_change"], context_name=client.context_manager.active_context_name)


# --- Individual Membership Event Handlers ---
def _handle_join_event(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles JOIN messages."""
    src_nick = parsed_msg.source_nick
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    client_nick_lower = client.nick.lower() if client.nick else ""
    src_nick_lower = src_nick.lower() if src_nick else ""

    joined_channel_raw = trailing.lstrip(":") if trailing else (params[0] if params else None)

    if not joined_channel_raw:
        client.add_message(f"[INVALID JOIN] Missing channel. Raw: {raw_line.strip()}", client.ui.colors["error"], context_name="Status")
        logger.warning(f"Invalid JOIN message (no channel): {raw_line.strip()}")
        return

    joined_channel = joined_channel_raw.split(",")[0]

    created_now = client.context_manager.create_context(
        joined_channel,
        context_type="channel",
        initial_join_status_for_channel=ChannelJoinStatus.JOIN_COMMAND_SENT
    )
    if created_now:
        logger.debug(f"Ensured channel context exists for JOIN: {joined_channel} (created with JOIN_COMMAND_SENT)")

    joined_ctx = client.context_manager.get_context(joined_channel)

    if src_nick_lower == client_nick_lower:
        logger.info(f"Self JOIN received for channel: {joined_channel}")
        if joined_ctx:
            joined_ctx.join_status = ChannelJoinStatus.SELF_JOIN_RECEIVED
            joined_ctx.users.clear()
            logger.debug(f"Set join_status to SELF_JOIN_RECEIVED for {joined_channel}")
        else:
            logger.error(f"Context for {joined_channel} not found after self-JOIN.")

        client.network.send_raw(f"NAMES {joined_channel}")
        client.network.send_raw(f"MODE {joined_channel}")
        client.add_message(f"Joining {joined_channel}...", client.ui.colors["join_part"], context_name=joined_channel)
    else:
        if joined_ctx:
            client.context_manager.add_user(joined_channel, src_nick)
            client.add_message(f"{src_nick} joined {joined_channel}", client.ui.colors["join_part"], context_name=joined_channel)
        else:
            logger.debug(f"Received other-JOIN for {joined_channel} by {src_nick}, but no local context exists.")


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
        client.add_message(f"[INVALID PART] {raw_line.strip()}", client.ui.colors["error"], "Status")
        return

    # part_ctx_exists = client.context_manager.get_context(parted_channel) # Not strictly needed before logic

    if src_nick_lower == client_nick_lower:
        logger.info(f"We parted channel: {parted_channel}{reason_message}")

        parted_ctx_obj = client.context_manager.get_context(parted_channel)
        if parted_ctx_obj:
            parted_ctx_obj.join_status = ChannelJoinStatus.NOT_JOINED
            parted_ctx_obj.users.clear()
            logger.debug(f"Set join_status to NOT_JOINED for parted channel {parted_channel}")

        client.currently_joined_channels.discard(parted_channel)
        client.add_message(f"You left {parted_channel}{reason_message}", client.ui.colors["join_part"], context_name=parted_channel)

        if client.context_manager.active_context_name == client.context_manager._normalize_context_name(parted_channel):
            other_joined_channels = sorted(list(client.currently_joined_channels), key=str.lower)
            if other_joined_channels: client.switch_active_context(other_joined_channels[0])
            elif "Status" in client.context_manager.get_all_context_names(): client.switch_active_context("Status")
            else:
                all_ctx_names = client.context_manager.get_all_context_names()
                if all_ctx_names: client.switch_active_context(all_ctx_names[0])

        if client.context_manager.remove_context(parted_channel):
            logger.info(f"Successfully removed context for parted channel: {parted_channel}")
        else:
            logger.warning(f"Failed to remove context for parted channel: {parted_channel}")
    else:
        parted_ctx = client.context_manager.get_context(parted_channel)
        if parted_ctx:
            if src_nick and client.context_manager.remove_user(parted_channel, src_nick):
                logger.debug(f"Removed {src_nick} from {parted_channel} user list due to PART.")
            client.add_message(f"{src_nick} left {parted_channel}{reason_message}", client.ui.colors["join_part"], context_name=parted_channel)


def _handle_quit_event(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles QUIT messages."""
    src_nick = parsed_msg.source_nick
    trailing = parsed_msg.trailing
    client_nick_lower = client.nick.lower() if client.nick else ""
    src_nick_lower = src_nick.lower() if src_nick else ""

    quit_reason = f" ({trailing.lstrip(':')})" if trailing else ""
    display_src_nick = src_nick if src_nick else "Someone"

    if src_nick_lower == client_nick_lower:
        logger.info(f"Received QUIT message for our own nick: {client.nick}{quit_reason}. Client is likely shutting down or changing servers.")
        return

    logger.info(f"User {display_src_nick} quit from the server{quit_reason}.")
    for ctx_name, ctx_obj in client.context_manager.contexts.items():
        if ctx_obj.type == "channel" and src_nick and src_nick in ctx_obj.users:
            client.context_manager.remove_user(ctx_name, src_nick)
            client.add_message(f"{display_src_nick} quit{quit_reason}", client.ui.colors["join_part"], context_name=ctx_name)


def _handle_kick_event(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles KICK messages."""
    src_nick = parsed_msg.source_nick
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    client_nick_lower = client.nick.lower() if client.nick else ""
    # src_nick_lower is not directly used here but kept for consistency if needed later

    channel_kicked_from = params[0] if len(params) > 0 else None
    user_kicked = params[1] if len(params) > 1 else None
    reason = f" ({trailing.lstrip(':')})" if trailing else ""

    if not channel_kicked_from or not user_kicked:
        logger.warning(f"Invalid KICK message: {raw_line.strip()}")
        return

    kick_message = f"{user_kicked} was kicked from {channel_kicked_from} by {src_nick}{reason}"

    if client.context_manager.create_context(channel_kicked_from, context_type="channel"):
        logger.debug(f"Ensured channel context exists for KICK: {channel_kicked_from}")

    client.add_message(kick_message, client.ui.colors["join_part"], context_name=channel_kicked_from)

    kicked_ctx = client.context_manager.get_context(channel_kicked_from)
    if kicked_ctx:
        client.context_manager.remove_user(channel_kicked_from, user_kicked)

    if user_kicked.lower() == client_nick_lower:
        logger.info(f"We were kicked from {channel_kicked_from} by {src_nick}{reason}")
        client.currently_joined_channels.discard(channel_kicked_from)
        if kicked_ctx:
            kicked_ctx.join_status = ChannelJoinStatus.NOT_JOINED
            kicked_ctx.users.clear()
            logger.debug(f"Set join_status to NOT_JOINED for kicked channel {channel_kicked_from}")

        if client.context_manager.active_context_name == client.context_manager._normalize_context_name(channel_kicked_from):
            other_joined_channels = sorted(list(client.currently_joined_channels), key=str.lower)
            if other_joined_channels: client.switch_active_context(other_joined_channels[0])
            elif "Status" in client.context_manager.get_all_context_names(): client.switch_active_context("Status")
            else:
                all_ctx_names = client.context_manager.get_all_context_names()
                if all_ctx_names: client.switch_active_context(all_ctx_names[0])

def _handle_membership_changes(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles JOIN, PART, QUIT, KICK messages."""
    cmd = parsed_msg.command
    # Common variables like src_nick, params, etc. are now handled within each specific event handler.

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
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    src_nick = parsed_msg.source_nick

    mode_target = params[0] if params else None
    if not mode_target:
        logger.warning(f"Malformed MODE message (no target): {raw_line.strip()}")
        return

    mode_changes_str = " ".join(params[1:])
    if trailing: mode_changes_str += f" :{trailing}"

    display_src = src_nick if src_nick else (parsed_msg.prefix if parsed_msg.prefix else "SERVER")
    logger.info(f"MODE received: By: {display_src}, Target: {mode_target}, Changes: {mode_changes_str.strip()}")

    context_for_mode_message = "Status"
    target_is_channel = mode_target.startswith(("#", "&", "+", "!"))

    if target_is_channel:
        if client.context_manager.create_context(mode_target, context_type="channel"):
            logger.debug(f"Ensured channel context exists for MODE: {mode_target}")
        context_for_mode_message = mode_target
    elif mode_target and client.nick and mode_target.lower() == client.nick.lower():
        context_for_mode_message = "Status"

    client.add_message(
        f"[MODE {mode_target}] by {display_src}: {mode_changes_str.strip()}",
        client.ui.colors["system"],
        context_name=context_for_mode_message,
    )

    if target_is_channel and len(params) > 1:
        actual_mode_str = params[1]
        mode_args = params[2:]

        current_op = None
        arg_idx = 0

        for char_mode in actual_mode_str:
            if char_mode == '+':
                current_op = '+'
            elif char_mode == '-':
                current_op = '-'
            elif current_op:
                user_affecting_modes = {'o': '@', 'v': '+', 'h': '%'}

                if char_mode in user_affecting_modes:
                    if arg_idx < len(mode_args):
                        nick_affected = mode_args[arg_idx]
                        new_prefix_for_user = ""

                        current_user_prefix_obj = client.context_manager.get_context(mode_target)
                        current_actual_prefix = ""
                        if current_user_prefix_obj:
                             current_actual_prefix = current_user_prefix_obj.users.get(nick_affected, "")

                        if current_op == '+':
                            new_prefix_candidate = user_affecting_modes[char_mode]
                            if new_prefix_candidate == '+' and current_actual_prefix in ['@', '%']:
                                new_prefix_for_user = current_actual_prefix
                            else:
                                new_prefix_for_user = new_prefix_candidate
                        elif current_op == '-':
                            if current_actual_prefix == user_affecting_modes[char_mode]:
                                new_prefix_for_user = ""
                            else:
                                new_prefix_for_user = current_actual_prefix

                        client.context_manager.update_user_prefix(mode_target, nick_affected, new_prefix_for_user)
                        logger.info(f"MODE {current_op}{char_mode} for {nick_affected} in {mode_target}. New prefix: '{new_prefix_for_user}' (Old: '{current_actual_prefix}')")
                        arg_idx += 1
                    else:
                        logger.warning(f"MODE: Not enough arguments for mode {current_op}{char_mode} in {mode_target}. Args: {mode_args}")
                elif char_mode in ['k', 'l', 'b', 'e', 'I']:
                    if arg_idx < len(mode_args):
                         arg_idx +=1


def handle_server_message(client, line: str): # raw_line is 'line' here
    """
    Processes a raw message line from the IRC server and calls
    appropriate methods on the client object to update state or UI.
    """
    parsed_msg = IRCMessage.parse(line)

    if not parsed_msg:
        logger.error(f"Failed to parse IRC message: {line.strip()}")
        client.add_message(f"[UNPARSED] {line.strip()}", client.ui.colors["error"], context_name="Status")
        return

    cmd = parsed_msg.command

    if hasattr(client, 'trigger_manager') and client.trigger_manager:
        raw_data = {
            "event_type": "RAW", "raw_line": line, "timestamp": time.time(),
            "client_nick": client.nick, "prefix": parsed_msg.prefix,
            "command": parsed_msg.command, "params_list": parsed_msg.params,
            "trailing": parsed_msg.trailing,
            "numeric": int(parsed_msg.command) if parsed_msg.command.isdigit() else None,
        }
        action_to_take = client.process_trigger_event("RAW", raw_data)
        if action_to_take:
            client.command_handler.process_user_command(action_to_take)

    if cmd == "CAP":
        _handle_cap_message(client, parsed_msg, line)
    elif cmd == "PING":
        ping_param = parsed_msg.trailing if parsed_msg.trailing else (parsed_msg.params[0] if parsed_msg.params else "")
        client.network.send_raw(f"PONG :{ping_param}")
        logger.debug(f"Responded to PING with PONG {ping_param}")
    elif cmd == "AUTHENTICATE":
        payload = parsed_msg.params[0] if parsed_msg.params else ""
        if not hasattr(client, 'sasl_authenticator') or not client.sasl_authenticator:
            logger.error("AUTHENTICATE received, but client.sasl_authenticator is not initialized.")
            client.add_message(f"[SASL Error] Authenticator not ready for AUTHENTICATE {payload}", client.ui.colors["error"], "Status")
            return

        if payload == "+":
            logger.info(f"SASL: Received AUTHENTICATE + challenge. Raw: {line.strip()}")
            client.sasl_authenticator.on_authenticate_challenge_received(payload)
        else:
            # According to RFC 4616, any other payload for AUTHENTICATE after initial PLAIN is an error or unexpected.
            # It could be the server sending an empty AUTHENTICATE on failure, or something else.
            # The SASL numerics (903, 904, etc.) are the primary way to signal success/failure after payload.
            logger.warning(f"SASL: Received AUTHENTICATE with payload other than '+': '{payload}'. This is unusual. Relying on numerics for outcome. Raw: {line.strip()}")
            # client.sasl_authenticator.handle_sasl_failure(f"Unexpected AUTHENTICATE payload: {payload}") # Or just log and wait for numeric
    elif cmd == "PRIVMSG":
        protocol_handler_instance._handle_privmsg(client, parsed_msg, line)
    elif cmd in ["JOIN", "PART", "QUIT", "KICK"]:
        _handle_membership_changes(client, parsed_msg, line)
    elif cmd == "NICK":
        _handle_nick_change(client, parsed_msg, line)
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

            client.context_manager.update_topic(channel, new_topic if new_topic is not None else "")
            client.add_message(message, client.ui.colors["system"], context_name=channel)
        else:
            logger.warning(f"Malformed TOPIC message (no channel): {line.strip()}") # Use 'line' here
    elif cmd == "NOTICE":
        protocol_handler_instance._handle_notice(client, parsed_msg, line)
    else:
        display_p_parts = list(parsed_msg.params)
        if parsed_msg.trailing is not None: display_p_parts.append(f":{parsed_msg.trailing}")
        display_p = " ".join(display_p_parts)

        display_src = parsed_msg.source_nick if parsed_msg.source_nick else (parsed_msg.prefix if parsed_msg.prefix else "SERVER")

        logger.warning(f"Unhandled command '{cmd.upper()}' from '{display_src}': {display_p}. Raw: {line.strip()}")
        client.add_message(
            f"[{cmd.upper()}] From: {display_src}, Data: {display_p}".strip(),
            client.ui.colors["system"],
            context_name="Status",
        )

    client.ui_needs_update.set()
