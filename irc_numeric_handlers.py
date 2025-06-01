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
    confirmed_nick = params[0] if params else client.nick # Default to current client.nick if 001 has no target

    # Update client's main nick attribute
    if client.nick != confirmed_nick:
        logger.info(f"RPL_WELCOME: Nick confirmed by server as '{confirmed_nick}', was '{client.nick}'. Updating client.nick.")
        client.nick = confirmed_nick
    # Ensure client.nick is set even if it matched or was defaulted
    elif not client.nick and confirmed_nick:
        client.nick = confirmed_nick


    client.add_message(
        f"Welcome to {client.server}: {trailing if trailing else ''}",
        client.ui.colors["system"],
        context_name="Status",
    )
    logger.info(f"Received RPL_WELCOME (001). Nick confirmed as {client.nick}.")

    # Notify RegistrationHandler about RPL_WELCOME
    if hasattr(client, 'registration_handler') and client.registration_handler:
        client.registration_handler.on_welcome_received(confirmed_nick)
    else:
        logger.error("RPL_WELCOME received, but client.registration_handler is not initialized.")
        client.add_message("Error: Registration handler not ready for RPL_WELCOME.", client.ui.colors["error"], "Status")

    # The old logic for CAP confirmation, channel joins, and NickServ IDENTIFY
    # is now managed by RegistrationHandler.on_welcome_received() and its interaction
    # with CapNegotiator.

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

    # Nick collision logic needs to be coordinated with RegistrationHandler
    # as it manages the NICK/USER sequence.
    is_our_nick_colliding = client.nick and client.nick.lower() == failed_nick.lower()

    # Only attempt auto-nick change if it's our current nick that collided,
    # and we are not already in a nick collision handling loop initiated by NetworkHandler,
    # and CAP negotiation (which might include initial NICK/USER) is considered complete or underway.
    # The `cap_negotiator.initial_cap_flow_complete_event.is_set()` or
    # `registration_handler.nick_user_sent` might be better checks.
    # For simplicity, we rely on `NetworkHandler.is_handling_nick_collision`
    # and if the registration handler exists to potentially update the nick it will use.

    if is_our_nick_colliding and not client.network.is_handling_nick_collision:
        if hasattr(client, 'registration_handler') and client.registration_handler:
            # Determine new nick based on client's initial_nick and current_nick
            # This logic might be better placed within RegistrationHandler or a shared utility
            current_nick_for_logic = client.nick # The nick that just failed
            initial_nick_for_logic = client.initial_nick # The original configured nick

            if current_nick_for_logic.lower() == initial_nick_for_logic.lower():
                new_try_nick = f"{initial_nick_for_logic}_"
            else:
                if current_nick_for_logic.endswith("_"): new_try_nick = f"{current_nick_for_logic[:-1]}1"
                elif current_nick_for_logic[-1].isdigit(): new_try_nick = f"{current_nick_for_logic[:-1]}{int(current_nick_for_logic[-1])+1}"
                else: new_try_nick = f"{current_nick_for_logic}_"

            logger.info(f"Nickname {failed_nick} in use, trying {new_try_nick}.")
            client.add_message(f"Trying {new_try_nick} instead.", client.ui.colors["system"], "Status")

            client.network.is_handling_nick_collision = True # Prevent immediate re-loops from NetworkHandler
            client.network.send_raw(f"NICK {new_try_nick}")
            client.nick = new_try_nick # Update client's current nick
            client.registration_handler.update_nick_for_registration(new_try_nick) # Inform reg handler
        else:
            logger.warning("ERR_NICKNAMEINUSE for our nick, but no registration_handler to manage retry.")
    elif is_our_nick_colliding and client.network.is_handling_nick_collision:
        logger.info(f"ERR_NICKNAMEINUSE for {failed_nick}, but already handling a nick collision. Manual /NICK needed if this fails.")

def _handle_sasl_loggedin_success(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles RPL_LOGGEDIN (900) and RPL_SASLSUCCESS (903)."""
    code = int(parsed_msg.command)
    account_name = "your account"
    original_params = parsed_msg.params
    if code == 900 and len(original_params) > 1:
        account_name = original_params[1]

    success_msg = f"Successfully logged in as {account_name} ({code})." if code == 900 else f"SASL authentication successful ({code})."

    # Messages are now handled by SaslAuthenticator
    # client.add_message(f"SASL: {success_msg}", client.ui.colors["system"], "Status")
    if hasattr(client, 'sasl_authenticator') and client.sasl_authenticator:
        client.sasl_authenticator.on_sasl_result_received(True, success_msg)
    else:
        logger.error(f"SASL Success ({code}), but no sasl_authenticator on client.")
        client.add_message(f"SASL Success ({code}), but authenticator missing.", client.ui.colors["error"], "Status")


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
    # Messages are now handled by SaslAuthenticator
    # client.add_message(f"SASL Error: {reason}", client.ui.colors["error"], "Status")
    if hasattr(client, 'sasl_authenticator') and client.sasl_authenticator:
        client.sasl_authenticator.on_sasl_result_received(False, reason)
    else:
        logger.error(f"SASL Failure ({code}), but no sasl_authenticator on client.")
        client.add_message(f"SASL Error ({code}): {reason}, but authenticator missing.", client.ui.colors["error"], "Status")

def _handle_err_saslalready(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str]):
    """Handles ERR_SASLALREADY (907)."""
    reason = trailing if trailing else "You have already authenticated (907)"
    # Messages are now handled by SaslAuthenticator
    # client.add_message(f"SASL Warning: {reason}", client.ui.colors["warning"], "Status")
    if hasattr(client, 'sasl_authenticator') and client.sasl_authenticator:
        # If server says already authenticated, treat it as a success for our flow.
        client.sasl_authenticator.on_sasl_result_received(True, reason)
    else:
        logger.error("ERR_SASLALREADY (907), but no sasl_authenticator on client.")
        client.add_message(f"SASL Warning (907): {reason}, but authenticator missing.", client.ui.colors["warning"], "Status")

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
