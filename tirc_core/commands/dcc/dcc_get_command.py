# pyrc_core/commands/dcc/dcc_get_command.py
import argparse
import logging
from typing import TYPE_CHECKING, List, Dict, Any
from .dcc_command_base import DCCCommandHandlerBase

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.get")

COMMAND_NAME = "get"
COMMAND_ALIASES: List[str] = []
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc get <nick> \"<filename>\" --token <token>",
    "description": "Accepts a passive (reverse) DCC SEND offer from a specified nickname and filename, using a provided token.",
    "aliases": "None"
}

class DCCGetCommandHandler(DCCCommandHandlerBase):
    """Handles the /dcc get command."""

    async def execute(self, cmd_args: List[str], active_context_name: str, dcc_context_name: str):
        """
        Handles the /dcc get command.
        Parses arguments and attempts to accept a passive DCC offer.
        """
        dcc_m = self.client_logic.dcc_manager
        if not dcc_m:
            await self._handle_dcc_error(f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
            return
        if not dcc_m.dcc_config.enabled:
            await self._handle_dcc_error(f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
            return

        parser = argparse.ArgumentParser(prog=f"/dcc {COMMAND_NAME}", add_help=False)
        parser.add_argument("nick", help="Sender's nickname.")
        parser.add_argument("filename", help="Filename offered (can be quoted).")
        parser.add_argument("--token", required=True, help="The token provided with the passive offer.")

        try:
            parsed_args = parser.parse_args(cmd_args)
            nick = parsed_args.nick
            filename = parsed_args.filename.strip('"')
            token = parsed_args.token

            if hasattr(dcc_m, "accept_passive_offer_by_token"):
                result = await dcc_m.accept_passive_offer_by_token(nick, filename, token)
                if result.get("success"):
                    await self.client_logic.add_message(f"Attempting to GET '{filename}' from {nick} via passive DCC (ID: {result.get('transfer_id', 'N/A')[:8]}).", self.client_logic.ui.colors["system"], context_name=dcc_context_name)
                else:
                    await self._handle_dcc_error(f"DCC GET for '{filename}' from {nick} failed: {result.get('error', 'Unknown error')}", dcc_context_name)
            else:
                # This case should ideally not be hit if the DCCManager is correctly implemented.
                # It suggests a missing method that should be part of the DCCManager's public API for this command.
                await self._handle_dcc_error("DCC GET command logic (accept_passive_offer_by_token) not found in DCCManager. This is an internal issue.", dcc_context_name, log_level=logging.CRITICAL)

            await self._ensure_dcc_context(dcc_context_name)

        except argparse.ArgumentError as e:
            await self._handle_dcc_error(f"Error: {e.message}\nUsage: {COMMAND_HELP['usage']}", active_context_name, log_level=logging.WARNING)
        except SystemExit: # Raised by argparse on error or --help
            await self.client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", self.client_logic.ui.colors["error"], context_name=active_context_name)
        except Exception as e:
            await self._handle_dcc_error(f"Error processing /dcc {COMMAND_NAME}: {e}. Usage: {COMMAND_HELP['usage']}", dcc_context_name, exc_info=True)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_class": DCCGetCommandHandler
    }
