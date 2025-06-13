# tirc_core/irc/handlers/state_change_handlers.py
import logging
from typing import TYPE_CHECKING, Optional, List, Dict, Any

from tirc_core.context_manager import ChannelJoinStatus
from tirc_core.features.triggers.trigger_manager import ActionType

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.irc.irc_message import IRCMessage

logger = logging.getLogger("tirc.handlers.state_change")

async def _handle_nick(client: "IRCClient_Logic", msg: "IRCMessage", raw_line: str, params: list, trailing: Optional[str]):
    """Handles NICK messages from the server."""
    old_nick = msg.source_nick
    new_nick = trailing or (params[0] if params else None)

    if not old_nick or not new_nick:
        logger.warning(f"Received NICK without old or new nick: {raw_line.strip()}")
        return

    is_self = old_nick.lower() == client.nick.lower() if client.nick else False

    for context_name, context_obj in client.context_manager.contexts.items():
        if context_obj.type == "channel" and old_nick in context_obj.users:
            user_prefix = context_obj.users.pop(old_nick, "")
            context_obj.users[new_nick] = user_prefix
            logger.debug(f"Updated nick in channel {context_name}: {old_nick} -> {new_nick}")
        elif context_obj.type == "query" and context_obj.name.lower() == old_nick.lower():
            logger.info(f"Query window for {old_nick} needs rename to {new_nick}. Manual /close and /query may be needed.")

    if is_self:
        conn_info = client.state_manager.get_connection_info()
        if conn_info:
            conn_info.nick = new_nick
            await client.state_manager.set_connection_info(conn_info)
        logger.info(f"Own nick changed: {old_nick} -> {new_nick}")
        await client.add_status_message(f"Your nickname is now {new_nick}", "system_highlight")
        await client.event_manager.dispatch_event("CLIENT_NICK_CHANGED", {"old_nick": old_nick, "new_nick": new_nick}, raw_line)
    else:
        for context_name, context_obj in client.context_manager.contexts.items():
            if context_obj.type == "channel" and new_nick in context_obj.users:
                await client.add_message(f"{old_nick} is now known as {new_nick}", client.ui.colors.get("nick_change", 0), context_name)

    await client.event_manager.dispatch_event(
        "NICK",
        {"old_nick": old_nick, "new_nick": new_nick, "userhost": msg.prefix, "is_self": is_self, "source_nick": msg.source_nick},
        raw_line
    )

    if client.trigger_manager:
        trigger_action = client.trigger_manager.process_trigger(
            "NICK",
            {"old_nick": old_nick, "new_nick": new_nick, "userhost": msg.prefix, "is_self": is_self, "raw_line": raw_line, "source_nick": msg.source_nick}
        )
        if trigger_action:
            if trigger_action["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(trigger_action["content"])
            elif trigger_action["type"] == ActionType.PYTHON and trigger_action.get("code"):
                await client.execute_python_trigger_code(trigger_action["code"], trigger_action["event_data"])
            elif trigger_action["type"] == ActionType.PYTHON:
                 logger.warning(f"Python trigger action for NICK has no code: {trigger_action}")


async def _handle_mode(client: "IRCClient_Logic", msg: "IRCMessage", raw_line: str, params: list, trailing: Optional[str]):
    if not params:
        logger.warning(f"Received MODE without parameters: {raw_line.strip()}")
        return

    target = params[0]
    modes_and_mode_params_str = " ".join(params[1:])
    if trailing:
        modes_and_mode_params_str += f" {trailing}"

    setter_nick = msg.source_nick or client.server
    setter_userhost = msg.prefix

    mode_parts = modes_and_mode_params_str.split()
    mode_string_from_server = mode_parts[0] if mode_parts else ""
    mode_params_from_server = mode_parts[1:]

    # TODO: Implement proper mode string parsing.
    # CapNegotiator does not handle this. Mode parsing is complex and IRC server specific.
    # For now, parsed_modes will be empty. Scripts and UI will have to rely on raw strings.
    parsed_modes: List[Dict[str, Any]] = []
    # Example of what a proper parser might produce:
    # parsed_modes = client.mode_parser.parse(mode_string_from_server, mode_params_from_server)

    logger.info(f"MODE received: Target='{target}', Modes='{modes_and_mode_params_str}', Setter='{setter_nick}'")
    await client.add_status_message(f"Mode [{target} {modes_and_mode_params_str}] by {setter_nick}", "mode_change")

    if client.context_manager.get_context_type(target) == "channel":
        context = client.context_manager.get_context(target)
        if context:
            current_channel_modes = list(context.modes)
            await client.event_manager.dispatch_event(
                "CHANNEL_MODE_APPLIED",
                {
                    "channel": target,
                    "setter_nick": setter_nick,
                    "setter_userhost": setter_userhost,
                    "mode_changes": parsed_modes,
                    "current_channel_modes": current_channel_modes,
                    "raw_mode_string": modes_and_mode_params_str
                },
                raw_line
            )
            await client.add_message(f"Mode [{target} {modes_and_mode_params_str}] by {setter_nick}", client.ui.colors.get("mode_change",0), target)

    await client.event_manager.dispatch_event(
        "MODE",
        {
            "target_name": target,
            "setter_nick": setter_nick,
            "setter_userhost": setter_userhost,
            "mode_string": mode_string_from_server,
            "mode_params": mode_params_from_server,
            "parsed_modes": parsed_modes,
            "source_nick": msg.source_nick
        },
        raw_line
    )

    if client.trigger_manager:
        trigger_action = client.trigger_manager.process_trigger(
            "MODE",
            {
                "target": target, "setter": setter_nick, "setter_userhost": setter_userhost,
                "mode_string": mode_string_from_server, "mode_params": mode_params_from_server,
                "parsed_modes": parsed_modes, "raw_line": raw_line, "source_nick": msg.source_nick
            }
        )
        if trigger_action:
            if trigger_action["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(trigger_action["content"])
            elif trigger_action["type"] == ActionType.PYTHON and trigger_action.get("code"):
                await client.execute_python_trigger_code(trigger_action["code"], trigger_action["event_data"])
            elif trigger_action["type"] == ActionType.PYTHON:
                 logger.warning(f"Python trigger action for MODE has no code: {trigger_action}")


async def _handle_topic(client: "IRCClient_Logic", msg: "IRCMessage", raw_line: str, params: list, trailing: Optional[str]):
    channel = params[0] if params else None
    new_topic = trailing

    if not channel:
        logger.warning(f"Received TOPIC/RPL_TOPIC without channel: {raw_line.strip()}")
        return

    setter_nick = msg.source_nick or client.server
    setter_userhost = msg.prefix

    client.context_manager.update_topic(channel, new_topic or "")

    topic_text = f"Topic for {channel} is: {new_topic}" if new_topic else f"No topic set for {channel}."
    if msg.command.upper() == "TOPIC":
        topic_text = f"{setter_nick} changed topic for {channel} to: {new_topic}"

    await client.add_message(topic_text, client.ui.colors.get("topic_change",0), channel)
    if client.context_manager.active_context_name != channel :
         await client.add_status_message(f"Topic for {channel} by {setter_nick}: {new_topic}", "topic_notify")

    await client.event_manager.dispatch_event(
        "TOPIC",
        {"channel": channel, "topic": new_topic, "setter_nick": setter_nick, "setter_userhost": setter_userhost, "source_nick": msg.source_nick},
        raw_line
    )

    if client.trigger_manager:
        trigger_action = client.trigger_manager.process_trigger(
            "TOPIC",
            {"channel": channel, "topic": new_topic, "setter": setter_nick, "setter_userhost": setter_userhost, "raw_line": raw_line, "source_nick": msg.source_nick}
        )
        if trigger_action:
            if trigger_action["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(trigger_action["content"])
            elif trigger_action["type"] == ActionType.PYTHON and trigger_action.get("code"):
                await client.execute_python_trigger_code(trigger_action["code"], trigger_action["event_data"])
            elif trigger_action["type"] == ActionType.PYTHON:
                logger.warning(f"Python trigger action for TOPIC has no code: {trigger_action}")


async def _handle_invite(client: "IRCClient_Logic", msg: "IRCMessage", raw_line: str, params: list, trailing: Optional[str]):
    inviting_nick = msg.source_nick
    invited_nick = params[0] if params else None
    channel = trailing or (params[1] if len(params) > 1 else None)

    if not inviting_nick or not invited_nick or not channel:
        logger.warning(f"Received malformed INVITE: {raw_line.strip()}")
        return

    is_self_invited = invited_nick.lower() == client.nick.lower() if client.nick else False

    if is_self_invited:
        message = f"{inviting_nick} invited you to join {channel}. Type /join {channel}"
        await client.add_status_message(message, "invite_notify")
    else:
        logger.info(f"Received INVITE for {invited_nick} to {channel} from {inviting_nick}")

    await client.event_manager.dispatch_event(
        "INVITE",
        {"inviting_nick": inviting_nick, "invited_nick": invited_nick, "channel": channel, "userhost": msg.prefix, "source_nick": msg.source_nick},
        raw_line
    )

    if client.trigger_manager:
        trigger_action = client.trigger_manager.process_trigger(
            "INVITE",
            {"inviter": inviting_nick, "invited": invited_nick, "channel": channel, "userhost": msg.prefix, "raw_line": raw_line, "source_nick": msg.source_nick}
        )
        if trigger_action:
            if trigger_action["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(trigger_action["content"])
            elif trigger_action["type"] == ActionType.PYTHON and trigger_action.get("code"):
                await client.execute_python_trigger_code(trigger_action["code"], trigger_action["event_data"])
            elif trigger_action["type"] == ActionType.PYTHON:
                logger.warning(f"Python trigger action for INVITE has no code: {trigger_action}")

async def _handle_chghost(client: "IRCClient_Logic", msg: "IRCMessage", raw_line: str, params: List[str], trailing: Optional[str]):
    old_nick_from_prefix = msg.source_nick
    old_userhost_from_prefix = msg.prefix

    if not old_nick_from_prefix or not old_userhost_from_prefix:
        logger.warning(f"CHGHOST received without a full prefix: {raw_line.strip()}")
        return

    if len(params) == 2:
        target_nick = old_nick_from_prefix
        new_ident = params[0]
        new_host = params[1]
    elif len(params) == 3:
        target_nick = params[0]
        new_ident = params[1]
        new_host = params[2]
        if target_nick.lower() != old_nick_from_prefix.lower():
            logger.warning(f"CHGHOST prefix nick {old_nick_from_prefix} differs from param nick {target_nick}. Using prefix nick.")
            target_nick = old_nick_from_prefix
    else:
        logger.warning(f"Malformed CHGHOST message: {raw_line.strip()}")
        return

    new_full_userhost = f"{new_ident}@{new_host}"
    logger.info(f"User {target_nick} changed host: {old_userhost_from_prefix} -> {target_nick}!{new_full_userhost}")

    for context in client.context_manager.contexts.values():
        if context.type == "channel" and target_nick in context.users:
            pass

    message_to_display = f"{target_nick} is now {target_nick}!{new_full_userhost} (was {old_userhost_from_prefix})"
    for channel_name in client.context_manager.get_all_channels():
        if target_nick in client.context_manager.get_users(channel_name):
            await client.add_message(message_to_display, client.ui.colors.get("system_dim", 0), channel_name)

    await client.event_manager.dispatch_event(
        "CHGHOST",
        {
            "nick": target_nick,
            "new_ident": new_ident,
            "new_host": new_host,
            "old_userhost": old_userhost_from_prefix,
            "source_nick": msg.source_nick
        },
        raw_line
    )

    if client.trigger_manager:
        trigger_action = client.trigger_manager.process_trigger(
            "CHGHOST",
            {
                "nick": target_nick, "new_ident": new_ident, "new_host": new_host,
                "old_userhost": old_userhost_from_prefix, "raw_line": raw_line, "source_nick": msg.source_nick
            }
        )
        if trigger_action:
            if trigger_action["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(trigger_action["content"])
            elif trigger_action["type"] == ActionType.PYTHON and trigger_action.get("code"):
                await client.execute_python_trigger_code(trigger_action["code"], trigger_action["event_data"])
            elif trigger_action["type"] == ActionType.PYTHON:
                logger.warning(f"Python trigger action for CHGHOST has no code: {trigger_action}")
