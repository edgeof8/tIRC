# irc_numeric_handlers.py
import logging
from typing import Optional

# Assuming IRCMessage will be passed and its structure is known.
# For explicit type hinting, you might add:
# from irc_message import IRCMessage
# However, to keep this module focused on handlers and avoid circular dependency
# if irc_message might ever need something from here (unlikely for this structure),
# we'll rely on the client object passing a correctly structured parsed_msg.
# For now, we will add it as it's good practice and the dependency is one-way.
from irc_message import IRCMessage
from context_manager import ChannelJoinStatus

logger = logging.getLogger("pyrc.protocol") # Using the same logger as irc_protocol for now

# --- Individual Numeric Handlers ---
def _handle_rpl_welcome(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles RPL_WELCOME (001)."""
    params = parsed_msg.params # Use original params for nick confirmation
    confirmed_nick = params[0] if params else client.nick
    if client.nick != confirmed_nick:
        logger.info(f"RPL_WELCOME: Nick confirmed by server as '{confirmed_nick}', was '{client.nick}'. Updating.")
        client.nick = confirmed_nick
    else:
        client.nick = confirmed_nick # Ensure client.nick is set even if it matched

    client.add_message(
        f"Welcome to {client.server}: {trailing if trailing else ''}",
        client.ui.colors["system"],
        context_name="Status",
    )
    logger.info(f"Received RPL_WELCOME (001). Nick confirmed as {client.nick}.")
    client.handle_cap_end_confirmation()

    if client.cap_negotiation_finished_event.wait(timeout=5.0):
        logger.info("CAP negotiation finished event is set. Proceeding with post-001 actions.")

        channels_to_join_now = client.network.channels_to_join_on_connect[:] # Operate on a copy
        if channels_to_join_now:
            logger.info(f"Post-001: Processing auto-join for channels: {', '.join(channels_to_join_now)}")
            for channel_name in channels_to_join_now:
                ctx = client.context_manager.get_context(channel_name)
                if not ctx:
                    client.context_manager.create_context(
                        channel_name,
                        context_type="channel",
                        initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN
                    )
                    ctx = client.context_manager.get_context(channel_name)

                if ctx and ctx.type == "channel":
                    ctx.join_status = ChannelJoinStatus.PENDING_INITIAL_JOIN
                    logger.debug(f"Set join_status to PENDING_INITIAL_JOIN for auto-join channel {channel_name}")

                client.command_handler.process_user_command(f"/join {channel_name}")
            client.network.channels_to_join_on_connect.clear()
        else:
            logger.info("No channels queued for auto-join post-001.")

        if client.nickserv_password and not ("sasl" in client.enabled_caps and client.sasl_authentication_succeeded is True):
            logger.info("Identifying with NickServ.")
            client.command_handler.process_user_command(f"/msg NickServ IDENTIFY {client.nickserv_password}")
        elif "sasl" in client.enabled_caps and client.sasl_authentication_succeeded is True:
            logger.info("SASL auth successful, no NickServ IDENTIFY needed.")
        elif client.nickserv_password:
             logger.info("SASL not enabled, NickServ password exists. Sending IDENTIFY.")
             client.command_handler.process_user_command(f"/msg NickServ IDENTIFY {client.nickserv_password}")
    else:
        logger.warning("Timed out waiting for CAP negotiation after 001. Joins/NickServ might be delayed/fail.")
        client.add_message("Warning: CAP negotiation timed out. Features might be delayed.", client.ui.colors["error"], "Status")
        if client.initial_channels_list and not client.network.channels_to_join_on_connect:
            logger.warning("CAP timeout fallback: joining initial_channels_list.")
            for channel_name in client.initial_channels_list: # Fallback
                ctx = client.context_manager.get_context(channel_name)
                if not ctx:
                    client.context_manager.create_context(
                        channel_name,
                        context_type="channel",
                        initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN
                    )
                    ctx = client.context_manager.get_context(channel_name)
                if ctx and ctx.type == "channel":
                    ctx.join_status = ChannelJoinStatus.PENDING_INITIAL_JOIN
                client.command_handler.process_user_command(f"/join {channel_name}")

def _handle_rpl_notopic(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles RPL_NOTOPIC (331)."""
    channel_name = display_params[0] if display_params else "channel"
    client.context_manager.create_context(channel_name, context_type="channel")
    context = client.context_manager.get_context(channel_name)
    if context: context.topic = None
    client.add_message(f"No topic set for {channel_name}.", client.ui.colors["system"], context_name=channel_name)

def _handle_rpl_topic(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles RPL_TOPIC (332)."""
    channel_name = display_params[0] if display_params else "channel"
    topic_text = trailing if trailing else ""
    client.context_manager.create_context(channel_name, context_type="channel")
    client.context_manager.update_topic(channel_name, topic_text)
    client.add_message(f"Topic for {channel_name}: {topic_text}", client.ui.colors["system"], context_name=channel_name)

def _handle_generic_numeric(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str], generic_numeric_msg: str):
    """Handles generic or unassigned numeric replies."""
    client.add_message(f"[{parsed_msg.command}] {generic_numeric_msg}", client.ui.colors["system"], "Status")
    logger.debug(f"Received unhandled/generic numeric {parsed_msg.command}: {raw_line.strip()} (Generic msg: {generic_numeric_msg})")

def _handle_rpl_namreply(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles RPL_NAMREPLY (353)."""
    channel_in_reply = display_params[1] if len(display_params) > 1 else None
    if channel_in_reply:
        created_for_namreply = client.context_manager.create_context(
            channel_in_reply,
            context_type="channel",
            initial_join_status_for_channel=ChannelJoinStatus.NOT_JOINED
        )
        if created_for_namreply:
             logger.debug(f"Ensured channel context exists for NAMREPLY: {channel_in_reply} (created with NOT_JOINED)")

        target_ctx_for_names = client.context_manager.get_context(channel_in_reply)
        if target_ctx_for_names:
            if target_ctx_for_names.join_status == ChannelJoinStatus.PENDING_INITIAL_JOIN or \
               target_ctx_for_names.join_status == ChannelJoinStatus.JOIN_COMMAND_SENT:
                target_ctx_for_names.join_status = ChannelJoinStatus.SELF_JOIN_RECEIVED
                logger.debug(f"NAMREPLY for {channel_in_reply}: Updated join_status to SELF_JOIN_RECEIVED")

            nicks_on_list = trailing.split() if trailing else []
            for nick_entry in nicks_on_list:
                prefix_char = ""
                actual_nick = nick_entry
                if nick_entry.startswith(("@", "+", "%", "&", "~")):
                    prefix_char = nick_entry[0]
                    actual_nick = nick_entry[1:]
                client.context_manager.add_user(channel_in_reply, actual_nick, prefix_char)
        else: logger.warning(f"RPL_NAMREPLY: Context {channel_in_reply} not found after create attempt.")
    else: logger.warning(f"RPL_NAMREPLY for unknown context. Raw: {raw_line.strip()}")

def _handle_rpl_endofnames(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles RPL_ENDOFNAMES (366)."""
    channel_ended = display_params[0] if display_params else "Unknown Channel"
    ctx_for_endofnames = client.context_manager.get_context(channel_ended)
    if ctx_for_endofnames and ctx_for_endofnames.type == "channel":
        user_count = len(ctx_for_endofnames.users)

        if ctx_for_endofnames.join_status in [ChannelJoinStatus.SELF_JOIN_RECEIVED, ChannelJoinStatus.JOIN_COMMAND_SENT, ChannelJoinStatus.PENDING_INITIAL_JOIN]:
            ctx_for_endofnames.join_status = ChannelJoinStatus.FULLY_JOINED
            logger.info(f"RPL_ENDOFNAMES for {channel_ended}. Set join_status to FULLY_JOINED. User count: {user_count}.")
            if channel_ended not in client.currently_joined_channels:
                client.currently_joined_channels.add(channel_ended)
                logger.info(f"Added {channel_ended} to tracked client.currently_joined_channels.")
            client.handle_channel_fully_joined(channel_ended)
        elif ctx_for_endofnames.join_status == ChannelJoinStatus.NOT_JOINED:
             logger.info(f"RPL_ENDOFNAMES for {channel_ended} (status NOT_JOINED). User count: {user_count}. Not changing join status from this alone, as we weren't in a pending join state.")

        client.add_message(f"Users in {channel_ended}: {user_count}", client.ui.colors["system"], context_name=channel_ended)
    else:
        logger.warning(f"RPL_ENDOFNAMES for {channel_ended}, but context not found or not a channel.")
        client.add_message(f"End of names for {channel_ended} (context not found).", client.ui.colors["error"], "Status")

def _handle_err_nosuchnick(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles ERR_NOSUCHNICK (401)."""
    nosuch_nick = display_params[0] if display_params else "nick"
    client.add_message(f"No such nick: {nosuch_nick}", client.ui.colors["error"], client.context_manager.active_context_name or "Status")

def _handle_err_nosuchchannel(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles ERR_NOSUCHCHANNEL (403)."""
    channel_name = display_params[0] if display_params else "channel"
    client.add_message(f"Channel {channel_name} does not exist or is invalid.", client.ui.colors["error"], "Status")
    failed_join_ctx = client.context_manager.get_context(channel_name)
    if failed_join_ctx and failed_join_ctx.type == "channel":
        failed_join_ctx.join_status = ChannelJoinStatus.JOIN_FAILED
        logger.debug(f"Set join_status to JOIN_FAILED for {channel_name} due to ERR_NOSUCHCHANNEL.")
    client.currently_joined_channels.discard(channel_name)
    logger.warning(f"ERR_NOSUCHCHANNEL (403) for {channel_name}. Marked as JOIN_FAILED and removed from tracked channels.")

def _handle_err_channel_join_group(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
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
    client.add_message(f"Cannot join {channel_name}: {reason}. {trailing if trailing else ''}", client.ui.colors["error"], "Status")
    failed_join_ctx = client.context_manager.get_context(channel_name)
    if failed_join_ctx and failed_join_ctx.type == "channel":
        failed_join_ctx.join_status = ChannelJoinStatus.JOIN_FAILED
        logger.debug(f"Set join_status to JOIN_FAILED for {channel_name} due to {code}.")
    client.currently_joined_channels.discard(channel_name)
    logger.warning(f"Channel join error {code} for {channel_name}. Marked as JOIN_FAILED.")

def _handle_err_nicknameinuse(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles ERR_NICKNAMEINUSE (433)."""
    failed_nick = display_params[0] if display_params else client.nick
    logger.warning(f"ERR_NICKNAMEINUSE (433) for {failed_nick}: {raw_line.strip()}")
    client.add_message(f"Nickname {failed_nick} is already in use.", client.ui.colors["error"], "Status")

    if client.nick and client.nick.lower() == failed_nick.lower() and \
       not client.network.is_handling_nick_collision and \
       client.cap_negotiation_finished_event.is_set():

        if client.nick.lower() == client.initial_nick.lower():
             new_try_nick = f"{client.initial_nick}_"
        else:
             if client.nick.endswith("_"): new_try_nick = f"{client.nick[:-1]}1"
             elif client.nick[-1].isdigit(): new_try_nick = f"{client.nick[:-1]}{int(client.nick[-1])+1}"
             else: new_try_nick = f"{client.nick}_"

        logger.info(f"Nickname {failed_nick} in use, trying {new_try_nick}.")
        client.add_message(f"Trying {new_try_nick} instead.", client.ui.colors["system"], "Status")
        client.network.is_handling_nick_collision = True
        client.network.send_raw(f"NICK {new_try_nick}")
        client.nick = new_try_nick

def _handle_sasl_loggedin_success(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles RPL_LOGGEDIN (900) and RPL_SASLSUCCESS (903)."""
    code = int(parsed_msg.command)
    account_name = "your account"
    original_params = parsed_msg.params
    if code == 900 and len(original_params) > 1:
        account_name = original_params[1]

    success_msg = f"Successfully logged in as {account_name} ({code})." if code == 900 else f"SASL authentication successful ({code})."

    logger.info(f"SASL: {success_msg} Raw: {raw_line.strip()}")
    client.add_message(f"SASL: {success_msg}", client.ui.colors["system"], "Status")
    client.handle_sasl_success(success_msg)

def _handle_sasl_mechanisms(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles RPL_SASLMECHS (902) or ERR_SASLMECHS (908)."""
    code = int(parsed_msg.command)
    mechanisms = trailing if trailing else "unknown"
    logger.info(f"SASL: Server indicated mechanisms: {mechanisms} (Code: {code}). Raw: {raw_line.strip()}")
    client.add_message(f"SASL: Server mechanisms: {mechanisms}", client.ui.colors["system"], "Status")

def _handle_sasl_fail_errors(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles ERR_SASLFAIL (904), ERR_SASLTOOLONG (905), ERR_SASLABORTED (906)."""
    code = int(parsed_msg.command)
    default_reasons = {
        904: "SASL authentication failed",
        905: "SASL message too long / Base64 decoding error",
        906: "SASL authentication aborted by server or client",
    }
    reason = trailing if trailing else default_reasons.get(code, f"SASL error ({code})")
    logger.warning(f"SASL: Authentication failed ({code}). Reason: {reason}. Raw: {raw_line.strip()}")
    client.add_message(f"SASL Error: {reason}", client.ui.colors["error"], "Status")
    client.handle_sasl_failure(reason)

def _handle_err_saslalready(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles ERR_SASLALREADY (907)."""
    reason = trailing if trailing else "You have already authenticated (907)"
    logger.warning(f"SASL: Already authenticated (907). Reason: {reason}. Raw: {raw_line.strip()}")
    client.add_message(f"SASL Warning: {reason}", client.ui.colors["warning"], "Status")
    if not client.is_sasl_completed() or client.sasl_authentication_succeeded is not True:
        logger.error("SASL: Server says already authenticated, but client state disagrees. Forcing success state.")
        client.handle_sasl_success(reason)

def _handle_rpl_whoisuser(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles RPL_WHOISUSER (311)."""
    original_params = parsed_msg.params
    whois_nick = original_params[0] if len(original_params) > 0 else "N/A"
    user_info = original_params[1] if len(original_params) > 1 else "N/A"
    host_info = original_params[2] if len(original_params) > 2 else "N/A"
    realname = trailing if trailing else "N/A"
    message_to_add = f"[WHOIS {whois_nick}] User: {user_info}@{host_info} Realname: {realname}"
    client.add_message(message_to_add, client.ui.colors["system"], "Status")

def _handle_rpl_endofwhois(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles RPL_ENDOFWHOIS (318)."""
    original_params = parsed_msg.params
    whois_nick = original_params[0] if len(original_params) > 0 else "N/A"
    client.add_message(f"[WHOIS {whois_nick}] End of WHOIS.", client.ui.colors["system"], "Status")

def _handle_motd_and_server_info(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str], generic_numeric_msg: str):
    """Handles MOTD and various server information numerics."""
    client.add_message(f"[{parsed_msg.command}] {generic_numeric_msg}", client.ui.colors["system"], "Status")


# --- Dispatcher for Numeric Handlers ---
NUMERIC_HANDLERS = {
    1: _handle_rpl_welcome,
    251: _handle_motd_and_server_info, # RPL_LUSERCLIENT
    252: _handle_motd_and_server_info, # RPL_LUSEROP
    253: _handle_motd_and_server_info, # RPL_LUSERUNKNOWN
    254: _handle_motd_and_server_info, # RPL_LUSERCHANNELS
    255: _handle_motd_and_server_info, # RPL_LUSERME
    265: _handle_motd_and_server_info, # RPL_LOCALUSERS
    266: _handle_motd_and_server_info, # RPL_GLOBALUSERS
    311: _handle_rpl_whoisuser,
    318: _handle_rpl_endofwhois,
    331: _handle_rpl_notopic,
    332: _handle_rpl_topic,
    353: _handle_rpl_namreply,
    366: _handle_rpl_endofnames,
    372: _handle_motd_and_server_info, # RPL_MOTD
    375: _handle_motd_and_server_info, # RPL_MOTDSTART
    376: _handle_motd_and_server_info, # RPL_ENDOFMOTD
    401: _handle_err_nosuchnick,
    403: _handle_err_nosuchchannel,
    433: _handle_err_nicknameinuse,
    471: _handle_err_channel_join_group, # ERR_CHANNELISFULL
    473: _handle_err_channel_join_group, # ERR_INVITEONLYCHAN
    474: _handle_err_channel_join_group, # ERR_BANNEDFROMCHAN
    475: _handle_err_channel_join_group, # ERR_BADCHANNELKEY
    900: _handle_sasl_loggedin_success,  # RPL_LOGGEDIN
    902: _handle_sasl_mechanisms,        # RPL_SASLMECHS
    903: _handle_sasl_loggedin_success,  # RPL_SASLSUCCESS
    904: _handle_sasl_fail_errors,       # ERR_SASLFAIL
    905: _handle_sasl_fail_errors,       # ERR_SASLTOOLONG
    906: _handle_sasl_fail_errors,       # ERR_SASLABORTED
    907: _handle_err_saslalready,        # ERR_SASLALREADY
    908: _handle_sasl_mechanisms,        # ERR_SASLMECHS (deprecated by CAP LS)
}


def _handle_numeric_command(client, parsed_msg: IRCMessage, raw_line: str):
    """Handles numeric IRC replies by dispatching to specific handlers."""
    code = int(parsed_msg.command)
    params = parsed_msg.params # Original params
    trailing = parsed_msg.trailing
    client_nick_lower = client.nick.lower() if client.nick else ""

    # display_params are params excluding the client's own nick if it's the first one
    display_params = list(params) # Make a mutable copy
    if params and params[0].lower() == client_nick_lower:
        display_params = params[1:]

    # generic_numeric_msg is for logging or fallback display
    generic_numeric_msg_parts = []
    if display_params: generic_numeric_msg_parts.extend(display_params)
    if trailing: generic_numeric_msg_parts.append(f":{trailing}")
    generic_numeric_msg = " ".join(generic_numeric_msg_parts)

    handler = NUMERIC_HANDLERS.get(code)
    if handler:
        # Pass generic_numeric_msg only to handlers that expect it (MOTD and fallback)
        if handler in [_handle_motd_and_server_info, _handle_generic_numeric]:
             handler(client, parsed_msg, raw_line, display_params, trailing, generic_numeric_msg)
        else:
            handler(client, parsed_msg, raw_line, display_params, trailing)
    else:
        # Fallback to generic handler if no specific handler is found in the dispatcher
        _handle_generic_numeric(client, parsed_msg, raw_line, display_params, trailing, generic_numeric_msg)
