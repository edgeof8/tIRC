# commands/dcc/dcc_send_command.py
import logging
from typing import TYPE_CHECKING, List, Optional, Union # Added Union
from pathlib import Path
import shlex # For parsing arguments respecting quotes

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.dcc.send")

COMMAND_DEFINITIONS = [
    {
        "name": "dcc_send",
        "handler": "handle_dcc_send_command",
        "help": {
            "usage": "/dcc_send [-p|--passive] <nick> <filepath1> [\"<filepath with spaces2>\"] [...]",
            "description": "Sends one or more files to a user via DCC. Use -p or --passive for a reverse DCC (sender connects).",
            "aliases": ["dsend"]
        }
    }
]

async def handle_dcc_send_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /dcc_send command."""
    active_context_name = client.context_manager.active_context_name or "Status"
    dcc_ui_context = client.dcc_manager.dcc_ui_context_name if client.dcc_manager else "Status"

    try:
        # Use shlex to handle quoted filepaths correctly
        args = shlex.split(args_str)
    except ValueError as e:
        await client.add_message(f"Error parsing arguments for /dcc_send: {e}", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    if not args:
        await client.add_message("Usage: /dcc_send [-p] <nick> <filepath> [filepath...]", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    passive = False
    if args[0] == "-p" or args[0] == "--passive":
        passive = True
        args.pop(0) # Remove the flag

    if len(args) < 2: # Need at least nick and one filepath
        await client.add_message("Usage: /dcc_send [-p] <nick> <filepath> [filepath...]", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    peer_nick = args[0]
    filepath_strs = args[1:]

    if not client.dcc_manager or not client.config.dcc.enabled:
        await client.add_message("DCC system is not enabled.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    filepath_objects: List[Union[str, Path]] = [] # Changed type hint
    for fp_str in filepath_strs:
        p = Path(fp_str)
        if not p.exists() or not p.is_file():
            await client.add_message(f"File not found or is not a regular file: {fp_str}", client.ui.colors.get("error", 0), context_name=active_context_name)
            # Continue to try sending other valid files if multiple were specified
        else:
            filepath_objects.append(p)

    if not filepath_objects:
        await client.add_message("No valid files specified to send.", client.ui.colors.get("warning", 0), context_name=active_context_name)
        return

    # Call DCCManager to handle queuing these sends
    transfer_ids = await client.dcc_manager.initiate_sends(peer_nick, filepath_objects, passive)

    num_queued = 0
    first_queued_filename = None
    first_transfer_id = None

    for i, transfer_id in enumerate(transfer_ids):
        if transfer_id:
            num_queued += 1
            if first_queued_filename is None:
                if i < len(filepath_objects):
                    # filepath_objects contains Path objects
                    path_obj = filepath_objects[i]
                    if isinstance(path_obj, Path):
                        first_queued_filename = path_obj.name
                    else: # Should not happen with current logic but defensive
                        first_queued_filename = str(path_obj)
                    first_transfer_id = transfer_id


    if num_queued > 0:
        msg = f"Queued {num_queued} file(s) for DCC SEND to {peer_nick}."
        if first_queued_filename and first_transfer_id:
             msg += f" First: '{first_queued_filename}' (ID: {first_transfer_id[:8]}). Mode: {'Passive' if passive else 'Active'}."

        await client.add_message(msg, client.ui.colors.get("system", 0), context_name=dcc_ui_context)
        if client.context_manager.active_context_name != dcc_ui_context:
            await client.view_manager.switch_active_context(dcc_ui_context)
    else:
        await client.add_message(
            f"Failed to queue any files for DCC SEND to {peer_nick}.",
            client.ui.colors.get("error", 0),
            context_name=active_context_name
        )
