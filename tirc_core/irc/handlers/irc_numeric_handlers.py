import logging
import random # Added for random nick generation
import asyncio # Import asyncio
from typing import Optional

from pyrc_core.irc.irc_message import IRCMessage
from pyrc_core.context_manager import ChannelJoinStatus
from pyrc_core.state_manager import ConnectionState

logger = logging.getLogger("pyrc.protocol")


async def _handle_rpl_welcome(
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
        conn_info = client.state_manager.get_connection_info()
        if conn_info:
            conn_info.nick = confirmed_nick
            client.state_manager.set("connection_info", conn_info)
    elif not client.nick and confirmed_nick:
        conn_info = client.state_manager.get_connection_info()
        if conn_info:
            conn_info.nick = confirmed_nick
            client.state_manager.set("connection_info", conn_info)

    server_name = client.server if client and client.server else "the server"
    await client.add_message(
        text=f"Welcome to {server_name}: {trailing if trailing else ''}",
        color_pair_id=client.ui.colors["system_message"],
        context_name="Status",
    )
    logger.info(f"Received RPL_WELCOME (001). Nick confirmed as {confirmed_nick}.")

    if hasattr(client, "event_manager") and client.event_manager:
        client.event_manager.dispatch_client_registered(
            nick=confirmed_nick,
            server_message=(trailing if trailing else ""),
            raw_line=raw_line,
        )

    if hasattr(client, "registration_handler") and client.registration_handler:
        await client.registration_handler.on_welcome_received(confirmed_nick)
    else:
        logger.error(
            "RPL_WELCOME received, but client.registration_handler is not initialized."
        )
        await client.add_message(
            text="Error: Registration handler not ready for RPL_WELCOME.",
            color_pair_id=client.ui.colors["error_message"],
            context_name="Status",
        )


async def _handle_rpl_notopic(
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
    await client.add_message(
        text=f"No topic set for {channel_name}.",
        color_pair_id=client.ui.colors["system_message"],
        context_name=channel_name,
    )


async def _handle_rpl_topic(
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
    await client.add_message(
        text=f"Topic for {channel_name}: {topic_text}",
        color_pair_id=client.ui.colors["system_message"],
        context_name=channel_name,
    )


async def _handle_generic_numeric(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
    generic_numeric_msg: str,
):
    """Handles generic or unassigned numeric replies."""
    await client.add_message(
        text=f"[{parsed_msg.command}] {generic_numeric_msg}",
        color_pair_id=client.ui.colors["system_message"],
        context_name="Status",
    )
    logger.debug(
        f"Received unhandled/generic numeric {parsed_msg.command}: {raw_line.strip()} (Generic msg: {generic_numeric_msg})"
    )
    # RPL_ENDOFMOTD (376) logic is now in _handle_motd_and_server_info


async def _handle_rpl_namreply(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_NAMREPLY (353)."""
    logger.debug(f"_handle_rpl_namreply: Called for raw_line='{raw_line.strip()}', display_params={display_params}, trailing='{trailing}'")
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


async def _handle_rpl_endofnames(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles RPL_ENDOFNAMES (366)."""
    logger.debug(f"_handle_rpl_endofnames: Called for raw_line='{raw_line.strip()}', display_params={display_params}, trailing='{trailing}'")
    channel_ended = display_params[0] if display_params else "Unknown Channel"
    ctx_for_endofnames = client.context_manager.get_context(channel_ended)
    if ctx_for_endofnames and ctx_for_endofnames.type == "channel":
        user_count = len(ctx_for_endofnames.users)
        logger.debug(f"NumericHandler._handle_rpl_endofnames: Context for {channel_ended} found. User count: {user_count}. Current join_status: {ctx_for_endofnames.join_status.name if ctx_for_endofnames.join_status else 'N/A'}")

        if ctx_for_endofnames.join_status in [
            ChannelJoinStatus.SELF_JOIN_RECEIVED,
            ChannelJoinStatus.JOIN_COMMAND_SENT,
            ChannelJoinStatus.PENDING_INITIAL_JOIN,
        ]:
            ctx_for_endofnames.join_status = ChannelJoinStatus.FULLY_JOINED
            logger.info(
                f"NumericHandler._handle_rpl_endofnames: RPL_ENDOFNAMES for {channel_ended}. Set join_status to FULLY_JOINED. User count: {user_count}."
            )
            conn_info = client.state_manager.get_connection_info()
            if conn_info:
                conn_info.currently_joined_channels.add(channel_ended)
                client.state_manager.set("connection_info", conn_info)
                logger.info(
                    f"_handle_rpl_endofnames: Added {channel_ended} to tracked client.currently_joined_channels."
                )
            logger.debug(f"_handle_rpl_endofnames: About to call client.handle_channel_fully_joined for {channel_ended}")
            await client.handle_channel_fully_joined(channel_ended)
            logger.debug(f"_handle_rpl_endofnames: Finished calling client.handle_channel_fully_joined for {channel_ended}")
        elif ctx_for_endofnames.join_status == ChannelJoinStatus.NOT_JOINED:
            logger.info(
                f"_handle_rpl_endofnames: RPL_ENDOFNAMES for {channel_ended} (status NOT_JOINED). User count: {user_count}. Not changing join status from this alone, as we weren't in a pending join state."
            )

            logger.info(
                f"[ENDOFNAMES_DEBUG] About to add user count message for {channel_ended}. Current user count: {user_count}"
            )
            await client.add_message(
                text=f"Users in {channel_ended}: {user_count}",
                color_pair_id=client.ui.colors.get("system", 0),
                context_name=channel_ended,
            )
            logger.info(
                f"[ENDOFNAMES_DEBUG] Finished adding user count message for {channel_ended}."
            )
    else:
        logger.warning(
            f"RPL_ENDOFNAMES for {channel_ended}, but context not found or not a channel."
        )
        await client.add_message(
            text=f"End of names for {channel_ended} (context not found).",
            color_pair_id=client.ui.colors.get("error", 0),
            context_name="Status",
        )


async def _handle_err_nosuchnick(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles ERR_NOSUCHNICK (401)."""
    nosuch_nick = display_params[0] if display_params else "nick"
    await client.add_message(
        text=f"No such nick: {nosuch_nick}",
        color_pair_id=client.ui.colors["error_message"],
        context_name=client.context_manager.active_context_name or "Status",
    )


async def _handle_err_nosuchchannel(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles ERR_NOSUCHCHANNEL (403)."""
    channel_name = display_params[0] if display_params else "channel"
    await client.add_message(
        text=f"Channel {channel_name} does not exist or is invalid.",
        color_pair_id=client.ui.colors["error_message"],
        context_name="Status",
    )
    failed_join_ctx = client.context_manager.get_context(channel_name)
    if failed_join_ctx and failed_join_ctx.type == "channel":
        failed_join_ctx.join_status = ChannelJoinStatus.JOIN_FAILED
        logger.debug(
            f"Set join_status to JOIN_FAILED for {channel_name} due to ERR_NOSUCHCHANNEL."
        )
    conn_info = client.state_manager.get_connection_info()
    if conn_info:
        conn_info.currently_joined_channels.discard(channel_name)
        client.state_manager.set("connection_info", conn_info)
    logger.warning(
        f"ERR_NOSUCHCHANNEL (403) for {channel_name}. Marked as JOIN_FAILED and removed from tracked channels."
    )
    # Check if this was an initial join attempt
    normalized_channel_name = client.context_manager._normalize_context_name(channel_name)
    if hasattr(client, 'pending_initial_joins') and normalized_channel_name in client.pending_initial_joins:
        client.pending_initial_joins.remove(normalized_channel_name)
        logger.info(f"ERR_NOSUCHCHANNEL: Removed '{normalized_channel_name}' from pending_initial_joins due to join failure. Remaining: {client.pending_initial_joins}")
        if not client.pending_initial_joins and hasattr(client, 'all_initial_joins_processed') and not client.all_initial_joins_processed.is_set():
            logger.info("ERR_NOSUCHCHANNEL: All initial join attempts (including this failure) processed. Setting all_initial_joins_processed event.")
            client.all_initial_joins_processed.set()


async def _handle_err_channel_join_group(
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
    await client.add_message(
        text=f"Cannot join {channel_name}: {reason}. {trailing if trailing else ''}",
        color_pair_id=client.ui.colors["error_message"],
        context_name="Status",
    )
    failed_join_ctx = client.context_manager.get_context(channel_name)
    if failed_join_ctx and failed_join_ctx.type == "channel":
        failed_join_ctx.join_status = ChannelJoinStatus.JOIN_FAILED
        logger.debug(
            f"Set join_status to JOIN_FAILED for {channel_name} due to {code}."
        )
    conn_info = client.state_manager.get_connection_info()
    if conn_info:
        conn_info.currently_joined_channels.discard(channel_name)
        client.state_manager.set("connection_info", conn_info)
    logger.warning(
        f"Channel join error {code} for {channel_name}. Marked as JOIN_FAILED."
    )
    # Check if this was an initial join attempt
    normalized_channel_name = client.context_manager._normalize_context_name(channel_name)
    if hasattr(client, 'pending_initial_joins') and normalized_channel_name in client.pending_initial_joins:
        client.pending_initial_joins.remove(normalized_channel_name)
        logger.info(f"ERR_CHANNEL_JOIN_GROUP ({code}): Removed '{normalized_channel_name}' from pending_initial_joins due to join failure. Remaining: {client.pending_initial_joins}")
        if not client.pending_initial_joins and hasattr(client, 'all_initial_joins_processed') and not client.all_initial_joins_processed.is_set():
            logger.info(f"ERR_CHANNEL_JOIN_GROUP ({code}): All initial join attempts (including this failure) processed. Setting all_initial_joins_processed event.")
            client.all_initial_joins_processed.set()


async def _handle_err_nicknameinuse(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles ERR_NICKNAMEINUSE (433)."""
    failed_nick = display_params[0] if display_params else client.nick
    logger.warning(f"ERR_NICKNAMEINUSE (433) for {failed_nick}: {raw_line.strip()}")
    await client.add_message(
        text=f"Nickname {failed_nick} is already in use.",
        color_pair_id=client.ui.colors["error_message"],
        context_name="Status",
    )

    conn_info = client.state_manager.get_connection_info()
    if not conn_info:
        logger.error("Cannot handle nick collision: no connection info.")
        return

    if (
        client.last_attempted_nick_change is not None
        and client.last_attempted_nick_change.lower() == failed_nick.lower()
    ):
        logger.info(
            f"ERR_NICKNAMEINUSE for user-attempted nick {failed_nick}. Resetting client.last_attempted_nick_change."
        )
        client.last_attempted_nick_change = None
        return  # Don't auto-retry for user-initiated nick changes

    is_our_nick_colliding = conn_info.nick and conn_info.nick.lower() == failed_nick.lower()

    if is_our_nick_colliding and not client.network_handler.is_handling_nick_collision:
        if hasattr(client, "registration_handler") and client.registration_handler:
            current_nick_for_logic = conn_info.nick
            initial_nick_for_logic = client.registration_handler.initial_nick

            # Generate a new nickname with a random suffix
            base_nick = initial_nick_for_logic
            # Ensure base_nick is not too long before adding suffix
            if len(base_nick) > 5: # Leave room for a 4-char random suffix
                base_nick = base_nick[:5]
            random_suffix = ''.join(random.choices('0123456789abcdef', k=4))
            new_try_nick = f"{base_nick}-{random_suffix}"

            # Ensure the new nickname isn't too long (IRC limit is typically 9 chars)
            if len(new_try_nick) > 9:
                new_try_nick = new_try_nick[:9]

            logger.info(f"Nickname {failed_nick} in use, trying {new_try_nick}.")
            await client.add_message(
                text=f"Trying {new_try_nick} instead.", color_pair_id=client.ui.colors["system_message"], context_name="Status"
            )

            client.network_handler.is_handling_nick_collision = True
            client.network_handler.send_raw(f"NICK {new_try_nick}")
            conn_info.nick = new_try_nick
            client.state_manager.set("connection_info", conn_info)
            client.registration_handler.update_nick_for_registration(new_try_nick)

            # Also update the nickname in state.json
            client.state_manager._save_state()
        else:
            logger.warning(
                "ERR_NICKNAMEINUSE for our nick, but no registration_handler to manage retry."
            )
    elif is_our_nick_colliding and client.network_handler.is_handling_nick_collision:
        logger.info(
            f"ERR_NICKNAMEINUSE for {failed_nick}, but already handling a nick collision. Manual /NICK needed if this fails."
        )
        await client.add_message(
            text="Nickname collision handling failed. Please use /nick to choose a different nickname.",
            color_pair_id=client.ui.colors["error_message"],
            context_name="Status",
        )
        client.network_handler.is_handling_nick_collision = False


async def _handle_sasl_loggedin_success(
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
        await client.add_message(
            text=f"SASL Success ({code}), but authenticator missing.",
            color_pair_id=client.ui.colors["error_message"],
            context_name="Status",
        )


async def _handle_sasl_mechanisms(
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
    await client.add_message(
        text=f"SASL: Server mechanisms: {mechanisms}", color_pair_id=client.ui.colors["system_message"], context_name="Status"
    )


async def _handle_sasl_fail_errors(
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
        await client.add_message(
            text=f"SASL Error ({code}): {reason}, but authenticator missing.",
            color_pair_id=client.ui.colors["error_message"],
            context_name="Status",
        )


async def _handle_err_saslalready(
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
        await client.add_message(
            text=f"SASL Warning (907): {reason}, but authenticator missing.",
            color_pair_id=client.ui.colors["system_message"],
            context_name="Status",
        )


async def _handle_rpl_whoisuser(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
    active_context_name: str, # Added
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
    await client.add_message(text=message_to_add, color_pair_id=client.ui.colors["system_message"], context_name=active_context_name) # Changed context


async def _handle_rpl_endofwhois(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
    active_context_name: str, # Added
):
    """Handles RPL_ENDOFWHOIS (318)."""
    original_params = parsed_msg.params
    whois_nick = original_params[0] if len(original_params) > 0 else "N/A"
    await client.add_message(
        text=f"[WHOIS {whois_nick}] End of WHOIS.", color_pair_id=client.ui.colors["system_message"], context_name=active_context_name # Changed context
    )


async def _handle_motd_and_server_info(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
    generic_numeric_msg: str,
):
    """Handles MOTD and various server information numerics."""
    await client.add_message(
        text=f"[{parsed_msg.command}] {generic_numeric_msg}",
        color_pair_id=client.ui.colors["system_message"],
        context_name="Status",
    )
    # Specifically set the end_of_motd_received event if this is RPL_ENDOFMOTD
    if parsed_msg.command == "376": # RPL_ENDOFMOTD
        if hasattr(client, "registration_handler") and client.registration_handler:
            if not client.registration_handler.end_of_motd_received.is_set():
                logger.info("RPL_ENDOFMOTD (376) received via _handle_motd_and_server_info, setting event.")
                client.registration_handler.end_of_motd_received.set()
                logger.info("RPL_ENDOFMOTD (376): Directly triggering post-MOTD actions from _handle_motd_and_server_info.")
                asyncio.create_task(client.registration_handler.execute_post_motd_actions())
            else:
                logger.debug("RPL_ENDOFMOTD (376) received via _handle_motd_and_server_info, but event was already set.")
        else:
            logger.warning("RPL_ENDOFMOTD (376) received via _handle_motd_and_server_info, but no registration_handler.")


async def _handle_rpl_whoreply(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
    active_context_name: str, # Added
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
    await client.add_message(text=message_to_add, color_pair_id=client.ui.colors["system_message"], context_name=active_context_name) # Changed context


async def _handle_rpl_endofwho(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
    active_context_name: str, # Added
):
    """Handles RPL_ENDOFWHO (315). <client_nick> <name> :End of WHO list"""
    # display_params[0] is <name> (the target of the WHO)
    who_target = display_params[0] if display_params else "N/A"
    message_to_add = (
        f"[WHO {who_target}] {trailing if trailing else 'End of WHO list.'}"
    )
    await client.add_message(text=message_to_add, color_pair_id=client.ui.colors["system_message"], context_name=active_context_name) # Changed context


async def _handle_rpl_whowasuser(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
    active_context_name: str, # Added
):
    """Handles RPL_WHOWASUSER (314). <client_nick> <nick> <user> <host> * :<real_name>"""
    # display_params[0] is <nick>
    # display_params[1] is <user>
    # display_params[2] is <host>
    # display_params[3] is <host>

    nick = display_params[0] if len(display_params) > 0 else "N/A"
    user = display_params[1] if len(display_params) > 1 else "N/A"
    host = display_params[2] if len(display_params) > 2 else "N/A"
    real_name = trailing if trailing else "N/A"

    message_to_add = f"[WHOWAS {nick}] User: {user}@{host} Realname: {real_name}"
    await client.add_message(text=message_to_add, color_pair_id=client.ui.colors["system_message"], context_name=active_context_name) # Changed context


async def _handle_rpl_endofwhowas(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
    active_context_name: str, # Added
):
    """Handles RPL_ENDOFWHOWAS (369). <client_nick> <nick> :End of WHOWAS list"""
    # display_params[0] is <nick>
    whowas_nick = display_params[0] if display_params else "N/A"
    message_to_add = (
        f"[WHOWAS {whowas_nick}] {trailing if trailing else 'End of WHOWAS list.'}"
    )
    await client.add_message(text=message_to_add, color_pair_id=client.ui.colors["system_message"], context_name=active_context_name) # Changed context


async def _handle_rpl_liststart(
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

    await client.add_message(text=message, color_pair_id=client.ui.colors["system_message"], context_name=target_context_name)


async def _handle_rpl_list(
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
    await client.add_message(text=message_to_add, color_pair_id=client.ui.colors["system_message"], context_name=target_context_name)


async def _handle_rpl_listend(
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
            await client.add_message(
                text="--- End of /list results ---",
                color_pair_id=client.ui.colors["system_message"],
                context_name=target_context_name_for_message,
            )
            await client.add_message(
                text="This is a temporary window. Type /close or press Ctrl+W to close it.",
                color_pair_id=client.ui.colors["system_message"],
                context_name=target_context_name_for_message,
            )
        elif list_ctx:
            logger.warning(
                f"RPL_LISTEND: active_list_context_name '{active_list_ctx_name}' exists but is not type 'list_results' (type: {list_ctx.type}). Defaulting to Status for end message."
            )
            await client.add_message(
                text=f"[List] {trailing if trailing else 'End of channel list.'}",
                color_pair_id=client.ui.colors["system_message"],
                context_name="Status",
            )
        else:
            logger.warning(
                f"RPL_LISTEND: active_list_context_name '{active_list_ctx_name}' not found. Defaulting to Status for end message."
            )
            await client.add_message(
                text=f"[List] {trailing if trailing else 'End of channel list.'}",
                color_pair_id=client.ui.colors["system_message"],
                context_name="Status",
            )
    else:  # No active_list_context_name was set, so message definitely goes to Status
        await client.add_message(
            text=f"[List] {trailing if trailing else 'End of channel list.'}",
            color_pair_id=client.ui.colors["system_message"],
            context_name="Status",
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


async def _handle_err_erroneusnickname(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles ERR_ERRONEUSNICKNAME (432)."""
    # <client> <nick> :Erroneous nickname
    failed_nick = display_params[0] if display_params else "nick"
    error_reason = trailing if trailing else "Erroneous nickname"
    logger.warning(f"ERR_ERRONEUSNICKNAME (432) for {failed_nick}: {error_reason}")
    await client.add_message(
        text=f"Cannot change nick to {failed_nick}: {error_reason}",
        color_pair_id=client.ui.colors["error_message"],
        context_name="Status",
    )
    if (
        client.last_attempted_nick_change is not None
        and client.last_attempted_nick_change.lower() == failed_nick.lower()
    ):
        logger.info(
            f"ERR_ERRONEUSNICKNAME for user-attempted nick {failed_nick}. Resetting client.last_attempted_nick_change."
        )
        client.last_attempted_nick_change = None


async def _handle_err_nickcollision(
    client,
    parsed_msg: IRCMessage,
    raw_line: str,
    display_params: list,
    trailing: Optional[str],
):
    """Handles ERR_NICKCOLLISION (436)."""
    # <client> <nick> :Nickname collision
    collided_nick = display_params[0] if display_params else "nick"
    error_reason = trailing if trailing else "Nickname collision"
    logger.warning(f"ERR_NICKCOLLISION (436) for {collided_nick}: {error_reason}")
    await client.add_message(
        text=f"Cannot change nick to {collided_nick}: {error_reason}. The server killed your nick, attempting to restore to {client.registration_handler.initial_nick}.",
        color_pair_id=client.ui.colors["error_message"],
        context_name="Status",
    )
    if (
        client.last_attempted_nick_change is not None
        and client.last_attempted_nick_change.lower() == collided_nick.lower()
    ):
        logger.info(
            f"ERR_NICKCOLLISION for user-attempted nick {collided_nick}. Resetting client.last_attempted_nick_change."
        )
        client.last_attempted_nick_change = None

    # Attempt to reclaim initial nick or a variant if collision occurs
    conn_info = client.state_manager.get_connection_info()
    if conn_info and conn_info.nick.lower() == collided_nick.lower():  # If our current nick is the one that collided
        client.network_handler.send_raw(f"NICK {client.registration_handler.initial_nick}") # Use registration_handler.initial_nick
        await client.add_message(
            text=f"Attempting to restore nick to {client.registration_handler.initial_nick}.", # Use registration_handler.initial_nick
            color_pair_id=client.ui.colors["system_message"],
            context_name="Status",
        )


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
    376: _handle_motd_and_server_info, # Ensure 376 uses _handle_motd_and_server_info
    401: _handle_err_nosuchnick,
    403: _handle_err_nosuchchannel,
    432: _handle_err_erroneusnickname,  # Added
    433: _handle_err_nicknameinuse,
    436: _handle_err_nickcollision,  # Added
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


async def _handle_numeric_command(client, parsed_msg: IRCMessage, raw_line: str, active_context_name: str): # Added active_context_name
    """Handles numeric commands."""
    code = int(parsed_msg.command)
    params = parsed_msg.params
    trailing = parsed_msg.trailing

    conn_info = client.state_manager.get_connection_info()
    current_nick = conn_info.nick if conn_info else ""

    # Remove client's nick from params for display purposes
    display_params = [p for p in params if p.lower() != current_nick.lower()]

    # Dispatch RAW_IRC_NUMERIC event
    if hasattr(client, "event_manager") and client.event_manager:
        client.event_manager.dispatch_raw_irc_numeric(
            numeric=code,
            source=parsed_msg.prefix,
            params_list=list(params),
            display_params_list=list(display_params),
            trailing=trailing,
            tags=parsed_msg.get_all_tags(),
            raw_line=raw_line,
        )

    # Define generic_msg here so it's always available
    generic_msg = trailing if trailing else " ".join(display_params)

    # Handle specific numeric replies
    handler = NUMERIC_HANDLERS.get(code)
    if handler:
        if handler:
            # Determine which arguments to pass based on the handler's expected signature.
            # This is a more robust way to handle varying argument counts for handlers.
            # We'll assume handlers either take 5 args (client, parsed_msg, raw_line, display_params, trailing)
            # or 6 args (adding active_context_name or generic_numeric_msg).

            # List handlers that expect active_context_name (6 arguments)
            handlers_with_active_context = {
                _handle_rpl_whoisuser, _handle_rpl_endofwhois,
                _handle_rpl_whoreply, _handle_rpl_endofwho,
                _handle_rpl_whowasuser, _handle_rpl_endofwhowas,
                _handle_rpl_liststart, _handle_rpl_list, _handle_rpl_listend,
                _handle_err_nosuchnick, _handle_err_nosuchchannel, _handle_err_channel_join_group,
                _handle_err_nicknameinuse, _handle_err_erroneusnickname, _handle_err_nickcollision,
                _handle_sasl_loggedin_success, _handle_sasl_mechanisms, _handle_sasl_fail_errors, _handle_err_saslalready,
            }

            # List handlers that expect generic_numeric_msg (6 arguments)
            handlers_with_generic_msg = {
                _handle_motd_and_server_info, _handle_generic_numeric
            }

            # List handlers that expect only 5 arguments
            handlers_with_5_args = {
                _handle_rpl_welcome, _handle_rpl_notopic, _handle_rpl_topic, _handle_rpl_namreply, _handle_rpl_endofnames
            }

            if handler in handlers_with_active_context:
                await handler(client, parsed_msg, raw_line, display_params, trailing, active_context_name)
            elif handler in handlers_with_generic_msg:
                await handler(client, parsed_msg, raw_line, display_params, trailing, generic_msg)
            elif handler in handlers_with_5_args:
                await handler(client, parsed_msg, raw_line, display_params, trailing)
            else:
                # Fallback for any handler not explicitly categorized, should ideally not be hit
                logger.warning(f"Numeric handler {handler.__name__} not explicitly categorized by argument count. Falling back to generic numeric handler.")
                await _handle_generic_numeric(client, parsed_msg, raw_line, display_params, trailing, generic_msg)
        else:
            # Generic numeric reply if no specific handler is found in NUMERIC_HANDLERS
            await _handle_generic_numeric(
                client, parsed_msg, raw_line, display_params, trailing, generic_msg
            )
