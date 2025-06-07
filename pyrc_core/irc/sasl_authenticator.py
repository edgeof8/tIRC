import base64
import logging
import threading # Import threading for Timer
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.network_handler import NetworkHandler # To avoid circular import
    from pyrc_core.irc.cap_negotiator import CapNegotiator # For callbacks
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.sasl")

class SaslAuthenticator:
    def __init__(self, network_handler: 'NetworkHandler', cap_negotiator: 'CapNegotiator', password: Optional[str], client_logic_ref: Optional['IRCClient_Logic'] = None):
        self.network_handler = network_handler
        self.cap_negotiator = cap_negotiator
        # self.nick removed, will be fetched from client_logic_ref when needed
        self.password = password
        self.client_logic_ref = client_logic_ref

        self.sasl_authentication_initiated: bool = False
        self.sasl_flow_active: bool = False
        self.sasl_authentication_succeeded: Optional[bool] = None
        self._sasl_timeout_timer: Optional[threading.Timer] = None
        self.sasl_timeout_seconds: float = 20.0 # Timeout for SASL steps

    def _add_status_message(self, message: str, color_key: str = "system"):
        logger.info(f"[SaslAuthenticator Status via Client] {message}") # Keep local log
        if self.client_logic_ref and hasattr(self.client_logic_ref, '_add_status_message'):
            self.client_logic_ref._add_status_message(message, color_key)
        elif self.client_logic_ref: # Fallback (defensive)
            logger.warning("SaslAuthenticator: client_logic_ref._add_status_message not found, using direct add_message.")
            color_attr = self.client_logic_ref.ui.colors.get(
                color_key, self.client_logic_ref.ui.colors["system"]
            )
            self.client_logic_ref.add_message(
                message, color_attr, context_name="Status"
            )

    def _start_sasl_step_timeout(self):
        self._cancel_sasl_step_timeout()
        if self.sasl_timeout_seconds > 0:
            logger.debug(f"SaslAuthenticator: Starting SASL step timeout ({self.sasl_timeout_seconds}s).")
            self._sasl_timeout_timer = threading.Timer(self.sasl_timeout_seconds, self._handle_sasl_step_timeout)
            self._sasl_timeout_timer.daemon = True
            self._sasl_timeout_timer.start()

    def _cancel_sasl_step_timeout(self):
        if self._sasl_timeout_timer and self._sasl_timeout_timer.is_alive():
            logger.debug("SaslAuthenticator: Cancelling SASL step timeout timer.")
            self._sasl_timeout_timer.cancel()
        self._sasl_timeout_timer = None

    def _handle_sasl_step_timeout(self):
        if not self.sasl_flow_active:
            logger.debug("SaslAuthenticator: SASL step timeout, but flow no longer active.")
            return

        logger.warning("SaslAuthenticator: SASL authentication step timed out.")
        self._add_status_message("SASL authentication timed out waiting for server response.", "error")
        self._handle_failure("SASL step timed out")


    def has_credentials(self) -> bool:
        return bool(self.password)

    def is_flow_active(self) -> bool:
        return self.sasl_flow_active

    def is_completed(self) -> bool:
        """Checks if SASL flow has finished (either succeeded or failed)."""
        return self.sasl_authentication_succeeded is not None

    def start_authentication(self):
        # 1. Trigger: Called by `CapNegotiator.on_cap_ack_received()` when the 'sasl' capability has been
        #    successfully acknowledged (ACKed) by the server and the client has credentials.
        # 2. Expected State Before:
        #    - `self.cap_negotiator.is_cap_enabled("sasl")` is True.
        #    - `self.has_credentials()` (i.e., `self.password` is set) is True.
        #    - SASL flow is not yet active (`self.sasl_flow_active` is False).
        #    - `self.sasl_authentication_succeeded` is None or a previous result.
        # 3. Key Actions:
        #    - Checks for credentials and if 'sasl' CAP is enabled. If not, logs error, notifies CapNegotiator of failure, and returns.
        #    - Adds a status message "SASL: Initiating PLAIN authentication...".
        #    - Sets `self.sasl_authentication_initiated = True`.
        #    - Sets `self.sasl_flow_active = True`.
        #    - Resets `self.sasl_authentication_succeeded = None`.
        #    - Calls `self.network_handler.send_authenticate("PLAIN")` to send the initial "AUTHENTICATE PLAIN" command
        #      to the server. This starts the SASL PLAIN mechanism.
        # 4. Expected State After:
        #    - `self.sasl_flow_active` is True.
        #    - The "AUTHENTICATE PLAIN" command has been sent to the server.
        #    - The client is now waiting for the server to respond with an "AUTHENTICATE +" challenge.
        #    - Subsequent step: Server's "AUTHENTICATE +" response will be handled by `self.on_authenticate_challenge_received()`.
        """Initiates SASL PLAIN authentication."""
        if not self.has_credentials():
            self._add_status_message("SASL: NickServ/SASL password not set. Skipping SASL.", color_key="warning")
            logger.warning("SASL: NickServ/SASL password not set when trying to start authentication.")
            self._notify_completion(False) # Signal failure
            return

        if not self.cap_negotiator or not self.cap_negotiator.is_cap_enabled("sasl"): # Added check for self.cap_negotiator
            self._add_status_message("SASL: 'sasl' CAP not enabled by server or CapNegotiator missing. Cannot start SASL.", color_key="error")
            logger.error("SASL: Attempted to start SASL authentication but 'sasl' CAP is not enabled or CapNegotiator missing.")
            self._notify_completion(False)
            return

        self._add_status_message("SASL: Initiating PLAIN authentication...")
        logger.info("SASL: Initiating PLAIN authentication.")
        self.sasl_authentication_initiated = True
        self.sasl_flow_active = True
        self.sasl_authentication_succeeded = None
        self.network_handler.send_authenticate("PLAIN")
        self._start_sasl_step_timeout() # Start timeout for server's AUTHENTICATE + response

    def on_authenticate_challenge_received(self, challenge: str):
        # 1. Trigger: Called by `irc_protocol.handle_authenticate()` when an "AUTHENTICATE +" message (challenge)
        #    is received from the server. This is in response to the client's initial "AUTHENTICATE PLAIN" command.
        # 2. Expected State Before:
        #    - `self.sasl_flow_active` is True.
        #    - The client has sent "AUTHENTICATE PLAIN".
        #    - `challenge` (method argument) contains the server's challenge data (typically just "+" for PLAIN).
        # 3. Key Actions:
        #    - If `self.sasl_flow_active` is False, ignores the message.
        #    - If `challenge` is "+":
        #        - Constructs the SASL PLAIN payload: "authcid\0authzid\0password" (typically nick\0nick\0password).
        #        - Base64 encodes this payload.
        #        - Calls `self.network_handler.send_authenticate(payload_b64)` to send the "AUTHENTICATE <base64_payload>"
        #          command containing the actual credentials.
        #    - If `challenge` is not "+":
        #        - Logs a warning and adds an error status message.
        #        - Calls `self._handle_failure()` to terminate SASL authentication as failed.
        # 4. Expected State After:
        #    - If challenge was "+":
        #        - The "AUTHENTICATE <base64_payload>" command with credentials has been sent.
        #        - The client is now waiting for the server to respond with a SASL result numeric (e.g., 903, 904).
        #        - Subsequent step: Server's SASL result numeric will be handled by `self.on_sasl_result_received()`.
        #    - If challenge was unexpected:
        #        - SASL authentication is marked as failed (`self.sasl_authentication_succeeded = False`).
        #        - `self.sasl_flow_active` is set to False.
        #        - `CapNegotiator` is notified of SASL completion (failure) via `self._notify_completion(False)`.
        """Handles the AUTHENTICATE + challenge from the server."""
        if not self.sasl_flow_active:
            logger.warning("SASL: Received AUTHENTICATE challenge but SASL flow not active. Ignoring.")
            self._cancel_sasl_step_timeout() # If flow is not active, cancel timer
            return

        self._cancel_sasl_step_timeout() # Received response, cancel current step timer

        if challenge == "+":
            logger.info("SASL: Received '+' challenge. Sending PLAIN credentials.")
            current_client_nick = "fallback_nick" # Default
            if self.client_logic_ref:
                 current_client_nick = self.client_logic_ref.nick if self.client_logic_ref.nick else "UnknownNick"
            else:
                logger.error("SASL: client_logic_ref is None when trying to get current nick!")

            if not self.password: # Should have been caught by has_credentials, but defensive
                logger.error("SASL: Password is None when trying to send credentials!")
                self._handle_failure("Internal error: Password missing for SASL PLAIN.")
                return

            payload_str = f"{current_client_nick}\0{current_client_nick}\0{self.password}"
            payload_b64 = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")

            masked_payload_str = f"{current_client_nick}\0{current_client_nick}\0********"
            masked_payload_b64 = base64.b64encode(masked_payload_str.encode("utf-8")).decode("utf-8")
            logger.debug(f"SASL: Sending AUTHENTICATE payload (masked): {masked_payload_b64}")

            self.network_handler.send_authenticate(payload_b64)
            self._start_sasl_step_timeout() # Start timeout for server's SASL result numeric
        else:
            logger.warning(f"SASL: Received unexpected challenge: {challenge}. Aborting SASL.")
            self._add_status_message(f"SASL: Unexpected challenge '{challenge}'. Aborting.", color_key="error")
            self._handle_failure(f"Unexpected challenge: {challenge}")

    def on_sasl_result_received(self, success: bool, message: str):
        # 1. Trigger: Called by `irc_protocol.handle_rpl_saslsuccess`, `handle_rpl_saslfail`, etc., when a SASL
        #    result numeric (e.g., 903, 904, 905, 906, 907) is received from the server. This is in response
        #    to the client's "AUTHENTICATE <payload>" command containing credentials.
        # 2. Expected State Before:
        #    - `self.sasl_flow_active` is True.
        #    - The client has sent its SASL credentials.
        #    - `success` (method argument) is True if the numeric indicates success (e.g., 903), False otherwise.
        #    - `message` (method argument) contains the textual part of the numeric (e.g., "SASL authentication successful").
        # 3. Key Actions:
        #    - If `success` is True, calls `self._handle_success(message)`.
        #    - If `success` is False, calls `self._handle_failure(message)`.
        # 4. Expected State After (via _handle_success or _handle_failure):
        #    - `self.sasl_authentication_succeeded` is set to True or False.
        #    - `self.sasl_flow_active` is set to False.
        #    - `CapNegotiator` is notified of SASL completion and its success/failure status via `self._notify_completion()`.
        #      This, in turn, may trigger `CapNegotiator.on_sasl_flow_completed()` to send "CAP END".
        #    - A status message indicating SASL success or failure is added to the UI.
        #    - Subsequent step: `CapNegotiator` handles the SASL completion, potentially sending "CAP END".
        #      Then, `RegistrationHandler` proceeds with NICK/USER if CAP/SASL phase is complete.
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is not None:
            logger.info(f"SASL: Received SASL result ({message}), but flow no longer active and already determined. Ignoring.")
            self._cancel_sasl_step_timeout()
            return

        self._cancel_sasl_step_timeout() # SASL result received, cancel timer

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
        self._cancel_sasl_step_timeout() # Ensure timer is cancelled on any failure path
        self._notify_completion(False)

    def notify_sasl_cap_rejected(self):
        """Called by CapNegotiator if the 'sasl' CAP REQ was NAKed."""
        if self.sasl_flow_active:
            logger.warning("SASL CAP was NAKed while SASL flow was presumed active. This shouldn't happen if ACK is awaited first.")
            self._handle_failure("SASL capability rejected by server after initial ACK (or NAK received for REQ).")
        else:
            logger.info("SASL CAP was NAKed. SASL authentication will not proceed.")
            # Ensure state reflects that SASL won't happen
            self.sasl_authentication_initiated = True
            self.sasl_authentication_succeeded = False
            self.sasl_flow_active = False
            self._cancel_sasl_step_timeout()
            self._notify_completion(False)


    def abort_authentication(self, reason: str):
        """Public method to abort an ongoing SASL authentication externally if needed."""
        if self.sasl_flow_active:
            logger.warning(f"SASL: Authentication aborted externally. Reason: {reason}")
            self._add_status_message(f"SASL: Authentication aborted. Reason: {reason}", color_key="warning")
            self._handle_failure(f"Aborted: {reason}")
        else:
            logger.info(f"SASL: Request to abort, but no SASL flow active. Reason: {reason}")
            self._cancel_sasl_step_timeout()

    def _notify_completion(self, success: bool):
        """Notifies the CapNegotiator that the SASL flow has completed."""
        if self.cap_negotiator:
            self.cap_negotiator.on_sasl_flow_completed(success)
        else:
            logger.error("SaslAuthenticator has no CapNegotiator reference to notify completion.")

    def reset_authentication_state(self):
        """Resets SASL state, typically on disconnect or new negotiation."""
        logger.debug("Resetting SaslAuthenticator state.")
        self._cancel_sasl_step_timeout()
        self.sasl_authentication_initiated = False
        self.sasl_flow_active = False
        self.sasl_authentication_succeeded = None
