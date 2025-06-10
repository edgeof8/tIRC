import logging
from typing import TYPE_CHECKING, Optional, List, Dict, Any # Ensure all needed types are here

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    from pyrc_core.irc.irc_message import IRCMessage

logger = logging.getLogger("pyrc.handlers.state_change")

async def handle_nick_message(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
    """Handles NICK messages."""
    old_nick = parsed_msg.source_nick
    new_nick = parsed_msg.trailing
    source_full_ident = parsed_msg.prefix

    if not old_nick or not new_nick:
        logger.warning(f"Malformed NICK message: {raw_line.strip()}")
        return

    # Check if this is our own nick change
    conn_info = client.state_manager.get_connection_info()
    is_our_nick_change = old_nick.lower() == (conn_info.nick.lower() if conn_info else "")

    if is_our_nick_change:
        # Update our nick
        conn_info = client.state_manager.get_connection_info()
        if not conn_info:
            logger.error("Cannot handle nick change - no connection info")
            return

        old_nick_val = conn_info.nick
        conn_info.nick = new_nick
        await client.state_manager.set_connection_info(conn_info)
        logger.info(f"Our nick changed from {old_nick_val} to {new_nick}")

        # Update nick in all contexts
        for context in client.context_manager.contexts.values():
            if context.type == "channel":
                if old_nick_val in context.users:
                    context.users[new_nick] = context.users.pop(old_nick_val)
                    if old_nick_val in context.user_prefixes:
                        context.user_prefixes[new_nick] = context.user_prefixes.pop(
                            old_nick_val
                        )

        # Add message to status
        await client.add_message(
            text=f"Nick changed from {old_nick_val} to {new_nick}",
            color_attr=client.ui.colors["system"],
            context_name="Status",
        )

        conn_info = client.state_manager.get_connection_info()
        if conn_info and conn_info.last_attempted_nick_change is not None and \
           conn_info.last_attempted_nick_change.lower() == new_nick.lower():
            logger.info(f"Successful user-initiated nick change to {new_nick} confirmed.")
            conn_info.last_attempted_nick_change = None
            await client.state_manager.set_connection_info(conn_info)

        # Dispatch CLIENT_NICK_CHANGED event
        if hasattr(client, "event_manager") and client.event_manager:
            await client.event_manager.dispatch_client_nick_changed(
                old_nick=old_nick_val, new_nick=new_nick, raw_line=raw_line
            )
    else:
        # Handle other users' nick changes
        for context in client.context_manager.contexts.values():
            if context.type == "channel":
                if old_nick in context.users:
                    context.users[new_nick] = context.users.pop(old_nick)
                    if old_nick in context.user_prefixes:
                        context.user_prefixes[new_nick] = context.user_prefixes.pop(
                            old_nick
                        )

                    # Add message to channel
                    await client.add_message(
                        text=f"{old_nick} is now known as {new_nick}",
                        color_attr=client.ui.colors["system"],
                        context_name=context.name,
                    )

    # Dispatch general NICK event
    if hasattr(client, "event_manager") and client.event_manager:
        await client.event_manager.dispatch_nick(
            old_nick=old_nick, new_nick=new_nick,
            userhost=source_full_ident, # Ensure this is the correct var
            is_self=is_our_nick_change, raw_line=raw_line
        )
async def handle_mode_message(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
    """Handles MODE messages."""
    source_nick = parsed_msg.source_nick
    source_full_ident = parsed_msg.prefix
    params = parsed_msg.params

    if not params:
        logger.warning(f"MODE without parameters: {raw_line.strip()}")
        return

    target = params[0]
    mode_string = params[1] if len(params) > 1 else ""
    mode_params = params[2:] if len(params) > 2 else []

    # Parse mode changes
    parsed_modes: List[Dict[str, Any]] = []
    current_operation: Optional[str] = None
    param_index = 0

    for char in mode_string:
        if char in ("+", "-"):
            current_operation = char
            continue

        mode_info: Dict[str, Any] = {"operation": current_operation, "mode": char, "param": None}

        # Check if this mode requires a parameter
        # Common modes requiring parameters: b (ban), k (key/password), l (limit), v (voice), h (halfop), o (op), a (admin), q (owner)
        # This list might need adjustment based on specific IRCd features.
        if char in ("b", "k", "l", "v", "h", "o", "a", "q"): # Extended list based on common usage
            if param_index < len(mode_params):
                mode_info["param"] = mode_params[param_index]
                param_index += 1

        parsed_modes.append(mode_info)

    # Handle channel modes
    if target.startswith(("#", "&", "!", "+")): # Common channel prefixes
        context = client.context_manager.get_context(target)
        if context and context.type == "channel":
            # Update channel modes
            for mode in parsed_modes:
                if mode["operation"] == "+":
                    if mode["mode"] not in context.modes:
                        context.modes.append(mode["mode"])
                elif mode["operation"] == "-":
                    try:
                        context.modes.remove(mode["mode"])
                    except ValueError:
                        pass  # Mode not in list, ignore

            # Format mode string for display
            mode_str_display = mode_string
            if mode_params:
                mode_str_display += " " + " ".join(mode_params)

            # Add message to channel
            await client.add_message(
                text=f"Mode {target} [{mode_str_display}] by {source_nick}",
                color_attr=client.ui.colors["system"],
                context_name=target,
            )

            # Dispatch CHANNEL_MODE_APPLIED event
            if hasattr(client, "event_manager") and client.event_manager:
                await client.event_manager.dispatch_channel_mode_applied(
                    channel=target, setter_nick=source_nick, setter_userhost=source_full_ident,
                    mode_changes=parsed_modes, current_channel_modes=list(context.modes),
                    raw_line=raw_line
                )

    # Handle user modes
    conn_info = client.state_manager.get_connection_info()
    if conn_info and target.lower() == conn_info.nick.lower():
        # Update user modes
        for mode in parsed_modes:
            if mode["operation"] == "+":
                current_modes = client.state_manager.get("user_modes", [])
                if mode["mode"] not in current_modes:
                    client.state_manager.set("user_modes", current_modes + [mode["mode"]]) # type: ignore[reportUnusedCoroutine]
            elif mode["operation"] == "-":
                current_modes = client.state_manager.get("user_modes", [])
                if mode["mode"] in current_modes:
                    client.state_manager.set("user_modes", [m for m in current_modes if m != mode["mode"]]) # type: ignore[reportUnusedCoroutine]

        # Format mode string for display
        mode_str_display = mode_string
        if mode_params:
            mode_str_display += " " + " ".join(mode_params)

        # Add message to status
        await client.add_message(
            text=f"Mode {conn_info.nick} [{mode_str_display}] by {source_nick}",
            color_attr=client.ui.colors["system"],
            context_name="Status",
        )

    # Dispatch general MODE event
    if hasattr(client, "event_manager") and client.event_manager:
        await client.event_manager.dispatch_mode(
            target_name=target, setter_nick=source_nick, setter_userhost=source_full_ident,
            mode_string=mode_string, mode_params=mode_params, parsed_modes=parsed_modes,
            raw_line=raw_line
        )
async def handle_topic_command_event(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
    """Handles TOPIC command messages."""
    # raw_line is 'line' from the original handle_server_message context
    channel = parsed_msg.params[0] if parsed_msg.params else None
    new_topic = parsed_msg.trailing

    if channel:
        if new_topic is not None:
            message = f"Topic for {channel} changed to: {new_topic}"
            if parsed_msg.source_nick:
                message = f"{parsed_msg.source_nick} changed topic for {channel} to: {new_topic}"
        else:
            message = f"Topic for {channel} cleared."

        client.context_manager.update_topic(
            channel, new_topic if new_topic is not None else ""
        )
        await client.add_message(
            text=message, color_attr=client.ui.colors["system"], context_name=channel
        )

        # Dispatch TOPIC event
        if hasattr(client, "event_manager") and client.event_manager:
            await client.event_manager.dispatch_topic(
                nick=parsed_msg.source_nick, userhost=parsed_msg.prefix,
                channel=channel, topic=(new_topic if new_topic is not None else ""),
                raw_line=raw_line # Pass raw_line here
            )
    else:
        logger.warning(f"Malformed TOPIC message (no channel): {raw_line.strip()}")

async def handle_chghost_command_event(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
    """Handles CHGHOST command messages."""
    # raw_line is 'line' from the original handle_server_message context
    src_nick = parsed_msg.source_nick
    new_ident = parsed_msg.params[0] if len(parsed_msg.params) > 0 else None # Check param length
    new_host = parsed_msg.params[1] if len(parsed_msg.params) > 1 else None # Check param length, CHGHOST has user and host in params

    # Note: Some servers might send CHGHOST with new_ident in params[0] and new_host in params[1]
    # Others might use source_nick for the user and params[0] for new_user, params[1] for new_host
    # The original code used src_nick, params[0] (as new_ident) and trailing (as new_host)
    # Let's adjust based on common CHGHOST format: USER newuser newhost
    # If parsed_msg.params has two elements, they are likely new_ident and new_host
    # If it has one, it might be just new_host and ident is implied from source_nick
    # For now, sticking to a more common interpretation:
    # Params: <user> <newhost> (src_nick is the target user, params[0] is new ident, params[1] is new host)
    # Or: <newident> <newhost> (src_nick is the target user, params[0] is new ident, params[1] is new host)
    # The original code had:
    # new_ident = parsed_msg.params[0] if parsed_msg.params else ""
    # new_host = parsed_msg.trailing if parsed_msg.trailing else ""
    # This seems less common for CHGHOST.
    # Reverting to a structure that matches the original parsing intention for CHGHOST if it was:
    # :nick!olduser@oldhost CHGHOST newuser newhost
    # Then params[0] = newuser, params[1] = newhost
    # If it was :nick!olduser@oldhost CHGHOST newhost (and newuser is taken from nick)
    # This needs clarification based on server behavior.
    # For now, let's assume params are [new_ident, new_host] if present.

    # Corrected logic based on typical CHGHOST: :nick!oldident@oldhost CHGHOST newident newhost
    # source_nick is the user whose host is changing.
    # params[0] is the new ident (username part).
    # params[1] is the new hostname.

    if len(parsed_msg.params) >= 2:
        new_ident = parsed_msg.params[0]
        new_host = parsed_msg.params[1]
    else:
        logger.warning(f"Malformed CHGHOST message (not enough params): {raw_line.strip()}")
        # Optionally, could try to infer from trailing if that's a server variant
        # For now, strict parsing based on common format.
        return


    if src_nick and new_ident and new_host:
        logger.info(f"Host change for {src_nick}: {new_ident}@{new_host}")
        # Update user's ident and host in all contexts where they exist
        # This part is tricky as we don't store full user@host per user in channel lists directly.
        # The event dispatch is the primary action here.
        # UI update might rely on seeing the new prefix in subsequent messages.
        for ctx_name, ctx_obj in client.context_manager.contexts.items():
            if ctx_obj.type == "channel" and src_nick in ctx_obj.users:
                # The user's presence in the channel is already tracked.
                # Actual update of userhost might happen implicitly via future messages
                # or a WHOIS/WHO call if needed.
                pass

        # Dispatch CHGHOST event
        if hasattr(client, "event_manager") and client.event_manager:
            await client.event_manager.dispatch_chghost(
                nick=src_nick, new_ident=new_ident, new_host=new_host,
                old_userhost=parsed_msg.prefix, # old userhost is prefix before change
                raw_line=raw_line # Pass raw_line here
            )
    else:
        # This condition might be hit if params were not as expected.
        logger.warning(f"Could not process CHGHOST due to missing info (src_nick, new_ident, or new_host): {raw_line.strip()}")
