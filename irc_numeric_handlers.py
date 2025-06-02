import logging
from typing import Optional

from irc_message import IRCMessage
from context_manager import ChannelJoinStatus

logger = logging.getLogger("pyrc.protocol")


def _handle_rpl_welcome(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_WELCOME (001)."""
    params = parsed_msg.params
    confirmed_nick = params[0] if params else client.nick

    if client.nick != confirmed_nick:
        logger.info(
            f"RPL_WELCOME: Nick confirmed by server as '{confirmed_nick}', was '{client.nick}'. Updating client.nick."
        )
        client.nick = confirmed_nick
    elif not client.nick and confirmed_nick:
        client.nick = confirmed_nick

    client.add_message(
        f"Welcome to {client.server}: {trailing if trailing else ''}",
        client.ui.colors["system"],
        context_name="Status",
    )
    logger.info(f"Received RPL_WELCOME (001). Nick confirmed as {client.nick}.")

    if hasattr(client, "registration_handler") and client.registration_handler:
        client.registration_handler.on_welcome_received(confirmed_nick)
    else:
        logger.error(
            "RPL_WELCOME received, but client.registration_handler is not initialized."
        )
        client.add_message(
            "Error: Registration handler not ready for RPL_WELCOME.",
            client.ui.colors["error"],
            "Status",
        )


def _handle_rpl_notopic(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_NOTOPIC (331)."""
    channel_name = display_params[0] if display_params else "channel"
    client.context_manager.create_context(channel_name, context_type="channel")
    context = client.context_manager.get_context(channel_name)
    if context:
        context.topic = None
    client.add_message(
        f"No topic set for {channel_name}.",
        client.ui.colors["system"],
        context_name=channel_name,
    )


def _handle_rpl_topic(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_TOPIC (332)."""
    channel_name = display_params[0] if display_params else "channel"
    topic_text = trailing if trailing else ""
    client.context_manager.create_context(channel_name, context_type="channel")
    client.context_manager.update_topic(channel_name, topic_text)
    client.add_message(
        f"Topic for {channel_name}: {topic_text}",
        client.ui.colors["system"],
        context_name=channel_name,
    )


def _handle_generic_numeric(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
    generic_numeric_msg: str,
):
    """Handles generic or unassigned numeric replies."""
    client.add_message(
        f"[{parsed_msg.command}] {generic_numeric_msg}",
        client.ui.colors["system"],
        "Status",
    )
    logger.debug(
        f"Received unhandled/generic numeric {parsed_msg.command}: {raw_line.strip()} (Generic msg: {generic_numeric_msg})"
    )


def _handle_rpl_namreply(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_NAMREPLY (353)."""
    channel_in_reply = display_params[1] if len(display_params) > 1 else None
    if channel_in_reply:
        created_for_namreply = client.context_manager.create_context(
            channel_in_reply,
            context_type="channel",
            initial_join_status_for_channel=ChannelJoinStatus.NOT_JOINED,
        )
        if created_for_namreply:
            logger.debug(
                f"Ensured channel context exists for NAMREPLY: {channel_in_reply} (created with NOT_JOINED)"
            )

        target_ctx_for_names = client.context_manager.get_context(channel_in_reply)
        if target_ctx_for_names:
            if (
                target_ctx_for_names.join_status
                == ChannelJoinStatus.PENDING_INITIAL_JOIN
                or target_ctx_for_names.join_status
                == ChannelJoinStatus.JOIN_COMMAND_SENT
            ):
                target_ctx_for_names.join_status = ChannelJoinStatus.SELF_JOIN_RECEIVED
                logger.debug(
                    f"NAMREPLY for {channel_in_reply}: Updated join_status to SELF_JOIN_RECEIVED"
                )

            nicks_on_list = trailing.split() if trailing else []
            for nick_entry in nicks_on_list:
                prefix_char = ""
                actual_nick = nick_entry
                if nick_entry.startswith(("@", "+", "%", "&", "~")):
                    prefix_char = nick_entry[0]
                    actual_nick = nick_entry[1:]
                client.context_manager.add_user(
                    channel_in_reply, actual_nick, prefix_char
                )
        else:
            logger.warning(
                f"RPL_NAMREPLY: Context {channel_in_reply} not found after create attempt."
            )
    else:
        logger.warning(f"RPL_NAMREPLY for unknown context. Raw: {raw_line.strip()}")


def _handle_rpl_endofnames(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_ENDOFNAMES (366)."""
    channel_ended = display_params[0] if display_params else "Unknown Channel"
    ctx_for_endofnames = client.context_manager.get_context(channel_ended)
    if ctx_for_endofnames and ctx_for_endofnames.type == "channel":
        user_count = len(ctx_for_endofnames.users)

        if ctx_for_endofnames.join_status in [
            ChannelJoinStatus.SELF_JOIN_RECEIVED,
            ChannelJoinStatus.JOIN_COMMAND_SENT,
            ChannelJoinStatus.PENDING_INITIAL_JOIN,
        ]:
            ctx_for_endofnames.join_status = ChannelJoinStatus.FULLY_JOINED
            logger.info(
                f"RPL_ENDOFNAMES for {channel_ended}. Set join_status to FULLY_JOINED. User count: {user_count}."
            )
            if channel_ended not in client.currently_joined_channels:
                client.currently_joined_channels.add(channel_ended)
                logger.info(
                    f"Added {channel_ended} to tracked client.currently_joined_channels."
                )
            client.handle_channel_fully_joined(channel_ended)
        elif ctx_for_endofnames.join_status == ChannelJoinStatus.NOT_JOINED:
            logger.info(
                f"RPL_ENDOFNAMES for {channel_ended} (status NOT_JOINED). User count: {user_count}. Not changing join status from this alone, as we weren't in a pending join state."
            )

        client.add_message(
            f"Users in {channel_ended}: {user_count}",
            client.ui.colors["system"],
            context_name=channel_ended,
        )
    else:
        logger.warning(
            f"RPL_ENDOFNAMES for {channel_ended}, but context not found or not a channel."
        )
        client.add_message(
            f"End of names for {channel_ended} (context not found).",
            client.ui.colors["error"],
            "Status",
        )


def _handle_err_nosuchnick(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles ERR_NOSUCHNICK (401)."""
    nosuch_nick = display_params[0] if display_params else "nick"
    client.add_message(
        f"No such nick: {nosuch_nick}",
        client.ui.colors["error"],
        client.context_manager.active_context_name or "Status",
    )


def _handle_err_nosuchchannel(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles ERR_NOSUCHCHANNEL (403)."""
    channel_name = display_params[0] if display_params else "channel"
    client.add_message(
        f"Channel {channel_name} does not exist or is invalid.",
        client.ui.colors["error"],
        "Status",
    )
    failed_join_ctx = client.context_manager.get_context(channel_name)
    if failed_join_ctx and failed_join_ctx.type == "channel":
        failed_join_ctx.join_status = ChannelJoinStatus.JOIN_FAILED
        logger.debug(
            f"Set join_status to JOIN_FAILED for {channel_name} due to ERR_NOSUCHCHANNEL."
        )
    client.currently_joined_channels.discard(channel_name)
    logger.warning(
        f"ERR_NOSUCHCHANNEL (403) for {channel_name}. Marked as JOIN_FAILED and removed from tracked channels."
    )


def _handle_err_channel_join_group(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles grouped channel join errors (471, 473, 474, 475)."""
    code = int(parsed_msg.command)
    channel_name = display_params[0] if display_params else "channel"
    error_message_map = {
        471: "is full",
        473: "is invite-only",
        474: "you are banned",
        475: "bad channel key (password)",
    }
    reason = error_message_map.get(code, "join error")
    client.add_message(
        f"Cannot join {channel_name}: {reason}. {trailing if trailing else ''}",
        client.ui.colors["error"],
        "Status",
    )
    failed_join_ctx = client.context_manager.get_context(channel_name)
    if failed_join_ctx and failed_join_ctx.type == "channel":
        failed_join_ctx.join_status = ChannelJoinStatus.JOIN_FAILED
        logger.debug(
            f"Set join_status to JOIN_FAILED for {channel_name} due to {code}."
        )
    client.currently_joined_channels.discard(channel_name)
    logger.warning(
        f"Channel join error {code} for {channel_name}. Marked as JOIN_FAILED."
    )


def _handle_err_nicknameinuse(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles ERR_NICKNAMEINUSE (433)."""
    failed_nick = display_params[0] if display_params else client.nick
    logger.warning(f"ERR_NICKNAMEINUSE (433) for {failed_nick}: {raw_line.strip()}")
    client.add_message(
        f"Nickname {failed_nick} is already in use.",
        client.ui.colors["error"],
        "Status",
    )

    is_our_nick_colliding = client.nick and client.nick.lower() == failed_nick.lower()

    if is_our_nick_colliding and not client.network.is_handling_nick_collision:
        if hasattr(client, "registration_handler") and client.registration_handler:
            current_nick_for_logic = client.nick
            initial_nick_for_logic = client.initial_nick

            if current_nick_for_logic.lower() == initial_nick_for_logic.lower():
                new_try_nick = f"{initial_nick_for_logic}_"
            else:
                if current_nick_for_logic.endswith("_"):
                    new_try_nick = f"{current_nick_for_logic[:-1]}1"
                elif current_nick_for_logic[-1].isdigit():
                    new_try_nick = f"{current_nick_for_logic[:-1]}{int(current_nick_for_logic[-1])+1}"
                else:
                    new_try_nick = f"{current_nick_for_logic}_"

            logger.info(f"Nickname {failed_nick} in use, trying {new_try_nick}.")
            client.add_message(
                f"Trying {new_try_nick} instead.", client.ui.colors["system"], "Status"
            )

            client.network.is_handling_nick_collision = True
            client.network.send_raw(f"NICK {new_try_nick}")
            client.nick = new_try_nick
            client.registration_handler.update_nick_for_registration(new_try_nick)
        else:
            logger.warning(
                "ERR_NICKNAMEINUSE for our nick, but no registration_handler to manage retry."
            )
    elif is_our_nick_colliding and client.network.is_handling_nick_collision:
        logger.info(
            f"ERR_NICKNAMEINUSE for {failed_nick}, but already handling a nick collision. Manual /NICK needed if this fails."
        )


def _handle_sasl_loggedin_success(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_LOGGEDIN (900) and RPL_SASLSUCCESS (903)."""
    code = int(parsed_msg.command)
    account_name = "your account"
    original_params = parsed_msg.params
    if code == 900 and len(original_params) > 1:
        account_name = original_params[1]

    success_msg = (
        f"Successfully logged in as {account_name} ({code})."
        if code == 900
        else f"SASL authentication successful ({code})."
    )

    if hasattr(client, "sasl_authenticator") and client.sasl_authenticator:
        client.sasl_authenticator.on_sasl_result_received(True, success_msg)
    else:
        logger.error(f"SASL Success ({code}), but no sasl_authenticator on client.")
        client.add_message(
            f"SASL Success ({code}), but authenticator missing.",
            client.ui.colors["error"],
            "Status",
        )


def _handle_sasl_mechanisms(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_SASLMECHS (902) or ERR_SASLMECHS (908)."""
    code = int(parsed_msg.command)
    mechanisms = trailing if trailing else "unknown"
    logger.info(
        f"SASL: Server indicated mechanisms: {mechanisms} (Code: {code}). Raw: {raw_line.strip()}"
    )
    client.add_message(
        f"SASL: Server mechanisms: {mechanisms}", client.ui.colors["system"], "Status"
    )


def _handle_sasl_fail_errors(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles ERR_SASLFAIL (904), ERR_SASLTOOLONG (905), ERR_SASLABORTED (906)."""
    code = int(parsed_msg.command)
    default_reasons = {
        904: "SASL authentication failed",
        905: "SASL message too long / Base64 decoding error",
        906: "SASL authentication aborted by server or client",
    }
    reason = trailing if trailing else default_reasons.get(code, f"SASL error ({code})")
    if hasattr(client, "sasl_authenticator") and client.sasl_authenticator:
        client.sasl_authenticator.on_sasl_result_received(False, reason)
    else:
        logger.error(f"SASL Failure ({code}), but no sasl_authenticator on client.")
        client.add_message(
            f"SASL Error ({code}): {reason}, but authenticator missing.",
            client.ui.colors["error"],
            "Status",
        )


def _handle_err_saslalready(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles ERR_SASLALREADY (907)."""
    reason = trailing if trailing else "You have already authenticated (907)"
    if hasattr(client, "sasl_authenticator") and client.sasl_authenticator:
        client.sasl_authenticator.on_sasl_result_received(True, reason)
    else:
        logger.error("ERR_SASLALREADY (907), but no sasl_authenticator on client.")
        client.add_message(
            f"SASL Warning (907): {reason}, but authenticator missing.",
            client.ui.colors["warning"],
            "Status",
        )


def _handle_rpl_whoisuser(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_WHOISUSER (311)."""
    original_params = parsed_msg.params
    whois_nick = original_params[0] if len(original_params) > 0 else "N/A"
    user_info = original_params[1] if len(original_params) > 1 else "N/A"
    host_info = original_params[2] if len(original_params) > 2 else "N/A"
    realname = trailing if trailing else "N/A"
    message_to_add = (
        f"[WHOIS {whois_nick}] User: {user_info}@{host_info} Realname: {realname}"
    )
    client.add_message(message_to_add, client.ui.colors["system"], "Status")


def _handle_rpl_endofwhois(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_ENDOFWHOIS (318)."""
    original_params = parsed_msg.params
    whois_nick = original_params[0] if len(original_params) > 0 else "N/A"
    client.add_message(
        f"[WHOIS {whois_nick}] End of WHOIS.", client.ui.colors["system"], "Status"
    )


def _handle_motd_and_server_info(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
    generic_numeric_msg: str,
):
    """Handles MOTD and various server information numerics."""
    client.add_message(
        f"[{parsed_msg.command}] {generic_numeric_msg}",
        client.ui.colors["system"],
        "Status",
    )


def _handle_rpl_whoreply(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_WHOREPLY (352). <client_nick> <channel> <user> <host> <server> <nick> <H|G>[*][@|+] :<hopcount> <real_name>"""
    # Params from server: <your_nick> <channel> <user> <host> <server> <nick> <flags> :<hops> <real_name>
    # display_params removes <your_nick>

    channel = display_params[0] if len(display_params) > 0 else "N/A"
    user = display_params[1] if len(display_params) > 1 else "N/A"
    host = display_params[2] if len(display_params) > 2 else "N/A"
    server_name = display_params[3] if len(display_params) > 3 else "N/A"
    nick = display_params[4] if len(display_params) > 4 else "N/A"
    flags = display_params[5] if len(display_params) > 5 else ""
    # trailing contains "<hopcount> <real_name>"

    message_to_add = f"[WHO {channel}] {nick} ({user}@{host} on {server_name}) Flags: {flags} - {trailing if trailing else ''}"
    client.add_message(message_to_add, client.ui.colors["system"], "Status")


def _handle_rpl_endofwho(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_ENDOFWHO (315). <client_nick> <name> :End of WHO list"""
    # display_params[0] is <name> (the target of the WHO)
    who_target = display_params[0] if display_params else "N/A"
    message_to_add = (
        f"[WHO {who_target}] {trailing if trailing else 'End of WHO list.'}"
    )
    client.add_message(message_to_add, client.ui.colors["system"], "Status")


def _handle_rpl_whowasuser(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_WHOWASUSER (314). <client_nick> <nick> <user> <host> * :<real_name>"""
    # display_params[0] is <nick>
    # display_params[1] is <user>
    # display_params[2] is <host>
    # trailing is <real_name>

    nick = display_params[0] if len(display_params) > 0 else "N/A"
    user = display_params[1] if len(display_params) > 1 else "N/A"
    host = display_params[2] if len(display_params) > 2 else "N/A"
    real_name = trailing if trailing else "N/A"

    message_to_add = f"[WHOWAS {nick}] User: {user}@{host} Realname: {real_name}"
    client.add_message(message_to_add, client.ui.colors["system"], "Status")


def _handle_rpl_endofwhowas(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_ENDOFWHOWAS (369). <client_nick> <nick> :End of WHOWAS list"""
    # display_params[0] is <nick>
    whowas_nick = display_params[0] if display_params else "N/A"
    message_to_add = (
        f"[WHOWAS {whowas_nick}] {trailing if trailing else 'End of WHOWAS list.'}"
    )
    client.add_message(message_to_add, client.ui.colors["system"], "Status")


def _handle_rpl_liststart(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_LISTSTART (321). <client_nick> Channels :Users Name"""
    # display_params might be empty or contain "Channels"
    # trailing might be "Users Name" or absent

    active_list_ctx_name = getattr(client, "active_list_context_name", None)
    target_context_name = "Status"  # Default target

    if active_list_ctx_name:
        list_ctx = client.context_manager.get_context(active_list_ctx_name)
        if list_ctx and list_ctx.type == "list_results":
            target_context_name = active_list_ctx_name
            logger.debug(
                f"RPL_LISTSTART: Active list operation detected. Target context: {target_context_name}"
            )
        elif list_ctx:  # Context exists but is not list_results type
            logger.warning(
                f"RPL_LISTSTART: active_list_context_name '{active_list_ctx_name}' exists but is not type 'list_results' (type: {list_ctx.type}). Defaulting to Status."
            )
        else:  # Context name was set, but context doesn't exist
            logger.warning(
                f"RPL_LISTSTART: active_list_context_name '{active_list_ctx_name}' not found. Defaulting to Status."
            )

    prefix = ""  # No prefix needed if going to its own window
    if target_context_name == "Status":
        prefix = "[List] "  # Add prefix only if falling back to Status

    message = f"{prefix}{trailing if trailing else 'Channel List Start'}"
    if display_params and display_params[0] == "Channels" and not trailing:
        message = f"{prefix}Channel List (Users Name)"
    elif not display_params and not trailing:
        message = f"{prefix}Channel List Start"

    client.add_message(message, client.ui.colors["system"], target_context_name)


def _handle_rpl_list(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_LIST (322). <client_nick> <channel> <#_visible> :<topic>"""
    # display_params[0] is <channel>
    # display_params[1] is <#_visible>
    # trailing is <topic>

    active_list_ctx_name = getattr(client, "active_list_context_name", None)
    target_context_name = "Status"  # Default target

    if active_list_ctx_name:
        list_ctx = client.context_manager.get_context(active_list_ctx_name)
        if list_ctx and list_ctx.type == "list_results":
            target_context_name = active_list_ctx_name
            logger.debug(
                f"RPL_LIST: Active list operation detected. Target context: {target_context_name}"
            )
        elif list_ctx:
            logger.warning(
                f"RPL_LIST: active_list_context_name '{active_list_ctx_name}' exists but is not type 'list_results' (type: {list_ctx.type}). Defaulting to Status."
            )
        else:
            logger.warning(
                f"RPL_LIST: active_list_context_name '{active_list_ctx_name}' not found. Defaulting to Status."
            )

    prefix = ""  # No prefix needed if going to its own window
    if target_context_name == "Status":
        prefix = "[List] "  # Add prefix only if falling back to Status

    channel = display_params[0] if len(display_params) > 0 else "N/A"
    visible_users = display_params[1] if len(display_params) > 1 else "N/A"
    topic = trailing if trailing else "No topic"

    message_to_add = f"{prefix}{channel}: {visible_users} users - {topic}"
    client.add_message(message_to_add, client.ui.colors["system"], target_context_name)


def _handle_rpl_listend(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_LISTEND (323). <client_nick> :End of LIST"""
    active_list_ctx_name = getattr(client, "active_list_context_name", None)
    target_context_name_for_message = (
        "Status"  # Default for the main "End of list" message
    )

    if active_list_ctx_name:
        list_ctx = client.context_manager.get_context(active_list_ctx_name)
        if list_ctx and list_ctx.type == "list_results":
            target_context_name_for_message = active_list_ctx_name
            logger.debug(
                f"RPL_LISTEND: Active list operation detected. Target context: {target_context_name_for_message}"
            )
            # Add specific instructions to the temporary list window
            client.add_message(
                "--- End of /list results ---",
                client.ui.colors["system"],
                target_context_name_for_message,
            )
            client.add_message(
                "This is a temporary window. Type /close or press Ctrl+W to close it.",
                client.ui.colors["system"],
                target_context_name_for_message,
            )
        elif list_ctx:
            logger.warning(
                f"RPL_LISTEND: active_list_context_name '{active_list_ctx_name}' exists but is not type 'list_results' (type: {list_ctx.type}). Defaulting to Status for end message."
            )
            client.add_message(
                f"[List] {trailing if trailing else 'End of channel list.'}",
                client.ui.colors["system"],
                "Status",
            )
        else:
            logger.warning(
                f"RPL_LISTEND: active_list_context_name '{active_list_ctx_name}' not found. Defaulting to Status for end message."
            )
            client.add_message(
                f"[List] {trailing if trailing else 'End of channel list.'}",
                client.ui.colors["system"],
                "Status",
            )
    else:  # No active_list_context_name was set, so message definitely goes to Status
        client.add_message(
            f"[List] {trailing if trailing else 'End of channel list.'}",
            client.ui.colors["system"],
            "Status",
        )

    # Clear active_list_context_name regardless of where messages went,
    # as the /list server operation is now finished.
    if (
        hasattr(client, "active_list_context_name")
        and client.active_list_context_name is not None
    ):
        logger.debug(
            f"RPL_LISTEND: Clearing active_list_context_name ('{client.active_list_context_name}')."
        )
        client.active_list_context_name = None


NUMERIC_HANDLERS = {
    1: _handle_rpl_welcome,
    251: _handle_motd_and_server_info,
    252: _handle_motd_and_server_info,
    253: _handle_motd_and_server_info,
    254: _handle_motd_and_server_info,
    255: _handle_motd_and_server_info,
    265: _handle_motd_and_server_info,
    266: _handle_motd_and_server_info,
    311: _handle_rpl_whoisuser,
    318: _handle_rpl_endofwhois,
    331: _handle_rpl_notopic,
    332: _handle_rpl_topic,
    353: _handle_rpl_namreply,
    366: _handle_rpl_endofnames,
    372: _handle_motd_and_server_info,
    375: _handle_motd_and_server_info,
    376: _handle_motd_and_server_info,
    401: _handle_err_nosuchnick,
    403: _handle_err_nosuchchannel,
    433: _handle_err_nicknameinuse,
    471: _handle_err_channel_join_group,
    473: _handle_err_channel_join_group,
    474: _handle_err_channel_join_group,
    475: _handle_err_channel_join_group,
    900: _handle_sasl_loggedin_success,
    902: _handle_sasl_mechanisms,
    903: _handle_sasl_loggedin_success,
    904: _handle_sasl_fail_errors,
    905: _handle_sasl_fail_errors,
    906: _handle_sasl_fail_errors,
    907: _handle_err_saslalready,
    908: _handle_sasl_mechanisms,
    # New handlers for WHO, WHOWAS, LIST
    314: _handle_rpl_whowasuser,
    315: _handle_rpl_endofwho,
    321: _handle_rpl_liststart,
    322: _handle_rpl_list,
    323: _handle_rpl_listend,
    352: _handle_rpl_whoreply,
    369: _handle_rpl_endofwhowas,
}


def _handle_numeric_command(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles numeric commands from the server."""
    code = int(parsed_msg.command)
    params = parsed_msg.params
    trailing = parsed_msg.trailing

    # Create display_params by removing client nick if present
    display_params = list(params)
    if (
        display_params
        and client.nick
        and display_params[0].lower() == client.nick.lower()
    ):
        display_params.pop(0)

    # Dispatch RAW_IRC_NUMERIC event before specific handlers
    if hasattr(client, "script_manager"):
        numeric_event_data = {
            "numeric": code,
            "source": parsed_msg.prefix,
            "params_list": list(params),
            "display_params_list": display_params,
            "trailing": trailing,
            "raw_line": raw_line,
            "tags": parsed_msg.get_all_tags(),
        }
        client.script_manager.dispatch_event("RAW_IRC_NUMERIC", numeric_event_data)

    # Handle specific numeric commands
    if code == 1:  # RPL_WELCOME
        _handle_rpl_welcome(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 251:  # MOTD and server info
        _handle_motd_and_server_info(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
    elif code == 252:  # MOTD and server info
        _handle_motd_and_server_info(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
    elif code == 253:  # MOTD and server info
        _handle_motd_and_server_info(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
    elif code == 254:  # MOTD and server info
        _handle_motd_and_server_info(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
    elif code == 255:  # MOTD and server info
        _handle_motd_and_server_info(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
    elif code == 265:  # MOTD and server info
        _handle_motd_and_server_info(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
    elif code == 266:  # MOTD and server info
        _handle_motd_and_server_info(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
    elif code == 311:  # RPL_WHOISUSER
        _handle_rpl_whoisuser(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 318:  # RPL_ENDOFWHOIS
        _handle_rpl_endofwhois(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 331:  # RPL_NOTOPIC
        _handle_rpl_notopic(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 332:  # RPL_TOPIC
        _handle_rpl_topic(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 353:  # RPL_NAMREPLY
        _handle_rpl_namreply(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 366:  # RPL_ENDOFNAMES
        _handle_rpl_endofnames(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 372:  # MOTD and server info
        _handle_motd_and_server_info(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
    elif code == 375:  # MOTD and server info
        _handle_motd_and_server_info(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
    elif code == 376:  # MOTD and server info
        _handle_motd_and_server_info(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
    elif code == 401:  # ERR_NOSUCHNICK
        _handle_err_nosuchnick(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 403:  # ERR_NOSUCHCHANNEL
        _handle_err_nosuchchannel(
            client, parsed_msg, raw_line, display_params, trailing
        )
    elif code == 433:  # ERR_NICKNAMEINUSE
        _handle_err_nicknameinuse(
            client, parsed_msg, raw_line, display_params, trailing
        )
    elif code == 471:  # ERR_CHANNEL_JOIN_GROUP
        _handle_err_channel_join_group(
            client, parsed_msg, raw_line, display_params, trailing
        )
    elif code == 473:  # ERR_CHANNEL_JOIN_GROUP
        _handle_err_channel_join_group(
            client, parsed_msg, raw_line, display_params, trailing
        )
    elif code == 474:  # ERR_CHANNEL_JOIN_GROUP
        _handle_err_channel_join_group(
            client, parsed_msg, raw_line, display_params, trailing
        )
    elif code == 475:  # ERR_CHANNEL_JOIN_GROUP
        _handle_err_channel_join_group(
            client, parsed_msg, raw_line, display_params, trailing
        )
    elif code == 900:  # RPL_LOGGEDIN
        _handle_sasl_loggedin_success(
            client, parsed_msg, raw_line, display_params, trailing
        )
    elif code == 902:  # RPL_SASLMECHS
        _handle_sasl_mechanisms(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 903:  # RPL_SASLSUCCESS
        _handle_sasl_loggedin_success(
            client, parsed_msg, raw_line, display_params, trailing
        )
    elif code == 904:  # ERR_SASLFAIL
        _handle_sasl_fail_errors(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 905:  # ERR_SASLTOOLONG
        _handle_sasl_fail_errors(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 906:  # ERR_SASLABORTED
        _handle_sasl_fail_errors(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 907:  # ERR_SASLALREADY
        _handle_err_saslalready(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 908:  # ERR_SASLMECHS
        _handle_sasl_mechanisms(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 314:  # RPL_WHOWASUSER
        _handle_rpl_whowasuser(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 315:  # RPL_ENDOFWHO
        _handle_rpl_endofwho(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 321:  # RPL_LISTSTART
        _handle_rpl_liststart(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 322:  # RPL_LIST
        _handle_rpl_list(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 323:  # RPL_LISTEND
        _handle_rpl_listend(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 352:  # RPL_WHOREPLY
        _handle_rpl_whoreply(client, parsed_msg, raw_line, display_params, trailing)
    elif code == 369:  # RPL_ENDOFWHOWAS
        _handle_rpl_endofwhowas(client, parsed_msg, raw_line, display_params, trailing)
    else:
        _handle_generic_numeric(
            client,
            parsed_msg,
            raw_line,
            display_params,
            trailing,
            display_params[0] if display_params else "",
        )
