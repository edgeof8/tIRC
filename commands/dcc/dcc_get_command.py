import argparse
import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.get")

class DCCGetCommandHandler:
    def __init__(self, client_logic: 'IRCClient_Logic'):
        self.client_logic = client_logic
        self.dcc_m = client_logic.dcc_manager
        self.active_context_name = client_logic.context_manager.active_context_name or "Status"
        self.dcc_context_name = "DCC"

    def execute(self, cmd_args: List[str]):
        if not self.dcc_m:
            self.client_logic.add_message("DCC system not available.", "error", context_name=self.active_context_name)
            return
        if not self.dcc_m.dcc_config.get("enabled"):
            self.client_logic.add_message("DCC is currently disabled.", "error", context_name=self.active_context_name)
            return

        parser = argparse.ArgumentParser(prog="/dcc get", add_help=False)
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
                    self.client_logic.add_message(f"DCC GET for '{filename}' from {nick} failed: {result.get('error', 'Unknown error')}", "error", context_name=self.dcc_context_name)
            else:
                self.client_logic.add_message(f"DCC GET command logic not fully implemented in DCCManager yet.", "error", context_name=self.dcc_context_name)

            if self.client_logic.context_manager.active_context_name != self.dcc_context_name:
                self.client_logic.switch_active_context(self.dcc_context_name)

        except argparse.ArgumentError as e:
            logger.warning(f"Argument parsing error for /dcc get: {e}")
            self.client_logic.add_message(f"Error: {e.message}\nUsage: /dcc get <nick> \"<filename>\" --token <token>", "error", context_name=self.active_context_name)
        except SystemExit:
            self.client_logic.add_message("Usage: /dcc get <nick> \"<filename>\" --token <token>", "error", context_name=self.active_context_name)
        except Exception as e:
            logger.error(f"Error processing /dcc get: {e}", exc_info=True)
            self.client_logic.add_message(f"Error in /dcc get: {e}. Usage: /dcc get <nick> \"<filename>\" --token <token>", "error", context_name=self.active_context_name)
