# tirc_core/irc/handlers/protocol_flow_handlers.py
import logging
from typing import TYPE_CHECKING, Optional, Dict, Any

from tirc_core.irc.irc_message import IRCMessage
from tirc_core.state_manager import ConnectionState # Import ConnectionState

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.handlers.protocol_flow")


async def _handle_ping(
    client: "IRCClient_Logic",
    parsed_msg: IRCMessage,
    raw_line: str,
    params: list, # PING usually has no params, server name is in trailing
    trailing: Optional[str],
):
    """Handles PING messages from the server."""
    # Server name is usually in trailing, but can be in params[0] for some servers
    server_name = trailing if trailing else (params[0] if params else "UnknownServer")
    await client.network_handler.send_raw(f"PONG :{server_name}")
    logger.debug(f"Responded to PING from {server_name} with PONG.")


async def _handle_pong(
    client: "IRCClient_Logic",
    parsed_msg: IRCMessage,
    raw_line: str,
    params: list,
    trailing: Optional[str],
):
    """Handles PONG messages (usually in response to our PING or server's keep-alive)."""
    # Typically, no action is needed client-side for PONG unless tracking latency.
    pong_origin = parsed_msg.prefix if parsed_msg.prefix else "UnknownOrigin"
    pong_message = trailing if trailing else (params[0] if params else "")
    logger.debug(f"Received PONG from {pong_origin} with message: {pong_message}")


async def _handle_error(
    client: "IRCClient_Logic",
    parsed_msg: IRCMessage,
    raw_line: str,
    params: list, # ERROR usually has no params, reason is in trailing
    trailing: Optional[str],
):
    """Handles ERROR messages from the server (usually indicates disconnection)."""
    error_reason = trailing if trailing else "Unknown error"
    logger.error(f"Received ERROR from server: {error_reason}. Raw: {raw_line.strip()}")
    await client.add_message(
        text=f"Server ERROR: {error_reason}",
        color_pair_id=client.ui.colors.get("error_message", 0),
        context_name="Status",
    )
    # Server is likely to close connection after ERROR.
    # Set state to ERROR and let NetworkHandler's loop detect closure.
    await client.state_manager.set_connection_state(ConnectionState.ERROR, error_reason)
    # No need to call disconnect_gracefully here, as server will close.
    # NetworkHandler's loop will handle the actual disconnection detection.


async def _handle_cap(
    client: "IRCClient_Logic",
    parsed_msg: IRCMessage,
    raw_line: str,
    params: list, # Params: <subcommand> [*] <capabilities>
    trailing: Optional[str], # Can also contain capabilities for LS/NEW
):
    """Handles CAP (Capability Negotiation) messages."""
    if not client.cap_negotiator:
        logger.warning("Received CAP message, but CapNegotiator is not initialized.")
        return

    # Params usually: target subcommand capabilities
    # Example: :server CAP * LS :sasl multi-prefix ...
    # Example: :server CAP yournick ACK :sasl
    # params[0] is usually target (our nick or '*')
    # params[1] is subcommand (LS, ACK, NAK, NEW, DEL)
    # params[2] (or trailing) is the capabilities string

    subcommand = params[1].upper() if len(params) > 1 else "UNKNOWN_SUBCOMMAND"
    capabilities_str = trailing if trailing else (params[2] if len(params) > 2 else "")

    logger.info(f"Received CAP {subcommand} with capabilities: '{capabilities_str}'")

    if subcommand == "LS":
        await client.cap_negotiator.handle_cap_ls(capabilities_str)
    elif subcommand == "ACK":
        await client.cap_negotiator.handle_cap_ack(capabilities_str)
    elif subcommand == "NAK":
        await client.cap_negotiator.handle_cap_nak(capabilities_str)
    elif subcommand == "NEW":
        # Server is announcing new capabilities it supports
        new_caps = set(capabilities_str.split())
        client.cap_negotiator.supported_caps.update(new_caps)
        logger.info(f"Server announced NEW CAPs: {new_caps}. Updated supported_caps.")
        # TODO: Potentially re-evaluate desired_caps and send CAP REQ if new ones are desired.
    elif subcommand == "DEL":
        # Server is announcing capabilities it no longer supports
        del_caps = set(capabilities_str.split())
        client.cap_negotiator.supported_caps.difference_update(del_caps)
        client.cap_negotiator.enabled_caps.difference_update(del_caps)
        logger.info(f"Server announced DEL CAPs: {del_caps}. Updated supported_caps and enabled_caps.")
    else:
        logger.warning(f"Unknown CAP subcommand: {subcommand}. Raw: {raw_line.strip()}")

    # Dispatch CAP event for scripts
    if hasattr(client, "event_manager") and client.event_manager:
        event_data = {
            "subcommand": subcommand,
            "capabilities": capabilities_str,
            "current_supported_caps": list(client.cap_negotiator.supported_caps),
            "current_enabled_caps": list(client.cap_negotiator.enabled_caps),
            "tags": parsed_msg.get_all_tags(),
            "raw_line": raw_line
        }
        # Use a specific event name like "SERVER_CAP_LS", "SERVER_CAP_ACK", etc.
        # or a generic "SERVER_CAP" with subcommand in data.
        await client.event_manager.dispatch_event(f"SERVER_CAP_{subcommand}", event_data, raw_line)


async def _handle_authenticate(
    client: "IRCClient_Logic",
    parsed_msg: IRCMessage,
    raw_line: str,
    params: list, # Params[0] is usually the payload or '+'
    trailing: Optional[str], # Can also be payload
):
    """Handles AUTHENTICATE messages during SASL."""
    if not client.sasl_authenticator:
        logger.warning("Received AUTHENTICATE message, but SaslAuthenticator is not initialized.")
        return

    payload = params[0] if params else (trailing if trailing else "")
    logger.info(f"Received AUTHENTICATE with payload: '{payload[:30]}...'") # Log truncated payload

    await client.sasl_authenticator.handle_authenticate_challenge(payload)
