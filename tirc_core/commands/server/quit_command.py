import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.server.quit")

COMMAND_DEFINITIONS = [
    {
        "name": "quit",
        "handler": "handle_quit_command",
        "help": {
            "usage": "/quit [message]",
            "description": "Disconnects from the server and exits tIRC.",
            "aliases": ["q"]
        }
    }
]

async def handle_quit_command(client: "IRCClient_Logic", args_str: str):
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
            reason = "tIRC Client Exiting"  # Fallback if no script provides a message

    await client.add_message(
        f"Quitting... (Reason: {reason})",
        client.ui.colors["system"],
        context_name="Status"
    )
    logger.info(f"User initiated /quit. Reason: {reason}")
    # disconnect_gracefully is expected to trigger the client shutdown sequence,
    # which includes setting client.should_quit.
    await client.network_handler.disconnect_gracefully(reason)
