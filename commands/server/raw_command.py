import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.server.raw")

COMMAND_DEFINITIONS = [
    {
        "name": "raw",
        "handler": "handle_raw_command",
        "help": {
            "usage": "/raw <raw IRC command>",
            "description": "Sends a raw command directly to the IRC server.",
            "aliases": ["quote", "r"]
        }
    }
]

def handle_raw_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /raw command"""
    help_data = client.script_manager.get_help_text_for_command("raw")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /raw <raw IRC command>"
    )
    # _ensure_args requires args_str to be non-empty by default (num_expected_parts=1)
    if not client.command_handler._ensure_args(args_str, usage_msg):
        return

    # Add a system message to the status window indicating the raw command is being sent
    # This is good for user feedback, as raw commands might not always have visible effects.
    client.add_message(
        f"Sending RAW: {args_str}",
        "system", # Or a more specific color key if desired, e.g., "raw_command_sent"
        context_name="Status"
    )
    logger.info(f"User initiated /raw command: {args_str}")
    client.network_handler.send_raw(args_str)
