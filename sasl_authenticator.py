# sasl_authenticator.py
import base64
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from network_handler import NetworkHandler # To avoid circular import
    from cap_negotiator import CapNegotiator # For callbacks

logger = logging.getLogger("pyrc.sasl")

class SaslAuthenticator:
    def __init__(self, network_handler: 'NetworkHandler', cap_negotiator: 'CapNegotiator', nick: str, password: Optional[str]):
        self.network_handler = network_handler
        self.cap_negotiator = cap_negotiator # To notify on completion
        self.nick = nick # The nick to use for authentication (authcid and authzid)
        self.password = password # NickServ password or SASL password

        self.sasl_authentication_initiated: bool = False
        self.sasl_flow_active: bool = False
        self.sasl_authentication_succeeded: Optional[bool] = None # None = not yet determined, True = success, False = failure

    def _add_status_message(self, message: str, color_key: str = "system"):
        # This method will need access to the client's UI/message adding facility.
        # For now, we'll log. This should be routed to IRCClient_Logic.add_message
        # or a similar shared messaging service.
        logger.info(f"[SaslAuthenticator Status] {message}")
        # Example: if self.cap_negotiator and hasattr(self.cap_negotiator, 'client_logic_ref'):
        #     self.cap_negotiator.client_logic_ref._add_status_message(message, color_key)

    def has_credentials(self) -> bool:
        return bool(self.password)

    def is_flow_active(self) -> bool:
        return self.sasl_flow_active

    def is_completed(self) -> bool:
        """Checks if SASL flow has finished (either succeeded or failed)."""
        return self.sasl_authentication_succeeded is not None

    def start_authentication(self):
        """Initiates SASL PLAIN authentication."""
        if not self.has_credentials():
            self._add_status_message("SASL: NickServ/SASL password not set. Skipping SASL.", color_key="warning")
            logger.warning("SASL: NickServ/SASL password not set when trying to start authentication.")
            self._notify_completion(False) # Signal failure
            return

        if not self.cap_negotiator.is_cap_enabled("sasl"):
            self._add_status_message("SASL: 'sasl' CAP not enabled by server. Cannot start SASL.", color_key="error")
            logger.error("SASL: Attempted to start SASL authentication but 'sasl' CAP is not enabled.")
            self._notify_completion(False)
            return

        self._add_status_message("SASL: Initiating PLAIN authentication...")
        logger.info("SASL: Initiating PLAIN authentication.")
        self.sasl_authentication_initiated = True
        self.sasl_flow_active = True
        self.sasl_authentication_succeeded = None # Reset previous result
        self.network_handler.send_authenticate("PLAIN")

    def on_authenticate_challenge_received(self, challenge: str):
        """Handles the AUTHENTICATE + challenge from the server."""
        if not self.sasl_flow_active:
            logger.warning("SASL: Received AUTHENTICATE challenge but SASL flow not active. Ignoring.")
            return

        if challenge == "+":
            logger.info("SASL: Received '+' challenge. Sending PLAIN credentials.")
            # Use self.nick as authcid, self.nick as authzid (common practice for NickServ)
            payload_str = f"{self.nick}\0{self.nick}\0{self.password}"
            payload_b64 = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")

            # Log masked payload for security
            masked_payload_str = f"{self.nick}\0{self.nick}\0********"
            masked_payload_b64 = base64.b64encode(masked_payload_str.encode("utf-8")).decode("utf-8")
            logger.debug(f"SASL: Sending AUTHENTICATE payload (masked): {masked_payload_b64}")

            self.network_handler.send_authenticate(payload_b64)
        else:
            logger.warning(f"SASL: Received unexpected challenge: {challenge}. Aborting SASL.")
            self._add_status_message(f"SASL: Unexpected challenge '{challenge}'. Aborting.", color_key="error")
            self._handle_failure(f"Unexpected challenge: {challenge}")

    def on_sasl_result_received(self, success: bool, message: str):
        """Handles SASL success (900, 903) or failure (904, etc.) numerics."""
        if success:
            self._handle_success(message)
        else:
            self._handle_failure(message)

    def _handle_success(self, message: str):
        """Processes SASL authentication success."""
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is True:
            logger.info(f"SASL: Received SASL success ({message}), but flow no longer active and already succeeded. Ignoring.")
            return

        logger.info(f"SASL: Authentication successful. Message: {message}")
        self._add_status_message(f"SASL: Authentication successful. ({message})")
        self.sasl_authentication_succeeded = True
        self.sasl_flow_active = False
        self._notify_completion(True)

    def _handle_failure(self, reason: str):
        """Processes SASL authentication failure."""
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is False:
            logger.info(f"SASL: Received SASL failure ({reason}), but flow no longer active and already failed. Ignoring.")
            return

        logger.warning(f"SASL: Authentication failed. Reason: {reason}")
        self._add_status_message(f"SASL: Authentication FAILED. Reason: {reason}", color_key="error")
        self.sasl_authentication_succeeded = False
        self.sasl_flow_active = False
        self._notify_completion(False)

    def notify_sasl_cap_rejected(self):
        """Called by CapNegotiator if the 'sasl' CAP REQ was NAKed."""
        if self.sasl_flow_active:
            logger.warning("SASL CAP was NAKed while SASL flow was presumed active. This shouldn't happen if ACK is awaited first.")
            self._handle_failure("SASL capability rejected by server after initial ACK (or NAK received for REQ).")
        else:
            logger.info("SASL CAP was NAKed. SASL authentication will not proceed.")
            # Ensure state reflects that SASL won't happen
            self.sasl_authentication_initiated = True # Attempted via CAP REQ
            self.sasl_authentication_succeeded = False # Failed due to NAK
            self.sasl_flow_active = False
            self._notify_completion(False) # Notify CapNegotiator that this path is done (failed)


    def abort_authentication(self, reason: str):
        """Public method to abort an ongoing SASL authentication externally if needed."""
        if self.sasl_flow_active:
            logger.warning(f"SASL: Authentication aborted externally. Reason: {reason}")
            self._add_status_message(f"SASL: Authentication aborted. Reason: {reason}", color_key="warning")
            self._handle_failure(f"Aborted: {reason}")
        else:
            logger.info(f"SASL: Request to abort, but no SASL flow active. Reason: {reason}")

    def _notify_completion(self, success: bool):
        """Notifies the CapNegotiator that the SASL flow has completed."""
        if self.cap_negotiator:
            self.cap_negotiator.on_sasl_flow_completed(success)
        else:
            logger.error("SaslAuthenticator has no CapNegotiator reference to notify completion.")

    def reset_authentication_state(self):
        """Resets SASL state, typically on disconnect or new negotiation."""
        logger.debug("Resetting SaslAuthenticator state.")
        self.sasl_authentication_initiated = False
        self.sasl_flow_active = False
        self.sasl_authentication_succeeded = None
        # self.nick and self.password are set at __init__ and usually don't change per connection attempt
        # unless IRCClient_Logic re-initializes this with new credentials.
