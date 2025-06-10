# pyrc_core/commands/dcc/dcc_accept_command.py
import argparse
import logging
from typing import TYPE_CHECKING, List, Dict, Any
from .dcc_command_base import DCCCommandHandlerBase

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.accept")

COMMAND_NAME = "accept"
COMMAND_ALIASES: List[str] = []
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc accept <nick> \"<filename>\" <ip> <port> <size>",
    "description": "Accepts an incoming DCC SEND offer from a specified nickname for a given filename, IP, port, and size.",
    "aliases": "None"
}

class DCCAcceptCommandHandler(DCCCommandHandlerBase):
    """Handles the /dcc accept command."""

    async def execute(self, cmd_args: List[str], active_context_name: str, dcc_context_name: str):
        """
        Handles the /dcc accept command.
        Parses arguments and attempts to accept an incoming DCC offer.
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
        parser.add_argument("ip", help="Sender's IP address.")
        parser.add_argument("port", type=int, help="Sender's port number.")
        parser.add_argument("size", type=int, help="File size in bytes.")

        try:
            parsed_args = parser.parse_args(cmd_args)
            nick = parsed_args.nick
            filename = parsed_args.filename.strip('"')
            ip_str = parsed_args.ip
            port = parsed_args.port
            filesize = parsed_args.size

            if not (0 < port <= 65535):
                await self._handle_dcc_error(f"Invalid port: {port}. Must be 1-65535.", dcc_context_name)
                return
            if filesize < 0:
                await self._handle_dcc_error(f"Invalid filesize: {filesize}. Must be non-negative.", dcc_context_name)
                return

            # Get transfer ID using the helper function
            transfer_id = dcc_m.receive_manager.get_transfer_id_by_args(nick, filename, ip_str, port, filesize)
            if not transfer_id:
                await self._handle_dcc_error(f"No pending DCC transfer found for {nick} '{filename}' at {ip_str}:{port} ({filesize} bytes). It may have expired.", dcc_context_name)
                return

            # Accept the DCC offer using the transfer ID
            success = await dcc_m.receive_manager.accept_dcc_offer(transfer_id)
            if success:
                await self.client_logic.add_message(text=f"Accepted DCC SEND from {nick} for '{filename}' (ID: {transfer_id[:8]}). Receiving...", color_attr=self.client_logic.ui.colors["system"], context_name=dcc_context_name)
            else:
                await self._handle_dcc_error(f"DCC ACCEPT for '{filename}' from {nick} failed. Check logs for details.", dcc_context_name)

            await self._ensure_dcc_context(dcc_context_name)

        except argparse.ArgumentError as e:
            await self._handle_dcc_error(f"Error: {e.message}\nUsage: {COMMAND_HELP['usage']}", active_context_name, log_level=logging.WARNING)
        except SystemExit:
            await self.client_logic.add_message(text=f"Usage: {COMMAND_HELP['usage']}", color_attr=self.client_logic.ui.colors["error"], context_name=active_context_name)
        except Exception as e:
            await self._handle_dcc_error(f"Error processing /dcc {COMMAND_NAME}: {e}. Please check format.", dcc_context_name, exc_info=True)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_class": DCCAcceptCommandHandler
    }
