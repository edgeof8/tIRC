import argparse
import logging
from typing import TYPE_CHECKING, List, Dict

from pyrc_core.commands.dcc.dcc_command_base import DCCCommandHandler, DCCCommandResult

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.accept")

class DCCAcceptCommandHandler(DCCCommandHandler):
    """
    Handles the /dcc accept command, used to accept incoming DCC SEND offers.
    Inherits common DCC command functionality from DCCCommandHandler.
    """
    command_name: str = "accept"
    command_aliases: List[str] = []
    command_help: Dict[str, str] = {
        "usage": "/dcc accept <nick> \"<filename>\" <ip> <port> <size>",
        "description": "Accepts an incoming DCC SEND offer from a specified nickname for a given filename, IP, port, and size.",
        "aliases": "None"
    }

    def __init__(self, client_logic: 'IRCClient_Logic'):
        super().__init__(client_logic)

    def execute(self, cmd_args: List[str]):
        """
        Executes the /dcc accept command.
        Parses arguments and attempts to accept an incoming DCC offer.
        """
        if not self.check_dcc_available(self.command_name):
            return

        parser = argparse.ArgumentParser(prog=f"/dcc {self.command_name}", add_help=False)
        parser.add_argument("nick", help="Sender's nickname.")
        parser.add_argument("filename", help="Filename offered (can be quoted).")
        parser.add_argument("ip", help="Sender's IP address.")
        parser.add_argument("port", type=int, help="Sender's port number.")
        parser.add_argument("size", type=int, help="File size in bytes.")

        try:
            parsed_args = parser.parse_args(cmd_args)
            nick = parsed_args.nick
            filename = parsed_args.filename.strip('"') # Remove quotes if present
            ip_str = parsed_args.ip
            port = parsed_args.port
            filesize = parsed_args.size

            # Additional validation for port and filesize
            if not (0 < port <= 65535):
                self.handle_error(f"Invalid port: {port}. Must be 1-65535.", context_name=self.active_context_name)
                return
            if filesize < 0:
                self.handle_error(f"Invalid filesize: {filesize}. Must be non-negative.", context_name=self.active_context_name)
                return

            result = self.dcc_m.accept_incoming_send_offer(nick, filename, ip_str, port, filesize)
            if result.get("success"):
                self.client_logic.add_message(f"Accepted DCC SEND from {nick} for '{filename}' (ID: {result.get('transfer_id', 'N/A')[:8]}). Receiving...", "system", context_name=self.dcc_context_name)
            else:
                err_msg = result.get('error', 'Unknown error')
                fn_for_err = result.get('sanitized_filename', filename) # Use sanitized name if available
                self.handle_error(f"DCC ACCEPT for '{fn_for_err}' from {nick} failed: {err_msg}", context_name=self.dcc_context_name)

            self.ensure_dcc_context()

        except argparse.ArgumentError as e:
            self.handle_error(f"Error: {e.message}\nUsage: {self.command_help['usage']}", log_level=logging.WARNING)
        except SystemExit: # Argparse calls sys.exit() on error by default if add_help=True or on bad args
            self.client_logic.add_message(f"Usage: {self.command_help['usage']}", "error", context_name=self.active_context_name)
        except Exception as e:
            self.handle_error(f"Error processing /dcc {self.command_name}: {e}. Please check format.", exc_info=True)
