# tirc_core/irc/cap_negotiator.py
import logging
import asyncio
from typing import List, Set, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.network_handler import NetworkHandler
    from tirc_core.state_manager import StateManager
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.cap")

class CapNegotiator:
    def __init__(self, network_handler: 'NetworkHandler', state_manager: 'StateManager', client_logic_ref: 'IRCClient_Logic'):
        self.network_handler = network_handler
        self.state_manager = state_manager
        self.client_logic_ref = client_logic_ref # Store the reference
        self.supported_caps: Set[str] = set()
        self.requested_caps: Set[str] = set()
        self.enabled_caps: Set[str] = set()
        self.pending_sasl_auth = False
        self.cap_negotiation_pending = False
        self.cap_negotiation_finished_event = asyncio.Event()
        self.cap_ls_version: Optional[str] = "302" # Default to 3.2

    async def reset_negotiation_state(self):
        logger.debug("Resetting CAP negotiation state.")
        self.supported_caps.clear()
        self.requested_caps.clear()
        self.enabled_caps.clear()
        self.pending_sasl_auth = False
        self.cap_negotiation_pending = False
        self.cap_negotiation_finished_event.clear()

    async def start_negotiation(self, version: Optional[str] = "302"):
        self.cap_ls_version = version
        self.cap_negotiation_pending = True
        self.cap_negotiation_finished_event.clear() # Ensure event is clear at start
        logger.info(f"Starting CAP negotiation (version {self.cap_ls_version or 'default'}).")
        await self.network_handler.send_cap_ls(self.cap_ls_version)

    async def handle_cap_ls(self, capabilities_str: str):
        self.supported_caps.update(capabilities_str.split())
        logger.info(f"Server supports CAP: {self.supported_caps}")

        conn_info = self.state_manager.get_connection_info()
        if not conn_info:
            logger.error("Cannot handle CAP LS: ConnectionInfo not found.")
            self.cap_negotiation_pending = False
            self.cap_negotiation_finished_event.set()
            return

        # Determine which desired capabilities are supported by the server
        self.requested_caps = set(conn_info.desired_caps).intersection(self.supported_caps)

        # Always request SASL if supported and configured, regardless of desired_caps
        if 'sasl' in self.supported_caps and conn_info.sasl_username and conn_info.sasl_password:
            self.requested_caps.add('sasl')
            logger.info("SASL supported by server and configured by user, adding to requested_caps.")

        if self.requested_caps:
            logger.info(f"Requesting CAPs: {self.requested_caps}")
            await self.network_handler.send_cap_req(list(self.requested_caps))
        else:
            logger.info("No desired capabilities supported or configured. Proceeding directly to registration after CAP END.")
            await self.network_handler.send_cap_end() # Still send CAP END as per protocol
            self.cap_negotiation_pending = False # Mark CAP phase as done
            self.cap_negotiation_finished_event.set() # Signal completion of CAP phase

            # Directly trigger the post-CAP negotiation logic from RegistrationHandler
            if self.client_logic_ref.registration_handler:
                await self.client_logic_ref.registration_handler.on_cap_negotiation_complete()
            else:
                logger.error("RegistrationHandler not available on client_logic_ref after CAP END (no caps requested path).")
            # No longer call self.on_cap_end_confirmed() from this specific path.


    async def handle_cap_ack(self, acknowledged_caps_str: str):
        acked_caps = set(acknowledged_caps_str.split())
        self.enabled_caps.update(acked_caps)
        logger.info(f"CAP ACK received for: {acked_caps}. Currently enabled: {self.enabled_caps}")

        if 'sasl' in acked_caps and self.client_logic_ref.sasl_authenticator:
            self.pending_sasl_auth = True
            logger.info("SASL acknowledged. Initiating SASL PLAIN authentication.")
            await self.client_logic_ref.sasl_authenticator.initiate_sasl_plain()
        else:
            # If SASL was requested but not ACKed, or if no SASL authenticator, end CAP.
            # Or if other caps were ACKed and SASL wasn't part of this ACK batch.
            # This logic might need refinement if SASL is part of a multi-stage ACK.
            # For now, assume if SASL isn't handled here, we proceed to CAP END.
            if not self.pending_sasl_auth: # Only send CAP END if SASL is not pending
                logger.info("No pending SASL auth after ACK. Ending CAP negotiation.")
                await self.network_handler.send_cap_end()
                # Negotiation isn't fully over until CAP END is confirmed by server or no more ACKs/NAKs
            else:
                logger.info("SASL authentication is pending. CAP END will be sent after SASL completion.")


    async def handle_cap_nak(self, rejected_caps_str: str):
        rejected_caps = set(rejected_caps_str.split())
        logger.warning(f"CAP NAK received for: {rejected_caps}")
        self.requested_caps.difference_update(rejected_caps) # Remove rejected caps from requested set
        # No need to re-request other caps, server will continue with what it can ACK or has ACKed.
        # If all requested caps were NAKed and SASL is not pending, send CAP END.
        if not self.requested_caps.intersection(self.supported_caps) and not self.pending_sasl_auth:
            logger.info("All remaining requested CAPs were NAKed or no SASL pending. Ending CAP negotiation.")
            await self.network_handler.send_cap_end()


    async def on_sasl_authentication_complete(self, success: bool):
        logger.info(f"SASL authentication completed (success: {success}). Pending SASL auth status: {self.pending_sasl_auth}")
        if self.pending_sasl_auth:
            self.pending_sasl_auth = False # SASL attempt is now complete
            logger.info("Sending CAP END after SASL completion.")
            await self.network_handler.send_cap_end()
            # Negotiation isn't fully over until CAP END is confirmed by server.
        else:
            logger.warning("on_sasl_authentication_complete called, but no SASL auth was pending.")


    async def on_cap_end_confirmed(self):
        """Called when CAP negotiation is truly finished (e.g., after CAP END or if no CAPs requested)."""
        if self.cap_negotiation_pending:
            logger.info("CAP negotiation fully confirmed/ended.")
            self.cap_negotiation_pending = False
            self.cap_negotiation_finished_event.set()
            if self.client_logic_ref.registration_handler:
                await self.client_logic_ref.registration_handler.on_cap_negotiation_complete()
            else:
                logger.error("RegistrationHandler not available on client_logic_ref after CAP END.")
        else:
            logger.debug("on_cap_end_confirmed called, but negotiation was not pending. Likely already handled.")

    async def wait_for_negotiation_finish(self, timeout: float = 10.0) -> bool:
        """Waits for the CAP negotiation to finish with a timeout."""
        if not self.cap_negotiation_pending and self.cap_negotiation_finished_event.is_set():
            logger.debug("CAP negotiation already finished.")
            return True
        try:
            logger.debug(f"Waiting for CAP negotiation finished event with timeout {timeout}s.")
            await asyncio.wait_for(self.cap_negotiation_finished_event.wait(), timeout=timeout)
            logger.debug("CAP negotiation finished event received.")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for CAP negotiation to finish. Forcing event set.")
            if not self.cap_negotiation_finished_event.is_set(): # Check before setting
                self.cap_negotiation_finished_event.set()
            self.cap_negotiation_pending = False # Ensure pending is false on timeout
            return False
        except Exception as e:
            logger.error(f"Error in wait_for_negotiation_finish: {e}", exc_info=True)
            if not self.cap_negotiation_finished_event.is_set():
                self.cap_negotiation_finished_event.set() # Ensure it's set on other errors too
            self.cap_negotiation_pending = False
            return False


    def get_enabled_caps(self) -> Set[str]:
        return self.enabled_caps.copy()
