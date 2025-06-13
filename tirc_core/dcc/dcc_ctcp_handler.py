# tirc_core/dcc/dcc_ctcp_handler.py
import logging
from typing import TYPE_CHECKING, Optional, Dict, Any

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.dcc.dcc_manager import DCCManager

# Module-level logger
logger = logging.getLogger("tirc.dcc.ctcphandler")

class DCCCTCPHandler:
    """Handles incoming CTCP messages related to DCC."""

    def __init__(self, client_logic: "IRCClient_Logic", dcc_manager: "DCCManager"):
        self.client_logic = client_logic
        self.dcc_manager = dcc_manager
        # logger instance specific to the class, if needed for more granular logging
        # self.class_logger = logging.getLogger("tirc.dcc.ctcphandler.instance")
        logger.info("DCCCTCPHandler initialized.")

    async def handle_ctcp_dcc(self, source_nick: str, ctcp_command: str, ctcp_args: str):
        """
        Processes a parsed CTCP DCC command.
        Example: ctcp_command="DCC", ctcp_args="SEND filename ip port size"
        """
        if not self.dcc_manager.dcc_config.enabled:
            logger.debug(f"DCC disabled, ignoring CTCP DCC from {source_nick}: {ctcp_command} {ctcp_args}")
            return

        logger.info(f"Received CTCP DCC from {source_nick}: Command='{ctcp_command}', Args='{ctcp_args}'")

        # The ctcp_args for a DCC message like "DCC SEND filename ..." will be "SEND filename ..."
        # We need to pass the full "SEND filename ..." part to the DCCManager's handler.
        # The DCCManager's handle_incoming_ctcp_dcc expects the full DCC payload after the "DCC " part.

        # Reconstruct the message part that parse_dcc_ctcp expects
        # (which is "DCC <subcommand> <args...>")
        # Here, ctcp_command is "DCC", and ctcp_args is "SEND filename..."
        # So, we pass ctcp_args directly to the DCCManager's handler.

        # It seems the original design was that IRCClient_Logic would parse the CTCP \x01...\x01 wrapper,
        # identify it as CTCP, then if the command inside is "DCC", it passes the *rest* of the
        # CTCP message (e.g., "SEND filename ip port size") to this handler.
        # This handler then further delegates to DCCManager.

        # Let's assume ctcp_args is "SEND filename ip port size"
        # The DCCManager.handle_incoming_ctcp_dcc expects the full string after the initial "DCC "
        # So, it expects "SEND filename ip port size"

        # The dcc_manager.handle_incoming_ctcp_dcc will call dcc_utils.parse_dcc_ctcp
        # which expects the *full* DCC CTCP message string, like "DCC SEND filename..."
        # This means we need to prepend "DCC " back to ctcp_args here.

        full_dcc_message_payload = f"DCC {ctcp_args}" # Reconstruct "DCC SEND ..."

        await self.dcc_manager.handle_incoming_ctcp_dcc(source_nick, full_dcc_message_payload)

# Example usage (conceptual, would be called from IRCClient_Logic or similar):
# async def on_ctcp_received(client, source_nick, command, args):
#     if command.upper() == "DCC":
#         if not client.dcc_ctcp_handler:
#             client.dcc_ctcp_handler = DCCCTCPHandler(client, client.dcc_manager)
#         await client.dcc_ctcp_handler.handle_ctcp_dcc(source_nick, command, args)
