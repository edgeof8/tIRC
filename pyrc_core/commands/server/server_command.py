# START OF MODIFIED FILE: commands/server/server_command.py
import logging
import time
import threading
from typing import TYPE_CHECKING, Optional # Ensure Optional is imported

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

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

def _proceed_with_new_server_connection(client: "IRCClient_Logic", config_name: str):
    """
    Helper function to encapsulate the logic for setting up and connecting to a new server.
    """
    if config_name not in client.all_server_configs:
        logger.error(f"/server: Target config '{config_name}' not found during connection attempt.")
        client.add_message(f"Error: Server configuration '{config_name}' disappeared.", "error", context_name="Status")
        return

    new_conf = client.all_server_configs[config_name]
    client.active_server_config_name = config_name
    client.active_server_config = new_conf

    client.server = new_conf.address
    client.port = new_conf.port
    client.nick = new_conf.nick
    client.initial_channels_list = new_conf.channels[:]
    client.password = new_conf.server_password
    client.nickserv_password = new_conf.nickserv_password
    client.use_ssl = new_conf.ssl
    client.verify_ssl_cert = new_conf.verify_ssl_cert

    client._initialize_connection_handlers()
    client._reset_state_for_new_connection() # Call this before update_connection_params

    if client.server and client.port:
        client.network_handler.update_connection_params(
            server=client.server,
            port=client.port,
            use_ssl=client.use_ssl,
            # channels_to_join will be handled by RegistrationHandler based on client.initial_channels_list
        )
        if not client.network_handler._network_thread or not client.network_handler._network_thread.is_alive():
            client.network_handler.start()

        client.add_message(
            f"Switched active server configuration to '{config_name}'. Attempting to connect...",
            "system",
            context_name="Status",
        )
    else:
        client.add_message(
            f"Error: Invalid server configuration for '{config_name}'. Missing server address or port.",
            "error",
            context_name="Status",
        )

def handle_server_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /server command for switching between configured servers."""
    if not args_str:
        help_data = client.script_manager.get_help_text_for_command("server")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /server <config_name>"
        )
        client.add_message(
            usage_msg,
            "error",
            context_name=client.context_manager.active_context_name or "Status",
        )
        return

    config_name = args_str.strip()
    if config_name not in client.all_server_configs:
        client.add_message(
            f"Server configuration '{config_name}' not found. Available configurations: {', '.join(sorted(client.all_server_configs.keys()))}",
            "error",
            context_name=client.context_manager.active_context_name or "Status",
        )
        return

    disconnect_needed = False
    if client.network_handler.connected:
        if config_name != client.active_server_config_name:
            disconnect_needed = True
        else: # Reconnecting to the same server
            disconnect_needed = True
            client.add_message(f"Reconnecting to server '{config_name}'...", "system", context_name="Status")


    if disconnect_needed:
        # Store target for when disconnect completes
        client._server_switch_target_config_name = config_name
        client._server_switch_disconnect_event = threading.Event()

        timeout_duration = 10.0  # seconds

        client.add_message(f"Disconnecting from current server to switch to '{config_name}'...", "system", context_name="Status")
        client.network_handler.disconnect_gracefully("Switching server configurations via /server command...")

        # Wait for the disconnect event to be set by NetworkHandler or IRCClient_Logic
        logger.info(f"/server: Waiting up to {timeout_duration}s for disconnect completion before switching to {config_name}...")

        # This part will run in the main thread, potentially blocking UI updates if timeout is long.
        # For a fully non-blocking UI, this wait and subsequent connection would need to be offloaded
        # to another thread, or the command handler itself would need to be structured to return
        # and have a callback. Given current architecture, a blocking wait here is simpler.

        disconnect_confirmed = client._server_switch_disconnect_event.wait(timeout=timeout_duration)

        # Clear the event and target name regardless of outcome
        final_target_config = client._server_switch_target_config_name
        client._server_switch_disconnect_event = None
        client._server_switch_target_config_name = None

        if not disconnect_confirmed:
            logger.warning(f"/server: Timeout waiting for CLIENT_DISCONNECTED when switching to {final_target_config}. Proceeding with connection attempt anyway.")
            client.add_message(f"Warning: Disconnect confirmation timed out. Attempting to connect to {final_target_config}...", "warning", context_name="Status")
        else:
            logger.info(f"/server: Disconnect confirmed. Proceeding to connect to {final_target_config}.")

        if final_target_config:
            _proceed_with_new_server_connection(client, final_target_config)
        else:
            logger.error("/server: Lost target configuration name after disconnect attempt.")
            client.add_message("Error: Internal error during server switch (lost target).", "error", context_name="Status")

        return
    else:
        # If not currently connected, or if it's the initial connection attempt
        _proceed_with_new_server_connection(client, config_name)

# END OF MODIFIED FILE: commands/server/server_command.py
