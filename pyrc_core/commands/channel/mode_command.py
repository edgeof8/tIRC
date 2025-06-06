import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.channel.mode")

COMMAND_DEFINITIONS = [
    {
        "name": "mode",
        "handler": "handle_mode_command",
        "help": {
            "usage": "/mode [<target>] <modes_and_params>",
            "description": "Sets or views channel or user modes. If <target> is omitted for a channel mode, it defaults to the current channel.",
            "aliases": []
        }
    }
]

def handle_mode_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /mode command"""
    parts = args_str.split(" ", 1)
    target = ""
    modes_and_params = ""
    # Default feedback to status window, but will be updated if target is a channel
    target_context_for_feedback = client.context_manager.active_context_name or "Status"


    active_ctx = client.context_manager.get_active_context()

    if not args_str.strip(): # No arguments provided
        help_data = client.script_manager.get_help_text_for_command("mode")
        usage_msg = (
            help_data["help_text"]
            if help_data
            else "Usage: /mode [<target>] <modes_and_params>"
        )
        client.add_message(
            usage_msg,
            "error",
            context_name="Status",
        )
        return

    # Try to determine if the first part is a target or modes
    first_part = parts[0]
    # Condition: first_part is a channel/nick OR (it's not a mode string AND there are more parts)
    if first_part.startswith(("#", "&", "!", "+")) or \
       (not first_part.startswith(("+", "-")) and len(parts) > 1):
        target = first_part
        if len(parts) > 1:
            modes_and_params = parts[1]
        else: # /mode #channel (to view modes) or /mode nick (user modes)
            modes_and_params = "" # Let server handle if it's a request for current modes
    else:
        # First part is likely modes, target is current channel if applicable
        if active_ctx and active_ctx.type == "channel":
            target = active_ctx.name
            modes_and_params = args_str # The whole string is modes_and_params
        else:
            # Cannot determine target for modes
            help_data = client.script_manager.get_help_text_for_command("mode")
            usage_msg = (
                help_data["help_text"]
                if help_data
                else "Usage: /mode [<target>] <modes_and_params>"
            )
            client.add_message(
                "Cannot set mode: No active channel context and target not specified clearly.",
                "error",
                context_name="Status",
            )
            client.add_message(usage_msg, "error", context_name="Status")
            return

    # If modes_and_params is empty AND target is not a channel (e.g. /mode nick), it's ambiguous
    # or typically a server request for user modes which often doesn't need explicit modes from client.
    # If target is empty (e.g. /mode +i), it's also an issue if not in a channel.
    if not target: # Should have been caught by "No active channel context..."
        client.add_message("Error: Target for mode command is missing.", "error", context_name="Status")
        return


    if target.startswith(("#", "&", "!", "+")):
        target_context_for_feedback = target
    elif active_ctx : # if target is a nick, feedback might go to active window or status
        target_context_for_feedback = active_ctx.name
    # else, it remains the initial active_context_name or "Status"

    send_command = f"MODE {target} {modes_and_params}".strip()
    client.network_handler.send_raw(send_command)

    # Provide feedback
    if modes_and_params:
        client.add_message(
            f"Attempting to set mode '{modes_and_params}' on {target}...",
            "system",
            context_name=target_context_for_feedback,
        )
    else: # Likely a request to view modes
        client.add_message(
            f"Requesting modes for {target}...",
            "system",
            context_name=target_context_for_feedback,
        )
