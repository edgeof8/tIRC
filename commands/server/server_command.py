import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.server.server")

COMMAND_DEFINITIONS = [
    {
        "name": "server",
        "handler": "handle_server_command",
        "help": {
            "usage": "/server <config_name>",
            "description": "Switches to a pre-defined server configuration and attempts to connect.",
            "aliases": ["s"]
        }
    }
]

def handle_server_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /server command for switching between configured servers."""
    if not args_str:
        help_data = client.script_manager.get_help_text_for_command("server")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /server <config_name>"
        )
        client.add_message(
            usage_msg,
            "error", # Using semantic color key
            context_name=client.context_manager.active_context_name,
        )
        return

    config_name = args_str.strip()
    if config_name not in client.all_server_configs:
        client.add_message(
            f"Server configuration '{config_name}' not found. Available configurations: {', '.join(sorted(client.all_server_configs.keys()))}",
            "error", # Using semantic color key
            context_name=client.context_manager.active_context_name,
        )
        return

    # If already connected and switching to a different server
    if (
        client.network_handler.connected
        and config_name != client.active_server_config_name
    ):
        client.network_handler.disconnect_gracefully(
            "Switching server configurations..."
        )
        # TODO: Replace with proper event-based approach or ensure disconnect is complete
        # A short delay might be needed if disconnect_gracefully is not fully blocking
        # or if subsequent operations depend on the socket being closed immediately.
        # For now, keeping a small delay as in original, but this is a point for improvement.
        time.sleep(1) # Reduced from 3, should be ideally event driven

    # Update active server configuration
    client.active_server_config_name = config_name
    client.active_server_config = client.all_server_configs[config_name]

    # Update client's connection attributes
    client.server = client.active_server_config.address
    client.port = client.active_server_config.port
    client.nick = client.active_server_config.nick
    # Critical: Update initial_channels_list for the new server *before* resetting contexts
    client.initial_channels_list = client.active_server_config.channels[:]
    client.password = client.active_server_config.server_password
    client.nickserv_password = (
        client.active_server_config.nickserv_password
    )
    client.use_ssl = client.active_server_config.ssl
    client.verify_ssl_cert = client.active_server_config.verify_ssl_cert

    # Reconfigure connection-specific handlers (CAP, SASL, Registration)
    # This needs to happen *before* network_handler.update_connection_params
    # because registration handler uses client.initial_channels_list.
    client._initialize_connection_handlers() # This will use the new server's config

    # Reset contexts using the new centralized method
    # This must be called *after* client.initial_channels_list is updated.
    client._reset_state_for_new_connection()

    # Update network handler connection parameters
    if (
        client.server and client.port
    ):  # Ensure we have valid connection parameters
        client.network_handler.update_connection_params(
            server=client.server,
            port=client.port,
            use_ssl=client.use_ssl,
            # channels_to_join will be picked up by RegistrationHandler
            # which now has the updated client.initial_channels_list
        )
        # Ensure the network connection (re)starts if necessary
        if not client.network_handler.network_thread or not client.network_handler.network_thread.is_alive():
            client.network_handler.start()
        # If it was already connected, the disconnect_gracefully + update_connection_params should trigger a reconnect attempt.

        client.add_message(
            f"Switched active server configuration to '{config_name}'. Attempting to connect...",
            "system", # Using semantic color key
            context_name="Status",
        )
    else:
        client.add_message(
            f"Error: Invalid server configuration for '{config_name}'. Missing server address or port.",
            "error", # Using semantic color key
            context_name="Status",
        )
