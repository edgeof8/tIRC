import argparse
import logging
from typing import TYPE_CHECKING, List, Dict

from pyrc_core.commands.dcc.dcc_command_base import DCCCommandHandler, DCCCommandResult

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.get")

class DCCGetCommandHandler(DCCCommandHandler):
    """
    Handles the /dcc get command, used to accept passive DCC SEND offers.
    Inherits common DCC command functionality from DCCCommandHandler.
    """
    command_name: str = "get"
    command_aliases: List[str] = []
    command_help: Dict[str, str] = {
        "usage": "/dcc get <nick> \"<filename>\" --token <token>",
        "description": "Accepts a passive (reverse) DCC SEND offer from a specified nickname and filename, using a provided token.",
        "aliases": "None"
    }

    def __init__(self, client_logic: 'IRCClient_Logic'):
        super().__init__(client_logic)

    def execute(self, cmd_args: List[str]):
        """
        Executes the /dcc get command.
        Parses arguments and attempts to accept a passive DCC offer.
        """
        if not self.check_dcc_available(self.command_name):
            return

        parser = argparse.ArgumentParser(prog=f"/dcc {self.command_name}", add_help=False)
        parser.add_argument("nick", help="Sender's nickname.")
        parser.add_argument("filename", help="Filename offered (can be quoted).")
        parser.add_argument("--token", required=True, help="The token provided with the passive offer.")

        try:
            parsed_args = parser.parse_args(cmd_args)
            nick = parsed_args.nick
            filename = parsed_args.filename.strip('"')
            token = parsed_args.token

            if hasattr(self.dcc_m, "accept_passive_offer_by_token"):
                result = self.dcc_m.accept_passive_offer_by_token(nick, filename, token)
                if result.get("success"):
                    self.client_logic.add_message(f"Attempting to GET '{filename}' from {nick} via passive DCC (ID: {result.get('transfer_id', 'N/A')[:8]}).", "system", context_name=self.dcc_context_name)
                else:
                    self.handle_error(f"DCC GET for '{filename}' from {nick} failed: {result.get('error', 'Unknown error')}", context_name=self.dcc_context_name)
            else:
                self.handle_error(f"DCC GET command logic not fully implemented in DCCManager.", context_name=self.dcc_context_name)

            self.ensure_dcc_context()

        except argparse.ArgumentError as e:
            self.handle_error(f"Error: {e.message}\nUsage: {self.command_help['usage']}", log_level=logging.WARNING)
        except SystemExit:
            self.client_logic.add_message(f"Usage: {self.command_help['usage']}", "error", context_name=self.active_context_name)
        except Exception as e:
            self.handle_error(f"Error processing /dcc {self.command_name}: {e}. Usage: {self.command_help['usage']}", exc_info=True)
