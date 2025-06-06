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
        desired_caps: Set[str],
        registration_handler: Optional["RegistrationHandler"] = None,
        client_logic_ref: Optional["IRCClient_Logic"] = None,
    ):
        logger.debug("CapNegotiator: Initializing.")
        self.network_handler = network_handler
        self.registration_handler = registration_handler
        self.sasl_authenticator: Optional["SaslAuthenticator"] = None
        self.client_logic_ref = client_logic_ref

        self.supported_caps: Set[str] = set()
        self.requested_caps: Set[str] = (
            set()
        )  # Caps we have sent REQ for and are awaiting ACK/NAK
        self.enabled_caps: Set[str] = set()  # Caps confirmed active by ACK
        self.desired_caps: Set[str] = desired_caps.copy()

        self.cap_negotiation_pending: bool = False # Initial state
        logger.debug(f"CapNegotiator: __init__ - cap_negotiation_pending set to {self.cap_negotiation_pending}")
        self.cap_negotiation_finished_event = (
            threading.Event()
        )  # Signals CAP negotiation (including SASL if part of it) is done

        # This event specifically signals that CAP LS, REQ, ACK/NAK, and END (if no SASL) is complete,
        # or that SASL has completed and CAP END has been sent.
        # It's what RegistrationHandler would wait on before proceeding with NICK/USER.
        self.initial_cap_flow_complete_event = threading.Event()

    def set_sasl_authenticator(self, sasl_authenticator: "SaslAuthenticator"):
        self.sasl_authenticator = sasl_authenticator

    def set_registration_handler(self, registration_handler: "RegistrationHandler"):
        """Sets the RegistrationHandler instance after initialization."""
        self.registration_handler = registration_handler

    def _add_status_message(self, message: str, color_key: str = "system"):
        logger.info(f"[CapNegotiator Status via Client] {message}") # Keep local log
        if self.client_logic_ref and hasattr(self.client_logic_ref, '_add_status_message'):
            self.client_logic_ref._add_status_message(message, color_key)
        elif self.client_logic_ref: # Fallback if _add_status_message somehow not found (defensive)
            logger.warning("CapNegotiator: client_logic_ref._add_status_message not found, using direct add_message.")
            color_attr = self.client_logic_ref.ui.colors.get(
                color_key, self.client_logic_ref.ui.colors["system"]
            )
            self.client_logic_ref.add_message(
                message, color_attr, context_name="Status"
            )

    def start_negotiation(self):
        """Initiates CAP negotiation by sending CAP LS."""
        logger.debug(f"CapNegotiator: start_negotiation called. Current pending: {self.cap_negotiation_pending}")
        if self.network_handler.connected:
            self.cap_negotiation_pending = True
            logger.debug(f"CapNegotiator: start_negotiation - cap_negotiation_pending set to {self.cap_negotiation_pending}")
            self.cap_negotiation_finished_event.clear()
            self.initial_cap_flow_complete_event.clear()
            self.enabled_caps.clear()
            self.supported_caps.clear()
            self.requested_caps.clear()

            self._add_status_message("Negotiating capabilities with server (CAP)...")
            self.network_handler.send_cap_ls()  # Assumes version 302 by default in NetworkHandler
        else:
            logger.warning("CapNegotiator.start_negotiation called but not connected. Current pending: {self.cap_negotiation_pending}")
            self._add_status_message("Cannot initiate CAP: Not connected.", "error")
        logger.debug(f"CapNegotiator: start_negotiation finished. Current pending: {self.cap_negotiation_pending}")

    def on_cap_ls_received(self, capabilities_str: str):
        """Handles the server's response to CAP LS, including multi-line responses."""
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP LS but negotiation is not pending. Ignoring.")
            return

        # Check for multi-line indicator. The subcommand is the second parameter.
        # e.g., :server CAP * LS * :cap-list
        # The presence of '*' as a param before the trailing message indicates more data.
        # We'll check if the raw string contains ' * ' before the capabilities. A bit of a heuristic.
        is_multi_line_in_progress = ' * ' in capabilities_str

        # Clean the capabilities string from any multi-line markers
        clean_caps_str = capabilities_str.replace(' * ', ' ')
        self.supported_caps.update(clean_caps_str.split())

        # If this is part of a multi-line response, just accumulate and wait for the final line.
        if is_multi_line_in_progress:
            logger.debug(f"Accumulated multi-line CAP LS: {clean_caps_str}")
            return

        # This is the final (or only) CAP LS line. Now we can proceed.
        logger.info(f"Final CAP LS received. Total supported caps: {len(self.supported_caps)}")
        self._add_status_message(
            f"Server supports CAP: {', '.join(sorted(list(self.supported_caps))) if self.supported_caps else 'None'}"
        )

        caps_to_request = list(self.desired_caps.intersection(self.supported_caps))

        if "sasl" in caps_to_request:
            if not self.sasl_authenticator or not self.sasl_authenticator.has_credentials():
                logger.info("SASL is supported, but no credentials. Removing from request.")
                caps_to_request.remove("sasl")
                self._add_status_message("SASL available but no credentials; skipping.", "warning")

        if caps_to_request:
            self.requested_caps.update(caps_to_request)
            self._add_status_message(f"Requesting CAP: {', '.join(caps_to_request)}")
            self.network_handler.send_cap_req(caps_to_request)
        else:
            self._add_status_message("No desired capabilities supported. Ending CAP negotiation.")
            self.network_handler.send_cap_end()
            self.initial_cap_flow_complete_event.set()
            if self.registration_handler:
                self.registration_handler.on_cap_negotiation_complete()

    def on_cap_ack_received(self, acked_caps_str: str):
        """Handles CAP ACK from the server."""
        logger.debug(f"CapNegotiator: on_cap_ack_received called. Current pending: {self.cap_negotiation_pending}")
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP ACK but negotiation is not pending. Ignoring. This should not happen.")
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

        if (
            sasl_was_just_acked
            and self.sasl_authenticator
            and self.sasl_authenticator.has_credentials()
        ):
            logger.info("SASL ACKed. Initiating SASL authentication.")
            self.sasl_authenticator.start_authentication()
            # CAP END will be deferred until SASL flow completes.
        elif not self.requested_caps:
            # If SASL flow is active (started due to ACK), wait for it.
            # Otherwise, if no SASL or SASL not active, send CAP END.
            if not (
                self.sasl_authenticator and self.sasl_authenticator.is_flow_active()
            ):
                self._add_status_message(
                    "All requested capabilities processed. Ending CAP negotiation."
                )
                self.network_handler.send_cap_end()
                # If CAP END is sent here, it means initial client-side CAP flow is done.
                self.initial_cap_flow_complete_event.set()
                if self.registration_handler:
                    self.registration_handler.on_cap_negotiation_complete()

                # If no SASL involved, this is also the end of the overall CAP process.
                if not (
                    "sasl" in self.enabled_caps
                    and self.sasl_authenticator
                    and self.sasl_authenticator.is_flow_active()
                ):
                    self.cap_negotiation_finished_event.set()
                    self.cap_negotiation_pending = False
                    logger.debug(f"CapNegotiator: on_cap_ack_received - cap_negotiation_pending set to {self.cap_negotiation_pending}")
        logger.debug(f"CapNegotiator: on_cap_ack_received finished. Current pending: {self.cap_negotiation_pending}")

    def on_cap_nak_received(self, naked_caps_str: str):
        """Handles CAP NAK from the server."""
        logger.debug(f"CapNegotiator: on_cap_nak_received called. Current pending: {self.cap_negotiation_pending}")
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP NAK but negotiation is not pending. Ignoring. This should not happen.")
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
            if not (
                self.sasl_authenticator and self.sasl_authenticator.is_flow_active()
            ):
                self._add_status_message(
                    "All requested capabilities processed (some NAKed). Ending CAP negotiation."
                )
                self.network_handler.send_cap_end()
                self.initial_cap_flow_complete_event.set()
                if self.registration_handler:
                    self.registration_handler.on_cap_negotiation_complete()

                if not (
                    "sasl" in self.enabled_caps
                    and self.sasl_authenticator
                    and self.sasl_authenticator.is_flow_active()
                ):
                    self.cap_negotiation_finished_event.set()
                    self.cap_negotiation_pending = False
                    logger.debug(f"CapNegotiator: on_cap_nak_received - cap_negotiation_pending set to {self.cap_negotiation_pending}")
        logger.debug(f"CapNegotiator: on_cap_nak_received finished. Current pending: {self.cap_negotiation_pending}")

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
            if (
                "sasl" in disabled_now
                and self.sasl_authenticator
                and self.sasl_authenticator.is_flow_active()
            ):
                logger.warning(
                    "SASL capability was deleted by server during active SASL flow. Aborting SASL."
                )
                self.sasl_authenticator.abort_authentication(
                    "SASL capability deleted by server"
                )
        self._add_status_message(msg)

    def on_cap_end_confirmed(self):
        """Called when the server confirms CAP END (e.g. by sending CAP END itself or by 001)."""
        logger.info(f"CAP END confirmed by server. Current pending: {self.cap_negotiation_pending}")
        self._add_status_message("CAP negotiation finalized with server.")

        # This method is called when the SERVER confirms CAP END (e.g. by sending CAP END itself, or via 001).
        # The NICK/USER registration should have ideally been triggered by the CLIENT sending CAP END.
        self.cap_negotiation_pending = False
        logger.debug(f"CapNegotiator: on_cap_end_confirmed - cap_negotiation_pending set to {self.cap_negotiation_pending}")
        self.initial_cap_flow_complete_event.set()  # Redundant if already set, but safe
        self.cap_negotiation_finished_event.set()

        # If RegistrationHandler hasn't proceeded yet (e.g. 001 came before client sent CAP END and triggered it),
        # this is a fallback point.
        if self.registration_handler and not self.registration_handler.nick_user_sent:
            logger.info(
                "CAP END confirmed by server; ensuring registration handler proceeds if it hasn't."
            )
            self.registration_handler.on_cap_negotiation_complete()  # Safe to call again; it checks nick_user_sent
        logger.debug(f"CapNegotiator: on_cap_end_confirmed finished. Current pending: {self.cap_negotiation_pending}")

    def on_sasl_flow_completed(self, success: bool):
        """Callback from SaslAuthenticator when SASL flow finishes."""
        logger.debug(f"CapNegotiator: on_sasl_flow_completed called. Success: {success}. Current pending: {self.cap_negotiation_pending}")
        logger.info(
            f"SASL flow completed. Success: {success}. Checking if CAP END needs to be sent."
        )
        # If CAP negotiation was pending on SASL completion (i.e. CAP END was not yet sent)
        if self.cap_negotiation_pending:
            if not self.requested_caps:  # Ensure no other non-SASL caps are pending REQ
                logger.info(
                    f"SASL flow completed (success: {success}). Sending CAP END."
                )
                self._add_status_message(
                    f"SASL flow completed. Finalizing CAP negotiation."
                )
                self.network_handler.send_cap_end()
                # After sending CAP END, the client-side CAP flow is done. Registration can proceed.
                self.initial_cap_flow_complete_event.set()
                if self.registration_handler:
                    self.registration_handler.on_cap_negotiation_complete()
                # cap_negotiation_finished_event will be set by on_cap_end_confirmed
            else:
                logger.info(
                    f"SASL flow completed, but other caps {self.requested_caps} still pending. CAP END deferred."
                )
        else:
            # SASL completed, but CAP negotiation wasn't pending on it (e.g. CAP END already sent).
            # Ensure overall state is consistent.
            logger.info(
                "SASL flow completed. CAP negotiation was not actively pending on it."
            )
            self.initial_cap_flow_complete_event.set()
            self.cap_negotiation_finished_event.set()
            self.cap_negotiation_pending = False
            logger.debug(f"CapNegotiator: on_sasl_flow_completed - cap_negotiation_pending set to {self.cap_negotiation_pending}")
            # If registration hasn't happened, this is another chance.
            if (
                self.registration_handler
                and not self.registration_handler.nick_user_sent
            ):
                self.registration_handler.on_cap_negotiation_complete()
        logger.debug(f"CapNegotiator: on_sasl_flow_completed finished. Current pending: {self.cap_negotiation_pending}")

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
        logger.debug(f"CapNegotiator: reset_negotiation_state called. Current pending: {self.cap_negotiation_pending}")
        self.supported_caps.clear()
        self.requested_caps.clear()
        self.enabled_caps.clear()
        self.cap_negotiation_pending = False
        logger.debug(f"CapNegotiator: reset_negotiation_state - cap_negotiation_pending set to {self.cap_negotiation_pending}")
        self.cap_negotiation_finished_event.clear()
        self.initial_cap_flow_complete_event.clear()
        if self.sasl_authenticator:
            self.sasl_authenticator.reset_authentication_state()  # Also reset SASL if it's linked
        logger.debug(f"CapNegotiator: reset_negotiation_state finished. Current pending: {self.cap_negotiation_pending}")
