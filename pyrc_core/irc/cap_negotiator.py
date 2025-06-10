# pyrc_core/irc/cap_negotiator.py
import inspect
# import threading # Removed
import logging
import asyncio
from typing import Set, List, TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pyrc_core.network_handler import NetworkHandler
    from pyrc_core.irc.sasl_authenticator import SaslAuthenticator
    from pyrc_core.irc.registration_handler import RegistrationHandler
    from pyrc_core.client.irc_client_logic import IRCClient_Logic


class CapNegotiator:
    logger = logging.getLogger("pyrc.cap")
    def __init__(
        self,
        network_handler: "NetworkHandler",
        desired_caps: Set[str],
        registration_handler: Optional["RegistrationHandler"] = None,
        client_logic_ref: Optional["IRCClient_Logic"] = None,
    ):
        self.logger.debug("CapNegotiator: Initializing.")
        self.network_handler = network_handler
        self.registration_handler = registration_handler
        self.sasl_authenticator: Optional["SaslAuthenticator"] = None
        self.client_logic_ref = client_logic_ref

        self.supported_caps: Set[str] = set()
        self.requested_caps: Set[str] = set()
        self.enabled_caps: Set[str] = set()
        self.desired_caps: Set[str] = desired_caps

        self.cap_negotiation_pending: bool = False
        self.cap_negotiation_finished_event = asyncio.Event() # Changed to asyncio.Event
        self.initial_cap_flow_complete_event = asyncio.Event() # Changed to asyncio.Event

        self.negotiation_timeout_seconds: float = 60.0
        self._negotiation_timeout_task: Optional[asyncio.Task] = None # Replaced timer with task
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.logger.warning("CapNegotiator: No running asyncio event loop found during init.")
            self.loop = None
        self._negotiation_lock = asyncio.Lock()

    async def _run_negotiation_timeout(self):
        try:
            await asyncio.sleep(self.negotiation_timeout_seconds)
            self.logger.debug(f"CapNegotiator: Negotiation timeout task triggered after {self.negotiation_timeout_seconds}s.")
            if self.cap_negotiation_pending: # Check if still relevant
                await self._handle_negotiation_timeout()
        except asyncio.CancelledError:
            self.logger.debug("CapNegotiator: Negotiation timeout task cancelled.")
            # asyncio.CancelledError should propagate if not handled here
        except Exception as e:
            self.logger.error(f"CapNegotiator: Error in negotiation timeout task: {e}", exc_info=True)

    async def _handle_negotiation_timeout(self):
        if not self.cap_negotiation_pending:
            self.logger.debug("CapNegotiator: Timeout handled, but negotiation no longer pending.")
            return

        self.logger.warning("CapNegotiator: CAP negotiation timed out.")
        if self.client_logic_ref:
            await self.add_status_message("CAP negotiation timed out with server.", "error")

        self.cap_negotiation_pending = False
        self.initial_cap_flow_complete_event.set()
        self.cap_negotiation_finished_event.set()

        if self.sasl_authenticator and self.sasl_authenticator.is_flow_active():
            await self.sasl_authenticator.abort_authentication("CAP negotiation timeout")

        if self.registration_handler:
            # Check if initial_cap_flow_complete_event was set by this timeout path
            # If CAP END was not sent because we timed out before _finalize_cap_negotiation_phase
            # we might need to send it here, or rely on registration_handler to proceed.
            # The original logic had:
            # if not self.initial_cap_flow_complete_event.is_set():
            #    await self.network_handler.send_cap_end()
            # This seems complex as initial_cap_flow_complete_event is set right above.
            # For now, let's assume registration_handler.on_cap_negotiation_complete handles it.
            await self.registration_handler.on_cap_negotiation_complete()

    def set_sasl_authenticator(self, sasl_authenticator: "SaslAuthenticator"):
        self.sasl_authenticator = sasl_authenticator

    def set_registration_handler(self, registration_handler: "RegistrationHandler"):
        self.registration_handler = registration_handler

    async def add_status_message(self, message: str, color_key: str):
        if self.client_logic_ref:
            if hasattr(self.client_logic_ref, 'add_status_message') and callable(self.client_logic_ref.add_status_message):
                await self.client_logic_ref.add_status_message(message, color_key)
            else:
                self.logger.warning(f"CapNegotiator: client_logic_ref.add_status_message not found or not callable. Message: {message} ({color_key}).")
        else:
            self.logger.warning(f"CapNegotiator: client_logic_ref is None. Message: {message} ({color_key}).")

    async def start_negotiation(self):
        stack = inspect.stack()
        self.logger.info(f"CapNegotiator.start_negotiation called by {stack[1].filename}:{stack[1].lineno} - {stack[1].function}. Current cap_negotiation_pending={self.cap_negotiation_pending}, network_connected={self.network_handler.connected if self.network_handler else 'N/A'}")

        async with self._negotiation_lock:
            self.logger.info(f"CapNegotiator.start_negotiation: Lock acquired. cap_negotiation_pending was {self.cap_negotiation_pending}.")

            if self.cap_negotiation_pending: # Re-entrancy check
                self.logger.warning("CapNegotiator: start_negotiation called while already pending. Current negotiation will proceed or timeout. Exiting this redundant call.")
                return

            self.cap_negotiation_pending = True
            self.logger.info(f"CapNegotiator.start_negotiation: Set cap_negotiation_pending=True.")
            self.cap_negotiation_finished_event.clear()
            self.initial_cap_flow_complete_event.clear()
            self.enabled_caps.clear()
            self.supported_caps.clear()
            self.requested_caps.clear()

            try:
                if not self.loop:
                    try:
                        self.loop = asyncio.get_running_loop()
                    except RuntimeError:
                        self.logger.error("CapNegotiator.start_negotiation: No running asyncio event loop.")
                        await self.add_status_message("Internal error: CAP negotiation cannot start (no event loop).", "error")
                        self.cap_negotiation_pending = False
                        self.cap_negotiation_finished_event.set()
                        self.initial_cap_flow_complete_event.set()
                        return

                if self.network_handler and self.network_handler.connected:
                    await self.add_status_message("Negotiating capabilities with server (CAP)...", "system")
                    self.logger.info("CapNegotiator: ABOUT TO SEND CAP LS.")
                    await self.network_handler.send_cap_ls()
                    self.logger.info("CapNegotiator: CAP LS SENT SUCCESSFULLY.")
                    # Start timeout task
                    if self._negotiation_timeout_task and not self._negotiation_timeout_task.done():
                        self._negotiation_timeout_task.cancel()
                    if self.negotiation_timeout_seconds > 0:
                        self.logger.debug(f"CapNegotiator: Starting negotiation timeout task ({self.negotiation_timeout_seconds}s).")
                        self._negotiation_timeout_task = asyncio.create_task(self._run_negotiation_timeout())
                else:
                    self.logger.warning("CapNegotiator.start_negotiation: Network not connected when expected. Cannot send CAP LS.")
                    await self.add_status_message("Cannot initiate CAP: Network not connected as expected.", "error")
                    self.cap_negotiation_pending = False
                    self.initial_cap_flow_complete_event.set()
                    self.cap_negotiation_finished_event.set()
                    if self._negotiation_timeout_task and not self._negotiation_timeout_task.done():
                        self._negotiation_timeout_task.cancel()
                    self._negotiation_timeout_task = None

            except Exception as e:
                self.logger.error(f"Error during CAP negotiation setup: {e}", exc_info=True)
                await self.add_status_message(f"Error starting CAP negotiation: {e}", "error")
                self.cap_negotiation_pending = False
                self.cap_negotiation_finished_event.set()
                self.initial_cap_flow_complete_event.set()
                if self._negotiation_timeout_task and not self._negotiation_timeout_task.done():
                    self._negotiation_timeout_task.cancel()
                self._negotiation_timeout_task = None

    async def on_cap_ls_received(self, capabilities_str: str):
        self.logger.info(f"CapNegotiator: Processing CAP LS response: {capabilities_str.strip()}")
        self.logger.debug(f"on_cap_ls_received called, cap_negotiation_pending={self.cap_negotiation_pending}")
        if not self.cap_negotiation_pending:
            self.logger.warning(f"Received CAP LS but negotiation is not pending. Ignoring. cap_negotiation_pending={self.cap_negotiation_pending}")
            return

        is_multi_line_in_progress = ' * ' in capabilities_str
        clean_caps_str = capabilities_str.replace(' * ', ' ')
        self.supported_caps.update(clean_caps_str.split())

        if is_multi_line_in_progress:
            self.logger.debug(f"Accumulated multi-line CAP LS: {clean_caps_str}")
            return

        self.logger.info(f"Final CAP LS received. Total supported caps: {len(self.supported_caps)}")
        await self.add_status_message(
            f"Server supports CAP: {', '.join(sorted(list(self.supported_caps))) if self.supported_caps else 'None'}", "system"
        )

        caps_to_request = list(self.desired_caps.intersection(self.supported_caps))

        if "sasl" in caps_to_request:
            if not self.sasl_authenticator or not self.sasl_authenticator.has_credentials():
                self.logger.info("SASL is supported, but no credentials or authenticator. Removing from request.")
                if "sasl" in caps_to_request: caps_to_request.remove("sasl")
                await self.add_status_message("SASL available but no credentials; skipping.", "warning")
            elif not self.sasl_authenticator:
                self.logger.error("SASL in desired/supported caps, but sasl_authenticator is None!")
                if "sasl" in caps_to_request: caps_to_request.remove("sasl")

        if caps_to_request:
            self.requested_caps.update(caps_to_request)
            await self.add_status_message(f"Requesting CAP: {', '.join(caps_to_request)}", "system")
            await self.network_handler.send_cap_req(caps_to_request)
        else:
            await self.add_status_message("No desired capabilities supported or to request. Ending CAP negotiation.", "system")
            await self._finalize_cap_negotiation_phase()

    async def _finalize_cap_negotiation_phase(self):
        if not self.cap_negotiation_pending:
            self.logger.debug("CapNegotiator: _finalize_cap_negotiation_phase called but negotiation not pending. Ignoring.")
            return

        self.logger.debug("CapNegotiator: Finalizing client-side CAP negotiation phase (sending CAP END).")
        await self.network_handler.send_cap_end()
        self.initial_cap_flow_complete_event.set()

        self.cap_negotiation_pending = False
        if self._negotiation_timeout_task and not self._negotiation_timeout_task.done():
            self._negotiation_timeout_task.cancel()
        self._negotiation_timeout_task = None
        self.cap_negotiation_finished_event.set()
        self.logger.info("CapNegotiator: CAP negotiation phase finalized. cap_negotiation_pending=False.")

        if self.registration_handler:
            await self.registration_handler.on_cap_negotiation_complete()

    async def on_cap_ack_received(self, acked_caps_str: str):
        self.logger.info(f"CapNegotiator: Processing CAP ACK response: {acked_caps_str.strip()}")
        if not hasattr(self, 'cap_negotiation_pending') or not self.cap_negotiation_pending:
            self.logger.warning(f"Received CAP ACK but negotiation is not pending. Ignoring. cap_negotiation_pending={getattr(self, 'cap_negotiation_pending', 'N/A')}")
            return

        if not hasattr(self, 'network_handler') or not self.network_handler.connected:
            self.logger.error("Received CAP ACK but network handler not connected")
            self.cap_negotiation_pending = False
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
            await self.add_status_message(f"CAP ACK: {', '.join(newly_acked)}", "system")

        if sasl_was_just_acked:
            if self.sasl_authenticator and self.sasl_authenticator.has_credentials():
                self.logger.info("SASL ACKed. Initiating SASL authentication.")
                authenticator = self.sasl_authenticator
                assert authenticator is not None
                if inspect.iscoroutinefunction(authenticator.start_authentication):
                    await authenticator.start_authentication()
                else:
                    self.logger.error("CapNegotiator: authenticator.start_authentication is not a coroutine function!")
            else:
                self.logger.warning("SASL ACKed but no authenticator or credentials. Cannot start SASL.")
                if not self.requested_caps:
                    await self.add_status_message("SASL ACKed but unusable. Ending CAP negotiation.", "warning")
                    await self._finalize_cap_negotiation_phase()

        elif not self.requested_caps:
            if not (self.sasl_authenticator and self.sasl_authenticator.is_flow_active()):
                await self.add_status_message("All requested capabilities processed. Ending CAP negotiation.", "system")
                await self._finalize_cap_negotiation_phase()
            else:
                self.logger.info("All CAPs ACKed/NAKed, but SASL flow is active. CAP END deferred.")

    async def on_cap_nak_received(self, naked_caps_str: str):
        self.logger.info(f"CapNegotiator: Processing CAP NAK response: {naked_caps_str.strip()}")
        if not self.cap_negotiation_pending:
            self.logger.warning("Received CAP NAK but negotiation is not pending. Ignoring.")
            return

        naked_caps_list = naked_caps_str.split()
        rejected_caps = []

        for cap in naked_caps_list:
            if cap in self.requested_caps:
                self.requested_caps.remove(cap)
            if cap in self.enabled_caps:
                self.enabled_caps.remove(cap)
            rejected_caps.append(cap)
            if cap == "sasl" and self.sasl_authenticator:
                await self.sasl_authenticator.notify_sasl_cap_rejected()

        if rejected_caps:
            await self.add_status_message(f"CAP NAK (rejected): {', '.join(rejected_caps)}", "system")

        if not self.requested_caps:
            if not (self.sasl_authenticator and self.sasl_authenticator.is_flow_active()):
                await self.add_status_message("All requested capabilities processed (some NAKed). Ending CAP negotiation.", "system")
                await self._finalize_cap_negotiation_phase()
            else:
                self.logger.info("All CAPs NAKed, but SASL flow is active. CAP END deferred.")

    async def on_cap_new_received(self, new_caps_str: str):
        new_caps = set(new_caps_str.split())
        self.supported_caps.update(new_caps)
        await self.add_status_message(f"CAP NEW: Server now additionally supports {', '.join(new_caps)}.", "system")

    async def on_cap_del_received(self, deleted_caps_str: str):
        deleted_caps = set(deleted_caps_str.split())
        self.supported_caps.difference_update(deleted_caps)
        disabled_now = self.enabled_caps.intersection(deleted_caps)
        self.enabled_caps.difference_update(deleted_caps)
        await self.add_status_message(
            f"CAP DEL: Server no longer supports {', '.join(deleted_caps)}. Disabled: {', '.join(disabled_now) if disabled_now else 'None'}", "system"
        )
        if "sasl" in disabled_now and self.sasl_authenticator and self.sasl_authenticator.is_flow_active():
            await self.sasl_authenticator.abort_authentication("SASL capability deleted by server")

    async def on_cap_end_confirmed(self):
        if not self.cap_negotiation_pending and self.cap_negotiation_finished_event.is_set():
            self.logger.debug("CapNegotiator: on_cap_end_confirmed called, but negotiation already finalized. Ignoring.")
            return

        self.logger.info("CAP END confirmed by server (e.g., via 001 or server CAP END).")
        await self.add_status_message("CAP negotiation finalized with server.", "system")

        if self.registration_handler and not self.registration_handler.nick_user_sent:
            self.logger.info("CAP END confirmed; ensuring registration proceeds if it hasn't.")
            await self.registration_handler.on_cap_negotiation_complete()

    async def on_sasl_flow_completed(self, success: bool):
        self.logger.info(f"SASL flow completed. Success: {success}. Current CAP pending: {self.cap_negotiation_pending}")

        if self.cap_negotiation_pending:
            if not self.requested_caps:
                self.logger.info(f"SASL flow completed (success: {success}). All other CAPs processed. Finalizing CAP negotiation.")
                await self.add_status_message(f"SASL flow completed. Finalizing CAP negotiation.", "system")
                await self._finalize_cap_negotiation_phase()
            else:
                self.logger.info(f"SASL flow completed, but other caps {self.requested_caps} still pending. CAP END deferred.")
        else:
            self.logger.info("SASL flow completed. CAP negotiation was not actively pending on it (already finalized or timed out).")
            self.initial_cap_flow_complete_event.set()
            self.cap_negotiation_finished_event.set()
            if self._negotiation_timeout_task and not self._negotiation_timeout_task.done():
                self._negotiation_timeout_task.cancel()
            self._negotiation_timeout_task = None

        if self.registration_handler and not self.registration_handler.nick_user_sent and self.initial_cap_flow_complete_event.is_set():
            await self.registration_handler.on_cap_negotiation_complete()

    def is_cap_enabled(self, cap_name: str) -> bool:
        return cap_name in self.enabled_caps

    def get_enabled_caps(self) -> Set[str]:
        return self.enabled_caps.copy()

    async def wait_for_negotiation_finish(self, timeout: Optional[float] = 5.0) -> bool:
        if not self.loop:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                self.logger.error("CapNegotiator.wait_for_negotiation_finish: No running asyncio event loop.")
                return False
        try:
            await asyncio.wait_for(self.cap_negotiation_finished_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            self.logger.debug(f"CapNegotiator: Timeout waiting for negotiation finish event after {timeout}s.")
            return False
        except Exception as e:
            self.logger.error(f"CapNegotiator: Error in wait_for_negotiation_finish: {e}", exc_info=True)
            return False

    async def wait_for_initial_flow_completion(self, timeout: Optional[float] = 5.0) -> bool:
        if not self.loop:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                self.logger.error("CapNegotiator.wait_for_initial_flow_completion: No running asyncio event loop.")
                return False
        try:
            await asyncio.wait_for(self.initial_cap_flow_complete_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            self.logger.debug(f"CapNegotiator: Timeout waiting for initial flow completion event after {timeout}s.")
            return False
        except Exception as e:
            self.logger.error(f"CapNegotiator: Error in wait_for_initial_flow_completion: {e}", exc_info=True)
            return False

    async def reset_negotiation_state(self):
        self.logger.debug("CapNegotiator: reset_negotiation_state called.")
        if self._negotiation_timeout_task and not self._negotiation_timeout_task.done():
            self._negotiation_timeout_task.cancel()
        self._negotiation_timeout_task = None
        self.supported_caps.clear()
        self.requested_caps.clear()
        self.enabled_caps.clear()
        self.cap_negotiation_pending = False
        self.cap_negotiation_finished_event.clear()
        self.initial_cap_flow_complete_event.clear()
        if self.sasl_authenticator:
            # Assuming sasl_authenticator.reset_authentication_state() is already async or safe to call
            self.sasl_authenticator.reset_authentication_state() # Ensure this is awaited if it becomes async
        self.logger.debug("CapNegotiator: reset_negotiation_state finished.")
