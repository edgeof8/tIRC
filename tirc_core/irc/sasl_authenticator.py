# tirc_core/irc/sasl_authenticator.py
import base64
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.network_handler import NetworkHandler
    from tirc_core.state_manager import StateManager, ConnectionInfo
    from tirc_core.client.irc_client_logic import IRCClient_Logic # Added for add_status_message

logger = logging.getLogger("tirc.sasl")

class SaslAuthenticator:
    def __init__(self, network_handler: 'NetworkHandler', state_manager: 'StateManager', client_logic_ref: 'IRCClient_Logic'):
        self.network_handler = network_handler
        self.state_manager = state_manager
        self.client_logic_ref = client_logic_ref # Store the reference
        self.sasl_in_progress = False
        self.sasl_authentication_succeeded: Optional[bool] = None

    def reset_authentication_state(self):
        logger.debug("Resetting SASL authentication state.")
        self.sasl_in_progress = False
        self.sasl_authentication_succeeded = None

    async def initiate_sasl_plain(self):
        conn_info = self.state_manager.get_connection_info()
        if not conn_info or not conn_info.sasl_username or not conn_info.sasl_password:
            logger.warning("SASL PLAIN: Username or password not configured. Aborting SASL.")
            # If SASL was mandatory and failed here, CapNegotiator should handle CAP END.
            # For now, assume CapNegotiator will send CAP END if SASL doesn't complete.
            if self.client_logic_ref.cap_negotiator:
                 # Signal that SASL part is "done" (by not succeeding) so CAP END can be sent.
                await self.client_logic_ref.cap_negotiator.on_sasl_authentication_complete(False)
            return

        self.sasl_in_progress = True
        self.sasl_authentication_succeeded = None # Reset before new attempt
        logger.info(f"Initiating SASL PLAIN authentication for user {conn_info.sasl_username}.")
        await self.network_handler.send_authenticate("PLAIN")
        # Server should respond with AUTHENTICATE +

    async def handle_authenticate_challenge(self, challenge: str):
        if not self.sasl_in_progress:
            logger.warning("Received AUTHENTICATE challenge, but SASL not in progress.")
            return

        conn_info = self.state_manager.get_connection_info()
        if not conn_info or not conn_info.sasl_username or not conn_info.sasl_password:
            logger.error("SASL PLAIN: Username or password missing during challenge response.")
            await self.network_handler.send_authenticate("*") # Abort SASL
            await self.on_sasl_result_received(False, "Configuration error for SASL")
            return

        if challenge == "+": # Server is ready for PLAIN payload
            # Payload format: "authzid\0authcid\0password"
            # authzid (authorization identity) can be empty.
            # authcid (authentication identity) is usually the username.
            authzid = conn_info.sasl_username # Or "" if server should derive from authcid
            authcid = conn_info.sasl_username
            password = conn_info.sasl_password

            payload_str = f"{authzid}\0{authcid}\0{password}"
            payload_b64 = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")
            logger.debug(f"Sending SASL PLAIN payload (b64): {payload_b64[:30]}...")
            await self.network_handler.send_authenticate(payload_b64)
        else:
            logger.warning(f"Unexpected SASL AUTHENTICATE challenge: {challenge}. Aborting SASL.")
            await self.network_handler.send_authenticate("*") # Abort
            await self.on_sasl_result_received(False, f"Unexpected challenge: {challenge}")


    async def on_sasl_result_received(self, success: bool, message: str):
        """Called by numeric handlers (900, 903, 904, etc.)"""
        self.sasl_in_progress = False # SASL attempt is now complete, regardless of success
        self.sasl_authentication_succeeded = success

        if success:
            logger.info(f"SASL authentication successful: {message}")
            await self.client_logic_ref.add_status_message(f"SASL: {message}", "success")
        else:
            logger.error(f"SASL authentication failed: {message}")
            await self.client_logic_ref.add_status_message(f"SASL Error: {message}", "error")

        # Notify CapNegotiator that SASL process is complete (successfully or not)
        if self.client_logic_ref.cap_negotiator:
            await self.client_logic_ref.cap_negotiator.on_sasl_authentication_complete(success)
        else:
            logger.error("SASL result received, but CapNegotiator not found on client_logic_ref.")
