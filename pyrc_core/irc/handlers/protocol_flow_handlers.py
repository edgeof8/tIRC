import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    from pyrc_core.irc.irc_message import IRCMessage

logger = logging.getLogger("pyrc.handlers.protocol_flow")

async def handle_cap_message(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
    """Handles CAP messages."""
    params = parsed_msg.params
    trailing = parsed_msg.trailing
    cap_subcommand = params[1] if len(params) > 1 else None
    capabilities_str = trailing if trailing else (params[2] if len(params) > 2 else "")

    if not cap_subcommand:
        logger.warning(f"Malformed CAP message received: {raw_line.strip()}")
        await client.add_message(
            f"[Malformed CAP] {raw_line.strip()}",
            client.ui.colors["error"],
            context_name="Status",
        )
        return

    logger.debug(
        f"Received CAP {cap_subcommand} with capabilities: '{capabilities_str}'"
    )

    if not hasattr(client, "cap_negotiator") or not client.cap_negotiator:
        logger.error(
            "CAP message received, but client.cap_negotiator is not initialized."
        )
        await client.add_message(
            f"[CAP Error] Negotiator not ready for {cap_subcommand}",
            client.ui.colors["error"],
            context_name="Status", # Corrected from "Status" to context_name="Status"
        )
        return

    if cap_subcommand == "LS":
        await client.cap_negotiator.on_cap_ls_received(capabilities_str)
    elif cap_subcommand == "ACK":
        await client.cap_negotiator.on_cap_ack_received(capabilities_str)
    elif cap_subcommand == "NAK":
        await client.cap_negotiator.on_cap_nak_received(capabilities_str)
    elif cap_subcommand == "NEW":
        await client.cap_negotiator.on_cap_new_received(capabilities_str)
    elif cap_subcommand == "DEL":
        await client.cap_negotiator.on_cap_del_received(capabilities_str)
    else:
        await client.add_message(
            f"[CAP] Unknown subcommand: {cap_subcommand} {capabilities_str}",
            client.ui.colors["system"],
            context_name="Status",
        )

# protocol_flow_handlers.py
async def handle_ping_command(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
    """Handles PING command."""
    ping_payload = parsed_msg.trailing
    if ping_payload is None:
        if parsed_msg.params: # If there are params, the first one is the target
            ping_payload = parsed_msg.params[0]
        else: # No trailing, no params (e.g., server sends just "PING")
            ping_payload = client.server if client and client.server else "heartbeat" # Fallback
            logger.warning(f"PING received with no parameters. Responding with PONG targeting '{ping_payload}'")

    if ping_payload is None: # Should be extremely rare with the fallback
        ping_payload = "unexpected_ping_payload_issue"
        logger.error("PING payload was unexpectedly None even after fallback. Using generic token.")

    await client.network_handler.send_raw(f"PONG :{ping_payload}")
    logger.debug(f"Responded to PING with PONG targeting '{ping_payload}'")

async def handle_authenticate_command(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
    """Handles AUTHENTICATE command."""
    # raw_line is 'line' from the original handle_server_message context
    payload = parsed_msg.params[0] if parsed_msg.params else ""
    if not hasattr(client, "sasl_authenticator") or not client.sasl_authenticator:
        logger.error(
            "AUTHENTICATE received, but client.sasl_authenticator is not initialized."
        )
        await client.add_message(
            f"[SASL Error] Authenticator not ready for AUTHENTICATE {payload}",
            client.ui.colors["error"],
            context_name="Status", # Corrected
        )
        return

    if payload == "+":
        logger.info(f"SASL: Received AUTHENTICATE + challenge. Raw: {raw_line.strip()}")
        await client.sasl_authenticator.on_authenticate_challenge_received(payload)
    else:
        logger.warning(
            f"SASL: Received AUTHENTICATE with payload other than '+': '{payload}'. This is unusual. Relying on numerics for outcome. Raw: {raw_line.strip()}"
        )

async def handle_unknown_command(client: "IRCClient_Logic", parsed_msg: "IRCMessage", raw_line: str):
    """Handles unknown/unsupported commands."""
    # raw_line is 'line' from the original handle_server_message context
    cmd = parsed_msg.command # Get command from parsed_msg
    display_p_parts = list(parsed_msg.params)
    if parsed_msg.trailing is not None:
        display_p_parts.append(f":{parsed_msg.trailing}")
    display_p = " ".join(display_p_parts)

    display_src = (
        parsed_msg.source_nick
        if parsed_msg.source_nick
        else (parsed_msg.prefix if parsed_msg.prefix else "SERVER")
    )

    logger.warning(
        f"Unhandled command '{cmd.upper()}' from '{display_src}': {display_p}. Raw: {raw_line.strip()}"
    )
    await client.add_message(
        f"[{cmd.upper()}] From: {display_src}, Data: {display_p}".strip(),
        client.ui.colors["system"],
        context_name="Status",
    )
