import argparse
import logging
from typing import TYPE_CHECKING, List, Dict, Any

from pyrc_core.commands.dcc.dcc_command_base import DCCCommandHandler, DCCCommandResult
# Use string type hints to avoid circular imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.send")

class DCCSendCommandHandler(DCCCommandHandler):
    """
    Handles the /dcc send command, initiating DCC file transfers.
    Inherits common DCC command functionality from DCCCommandHandler.
    """
    command_name: str = "send"
    command_aliases: List[str] = []
    command_help: Dict[str, str] = {
        "usage": "/dcc send [-p] <nick> <filepath ...>",
        "description": "Initiates a DCC file transfer to a specified nickname. Use -p for passive (reverse) DCC.",
        "aliases": "None"
    }

    def __init__(self, client_logic: 'IRCClient_Logic'):
        super().__init__(client_logic)

    def _handle_send_results(self, results: Dict[str, Any], nick: str):
        """Processes and displays the results of the initiate_sends operation."""
        if results.get("transfers_started"):
            for transfer_info in results["transfers_started"]:
                fn = transfer_info.get("filename", "Unknown file")
                tid = transfer_info.get("transfer_id", "N/A")[:8]
                token_info = ""
                if transfer_info.get("passive") and transfer_info.get("token"):
                    token_info = f" (Passive Offer, token: {transfer_info.get('token')[:8]})"
                self.client_logic.add_message(f"DCC SEND of '{fn}' to {nick} initiated (ID: {tid}){token_info}.", "system", context_name=self.dcc_context_name)

        if results.get("files_queued"):
            for queue_info in results["files_queued"]:
                fn = queue_info.get("filename", "Unknown file")
                self.client_logic.add_message(f"DCC SEND of '{fn}' to {nick} queued.", "system", context_name=self.dcc_context_name)

        if results.get("errors"):
            for error_info in results["errors"]:
                fn = error_info.get("filename", "Unknown file")
                err = error_info.get("error", "Unknown error")
                self.handle_error(f"DCC SEND for '{fn}' to {nick} failed: {err}", context_name=self.dcc_context_name)

        if not results.get("overall_success", True) and not results.get("transfers_started") and not results.get("files_queued") and not results.get("errors"):
             self.handle_error(f"DCC SEND to {nick} failed: {results.get('error', 'No files processed or unknown error.')}", context_name=self.dcc_context_name)

    def execute(self, cmd_args: List[str]):
        """
        Executes the /dcc send command.
        Parses arguments, initiates DCC sends, and provides feedback.
        """
        if not self.check_dcc_available(self.command_name):
            return

        parser = argparse.ArgumentParser(prog=f"/dcc {self.command_name}", add_help=False)
        parser.add_argument("-p", "--passive", action="store_true", help="Initiate a passive (reverse) DCC send.")
        parser.add_argument("nick", help="The recipient's nickname.")
        parser.add_argument("filepath", nargs='+', help="The path(s) to the file(s) to send.")

        try:
            parsed_args = parser.parse_args(cmd_args)

            nick = parsed_args.nick
            filepaths_to_send = parsed_args.filepath
            passive_mode = parsed_args.passive

            results = self.dcc_m.initiate_sends(nick, filepaths_to_send, passive=passive_mode)
            self._handle_send_results(results, nick)

            self.ensure_dcc_context()

        except argparse.ArgumentError as e:
            self.handle_error(f"Error: {e.message}\nUsage: {self.command_help['usage']}", log_level=logging.WARNING)
        except SystemExit:
            self.client_logic.add_message(f"Usage: {self.command_help['usage']}", "error", context_name=self.active_context_name)
        except Exception as e:
            self.handle_error(f"Error processing /dcc {self.command_name}: {e}. Check usage.", exc_info=True)
