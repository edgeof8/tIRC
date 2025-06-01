# irc_client_logic.py
import curses
import threading
import time
import socket
from collections import deque
from typing import Optional, Any, List, Set, Dict
import base64
import logging
import os

from config import (
    MAX_HISTORY,
    VERIFY_SSL_CERT,
)
from context_manager import ContextManager, ChannelJoinStatus # Added ChannelJoinStatus

from ui_manager import UIManager
from network_handler import NetworkHandler # Correct import
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
        self.server = server_addr
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

        self.currently_joined_channels: Set[str] = set()

        self.password = password
        self.nickserv_password = nickserv_password
        self.use_ssl = use_ssl
        self.verify_ssl_cert = VERIFY_SSL_CERT
        logger.info(f"IRCClient_Logic.__init__: server='{server_addr}', port={port}, use_ssl={self.use_ssl}, verify_ssl_cert={self.verify_ssl_cert}")
        self.echo_sent_to_status: bool = True

        self.context_manager = ContextManager(max_history_per_context=MAX_HISTORY)
        self.context_manager.create_context("Status", context_type="status")
        self.context_manager.set_active_context("Status")

        # Create contexts for initial channels but don't join them yet
        for ch_name in self.initial_channels_list:
            self.context_manager.create_context(
                ch_name,
                context_type="channel",
                initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN
            )
        self.last_join_command_target: Optional[str] = None # Track the target of the last /join command

        self.should_quit = False
        self.ui_needs_update = threading.Event()

        self.supported_caps: Set[str] = set()
        self.requested_caps: Set[str] = set()
        self.enabled_caps: Set[str] = set()
        self.cap_negotiation_pending: bool = False # Will be set true by initiate_cap_negotiation
        self.cap_negotiation_finished_event = threading.Event()
        self.desired_caps: Set[str] = {
            "sasl", "multi-prefix", "server-time", "message-tags", "account-tag",
            "echo-message", "away-notify", "chghost", "userhost-in-names",
            "cap-notify", "extended-join", "account-notify", "invite-notify",
        }
        self.sasl_authentication_initiated: bool = False
        self.sasl_flow_active: bool = False
        self.sasl_authentication_succeeded: Optional[bool] = None

        # Initialize NetworkHandler here AFTER other attributes it might depend on (like initial_channels_list)
        self.network = NetworkHandler(self)
        # Populate channels_to_join_on_connect in NetworkHandler from initial_channels_list
        self.network.channels_to_join_on_connect = self.initial_channels_list[:]


        self.ui = UIManager(stdscr, self)
        self.command_handler = CommandHandler(self)
        self.input_handler = InputHandler(self)
        self.trigger_manager = TriggerManager(
            os.path.join(os.path.expanduser("~"), ".config", "pyrc")
        )
        # TriggerCommands is part of CommandHandler, no need to init separately here if CommandHandler does it.
        # self.trigger_commands = TriggerCommands(self) # Already done in CommandHandler

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
        color_attr = self.ui.colors.get(color_key, self.ui.colors["system"])
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
            logger.error("add_message called with no target_context_name and no active context.")
            target_context_name = "Status" # Fallback

        # Ensure context exists or create it
        target_ctx_exists = self.context_manager.get_context(target_context_name)
        if not target_ctx_exists:
            context_type = "generic"
            initial_join_status_for_new_channel: Optional[ChannelJoinStatus] = None
            if target_context_name.startswith(("#", "&", "+", "!")): # Common channel prefixes
                context_type = "channel"
                # If a message is being added to a channel context that doesn't exist,
                # it's likely from the server for a channel we're not explicitly joining.
                # Mark as NOT_JOINED by default.
                initial_join_status_for_new_channel = ChannelJoinStatus.NOT_JOINED
            elif target_context_name != "Status" and ":" not in target_context_name and not target_context_name.startswith("#"): # Likely a query if not Status or channel
                context_type = "query"


            if self.context_manager.create_context(
                target_context_name,
                context_type=context_type,
                initial_join_status_for_channel=initial_join_status_for_new_channel
                ):
                logger.info(f"Dynamically created context '{target_context_name}' of type '{context_type}' for message.")
            else: # Failed to create context
                # Fallback to Status if creation fails, to prevent message loss
                logger.error(f"Failed to create context '{target_context_name}'. Adding message to 'Status'.")
                status_ctx_for_error = self.context_manager.get_context("Status")
                if not status_ctx_for_error: self.context_manager.create_context("Status", context_type="status") # Should not happen

                self.context_manager.add_message_to_context(
                    "Status",
                    f"[CtxErr for {target_context_name}] {text}", # Prepend info about original target
                    color_attr, # Use original color
                )
                self.ui_needs_update.set()
                return

        target_context_obj = self.context_manager.get_context(target_context_name)
        if not target_context_obj: # Should not happen if above logic is correct
            logger.critical(f"Context {target_context_name} is unexpectedly None after creation/check. Message lost: {text}")
            return

        max_w = self.ui.msg_win_width - 1 if self.ui.msg_win_width > 1 else 80
        timestamp = time.strftime("%H:%M:%S ") if prefix_time else ""

        # Avoid double timestamping if text already starts with one (e.g. from logs being re-added)
        if text.startswith(timestamp.strip()): # Check against stripped timestamp
            full_message = text
        else:
            full_message = f"{timestamp}{text}"


        lines = []
        current_line = ""
        # Simple word wrapping
        for word in full_message.split(" "):
            if current_line and (len(current_line) + len(word) + 1 > max_w) :
                lines.append(current_line)
                current_line = word
            else:
                if current_line:
                    current_line += " "
                current_line += word
        if current_line:
            lines.append(current_line)

        if not lines and full_message: # Handle case where full_message is shorter than max_w
            lines.append(full_message)


        num_lines_added_for_this_message = len(lines)

        for line_part in lines:
            self.context_manager.add_message_to_context(
                target_context_name, line_part, color_attr, 1 # Pass 1 line at a time for unread count
            )

        if target_context_name == self.context_manager.active_context_name:
            if (
                hasattr(target_context_obj, "scrollback_offset")
                and target_context_obj.scrollback_offset > 0
            ):
                # If scrolled up, adjust offset to "follow" new messages
                target_context_obj.scrollback_offset += num_lines_added_for_this_message

        self.ui_needs_update.set()


    def handle_server_message(self, line: str):
        irc_protocol.handle_server_message(self, line)

    def switch_active_context(self, direction: str):
        context_names = self.context_manager.get_all_context_names()
        if not context_names:
            return

        if "Status" in context_names:
            sorted_context_names = ["Status"] + sorted(
                [name for name in context_names if name != "Status"], key=lambda x: x.lower()
            )
        else:
            sorted_context_names = sorted(context_names, key=lambda x: x.lower())

        current_active_name = self.context_manager.active_context_name
        if not current_active_name and sorted_context_names:
            current_active_name = sorted_context_names[0]
        elif not current_active_name: # No contexts at all
            return

        try:
            current_idx = sorted_context_names.index(current_active_name)
        except ValueError:
            current_idx = 0
            if not sorted_context_names: return
            current_active_name = sorted_context_names[0]

        new_active_context_name = None

        if direction == "next":
            new_idx = (current_idx + 1) % len(sorted_context_names)
            new_active_context_name = sorted_context_names[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + len(sorted_context_names)) % len(sorted_context_names)
            new_active_context_name = sorted_context_names[new_idx]
        else: # Direct switch by name or number
            if direction in sorted_context_names:
                new_active_context_name = direction
            else:
                try:
                    num_idx = int(direction) -1 # 1-based index for user
                    if 0 <= num_idx < len(sorted_context_names):
                        new_active_context_name = sorted_context_names[num_idx]
                    else:
                        self.add_message(f"Invalid window number: {direction}. Max: {len(sorted_context_names)}", self.ui.colors["error"], context_name=current_active_name)
                        return
                except ValueError: # Partial name match
                    found_ctx = [name for name in sorted_context_names if direction.lower() in name.lower()]
                    if len(found_ctx) == 1:
                        new_active_context_name = found_ctx[0]
                    elif len(found_ctx) > 1:
                         self.add_message(f"Ambiguous window name '{direction}'. Matches: {', '.join(sorted(found_ctx))}", self.ui.colors["error"], context_name=current_active_name)
                         return
                    else: # No partial match, try case-insensitive exact match
                        exact_match_case_insensitive = [name for name in sorted_context_names if direction.lower() == name.lower()]
                        if len(exact_match_case_insensitive) == 1:
                            new_active_context_name = exact_match_case_insensitive[0]
                        else:
                            self.add_message(f"Window '{direction}' not found.", self.ui.colors["error"], context_name=current_active_name)
                            return

        if new_active_context_name:
            # Before setting active, check if it's a channel and its join status
            target_ctx_to_activate = self.context_manager.get_context(new_active_context_name)
            if target_ctx_to_activate and target_ctx_to_activate.type == "channel" and \
               target_ctx_to_activate.join_status and \
               target_ctx_to_activate.join_status != ChannelJoinStatus.FULLY_JOINED:
                join_status_name = target_ctx_to_activate.join_status.name # Safe now due to the check
                self.add_message(
                    f"Channel {new_active_context_name} is not fully joined yet (Status: {join_status_name}).",
                    self.ui.colors["system"], # Or warning
                    context_name=current_active_name # Show message in current window
                )
                # Optionally, do not switch, or switch but UI clearly indicates "joining" state.
                # For now, we allow the switch, UI will handle display.

            if self.context_manager.set_active_context(new_active_context_name):
                logger.debug(f"Switched active context to: {self.context_manager.active_context_name}")
                self.ui_needs_update.set()
            else: # Should not happen if new_active_context_name is from sorted_context_names
                logger.error(f"Failed to set active context to {new_active_context_name} via ContextManager.")
                self.add_message(f"Error switching to window '{new_active_context_name}'.", self.ui.colors["error"], context_name=current_active_name)


    def switch_active_channel(self, direction: str):
        all_context_names = self.context_manager.get_all_context_names()
        channel_context_names: List[str] = []
        status_context_name_const = "Status"

        channel_names_only: List[str] = []
        for name in all_context_names:
            context_obj = self.context_manager.get_context(name)
            if context_obj and context_obj.type == "channel":
                channel_names_only.append(name)

        channel_names_only.sort(key=lambda x: x.lower())
        channel_context_names.extend(channel_names_only)

        if status_context_name_const in all_context_names:
            channel_context_names.append(status_context_name_const) # Add Status to the end of cycle

        if not channel_context_names:
            self.add_message("No channels or Status window to switch to.", self.ui.colors["system"], context_name=self.context_manager.active_context_name or "Status")
            return

        current_active_name_str: Optional[str] = self.context_manager.active_context_name
        current_idx = -1

        if current_active_name_str:
            try:
                current_idx = channel_context_names.index(current_active_name_str)
            except ValueError: # Current active context is not in our cyclable list (e.g., a query window)
                current_idx = -1
                logger.debug(f"Active context '{current_active_name_str}' not in channel/status cycle list.")


        new_active_channel_name = None
        num_cyclable = len(channel_context_names)

        if current_idx == -1: # If not in a known channel/status, or current was None
             # Default to the first channel if available, else first in list (which might be Status)
            if channel_names_only:
                new_active_channel_name = channel_names_only[0]
            elif channel_context_names: # Should always have at least Status if it exists
                new_active_channel_name = channel_context_names[0]
            else: # Should not happen
                return
        elif direction == "next":
            new_idx = (current_idx + 1) % num_cyclable
            new_active_channel_name = channel_context_names[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + num_cyclable) % num_cyclable
            new_active_channel_name = channel_context_names[new_idx]

        if new_active_channel_name:
            if self.context_manager.set_active_context(new_active_channel_name):
                logger.debug(f"Switched active channel/status to: {self.context_manager.active_context_name}")
                self.ui_needs_update.set()
            else:
                logger.error(f"Failed to set active channel/status to {new_active_channel_name}.")
                self.add_message(f"Error switching to '{new_active_channel_name}'.", self.ui.colors["error"], context_name=current_active_name_str or "Status")


    def initiate_cap_negotiation(self):
        if self.network.connected:
            self.cap_negotiation_pending = True
            self.cap_negotiation_finished_event.clear()
            self.sasl_authentication_initiated = False
            self.sasl_flow_active = False
            self.sasl_authentication_succeeded = None
            self.enabled_caps.clear()
            self.supported_caps.clear()
            self.requested_caps.clear()
            self._add_status_message("Negotiating capabilities with server (CAP)...")
            self.network.send_cap_ls()
        else:
            logger.warning("initiate_cap_negotiation called but not connected.")
            self._add_status_message("Cannot initiate CAP: Not connected.", "error")


    def proceed_with_registration(self):
        if self.cap_negotiation_finished_event.is_set() and not self.cap_negotiation_pending:
            logger.debug("proceed_with_registration called but registration already signaled or not in CAP pending state.")
            return

        self.cap_negotiation_pending = False
        self.cap_negotiation_finished_event.set()
        logger.info("CAP negotiation concluded. Proceeding with NICK/USER registration.")
        self._add_status_message("Proceeding with NICK/USER registration.")

        if self.password:
            self.network.send_raw(f"PASS {self.password}")
        self.network.send_raw(f"NICK {self.nick}") # Use current nick, which might have been changed by 433
        self.network.send_raw(f"USER {self.initial_nick} 0 * :{self.initial_nick}") # Use initial_nick for USER realname part


    def handle_cap_ls(self, capabilities_str: str):
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP LS but negotiation is not pending. Ignoring.")
            return

        self.supported_caps = set(capabilities_str.split())
        self._add_status_message(f"Server supports CAP: {', '.join(self.supported_caps) if self.supported_caps else 'None'}")

        caps_to_request = list(self.desired_caps.intersection(self.supported_caps))

        if "sasl" in caps_to_request and not self.nickserv_password:
            logger.info("SASL is supported and desired, but no NickServ password configured. Removing SASL from request.")
            caps_to_request.remove("sasl")
            self._add_status_message("SASL capability available but no NickServ password set; skipping SASL request.", "warning")


        if caps_to_request:
            self.requested_caps.update(caps_to_request)
            self._add_status_message(f"Requesting CAP: {', '.join(caps_to_request)}")
            self.network.send_cap_req(caps_to_request)
            # If SASL is requested, CAP END will be deferred until SASL flow completes.
            # If SASL is not requested (or not supported/desired), and no other caps are pending,
            # then CAP END might be sent if self.requested_caps becomes empty after this.
            # This is handled in handle_cap_ack/nak.
        else: # No common caps to request, or SASL was the only one and removed.
            self._add_status_message("No desired and supported capabilities to request. Ending CAP negotiation.")
            self.network.send_cap_end() # Server will confirm, then 001 will trigger registration.

    def handle_cap_ack(self, acked_caps_str: str):
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

        if sasl_was_just_acked and not self.sasl_authentication_initiated:
            self.sasl_authentication_initiated = True
            if self.nickserv_password: # Check again, in case it was cleared elsewhere
                self.initiate_sasl_plain_authentication()
            else:
                # This case should ideally be caught by handle_cap_ls not requesting SASL.
                # If it gets here, it means SASL was requested but password disappeared.
                logger.warning("SASL ACKed, but no NickServ password now. Cannot start SASL.")
                self._add_status_message("SASL ACKed but no password available. Skipping SASL auth.", "warning")
                self.sasl_authentication_succeeded = False # Treat as failed for flow control
                self.sasl_flow_active = False
                # Proceed to CAP END if no other caps are pending
                if not self.requested_caps:
                    self._add_status_message("All other requested capabilities processed. Ending CAP negotiation.")
                    self.network.send_cap_end()
        elif not self.requested_caps: # All initially requested caps processed
            # If SASL flow is active, wait for it to complete.
            # If SASL is not enabled OR SASL flow is complete, send CAP END.
            if not ("sasl" in self.enabled_caps and self.sasl_flow_active):
                self._add_status_message("All requested capabilities processed. Ending CAP negotiation.")
                self.network.send_cap_end()
                # If SASL is not enabled and not active, and we haven't finished CAP negotiation yet, proceed.
                if not ("sasl" in self.enabled_caps and self.sasl_flow_active) and not self.cap_negotiation_finished_event.is_set():
                    logger.debug("CAP ACK: SASL not active, all other caps processed. Attempting registration.")
                    self.proceed_with_registration()


    def handle_cap_nak(self, naked_caps_str: str):
        if not self.cap_negotiation_pending:
            logger.warning("Received CAP NAK but negotiation is not pending. Ignoring.")
            return

        naked_caps_list = naked_caps_str.split()
        rejected = []
        sasl_was_naked = False
        for cap in naked_caps_list:
            if cap in self.requested_caps:
                self.requested_caps.remove(cap)
            if cap in self.enabled_caps: # Should not be in enabled_caps if NAKed
                self.enabled_caps.remove(cap)
            rejected.append(cap)
            if cap == "sasl":
                sasl_was_naked = True

        if rejected:
            self._add_status_message(f"CAP NAK (rejected): {', '.join(rejected)}")

        if sasl_was_naked:
            # If SASL was rejected, mark its flow as complete (failed)
            self.sasl_authentication_succeeded = False
            self.sasl_flow_active = False
            self.sasl_authentication_initiated = True # Mark as attempted

        if not self.requested_caps: # All initially requested caps processed
            if not ("sasl" in self.enabled_caps and self.sasl_flow_active): # Check if SASL flow still active
                self._add_status_message("All requested capabilities processed (some NAKed). Ending CAP negotiation.")
                self.network.send_cap_end()
                # If SASL is not enabled and not active, and we haven't finished CAP negotiation yet, proceed.
                if not ("sasl" in self.enabled_caps and self.sasl_flow_active) and not self.cap_negotiation_finished_event.is_set():
                    logger.debug("CAP NAK: SASL not active, all other caps processed. Attempting registration.")
                    self.proceed_with_registration()


    def handle_cap_end_confirmation(self):
        if self.cap_negotiation_pending:
            self._add_status_message("CAP negotiation finalized with server.")
            self.cap_negotiation_pending = False
            if not ("sasl" in self.enabled_caps and self.sasl_flow_active and self.sasl_authentication_succeeded is None):
                if not self.cap_negotiation_finished_event.is_set():
                    self.proceed_with_registration()
            else: # SASL is enabled, flow is active, but not yet succeeded/failed
                logger.info("CAP END confirmed, but SASL flow is still active. Registration deferred.")
        elif not self.cap_negotiation_finished_event.is_set():
            logger.info("CAP END confirmation received (e.g. via 001), but CAP was not marked pending. Ensuring registration proceeds.")
            self.proceed_with_registration()


    def initiate_sasl_plain_authentication(self):
        if not self.nickserv_password: # Should have been checked before requesting SASL cap
            self._add_status_message("SASL: NickServ password not set. Skipping SASL.", color_key="warning")
            logger.warning("SASL: NickServ password not set. Skipping SASL.")
            self.handle_sasl_failure("No NickServ password.") # Trigger failure flow
            return

        self._add_status_message("SASL: Initiating PLAIN authentication...")
        logger.info("SASL: Initiating PLAIN authentication.")
        self.sasl_flow_active = True
        self.sasl_authentication_succeeded = None
        self.network.send_authenticate("PLAIN")


    def handle_sasl_authenticate_challenge(self, challenge: str):
        if not self.sasl_flow_active:
            logger.warning("SASL: Received AUTHENTICATE challenge but SASL flow not active. Ignoring.")
            return

        if challenge == "+":
            logger.info("SASL: Received '+' challenge. Sending PLAIN credentials.")
            # Use self.nick as authcid, self.nick as authzid (common practice for NickServ)
            # If server uses a different account system, authzid might be different.
            payload_str = f"{self.nick}\0{self.nick}\0{self.nickserv_password}"
            payload_b64 = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")

            # Log masked payload for security
            masked_payload_str = f"{self.nick}\0{self.nick}\0********"
            masked_payload_b64 = base64.b64encode(masked_payload_str.encode("utf-8")).decode("utf-8")
            logger.debug(f"SASL: Sending AUTHENTICATE payload (masked): {masked_payload_b64}")

            self.network.send_authenticate(payload_b64)
        else:
            logger.warning(f"SASL: Received unexpected challenge: {challenge}. Aborting SASL.")
            self._add_status_message(f"SASL: Unexpected challenge '{challenge}'. Aborting.", color_key="error")
            self.handle_sasl_failure(f"Unexpected challenge: {challenge}")

    def handle_sasl_success(self, message: str):
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is True:
            logger.info(f"SASL: Received SASL success ({message}), but flow no longer active and already succeeded. Ignoring.")
            return

        logger.info(f"SASL: Authentication successful. Message: {message}")
        self._add_status_message(f"SASL: Authentication successful. ({message})")
        self.sasl_authentication_succeeded = True
        self.sasl_flow_active = False
        self.sasl_authentication_initiated = True # Ensure marked as attempted

        # If CAP negotiation was pending on SASL completion
        if self.cap_negotiation_pending: # This implies CAP END was not yet sent
            logger.info("SASL successful. Sending CAP END.")
            self._add_status_message("SASL successful. Finalizing CAP negotiation.")
            self.network.send_cap_end() # Server confirms, then 001 triggers registration
        elif not self.cap_negotiation_finished_event.is_set():
            # SASL succeeded, but CAP negotiation might have already sent CAP END (e.g., no other caps)
            # or server sent 001 early. Proceed with registration if not already done.
            logger.info("SASL successful. Proceeding with registration as CAP END was not pending or already handled.")
            self.proceed_with_registration()


    def handle_sasl_failure(self, reason: str):
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is False:
            logger.info(f"SASL: Received SASL failure ({reason}), but flow no longer active and already failed. Ignoring.")
            return

        logger.warning(f"SASL: Authentication failed. Reason: {reason}")
        self._add_status_message(f"SASL: Authentication FAILED. Reason: {reason}", color_key="error")
        self.sasl_authentication_succeeded = False
        self.sasl_flow_active = False
        self.sasl_authentication_initiated = True # Ensure marked as attempted

        if self.cap_negotiation_pending:
            logger.info("SASL failed. Sending CAP END.")
            self._add_status_message("SASL failed. Finalizing CAP negotiation.")
            self.network.send_cap_end()
        elif not self.cap_negotiation_finished_event.is_set():
            logger.info("SASL failed. Proceeding with registration as CAP END was not pending or already handled.")
            self.proceed_with_registration()


    def is_cap_negotiation_pending(self) -> bool:
        return self.cap_negotiation_pending

    def is_sasl_completed(self) -> bool:
        # SASL is completed if it wasn't initiated, or if it was initiated and flow is no longer active
        # and a result (success/failure) has been recorded.
        if not self.sasl_authentication_initiated:
            return True # Never started, so "completed" in terms of not blocking other things
        if not self.sasl_flow_active and self.sasl_authentication_succeeded is not None:
            return True
        return False

    def handle_channel_fully_joined(self, channel_name: str):
        """
        Called when a channel is confirmed as fully joined (e.g., after RPL_ENDOFNAMES).
        If this channel was the target of the last /join command, make it active.
        """
        normalized_channel_name = self.context_manager._normalize_context_name(channel_name)
        logger.info(f"Channel {normalized_channel_name} reported as fully joined.")

        # Check if this fully joined channel was the one we last explicitly tried to join
        if self.last_join_command_target and \
           self.context_manager._normalize_context_name(self.last_join_command_target) == normalized_channel_name:

            logger.info(f"Setting active context to recently joined channel: {normalized_channel_name}")
            self.context_manager.set_active_context(normalized_channel_name) # Name is already normalized
            self.last_join_command_target = None # Clear the target
            self.ui_needs_update.set()
        else:
            # If it's an initial auto-join channel, and no other channel is active,
            # or if the active context is just "Status", consider activating it.
            active_ctx = self.context_manager.get_active_context()
            if not active_ctx or active_ctx.name == "Status":
                if channel_name in self.initial_channels_list: # Check against original case list
                    logger.info(f"Auto-joined channel {normalized_channel_name} is now fully joined. Setting active.")
                    self.context_manager.set_active_context(normalized_channel_name)
                    self.ui_needs_update.set()


    def process_trigger_event(self, event_type: str, event_data: dict) -> Optional[str]:
        return self.trigger_manager.process_trigger(event_type, event_data)

    def handle_text_input(self, text: str):
        active_ctx_name = self.context_manager.active_context_name
        if not active_ctx_name:
            self.add_message("No active window to send message to.", self.ui.colors["error"], context_name="Status")
            return

        active_ctx = self.context_manager.get_context(active_ctx_name)
        if not active_ctx:
            self.add_message(f"Error: Active context '{active_ctx_name}' not found.", self.ui.colors["error"], context_name="Status")
            return

        if active_ctx.type == "channel":
            if active_ctx.join_status == ChannelJoinStatus.FULLY_JOINED:
                self.network.send_raw(f"PRIVMSG {active_ctx_name} :{text}")
                if "echo-message" not in self.enabled_caps:
                    self.add_message(f"<{self.nick}> {text}", self.ui.colors["my_message"], context_name=active_ctx_name)
                elif self.echo_sent_to_status:
                    self.add_message(f"To {active_ctx_name}: <{self.nick}> {text}", self.ui.colors["my_message"], context_name="Status")
            else:
                self.add_message(
                    f"Cannot send message: Channel {active_ctx_name} not fully joined (Status: {active_ctx.join_status.name if active_ctx.join_status else 'N/A'}).",
                    self.ui.colors["error"],
                    context_name=active_ctx_name # Show error in the channel window itself
                )
        elif active_ctx.type == "query":
            self.network.send_raw(f"PRIVMSG {active_ctx_name} :{text}")
            if "echo-message" not in self.enabled_caps: # Assuming echo-message also applies to PMs if server supports it
                self.add_message(f"<{self.nick}> {text}", self.ui.colors["my_message"], context_name=active_ctx_name)
            elif self.echo_sent_to_status: # Or a specific setting for PM echo
                 self.add_message(f"To {active_ctx_name}: <{self.nick}> {text}", self.ui.colors["my_message"], context_name="Status")
        else: # e.g. "Status" window
            self.add_message(f"Cannot send messages to '{active_ctx_name}' (type: {active_ctx.type}). Try a command like /msg.", self.ui.colors["error"], context_name="Status")


    def run_main_loop(self):
        logger.info("Starting main client loop.")
        self.network.start() # Starts the network thread, which will call _connect_socket
        while not self.should_quit:
            try:
                key_code = self.ui.get_input_char()
                if key_code != curses.ERR:
                    self.input_handler.handle_key_press(key_code)

                if self.ui_needs_update.is_set() or key_code != curses.ERR:
                    self.ui.refresh_all_windows()
                    if self.ui_needs_update.is_set():
                        self.ui_needs_update.clear()

                time.sleep(0.05) # Reduce CPU usage
            except curses.error as e:
                logger.error(f"Curses error in main loop: {e}", exc_info=True)
                try: self.add_message(f"Curses error: {e}. Quitting.", self.ui.colors["error"], context_name="Status")
                except: pass
                self.should_quit = True; break
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received. Initiating quit.")
                self.add_message("Ctrl+C pressed. Quitting...", self.ui.colors["system"], context_name="Status")
                self.should_quit = True
                if self.network.connected: self.network.send_raw("QUIT :Ctrl+C pressed")
                break
            except Exception as e:
                logger.critical(f"Unhandled exception in main client loop: {e}", exc_info=True)
                try: self.add_message(f"CRITICAL ERROR: {e}. Attempting to quit.", self.ui.colors["error"], context_name="Status")
                except: pass
                self.should_quit = True; break

        logger.info("Main client loop ended.")
        self.should_quit = True # Ensure flag is set
        # network.stop might try to send QUIT again, which is fine.
        # The network thread itself will exit due to self.client.should_quit or _should_thread_stop.
        self.network.stop(send_quit=self.network.connected) # Pass current connected state
        if self.network.network_thread and self.network.network_thread.is_alive():
            logger.debug("Waiting for network thread to join...")
            self.network.network_thread.join(timeout=2.0)
            if self.network.network_thread.is_alive(): logger.warning("Network thread did not join in time.")
            else: logger.debug("Network thread joined successfully.")
