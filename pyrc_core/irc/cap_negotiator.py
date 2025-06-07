# pyrc_core/irc/cap_negotiator.py
import threading
import logging
from typing import Set, List, TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pyrc_core.network_handler import NetworkHandler
    from pyrc_core.irc.sasl_authenticator import SaslAuthenticator
    from pyrc_core.irc.registration_handler import RegistrationHandler
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.cap")


class CapNegotiator:
    def __init__(
        self,
        network_handler: "NetworkHandler",
        desired_caps: Set[str], # Already fixed to be a Set
        registration_handler: Optional["RegistrationHandler"] = None,
        client_logic_ref: Optional["IRCClient_Logic"] = None,
    ):
        logger.debug("CapNegotiator: Initializing.")
        self.network_handler = network_handler
        self.registration_handler = registration_handler
        self.sasl_authenticator: Optional["SaslAuthenticator"] = None
        self.client_logic_ref = client_logic_ref

        self.supported_caps: Set[str] = set()
        self.requested_caps: Set[str] = set()
        self.enabled_caps: Set[str] = set()
        self.desired_caps: Set[str] = desired_caps # Ensure this is a copy or handled if modified

        self.cap_negotiation_pending: bool = False
        self.cap_negotiation_finished_event = threading.Event()
        self.initial_cap_flow_complete_event = threading.Event()

        self.negotiation_timeout_seconds: float = 30.0
        self._negotiation_timer: Optional[threading.Timer] = None

        # Timeout for the entire CAP negotiation process
        self.negotiation_timeout_seconds: float = 30.0 # Configurable?
        self._negotiation_timer: Optional[threading.Timer] = None


    def _start_negotiation_timeout_timer(self):
        self._cancel_negotiation_timeout_timer() # Cancel any existing timer
        if self.negotiation_timeout_seconds > 0:
            logger.debug(f"CapNegotiator: Starting negotiation timeout timer ({self.negotiation_timeout_seconds}s).")
            self._negotiation_timer = threading.Timer(self.negotiation_timeout_seconds, self._handle_negotiation_timeout)
            self._negotiation_timer.daemon = True
            self._negotiation_timer.start()

    def _cancel_negotiation_timeout_timer(self):
        if self._negotiation_timer and self._negotiation_timer.is_alive():
            logger.debug("CapNegotiator: Cancelling negotiation timeout timer.")
            self._negotiation_timer.cancel()
        self._negotiation_timer = None

    def _handle_negotiation_timeout(self):
        if not self.cap_negotiation_pending:
            logger.debug("CapNegotiator: Timeout handled, but negotiation no longer pending.")
            return

        logger.warning("CapNegotiator: CAP negotiation timed out.")
        self._add_status_message("CAP negotiation timed out with server.", "error")
        # Mark negotiation as failed/ended and allow registration to proceed (possibly without desired caps)
        self.cap_negotiation_pending = False
        self.initial_cap_flow_complete_event.set() # Allow registration to proceed
        self.cap_negotiation_finished_event.set()   # Overall CAP process is done (failed)

        if self.sasl_authenticator and self.sasl_authenticator.is_flow_active():
            self.sasl_authenticator.abort_authentication("CAP negotiation timeout")

        if self.registration_handler:
            # Ensure CAP END is sent if we were stuck before it
            if not self.initial_cap_flow_complete_event.is_set(): # Defensive, should be set above
                 self.network_handler.send_cap_end() # Try to end it cleanly if possible
            self.registration_handler.on_cap_negotiation_complete()


    def set_sasl_authenticator(self, sasl_authenticator: "SaslAuthenticator"):
        self.sasl_authenticator = sasl_authenticator

    def set_registration_handler(self, registration_handler: "RegistrationHandler"):
        self.registration_handler = registration_handler

    def _add_status_message(self, message: str, color_key: str = "system"):
        if self.client_logic_ref and hasattr(self.client_logic_ref, '_add_status_message'):
            self.client_logic_ref._add_status_message(message, color_key)
        elif self.client_logic_ref:
            logger.warning("CapNegotiator: client_logic_ref._add_status_message not found.")
            # Fallback logging or direct message adding if necessary

    def start_negotiation(self):
        if self.cap_negotiation_pending:
            logger.warning("CapNegotiator: start_negotiation called while already pending. Resetting.")
            self.reset_negotiation_state() # Reset to ensure clean start

        if self.network_handler.connected:
            self.cap_negotiation_pending = True
            self.cap_negotiation_finished_event.clear()
            self.initial_cap_flow_complete_event.clear()
            self.enabled_caps.clear()
            self.supported_caps.clear()
            self.requested_caps.clear()

            self._add_status_message("Negotiating capabilities with server (CAP)...")
            self.network_handler.send_cap_ls()
            self._start_negotiation_timeout_timer()
        else:
            logger.warning("CapNegotiator.start_negotiation called but not connected.")
            self._add_status_message("Cannot initiate CAP: Not connected.", "error")
            # Ensure events are set if negotiation can't start, to prevent deadlocks
            self.initial_cap_flow_complete_event.set()
            self.cap_negotiation_finished_event.set()


    def on_cap_ls_received(self, capabilities_str: str):
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP LS but negotiation is not pending. Ignoring.")
            return

        is_multi_line_in_progress = ' * ' in capabilities_str # Simplified check
        clean_caps_str = capabilities_str.replace(' * ', ' ')
        self.supported_caps.update(clean_caps_str.split())

        if is_multi_line_in_progress:
            logger.debug(f"Accumulated multi-line CAP LS: {clean_caps_str}")
            return # Wait for the final line

        logger.info(f"Final CAP LS received. Total supported caps: {len(self.supported_caps)}")
        self._add_status_message(
            f"Server supports CAP: {', '.join(sorted(list(self.supported_caps))) if self.supported_caps else 'None'}"
        )

        caps_to_request = list(self.desired_caps.intersection(self.supported_caps))

        if "sasl" in caps_to_request:
            if not self.sasl_authenticator or not self.sasl_authenticator.has_credentials():
                logger.info("SASL is supported, but no credentials or authenticator. Removing from request.")
                caps_to_request.remove("sasl")
                self._add_status_message("SASL available but no credentials; skipping.", "warning")
            elif not self.sasl_authenticator: # Should not happen if logic is correct
                logger.error("SASL in desired/supported caps, but sasl_authenticator is None!")
                caps_to_request.remove("sasl")


        if caps_to_request:
            self.requested_caps.update(caps_to_request)
            self._add_status_message(f"Requesting CAP: {', '.join(caps_to_request)}")
            self.network_handler.send_cap_req(caps_to_request)
        else:
            self._add_status_message("No desired capabilities supported or to request. Ending CAP negotiation.")
            self._finalize_cap_negotiation_phase()

    def _finalize_cap_negotiation_phase(self):
        """Called when client decides to send CAP END (no SASL, or no caps to request)."""
        logger.debug("CapNegotiator: Finalizing client-side CAP negotiation phase (sending CAP END).")
        self.network_handler.send_cap_end()
        self.initial_cap_flow_complete_event.set() # NICK/USER can proceed
        # Overall CAP negotiation is not finished yet; server needs to confirm CAP END or send 001.
        # self.cap_negotiation_finished_event will be set by on_cap_end_confirmed or SASL completion.
        if self.registration_handler:
            self.registration_handler.on_cap_negotiation_complete()


    def on_cap_ack_received(self, acked_caps_str: str):
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
            # CAP END is deferred until SASL flow completes. initial_cap_flow_complete_event also defers.
        elif not self.requested_caps: # All other requested caps (non-SASL) are ACKed/NAKed
            if not (self.sasl_authenticator and self.sasl_authenticator.is_flow_active()):
                self._add_status_message("All requested capabilities processed. Ending CAP negotiation.")
                self._finalize_cap_negotiation_phase()
            # If SASL flow is active, _finalize_cap_negotiation_phase will be called by on_sasl_flow_completed.

    def on_cap_nak_received(self, naked_caps_str: str):
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP NAK but negotiation is not pending. Ignoring.")
            return

        naked_caps_list = naked_caps_str.split()
        rejected_caps = []

        for cap in naked_caps_list:
            if cap in self.requested_caps:
                self.requested_caps.remove(cap)
            if cap in self.enabled_caps: # Should not be enabled if NAKed, but defensive
                self.enabled_caps.remove(cap)
            rejected_caps.append(cap)
            if cap == "sasl" and self.sasl_authenticator:
                self.sasl_authenticator.notify_sasl_cap_rejected() # Inform SASL authenticator

        if rejected_caps:
            self._add_status_message(f"CAP NAK (rejected): {', '.join(rejected_caps)}")

        if not self.requested_caps: # All other requested caps (non-SASL) are ACKed/NAKed
            if not (self.sasl_authenticator and self.sasl_authenticator.is_flow_active()):
                self._add_status_message("All requested capabilities processed (some NAKed). Ending CAP negotiation.")
                self._finalize_cap_negotiation_phase()


    def on_cap_new_received(self, new_caps_str: str):
        # Logic for CAP NEW (less critical for initial connection flow)
        new_caps = set(new_caps_str.split())
        self.supported_caps.update(new_caps)
        self._add_status_message(f"CAP NEW: Server now additionally supports {', '.join(new_caps)}.")
        # Potentially auto-request if in desired_caps, or notify user. For now, just log.

    def on_cap_del_received(self, deleted_caps_str: str):
        # Logic for CAP DEL
        deleted_caps = set(deleted_caps_str.split())
        self.supported_caps.difference_update(deleted_caps)
        disabled_now = self.enabled_caps.intersection(deleted_caps)
        self.enabled_caps.difference_update(deleted_caps)
        self._add_status_message(f"CAP DEL: Server no longer supports {', '.join(deleted_caps)}. Disabled: {', '.join(disabled_now) if disabled_now else 'None'}")
        if "sasl" in disabled_now and self.sasl_authenticator and self.sasl_authenticator.is_flow_active():
            self.sasl_authenticator.abort_authentication("SASL capability deleted by server")

    def on_cap_end_confirmed(self):
        """Called when server confirms CAP END (e.g., by 001 or server sending CAP END)."""
        if not self.cap_negotiation_pending and self.cap_negotiation_finished_event.is_set():
            logger.debug("CapNegotiator: on_cap_end_confirmed called, but negotiation already finalized. Ignoring.")
            return

        logger.info("CAP END confirmed by server (e.g., via 001 or server CAP END).")
        self._add_status_message("CAP negotiation finalized with server.")
        self._cancel_negotiation_timeout_timer() # CAP negotiation is successful or server-ended

        self.cap_negotiation_pending = False
        self.initial_cap_flow_complete_event.set() # Ensure this is set
        self.cap_negotiation_finished_event.set()  # Overall CAP process is now truly done

        if self.registration_handler and not self.registration_handler.nick_user_sent:
            logger.info("CAP END confirmed; ensuring registration proceeds if it hasn't (e.g. due to 001).")
            self.registration_handler.on_cap_negotiation_complete()

    def on_sasl_flow_completed(self, success: bool):
        """Callback from SaslAuthenticator when SASL flow finishes."""
        logger.info(f"SASL flow completed. Success: {success}. Current CAP pending: {self.cap_negotiation_pending}")

        if self.cap_negotiation_pending: # If CAP END was deferred waiting for SASL
            if not self.requested_caps: # Ensure no other non-SASL caps are pending REQ
                logger.info(f"SASL flow completed (success: {success}). Finalizing CAP negotiation by sending CAP END.")
                self._add_status_message(f"SASL flow completed. Finalizing CAP negotiation.")
                self._finalize_cap_negotiation_phase() # This sends CAP END and sets initial_cap_flow_complete_event
            else:
                logger.info(f"SASL flow completed, but other caps {self.requested_caps} still pending. CAP END deferred.")
        else: # SASL completed, but CAP negotiation wasn't pending on it (e.g. CAP END already sent or timed out)
            logger.info("SASL flow completed. CAP negotiation was not actively pending on it.")
            # Ensure overall state reflects completion
            self.initial_cap_flow_complete_event.set() # Should already be set if CAP END was sent
            self.cap_negotiation_finished_event.set()
            self._cancel_negotiation_timeout_timer() # SASL finished, so main negotiation part is done

        # If registration hasn't happened, this is another chance.
        if self.registration_handler and not self.registration_handler.nick_user_sent and self.initial_cap_flow_complete_event.is_set():
            self.registration_handler.on_cap_negotiation_complete()


    def is_cap_enabled(self, cap_name: str) -> bool:
        return cap_name in self.enabled_caps

    def get_enabled_caps(self) -> Set[str]:
        return self.enabled_caps.copy()

    def wait_for_negotiation_finish(self, timeout: Optional[float] = 5.0) -> bool:
        return self.cap_negotiation_finished_event.wait(timeout)

    def wait_for_initial_flow_completion(self, timeout: Optional[float] = 5.0) -> bool:
        return self.initial_cap_flow_complete_event.wait(timeout)

    def reset_negotiation_state(self):
        logger.debug("CapNegotiator: reset_negotiation_state called.")
        self._cancel_negotiation_timeout_timer()
        self.supported_caps.clear()
        self.requested_caps.clear()
        self.enabled_caps.clear()
        self.cap_negotiation_pending = False
        self.cap_negotiation_finished_event.clear()
        self.initial_cap_flow_complete_event.clear()
        if self.sasl_authenticator:
            self.sasl_authenticator.reset_authentication_state()
        logger.debug("CapNegotiator: reset_negotiation_state finished.")
