import curses
import threading
import time
import socket
from collections import deque
from typing import Optional, Any, List, Set, Dict, Tuple
import logging
import logging.handlers
import os
import platform

from config import (
    MAX_HISTORY,
    VERIFY_SSL_CERT,
    CHANNEL_LOG_ENABLED,
    LOG_LEVEL,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    BASE_DIR,
    is_source_ignored,
    reload_all_config_values,  # For /rehash
    ENABLE_TRIGGER_SYSTEM,
    DISABLED_SCRIPTS,
    HEADLESS_MAX_HISTORY,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    CONNECTION_TIMEOUT,
)

# Import the config module itself to access its updated globals after reload
import config as app_config
from script_manager import ScriptManager  # Add this

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


class DummyUI:
    """A dummy UI class for headless mode that provides no-op implementations of UI methods."""

    def __init__(self):
        self.colors = {
            "default": 0,
            "system": 0,
            "join_part": 0,
            "nick_change": 0,
            "my_message": 0,
            "other_message": 0,
            "highlight": 0,
            "error": 0,
            "status_bar": 0,
            "sidebar_header": 0,
            "sidebar_item": 0,
            "sidebar_user": 0,
            "input": 0,
            "pm": 0,
            "user_prefix": 0,
            "warning": 0,
            "info": 0,
            "debug": 0,
            "timestamp": 0,
            "nick": 0,
            "channel": 0,
            "query": 0,
            "status": 0,
            "list": 0,
            "list_selected": 0,
            "list_header": 0,
            "list_footer": 0,
            "list_highlight": 0,
            "list_selected_highlight": 0,
            "list_selected_header": 0,
            "list_selected_footer": 0,
            "list_selected_highlight_header": 0,
            "list_selected_highlight_footer": 0,
        }
        self.split_mode_active = False
        self.active_split_pane = "top"
        self.top_pane_context_name = ""
        self.bottom_pane_context_name = ""
        self.msg_win_width = 80  # Default width for message window
        self.msg_win_height = 24  # Default height for message window
        self.user_list_width = 20  # Default width for user list
        self.user_list_height = 24  # Default height for user list
        self.status_win_height = 1  # Default height for status window
        self.input_win_height = 1  # Default height for input window
        self.msg_win = None
        self.user_list_win = None
        self.status_win = None
        self.input_win = None
        self.stdscr = None

    def refresh_all_windows(self):
        pass

    def scroll_messages(self, direction: str, lines: int = 1):
        pass

    def get_input_char(self) -> int:
        return curses.ERR

    def setup_layout(self):
        pass

    def scroll_user_list(self, direction: str, lines_arg: int = 1):
        pass


class IRCClient_Logic:
    # Class-level flag to track if exit screen has been shown
    exit_screen_shown = False

    def __init__(
        self,
        stdscr,
        args,
        server_addr,
        port,
        nick,
        initial_channels_raw: list,
        password,
        nickserv_password,
        use_ssl,
    ):
        self.stdscr = stdscr
        self.is_headless = stdscr is None
        self.args = args  # Store args for access by other components
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
        logger.info(
            f"IRCClient_Logic.__init__: server='{server_addr}', port={port}, use_ssl={self.use_ssl}, verify_ssl_cert={self.verify_ssl_cert}, headless={self.is_headless}"
        )
        self.echo_sent_to_status: bool = True
        self.show_raw_log_in_ui: bool = False

        # Set max history based on mode
        max_hist_to_use = MAX_HISTORY  # Default
        if self.is_headless:
            headless_hist_val = HEADLESS_MAX_HISTORY
            if isinstance(headless_hist_val, int) and headless_hist_val >= 0:
                max_hist_to_use = headless_hist_val
                logger.info(
                    f"Headless mode: Using MAX_HISTORY of {max_hist_to_use} from 'headless_message_history_lines'."
                )
            else:
                logger.info(
                    f"Headless mode: Using default MAX_HISTORY of {max_hist_to_use} ('headless_message_history_lines' not configured or invalid)."
                )
        else:  # UI mode
            logger.info(f"UI mode: Using MAX_HISTORY of {max_hist_to_use}.")

        self.context_manager = ContextManager(max_history_per_context=max_hist_to_use)
        self.context_manager.create_context("Status", context_type="status")
        self.context_manager.set_active_context("Status")

        # Create contexts for initial channels but don't join them yet
        for ch_name in self.initial_channels_list:
            self.context_manager.create_context(
                ch_name,
                context_type="channel",
                initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN,
            )
        self.last_join_command_target: Optional[str] = None

        self.should_quit = False
        self.ui_needs_update = threading.Event()

        self.desired_caps_config: Set[str] = {
            "sasl",
            "multi-prefix",
            "server-time",
            "message-tags",
            "account-tag",
            "echo-message",
            "away-notify",
            "chghost",
            "userhost-in-names",
            "cap-notify",
            "extended-join",
            "account-notify",
            "invite-notify",
        }

        self.network_handler = NetworkHandler(self)
        self.network_handler.channels_to_join_on_connect = self.initial_channels_list[:]

        # Initialize UI based on mode
        if self.is_headless:
            self.ui = DummyUI()
            self.input_handler = None
        else:
            self.ui = UIManager(stdscr, self)
            self.input_handler = InputHandler(self)

        self.command_handler = CommandHandler(self)

        # Initialize ScriptManager with disabled scripts from both config and CLI
        cli_disabled = (
            set(self.args.disable_script)
            if hasattr(self.args, "disable_script") and self.args.disable_script
            else set()
        )
        config_disabled = set(DISABLED_SCRIPTS)
        self.script_manager = ScriptManager(
            self, BASE_DIR, disabled_scripts=cli_disabled.union(config_disabled)
        )
        self.script_manager.load_scripts()

        # Initialize TriggerManager only if enabled
        if ENABLE_TRIGGER_SYSTEM:
            config_dir_triggers = os.path.join(BASE_DIR, "config")
            if not os.path.exists(config_dir_triggers):
                try:
                    os.makedirs(config_dir_triggers, exist_ok=True)
                except OSError as e_mkdir:
                    logger.error(
                        f"Could not create config directory for triggers: {e_mkdir}"
                    )
            self.trigger_manager = TriggerManager(config_dir_triggers)
            logger.info("TriggerManager initialized.")
        else:
            self.trigger_manager = None
            logger.info(
                "TriggerManager is disabled by configuration (ENABLE_TRIGGER_SYSTEM=False)."
            )

        self.cap_negotiator = CapNegotiator(
            network_handler=self.network_handler,
            desired_caps=self.desired_caps_config,
            registration_handler=None,
            client_logic_ref=self,
        )

        self.sasl_authenticator = SaslAuthenticator(
            network_handler=self.network_handler,
            cap_negotiator=self.cap_negotiator,
            password=self.nickserv_password,
            client_logic_ref=self,
        )

        self.registration_handler = RegistrationHandler(
            network_handler=self.network_handler,
            command_handler=self.command_handler,
            initial_nick=self.initial_nick,
            username=self.initial_nick,
            realname=self.initial_nick,
            server_password=self.password,
            nickserv_password=self.nickserv_password,
            initial_channels_to_join=self.initial_channels_list,
            cap_negotiator=self.cap_negotiator,
            client_logic_ref=self,
        )

        self.cap_negotiator.set_registration_handler(self.registration_handler)
        self.cap_negotiator.set_sasl_authenticator(self.sasl_authenticator)
        self.registration_handler.set_sasl_authenticator(self.sasl_authenticator)

        # Only initialize input handler in non-headless mode
        if not self.is_headless:
            self.input_handler = InputHandler(self)

        # Determine platform-specific config directory
        if platform.system() == "Windows":
            config_dir = os.path.join(
                os.getenv("APPDATA", os.path.expanduser("~")), "PyRC"
            )
        elif platform.system() == "Darwin":
            config_dir = os.path.join(
                os.path.expanduser("~"), "Library", "Application Support", "PyRC"
            )
        else:  # Linux and other Unix-like systems
            config_dir = os.path.join(os.path.expanduser("~"), ".config", "pyrc")

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
        self.active_list_context_name: Optional[str] = None  # For /list command output

        if self.channel_log_enabled and not os.path.exists(self.main_log_dir_path):
            try:
                os.makedirs(self.main_log_dir_path)
                logger.info(
                    f"Created main log directory in logic: {self.main_log_dir_path}"
                )
            except OSError as e:
                logger.error(
                    f"Error creating main log directory in logic {self.main_log_dir_path}: {e}"
                )
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

        self.max_history = max_hist_to_use
        self.reconnect_delay = RECONNECT_INITIAL_DELAY
        self.max_reconnect_delay = RECONNECT_MAX_DELAY
        self.connection_timeout = CONNECTION_TIMEOUT

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
        is_privmsg_or_notice: bool = False,
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
            logger.error(
                "add_message called with no target_context_name and no active context."
            )
            target_context_name = "Status"

        if (
            is_privmsg_or_notice
            and source_full_ident
            and is_source_ignored(source_full_ident)
        ):
            logger.debug(
                f"Ignoring message from {source_full_ident} due to ignore list match."
            )
            return

        target_ctx_exists = self.context_manager.get_context(target_context_name)
        if not target_ctx_exists:
            context_type = "generic"
            initial_join_status_for_new_channel: Optional[ChannelJoinStatus] = None
            if target_context_name.startswith(("#", "&", "+", "!")):
                context_type = "channel"
                initial_join_status_for_new_channel = ChannelJoinStatus.NOT_JOINED
            elif (
                target_context_name != "Status"
                and ":" not in target_context_name
                and not target_context_name.startswith("#")
            ):
                context_type = "query"

            if self.context_manager.create_context(
                target_context_name,
                context_type=context_type,
                initial_join_status_for_channel=initial_join_status_for_new_channel,
            ):
                logger.info(
                    f"Dynamically created context '{target_context_name}' of type '{context_type}' for message."
                )
            else:
                logger.error(
                    f"Failed to create context '{target_context_name}'. Adding message to 'Status'."
                )
                status_ctx_for_error = self.context_manager.get_context("Status")
                if not status_ctx_for_error:
                    self.context_manager.create_context("Status", context_type="status")

                self.context_manager.add_message_to_context(
                    "Status",
                    f"[CtxErr for {target_context_name}] {text}",
                    color_attr,
                )
                self.ui_needs_update.set()
                return

        target_context_obj = self.context_manager.get_context(target_context_name)
        if not target_context_obj:
            logger.critical(
                f"Context {target_context_name} is unexpectedly None after creation/check. Message lost: {text}"
            )
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
            if current_line and (len(current_line) + len(word) + 1 > max_w):
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

        sanitized_name_part = channel_name.lstrip("#&+!").lower()
        safe_filename_part = "".join(
            c if c.isalnum() else "_" for c in sanitized_name_part
        )

        logger_key = safe_filename_part

        if logger_key in self.channel_loggers:
            return self.channel_loggers[logger_key]

        try:
            log_file_name = f"{safe_filename_part}.log"
            channel_log_file_path = os.path.join(self.main_log_dir_path, log_file_name)

            channel_logger_instance = logging.getLogger(
                f"pyrc.channel.{safe_filename_part}"
            )
            channel_logger_instance.setLevel(self.channel_log_level)

            if not os.path.exists(self.main_log_dir_path):
                logger.warning(
                    f"Main log directory {self.main_log_dir_path} not found when creating logger for {channel_name}. Attempting to create."
                )
                try:
                    os.makedirs(self.main_log_dir_path)
                except OSError as e:
                    logger.error(
                        f"Failed to create main log directory {self.main_log_dir_path} for {channel_name}: {e}. Disabling logger for this channel."
                    )
                    return None

            file_handler = logging.handlers.RotatingFileHandler(
                channel_log_file_path,
                maxBytes=self.channel_log_max_bytes,
                backupCount=self.channel_log_backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(self.log_formatter)

            channel_logger_instance.addHandler(file_handler)
            channel_logger_instance.propagate = (
                False  # IMPORTANT: Prevent duplication to root logger / main file
            )

            self.channel_loggers[logger_key] = channel_logger_instance
            logger.info(
                f"Initialized logger for channel {channel_name} at {channel_log_file_path}"
            )
            return channel_logger_instance
        except Exception as e:
            logger.error(
                f"Failed to create logger for channel {channel_name}: {e}",
                exc_info=True,
            )
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
            self.add_message(
                f"S << {line.strip()}",
                self.ui.colors.get("system", 0),
                context_name="Status",
                prefix_time=True,
            )

        parsed_msg = IRCMessage.parse(line)
        if (
            parsed_msg
            and parsed_msg.command in ["PRIVMSG", "NOTICE"]
            and parsed_msg.params
            and parsed_msg.params[0].startswith(("#", "&", "+", "!"))
        ):
            target_channel = parsed_msg.params[0]
            channel_logger = self.get_channel_logger(target_channel)
            if channel_logger:
                # The raw line is already being logged to general log if enabled,
                # and channel specific log for PRIVMSG/NOTICE to channels if enabled.
                # No need to duplicate raw log here specifically unless desired for a different format.
                # The S << line above handles UI display.
                pass  # Placeholder if specific raw logging to file for this flag was intended beyond UI

        irc_protocol.handle_server_message(self, line)

    def switch_active_context(self, direction: str):
        context_names = self.context_manager.get_all_context_names()
        if not context_names:
            return

        if "Status" in context_names:
            sorted_context_names = ["Status"] + sorted(
                [name for name in context_names if name != "Status"],
                key=lambda x: x.lower(),
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
            if not sorted_context_names:
                return
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
            if direction in sorted_context_names:
                new_active_context_name = direction
            else:
                try:
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
                except ValueError:
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
                        exact_match_case_insensitive = [
                            name
                            for name in sorted_context_names
                            if direction.lower() == name.lower()
                        ]
                        if len(exact_match_case_insensitive) == 1:
                            new_active_context_name = exact_match_case_insensitive[0]
                        else:
                            self.add_message(
                                f"Window '{direction}' not found.",
                                self.ui.colors["error"],
                                context_name=current_active_name,
                            )
                            return

        if new_active_context_name:
            target_ctx_to_activate = self.context_manager.get_context(
                new_active_context_name
            )
            if (
                target_ctx_to_activate
                and target_ctx_to_activate.type == "channel"
                and target_ctx_to_activate.join_status
                and target_ctx_to_activate.join_status != ChannelJoinStatus.FULLY_JOINED
            ):
                join_status_name = target_ctx_to_activate.join_status.name
                self.add_message(
                    f"Channel {new_active_context_name} is not fully joined yet (Status: {join_status_name}).",
                    self.ui.colors["system"],
                    context_name=current_active_name,
                )

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
            self.add_message(
                "No channels or Status window to switch to.",
                self.ui.colors["system"],
                context_name=self.context_manager.active_context_name or "Status",
            )
            return

        current_active_name_str: Optional[str] = (
            self.context_manager.active_context_name
        )
        current_idx = -1

        if current_active_name_str:
            try:
                current_idx = channel_context_names.index(current_active_name_str)
            except ValueError:
                current_idx = -1
                logger.debug(
                    f"Active context '{current_active_name_str}' not in channel/status cycle list."
                )

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
                logger.debug(
                    f"Switched active channel/status to: {self.context_manager.active_context_name}"
                )
                self.ui_needs_update.set()
            else:
                logger.error(
                    f"Failed to set active channel/status to {new_active_channel_name}."
                )
                self.add_message(
                    f"Error switching to '{new_active_channel_name}'.",
                    self.ui.colors["error"],
                    context_name=current_active_name_str or "Status",
                )

    def is_cap_negotiation_pending(self) -> bool:
        return self.cap_negotiator.is_cap_negotiation_pending()

    def is_sasl_completed(self) -> bool:
        return (
            self.sasl_authenticator.is_completed() if self.sasl_authenticator else True
        )

    def get_enabled_caps(self) -> Set[str]:
        """Returns the set of currently enabled capabilities."""
        return self.cap_negotiator.get_enabled_caps() if self.cap_negotiator else set()

    def handle_channel_fully_joined(self, channel_name: str):
        """
        Called when a channel is confirmed as fully joined (e.g., after RPL_ENDOFNAMES).
        If this channel was the target of the last /join command, make it active.
        """
        normalized_channel_name = self.context_manager._normalize_context_name(
            channel_name
        )
        logger.info(f"Channel {normalized_channel_name} reported as fully joined.")

        if (
            self.last_join_command_target
            and self.context_manager._normalize_context_name(
                self.last_join_command_target
            )
            == normalized_channel_name
        ):

            logger.info(
                f"Setting active context to recently joined channel: {normalized_channel_name}"
            )
            self.context_manager.set_active_context(normalized_channel_name)
            self.last_join_command_target = None
            self.ui_needs_update.set()
        else:
            active_ctx = self.context_manager.get_active_context()
            if not active_ctx or active_ctx.name == "Status":
                if channel_name in self.initial_channels_list:
                    logger.info(
                        f"Auto-joined channel {normalized_channel_name} is now fully joined. Setting active."
                    )
                    self.context_manager.set_active_context(normalized_channel_name)
                    self.ui_needs_update.set()

    def _execute_python_trigger(
        self, code: str, event_data: Dict[str, Any], trigger_info_for_error: str
    ):
        """
        Executes a Python code snippet from a trigger.
        WARNING: This uses exec() and can be dangerous if untrusted code is used.
        """
        current_context_name = self.context_manager.active_context_name or "Status"
        try:
            # Prepare a limited execution scope
            # Provide 'client' for interacting with the IRC client and 'event_data' for trigger context
            execution_globals = {}  # Or provide some safe builtins if needed
            execution_locals = {
                "client": self,  # Gives access to self.add_message, self.send_raw etc.
                "event_data": event_data,  # Contains $nick, $channel, $msg, $0, $1 etc.
            }
            exec(code, execution_globals, execution_locals)
        except Exception as e:
            error_message = f"Error executing Python trigger ({trigger_info_for_error}): {type(e).__name__}: {e}"
            logger.error(error_message, exc_info=True)
            self.add_message(
                error_message,
                self.ui.colors["error"],
                prefix_time=True,
                context_name="Status",
            )
            # Optionally, add more detailed error to a specific debug context or log if too verbose for main chat

    def process_trigger_event(
        self, event_type: str, event_data: Dict[str, Any]
    ) -> Optional[str]:
        """Process a trigger event and return any action to take."""
        if not ENABLE_TRIGGER_SYSTEM or not self.trigger_manager:
            return None

        result = self.trigger_manager.process_trigger(event_type, event_data)
        if not result:
            return None

        action_type = result.get("action_type")
        if action_type == "command":
            return result.get("content")
        elif action_type == "python":
            # Execute Python trigger
            code = result.get("content")
            if code:
                try:
                    exec(code, {"event_data": event_data})
                except Exception as e:
                    logger.error(f"Error executing Python trigger: {e}")
        return None

    def handle_text_input(self, text: str):
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

        if active_ctx.type == "channel":
            if active_ctx.join_status == ChannelJoinStatus.FULLY_JOINED:
                self.network_handler.send_raw(f"PRIVMSG {active_ctx_name} :{text}")
                if "echo-message" not in self.get_enabled_caps():
                    self.add_message(
                        f"<{self.nick}> {text}",
                        self.ui.colors["my_message"],
                        context_name=active_ctx_name,
                    )
                elif self.echo_sent_to_status:
                    self.add_message(
                        f"To {active_ctx_name}: <{self.nick}> {text}",
                        self.ui.colors["my_message"],
                        context_name="Status",
                    )
            else:
                self.add_message(
                    f"Cannot send message: Channel {active_ctx_name} not fully joined (Status: {active_ctx.join_status.name if active_ctx.join_status else 'N/A'}).",
                    self.ui.colors["error"],
                    context_name=active_ctx_name,
                )
        elif active_ctx.type == "query":
            self.network_handler.send_raw(f"PRIVMSG {active_ctx_name} :{text}")
            if "echo-message" not in self.get_enabled_caps():
                self.add_message(
                    f"<{self.nick}> {text}",
                    self.ui.colors["my_message"],
                    context_name=active_ctx_name,
                )
            elif self.echo_sent_to_status:
                self.add_message(
                    f"To {active_ctx_name}: <{self.nick}> {text}",
                    self.ui.colors["my_message"],
                    context_name="Status",
                )
        else:
            self.add_message(
                f"Cannot send messages to '{active_ctx_name}' (type: {active_ctx.type}). Try a command like /msg.",
                self.ui.colors["error"],
                context_name="Status",
            )

    def handle_rehash_config(self):
        """Handles the /rehash command by reloading configuration."""
        logger.info("Attempting to reload configuration via /rehash...")
        try:
            app_config.reload_all_config_values()

            # Update IRCClient_Logic's attributes from the now-reloaded config module's globals
            self.verify_ssl_cert = app_config.VERIFY_SSL_CERT
            self.channel_log_enabled = app_config.CHANNEL_LOG_ENABLED
            self.channel_log_level = (
                app_config.LOG_LEVEL
            )  # LOG_LEVEL in config.py is the actual level object
            self.channel_log_max_bytes = app_config.LOG_MAX_BYTES
            self.channel_log_backup_count = app_config.LOG_BACKUP_COUNT

            # Update ContextManager's default max_history for new contexts
            # This will apply to newly created contexts.
            # Existing contexts will retain their original max_history unless explicitly updated.
            if hasattr(self.context_manager, "max_history"):
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
                context_name="Status",
            )
            logger.info(
                "Configuration successfully reloaded and applied where possible."
            )
            self.ui_needs_update.set()  # Ensure UI reflects any changes if necessary

        except Exception as e:
            logger.error(f"Error during /rehash: {e}", exc_info=True)
            self.add_message(
                f"Error reloading configuration: {e}",
                self.ui.colors["error"],
                context_name="Status",
            )
            self.ui_needs_update.set()

    def run_main_loop(self):
        """Main loop for the IRC client."""
        logger.info(f"Starting main client loop (headless={self.is_headless}).")
        if not self.is_headless:
            self.ui.refresh_all_windows()  # Initial draw

        # Start network operations if not already started
        if (
            not self.network_handler.network_thread
            or not self.network_handler.network_thread.is_alive()
        ):
            self.network_handler.start()
            if self.is_headless:  # Specific log for headless start after network
                logger.info("Started network connection in headless mode")

        try:
            while not self.should_quit:
                if not self.is_headless and self.input_handler and self.ui:
                    key_code = self.ui.get_input_char()
                    if key_code != curses.ERR:
                        self.input_handler.handle_key_press(key_code)
                    if self.ui_needs_update.is_set() or key_code != curses.ERR:
                        self.ui.refresh_all_windows()
                        if self.ui_needs_update.is_set():
                            self.ui_needs_update.clear()
                else:  # Headless mode or UI not fully up
                    if self.ui_needs_update.is_set():  # Scripts might still set this
                        if not self.is_headless and self.ui:  # Refresh if UI exists
                            self.ui.refresh_all_windows()
                        self.ui_needs_update.clear()

                time.sleep(0.05)  # Main loop sleep

        except KeyboardInterrupt:
            logger.info(
                "Keyboard interrupt received in main client loop. Initiating quit."
            )
            self.should_quit = True
        except curses.error as e:
            if not self.is_headless:  # Only relevant if curses is active
                logger.error(f"Curses error in main loop: {e}", exc_info=True)
                try:
                    self.add_message(
                        f"Curses error: {e}. Quitting.",
                        self.ui.colors["error"],
                        prefix_time=True,
                        context_name="Status",
                    )
                except:
                    pass
            else:
                logger.error(
                    f"Curses-related error in headless main loop (should not happen often): {e}",
                    exc_info=True,
                )
            self.should_quit = True
        except Exception as e:
            logger.critical(
                f"Unhandled exception in main client loop: {e}", exc_info=True
            )
            try:
                self.add_message(
                    f"CRITICAL ERROR: {e}. Attempting to quit.",
                    self.ui.colors["error"],
                    prefix_time=True,
                    context_name="Status",
                )
            except:
                pass
            self.should_quit = True
        finally:
            logger.info("IRCClient_Logic.run_main_loop() finally block executing.")
            self.should_quit = True  # Ensure this is set

            quit_message_to_send = "PyRC - Exiting"
            if hasattr(self, "script_manager") and self.script_manager:
                # Allow scripts to provide a quit message
                temp_nick_for_quit = self.nick
                temp_server_for_quit = self.server
                random_msg = self.script_manager.get_random_quit_message_from_scripts(
                    {"nick": temp_nick_for_quit, "server": temp_server_for_quit}
                )
                if random_msg:
                    quit_message_to_send = random_msg

            # Store the quit message for NetworkHandler to use
            self._final_quit_message = quit_message_to_send

            if self.network_handler:
                logger.debug(
                    "Calling network_handler.stop() from IRCClient_Logic.run_main_loop finally."
                )
                self.network_handler.disconnect_gracefully(
                    quit_message=quit_message_to_send
                )

                if (
                    self.network_handler.network_thread
                    and self.network_handler.network_thread.is_alive()
                ):
                    logger.debug(
                        "Waiting for network thread to join in IRCClient_Logic.run_main_loop finally."
                    )
                    self.network_handler.network_thread.join(
                        timeout=2.0
                    )  # Increased timeout slightly
                    if self.network_handler.network_thread.is_alive():
                        logger.warning(
                            "Network thread did not join in time from IRCClient_Logic."
                        )
                    else:
                        logger.debug(
                            "Network thread joined successfully from IRCClient_Logic."
                        )
            logger.info("IRCClient_Logic.run_main_loop() completed.")

    def initialize(self) -> bool:
        """Initialize the client components."""
        try:
            # Initialize network handler
            self.network_handler = NetworkHandler(self)

            # Initialize script manager with disabled scripts
            self.script_manager = ScriptManager(self, BASE_DIR)
            self.script_manager.disabled_scripts = set(DISABLED_SCRIPTS)
            self.script_manager.load_scripts()

            # Initialize trigger manager if enabled
            if ENABLE_TRIGGER_SYSTEM:
                self.trigger_manager = TriggerManager(os.path.join(BASE_DIR, "config"))
                self.trigger_manager.load_triggers()
            else:
                logger.info("Trigger system is disabled")

            return True
        except Exception as e:
            logger.error(f"Failed to initialize client: {str(e)}")
            return False

    def connect(self, server: str, port: int, use_ssl: bool = False) -> bool:
        """Connect to an IRC server."""
        if not self.network_handler:
            logger.error("Network handler not initialized")
            return False

        try:
            self.network_handler.update_connection_params(
                server=server, port=port, use_ssl=use_ssl
            )
            self.network_handler.start()
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {str(e)}")
            return False

    def disconnect(self, quit_message: str = "Client disconnecting") -> None:
        """Disconnect from the server."""
        if self.network_handler:
            self.network_handler.disconnect_gracefully(quit_message)

    def process_message(self, message: str) -> Optional[str]:
        """Process an incoming message through triggers."""
        if not ENABLE_TRIGGER_SYSTEM:
            return None

        trigger_manager = self.trigger_manager
        if not trigger_manager or not hasattr(trigger_manager, "process_trigger"):
            return None

        try:
            result = trigger_manager.process_trigger("TEXT", {"message": message})
            if result and result["type"] == ActionType.COMMAND:
                return result["content"]
        except Exception as e:
            logger.error(f"Error processing trigger: {e}")
        return None

    def handle_reconnect(self) -> None:
        """Handle reconnection with exponential backoff."""
        if self.reconnect_delay < self.max_reconnect_delay:
            self.reconnect_delay *= 2
        logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")

    def reset_reconnect_delay(self) -> None:
        """Reset the reconnect delay to initial value."""
        self.reconnect_delay = RECONNECT_INITIAL_DELAY
