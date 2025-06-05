import logging
import os
from typing import TYPE_CHECKING, Dict, Any

from .dcc_send_command import DCCSendCommandHandler
from .dcc_get_command import DCCGetCommandHandler
from .dcc_accept_command import DCCAcceptCommandHandler
from .dcc_list_command import DCCListCommandHandler
from .dcc_browse_command import DCCBrowseCommandHandler
from .dcc_cancel_command import DCCCancelCommandHandler
from .dcc_auto_command import DCCAutoCommandHandler
from .dcc_resume_command import DCCResumeCommandHandler

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc")

def dcc_command_handler(client_logic: 'IRCClient_Logic', args_str: str):
    """Handles the main /dcc command and its subcommands."""

    # Use a simple list of args for now, consider argparse for more complex needs later
    args = args_str.split()

    if not hasattr(client_logic, 'dcc_manager') or not client_logic.dcc_manager:
        client_logic.add_message("DCC system is not initialized or available.", "error", context_name="Status")
        return

    dcc_m = client_logic.dcc_manager
    active_context_name = client_logic.context_manager.active_context_name or "Status"
    dcc_context_name = "DCC"

    if not dcc_m.dcc_config.get("enabled"):
        client_logic.add_message("DCC is currently disabled in the configuration.", "error", context_name=active_context_name)
        return

    if not args:
        client_logic.add_message(
            "Usage: /dcc <send|get|accept|list|close|browse|cancel|resume> [options...]. Try /help dcc for more.",
            "error",
            context_name=active_context_name
        )
        return

    subcommand = args[0].lower()
    cmd_args = args[1:]

    # Dispatch to the appropriate command handler
    if subcommand == "send":
        handler = DCCSendCommandHandler(client_logic)
        handler.execute(cmd_args)
    elif subcommand == "get":
        handler = DCCGetCommandHandler(client_logic)
        handler.execute(cmd_args)
    elif subcommand == "accept":
        handler = DCCAcceptCommandHandler(client_logic)
        handler.execute(cmd_args)
    elif subcommand == "list":
        handler = DCCListCommandHandler(client_logic)
        handler.execute(cmd_args)
    elif subcommand == "browse":
        handler = DCCBrowseCommandHandler(client_logic)
        handler.execute(cmd_args)
    elif subcommand in ["close", "cancel"]:
        handler = DCCCancelCommandHandler(client_logic)
        handler.execute(cmd_args)
    elif subcommand == "auto":
        handler = DCCAutoCommandHandler(client_logic)
        handler.execute(cmd_args)
    elif subcommand == "resume":
        handler = DCCResumeCommandHandler(client_logic)
        handler.execute(cmd_args)
    else:
        client_logic.add_message(f"Unknown DCC subcommand: {subcommand}. Try /help dcc.", "error", context_name=active_context_name)

COMMAND_DEFINITIONS = [
    {
        "name": "dcc",
        "handler": "dcc_command_handler", # Name of the function in this module
        "help": {
            "usage": "/dcc <subcommand> [args]",
            "description": "Manages DCC file transfers. Subcommands: send, get, accept, list, close, browse, cancel, auto, resume.",
            "aliases": []
        }
    },
    # Help for subcommands can be implicitly handled by the main /dcc help string
    # or CommandHandler could be extended for sub-command help topics.
]
