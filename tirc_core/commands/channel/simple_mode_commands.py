# commands/channel/simple_mode_commands.py
import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.channel.simple_modes")

# Helper function to create mode command handlers
def _create_simple_mode_handler(mode_char: str, op_char: str, command_name: str):
    async def _handler(client: "IRCClient_Logic", args_str: str):
        parts = args_str.split()
        active_context_name = client.context_manager.active_context_name or "Status"

        target_channel: Optional[str] = None
        target_nick: Optional[str] = None

        if not parts: # /op (target active user in active channel) - this is too ambiguous
            await client.add_message(f"Usage: /{command_name} <nickname> [channel]", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

        target_nick = parts[0]
        if len(parts) > 1:
            target_channel = parts[1]
        elif active_context_name != "Status" and client.context_manager.get_context_type(active_context_name) == "channel":
            target_channel = active_context_name
        else:
            await client.add_message(f"Usage: /{command_name} <nickname> [channel] - No channel specified or active.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

        if not target_channel or not target_nick: # Should be caught by logic above
            await client.add_message(f"Error determining target for /{command_name}.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

        normalized_channel = client.context_manager._normalize_context_name(target_channel)

        # Ensure channel context exists (though server will ultimately validate channel)
        if not client.context_manager.get_context(normalized_channel):
             # We could create it, but for mode ops, it's better if user is in it or it's known.
             # For now, let server handle if channel doesn't exist on client side.
             pass


        await client.network_handler.send_raw(f"MODE {normalized_channel} {op_char}{mode_char} {target_nick}")
        logger.info(f"Sent MODE {normalized_channel} {op_char}{mode_char} {target_nick} via /{command_name} command.")
        # Server will send MODE confirmation back.
        await client.add_status_message(f"Attempting to {op_char}mode {mode_char} for {target_nick} in {normalized_channel}...", "system")

    _handler.__name__ = f"handle_{command_name}_command" # For clarity in logs/debugging
    _handler.__doc__ = f"Handles the /{command_name} command."
    return _handler

COMMAND_DEFINITIONS = [
    {
        "name": "op",
        "handler_function": _create_simple_mode_handler("o", "+", "op"), # Pass function directly
        "help": { "usage": "/op <nickname> [channel]", "description": "Grants operator status (+o) to <nickname> in [channel] or current channel.", "aliases": ["o"]},
    },
    {
        "name": "deop",
        "handler_function": _create_simple_mode_handler("o", "-", "deop"),
        "help": { "usage": "/deop <nickname> [channel]", "description": "Removes operator status (-o) from <nickname>.", "aliases": ["do"]},
    },
    {
        "name": "voice",
        "handler_function": _create_simple_mode_handler("v", "+", "voice"),
        "help": { "usage": "/voice <nickname> [channel]", "description": "Grants voice status (+v) to <nickname>.", "aliases": ["v"]},
    },
    {
        "name": "devoice",
        "handler_function": _create_simple_mode_handler("v", "-", "devoice"),
        "help": { "usage": "/devoice <nickname> [channel]", "description": "Removes voice status (-v) from <nickname>.", "aliases": ["dv"]},
    },
    # Add other simple modes like +b, -b (ban/unban) if they are simple enough.
    # Note: Ban usually requires a hostmask, not just a nick, so it's more complex than these.
    # Ban commands are in ban_commands.py
]

# The CommandHandler needs to be adapted to understand "handler_function" if it's different from "handler" (string name)
# For now, let's assume CommandHandler can take a direct callable.
# If not, each handler would need to be defined explicitly without the factory.
# To make it compatible with existing CommandHandler expecting string names,
# we can assign these to the module scope.

# Dynamically create and assign handlers to module scope for CommandHandler to find by string name
for cmd_def in COMMAND_DEFINITIONS:
    if "handler_function" in cmd_def:
        handler_name = f"handle_{cmd_def['name']}_command"
        globals()[handler_name] = cmd_def["handler_function"]
        cmd_def["handler"] = handler_name # Set the string name for CommandHandler
        del cmd_def["handler_function"] # Remove the temporary key
