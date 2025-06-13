# commands/user/me_command.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.user.me")

COMMAND_DEFINITIONS = [
    {
        "name": "me",
        "handler": "handle_me_command",
        "help": {
            "usage": "/me <action text>",
            "description": "Sends an action message (CTCP ACTION) to the current active window.",
            "aliases": ["action"]
        }
    }
]

async def handle_me_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /me <action text> command."""
    if not args_str:
        await client.add_message(
            "Usage: /me <action text>",
            client.ui.colors.get("error", 0),
            context_name=client.context_manager.active_context_name or "Status",
        )
        return

    active_context_name = client.context_manager.active_context_name
    if not active_context_name or active_context_name == "Status": # Cannot /me in Status
        await client.add_message(
            "Cannot send action to Status window. Join a channel or query a user.",
            client.ui.colors.get("error", 0),
            context_name="Status",
        )
        return

    # Send CTCP ACTION
    # The ScriptAPIHandler.send_action method already formats it correctly.
    # Here, we are in a core command, so we might call a lower-level method or construct it.
    # For consistency, let's assume IRCClient_Logic has a helper or we use network_handler directly.
    # Constructing CTCP ACTION: PRIVMSG <target> :\x01ACTION <message>\x01
    ctcp_action_message = f"\x01ACTION {args_str}\x01"
    await client.network_handler.send_raw(f"PRIVMSG {active_context_name} :{ctcp_action_message}")

    # Echo the action to the local UI
    client_nick = client.nick or "Me" # Fallback
    formatted_action = f"* {client_nick} {args_str}"
    await client.add_message(
        formatted_action,
        client.ui.colors.get("my_action_message", client.ui.colors.get("action_message", 0)), # Use a specific color for self-actions
        context_name=active_context_name
    )
    logger.info(f"Sent ACTION to {active_context_name}: {args_str}")
