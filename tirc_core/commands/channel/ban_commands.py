# commands/channel/ban_commands.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.channel.ban")

# Helper function to create ban-related mode command handlers
def _create_ban_mode_handler(mode_char: str, op_char: str, command_name: str, requires_mask: bool = True):
    async def _handler(client: "IRCClient_Logic", args_str: str):
        parts = args_str.split(" ", 1 if requires_mask else 2) # nick_or_mask, [channel]
                                                                # For unban, it's usually just mask [channel]
        active_context_name = client.context_manager.active_context_name or "Status"

        target_channel: Optional[str] = None
        target_mask_or_nick: Optional[str] = None # For ban, this is usually a hostmask. For kickban, a nick.

        if not parts or not parts[0]:
            usage = f"/{command_name} <{'hostmask' if requires_mask else 'nickname_or_hostmask'}> [channel]"
            await client.add_message(f"Usage: {usage}", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

        target_mask_or_nick = parts[0]

        if len(parts) > 1: # Channel specified
            target_channel = parts[1]
        elif active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel = active_context_name
        else:
            usage = f"/{command_name} <{'hostmask' if requires_mask else 'nickname_or_hostmask'}> [channel] - No channel specified or active."
            await client.add_message(usage, client.ui.colors.get("error", 0), context_name=active_context_name)
            return

        if not target_channel or not target_mask_or_nick: # Should be caught
            await client.add_message(f"Error determining target for /{command_name}.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

        normalized_channel = client.context_manager._normalize_context_name(target_channel)

        # For bans, target_mask_or_nick is often a hostmask like *!*@*.example.com
        # For kickban, it's a nickname, and the server might resolve the hostmask.
        # The server ultimately handles the mask format.

        mode_command = f"MODE {normalized_channel} {op_char}{mode_char} {target_mask_or_nick}"

        if command_name == "kickban": # Kickban is a KICK then a BAN
            kick_reason = f"Banned by {client.nick or 'operator'}" # Default kick reason for kickban
            kick_command = f"KICK {normalized_channel} {target_mask_or_nick} :{kick_reason}"
            await client.network_handler.send_raw(kick_command)
            logger.info(f"Sent KICK for /kickban on {target_mask_or_nick} from {normalized_channel}.")
            # Server will send KICK message.
            # Then send the BAN
            await client.network_handler.send_raw(mode_command)
            logger.info(f"Sent MODE (ban) for /kickban on {target_mask_or_nick} in {normalized_channel}.")
            await client.add_status_message(f"Attempting to kickban {target_mask_or_nick} from {normalized_channel}...", "system")
        else: # Just ban or unban
            await client.network_handler.send_raw(mode_command)
            action = "banning" if op_char == "+" else "unbanning"
            logger.info(f"Sent MODE ({action}) for {target_mask_or_nick} in {normalized_channel} via /{command_name}.")
            await client.add_status_message(f"Attempting {action} on {target_mask_or_nick} in {normalized_channel}...", "system")

        # Server will send MODE confirmation.

    _handler.__name__ = f"handle_{command_name}_command"
    _handler.__doc__ = f"Handles the /{command_name} command."
    return _handler

COMMAND_DEFINITIONS = [
    {
        "name": "ban",
        "handler_function": _create_ban_mode_handler("b", "+", "ban", requires_mask=True),
        "help": { "usage": "/ban <hostmask> [channel]", "description": "Bans <hostmask> from [channel] or current channel.", "aliases": []},
    },
    {
        "name": "unban",
        "handler_function": _create_ban_mode_handler("b", "-", "unban", requires_mask=True),
        "help": { "usage": "/unban <hostmask> [channel]", "description": "Removes ban for <hostmask>.", "aliases": []},
    },
    {
        "name": "kickban",
        "handler_function": _create_ban_mode_handler("b", "+", "kickban", requires_mask=False), # For kickban, target is usually a nick
        "help": { "usage": "/kickban <nickname> [channel] [reason]", "description": "Kicks and bans <nickname>.", "aliases": ["kb"]},
        # Note: Kickban reason is not directly handled by this simple factory.
        # A more complex handler would be needed if kick reason needs to be parsed from args_str.
        # The current implementation uses a default kick reason.
    },
]

# Dynamically create and assign handlers to module scope
for cmd_def in COMMAND_DEFINITIONS:
    if "handler_function" in cmd_def:
        handler_name = f"handle_{cmd_def['name']}_command"
        globals()[handler_name] = cmd_def["handler_function"]
        cmd_def["handler"] = handler_name
        del cmd_def["handler_function"]
