import argparse
import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.send")

class DCCSendCommandHandler:
    def __init__(self, client_logic: 'IRCClient_Logic'):
        self.client_logic = client_logic
        self.dcc_m = client_logic.dcc_manager
        self.active_context_name = client_logic.context_manager.active_context_name or "Status"
        self.dcc_context_name = "DCC"

    def execute(self, cmd_args: List[str]):
        if not self.dcc_m: # Should have been checked by main /dcc dispatcher
            self.client_logic.add_message("DCC system not available.", "error", context_name=self.active_context_name)
            return
        if not self.dcc_m.dcc_config.get("enabled"): # Also should be checked by dispatcher
            self.client_logic.add_message("DCC is currently disabled.", "error", context_name=self.active_context_name)
            return

        parser = argparse.ArgumentParser(prog="/dcc send", add_help=False)
        parser.add_argument("-p", "--passive", action="store_true", help="Initiate a passive (reverse) DCC send.")
        parser.add_argument("nick", help="The recipient's nickname.")
        parser.add_argument("filepath", nargs='+', help="The path(s) to the file(s) to send.")

        try:
            parsed_known_args = parser.parse_args(cmd_args)
            # No remaining_args check here as parse_args raises SystemExit on unknown args

            nick = parsed_known_args.nick
            filepaths_to_send = parsed_known_args.filepath
            passive_mode = parsed_known_args.passive

            results = self.dcc_m.initiate_sends(nick, filepaths_to_send, passive=passive_mode)

            if results.get("transfers_started"):
                for transfer_info in results["transfers_started"]:
                    fn = transfer_info.get("filename", "Unknown file")
                    tid = transfer_info.get("transfer_id", "N/A")[:8]
                    token_info = ""
                    if passive_mode and transfer_info.get("token"):
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
                    self.client_logic.add_message(f"DCC SEND for '{fn}' to {nick} failed: {err}", "error", context_name=self.dcc_context_name)

            if not results.get("overall_success", True) and not results.get("transfers_started") and not results.get("files_queued") and not results.get("errors"):
                 self.client_logic.add_message(f"DCC SEND to {nick} failed: {results.get('error', 'No files processed or unknown error.')}", "error", context_name=self.dcc_context_name)

            if self.client_logic.context_manager.active_context_name != self.dcc_context_name:
                self.client_logic.switch_active_context(self.dcc_context_name)

        except argparse.ArgumentError as e: # Catch specific argparse errors
            logger.warning(f"Argument parsing error for /dcc send: {e}")
            self.client_logic.add_message(f"Error: {e.message}\nUsage: /dcc send [-p] <nick> <filepath ...>", "error", context_name=self.active_context_name)
        except SystemExit: # Argparse calls sys.exit() on error by default if add_help=True or on bad args
            # This might be too generic if parse_args is used. Consider exit_on_error=False for parser.
            self.client_logic.add_message("Usage: /dcc send [-p] <nick> <filepath ...>", "error", context_name=self.active_context_name)
        except Exception as e:
            logger.error(f"Error processing /dcc send: {e}", exc_info=True)
            self.client_logic.add_message(f"Error in /dcc send: {e}. Check usage.", "error", context_name=self.active_context_name)

# This structure assumes CommandHandler will instantiate DCCSendCommandHandler
# and call its execute method. Or, a simpler functional approach might be used
# if commands are just functions. For now, class-based.

# Example of how it might be registered (hypothetical, depends on command_handler.py)
# def register(command_handler):
#     command_handler.register_command("dccsend", DCCSendCommandHandler, "Sends a file via DCC.")
