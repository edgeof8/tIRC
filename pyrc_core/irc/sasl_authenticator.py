import base64
import logging
# import threading # Removed
import asyncio
from typing import Optional, TYPE_CHECKING

from pyrc_core.network_handler import NetworkHandler # To avoid circular import
from pyrc_core.irc.cap_negotiator import CapNegotiator # For callbacks

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.sasl")

class SaslAuthenticator:
    def __init__(self, network_handler: 'NetworkHandler', cap_negotiator: 'CapNegotiator', password: Optional[str], client_logic_ref: Optional['IRCClient_Logic'] = None):
        self.network_handler = network_handler
        self.cap_negotiator = cap_negotiator
        self.password = password
        self.client_logic_ref = client_logic_ref
        self.loop = asyncio.get_event_loop() # Should be fine, or get from client_logic_ref if preferred

        self.sasl_authentication_initiated: bool = False
        self.sasl_flow_active: bool = False
        self.sasl_authentication_succeeded: Optional[bool] = None
        # self._sasl_timeout_timer: Optional[threading.Timer] = None # Removed
        self._sasl_step_timeout_task: Optional[asyncio.Task] = None # Added
        self.sasl_timeout_seconds: float = 20.0

    async def _add_status_message(self, message: str, color_key: str = "system"):
        logger.info(f"[SaslAuthenticator Status via Client] {message}")
        if self.client_logic_ref and hasattr(self.client_logic_ref, 'add_status_message') and callable(self.client_logic_ref.add_status_message):
            await self.client_logic_ref.add_status_message(message, color_key)
        else:
            logger.warning("SaslAuthenticator: client_logic_ref is None or add_status_message method is not available.")

    async def _run_sasl_step_timeout(self):
        try:
            await asyncio.sleep(self.sasl_timeout_seconds)
            logger.debug(f"SaslAuthenticator: SASL step timeout task triggered after {self.sasl_timeout_seconds}s.")
            if self.sasl_flow_active: # Check if still relevant
                logger.warning("SaslAuthenticator: SASL authentication step timed out.")
                await self._add_status_message("SASL authentication timed out waiting for server response.", "error")
                await self._handle_failure("SASL step timed out")
        except asyncio.CancelledError:
            logger.debug("SaslAuthenticator: SASL step timeout task cancelled.")
        except Exception as e:
            logger.error(f"SaslAuthenticator: Error in SASL step timeout task: {e}", exc_info=True)

    def has_credentials(self) -> bool:
        return bool(self.password)

    def is_flow_active(self) -> bool:
        return self.sasl_flow_active

    def is_completed(self) -> bool:
        return self.sasl_authentication_succeeded is not None

    async def start_authentication(self):
        if not self.has_credentials():
            await self._add_status_message("SASL: NickServ/SASL password not set. Skipping SASL.", color_key="warning")
            logger.warning("SASL: NickServ/SASL password not set when trying to start authentication.")
            await self._notify_completion(False)
            return

        if not self.cap_negotiator or not self.cap_negotiator.is_cap_enabled("sasl"):
            await self._add_status_message("SASL: 'sasl' CAP not enabled by server or CapNegotiator missing. Cannot start SASL.", color_key="error")
            logger.error("SASL: Attempted to start SASL authentication but 'sasl' CAP is not enabled or CapNegotiator missing.")
            await self._notify_completion(False)
            return

        await self._add_status_message("SASL: Initiating PLAIN authentication...")
        logger.info("SASL: Initiating PLAIN authentication.")
        self.sasl_authentication_initiated = True
        self.sasl_flow_active = True
        self.sasl_authentication_succeeded = None

        await self.network_handler.send_authenticate("PLAIN")

        if self._sasl_step_timeout_task and not self._sasl_step_timeout_task.done():
            self._sasl_step_timeout_task.cancel()
        if self.sasl_timeout_seconds > 0:
            logger.debug(f"SaslAuthenticator: Starting SASL step timeout task ({self.sasl_timeout_seconds}s).")
            self._sasl_step_timeout_task = asyncio.create_task(self._run_sasl_step_timeout())

    async def on_authenticate_challenge_received(self, challenge: str):
        if not self.sasl_flow_active:
            logger.warning("SASL: Received AUTHENTICATE challenge but SASL flow not active. Ignoring.")
            if self._sasl_step_timeout_task and not self._sasl_step_timeout_task.done():
                self._sasl_step_timeout_task.cancel()
            self._sasl_step_timeout_task = None
            return

        if self._sasl_step_timeout_task and not self._sasl_step_timeout_task.done():
            self._sasl_step_timeout_task.cancel()
        self._sasl_step_timeout_task = None

        if challenge == "+":
            logger.info("SASL: Received '+' challenge. Sending PLAIN credentials.")
            current_client_nick = "fallback_nick"
            if self.client_logic_ref:
                 current_client_nick = self.client_logic_ref.nick if self.client_logic_ref.nick else "UnknownNick"
            else:
                logger.error("SASL: client_logic_ref is None when trying to get current nick!")

            if not self.password:
                logger.error("SASL: Password is None when trying to send credentials!")
                await self._handle_failure("Internal error: Password missing for SASL PLAIN.")
                return

            payload_str = f"{current_client_nick}\0{current_client_nick}\0{self.password}"
            payload_b64 = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")

            masked_payload_str = f"{current_client_nick}\0{current_client_nick}\0********"
            masked_payload_b64 = base64.b64encode(masked_payload_str.encode("utf-8")).decode("utf-8")
            logger.debug(f"SASL: Sending AUTHENTICATE payload (masked): {masked_payload_b64}")

            await self.network_handler.send_authenticate(payload_b64)

            if self.sasl_timeout_seconds > 0: # Restart timer for next step
                logger.debug(f"SaslAuthenticator: Starting SASL step timeout task ({self.sasl_timeout_seconds}s) for next server response.")
                self._sasl_step_timeout_task = asyncio.create_task(self._run_sasl_step_timeout())
        else:
            logger.warning(f"SASL: Received unexpected challenge: {challenge}. Aborting SASL.")
            await self._add_status_message(f"SASL: Unexpected challenge '{challenge}'. Aborting.", color_key="error")
            await self._handle_failure(f"Unexpected challenge: {challenge}")

    async def on_sasl_result_received(self, success: bool, message: str):
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is not None:
            logger.info(f"SASL: Received SASL result ({message}), but flow no longer active and already determined. Ignoring.")
            if self._sasl_step_timeout_task and not self._sasl_step_timeout_task.done():
                self._sasl_step_timeout_task.cancel()
            self._sasl_step_timeout_task = None
            return

        if self._sasl_step_timeout_task and not self._sasl_step_timeout_task.done():
            self._sasl_step_timeout_task.cancel()
        self._sasl_step_timeout_task = None

        if success:
            await self._handle_success(message)
        else:
            await self._handle_failure(message)

    async def _handle_success(self, message: str):
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is True:
            logger.info(f"SASL: Received SASL success ({message}), but flow no longer active and already succeeded. Ignoring.")
            return

        logger.info(f"SASL: Authentication successful. Message: {message}")
        await self._add_status_message(f"SASL: Authentication successful. ({message})")
        self.sasl_authentication_succeeded = True
        self.sasl_flow_active = False
        # Task already cancelled in on_sasl_result_received or will be if timeout occurs before this
        await self._notify_completion(True)

    async def _handle_failure(self, reason: str):
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is False:
            logger.info(f"SASL: Received SASL failure ({reason}), but flow no longer active and already failed. Ignoring.")
            return

        logger.warning(f"SASL: Authentication failed. Reason: {reason}")
        await self._add_status_message(f"SASL: Authentication FAILED. Reason: {reason}", color_key="error")
        self.sasl_authentication_succeeded = False
        self.sasl_flow_active = False
        if self._sasl_step_timeout_task and not self._sasl_step_timeout_task.done(): # Ensure cancellation
            self._sasl_step_timeout_task.cancel()
        self._sasl_step_timeout_task = None
        await self._notify_completion(False)

    async def notify_sasl_cap_rejected(self):
        if self.sasl_flow_active:
            logger.warning("SASL CAP was NAKed while SASL flow was presumed active. This shouldn't happen if ACK is awaited first.")
            await self._handle_failure("SASL capability rejected by server after initial ACK (or NAK received for REQ).")
        else:
            logger.info("SASL CAP was NAKed. SASL authentication will not proceed.")
            self.sasl_authentication_initiated = True # Mark as attempted
            self.sasl_authentication_succeeded = False
            self.sasl_flow_active = False
            if self._sasl_step_timeout_task and not self._sasl_step_timeout_task.done():
                self._sasl_step_timeout_task.cancel()
            self._sasl_step_timeout_task = None
            await self._notify_completion(False)

    async def abort_authentication(self, reason: str):
        if self.sasl_flow_active:
            logger.warning(f"SASL: Authentication aborted externally. Reason: {reason}")
            await self._add_status_message(f"SASL: Authentication aborted. Reason: {reason}", color_key="warning")
            await self._handle_failure(f"Aborted: {reason}")
        else:
            logger.info(f"SASL: Request to abort, but no SASL flow active. Reason: {reason}")
            if self._sasl_step_timeout_task and not self._sasl_step_timeout_task.done():
                self._sasl_step_timeout_task.cancel()
            self._sasl_step_timeout_task = None

    async def _notify_completion(self, success: bool):
        if self.cap_negotiator:
            await self.cap_negotiator.on_sasl_flow_completed(success)
        else:
            logger.error("SaslAuthenticator has no CapNegotiator reference to notify completion.")

    def reset_authentication_state(self):
        logger.debug("Resetting SaslAuthenticator state.")
        if self._sasl_step_timeout_task and not self._sasl_step_timeout_task.done():
            self._sasl_step_timeout_task.cancel()
        self._sasl_step_timeout_task = None
        self.sasl_authentication_initiated = False
        self.sasl_flow_active = False
        self.sasl_authentication_succeeded = None
