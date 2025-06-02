import curses
import threading
import time
import socket
from collections import deque
from typing import Optional, Any, List, Set, Dict, Tuple
import logging
import logging.handlers
import os

from config import (
    MAX_HISTORY,
    VERIFY_SSL_CERT,
    LEAVE_MESSAGE,
    CHANNEL_LOG_ENABLED,
    LOG_LEVEL,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    BASE_DIR,
    is_source_ignored,
    reload_all_config_values, # For /rehash
)
# Import the config module itself to access its updated globals after reload
import config as app_config

from context_manager import ContextManager, ChannelJoinStatus

from ui_manager import UIManager
from network_handler import NetworkHandler
from command_handler import CommandHandler
from input_handler import InputHandler
from features.triggers.trigger_manager import TriggerManager, ActionType
from features.triggers.trigger_commands import TriggerCommands
import irc_protocol
from irc_message import IRCMessage

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
        self.show_raw_log_in_ui: bool = False

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
        self.last_join_command_target: Optional[str] = None

        self.should_quit = False
        self.ui_needs_update = threading.Event()

        self.desired_caps_config: Set[str] = {
            "sasl", "multi-prefix", "server-time", "message-tags", "account-tag",
            "echo-message", "away-notify", "chghost", "userhost-in-names",
            "cap-notify", "extended-join", "account-notify", "invite-notify",
        }

        self.network = NetworkHandler(self)
        self.network.channels_to_join_on_connect = self.initial_channels_list[:]

        self.ui = UIManager(stdscr, self)
        self.command_handler = CommandHandler(self)

        self.cap_negotiator = CapNegotiator(
            network_handler=self.network,
            desired_caps=self.desired_caps_config,
            registration_handler=None,
            client_logic_ref=self
        )

        self.sasl_authenticator = SaslAuthenticator(
            network_handler=self.network,
            cap_negotiator=self.cap_negotiator,
            # nick=self.nick, # Removed as SaslAuthenticator now fetches from client_logic_ref
            password=self.nickserv_password,
            client_logic_ref=self
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
            cap_negotiator=self.cap_negotiator,
            client_logic_ref=self
        )

        self.cap_negotiator.set_registration_handler(self.registration_handler)
        self.cap_negotiator.set_sasl_authenticator(self.sasl_authenticator)
        self.registration_handler.set_sasl_authenticator(self.sasl_authenticator)


        self.input_handler = InputHandler(self)
        self.trigger_manager = TriggerManager(
            os.path.join(os.path.expanduser("~"), ".config", "pyrc")
        )

        self.channel_log_enabled = CHANNEL_LOG_ENABLED
        self.main_log_dir_path = os.path.join(BASE_DIR, "logs")
        self.channel_log_base_path = self.main_log_dir_path
        self.channel_log_level = LOG_LEVEL
        self.channel_log_max_bytes = LOG_MAX_BYTES
        self.channel_log_backup_count = LOG_BACKUP_COUNT
        self.channel_loggers: Dict[str, logging.Logger] = {}
        self.log_formatter = logging.Formatter(
             "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self.active_list_context_name: Optional[str] = None # For /list command output

        if self.channel_log_enabled and not os.path.exists(self.main_log_dir_path):
            try:
                os.makedirs(self.main_log_dir_path)
                logger.info(f"Created main log directory in logic: {self.main_log_dir_path}")
            except OSError as e:
                logger.error(f"Error creating main log directory in logic {self.main_log_dir_path}: {e}")
                self.channel_log_enabled = False

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
        source_full_ident: Optional[str] = None,
        is_privmsg_or_notice: bool = False
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
            target_context_name = "Status"

        if is_privmsg_or_notice and source_full_ident and is_source_ignored(source_full_ident):
            logger.debug(f"Ignoring message from {source_full_ident} due to ignore list match.")
            return

        target_ctx_exists = self.context_manager.get_context(target_context_name)
        if not target_ctx_exists:
            context_type = "generic"
            initial_join_status_for_new_channel: Optional[ChannelJoinStatus] = None
            if target_context_name.startswith(("#", "&", "+", "!")):
                context_type = "channel"
                initial_join_status_for_new_channel = ChannelJoinStatus.NOT_JOINED
            elif target_context_name != "Status" and ":" not in target_context_name and not target_context_name.startswith("#"):
                context_type = "query"


            if self.context_manager.create_context(
                target_context_name,
                context_type=context_type,
                initial_join_status_for_channel=initial_join_status_for_new_channel
                ):
                logger.info(f"Dynamically created context '{target_context_name}' of type '{context_type}' for message.")
            else:
                logger.error(f"Failed to create context '{target_context_name}'. Adding message to 'Status'.")
                status_ctx_for_error = self.context_manager.get_context("Status")
                if not status_ctx_for_error: self.context_manager.create_context("Status", context_type="status")

                self.context_manager.add_message_to_context(
                    "Status",
                    f"[CtxErr for {target_context_name}] {text}",
                    color_attr,
                )
                self.ui_needs_update.set()
                return

        target_context_obj = self.context_manager.get_context(target_context_name)
        if not target_context_obj:
            logger.critical(f"Context {target_context_name} is unexpectedly None after creation/check. Message lost: {text}")
            return

        max_w = self.ui.msg_win_width - 1 if self.ui.msg_win_width > 1 else 80
        timestamp = time.strftime("%H:%M:%S ") if prefix_time else ""

        if text.startswith(timestamp.strip()):
            full_message = text
        else:
            full_message = f"{timestamp}{text}"


        lines = []
        current_line = ""
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

        if not lines and full_message:
            lines.append(full_message)


        num_lines_added_for_this_message = len(lines)

        for line_part in lines:
            self.context_manager.add_message_to_context(
                target_context_name, line_part, color_attr, 1
            )

        if target_context_obj and target_context_obj.type == "channel":
            channel_logger = self.get_channel_logger(target_context_name)
            if channel_logger:
                channel_logger.info(text)


        if target_context_name == self.context_manager.active_context_name:
            if (
                hasattr(target_context_obj, "scrollback_offset")
                and target_context_obj.scrollback_offset > 0
            ):
                target_context_obj.scrollback_offset += num_lines_added_for_this_message

        self.ui_needs_update.set()

    def get_channel_logger(self, channel_name: str) -> Optional[logging.Logger]:
        if not self.channel_log_enabled:
            return None

        sanitized_name_part = channel_name.lstrip('#&+!').lower()
        safe_filename_part = "".join(c if c.isalnum() else "_" for c in sanitized_name_part)

        logger_key = safe_filename_part

        if logger_key in self.channel_loggers:
            return self.channel_loggers[logger_key]

        try:
            log_file_name = f"{safe_filename_part}.log"
            channel_log_file_path = os.path.join(self.main_log_dir_path, log_file_name)

            channel_logger_instance = logging.getLogger(f"pyrc.channel.{safe_filename_part}")
            channel_logger_instance.setLevel(self.channel_log_level)

            if not os.path.exists(self.main_log_dir_path):
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
            file_handler.setFormatter(self.log_formatter)

            channel_logger_instance.addHandler(file_handler)
            channel_logger_instance.propagate = False  # IMPORTANT: Prevent duplication to root logger / main file

            self.channel_loggers[logger_key] = channel_logger_instance
            logger.info(f"Initialized logger for channel {channel_name} at {channel_log_file_path}")
            return channel_logger_instance
        except Exception as e:
            logger.error(f"Failed to create logger for channel {channel_name}: {e}", exc_info=True)
            return None

    def handle_server_message(self, line: str):
        # 1. Trigger: Called by `NetworkHandler._network_loop()` for each complete line received from the IRC server.
        # 2. Expected State Before:
        #    - `line` (method argument) contains a raw, decoded IRC message string (e.g., ":irc.example.com 001 MyNick :Welcome...").
        #    - The client is connected and listening for server messages.
        # 3. Key Actions:
        #    - Parses the raw `line` into an `IRCMessage` object (optional, for logging).
        #    - If channel logging is enabled and the message is a PRIVMSG/NOTICE to a channel, logs it to the specific channel log.
        #    - CRITICAL: Calls `irc_protocol.handle_server_message(self, line)`.
        #        - This is the main dispatch point for all incoming IRC commands.
        #        - `irc_protocol.handle_server_message` parses the line again (or uses a more robust parser)
        #          and then calls specific handlers within `irc_protocol.py` based on the command
        #          (e.g., `handle_rpl_welcome`, `handle_cap`, `handle_authenticate`, `handle_ping`, `handle_privmsg`, etc.).
        #        - These specific handlers in `irc_protocol.py` then interact with the appropriate client components:
        #            - `CapNegotiator` for CAP subcommands (LS, ACK, NAK).
        #            - `SaslAuthenticator` for AUTHENTICATE responses and SASL numerics (900-907).
        #            - `RegistrationHandler` for RPL_WELCOME (001) and nick collision errors (433).
        #            - `UIManager` / `ContextManager` for displaying messages.
        #            - `CommandHandler` for some server-side actions that might map to client commands.
        # 4. Expected State After:
        #    - The raw `line` has been passed to `irc_protocol.handle_server_message`.
        #    - The appropriate specific handler within `irc_protocol.py` (and subsequently `CapNegotiator`,
        #      `SaslAuthenticator`, `RegistrationHandler`, etc.) has processed the command.
        #    - Client state (e.g., `enabled_caps`, `sasl_authentication_succeeded`, `nick_user_sent`, UI)
        #      may have been updated based on the message.
        #    - Subsequent step: Depends on the message; could be sending another command, updating UI, or just listening.
        #      This function is central to the client's reaction to server events during the handshake and beyond.
        if self.show_raw_log_in_ui:
            self.add_message(f"S << {line.strip()}", self.ui.colors.get("system", 0), context_name="Status", prefix_time=True)

        parsed_msg = IRCMessage.parse(line)
        if parsed_msg and parsed_msg.command in ["PRIVMSG", "NOTICE"] and \
           parsed_msg.params and parsed_msg.params[0].startswith(("#", "&", "+", "!")):
            target_channel = parsed_msg.params[0]
            channel_logger = self.get_channel_logger(target_channel)
            if channel_logger:
                # The raw line is already being logged to general log if enabled,
                # and channel specific log for PRIVMSG/NOTICE to channels if enabled.
                # No need to duplicate raw log here specifically unless desired for a different format.
                # The S << line above handles UI display.
                pass # Placeholder if specific raw logging to file for this flag was intended beyond UI

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
        elif not current_active_name:
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
        else:
            if direction in sorted_context_names:
                new_active_context_name = direction
            else:
                try:
                    num_idx = int(direction) -1
                    if 0 <= num_idx < len(sorted_context_names):
                        new_active_context_name = sorted_context_names[num_idx]
                    else:
                        self.add_message(f"Invalid window number: {direction}. Max: {len(sorted_context_names)}", self.ui.colors["error"], context_name=current_active_name)
                        return
                except ValueError:
                    found_ctx = [name for name in sorted_context_names if direction.lower() in name.lower()]
                    if len(found_ctx) == 1:
                        new_active_context_name = found_ctx[0]
                    elif len(found_ctx) > 1:
                         self.add_message(f"Ambiguous window name '{direction}'. Matches: {', '.join(sorted(found_ctx))}", self.ui.colors["error"], context_name=current_active_name)
                         return
                    else:
                        exact_match_case_insensitive = [name for name in sorted_context_names if direction.lower() == name.lower()]
                        if len(exact_match_case_insensitive) == 1:
                            new_active_context_name = exact_match_case_insensitive[0]
                        else:
                            self.add_message(f"Window '{direction}' not found.", self.ui.colors["error"], context_name=current_active_name)
                            return

        if new_active_context_name:
            target_ctx_to_activate = self.context_manager.get_context(new_active_context_name)
            if target_ctx_to_activate and target_ctx_to_activate.type == "channel" and \
               target_ctx_to_activate.join_status and \
               target_ctx_to_activate.join_status != ChannelJoinStatus.FULLY_JOINED:
                join_status_name = target_ctx_to_activate.join_status.name
                self.add_message(
                    f"Channel {new_active_context_name} is not fully joined yet (Status: {join_status_name}).",
                    self.ui.colors["system"],
                    context_name=current_active_name
                )

            if self.context_manager.set_active_context(new_active_context_name):
                logger.debug(f"Switched active context to: {self.context_manager.active_context_name}")
                self.ui_needs_update.set()
            else:
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
            channel_context_names.append(status_context_name_const)

        if not channel_context_names:
            self.add_message("No channels or Status window to switch to.", self.ui.colors["system"], context_name=self.context_manager.active_context_name or "Status")
            return

        current_active_name_str: Optional[str] = self.context_manager.active_context_name
        current_idx = -1

        if current_active_name_str:
            try:
                current_idx = channel_context_names.index(current_active_name_str)
            except ValueError:
                current_idx = -1
                logger.debug(f"Active context '{current_active_name_str}' not in channel/status cycle list.")


        new_active_channel_name = None
        num_cyclable = len(channel_context_names)

        if current_idx == -1:
            if channel_names_only:
                new_active_channel_name = channel_names_only[0]
            elif channel_context_names:
                new_active_channel_name = channel_context_names[0]
            else:
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



    def is_cap_negotiation_pending(self) -> bool:
        return self.cap_negotiator.is_cap_negotiation_pending()

    def is_sasl_completed(self) -> bool:
        return self.sasl_authenticator.is_completed() if self.sasl_authenticator else True


    def get_enabled_caps(self) -> Set[str]:
        """Returns the set of currently enabled capabilities."""
        return self.cap_negotiator.get_enabled_caps() if self.cap_negotiator else set()


    def handle_channel_fully_joined(self, channel_name: str):
        """
        Called when a channel is confirmed as fully joined (e.g., after RPL_ENDOFNAMES).
        If this channel was the target of the last /join command, make it active.
        """
        normalized_channel_name = self.context_manager._normalize_context_name(channel_name)
        logger.info(f"Channel {normalized_channel_name} reported as fully joined.")

        if self.last_join_command_target and \
           self.context_manager._normalize_context_name(self.last_join_command_target) == normalized_channel_name:

            logger.info(f"Setting active context to recently joined channel: {normalized_channel_name}")
            self.context_manager.set_active_context(normalized_channel_name)
            self.last_join_command_target = None
            self.ui_needs_update.set()
        else:
            active_ctx = self.context_manager.get_active_context()
            if not active_ctx or active_ctx.name == "Status":
                if channel_name in self.initial_channels_list:
                    logger.info(f"Auto-joined channel {normalized_channel_name} is now fully joined. Setting active.")
                    self.context_manager.set_active_context(normalized_channel_name)
                    self.ui_needs_update.set()


    def _execute_python_trigger(self, code: str, event_data: Dict[str, Any], trigger_info_for_error: str):
        """
        Executes a Python code snippet from a trigger.
        WARNING: This uses exec() and can be dangerous if untrusted code is used.
        """
        current_context_name = self.context_manager.active_context_name or "Status"
        try:
            # Prepare a limited execution scope
            # Provide 'client' for interacting with the IRC client and 'event_data' for trigger context
            execution_globals = {} # Or provide some safe builtins if needed
            execution_locals = {
                "client": self,      # Gives access to self.add_message, self.send_raw etc.
                "event_data": event_data # Contains $nick, $channel, $msg, $0, $1 etc.
            }
            exec(code, execution_globals, execution_locals)
        except Exception as e:
            error_message = f"Error executing Python trigger ({trigger_info_for_error}): {type(e).__name__}: {e}"
            logger.error(error_message, exc_info=True)
            self.add_message(
                error_message,
                self.ui.colors["error"],
                context_name=current_context_name, # Or a specific error context
            )
            # Optionally, add more detailed error to a specific debug context or log if too verbose for main chat

    def process_trigger_event(self, event_type: str, event_data: dict) -> Optional[str]:
        """
        Processes a trigger event.
        If a COMMAND trigger matches, returns the command string.
        If a PYTHON trigger matches, executes the Python code and returns None.
        """
        processed_action = self.trigger_manager.process_trigger(event_type, event_data)

        if processed_action:
            action_type = processed_action.get("type")

            if action_type == ActionType.COMMAND:
                return processed_action.get("content")
            elif action_type == ActionType.PYTHON:
                code_to_execute = processed_action.get("code")
                data_for_code = processed_action.get("event_data", {}) # Default to empty dict

                # Construct a string for error reporting, e.g., "event_type matching pattern"
                # This is a bit simplistic, might need original trigger pattern/id if available in processed_action
                trigger_info_str = f"Type: PY, Event: {event_type}"
                if data_for_code.get('$0'): # If regex match was involved
                    trigger_info_str += f", Match: \"{data_for_code['$0'][:50]}{'...' if len(data_for_code['$0']) > 50 else ''}\""

                if code_to_execute:
                    self._execute_python_trigger(code_to_execute, data_for_code, trigger_info_str)
                return None # Python actions are self-contained

        return None

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
                if "echo-message" not in self.get_enabled_caps():
                    self.add_message(f"<{self.nick}> {text}", self.ui.colors["my_message"], context_name=active_ctx_name)
                elif self.echo_sent_to_status:
                    self.add_message(f"To {active_ctx_name}: <{self.nick}> {text}", self.ui.colors["my_message"], context_name="Status")
            else:
                self.add_message(
                    f"Cannot send message: Channel {active_ctx_name} not fully joined (Status: {active_ctx.join_status.name if active_ctx.join_status else 'N/A'}).",
                    self.ui.colors["error"],
                    context_name=active_ctx_name
                )
        elif active_ctx.type == "query":
            self.network.send_raw(f"PRIVMSG {active_ctx_name} :{text}")
            if "echo-message" not in self.get_enabled_caps():
                self.add_message(f"<{self.nick}> {text}", self.ui.colors["my_message"], context_name=active_ctx_name)
            elif self.echo_sent_to_status:
                 self.add_message(f"To {active_ctx_name}: <{self.nick}> {text}", self.ui.colors["my_message"], context_name="Status")
        else:
            self.add_message(f"Cannot send messages to '{active_ctx_name}' (type: {active_ctx.type}). Try a command like /msg.", self.ui.colors["error"], context_name="Status")

    def handle_rehash_config(self):
        """Handles the /rehash command by reloading configuration."""
        logger.info("Attempting to reload configuration via /rehash...")
        try:
            app_config.reload_all_config_values()

            # Update IRCClient_Logic's attributes from the now-reloaded config module's globals
            self.verify_ssl_cert = app_config.VERIFY_SSL_CERT
            self.channel_log_enabled = app_config.CHANNEL_LOG_ENABLED
            self.channel_log_level = app_config.LOG_LEVEL # LOG_LEVEL in config.py is the actual level object
            self.channel_log_max_bytes = app_config.LOG_MAX_BYTES
            self.channel_log_backup_count = app_config.LOG_BACKUP_COUNT

            # Update ContextManager's default max_history for new contexts
            # This will apply to newly created contexts.
            # Existing contexts will retain their original max_history unless explicitly updated.
            if hasattr(self.context_manager, 'max_history'):
                 self.context_manager.max_history = app_config.MAX_HISTORY
            # elif hasattr(self.context_manager, 'max_history_per_context'): # Check for older name if necessary
            #      self.context_manager.max_history_per_context = app_config.MAX_HISTORY

            # Note: For logging changes like LOG_FILE or root logger level/handlers,
            # a full application restart is generally required for them to take effect
            # on the existing logging setup. This rehash primarily updates config values
            # that the application logic can adapt to at runtime.
            # Channel loggers created *after* this rehash for *new* channels will use the new settings.

            self.add_message(
                "Configuration reloaded. Some changes (like main log file settings or server connection details if manually edited in INI) may require a /reconnect or client restart to fully apply.",
                self.ui.colors["system"],
                context_name="Status"
            )
            logger.info("Configuration successfully reloaded and applied where possible.")
            self.ui_needs_update.set() # Ensure UI reflects any changes if necessary

        except Exception as e:
            logger.error(f"Error during /rehash: {e}", exc_info=True)
            self.add_message(
                f"Error reloading configuration: {e}",
                self.ui.colors["error"],
                context_name="Status"
            )
            self.ui_needs_update.set()


    def run_main_loop(self):
        # 1. Trigger: Called by `pyrc.py` after `IRCClient_Logic` is initialized, to start the client's operation.
        # 2. Expected State Before:
        #    - All handlers (`NetworkHandler`, `CapNegotiator`, `SaslAuthenticator`, `RegistrationHandler`, `UIManager`, etc.)
        #      are initialized but the network connection is not yet active.
        #    - `self.should_quit` is False.
        # 3. Key Actions:
        #    - Calls `self.network.start()`:
        #        - This is a CRITICAL step that initiates the entire connection sequence.
        #        - `NetworkHandler.start()` creates and starts a new thread for `NetworkHandler._network_loop()`.
        #        - Inside `_network_loop()`, if not connected, `NetworkHandler._connect_socket()` is called.
        #        - `_connect_socket()` establishes the TCP/IP (and SSL if enabled) connection.
        #        - Upon successful socket connection, `_connect_socket()` calls `self.cap_negotiator.start_negotiation()`.
        #        - `CapNegotiator.start_negotiation()` sends the initial "CAP LS" command, formally starting the IRC handshake.
        #    - Enters the main client loop which continues as long as `self.should_quit` is False:
        #        - Fetches user input using `self.ui.get_input_char()`.
        #        - If input is received, passes it to `self.input_handler.handle_key_press()`.
        #        - If the UI needs an update (signaled by `self.ui_needs_update.is_set()` or if input was received),
        #          calls `self.ui.refresh_all_windows()`.
        #        - Sleeps briefly to prevent high CPU usage.
        #        - Handles `curses.error`, `KeyboardInterrupt` (Ctrl+C), and other exceptions to gracefully set `self.should_quit = True`.
        #    - After the loop exits (due to `self.should_quit` becoming True):
        #        - Ensures `self.should_quit` is True.
        #        - Calls `self.network.stop()` to gracefully close the network connection (sending QUIT) and stop the network thread.
        #        - Waits for the network thread to join.
        # 4. Expected State After (Loop Exit):
        #    - `self.should_quit` is True.
        #    - The network connection is closed or being closed.
        #    - The network thread is stopped or being stopped.
        #    - The application is shutting down.
        #
        # Connection Sequence Initiation Summary within this method:
        # `run_main_loop()` -> `self.network.start()` -> `NetworkHandler._network_loop()` (new thread)
        # -> `NetworkHandler._connect_socket()` -> `self.cap_negotiator.start_negotiation()` -> Sends "CAP LS".
        # This kicks off the chain: CAP LS -> CAP ACK/NAK -> (SASL AUTHENTICATE if enabled) -> CAP END -> NICK/USER -> RPL_WELCOME.
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
                try: self.add_message(f"Curses error: {e}. Quitting.", self.ui.colors["error"], context_name="Status")
                except: pass
                self.should_quit = True; break
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received. Initiating quit.")
                self.add_message("Ctrl+C pressed. Quitting...", self.ui.colors["system"], context_name="Status")
                self.should_quit = True
                break
            except Exception as e:
                logger.critical(f"Unhandled exception in main client loop: {e}", exc_info=True)
                try: self.add_message(f"CRITICAL ERROR: {e}. Attempting to quit.", self.ui.colors["error"], context_name="Status")
                except: pass
                self.should_quit = True; break

        logger.info("Main client loop ended.")
        self.should_quit = True
        self.network.stop(send_quit=self.network.connected, quit_message=LEAVE_MESSAGE)
        if self.network.network_thread and self.network.network_thread.is_alive():
            logger.debug("Waiting for network thread to join...")
            self.network.network_thread.join(timeout=2.0)
            if self.network.network_thread.is_alive(): logger.warning("Network thread did not join in time.")
            else: logger.debug("Network thread joined successfully.")
