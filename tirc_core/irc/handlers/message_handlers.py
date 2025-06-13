# tirc_core/irc/handlers/message_handlers.py
import logging
from typing import TYPE_CHECKING, Optional, Dict, Any

from tirc_core.irc.irc_message import IRCMessage
from tirc_core.features.triggers.trigger_manager import ActionType # Added import

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.handlers.message")


async def _handle_privmsg(
    client: "IRCClient_Logic",
    parsed_msg: IRCMessage,
    raw_line: str,
    params: list,
    trailing: Optional[str],
):
    """Handles PRIVMSG commands."""
    if not params or not trailing:
        logger.warning(f"PRIVMSG: Missing target or message. Raw: {raw_line.strip()}")
        return

    target = params[0]
    message_content = trailing
    source_nick = parsed_msg.source_nick if parsed_msg.source_nick else "Unknown" # Corrected
    source_full_ident = parsed_msg.prefix if parsed_msg.prefix else "Unknown!Unknown@Unknown"

    is_channel_msg = target.startswith(("#", "&", "!", "+"))
    context_name_to_use = target if is_channel_msg else source_nick

    if not is_channel_msg:
        client.context_manager.create_context(context_name_to_use, context_type="query")

    color_key = "channel_message" if is_channel_msg else "private_message"
    color_pair_id = client.ui.colors.get(color_key, client.ui.colors.get("default", 0))

    action_text = "" # Define action_text outside the if block
    if message_content.startswith("\x01ACTION ") and message_content.endswith("\x01"):
        action_text = message_content[len("\x01ACTION ") : -1]
        formatted_message = f"* {source_nick} {action_text}"
        color_pair_id = client.ui.colors.get("action_message", color_pair_id)
    else:
        formatted_message = f"<{source_nick}> {message_content}"


    await client.add_message(
        text=formatted_message,
        color_pair_id=color_pair_id,
        context_name=context_name_to_use,
        source_full_ident=source_full_ident,
        is_privmsg_or_notice=True
    )

    if hasattr(client, "event_manager") and client.event_manager:
        await client.event_manager.dispatch_privmsg(
            nick=source_nick,
            userhost=source_full_ident,
            target=target,
            message=message_content,
            is_channel_msg=is_channel_msg,
            tags=parsed_msg.get_all_tags(),
            raw_line=raw_line
        )

    if client.trigger_manager:
        trigger_event_data = {
            "nick": source_nick,
            "userhost": source_full_ident,
            "target": target,
            "message": message_content,
            "is_channel_msg": is_channel_msg,
            "tags": parsed_msg.get_all_tags(),
            "raw_line": raw_line,
            "client_nick": client.nick,
            "source_nick": source_nick # Added for consistency
        }
        trigger_event_type = "ACTION" if message_content.startswith("\x01ACTION ") and message_content.endswith("\x01") else "TEXT"
        if trigger_event_type == "ACTION":
            trigger_event_data["message"] = action_text

        action_to_take = client.trigger_manager.process_trigger(trigger_event_type, trigger_event_data)
        if action_to_take:
            if action_to_take["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(action_to_take["content"])
            elif action_to_take["type"] == ActionType.PYTHON and action_to_take.get("code"): # Check for code
                await client.execute_python_trigger_code(action_to_take["code"], action_to_take["event_data"]) # Corrected call
            elif action_to_take["type"] == ActionType.PYTHON:
                logger.warning(f"Python trigger action for {trigger_event_type} has no code: {action_to_take}")


async def _handle_notice(
    client: "IRCClient_Logic",
    parsed_msg: IRCMessage,
    raw_line: str,
    params: list,
    trailing: Optional[str],
):
    if not params or not trailing:
        logger.warning(f"NOTICE: Missing target or message. Raw: {raw_line.strip()}")
        return

    target = params[0]
    message_content = trailing
    source_nick = parsed_msg.source_nick if parsed_msg.source_nick else "Server" # Corrected
    source_full_ident = parsed_msg.prefix if parsed_msg.prefix else "Server!Server@Server"

    is_channel_notice = target.startswith(("#", "&", "!", "+"))
    context_name_to_use = "Status"

    if is_channel_notice and client.context_manager.get_context(target):
        context_name_to_use = target
    elif not is_channel_notice and target.lower() == (client.nick or "").lower():
        context_name_to_use = source_nick
        client.context_manager.create_context(context_name_to_use, context_type="query")
    elif not is_channel_notice:
        context_name_to_use = "Status"


    formatted_message = f"-{source_nick}- {message_content}"
    color_pair_id = client.ui.colors.get("notice_message", client.ui.colors.get("system_dim", 0))

    await client.add_message(
        text=formatted_message,
        color_pair_id=color_pair_id,
        context_name=context_name_to_use,
        source_full_ident=source_full_ident,
        is_privmsg_or_notice=True
    )

    if hasattr(client, "event_manager") and client.event_manager:
        await client.event_manager.dispatch_notice(
            nick=source_nick,
            userhost=source_full_ident,
            target=target,
            message=message_content,
            is_channel_notice=is_channel_notice,
            tags=parsed_msg.get_all_tags(),
            raw_line=raw_line
        )

    if client.trigger_manager:
        trigger_event_data = {
            "nick": source_nick,
            "userhost": source_full_ident,
            "target": target,
            "message": message_content,
            "is_channel_notice": is_channel_notice,
            "tags": parsed_msg.get_all_tags(),
            "raw_line": raw_line,
            "client_nick": client.nick,
            "source_nick": source_nick # Added for consistency
        }
        action_to_take = client.trigger_manager.process_trigger("NOTICE", trigger_event_data)
        if action_to_take:
            if action_to_take["type"] == ActionType.COMMAND:
                await client.command_handler.process_user_command(action_to_take["content"])
            elif action_to_take["type"] == ActionType.PYTHON and action_to_take.get("code"): # Check for code
                await client.execute_python_trigger_code(action_to_take["code"], action_to_take["event_data"]) # Corrected call
            elif action_to_take["type"] == ActionType.PYTHON:
                logger.warning(f"Python trigger action for NOTICE has no code: {action_to_take}")
