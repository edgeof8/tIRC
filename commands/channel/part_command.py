import logging
from typing import TYPE_CHECKING

from context_manager import ChannelJoinStatus

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.channel.part")

COMMAND_DEFINITIONS = [
    {
        "name": "part",
        "handler": "handle_part_command",
        "help": {
            "usage": "/part [channel] [reason]",
            "description": "Leaves the specified channel or the current channel if none is specified.",
            "aliases": ["p"]
        }
    }
]

def handle_part_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /part command"""
    help_data = client.script_manager.get_help_text_for_command("part")
    usage_msg = (
        help_data["help_text"] if help_data else "Usage: /part [channel] [reason]"
    )
    # _ensure_args with no num_expected_parts means it can be empty or have content.
    # For /part, if args_str is empty, we part the current channel.
    # If it's not empty, the first word is the channel, the rest is the reason.
    # So, we don't strictly need _ensure_args to validate presence for *this* command structure,
    # but it's good practice if we wanted to enforce at least a channel if current isn't available.
    # However, the original logic allows empty args_str to mean "current channel".

    # Let's adjust how we get channel_to_part and reason based on args_str
    current_active_channel_name = None
    active_ctx = client.context_manager.get_active_context()
    if active_ctx and active_ctx.type == "channel":
        current_active_channel_name = active_ctx.name

    parts = []
    if args_str:
        parts = args_str.split(" ", 1)
        channel_to_part_arg = parts[0]
        reason_arg = parts[1] if len(parts) > 1 else None
    else: # No args given
        if not current_active_channel_name:
            client.add_message(
                "No channel specified and not currently in a channel window.",
                "error",
                context_name="Status"
            )
            client.add_message(usage_msg, "error", context_name="Status")
            return
        channel_to_part_arg = current_active_channel_name
        reason_arg = None

    # If channel_to_part_arg was from args, ensure it's a valid channel name format
    # If it was from current_active_channel_name, it's already correct.
    if args_str and parts: # only re-format if it came from user input
        if not channel_to_part_arg.startswith("#"):
            channel_to_part = f"#{channel_to_part_arg}"
        else:
            channel_to_part = channel_to_part_arg
    else:
        channel_to_part = channel_to_part_arg


    reason = reason_arg

    part_ctx = client.context_manager.get_context(channel_to_part)
    if part_ctx and part_ctx.type == "channel":
        # Ensure join_status attribute exists before trying to set it
        if hasattr(part_ctx, "join_status"):
            part_ctx.join_status = ChannelJoinStatus.PARTING
        logger.info(f"/part: Set context for {channel_to_part} to status PARTING.")
    else:
        logger.debug(
            f"/part: No local channel context for {channel_to_part} or not a channel type. Sending PART anyway."
        )

    if not reason:
        variables = {"nick": client.nick, "channel": channel_to_part}
        reason = client.script_manager.get_random_part_message_from_scripts(
            variables
        )
        if not reason:
            reason = "Leaving"  # Fallback if no script provides a message

    client.network_handler.send_raw(f"PART {channel_to_part} :{reason}")
