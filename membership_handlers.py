import logging
from typing import TYPE_CHECKING, Optional

from context_manager import ChannelJoinStatus # Used by these handlers

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic
    from irc_message import IRCMessage

logger = logging.getLogger("pyrc.handlers.membership")

def handle_join_event(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
    """Handles JOIN messages."""
    src_nick = parsed_msg.source_nick
    params = parsed_msg.params
    client_nick_lower = client.nick.lower() if client.nick else ""
    src_nick_lower = src_nick.lower() if src_nick else ""

    joined_channel = params[0] if params else None

    if not joined_channel:
        logger.warning(f"JOIN command received with no channel: {raw_line.strip()}")
        client.add_message(
            f"[INVALID JOIN] {raw_line.strip()}", client.ui.colors["error"], context_name="Status"
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
    if hasattr(client, "event_manager") and client.event_manager:
        # Extract extended join info if available from tags
        account_name = parsed_msg.get_tag('account')
        real_name = parsed_msg.trailing.split(':', 1)[-1] if parsed_msg.trailing and ':' in parsed_msg.trailing else src_nick # Simplistic realname from JOIN, better from WHOIS if needed
        userhost = parsed_msg.prefix # Should be nick!user@host

        client.event_manager.dispatch_join(
            nick=src_nick, userhost=userhost, channel=joined_channel,
            account=account_name, real_name=real_name, # Pass new fields
            is_self=(src_nick_lower == client_nick_lower), raw_line=raw_line
        )

def handle_part_event(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
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
            f"[INVALID PART] {raw_line.strip()}", client.ui.colors["error"], context_name="Status"
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
    if hasattr(client, "event_manager") and client.event_manager:
        client.event_manager.dispatch_part(
            nick=src_nick, userhost=parsed_msg.prefix, channel=parted_channel, # Use parsed_msg.prefix for userhost
            reason=(parsed_msg.trailing.lstrip(":") if parsed_msg.trailing else ""),
            is_self=(src_nick_lower == client_nick_lower), raw_line=raw_line
        )

def handle_quit_event(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
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
    if hasattr(client, "event_manager") and client.event_manager:
        client.event_manager.dispatch_quit(
            nick=src_nick, userhost=parsed_msg.prefix, # Use parsed_msg.prefix for userhost
            reason=(parsed_msg.trailing.lstrip(":") if parsed_msg.trailing else ""),
            raw_line=raw_line
        )

def handle_kick_event(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
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

def handle_membership_changes(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
    """Handles JOIN, PART, QUIT, KICK messages."""
    cmd = parsed_msg.command

    if cmd == "JOIN":
        handle_join_event(client, parsed_msg, raw_line)
    elif cmd == "PART":
        handle_part_event(client, parsed_msg, raw_line)
    elif cmd == "QUIT":
        handle_quit_event(client, parsed_msg, raw_line)
    elif cmd == "KICK":
        handle_kick_event(client, parsed_msg, raw_line)
