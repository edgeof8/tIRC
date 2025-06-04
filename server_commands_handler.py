import logging
from typing import TYPE_CHECKING #, Optional, Tuple # Optional, Tuple no longer needed
# import time # No longer needed

# from context_manager import ChannelJoinStatus # No longer needed
# from config import DEFAULT_PORT, DEFAULT_SSL_PORT  # No longer needed

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.server_commands_handler")

# DEPRECATED: This class is now empty after refactoring.
# Server command logic has been moved to individual command files
# in the commands/server/ directory.
# Context reset logic has been centralized in IRCClient_Logic.
# This file can be removed in a future cleanup.
#
# class ServerCommandsHandler:
#     def __init__(self, client_logic: "IRCClient_Logic"):
#         self.client = client_logic
#
#     # _reset_contexts_for_new_connection method was moved to IRCClient_Logic
#     # handle_server_command method was moved to commands/server/server_command.py
