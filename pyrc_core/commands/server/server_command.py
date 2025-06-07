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
    # client.all_server_configs is now client.config.all_server_configs
    if config_name not in client.config.all_server_configs:
        logger.error(f"/server: Target config '{config_name}' not found during connection attempt.")
        client.add_message(f"Error: Server configuration '{config_name}' disappeared.", "error", context_name="Status")
        return

    new_conf = client.config.all_server_configs[config_name]

    # --- MODIFICATION START ---
    # Call _configure_from_server_config which now handles setting ConnectionInfo in StateManager
    # and returns True/False based on validation.
    if not client._configure_from_server_config(new_conf, config_name):
        # Errors would have been logged and displayed by _configure_from_server_config or StateManager/StateChangeUIHandler
        client.add_message(f"Failed to apply server configuration '{config_name}'. Check logs/status for details.", "error", context_name="Status")
        return
    # --- MODIFICATION END ---

    # State is now set in StateManager by _configure_from_server_config.
    # We can retrieve it if needed, or trust that NetworkHandler will use it.
    conn_info = client.state_manager.get_connection_info()
    if not conn_info: # Should not happen if _configure_from_server_config succeeded
        client.add_message(f"Critical error: Connection info lost after configuring for '{config_name}'.", "error", context_name="Status")
        return

    # These direct assignments to client attributes are being phased out by StateManager.
    # client.active_server_config_name = config_name
    # client.active_server_config = new_conf # This might still be useful for client logic to know current named config

    client._initialize_connection_handlers() # Re-initialize based on new state_manager.connection_info
    client._reset_state_for_new_connection()

    if conn_info.server and conn_info.port is not None:
        client.network_handler.update_connection_params(
            server=conn_info.server,
            port=conn_info.port,
            use_ssl=conn_info.ssl,
            channels_to_join=conn_info.initial_channels # Ensure this is passed
        )
        # network_handler.start() is usually called by update_connection_params if not running,
        # or connection is re-attempted in its loop.
        # For /server, explicitly ensure it starts if not alive.
        if not client.network_handler._network_thread or not client.network_handler._network_thread.is_alive():
            client.network_handler.start()

        client.add_message(
            f"Switched active server configuration to '{config_name}'. Attempting to connect...",
            "system",
            context_name="Status",
        )
    else:
        # This case should be caught by _configure_from_server_config returning False
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
    if config_name not in client.config.all_server_configs:
        client.add_message(
            f"Server configuration '{config_name}' not found. Available configurations: {', '.join(sorted(client.config.all_server_configs.keys()))}",
            "error",
            context_name=client.context_manager.active_context_name or "Status",
        )
        return

    disconnect_needed = False
    conn_info = client.state_manager.get_connection_info()
    if client.network_handler.connected and conn_info:
        # Check if the target config is different from the currently active one
        # This needs to be based on the actual connection_info in StateManager, not client.active_server_config_name
        # as that's being phased out.
        current_server_address = conn_info.server
        current_server_port = conn_info.port

        target_config = client.config.all_server_configs[config_name]

        if target_config.address != current_server_address or target_config.port != current_server_port:
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
