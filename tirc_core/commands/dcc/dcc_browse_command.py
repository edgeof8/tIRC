# commands/dcc/dcc_browse_command.py
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.dcc.browse")

COMMAND_DEFINITIONS = [
    {
        "name": "dcc_browse", # Changed from "browse" to be DCC specific
        "handler": "handle_dcc_browse_command",
        "help": {
            "usage": "/dcc_browse [path]",
            "description": "Lists contents of a local directory path (or default DCC upload/download dir if no path). Useful for finding files to send.",
            "aliases": ["dccbrowse", "dbrowse"]
        }
    }
]

async def handle_dcc_browse_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /dcc_browse command."""
    path_arg = args_str.strip()
    active_context_name = client.context_manager.active_context_name or "Status"
    # For DCC browse, results are usually shown in the active context or Status.
    # A dedicated DCC browse window might be overkill unless results are very large.

    if not client.dcc_manager or not client.config.dcc.enabled:
        await client.add_message("DCC system is not enabled.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    base_path_to_browse: Path
    if path_arg:
        base_path_to_browse = Path(path_arg).expanduser()
    else:
        # Default to DCC upload directory, or download if upload not set, or CWD as last resort
        if client.config.dcc.upload_dir:
            base_path_to_browse = Path(client.config.dcc.upload_dir).expanduser()
        elif client.config.dcc.download_dir:
            base_path_to_browse = Path(client.config.dcc.download_dir).expanduser()
        else:
            base_path_to_browse = Path.cwd() # Current working directory of tIRC process

    try:
        # Resolve to an absolute path to prevent ambiguity and ensure it exists
        # strict=True will raise FileNotFoundError if path doesn't exist
        resolved_path = base_path_to_browse.resolve(strict=True)
        if not resolved_path.is_dir():
            await client.add_message(f"Error: Path '{resolved_path}' is not a directory.", client.ui.colors.get("error", 0), context_name=active_context_name)
            return

    except FileNotFoundError:
        await client.add_message(f"Error: Path '{base_path_to_browse}' not found.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return
    except Exception as e:
        logger.error(f"Error resolving path '{base_path_to_browse}' for /dcc_browse: {e}", exc_info=True)
        await client.add_message(f"Error accessing path '{base_path_to_browse}': {e}", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    await client.add_message(f"--- Contents of {resolved_path} ---", client.ui.colors.get("system_highlight", 0), context_name=active_context_name)

    items_listed = 0
    try:
        for item in sorted(os.listdir(resolved_path)): # List and sort
            item_full_path = resolved_path / item
            display_item = item
            if item_full_path.is_dir():
                display_item += "/" # Indicate directory

            # Could add file size for files, but might make output too verbose for a quick browse
            # stat_info = item_full_path.stat()
            # size_str = format_filesize(stat_info.st_size) if item_full_path.is_file() else ""
            # display_item += f" ({size_str})"

            await client.add_message(display_item, client.ui.colors.get("system", 0), context_name=active_context_name)
            items_listed += 1
            if items_listed >= 50: # Limit output to prevent flooding
                await client.add_message("... (output truncated, too many items)", client.ui.colors.get("info_dim", 0), context_name=active_context_name)
                break

    except PermissionError:
        await client.add_message(f"Error: Permission denied to list contents of '{resolved_path}'.", client.ui.colors.get("error", 0), context_name=active_context_name)
    except Exception as e:
        logger.error(f"Error listing directory '{resolved_path}' for /dcc_browse: {e}", exc_info=True)
        await client.add_message(f"Error listing directory '{resolved_path}': {e}", client.ui.colors.get("error", 0), context_name=active_context_name)

    if items_listed == 0:
        await client.add_message(f"Directory '{resolved_path}' is empty.", client.ui.colors.get("system", 0), context_name=active_context_name)
