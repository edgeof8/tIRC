import logging
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic
    from irc_message import IRCMessage
    # from context_manager import ChannelJoinStatus # Not directly used by these two

logger = logging.getLogger("pyrc.handlers.message")

def handle_privmsg(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
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
    display_nick = f"<{nick}>" # Markdown escape for < and >
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
    if hasattr(client, "event_manager") and client.event_manager:
        client.event_manager.dispatch_privmsg(
            nick=nick, userhost=source_full_ident, target=target,
            message=message_body, is_channel_msg=is_channel_msg,
            tags=parsed_msg.get_all_tags(), raw_line=raw_line
        )

def handle_notice(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
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
    if hasattr(client, "event_manager") and client.event_manager:
        client.event_manager.dispatch_notice(
            nick=nick, userhost=source_full_ident, target=target,
            message=message_body, is_channel_notice=is_channel_notice,
            tags=parsed_msg.get_all_tags(), raw_line=raw_line
        )
