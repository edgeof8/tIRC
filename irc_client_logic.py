# irc_client_logic.py
import curses
import threading
import time
import socket
from collections import deque
from typing import Optional, Any, List, Set, Dict  # Added Set, Dict
import base64
import logging
import os

from config import (
    MAX_HISTORY,
    VERIFY_SSL_CERT, # Import the SSL verification setting
)
from context_manager import ContextManager

from ui_manager import UIManager
from network_handler import NetworkHandler
from command_handler import CommandHandler
from input_handler import InputHandler
from features.triggers.trigger_manager import TriggerManager
from features.triggers.trigger_commands import TriggerCommands
import irc_protocol

logger = logging.getLogger("pyrc.logic")


class IRCClient_Logic:
    def __init__(
        self,
        stdscr,
        server_addr,
        port,
        nick,
        initial_channels_raw: list,
        password,
        nickserv_password,
        use_ssl,
    ):
        self.stdscr = stdscr
        self.server = server_addr  # Will be set by /connect or initial args
        self.port = port
        self.initial_nick = nick
        self.nick = nick

        self.initial_channels_list = []
        if initial_channels_raw and isinstance(initial_channels_raw, list):
            for ch in initial_channels_raw:
                if isinstance(ch, str):
                    processed_ch = ch.lstrip()
                    if not processed_ch.startswith("#"):
                        processed_ch = "#" + processed_ch
                    self.initial_channels_list.append(processed_ch)

        self.currently_joined_channels: Set[str] = (
            set()
        )  # New attribute to track joined channels

        self.password = password
        self.nickserv_password = nickserv_password
        self.use_ssl = use_ssl
        self.verify_ssl_cert = VERIFY_SSL_CERT # Store the config setting
        logger.info(f"IRCClient_Logic.__init__: server='{server_addr}', port={port}, use_ssl={self.use_ssl}, verify_ssl_cert={self.verify_ssl_cert}")
        self.echo_sent_to_status: bool = True  # New setting

        self.context_manager = ContextManager(max_history_per_context=MAX_HISTORY)
        # ... (rest of __init__)
        self.context_manager.create_context("Status", context_type="status")
        self.context_manager.set_active_context("Status")

        for ch_name in self.initial_channels_list:
            self.context_manager.create_context(ch_name, context_type="channel")

        # if self.initial_channels_list: # mIRC behavior: Stay in Status until channel actually joined
        #     self.context_manager.set_active_context(self.initial_channels_list[0])

        self.should_quit = False
        self.ui_needs_update = threading.Event()

        self.supported_caps: Set[str] = set()
        self.requested_caps: Set[str] = set()  # Caps we've sent in CAP REQ
        self.enabled_caps: Set[str] = set()  # Caps ACKed by server
        self.cap_negotiation_pending: bool = False
        self.cap_negotiation_finished_event = (
            threading.Event()
        )  # To signal NICK/USER can proceed
        self.desired_caps: Set[str] = {
            "sasl",
            "multi-prefix",
            "server-time",
            "message-tags",
            "account-tag",
            "echo-message",
            "away-notify",
            "chghost",
            "userhost-in-names",
            "cap-notify",  # For CAP NEW/DEL
            "extended-join",  # If we want to parse extended JOIN info
            "account-notify",  # For account changes
            "invite-notify",  # For server-side invite tracking
        }
        self.sasl_authentication_initiated: bool = (
            False  # To prevent double SASL attempts
        )
        self.sasl_flow_active: bool = False
        self.sasl_authentication_succeeded: Optional[bool] = None

        self.network = NetworkHandler(self)
        self.ui = UIManager(stdscr, self)
        self.command_handler = CommandHandler(self)
        self.input_handler = InputHandler(self)
        self.trigger_manager = TriggerManager(
            os.path.join(os.path.expanduser("~"), ".config", "pyrc")
        )

        self.add_message(
            "Simple IRC Client starting...",
            self.ui.colors["system"],
            context_name="Status",
        )
        initial_channels_display = (
            ", ".join(self.initial_channels_list)
            if self.initial_channels_list
            else "None"
        )
        self.add_message(
            f"Target: {self.server}:{self.port}, Nick: {self.nick}, Channels: {initial_channels_display}",
            self.ui.colors["system"],
            context_name="Status",
        )
        logger.info(
            f"IRCClient_Logic initialized for {self.server}:{self.port} as {self.nick}. Channels: {initial_channels_display}"
        )

    def _add_status_message(self, text: str, color_key: str = "system"):
        """Helper to add a message to the 'Status' context."""
        # Ensure ui.colors is accessible, might need self.ui.colors if ui is always initialized
        # Assuming self.ui is initialized before this can be called indirectly via other methods.
        color_attr = self.ui.colors.get(color_key, self.ui.colors["system"]) # Fallback to system color
        self.add_message(text, color_attr, context_name="Status")

    def add_message(
        self,
        text: str,
        color_attr: int,
        prefix_time: bool = True,
        context_name: Optional[str] = None,
    ):
        target_context_name = (
            context_name
            if context_name is not None
            else self.context_manager.active_context_name
        )
        if not target_context_name:
            logger.error(
                "add_message called with no target_context_name and no active context."
            )
            target_context_name = "Status"

        target_ctx_exists = self.context_manager.get_context(target_context_name)
        if not target_ctx_exists:
            context_type = "generic"
            if target_context_name.startswith("#"):
                context_type = "channel"
            elif target_context_name != "Status" and ":" in target_context_name:
                context_type = "query"

            if self.context_manager.create_context(
                target_context_name, context_type=context_type
            ):
                logger.info(
                    f"Dynamically created context '{target_context_name}' of type '{context_type}' for message."
                )
            else:
                if not self.context_manager.get_context(target_context_name):
                    logger.error(
                        f"FATAL: Failed to ensure context '{target_context_name}' for message. Message lost: {text}"
                    )
                    # Attempt to add to status, but ensure status context itself exists
                    status_ctx_for_error = self.context_manager.get_context("Status")
                    if not status_ctx_for_error:  # Highly unlikely, but guard
                        self.context_manager.create_context(
                            "Status", context_type="status"
                        )

                    self.context_manager.add_message_to_context(
                        "Status",
                        f"Error: Failed to create context '{target_context_name}' for message: {text}",
                        self.ui.colors["error"],
                    )
                    self.ui_needs_update.set()
                    return

        target_context_obj = self.context_manager.get_context(target_context_name)
        if not target_context_obj:
            logger.critical(
                f"Context {target_context_name} is unexpectedly None after creation/check."
            )
            return

        max_w = self.ui.msg_win_width - 1 if self.ui.msg_win_width > 1 else 80
        timestamp = time.strftime("%H:%M:%S ") if prefix_time else ""
        full_message = f"{timestamp}{text}"

        lines = []
        current_line = ""
        for word in full_message.split(" "):
            if len(current_line) + len(word) + 1 > max_w and current_line:
                lines.append(current_line)
                current_line = word
            else:
                if current_line:
                    current_line += " "
                current_line += word
        if current_line:
            lines.append(current_line)

        num_lines_added_for_this_message = len(lines)

        for line_part in lines:
            self.context_manager.add_message_to_context(
                target_context_name, line_part, color_attr, 1
            )

        if target_context_name == self.context_manager.active_context_name:
            if (
                hasattr(target_context_obj, "scrollback_offset")
                and target_context_obj.scrollback_offset > 0
            ):
                target_context_obj.scrollback_offset += num_lines_added_for_this_message

        self.ui_needs_update.set()

    def handle_server_message(self, line: str):
        """Delegate IRC message handling to the protocol handler."""
        irc_protocol.handle_server_message(self, line)

    def switch_active_context(self, direction: str):
        context_names = self.context_manager.get_all_context_names()
        if not context_names:
            return

        # Ensure "Status" is first for numeric indexing if present, then sort others
        if "Status" in context_names:
            sorted_context_names = ["Status"] + sorted(
                [name for name in context_names if name != "Status"]
            )
        else:
            sorted_context_names = sorted(context_names)

        current_active_name = self.context_manager.active_context_name
        if not current_active_name and sorted_context_names:
            current_active_name = sorted_context_names[0]
        elif not current_active_name:
            return

        try:
            current_idx = sorted_context_names.index(current_active_name)
        except ValueError:  # Active context not in sorted list (e.g. just closed)
            current_idx = 0  # Default to first
            if not sorted_context_names:
                return  # No contexts left
            current_active_name = sorted_context_names[0]

        new_active_context_name = None

        if direction == "next":
            new_idx = (current_idx + 1) % len(sorted_context_names)
            new_active_context_name = sorted_context_names[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + len(sorted_context_names)) % len(
                sorted_context_names
            )
            new_active_context_name = sorted_context_names[new_idx]
        else:
            if direction in sorted_context_names:  # Direct name match
                new_active_context_name = direction
            else:
                try:  # Attempt numeric match (1-based)
                    num_idx = int(direction) - 1
                    if 0 <= num_idx < len(sorted_context_names):
                        new_active_context_name = sorted_context_names[num_idx]
                    else:
                        self.add_message(
                            f"Invalid window number: {direction}. Max: {len(sorted_context_names)}",
                            self.ui.colors["error"],
                            context_name=current_active_name,
                        )
                        return
                except ValueError:  # Attempt partial name match
                    found_ctx = [
                        name
                        for name in sorted_context_names
                        if direction.lower() in name.lower()
                    ]
                    if len(found_ctx) == 1:
                        new_active_context_name = found_ctx[0]
                    elif len(found_ctx) > 1:
                        self.add_message(
                            f"Ambiguous window name '{direction}'. Matches: {', '.join(sorted(found_ctx))}",
                            self.ui.colors["error"],
                            context_name=current_active_name,
                        )
                        return
                    else:
                        self.add_message(
                            f"Window '{direction}' not found.",
                            self.ui.colors["error"],
                            context_name=current_active_name,
                        )
                        return

        if new_active_context_name:
            if self.context_manager.set_active_context(new_active_context_name):
                logger.debug(
                    f"Switched active context to: {self.context_manager.active_context_name}"
                )
                self.ui_needs_update.set()
            else:
                logger.error(
                    f"Failed to set active context to {new_active_context_name} via ContextManager."
                )
                self.add_message(
                    f"Error switching to window '{new_active_context_name}'.",
                    self.ui.colors["error"],
                    context_name=current_active_name,
                )

    def switch_active_channel(self, direction: str):
        """Switches active context only among 'channel' type contexts."""
        all_context_names = self.context_manager.get_all_context_names()

        # Build the list of contexts to cycle through: channels and "Status"
        cyclable_context_names_temp: List[str] = []
        status_context_name_const = "Status"  # Define to avoid typos

        channel_names_only: List[str] = []

        for name in all_context_names:
            context_obj = self.context_manager.get_context(name)
            if context_obj:
                if context_obj.type == "channel":
                    channel_names_only.append(name)
                # "Status" will be added specifically later if it exists

        # Sort channel names alphabetically (case-insensitive)
        channel_names_only.sort(key=lambda x: x.lower())

        # Start with sorted channels
        cyclable_context_names_temp.extend(channel_names_only)

        # Add "Status" to the end if it exists
        if status_context_name_const in all_context_names:
            cyclable_context_names_temp.append(status_context_name_const)

        channel_context_names: List[str] = (
            cyclable_context_names_temp  # Rename for less diff below
        )

        if not channel_context_names:  # Should not be empty if Status always exists
            self.add_message(
                "No channels to switch to.",
                self.ui.colors["system"],
                context_name=self.context_manager.active_context_name or "Status",
            )
            return

        current_active_name_str: Optional[str] = (
            self.context_manager.active_context_name
        )
        current_idx = -1

        # Check if the current active context is a channel and is in our list
        if current_active_name_str:  # Ensure current_active_name_str is not None
            current_active_context_obj = self.context_manager.get_context(
                current_active_name_str
            )
            if (
                current_active_context_obj
                and current_active_context_obj.type == "channel"
            ):
                try:
                    # current_active_name_str is guaranteed to be a string here
                    current_idx = channel_context_names.index(current_active_name_str)
                except ValueError:
                    # This means the current active channel name (which is a channel type)
                    # is somehow not in our filtered & sorted list. Should be rare.
                    # Treat as if not in a known channel.
                    current_idx = -1
                    logger.warning(
                        f"Active channel '{current_active_name_str}' not found in filtered channel list."
                    )

        new_active_channel_name = None
        num_channels = len(channel_context_names)

        if current_idx == -1:
            # If not currently in a known channel, or if current_active_name was None,
            # default to the first channel in the list.
            new_active_channel_name = channel_context_names[0]
        elif direction == "next":
            new_idx = (current_idx + 1) % num_channels
            new_active_channel_name = channel_context_names[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + num_channels) % num_channels
            new_active_channel_name = channel_context_names[new_idx]

        if new_active_channel_name:
            if self.context_manager.set_active_context(new_active_channel_name):
                logger.debug(
                    f"Switched active channel to: {self.context_manager.active_context_name}"
                )
                self.ui_needs_update.set()
            else:
                logger.error(
                    f"Failed to set active channel to {new_active_channel_name}."
                )
                self.add_message(
                    f"Error switching to channel '{new_active_channel_name}'.",
                    self.ui.colors["error"],
                    context_name=current_active_name_str
                    or "Status",  # Use the string version or fallback
                )

    def initiate_cap_negotiation(self):
        """Called by NetworkHandler after connection is established."""
        if self.network.connected:
            self.cap_negotiation_pending = True
            self.cap_negotiation_finished_event.clear()
            self.sasl_authentication_initiated = False  # Reset for new connection
            self.enabled_caps.clear()  # Clear previously enabled caps
            self.supported_caps.clear()
            self.requested_caps.clear()
            self._add_status_message("Negotiating capabilities with server (CAP)...")
            self.network.send_cap_ls()  # Request capabilities list

    def proceed_with_registration(self):
        """Called after CAP negotiation is done or SASL is handled."""
        # Ensure this is called only once per connection attempt after CAP/SASL
        if (
            self.cap_negotiation_finished_event.is_set()
            and not self.cap_negotiation_pending
        ):
            logger.debug(
                "proceed_with_registration called but registration already signaled or not in CAP pending state."
            )
            return

        self.cap_negotiation_pending = False  # Ensure this is false
        self.cap_negotiation_finished_event.set()  # Signal that NICK/USER can be sent
        logger.info(
            "CAP negotiation concluded. Proceeding with NICK/USER registration."
        )
        self._add_status_message("Proceeding with NICK/USER registration.")

        if self.password:
            self.network.send_raw(f"PASS {self.password}")
        self.network.send_raw(f"NICK {self.nick}")
        self.network.send_raw(f"USER {self.nick} 0 * :{self.nick}")

    def handle_cap_ls(self, capabilities_str: str):
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP LS but negotiation is not pending. Ignoring.")
            return

        self.supported_caps = set(capabilities_str.split())
        self._add_status_message(f"Server supports CAP: {', '.join(self.supported_caps) if self.supported_caps else 'None'}")

        caps_to_request = list(self.desired_caps.intersection(self.supported_caps))

        if caps_to_request:
            self.requested_caps.update(caps_to_request)
            self._add_status_message(f"Requesting CAP: {', '.join(caps_to_request)}")
            self.network.send_cap_req(caps_to_request)
            if (
                not self.requested_caps
            ):  # If all requested caps were filtered out (e.g. empty intersection)
                self._add_status_message("No desired and supported capabilities to request. Ending CAP negotiation.")
                self.network.send_cap_end()
                # proceed_with_registration will be called by handle_cap_end_confirmation or 001
        else:
            self._add_status_message("No desired capabilities supported or none to request. Ending CAP negotiation.")
            self.network.send_cap_end()
            # proceed_with_registration will be called by handle_cap_end_confirmation or 001

    def handle_cap_ack(self, acked_caps_str: str):
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP ACK but negotiation is not pending. Ignoring.")
            return

        acked_caps_list = acked_caps_str.split()
        newly_acked = []
        for cap in acked_caps_list:
            self.enabled_caps.add(cap)
            if cap in self.requested_caps:
                self.requested_caps.remove(cap)
            newly_acked.append(cap)

        if newly_acked:
            self._add_status_message(f"CAP ACK: {', '.join(newly_acked)}")

        if "sasl" in self.enabled_caps and not self.sasl_authentication_initiated:
            self.sasl_authentication_initiated = True
            self._add_status_message("SASL capability acknowledged. Future step: Initiate SASL authentication...")
            # Actual SASL logic will be here. For now, we assume it's handled to test CAP END.
            # If SASL were real, it would have its own flow, and CAP END would be after SASL success/failure.

        if (
            not self.requested_caps
        ):  # All *initially* requested caps have been ACKed or NAKed
            # If SASL is part of the flow and not yet completed, wait for SASL.
            if not (
                "sasl" in self.enabled_caps
                and self.sasl_authentication_initiated
                and not self.is_sasl_completed()
            ):
                self._add_status_message("All requested capabilities processed. Ending CAP negotiation.")
                self.network.send_cap_end()
                # proceed_with_registration will be called by handle_cap_end_confirmation or 001

    def handle_cap_nak(self, naked_caps_str: str):
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP NAK but negotiation is not pending. Ignoring.")
            return

        naked_caps_list = naked_caps_str.split()
        rejected = []
        for cap in naked_caps_list:
            if cap in self.requested_caps:
                self.requested_caps.remove(cap)
            if cap in self.enabled_caps:
                self.enabled_caps.remove(cap)
            rejected.append(cap)

        if rejected:
            self._add_status_message(f"CAP NAK (rejected): {', '.join(rejected)}")

        if (
            not self.requested_caps
        ):  # All *initially* requested caps have been ACKed or NAKed
            if not (
                "sasl" in self.enabled_caps
                and self.sasl_authentication_initiated
                and not self.is_sasl_completed()
            ):
                self._add_status_message("All requested capabilities processed (some NAKed). Ending CAP negotiation.")
                self.network.send_cap_end()
                # proceed_with_registration will be called by handle_cap_end_confirmation or 001

    def handle_cap_end_confirmation(self):
        """Called when server confirms CAP END or implicitly (e.g. on 001)."""
        if self.cap_negotiation_pending:  # Only if we were actually pending
            self._add_status_message("CAP negotiation finalized with server.")
            self.cap_negotiation_pending = False  # Mark as no longer pending
            # Only proceed with registration if SASL is not enabled/initiated OR if it's completed
            if not (
                "sasl" in self.enabled_caps
                and self.sasl_authentication_initiated
                and not self.is_sasl_completed()
            ):
                if (
                    not self.cap_negotiation_finished_event.is_set()
                ):  # Avoid double registration
                    self.proceed_with_registration()
            else:
                logger.info(
                    "CAP END confirmed, but SASL is active and not yet completed. Registration deferred."
                )
        elif not self.cap_negotiation_finished_event.is_set():
            # If CAP wasn't 'pending' but registration hasn't happened, e.g. server sent 001 early
            logger.info(
                "CAP END confirmation received, but CAP was not marked pending. Ensuring registration proceeds if not already done."
            )
            self.proceed_with_registration()

    # SASL Authentication Handlers
    def initiate_sasl_plain_authentication(self):
        if not self.nickserv_password:
            self._add_status_message("SASL: NickServ password not set. Skipping SASL.", color_key="warning")
            logger.warning("SASL: NickServ password not set. Skipping SASL.")
            self.sasl_authentication_succeeded = (
                False  # Mark as failed to allow CAP END
            )
            self.sasl_flow_active = False
            # If CAP END was deferred for SASL, send it now
            if (
                "sasl" in self.enabled_caps and self.cap_negotiation_pending
            ):  # Check if CAP was pending for SASL
                self._add_status_message("SASL skipped. Proceeding to end CAP negotiation.")
                self.network.send_cap_end()  # Server will confirm, then registration
            return

        self._add_status_message("SASL: Initiating PLAIN authentication...")
        logger.info("SASL: Initiating PLAIN authentication.")
        self.sasl_flow_active = True
        self.sasl_authentication_succeeded = None  # Reset status
        payload_str = f"{self.nick}\0{self.nick}\0{self.nickserv_password}"
        # payload_b64 = base64.b64encode(payload_str.encode('utf-8')).decode('utf-8') # Credentials sent after challenge
        self.network.send_authenticate(
            "PLAIN"
        )  # Inform server we are starting PLAIN, server responds with AUTHENTICATE +

    def handle_sasl_authenticate_challenge(self, challenge: str):
        if not self.sasl_flow_active:
            logger.warning(
                "SASL: Received AUTHENTICATE challenge but SASL flow not active. Ignoring."
            )
            return

        if challenge == "+":  # Standard challenge for PLAIN, expecting credentials
            logger.info("SASL: Received '+' challenge. Sending PLAIN credentials.")
            payload_str = f"{self.nick}\0{self.nick}\0{self.nickserv_password}"
            payload_b64 = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")

            masked_payload_str = f"{self.nick}\0{self.nick}\0********"
            masked_payload_b64 = base64.b64encode(
                masked_payload_str.encode("utf-8")
            ).decode("utf-8")
            logger.debug(
                f"SASL: Sending AUTHENTICATE payload (masked): {masked_payload_b64}"
            )

            self.network.send_authenticate(payload_b64)
        else:
            logger.warning(
                f"SASL: Received unexpected challenge: {challenge}. Aborting SASL."
            )
            self._add_status_message(f"SASL: Unexpected challenge '{challenge}'. Aborting.", color_key="error")
            self.handle_sasl_failure(f"Unexpected challenge: {challenge}")

    def handle_sasl_success(self, message: str):
        if not self.sasl_flow_active:
            logger.info(
                f"SASL: Received SASL success ({message}), but flow no longer active. Assuming already handled or connection proceeded."
            )
            return

        logger.info(f"SASL: Authentication successful. Message: {message}")
        self._add_status_message(f"SASL: Authentication successful. ({message})")
        self.sasl_authentication_succeeded = True
        self.sasl_flow_active = False
        self.sasl_authentication_initiated = True

        if self.cap_negotiation_pending:
            logger.info("SASL successful. Sending CAP END.")
            self._add_status_message("SASL successful. Finalizing CAP negotiation.")
            self.network.send_cap_end()
        elif not self.cap_negotiation_finished_event.is_set():
            logger.info(
                "SASL successful. Proceeding with registration as CAP END was not pending."
            )
            self.proceed_with_registration()

    def handle_sasl_failure(self, reason: str):
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is not None:
            logger.info(
                f"SASL: Received SASL failure ({reason}), but flow no longer active and result recorded. Ignoring."
            )
            return

        logger.warning(f"SASL: Authentication failed. Reason: {reason}")
        self._add_status_message(f"SASL: Authentication FAILED. Reason: {reason}", color_key="error")
        self.sasl_authentication_succeeded = False
        self.sasl_flow_active = False
        self.sasl_authentication_initiated = True

        if self.cap_negotiation_pending:
            logger.info("SASL failed. Sending CAP END.")
            self._add_status_message("SASL failed. Finalizing CAP negotiation.")
            self.network.send_cap_end()
        elif not self.cap_negotiation_finished_event.is_set():
            logger.info(
                "SASL failed. Proceeding with registration as CAP END was not pending."
            )
            self.proceed_with_registration()

    def is_cap_negotiation_pending(self) -> bool:
        return self.cap_negotiation_pending

    def is_sasl_completed(self) -> bool:
        # SASL is completed if the flow is not active AND there has been a success or failure.
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is not None:
            return True
        # If SASL was never even initiated (e.g. 'sasl' not in enabled_caps or no password)
        # and we are not actively in a SASL flow, it's also considered 'completed' for registration purposes.
        if not self.sasl_authentication_initiated and not self.sasl_flow_active:
            return True
        return False

    def process_trigger_event(self, event_type: str, event_data: dict) -> Optional[str]:
        """Process a trigger event and return any action to take.

        Args:
            event_type: The type of event (e.g., "TEXT", "JOIN", "PART", etc.)
            event_data: Dictionary containing event data

        Returns:
            Optional[str]: The action to take, or None if no action
        """
        return self.trigger_manager.process_trigger(event_type, event_data)

    def handle_text_input(self, text: str):
        """Handles plain text input, sending it as a PRIVMSG to the active context."""
        active_ctx_name = self.context_manager.active_context_name
        if not active_ctx_name:
            self.add_message(
                "No active window to send message to.",
                self.ui.colors["error"],
                context_name="Status",
            )
            return

        active_ctx = self.context_manager.get_context(active_ctx_name)
        if not active_ctx:
            self.add_message(
                f"Error: Active context '{active_ctx_name}' not found.",
                self.ui.colors["error"],
                context_name="Status",
            )
            return

        if active_ctx.type in ["channel", "query"]:
            self.network.send_raw(f"PRIVMSG {active_ctx_name} :{text}")
            # Echo the message to the current context if not handled by echo-message CAP
            if "echo-message" not in self.enabled_caps:
                # Format similar to how incoming messages might be displayed
                # This is a simplified echo; server might format differently.
                self.add_message(
                    f"<{self.nick}> {text}",
                    self.ui.colors["my_message"], # Assuming a color for own messages
                    context_name=active_ctx_name,
                )
            elif self.echo_sent_to_status: # If echo-message is on, but user wants to see it in status
                 self.add_message(
                    f"To {active_ctx_name}: <{self.nick}> {text}",
                    self.ui.colors["my_message"],
                    context_name="Status",
                )
        else:
            self.add_message(
                f"Cannot send messages to '{active_ctx_name}' (type: {active_ctx.type}).",
                self.ui.colors["error"],
                context_name="Status",
            )

    def run_main_loop(self):
        logger.info("Starting main client loop.")
        self.network.start()
        while not self.should_quit:
            try:
                key_code = self.ui.get_input_char()
                if key_code != curses.ERR:
                    self.input_handler.handle_key_press(key_code)

                if self.ui_needs_update.is_set() or key_code != curses.ERR:
                    self.ui.refresh_all_windows()
                    if self.ui_needs_update.is_set():
                        self.ui_needs_update.clear()

                time.sleep(0.05)
            except curses.error as e:
                logger.error(f"Curses error in main loop: {e}", exc_info=True)
                try:
                    self.add_message(
                        f"Curses error: {e}. Quitting.",
                        self.ui.colors["error"],
                        context_name="Status",
                    )
                except:
                    pass
                self.should_quit = True
                break
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received. Initiating quit.")
                self.add_message(
                    "Ctrl+C pressed. Quitting...",
                    self.ui.colors["system"],
                    context_name="Status",
                )
                self.should_quit = True
                if self.network.connected:
                    self.network.send_raw("QUIT :Ctrl+C pressed")
                break
            except Exception as e:
                logger.critical(
                    f"Unhandled exception in main client loop: {e}", exc_info=True
                )
                try:
                    self.add_message(
                        f"CRITICAL ERROR: {e}. Attempting to quit.",
                        self.ui.colors["error"],
                        context_name="Status",
                    )
                except:
                    pass
                self.should_quit = True
                break

        logger.info("Main client loop ended.")
        self.should_quit = True
        self.network.stop(send_quit=self.network.connected)
        if self.network.network_thread and self.network.network_thread.is_alive():
            logger.debug("Waiting for network thread to join...")
            self.network.network_thread.join(timeout=2.0)
            if self.network.network_thread.is_alive():
                logger.warning("Network thread did not join in time.")
            else:
                logger.debug("Network thread joined successfully.")
