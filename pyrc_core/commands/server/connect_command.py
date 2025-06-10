import logging
from typing import TYPE_CHECKING, Optional, Tuple

from pyrc_core.app_config import DEFAULT_PORT, DEFAULT_SSL_PORT
from pyrc_core.state_manager import ConnectionInfo # Import ConnectionInfo

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

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

async def _parse_connect_args_internal(client: "IRCClient_Logic", args_str: str) -> Optional[Tuple[str, int, bool]]:
    conn_args = args_str.split()
    if not conn_args:
        help_data = client.script_manager.get_help_text_for_command("connect")
        usage_msg = (
            help_data["help_text"]
            if help_data
            else "Usage: /connect <server[:port]> [ssl|nossl]"
        )
        await client.add_message(
            usage_msg,
            client.ui.colors["error"],
            context_name=client.context_manager.active_context_name or "Status",
        )
        return None

    new_server_host, port_str_arg = conn_args[0], None
    new_port: Optional[int] = None
    # Default to current SSL setting if not specified otherwise
    # client.use_ssl returns a string representation of bool or None, convert to bool
    new_ssl: bool = client.use_ssl.lower() == 'true' if client.use_ssl is not None else False


    if ":" in new_server_host:
        new_server_host, port_str_arg = new_server_host.split(":", 1)
        try:
            new_port = int(port_str_arg)
        except ValueError:
            await client.add_message(
                f"Invalid port: {port_str_arg}",
                client.ui.colors["error"],
                context_name=client.context_manager.active_context_name or "Status",
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

async def handle_connect_command(client: "IRCClient_Logic", args_str: str):
    parsed_args = await _parse_connect_args_internal(client, args_str)
    if parsed_args is None:
        return

    new_server_host, new_port, new_ssl = parsed_args

    if client.network_handler.connected:
        await client.network_handler.disconnect_gracefully("Changing servers via /connect")

    # Create a temporary ConnectionInfo object and set it in the StateManager
    # This will allow IRCClient_Logic's properties and network_handler to pick up the new values
    conn_info = client.state_manager.get_connection_info()
    current_nick = conn_info.nick if conn_info else "PyRC" # Use existing nick or default

    temp_conn_info = ConnectionInfo(
        server=new_server_host,
        port=new_port,
        ssl=new_ssl,
        nick=current_nick, # Keep current nick for /connect
        username=current_nick,
        realname=current_nick,
        auto_connect=False, # This is a manual connect, not auto
        initial_channels=[], # /connect doesn't specify initial channels
        desired_caps=[] # /connect doesn't specify caps
    )

    if not client.state_manager.set_connection_info(temp_conn_info):
        await client.add_message(f"Failed to set connection info for {new_server_host}:{new_port}. Validation failed.", client.ui.colors["error"], context_name="Status")
        logger.error(f"Failed to set connection info for {new_server_host}:{new_port}. Validation failed.")
        return

    await client.add_message(
        f"Attempting to connect to: {client.server}:{client.port} (SSL: {client.use_ssl})", # Use properties
        client.ui.colors["system"],
        context_name="Status",
    )
    logger.info(
        f"Attempting new connection via /connect: {client.server}:{client.port} (SSL: {client.use_ssl})" # Use properties
    )

    # Ensure connection_info is not None before passing to establish_connection
    final_conn_info = client.state_manager.get_connection_info()
    if not final_conn_info:
        await client.add_message("Internal error: Connection info not available after /connect setup.", client.ui.colors["error"], context_name="Status")
        logger.error("Connection info is None after setting it in StateManager during /connect.")
        return

    # The connection orchestrator will now use the connection info from StateManager
    await client.connection_orchestrator.establish_connection(final_conn_info)
