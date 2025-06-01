import threading
import logging
from typing import Set, List, TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from network_handler import NetworkHandler
    from sasl_authenticator import SaslAuthenticator
    from registration_handler import RegistrationHandler
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.cap")

class CapNegotiator:
    def __init__(self,
                 network_handler: 'NetworkHandler',
                 desired_caps: Set[str],
                 registration_handler: Optional['RegistrationHandler'] = None,
                 client_logic_ref: Optional['IRCClient_Logic'] = None):
        self.network_handler = network_handler
        self.registration_handler = registration_handler
        self.sasl_authenticator: Optional['SaslAuthenticator'] = None
        self.client_logic_ref = client_logic_ref

        self.supported_caps: Set[str] = set()
        self.requested_caps: Set[str] = set() # Caps we have sent REQ for and are awaiting ACK/NAK
        self.enabled_caps: Set[str] = set()   # Caps confirmed active by ACK
        self.desired_caps: Set[str] = desired_caps.copy()

        self.cap_negotiation_pending: bool = False
        self.cap_negotiation_finished_event = threading.Event() # Signals CAP negotiation (including SASL if part of it) is done

        # This event specifically signals that CAP LS, REQ, ACK/NAK, and END (if no SASL) is complete,
        # or that SASL has completed and CAP END has been sent.
        # It's what RegistrationHandler would wait on before proceeding with NICK/USER.
        self.initial_cap_flow_complete_event = threading.Event()


    def set_sasl_authenticator(self, sasl_authenticator: 'SaslAuthenticator'):
        self.sasl_authenticator = sasl_authenticator

    def set_registration_handler(self, registration_handler: 'RegistrationHandler'):
        """Sets the RegistrationHandler instance after initialization."""
        self.registration_handler = registration_handler

    def _add_status_message(self, message: str, color_key: str = "system"):
        logger.info(f"[CapNegotiator Status] {message}")
        if self.client_logic_ref:
            color_attr = self.client_logic_ref.ui.colors.get(color_key, self.client_logic_ref.ui.colors["system"])
            self.client_logic_ref.add_message(
                message,
                color_attr,
                context_name="Status"
            )


    def start_negotiation(self):
        # 1. Trigger: Called by `NetworkHandler._connect_socket()` immediately after a successful TCP/IP (and SSL, if applicable)
        #    connection to the IRC server has been established.
        # 2. Expected State Before:
        #    - `self.network_handler.connected` is True.
        #    - `self.network_handler.sock` is an active, connected socket.
        #    - CAP negotiation state variables (`cap_negotiation_pending`, events, cap sets) are typically in their initial/reset state.
        # 3. Key Actions:
        #    - Sets `self.cap_negotiation_pending` to True.
        #    - Clears `self.cap_negotiation_finished_event` and `self.initial_cap_flow_complete_event`.
        #    - Clears internal capability sets (`enabled_caps`, `supported_caps`, `requested_caps`).
        #    - Adds a status message to the UI indicating CAP negotiation is starting.
        #    - Calls `self.network_handler.send_cap_ls()` to send the "CAP LS [version]" command to the server,
        #      requesting a list of its supported capabilities.
        # 4. Expected State After:
        #    - `self.cap_negotiation_pending` is True.
        #    - Relevant event flags are cleared.
        #    - The "CAP LS" command has been sent to the server via `NetworkHandler`.
        #    - The client is now waiting for the server to respond with "CAP * LS ..." messages.
        #    - Subsequent step: The server's "CAP * LS" response will be handled by `self.on_cap_ls_received()`.
        """Initiates CAP negotiation by sending CAP LS."""
        if self.network_handler.connected:
            self.cap_negotiation_pending = True
            self.cap_negotiation_finished_event.clear()
            self.initial_cap_flow_complete_event.clear()
            self.enabled_caps.clear()
            self.supported_caps.clear()
            self.requested_caps.clear()

            self._add_status_message("Negotiating capabilities with server (CAP)...")
            self.network_handler.send_cap_ls() # Assumes version 302 by default in NetworkHandler
        else:
            logger.warning("CapNegotiator.start_negotiation called but not connected.")
            self._add_status_message("Cannot initiate CAP: Not connected.", "error")

    def on_cap_ls_received(self, capabilities_str: str):
        # 1. Trigger: Called by `irc_protocol.handle_cap()` when a "CAP * LS" message is received from the server.
        #    This is in response to the client's "CAP LS" command sent by `self.start_negotiation()`.
        #    A server might send multiple "CAP * LS" lines if the list is long (multi-line LS).
        # 2. Expected State Before:
        #    - `self.cap_negotiation_pending` is True.
        #    - The client has sent "CAP LS" and is awaiting the server's list of supported capabilities.
        #    - `capabilities_str` contains the space-separated list of capabilities from one "CAP * LS" line.
        # 3. Key Actions:
        #    - If `cap_negotiation_pending` is False, ignores the message.
        #    - Parses `capabilities_str` and adds the capabilities to `self.supported_caps`.
        #    - Adds a status message listing the (newly) supported capabilities.
        #    - Determines `caps_to_request` by intersecting `self.desired_caps` with `self.supported_caps`.
        #    - If "sasl" is in `caps_to_request` but SASL is not configured (no authenticator or credentials),
        #      "sasl" is removed from `caps_to_request`.
        #    - If `caps_to_request` is not empty:
        #        - Adds these capabilities to `self.requested_caps`.
        #        - Adds a status message listing the capabilities being requested.
        #        - Calls `self.network_handler.send_cap_req()` to send "CAP REQ :cap1 cap2..." to the server.
        #    - If `caps_to_request` is empty (no common desired and supported caps, or SASL was filtered out):
        #        - Adds a status message indicating no capabilities will be requested.
        #        - Calls `self.network_handler.send_cap_end()` to terminate CAP negotiation.
        #        - Sets `self.initial_cap_flow_complete_event` and `self.cap_negotiation_finished_event`.
        #        - Sets `self.cap_negotiation_pending` to False.
        #        - Calls `self.registration_handler.on_cap_negotiation_complete()` to allow NICK/USER registration.
        # 4. Expected State After:
        #    - If capabilities were requested:
        #        - `self.requested_caps` is populated.
        #        - "CAP REQ" command has been sent.
        #        - Client is waiting for "CAP * ACK" or "CAP * NAK" responses.
        #        - Subsequent step: `self.on_cap_ack_received()` or `self.on_cap_nak_received()`.
        #    - If no capabilities were requested (or CAP END sent):
        #        - `self.cap_negotiation_pending` is False.
        #        - `initial_cap_flow_complete_event` and `cap_negotiation_finished_event` are set.
        #        - CAP negotiation is considered finished from the client's perspective.
        #        - NICK/USER registration is enabled via `RegistrationHandler`.
        """Handles the server's response to CAP LS."""
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP LS but negotiation is not pending. Ignoring.")
            return

        self.supported_caps = set(capabilities_str.split())
        self._add_status_message(f"Server supports CAP: {', '.join(self.supported_caps) if self.supported_caps else 'None'}")

        caps_to_request = list(self.desired_caps.intersection(self.supported_caps))

        if "sasl" in caps_to_request:
            if not self.sasl_authenticator or not self.sasl_authenticator.has_credentials():
                logger.info("SASL is supported and desired, but no SASL authenticator or credentials. Removing SASL from request.")
                caps_to_request.remove("sasl")
                self._add_status_message("SASL capability available but no credentials/authenticator; skipping SASL request.", "warning")

        if caps_to_request:
            self.requested_caps.update(caps_to_request)
            self._add_status_message(f"Requesting CAP: {', '.join(caps_to_request)}")
            self.network_handler.send_cap_req(caps_to_request)
        else:
            self._add_status_message("No desired and supported capabilities to request. Ending CAP negotiation.")
            self.network_handler.send_cap_end()
            # If no caps requested, initial flow is done, signal for registration
            self.initial_cap_flow_complete_event.set()
            self.cap_negotiation_finished_event.set()
            self.cap_negotiation_pending = False
            if self.registration_handler:
                self.registration_handler.on_cap_negotiation_complete()


    def on_cap_ack_received(self, acked_caps_str: str):
        # 1. Trigger: Called by `irc_protocol.handle_cap()` when a "CAP * ACK :cap1 cap2..." message is received from the server.
        #    This is in response to the client's "CAP REQ" command.
        # 2. Expected State Before:
        #    - `self.cap_negotiation_pending` is True.
        #    - The client has sent "CAP REQ" for one or more capabilities.
        #    - `self.requested_caps` contains the set of capabilities for which a response (ACK/NAK) is awaited.
        #    - `acked_caps_str` contains the space-separated list of capabilities acknowledged by the server.
        # 3. Key Actions:
        #    - If `cap_negotiation_pending` is False, ignores the message.
        #    - Parses `acked_caps_str`. For each acknowledged capability:
        #        - Adds it to `self.enabled_caps`.
        #        - Removes it from `self.requested_caps`.
        #        - Records if "sasl" was among the acknowledged capabilities (`sasl_was_just_acked`).
        #    - Adds a status message listing the newly acknowledged capabilities.
        #    - If `sasl_was_just_acked` and SASL is configured and has credentials:
        #        - Calls `self.sasl_authenticator.start_authentication()` to begin the SASL handshake.
        #        - Sending "CAP END" is deferred until the SASL flow completes (handled by `on_sasl_flow_completed`).
        #    - Else if `self.requested_caps` is now empty (all requested capabilities have received a response)
        #      AND SASL authentication is not currently active (either not ACKed, not configured, or already completed/failed):
        #        - Calls `self.network_handler.send_cap_end()` to terminate CAP negotiation.
        #        - Sets `self.initial_cap_flow_complete_event`.
        #        - Calls `self.registration_handler.on_cap_negotiation_complete()` to allow NICK/USER registration.
        #        - If SASL is not enabled or its flow is not active, sets `self.cap_negotiation_finished_event`
        #          and sets `self.cap_negotiation_pending` to False.
        # 4. Expected State After:
        #    - Acknowledged capabilities are moved from `self.requested_caps` to `self.enabled_caps`.
        #    - If "sasl" was ACKed and is viable: SASL authentication process is initiated. "CAP END" is deferred.
        #    - If all requested capabilities are resolved and SASL is not a pending factor:
        #        - "CAP END" is sent.
        #        - `initial_cap_flow_complete_event` is set.
        #        - NICK/USER registration is enabled.
        #        - `cap_negotiation_finished_event` might be set and `cap_negotiation_pending` becomes False.
        #    - Subsequent step: If SASL started, `SaslAuthenticator` handles its flow. If "CAP END" sent, client waits for server
        #      confirmation of CAP END (e.g., 001) or proceeds with registration. If more ACKs/NAKs are expected for other
        #      capabilities (less common if server batches ACKs), waits for those.
        """Handles CAP ACK from the server."""
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP ACK but negotiation is not pending. Ignoring.")
            return

        acked_caps_list = acked_caps_str.split()
        newly_acked = []
        sasl_was_just_acked = False

        for cap in acked_caps_list:
            self.enabled_caps.add(cap)
            if cap in self.requested_caps:
                self.requested_caps.remove(cap)
            newly_acked.append(cap)
            if cap == "sasl":
                sasl_was_just_acked = True

        if newly_acked:
            self._add_status_message(f"CAP ACK: {', '.join(newly_acked)}")

        if sasl_was_just_acked and self.sasl_authenticator and self.sasl_authenticator.has_credentials():
            logger.info("SASL ACKed. Initiating SASL authentication.")
            self.sasl_authenticator.start_authentication()
            # CAP END will be deferred until SASL flow completes.
        elif not self.requested_caps:
            # If SASL flow is active (started due to ACK), wait for it.
            # Otherwise, if no SASL or SASL not active, send CAP END.
            if not (self.sasl_authenticator and self.sasl_authenticator.is_flow_active()):
                self._add_status_message("All requested capabilities processed. Ending CAP negotiation.")
                self.network_handler.send_cap_end()
                # If CAP END is sent here, it means initial client-side CAP flow is done.
                self.initial_cap_flow_complete_event.set()
                if self.registration_handler:
                    self.registration_handler.on_cap_negotiation_complete()

                # If no SASL involved, this is also the end of the overall CAP process.
                if not ("sasl" in self.enabled_caps and self.sasl_authenticator and self.sasl_authenticator.is_flow_active()):
                    self.cap_negotiation_finished_event.set()
                    self.cap_negotiation_pending = False


    def on_cap_nak_received(self, naked_caps_str: str):
        # 1. Trigger: Called by `irc_protocol.handle_cap()` when a "CAP * NAK :cap1 cap2..." message is received from the server.
        #    This is in response to the client's "CAP REQ" command.
        # 2. Expected State Before:
        #    - `self.cap_negotiation_pending` is True.
        #    - The client has sent "CAP REQ" for one or more capabilities.
        #    - `self.requested_caps` contains the set of capabilities for which a response (ACK/NAK) is awaited.
        #    - `naked_caps_str` contains the space-separated list of capabilities rejected (NAK'd) by the server.
        # 3. Key Actions:
        #    - If `cap_negotiation_pending` is False, ignores the message.
        #    - Parses `naked_caps_str`. For each NAK'd capability:
        #        - Removes it from `self.requested_caps`.
        #        - Ensures it's not in `self.enabled_caps`.
        #        - If "sasl" was NAK'd and SASL authenticator exists, calls `sasl_authenticator.notify_sasl_cap_rejected()`.
        #    - Adds a status message listing the rejected capabilities.
        #    - If `self.requested_caps` is now empty (all requested capabilities have received a response)
        #      AND SASL authentication is not currently active:
        #        - Calls `self.network_handler.send_cap_end()` to terminate CAP negotiation.
        #        - Sets `self.initial_cap_flow_complete_event`.
        #        - Calls `self.registration_handler.on_cap_negotiation_complete()` to allow NICK/USER registration.
        #        - If SASL is not enabled or its flow is not active, sets `self.cap_negotiation_finished_event`
        #          and sets `self.cap_negotiation_pending` to False.
        # 4. Expected State After:
        #    - NAK'd capabilities are removed from `self.requested_caps`. They are not added to `self.enabled_caps`.
        #    - If "sasl" was NAK'd, the SASL authenticator is informed, potentially altering SASL flow.
        #    - If all requested capabilities are resolved and SASL is not a pending factor:
        #        - "CAP END" is sent.
        #        - `initial_cap_flow_complete_event` is set.
        #        - NICK/USER registration is enabled.
        #        - `cap_negotiation_finished_event` might be set and `cap_negotiation_pending` becomes False.
        #    - Subsequent step: If "CAP END" sent, client waits for server confirmation or proceeds with registration.
        #      If other capabilities were requested and are still pending ACK/NAK, waits for those.
        """Handles CAP NAK from the server."""
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP NAK but negotiation is not pending. Ignoring.")
            return

        naked_caps_list = naked_caps_str.split()
        rejected = []
        sasl_was_naked = False

        for cap in naked_caps_list:
            if cap in self.requested_caps:
                self.requested_caps.remove(cap)
            if cap in self.enabled_caps:
                self.enabled_caps.remove(cap)
            rejected.append(cap)
            if cap == "sasl" and self.sasl_authenticator:
                sasl_was_naked = True
                self.sasl_authenticator.notify_sasl_cap_rejected()


        if rejected:
            self._add_status_message(f"CAP NAK (rejected): {', '.join(rejected)}")

        if not self.requested_caps:
            if not (self.sasl_authenticator and self.sasl_authenticator.is_flow_active()):
                self._add_status_message("All requested capabilities processed (some NAKed). Ending CAP negotiation.")
                self.network_handler.send_cap_end()
                self.initial_cap_flow_complete_event.set()
                if self.registration_handler:
                    self.registration_handler.on_cap_negotiation_complete()

                if not ("sasl" in self.enabled_caps and self.sasl_authenticator and self.sasl_authenticator.is_flow_active()):
                    self.cap_negotiation_finished_event.set()
                    self.cap_negotiation_pending = False


    def on_cap_new_received(self, new_caps_str: str):
        """Handles CAP NEW from the server."""
        new_caps = set(new_caps_str.split())
        self.supported_caps.update(new_caps)
        # Auto-enable newly supported caps if they are in our desired list and not already enabled
        auto_enabled_now = new_caps.intersection(self.desired_caps) - self.enabled_caps

        newly_added_to_enabled = set()
        for cap_to_enable in auto_enabled_now:
            # Potentially, we could send a CAP REQ for these new ones if we want to explicitly enable them.
            # For now, just adding to enabled_caps if they are desired.
            # Some servers might auto-enable them, some might expect a REQ.
            # Let's assume for now they are auto-enabled if NEW is sent for a desired cap.
            # Or, more safely, just update supported_caps and let a user command handle enabling if needed.
            # For simplicity, let's say if it's desired, we mark it enabled.
            self.enabled_caps.add(cap_to_enable)
            newly_added_to_enabled.add(cap_to_enable)

        msg = f"CAP NEW: Server now supports {', '.join(new_caps)}."
        if newly_added_to_enabled:
            msg += f" Auto-enabled desired: {', '.join(newly_added_to_enabled)}."
        self._add_status_message(msg)


    def on_cap_del_received(self, deleted_caps_str: str):
        """Handles CAP DEL from the server."""
        deleted_caps = set(deleted_caps_str.split())
        disabled_now = self.enabled_caps.intersection(deleted_caps)

        self.supported_caps.difference_update(deleted_caps)
        self.enabled_caps.difference_update(deleted_caps)

        msg = f"CAP DEL: Server no longer supports {', '.join(deleted_caps)}."
        if disabled_now:
            msg += f" Disabled: {', '.join(disabled_now)}."
            if "sasl" in disabled_now and self.sasl_authenticator and self.sasl_authenticator.is_flow_active():
                logger.warning("SASL capability was deleted by server during active SASL flow. Aborting SASL.")
                self.sasl_authenticator.abort_authentication("SASL capability deleted by server")
        self._add_status_message(msg)

    def on_cap_end_confirmed(self):
        """Called when the server confirms CAP END (e.g. by sending CAP END itself or by 001)."""
        logger.info("CAP END confirmed by server.")
        self._add_status_message("CAP negotiation finalized with server.")

        # This method is called when the SERVER confirms CAP END (e.g. by sending CAP END itself, or via 001).
        # The NICK/USER registration should have ideally been triggered by the CLIENT sending CAP END.
        self.cap_negotiation_pending = False
        self.initial_cap_flow_complete_event.set() # Redundant if already set, but safe
        self.cap_negotiation_finished_event.set()

        # If RegistrationHandler hasn't proceeded yet (e.g. 001 came before client sent CAP END and triggered it),
        # this is a fallback point.
        if self.registration_handler and not self.registration_handler.nick_user_sent:
            logger.info("CAP END confirmed by server; ensuring registration handler proceeds if it hasn't.")
            self.registration_handler.on_cap_negotiation_complete() # Safe to call again; it checks nick_user_sent

    def on_sasl_flow_completed(self, success: bool):
        # 1. Trigger: Called by `SaslAuthenticator.finish_authentication()` when the SASL authentication process
        #    (successful or failed) concludes. This happens after the server responds to the client's
        #    `AUTHENTICATE` messages (e.g., with 903, 904, etc.).
        # 2. Expected State Before:
        #    - `self.cap_negotiation_pending` might be True (if CAP END was deferred pending SASL).
        #    - The 'sasl' capability was ACKed by the server.
        #    - `SaslAuthenticator.is_flow_active()` was True and is now transitioning to False.
        #    - `success` (method argument) indicates if SASL authentication was successful.
        # 3. Key Actions:
        #    - Logs the completion of the SASL flow and its success status.
        #    - If `self.cap_negotiation_pending` is True AND there are no other non-SASL capabilities still awaiting an ACK/NAK
        #      (i.e., `self.requested_caps` is empty):
        #        - Sends "CAP END" via `self.network_handler.send_cap_end()`. This is critical because CAP END
        #          was deferred if SASL was active.
        #        - Sets `self.initial_cap_flow_complete_event`. This signals that the initial phase of CAP negotiation
        #          (including SASL, if used) is complete, allowing NICK/USER registration to proceed.
        #        - Calls `self.registration_handler.on_cap_negotiation_complete()`.
        #    - If `self.cap_negotiation_pending` is False (e.g., CAP END was already sent for some reason, or SASL completed
        #      after the main CAP flow was thought to be over):
        #        - Ensures `initial_cap_flow_complete_event` and `cap_negotiation_finished_event` are set.
        #        - Sets `self.cap_negotiation_pending` to False.
        #        - Potentially calls `self.registration_handler.on_cap_negotiation_complete()` if NICK/USER hasn't been sent.
        # 4. Expected State After:
        #    - If CAP END was sent:
        #        - The "CAP END" command is transmitted to the server.
        #        - `self.initial_cap_flow_complete_event` is set.
        #        - `RegistrationHandler` is notified to proceed with NICK/USER.
        #        - The overall `cap_negotiation_finished_event` will typically be set by `on_cap_end_confirmed`
        #          when the server acknowledges the CAP END (e.g., via RPL_WELCOME or another CAP END).
        #    - If CAP END was not sent (e.g., other caps still pending, or CAP was not pending on SASL):
        #        - State is updated to reflect SASL completion, but CAP END sending might be handled elsewhere or later.
        #    - Subsequent step: `RegistrationHandler` proceeds with NICK/USER if `initial_cap_flow_complete_event` is set.
        #      The server will eventually confirm CAP END (often implicitly with 001).
        """Callback from SaslAuthenticator when SASL flow finishes."""
        logger.info(f"SASL flow completed. Success: {success}. Checking if CAP END needs to be sent.")
        # If CAP negotiation was pending on SASL completion (i.e. CAP END was not yet sent)
        if self.cap_negotiation_pending:
            if not self.requested_caps: # Ensure no other non-SASL caps are pending REQ
                logger.info(f"SASL flow completed (success: {success}). Sending CAP END.")
                self._add_status_message(f"SASL flow completed. Finalizing CAP negotiation.")
                self.network_handler.send_cap_end()
                # After sending CAP END, the client-side CAP flow is done. Registration can proceed.
                self.initial_cap_flow_complete_event.set()
                if self.registration_handler:
                    self.registration_handler.on_cap_negotiation_complete()
                # cap_negotiation_finished_event will be set by on_cap_end_confirmed
            else:
                logger.info(f"SASL flow completed, but other caps {self.requested_caps} still pending. CAP END deferred.")
        else:
            # SASL completed, but CAP negotiation wasn't pending on it (e.g. CAP END already sent).
            # Ensure overall state is consistent.
            logger.info("SASL flow completed. CAP negotiation was not actively pending on it.")
            self.initial_cap_flow_complete_event.set()
            self.cap_negotiation_finished_event.set()
            self.cap_negotiation_pending = False
            # If registration hasn't happened, this is another chance.
            if self.registration_handler and not self.registration_handler.nick_user_sent:
                 self.registration_handler.on_cap_negotiation_complete()

    def is_cap_negotiation_pending(self) -> bool:
        return self.cap_negotiation_pending

    def is_cap_enabled(self, cap_name: str) -> bool:
        return cap_name in self.enabled_caps

    def get_enabled_caps(self) -> Set[str]:
        return self.enabled_caps.copy()

    def wait_for_negotiation_finish(self, timeout: Optional[float] = 5.0) -> bool:
        """Waits for the cap_negotiation_finished_event."""
        return self.cap_negotiation_finished_event.wait(timeout)

    def wait_for_initial_flow_completion(self, timeout: Optional[float] = 5.0) -> bool:
        """
        Waits for the initial CAP flow (LS, REQ, ACK/NAK, and END if no SASL, or SASL completion if SASL is involved)
        to complete before registration (NICK/USER) can proceed.
        """
        return self.initial_cap_flow_complete_event.wait(timeout)

    def reset_negotiation_state(self):
        """Resets all CAP negotiation state, typically on disconnect."""
        logger.debug("Resetting CapNegotiator state.")
        self.supported_caps.clear()
        self.requested_caps.clear()
        self.enabled_caps.clear()
        self.cap_negotiation_pending = False
        self.cap_negotiation_finished_event.clear()
        self.initial_cap_flow_complete_event.clear()
        if self.sasl_authenticator:
            self.sasl_authenticator.reset_authentication_state() # Also reset SASL if it's linked
