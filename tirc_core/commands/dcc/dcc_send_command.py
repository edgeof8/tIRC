# pyrc_core/commands/dcc/dcc_send_command.py
import argparse
import logging
from typing import TYPE_CHECKING, List, Dict, Any
from .dcc_command_base import DCCCommandHandlerBase

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.send")

COMMAND_NAME = "send"
COMMAND_ALIASES: List[str] = []
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc send [-p] <nick> <filepath ...>",
    "description": "Initiates a DCC file transfer to a specified nickname. Use -p for passive (reverse) DCC.",
    "aliases": "None"
}

class DCCSendCommandHandler(DCCCommandHandlerBase):
    """Handles the /dcc send command."""

    async def _handle_send_results(self, results: Dict[str, Any], nick: str, dcc_context_name: str):
        """Processes and displays the results of the initiate_sends operation."""
        if results.get("transfers_started"):
            for transfer_info in results["transfers_started"]:
                fn = transfer_info.get("filename", "Unknown file")
                tid = transfer_info.get("transfer_id", "N/A")[:8]
                token_info = ""
                if transfer_info.get("passive") and transfer_info.get("token"): # Check for passive key
                    token_info = f" (Passive Offer, token: {transfer_info.get('token')[:8]})"
                await self.client_logic.add_message(f"DCC SEND of '{fn}' to {nick} initiated (ID: {tid}){token_info}.", self.client_logic.ui.colors["system"], context_name=dcc_context_name)

        if results.get("files_queued"):
            for queue_info in results["files_queued"]:
                fn = queue_info.get("filename", "Unknown file")
                await self.client_logic.add_message(f"DCC SEND of '{fn}' to {nick} queued.", self.client_logic.ui.colors["system"], context_name=dcc_context_name)

        if results.get("errors"):
            for error_info in results["errors"]:
                fn = error_info.get("filename", "Unknown file")
                err = error_info.get("error", "Unknown error")
                await self._handle_dcc_error(f"DCC SEND for '{fn}' to {nick} failed: {err}", dcc_context_name)

        if not results.get("overall_success", True) and not results.get("transfers_started") and not results.get("files_queued") and not results.get("errors"):
             await self._handle_dcc_error(f"DCC SEND to {nick} failed: {results.get('error', 'No files processed or unknown error.')}", dcc_context_name)

    async def execute(self, cmd_args: List[str], active_context_name: str, dcc_context_name: str):
        """
        Handles the /dcc send command.
        Parses arguments, initiates DCC sends, and provides feedback.
        """
        dcc_m = self.client_logic.dcc_manager
        if not dcc_m:
            await self._handle_dcc_error(f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
            return
        if not dcc_m.dcc_config.enabled:
            await self._handle_dcc_error(f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
            return

        parser = argparse.ArgumentParser(prog=f"/dcc {COMMAND_NAME}", add_help=False)
        parser.add_argument("-p", "--passive", action="store_true", help="Initiate a passive (reverse) DCC send.")
        parser.add_argument("nick", help="The recipient's nickname.")
        parser.add_argument("filepath", nargs='+', help="The path(s) to the file(s) to send.")

        try:
            parsed_args = parser.parse_args(cmd_args)
            nick = parsed_args.nick
            filepaths_to_send = parsed_args.filepath
            passive_mode = parsed_args.passive

            results = await dcc_m.initiate_sends(nick, filepaths_to_send, passive=passive_mode)
            await self._handle_send_results(results, nick, dcc_context_name)
            await self._ensure_dcc_context(dcc_context_name)

        except argparse.ArgumentError as e:
            await self._handle_dcc_error(f"Error: {e.message}\nUsage: {COMMAND_HELP['usage']}", active_context_name, log_level=logging.WARNING)
        except SystemExit: # argparse raises SystemExit on --help or error
            # For --help, it prints help and exits. We want to show usage in client.
            # For other errors, it might print to stderr. We want to control output.
            await self.client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", self.client_logic.ui.colors["error"], context_name=active_context_name)
        except Exception as e:
            await self._handle_dcc_error(f"Error processing /dcc {COMMAND_NAME}: {e}. Check usage.", dcc_context_name, exc_info=True)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_class": DCCSendCommandHandler
    }
