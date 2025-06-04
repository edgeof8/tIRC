import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.information.who")

COMMAND_DEFINITIONS = [
    {
        "name": "who",
        "handler": "handle_who_command",
        "help": {
            "usage": "/who [channel|nick]",
            "description": "Shows WHO information for a channel or user.",
            "aliases": []
        }
    }
]

def handle_who_command(client: "IRCClient_Logic", args_str: str):
    target = args_str.strip()
    if not target:
        active_context = client.context_manager.get_active_context()
        if active_context and active_context.type == "channel":
            target = active_context.name
            logger.debug(f"/who command using active channel '{target}' as target.")
        else:
            help_data = client.script_manager.get_help_text_for_command("who")
            usage_msg = (
                help_data["help_text"]
                if help_data
                else "Usage: /who [channel|nick]"
            )
            client.add_message(
                usage_msg, "error", context_name="Status"
            )
            return

    if target:
        client.network_handler.send_raw(f"WHO {target}")
    else:
        # This case should ideally be caught by the logic above,
        # but as a fallback, show usage if no target could be determined.
        help_data = client.script_manager.get_help_text_for_command("who")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /who [channel|nick]"
        )
        client.add_message(
            usage_msg, "error", context_name="Status"
        )
