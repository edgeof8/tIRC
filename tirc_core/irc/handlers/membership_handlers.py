# tirc_core/irc/handlers/membership_handlers.py
import logging
from typing import TYPE_CHECKING, Optional, Dict, Any

from tirc_core.context_manager import ChannelJoinStatus
from tirc_core.features.triggers.trigger_manager import ActionType

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.irc.irc_message import IRCMessage

logger = logging.getLogger("tirc.handlers.membership")

async def _handle_join(client: "IRCClient_Logic", msg: "IRCMessage", raw_line: str, params: list, trailing: Optional[str]):
    """Handles JOIN messages from the server."""
    channel_name = trailing or (params[0] if params else None)
    if not channel_name:
        logger.warning(f"JOIN message without channel: {raw_line.strip()}")
        return

    source_nick = msg.source_nick
    source_full_ident = msg.prefix
    is_self_join = source_nick.lower() == client.nick.lower() if client.nick else False

    account_name = msg.get_tag("account")
    real_name = trailing if len(params) > 1 and params[0] == "*" else None

    normalized_channel_name = client.context_manager._normalize_context_name(channel_name)
    context_obj = client.context_manager.get_context(normalized_channel_name)
    if not context_obj:
        client.context_manager.create_context(normalized_channel_name, context_type="channel", initial_join_status_for_channel=ChannelJoinStatus.SELF_JOIN_RECEIVED if is_self_join else ChannelJoinStatus.NOT_JOINED)
        context_obj = client.context_manager.get_context(normalized_channel_name)

    if context_obj and context_obj.type == "channel":
        if source_nick: client.context_manager.add_user(normalized_channel_name, source_nick)
        if is_self_join:
            context_obj.update_join_status(ChannelJoinStatus.SELF_JOIN_RECEIVED)
            logger.info(f"Successfully joined channel: {normalized_channel_name}")
            await client.add_message(f"You have joined {normalized_channel_name}", client.ui.colors.get("self_join_part",0), normalized_channel_name)
            if client.last_join_command_target and client.context_manager._normalize_context_name(client.last_join_command_target) == normalized_channel_name:
                await client.view_manager.switch_active_context(normalized_channel_name)
                client.last_join_command_target = None
        else:
            await client.add_message(f"{source_nick} ({source_full_ident}) has joined {normalized_channel_name}", client.ui.colors.get("join_part",0), normalized_channel_name)

    await client.event_manager.dispatch_join(
        nick=source_nick,
        userhost=source_full_ident,
        channel=normalized_channel_name,
        account=account_name,
        real_name=real_name,
        is_self=is_self_join,
        raw_line=raw_line
    )

    if client.trigger_manager:
        trigger_action = client.trigger_manager.process_trigger(
            "JOIN",
            {"nick": source_nick, "userhost": source_full_ident, "channel": normalized_channel_name, "account": account_name, "real_name": real_name, "is_self": is_self_join, "raw_line": raw_line, "source_nick": source_nick}
        )
        if trigger_action:
            if trigger_action["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(trigger_action["content"])
            elif trigger_action["type"] == ActionType.PYTHON and trigger_action.get("code"):
                await client.execute_python_trigger_code(trigger_action["code"], trigger_action["event_data"])
            elif trigger_action["type"] == ActionType.PYTHON:
                logger.warning(f"Python trigger action for JOIN has no code: {trigger_action}")


async def _handle_part(client: "IRCClient_Logic", msg: "IRCMessage", raw_line: str, params: list, trailing: Optional[str]):
    channel_name = params[0] if params else None
    part_message = trailing

    if not channel_name:
        logger.warning(f"PART message without channel: {raw_line.strip()}")
        return

    source_nick = msg.source_nick
    source_full_ident = msg.prefix
    is_self_part = source_nick.lower() == client.nick.lower() if client.nick else False
    normalized_channel_name = client.context_manager._normalize_context_name(channel_name)

    if is_self_part:
        await client.add_message(f"You have left {normalized_channel_name} ({part_message or ''})", client.ui.colors.get("self_join_part",0), normalized_channel_name)
        if client.context_manager.active_context_name == normalized_channel_name:
            next_context_to_switch = "Status"
            all_contexts = client.context_manager.get_all_context_names()
            if "Status" not in all_contexts and len(all_contexts) > 1:
                other_channels = [name for name in all_contexts if name != normalized_channel_name]
                if other_channels: next_context_to_switch = other_channels[0]

            client.context_manager.remove_context(normalized_channel_name)
            await client.view_manager.switch_active_context(next_context_to_switch)
        else:
            client.context_manager.remove_context(normalized_channel_name)

        context_obj = client.context_manager.get_context(normalized_channel_name)
        if context_obj and context_obj.type == "channel":
             context_obj.update_join_status(ChannelJoinStatus.NOT_JOINED)

    else:
        client.context_manager.remove_user(normalized_channel_name, source_nick)
        message = f"{source_nick} ({source_full_ident}) has left {normalized_channel_name}"
        if part_message: message += f" ({part_message})"
        await client.add_message(message, client.ui.colors.get("join_part",0), normalized_channel_name)

    await client.event_manager.dispatch_part(
        nick=source_nick,
        userhost=source_full_ident,
        channel=normalized_channel_name,
        reason=part_message or "",
        is_self=is_self_part,
        raw_line=raw_line
    )

    if client.trigger_manager:
        trigger_action = client.trigger_manager.process_trigger(
            "PART",
            {"nick": source_nick, "userhost": source_full_ident, "channel": normalized_channel_name, "reason": part_message or "", "is_self": is_self_part, "raw_line": raw_line, "source_nick": source_nick}
        )
        if trigger_action:
            if trigger_action["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(trigger_action["content"])
            elif trigger_action["type"] == ActionType.PYTHON and trigger_action.get("code"):
                await client.execute_python_trigger_code(trigger_action["code"], trigger_action["event_data"])
            elif trigger_action["type"] == ActionType.PYTHON:
                logger.warning(f"Python trigger action for PART has no code: {trigger_action}")


async def _handle_quit(client: "IRCClient_Logic", msg: "IRCMessage", raw_line: str, params: list, trailing: Optional[str]):
    quit_message = trailing
    source_nick = msg.source_nick
    source_full_ident = msg.prefix

    if not source_nick:
        logger.warning(f"QUIT message without source_nick: {raw_line.strip()}")
        return

    message = f"{source_nick} ({source_full_ident}) has quit"
    if quit_message: message += f" ({quit_message})"

    for channel_name, context_obj in list(client.context_manager.contexts.items()):
        if context_obj.type == "channel" and source_nick in context_obj.users:
            client.context_manager.remove_user(channel_name, source_nick)
            await client.add_message(message, client.ui.colors.get("quit",0), channel_name)

    await client.event_manager.dispatch_quit(
        nick=source_nick,
        userhost=source_full_ident,
        reason=quit_message or "",
        raw_line=raw_line
    )

    if client.trigger_manager:
        trigger_action = client.trigger_manager.process_trigger(
            "QUIT",
            {"nick": source_nick, "userhost": source_full_ident, "reason": quit_message or "", "raw_line": raw_line, "source_nick": source_nick}
        )
        if trigger_action:
            if trigger_action["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(trigger_action["content"])
            elif trigger_action["type"] == ActionType.PYTHON and trigger_action.get("code"):
                await client.execute_python_trigger_code(trigger_action["code"], trigger_action["event_data"])
            elif trigger_action["type"] == ActionType.PYTHON:
                logger.warning(f"Python trigger action for QUIT has no code: {trigger_action}")


async def _handle_kick(client: "IRCClient_Logic", msg: "IRCMessage", raw_line: str, params: list, trailing: Optional[str]):
    if len(params) < 2:
        logger.warning(f"KICK message with insufficient params: {raw_line.strip()}")
        return

    channel_name = params[0]
    kicked_nick = params[1]
    kick_reason = trailing or "No reason given"

    kicker_nick = msg.source_nick
    kicker_full_ident = msg.prefix
    normalized_channel_name = client.context_manager._normalize_context_name(channel_name)

    is_self_kicked = kicked_nick.lower() == client.nick.lower() if client.nick else False

    message = f"{kicked_nick} was kicked from {normalized_channel_name} by {kicker_nick} ({kick_reason})"
    await client.add_message(message, client.ui.colors.get("kick",0), normalized_channel_name)

    if is_self_kicked:
        await client.add_status_message(f"You were kicked from {normalized_channel_name} by {kicker_nick} ({kick_reason})", "error_highlight")
        context_obj = client.context_manager.get_context(normalized_channel_name)
        if context_obj and context_obj.type == "channel":
            context_obj.update_join_status(ChannelJoinStatus.NOT_JOINED)
    else:
        client.context_manager.remove_user(normalized_channel_name, kicked_nick)

    await client.event_manager.dispatch_event(
        "KICK",
        {
            "kicker_nick": kicker_nick,
            "kicker_userhost": kicker_full_ident,
            "channel": normalized_channel_name,
            "kicked_nick": kicked_nick,
            "reason": kick_reason,
            "is_self": is_self_kicked,
            "source_nick": msg.source_nick
        },
        raw_line
    )
    if client.trigger_manager:
        trigger_action = client.trigger_manager.process_trigger(
            "KICK",
             {
                "kicker_nick": kicker_nick, "kicker_userhost": kicker_full_ident,
                "channel": normalized_channel_name, "kicked_nick": kicked_nick,
                "reason": kick_reason, "is_self": is_self_kicked, "raw_line": raw_line, "source_nick": msg.source_nick # Corrected
            }
        )
        if trigger_action:
            if trigger_action["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(trigger_action["content"])
            elif trigger_action["type"] == ActionType.PYTHON and trigger_action.get("code"):
                await client.execute_python_trigger_code(trigger_action["code"], trigger_action["event_data"])
            elif trigger_action["type"] == ActionType.PYTHON:
                logger.warning(f"Python trigger action for KICK has no code: {trigger_action}")
