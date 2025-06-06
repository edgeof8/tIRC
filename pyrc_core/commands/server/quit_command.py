import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    # If access to app_config is needed for default nick/server for quit message script.
    # import config as app_config

logger = logging.getLogger("pyrc.commands.server.quit")

COMMAND_DEFINITIONS = [
    {
        "name": "quit",
        "handler": "handle_quit_command",
        "help": {
            "usage": "/quit [message]",
            "description": "Disconnects from the server and exits PyRC.",
            "aliases": ["q"]
        }
    }
]

def handle_quit_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /quit command"""
    reason: str
    if args_str:
        reason = args_str
    else:
        # Try to get a random quit message from scripts
        # Ensure client.nick and client.server are accessed safely if they might be None
        nick_for_script = client.nick if client.nick else "UnknownUser"
        server_for_script = client.server if client.server else "UnknownServer"
        variables = {"nick": nick_for_script, "server": server_for_script}

        script_reason = client.script_manager.get_random_quit_message_from_scripts(
            variables
        )
        if script_reason:
            reason = script_reason
        else:
            reason = "PyRC Client Exiting"  # Fallback if no script provides a message

    client.add_message(
        f"Quitting... (Reason: {reason})",
        "system",
        context_name="Status"
    )
    logger.info(f"User initiated /quit. Reason: {reason}")
    # The disconnect_gracefully method will also set client.should_quit = True via its call to self.stop()
    client.network_handler.disconnect_gracefully(reason)
    # Ensure should_quit is explicitly set if not already handled by disconnect_gracefully's chain
    client.should_quit = True
