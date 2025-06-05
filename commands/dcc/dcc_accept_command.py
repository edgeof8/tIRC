import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.accept")

class DCCAcceptCommandHandler:
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

        # /dcc accept <nick> "<filename>" <ip> <port> <size>
        if len(cmd_args) < 5:
            self.client_logic.add_message("Usage: /dcc accept <nick> \"<filename>\" <ip> <port> <size>", "error", context_name=self.active_context_name)
            return

        try:
            nick = cmd_args[0]
            # Filename can contain spaces, so it's cmd_args[1] up to cmd_args[-4]
            # However, the original code just took cmd_args[1].strip('"') which implies filename cannot have spaces
            # unless quoted, and even then, only the first part if not quoted.
            # For consistency with original, let's assume filename is cmd_args[1] for now.
            # A more robust solution would use argparse or better manual parsing for filenames with spaces.
            # If filenames with spaces are common, this part needs to be more robust.
            # For now, sticking to the original simple parsing for this specific command:
            filename = cmd_args[1].strip('"')
            ip_str = cmd_args[2]
            port_str = cmd_args[3]
            filesize_str = cmd_args[4]

            # Validate port and filesize
            try:
                port = int(port_str)
                filesize = int(filesize_str)
                if not (0 < port <= 65535):
                    self.client_logic.add_message(f"Invalid port: {port_str}. Must be 1-65535.", "error", context_name=self.active_context_name)
                    return
                if filesize < 0:
                    self.client_logic.add_message(f"Invalid filesize: {filesize_str}. Must be non-negative.", "error", context_name=self.active_context_name)
                    return
            except ValueError:
                self.client_logic.add_message("Port and filesize must be integers.", "error", context_name=self.active_context_name)
                return

            result = self.dcc_m.accept_incoming_send_offer(nick, filename, ip_str, port, filesize)
            if result.get("success"):
                self.client_logic.add_message(f"Accepted DCC SEND from {nick} for '{filename}' (ID: {result.get('transfer_id', 'N/A')[:8]}). Receiving...", "system", context_name=self.dcc_context_name)
            else:
                err_msg = result.get('error', 'Unknown error')
                fn_for_err = result.get('sanitized_filename', filename) # Use sanitized name if available
                self.client_logic.add_message(f"DCC ACCEPT for '{fn_for_err}' from {nick} failed: {err_msg}", "error", context_name=self.dcc_context_name)

            if self.client_logic.context_manager.active_context_name != self.dcc_context_name:
                self.client_logic.switch_active_context(self.dcc_context_name)

        except IndexError: # Should be caught by len(cmd_args) < 5
             self.client_logic.add_message("Usage: /dcc accept <nick> \"<filename>\" <ip> <port> <size>", "error", context_name=self.active_context_name)
        except Exception as e:
            logger.error(f"Error processing /dcc accept: {e}", exc_info=True)
            self.client_logic.add_message(f"Error in /dcc accept: {e}. Please check format.", "error", context_name=self.active_context_name)
