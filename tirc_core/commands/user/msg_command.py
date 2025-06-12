# commands/user/msg_command.py
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.user.msg")

COMMAND_DEFINITIONS = [
    {
        "name": "msg",
        "handler": "handle_msg_command",
        "help": {
            "usage": "/msg <target> <message>",
            "description": "Sends a private message to a user or a message to a channel.",
            "aliases": ["m"]
        }
    }
]

async def handle_msg_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /msg command"""
    help_data = client.script_manager.get_help_text_for_command("msg")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /msg <target> <message>"
    )
    parts = await client.command_handler._ensure_args(args_str, usage_msg, num_expected_parts=2)
    if not parts:
        return
    target = parts[0]
    message = parts[1]
    await client.network_handler.send_raw(f"PRIVMSG {target} :{message}")

    # If sending to a user (potential query) and no echo-message, add to our local query context for immediate feedback
    if (
        client.cap_negotiator
        and client.cap_negotiator.supported_caps
        and "echo-message" not in client.cap_negotiator.supported_caps
        and not target.startswith(("#", "&", "+", "!"))
    ):
        # Ensure a query context exists for the target. If not, create it.
        # This is important because if we /msg UserHi and no window exists, it should open.
        query_ctx = client.context_manager.get_context(target)
        if not query_ctx:
            client.context_manager.create_context(target, context_type="query")

        # Add the message to this query context
        # This is for our own view of what we sent.
        # If the target is ourselves, the server will send a PRIVMSG back which message_handlers will pick up.
        if client.nick and client.nick.lower() != target.lower():  # Don't self-echo if PMing self here
            await client.add_message(
                f"<{client.nick}> {message}",
                client.ui.colors["my_message"],
                context_name=target,
            )
