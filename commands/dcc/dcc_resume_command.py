import logging
import argparse
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.resume")

class DCCResumeCommandHandler:
    def __init__(self, client_logic: 'IRCClient_Logic'):
        self.client_logic = client_logic
        self.dcc_m = client_logic.dcc_manager
        self.dcc_context_name = "DCC"

    def execute(self, cmd_args: List[str]):
        # Usage: /dcc resume <transfer_id_prefix_or_filename>
        parser_resume = argparse.ArgumentParser(prog="/dcc resume", add_help=False)
        parser_resume.add_argument("identifier", help="The transfer ID prefix or filename to resume.")

        try:
            parsed_resume_args = parser_resume.parse_args(cmd_args)
            identifier = parsed_resume_args.identifier

            if hasattr(self.dcc_m, "attempt_user_resume"):
                result = self.dcc_m.attempt_user_resume(identifier)
                if result.get("success"):
                    resumed_filename = result.get("filename", identifier)
                    resumed_tid = result.get("transfer_id", "N/A")[:8]
                    self.client_logic.add_message(
                        f"Attempting to resume DCC SEND for '{resumed_filename}' (New ID: {resumed_tid}).",
                        "system",
                        context_name=self.dcc_context_name
                    )
                else:
                    self.client_logic.add_message(
                        f"DCC RESUME for '{identifier}' failed: {result.get('error', 'Unknown error or transfer not found/resumable.')}",
                        "error",
                        context_name=self.dcc_context_name
                    )
            else:
                self.client_logic.add_message(
                    "DCC RESUME command logic not fully implemented in DCCManager yet.",
                    "error",
                    context_name=self.dcc_context_name
                )

            if self.client_logic.context_manager.active_context_name != self.dcc_context_name:
                self.client_logic.switch_active_context(self.dcc_context_name)

        except SystemExit:  # Argparse calls sys.exit()
            self.client_logic.add_message(
                "Usage: /dcc resume <transfer_id_prefix_or_filename>",
                "error",
                context_name=self.client_logic.context_manager.active_context_name or "Status"
            )
            return
        except Exception as e:
            logger.error(f"Error parsing /dcc resume arguments: {e}", exc_info=True)
            self.client_logic.add_message(
                f"Error in /dcc resume: {e}. Usage: /dcc resume <transfer_id_prefix_or_filename>",
                "error",
                context_name=self.client_logic.context_manager.active_context_name or "Status"
            )
            return

def get_command_definition():
    return {
        "name": "dccresume",
        "handler_class": DCCResumeCommandHandler,
        "help": {
            "usage": "/dcc resume <transfer_id_prefix_or_filename>",
            "description": "Attempts to resume a previously failed or cancelled DCC file transfer.",
            "aliases": []
        }
    }
