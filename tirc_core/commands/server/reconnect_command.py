# commands/server/reconnect_command.py
import logging
from typing import TYPE_CHECKING, Optional
import asyncio

from tirc_core.state_manager import ConnectionState # For checking state

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.state_manager import ConnectionInfo # For type hint

logger = logging.getLogger("tirc.commands.server.reconnect")

COMMAND_DEFINITIONS = [
    {
        "name": "reconnect",
        "handler": "handle_reconnect_command",
        "help": {
            "usage": "/reconnect",
            "description": "Disconnects and reconnects to the current server using its last known configuration.",
            "aliases": ["rc"]
        }
    }
]

async def handle_reconnect_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /reconnect command."""
    active_context_name = client.context_manager.active_context_name or "Status"

    current_conn_info: Optional["ConnectionInfo"] = client.state_manager.get_connection_info()
    current_conn_state = client.state_manager.get_connection_state()

    if not current_conn_info:
        await client.add_message(
            "Not currently connected to any server or no connection info available to reconnect.",
            client.ui.colors.get("error", 0),
            context_name=active_context_name,
        )
        return

    server_display_name = current_conn_info.server if current_conn_info.server else "the current server"

    await client.add_message(
        f"Attempting to reconnect to {server_display_name}...",
        client.ui.colors.get("system", 0),
        context_name=active_context_name,
    )

    # If already connected or connecting, disconnect first
    if current_conn_state not in [ConnectionState.DISCONNECTED, ConnectionState.ERROR, ConnectionState.CONFIG_ERROR]:
        logger.info(f"Reconnect: Currently connected/connecting to {server_display_name}. Disconnecting first.")
        # The disconnect_gracefully method in NetworkHandler will eventually set state to DISCONNECTED.
        # ConnectionOrchestrator's establish_connection will then handle the new connection attempt.
        await client.network_handler.disconnect_gracefully(f"Reconnecting to {server_display_name}")
        # Add a small delay to allow disconnect to propagate and state to update
        await asyncio.sleep(1.0)

    # Now, establish the connection using the existing ConnectionInfo
    # The ConnectionOrchestrator will handle the full connection lifecycle.
    # The ConnectionInfo object already holds all necessary details.
    logger.info(f"Reconnect: Calling establish_connection for {current_conn_info.server}")
    await client.connection_orchestrator.establish_connection(current_conn_info)

    # No need to explicitly call client.network_handler.start() here,
    # establish_connection in ConnectionOrchestrator should handle it if necessary.
