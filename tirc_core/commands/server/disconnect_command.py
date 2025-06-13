# commands/server/disconnect_command.py
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.server.disconnect")

COMMAND_DEFINITIONS = [
    {
        "name": "disconnect",
        "handler": "handle_disconnect_command",
        "help": {
            "usage": "/disconnect [message]",
            "description": "Disconnects from the current server with an optional message.",
            "aliases": ["d", "dc"]
        }
    }
]

async def handle_disconnect_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /disconnect command."""
    quit_message = args_str.strip() if args_str else "Client disconnecting"
    active_context_name = client.context_manager.active_context_name or "Status"

    if not client.network_handler.connected:
        await client.add_message("Not connected to any server.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    await client.add_status_message(f"Disconnecting from server... (Reason: {quit_message})", "system")
    logger.info(f"User initiated /disconnect. Reason: {quit_message}")

    # The disconnect_gracefully method will send QUIT and then stop the network handler.
    # The network handler's stop method and _reset_connection_state will handle UI updates
    # and event dispatches related to disconnection.
    await client.network_handler.disconnect_gracefully(quit_message)
    # No need to set client.should_quit = True here, as /disconnect doesn't mean exit client.
