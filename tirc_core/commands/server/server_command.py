# commands/server/server_command.py
import logging
from typing import TYPE_CHECKING, Optional
import asyncio

from tirc_core.state_manager import ConnectionState # For checking state
from tirc_core.app_config import ServerConfig # For type hint

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.state_manager import ConnectionInfo

logger = logging.getLogger("tirc.commands.server.server")

COMMAND_DEFINITIONS = [
    {
        "name": "server",
        "handler": "handle_server_command",
        "help": {
            "usage": "/server [config_name]",
            "description": "Lists available server configurations or connects to a specified server configuration.",
            "aliases": ["s"]
        }
    }
]

async def handle_server_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /server command."""
    config_name_arg = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"

    if not config_name_arg:
        # List available server configurations
        server_configs = client.config.all_server_configs
        if not server_configs:
            await client.add_message("No server configurations found. Please check your tirc_config.ini.",
                                     client.ui.colors.get("warning", 0), context_name=active_context_name)
            return

        await client.add_message("Available server configurations:", client.ui.colors.get("system", 0), context_name=active_context_name)
        for name, conf in server_configs.items():
            details = f"{name} ({conf.address}:{conf.port}, Nick: {conf.nick})"
            if name == client.config.default_server_config_name:
                details += " (default)"
            current_conn_info = client.state_manager.get_connection_info()
            if current_conn_info and current_conn_info.server == conf.address and current_conn_info.port == conf.port:
                 details += " (current)"
            await client.add_message(f"  {details}", client.ui.colors.get("system", 0), context_name=active_context_name)
        return

    # Attempt to connect to the specified server configuration
    server_conf_to_connect: Optional[ServerConfig] = client.config.all_server_configs.get(config_name_arg)

    if not server_conf_to_connect:
        await client.add_message(f"Server configuration '{config_name_arg}' not found.",
                                 client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    current_conn_info: Optional["ConnectionInfo"] = client.state_manager.get_connection_info()
    current_conn_state = client.state_manager.get_connection_state()

    # Check if already connected to the target server
    if current_conn_info and \
       current_conn_info.server == server_conf_to_connect.address and \
       current_conn_info.port == server_conf_to_connect.port and \
       current_conn_state not in [ConnectionState.DISCONNECTED, ConnectionState.ERROR, ConnectionState.CONFIG_ERROR]:
        await client.add_message(f"Already connected to {server_conf_to_connect.address}:{server_conf_to_connect.port}.",
                                 client.ui.colors.get("info", 0), context_name=active_context_name)
        return

    await client.add_message(f"Switching to server: {config_name_arg} ({server_conf_to_connect.address}:{server_conf_to_connect.port})...",
                             client.ui.colors.get("system", 0), context_name=active_context_name)

    # If currently connected to a different server, disconnect first
    if current_conn_state not in [ConnectionState.DISCONNECTED, ConnectionState.ERROR, ConnectionState.CONFIG_ERROR]:
        logger.info(f"/server: Currently connected to {current_conn_info.server if current_conn_info else 'another server'}. Disconnecting first.")

        # Set up an event to wait for disconnect completion before proceeding
        client._server_switch_disconnect_event = asyncio.Event()
        client._server_switch_target_config_name = config_name_arg # Store for after disconnect

        await client.network_handler.disconnect_gracefully(f"Switching to server {config_name_arg}")

        try:
            logger.debug(f"/server: Waiting for disconnect event to be set for target {config_name_arg}...")
            await asyncio.wait_for(client._server_switch_disconnect_event.wait(), timeout=10.0)
            logger.debug(f"/server: Disconnect event set for {config_name_arg}. Proceeding with new connection.")
        except asyncio.TimeoutError:
            logger.warning(f"/server: Timeout waiting for disconnect before switching to {config_name_arg}. Proceeding anyway.")
        finally:
            client._server_switch_disconnect_event = None
            client._server_switch_target_config_name = None
            # Ensure state is DISCONNECTED before trying to reconfigure and connect
            await client.state_manager.set_connection_state(ConnectionState.DISCONNECTED)
            await asyncio.sleep(0.5) # Brief pause after disconnect

    # Configure the client with the new server settings and establish connection
    # _configure_from_server_config will create and set the ConnectionInfo in StateManager
    if await client._configure_from_server_config(server_conf_to_connect, config_name_arg):
        new_conn_info = client.state_manager.get_connection_info()
        if new_conn_info:
            await client.connection_orchestrator.reset_for_new_connection() # Reset contexts etc.
            await client.connection_orchestrator.establish_connection(new_conn_info)
        else:
            # This case should ideally be handled by _configure_from_server_config failing
            await client.add_message(f"Failed to prepare connection info for '{config_name_arg}'.",
                                     client.ui.colors.get("error", 0), context_name=active_context_name)
    else:
        # _configure_from_server_config would have logged errors and set state to CONFIG_ERROR
        await client.add_message(f"Failed to configure client for server '{config_name_arg}'. Check logs.",
                                 client.ui.colors.get("error", 0), context_name=active_context_name)
