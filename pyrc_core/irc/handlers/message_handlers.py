import logging
import time
from typing import TYPE_CHECKING, Optional, Awaitable

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    from pyrc_core.irc.irc_message import IRCMessage

logger = logging.getLogger("pyrc.handlers.message")

async def handle_privmsg(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str) -> Optional[str]:
    nick = parsed_msg.source_nick
    source_full_ident = parsed_msg.prefix

    logger.debug(f"HANDLE_PRIVMSG: Raw='{raw_line.strip()}', Parsed Nick='{parsed_msg.source_nick}', Target='{parsed_msg.params[0] if parsed_msg.params else None}', Body='{parsed_msg.trailing}'")

    if not nick or not source_full_ident:
        logger.warning(f"PRIVMSG without valid source: {raw_line.strip()}")
        return None

    target = parsed_msg.params[0] if parsed_msg.params else None
    message_body = parsed_msg.trailing if parsed_msg.trailing else ""

    if not target:
        logger.warning(f"PRIVMSG without target: {raw_line.strip()}")
        return None

    conn_info = client.state_manager.get_connection_info()
    client_nick = conn_info.nick if conn_info else ""

    is_channel_msg = target.startswith(("#", "&", "!", "+"))
    is_private_msg_to_me = (
        not is_channel_msg and target.lower() == client_nick.lower()
    )

    target_context_name = target
    display_nick = f"<{nick}>"
    color_key = "other_message"

    if is_private_msg_to_me:
        target_context_name = nick
        client.context_manager.create_context( # Not an awaitable function
            target_context_name, context_type="query"
        )
        display_nick = f"*{nick}*"
        color_key = "pm"
    elif client_nick and nick.lower() == client_nick.lower() and is_channel_msg:
        color_key = "my_message"
        logger.debug(f"HANDLE_PRIVMSG: Echoed self-message to channel. Nick: {nick}, Target: {target_context_name}, Color: {color_key}, Message: '{message_body[:50]}...'")

    if (
        client_nick
        and client_nick.lower() in message_body.lower()
        and not (client_nick and nick.lower() == client_nick.lower())
    ):
        color_key = "highlight"

    formatted_msg = f"{display_nick} {message_body}"

    logger.debug(f"HANDLE_PRIVMSG: Adding to context '{target_context_name}': '{formatted_msg}' with color_key '{color_key}'")
    await client.add_message(
        formatted_msg,
        client.ui.colors[color_key],
        context_name=target_context_name,
        source_full_ident=source_full_ident,
        is_privmsg_or_notice=True,
    )

    action_from_text_trigger = None
    if client and hasattr(client, "process_trigger_event") and client.process_trigger_event:
        task: Optional[Awaitable[str]] = client.process_trigger_event(
            "TEXT",
            {
                "nick": nick, "userhost": source_full_ident, "target": target,
                "channel": target if is_channel_msg else "", "message": message_body,
                 "message_words": message_body.split(),
                "client_nick": client_nick,
                "raw_line": raw_line,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "tags": parsed_msg.get_all_tags(),
            }
        )
        if task is not None:
            action_from_text_trigger = await task
        else:
            action_from_text_trigger = None

    if hasattr(client, "event_manager") and client.event_manager:
        await client.event_manager.dispatch_privmsg(
            nick=nick, userhost=source_full_ident, target=target,
            message=message_body, is_channel_msg=is_channel_msg,
            tags=parsed_msg.get_all_tags(), raw_line=raw_line
        )

    return action_from_text_trigger


async def handle_notice(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str) -> Optional[str]:
    if client is None:
        logger.warning("handle_notice: Client is None. Skipping message processing.")
        return None

    nick = parsed_msg.source_nick
    source_full_ident = parsed_msg.prefix
    logger.debug(f"HANDLE_NOTICE: Raw='{raw_line.strip()}', Parsed Nick='{parsed_msg.source_nick}', Target='{parsed_msg.params[0] if parsed_msg.params else None}', Body='{parsed_msg.trailing}'")

    target = parsed_msg.params[0] if parsed_msg.params else None
    message_body = parsed_msg.trailing if parsed_msg.trailing else ""

    if not target:
        logger.warning(f"NOTICE without target: {raw_line.strip()}")
        return None

    conn_info = client.state_manager.get_connection_info()
    client_nick = conn_info.nick if conn_info else ""

    is_channel_notice = target.startswith(("#", "&", "!", "+"))
    display_source = nick if nick else (source_full_ident if source_full_ident and "!" not in source_full_ident else "Server")
    notice_prefix = f"-{display_source}-"
    target_context_name = "Status"

    if is_channel_notice:
        target_context_name = target
    elif target.lower() == client_nick.lower():
        if nick and source_full_ident and "!" in source_full_ident:
            target_context_name = nick
            client.context_manager.create_context(target_context_name, context_type="query") # Not an awaitable function

    formatted_msg = f"{notice_prefix} {message_body}"

    logger.debug(f"HANDLE_NOTICE: Adding to context '{target_context_name}': '{formatted_msg}'")
    await client.add_message(
        formatted_msg, client.ui.colors["system"], context_name=target_context_name,
        source_full_ident=source_full_ident, is_privmsg_or_notice=True,
    )

    action_from_notice_trigger = None
    if client:
        task: Optional[Awaitable[str]] = client.process_trigger_event(
            "NOTICE",
            {
                "nick": nick, "userhost": source_full_ident, "target": target,
                "channel": target if is_channel_notice else "", "message": message_body,
                 "message_words": message_body.split(),
                "client_nick": client_nick,
                "raw_line": raw_line,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "tags": parsed_msg.get_all_tags(),
            }
        )
        if task is not None:
            action_from_notice_trigger = await task
        else:
            action_from_notice_trigger = None

    if hasattr(client, "event_manager") and client.event_manager:
        await client.event_manager.dispatch_notice(
            nick=nick, userhost=source_full_ident, target=target,
            message=message_body, is_channel_notice=is_channel_notice,
            tags=parsed_msg.get_all_tags(), raw_line=raw_line
        )

    return action_from_notice_trigger
