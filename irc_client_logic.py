# irc_client_logic.py
import curses
import threading
import time
import socket
from collections import deque
from typing import Optional, Any, List, Set, Dict, Tuple # Added Tuple
# import base64 # No longer used directly here
import logging
import logging.handlers # Added for RotatingFileHandler
import os

from config import (
    MAX_HISTORY,
    VERIFY_SSL_CERT,
    LEAVE_MESSAGE,  # Added LEAVE_MESSAGE
    # Logging config for channel logs
    CHANNEL_LOG_ENABLED,
    # CHANNEL_LOG_DIR, # Removed as per user feedback
    LOG_LEVEL, # Main log level, can be used for channel logs too
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    BASE_DIR, # To construct full log paths
    is_source_ignored, # Import the new function
)
from context_manager import ContextManager, ChannelJoinStatus # Added ChannelJoinStatus

from ui_manager import UIManager
from network_handler import NetworkHandler # Correct import
from command_handler import CommandHandler
from input_handler import InputHandler
from features.triggers.trigger_manager import TriggerManager
from features.triggers.trigger_commands import TriggerCommands
import irc_protocol
from irc_message import IRCMessage # Added for parsing

# New Handler Imports
from cap_negotiator import CapNegotiator
from sasl_authenticator import SaslAuthenticator
from registration_handler import RegistrationHandler

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

        # CAP/SASL/Registration state and logic are moved to their respective handlers.
        self.desired_caps_config: Set[str] = { # Renamed to avoid conflict if used elsewhere directly
            "sasl", "multi-prefix", "server-time", "message-tags", "account-tag",
            "echo-message", "away-notify", "chghost", "userhost-in-names",
            "cap-notify", "extended-join", "account-notify", "invite-notify",
        }

        # Initialize NetworkHandler first as other handlers might need it
        self.network = NetworkHandler(self)
        self.network.channels_to_join_on_connect = self.initial_channels_list[:] # Still needed for NetworkHandler's logic

        self.ui = UIManager(stdscr, self)
        self.command_handler = CommandHandler(self) # RegistrationHandler will need this

        # Initialize New Handlers
        # Order of initialization and linking to resolve circular dependencies:
        # 1. Create CapNegotiator (can take registration_handler=None initially)
        # 2. Create SaslAuthenticator (needs CapNegotiator)
        # 3. Create RegistrationHandler (needs CapNegotiator)
        # 4. Link handlers using their setter methods.

        self.cap_negotiator = CapNegotiator(
            network_handler=self.network,
            desired_caps=self.desired_caps_config,
            registration_handler=None  # Pass None initially
        )

        self.sasl_authenticator = SaslAuthenticator(
            network_handler=self.network,
            cap_negotiator=self.cap_negotiator,
            nick=self.nick,
            password=self.nickserv_password
        )

        self.registration_handler = RegistrationHandler(
            network_handler=self.network,
            command_handler=self.command_handler,
            initial_nick=self.initial_nick,
            username=self.initial_nick,
            realname=self.initial_nick,
            server_password=self.password,
            nickserv_password=self.nickserv_password,
            initial_channels_to_join=self.initial_channels_list,
            cap_negotiator=self.cap_negotiator # Pass the created cap_negotiator
        )

        # Complete the circular linking
        self.cap_negotiator.set_registration_handler(self.registration_handler)
        self.cap_negotiator.set_sasl_authenticator(self.sasl_authenticator)
        self.registration_handler.set_sasl_authenticator(self.sasl_authenticator)
        # self.registration_handler.set_cap_negotiator(self.cap_negotiator) # Already set in its __init__


        self.input_handler = InputHandler(self)
        self.trigger_manager = TriggerManager(
            os.path.join(os.path.expanduser("~"), ".config", "pyrc")
        )

        # Channel Logging Setup
        self.channel_log_enabled = CHANNEL_LOG_ENABLED
        self.main_log_dir_path = os.path.join(BASE_DIR, "logs") # Base "logs" directory
        # self.channel_log_subdir_name removed - channel logs go directly into main_log_dir_path
        self.channel_log_base_path = self.main_log_dir_path # Channel logs go directly here
        self.channel_log_level = LOG_LEVEL # Use the same log level as main for now
        self.channel_log_max_bytes = LOG_MAX_BYTES
        self.channel_log_backup_count = LOG_BACKUP_COUNT
        self.channel_loggers: Dict[str, logging.Logger] = {}
        self.log_formatter = logging.Formatter(
             "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ) # Re-use or define a standard formatter

        # Ensure the main log directory exists (pyrc.py should also do this, this is a fallback)
        if self.channel_log_enabled and not os.path.exists(self.main_log_dir_path):
            try:
                os.makedirs(self.main_log_dir_path)
                logger.info(f"Created main log directory in logic: {self.main_log_dir_path}")
            except OSError as e:
                logger.error(f"Error creating main log directory in logic {self.main_log_dir_path}: {e}")
                self.channel_log_enabled = False # Disable channel logging if dir creation fails

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
        color_attr: int, # curses color attribute
        prefix_time: bool = True,
        context_name: Optional[str] = None,
        source_full_ident: Optional[str] = None, # New parameter
        is_privmsg_or_notice: bool = False # New parameter to specify if it's a user message
    ):
        """
        Adds a message to the specified or active context.
        If source_full_ident is provided and is_privmsg_or_notice is True,
        it checks against the ignore list.
        """
        target_context_name = (
            context_name
            if context_name is not None
            else self.context_manager.active_context_name
        )
        if not target_context_name:
            logger.error("add_message called with no target_context_name and no active context.")
            target_context_name = "Status" # Fallback

        # --- IGNORE CHECK ---
        if is_privmsg_or_notice and source_full_ident and is_source_ignored(source_full_ident):
            logger.debug(f"Ignoring message from {source_full_ident} due to ignore list match.")
            return # Do not add the message
        # --- END IGNORE CHECK ---

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

        # Log to channel-specific file if it's a channel message
        if target_context_obj and target_context_obj.type == "channel":
            channel_logger = self.get_channel_logger(target_context_name)
            if channel_logger:
                # Log the original, non-timestamped, non-wrapped text to the file.
                # The logger's formatter will add its own timestamp.
                channel_logger.info(text)


        if target_context_name == self.context_manager.active_context_name:
            if (
                hasattr(target_context_obj, "scrollback_offset")
                and target_context_obj.scrollback_offset > 0
            ):
                # If scrolled up, adjust offset to "follow" new messages
                target_context_obj.scrollback_offset += num_lines_added_for_this_message

        self.ui_needs_update.set()

    def get_channel_logger(self, channel_name: str) -> Optional[logging.Logger]:
        if not self.channel_log_enabled:
            return None

        # Normalize channel name for filename and logger name
        # Remove leading '#' and convert to lowercase for consistency.
        # Ensure it's a valid filename (basic sanitization).
        sanitized_name_part = channel_name.lstrip('#&+!').lower()
        # Replace characters that might be problematic in filenames.
        # This is a basic example; more robust sanitization might be needed.
        safe_filename_part = "".join(c if c.isalnum() else "_" for c in sanitized_name_part)

        logger_key = safe_filename_part # Key for self.channel_loggers dictionary

        if logger_key in self.channel_loggers:
            return self.channel_loggers[logger_key]

        try:
            # Construct full path for the channel's log file
            log_file_name = f"{safe_filename_part}.log"
            # Channel logs go directly into the main_log_dir_path (e.g. "logs/")
            channel_log_file_path = os.path.join(self.main_log_dir_path, log_file_name)

            # Create logger instance
            # Use a distinct name for each channel logger to avoid conflicts.
            channel_logger_instance = logging.getLogger(f"pyrc.channel.{safe_filename_part}")
            channel_logger_instance.setLevel(self.channel_log_level) # Use configured log level

            # Create RotatingFileHandler for this channel
            # Ensure the directory self.main_log_dir_path exists
            if not os.path.exists(self.main_log_dir_path):
                 # This should have been created by pyrc.py or __init__, but double check
                logger.warning(f"Main log directory {self.main_log_dir_path} not found when creating logger for {channel_name}. Attempting to create.")
                try:
                    os.makedirs(self.main_log_dir_path)
                except OSError as e:
                    logger.error(f"Failed to create main log directory {self.main_log_dir_path} for {channel_name}: {e}. Disabling logger for this channel.")
                    return None

            file_handler = logging.handlers.RotatingFileHandler(
                channel_log_file_path,
                maxBytes=self.channel_log_max_bytes,
                backupCount=self.channel_log_backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(self.log_formatter) # Use the shared formatter

            channel_logger_instance.addHandler(file_handler)
            channel_logger_instance.propagate = False  # IMPORTANT: Prevent duplication to root logger / main file

            self.channel_loggers[logger_key] = channel_logger_instance
            logger.info(f"Initialized logger for channel {channel_name} at {channel_log_file_path}")
            return channel_logger_instance
        except Exception as e:
            logger.error(f"Failed to create logger for channel {channel_name}: {e}", exc_info=True)
            return None

    def handle_server_message(self, line: str):
        # Potentially log raw line to channel log if it's a channel message
        parsed_msg = IRCMessage.parse(line) # Corrected parser usage
        if parsed_msg and parsed_msg.command in ["PRIVMSG", "NOTICE"] and \
           parsed_msg.params and parsed_msg.params[0].startswith(("#", "&", "+", "!")):
            target_channel = parsed_msg.params[0]
            channel_logger = self.get_channel_logger(target_channel)
            if channel_logger:
                # Log a slightly modified line to indicate it's raw, or just the content
                log_line_content = f"RAW << {line}"
                if parsed_msg.trailing:
                    # For PRIVMSG/NOTICE, the interesting part is often prefix, command, target, trailing
                    log_line_content = f"{parsed_msg.prefix if parsed_msg.prefix else ''} {parsed_msg.command} {target_channel} :{parsed_msg.trailing}"
                channel_logger.debug(log_line_content) # Log raw at DEBUG level

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


    # CAP and SASL methods are removed from IRCClient_Logic.
    # They are now handled by CapNegotiator and SaslAuthenticator.
    # Calls to these methods from irc_protocol.py and irc_numeric_handlers.py
    # will be rerouted to the new handler instances.

    # Methods like initiate_cap_negotiation, proceed_with_registration, handle_cap_ls,
    # handle_cap_ack, handle_cap_nak, handle_cap_end_confirmation,
    # initiate_sasl_plain_authentication, handle_sasl_authenticate_challenge,
    # handle_sasl_success, handle_sasl_failure are now part of
    # CapNegotiator, SaslAuthenticator, or RegistrationHandler.

    # Helper methods like is_cap_negotiation_pending and is_sasl_completed
    # will now call into the respective handlers.

    def is_cap_negotiation_pending(self) -> bool:
        return self.cap_negotiator.is_cap_negotiation_pending()

    def is_sasl_completed(self) -> bool:
        # Check if SASL authenticator exists and then if it's completed
        return self.sasl_authenticator.is_completed() if self.sasl_authenticator else True


    def get_enabled_caps(self) -> Set[str]:
        """Returns the set of currently enabled capabilities."""
        return self.cap_negotiator.get_enabled_caps() if self.cap_negotiator else set()


    # This method is called by irc_numeric_handlers for RPL_ENDOFNAMES
    # and also by CommandHandler for /join success.
    # It remains here as it deals with UI and context switching logic.
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
                if "echo-message" not in self.get_enabled_caps(): # Use new getter
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
            if "echo-message" not in self.get_enabled_caps(): # Use new getter
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
                # Removed direct QUIT send, network.stop will handle it with the configured message
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
        self.network.stop(send_quit=self.network.connected, quit_message=LEAVE_MESSAGE) # Pass current connected state and LEAVE_MESSAGE
        if self.network.network_thread and self.network.network_thread.is_alive():
            logger.debug("Waiting for network thread to join...")
            self.network.network_thread.join(timeout=2.0)
            if self.network.network_thread.is_alive(): logger.warning("Network thread did not join in time.")
            else: logger.debug("Network thread joined successfully.")
