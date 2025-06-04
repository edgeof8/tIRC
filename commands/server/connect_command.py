import logging
from typing import TYPE_CHECKING, Optional, Tuple

from config import DEFAULT_PORT, DEFAULT_SSL_PORT
from context_manager import ChannelJoinStatus # For _reset_client_contexts

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.server.connect")

COMMAND_DEFINITIONS = [
    {
        "name": "connect",
        "handler": "handle_connect_command",
        "help": {
            "usage": "/connect <server[:port]> [ssl|nossl]",
            "description": "Connects to the specified IRC server. Uses SSL if 'ssl' is provided, or attempts to infer from port.",
            "aliases": []
        }
    }
]

def _parse_connect_args_internal(client: "IRCClient_Logic", args_str: str) -> Optional[Tuple[str, int, bool]]:
    conn_args = args_str.split()
    if not conn_args:
        help_data = client.script_manager.get_help_text_for_command("connect")
        usage_msg = (
            help_data["help_text"]
            if help_data
            else "Usage: /connect <server[:port]> [ssl|nossl]"
        )
        client.add_message(
            usage_msg,
            "error",
            context_name=client.context_manager.active_context_name,
        )
        return None

    new_server_host, port_str_arg = conn_args[0], None
    new_port: Optional[int] = None
    # Default to current SSL setting if not specified otherwise
    new_ssl: bool = client.use_ssl if client.use_ssl is not None else False


    if ":" in new_server_host:
        new_server_host, port_str_arg = new_server_host.split(":", 1)
        try:
            new_port = int(port_str_arg)
        except ValueError:
            client.add_message(
                f"Invalid port: {port_str_arg}",
                "error",
                context_name=client.context_manager.active_context_name,
            )
            return None

    if len(conn_args) > 1:
        ssl_arg = conn_args[1].lower()
        if ssl_arg == "ssl":
            new_ssl = True
        elif ssl_arg == "nossl":
            new_ssl = False
        # If something else, new_ssl retains its current/default value

    if new_port is None:
        new_port = DEFAULT_SSL_PORT if new_ssl else DEFAULT_PORT

    return new_server_host, new_port, new_ssl

def _reset_client_contexts(client: "IRCClient_Logic"):
    """
    Resets client contexts for a new server connection.
    Copied from ServerCommandsHandler._reset_contexts_for_new_connection.
    """
    logger.debug("Clearing existing contexts for new server connection (connect_command).")
    status_context = client.context_manager.get_context("Status")
    current_status_msgs = list(status_context.messages) if status_context else []
    status_scroll_offset = (
        status_context.scrollback_offset
        if status_context and hasattr(status_context, "scrollback_offset")
        else 0
    )

    client.context_manager.contexts.clear()
    client.context_manager.create_context("Status", context_type="status")
    new_status_context = client.context_manager.get_context("Status")
    if new_status_context:
        for msg_tuple in current_status_msgs: # msg_tuple is (text, color_attr)
            new_status_context.add_message(msg_tuple[0], msg_tuple[1])
        if hasattr(new_status_context, "scrollback_offset"):
            new_status_context.scrollback_offset = status_scroll_offset
    logger.debug(
        f"Restored {len(current_status_msgs)} messages to 'Status' context (connect_command)."
    )

    # Re-create contexts for initial channels if they exist on the client logic
    # This assumes client.initial_channels_list is relevant for a raw /connect.
    # Typically, /connect might not auto-join channels unless they are part of a saved server config
    # that /connect might implicitly load if no server arg is given (not current logic).
    # For a direct /connect <host>, initial_channels_list might be empty or from a previous config.
    # For simplicity, we'll mirror the original logic which re-adds initial_channels_list.
    if client.initial_channels_list:
        for ch_name in client.initial_channels_list:
            client.context_manager.create_context(
                ch_name,
                context_type="channel",
                initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN,
            )
            logger.debug(
                f"Re-created initial channel context: {ch_name} with PENDING_INITIAL_JOIN (connect_command)."
            )

    if client.initial_channels_list:
        client.context_manager.set_active_context(
            client.initial_channels_list[0]
        )
    else:
        client.context_manager.set_active_context("Status")
    logger.info(
        f"Set active context to '{client.context_manager.active_context_name}' after server change (connect_command)."
    )
    client.ui_needs_update.set()


def handle_connect_command(client: "IRCClient_Logic", args_str: str):
    parsed_args = _parse_connect_args_internal(client, args_str)
    if parsed_args is None:
        return

    new_server_host, new_port, new_ssl = parsed_args

    if client.network_handler.connected:
        client.network_handler.disconnect_gracefully("Changing servers via /connect")

    # Update client's main connection parameters
    client.server = new_server_host
    client.port = new_port
    client.use_ssl = new_ssl
    # Note: /connect doesn't inherently change client.nick, client.password etc.
    # It primarily establishes a new connection. Server-specific profiles are handled by /server.

    client.add_message(
        f"Attempting to connect to: {client.server}:{client.port} (SSL: {client.use_ssl})",
        "system", # Semantic color key
        context_name="Status",
    )
    logger.info(
        f"Attempting new connection via /connect: {client.server}:{client.port} (SSL: {client.use_ssl})"
    )

    _reset_client_contexts(client) # Use the local helper

    # This will also re-initialize CAP, SASL, Registration handlers based on new connection params
    client.network_handler.update_connection_params(
        server=client.server,
        port=client.port,
        use_ssl=client.use_ssl,
        # channels_to_join will be handled by RegistrationHandler based on client.initial_channels_list
        # or if specific channels are passed to update_connection_params (not typical for raw /connect)
    )
    # The network_handler.start() or its internal reconnect logic will pick up the new params.
    # If not already running, ensure it starts. If it was running, disconnect_gracefully + update_connection_params
    # should trigger a reconnect with new params.
    if not client.network_handler.network_thread or not client.network_handler.network_thread.is_alive():
         client.network_handler.start()
