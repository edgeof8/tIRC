# pyrc_core/client/irc_client_logic.py
from __future__ import annotations
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

from pyrc_core import app_config as _app_config
from typing import cast
from pyrc_core.app_config import _AppConfigModule, ServerConfig

app_config: _AppConfigModule = cast(_AppConfigModule, _app_config)

from pyrc_core.logging.channel_logger import ChannelLoggerManager
from pyrc_core.scripting.script_manager import ScriptManager
from pyrc_core.event_manager import EventManager
from pyrc_core.context_manager import ContextManager, ChannelJoinStatus
from pyrc_core.client.ui_manager import UIManager
from pyrc_core.network_handler import NetworkHandler
from pyrc_core.commands.command_handler import CommandHandler
from pyrc_core.client.input_handler import InputHandler
from pyrc_core.features.triggers.trigger_manager import TriggerManager, ActionType
from pyrc_core.features.triggers.trigger_commands import TriggerCommands
from pyrc_core.irc import irc_protocol
from pyrc_core.irc.irc_message import IRCMessage
from pyrc_core.irc.cap_negotiator import CapNegotiator
from pyrc_core.irc.sasl_authenticator import SaslAuthenticator
from pyrc_core.irc.registration_handler import RegistrationHandler
from pyrc_core.scripting.python_trigger_api import PythonTriggerAPI

# DCC Imports
from pyrc_core.dcc.dcc_manager import DCCManager
# Moved DCC imports to avoid circular dependencies
# Will be imported lazily when needed
dcc_commands = None

logger = logging.getLogger("pyrc.logic")


class DummyUI:
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
        self.msg_win_width = 80
        self.msg_win_height = 24
        self.user_list_width = 20
        self.user_list_height = 24
        self.status_win_height = 1
        self.input_win_height = 1
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
        return curses.ERR if curses else -1

    def setup_layout(self):
        pass

    def scroll_user_list(self, direction: str, lines_arg: int = 1):
        pass

    def _calculate_available_lines_for_user_list(self) -> int:
        return 0


class IRCClient_Logic:
    exit_screen_shown = False
    reconnect_delay: int
    max_reconnect_delay: int
    pending_server_switch_config_name: Optional[str] = None # ADDED
    # Event to signal disconnect completion for /server command
    _server_switch_disconnect_event: Optional[threading.Event] = None # ADDED
    _server_switch_target_config_name: Optional[str] = None # ADDED

    def __init__(self, stdscr, args):
        self.stdscr = stdscr
        self.is_headless = stdscr is None
        self.args = args
        self.app_config = app_config
        self.all_server_configs = app_config.ALL_SERVER_CONFIGS  # type: ignore
        self.active_server_config_name: Optional[str] = None
        self.active_server_config: Optional[ServerConfig] = None
        self.pending_server_switch_config_name = None # Initialize
        self._server_switch_disconnect_event = None
        self._server_switch_target_config_name = None

        # Initialize Managers
        self.channel_logger_manager = ChannelLoggerManager()

        if hasattr(args, "server") and args.server:
            cli_port = (
                args.port
                if hasattr(args, "port") and args.port is not None
                else (
                    self.app_config.DEFAULT_SSL_PORT  # type: ignore
                    if (hasattr(args, "ssl") and args.ssl)
                    else self.app_config.DEFAULT_PORT  # type: ignore
                )
            )
            cli_nick = (
                args.nick
                if hasattr(args, "nick") and args.nick
                else self.app_config.DEFAULT_NICK  # type: ignore
            )
            cli_channels = (
                args.channel if hasattr(args, "channel") and args.channel else []
            )
            cli_ssl = args.ssl if hasattr(args, "ssl") else False
            cli_password = args.password if hasattr(args, "password") else None
            cli_nickserv_password = (
                args.nickserv_password if hasattr(args, "nickserv_password") else None
            )

            temp_config = app_config.ServerConfig(
                server_id="CommandLine",
                address=args.server,
                port=cli_port,
                ssl=cli_ssl,
                nick=cli_nick,
                channels=cli_channels,
                server_password=cli_password,
                nickserv_password=cli_nickserv_password,
                verify_ssl_cert=self.app_config.VERIFY_SSL_CERT,
                auto_connect=True,
            )
            self.active_server_config = temp_config
            self.active_server_config_name = "CommandLine"
            logger.info(f"Using command-line server configuration: {args.server}")
        elif (
            self.app_config.DEFAULT_SERVER_CONFIG_NAME
            and self.app_config.DEFAULT_SERVER_CONFIG_NAME in self.all_server_configs
        ):
            self.active_server_config_name = self.app_config.DEFAULT_SERVER_CONFIG_NAME
            self.active_server_config = self.all_server_configs[
                self.app_config.DEFAULT_SERVER_CONFIG_NAME
            ]
            logger.info(
                f"Using default server configuration: {self.active_server_config_name}"
            )
        else:
            self.active_server_config = None
            self.active_server_config_name = None
            logger.warning(
                "No command-line server specified and no default server configuration found."
            )

        if self.active_server_config:
            self.server = self.active_server_config.address
            self.port = self.active_server_config.port
            self.initial_nick = self.active_server_config.nick
            self.nick = self.active_server_config.nick
            self.initial_channels_list = self.active_server_config.channels[:]
            self.password = self.active_server_config.server_password
            self.nickserv_password = self.active_server_config.nickserv_password
            self.use_ssl = self.active_server_config.ssl
            self.verify_ssl_cert = self.active_server_config.verify_ssl_cert
        else:
            self.server = None
            self.port = None
            self.initial_nick = self.app_config.DEFAULT_NICK  # type: ignore
            self.nick = self.app_config.DEFAULT_NICK  # type: ignore
            self.initial_channels_list = self.app_config.DEFAULT_CHANNELS[:]  # type: ignore
            self.password = self.app_config.DEFAULT_PASSWORD  # type: ignore
            self.nickserv_password = self.app_config.DEFAULT_NICKSERV_PASSWORD  # type: ignore
            self.use_ssl = self.app_config.DEFAULT_SSL  # type: ignore
            self.verify_ssl_cert = self.app_config.DEFAULT_VERIFY_SSL_CERT  # type: ignore

        self.currently_joined_channels: Set[str] = set()
        logger.info(
            f"IRCClient_Logic.__init__: server='{self.server}', port={self.port}, nick='{self.nick}' use_ssl={self.use_ssl}, verify_ssl_cert={self.verify_ssl_cert}, headless={self.is_headless}"
        )
        self.echo_sent_to_status: bool = True
        self.show_raw_log_in_ui: bool = False

        self.context_manager = ContextManager(max_history_per_context=app_config.MAX_HISTORY)
        self.context_manager.create_context("Status", context_type="status")
        self.context_manager.create_context(
            "DCC", context_type="dcc_transfers"
        )
        self.context_manager.set_active_context("Status")

        for ch_name in self.initial_channels_list:
            self.context_manager.create_context(
                ch_name,
                context_type="channel",
                initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN,
            )
        self.last_join_command_target: Optional[str] = None
        self.should_quit = False
        self.ui_needs_update = threading.Event()
        # NetworkHandler uses client_logic_ref attributes, ensure they are correct
        self.network_handler = NetworkHandler(self)
        self.network_handler.channels_to_join_on_connect = self.initial_channels_list[:]

        if self.server and self.port is not None:
            self.network_handler.start()

        if self.is_headless:
            self.ui = DummyUI()
            self.input_handler = None
        else:
            self.ui = UIManager(stdscr, self)
            self.input_handler = InputHandler(self)

        cli_disabled = (
            set(self.args.disable_script)
            if hasattr(self.args, "disable_script") and self.args.disable_script
            else set()
        )
        # Assuming app_config.DISABLED_SCRIPTS is already a set due to app_config.py fix
        config_disabled = app_config.DISABLED_SCRIPTS
        self.script_manager = ScriptManager(
            self, app_config.BASE_DIR, disabled_scripts=cli_disabled.union(config_disabled)
        )

        self.command_handler = CommandHandler(self)
        self._initialize_connection_handlers()
        self.event_manager = EventManager(self, self.script_manager)
        self.dcc_manager = DCCManager(
            self, self.event_manager
        )

        self.script_manager.load_scripts()

        if app_config.ENABLE_TRIGGER_SYSTEM:
            config_dir_triggers = os.path.join(app_config.BASE_DIR, "config")
            if not os.path.exists(config_dir_triggers):
                try:
                    os.makedirs(config_dir_triggers, exist_ok=True)
                except OSError as e_mkdir:
                    logger.error(
                        f"Could not create config directory for triggers: {e_mkdir}"
                    )
            self.trigger_manager = TriggerManager(config_dir_triggers)
            self.trigger_manager.load_triggers()
        else:
            self.trigger_manager = None

        if not self.is_headless and not self.input_handler:
            self.input_handler = InputHandler(self)

        if platform.system() == "Windows":
            config_dir = os.path.join(
                os.getenv("APPDATA", os.path.expanduser("~")), "PyRC"
            )
        elif platform.system() == "Darwin":
            config_dir = os.path.join(
                os.path.expanduser("~"), "Library", "Application Support", "PyRC"
            )
        else:
            config_dir = os.path.join(os.path.expanduser("~"), ".config", "pyrc")

        self.active_list_context_name: Optional[str] = None
        self.user_modes: List[str] = []

        if not self.active_server_config:
            self._add_status_message(
                "No server specified and no default configuration. Use /server <name> or /connect <host> to connect.",
                "warning",
            )
        self._add_status_message("Simple IRC Client starting...")
        initial_channels_display = (
            ", ".join(self.initial_channels_list)
            if self.initial_channels_list
            else "None"
        )
        self._add_status_message(
            f"Target: {self.server or 'Not configured'}:{self.port or 'N/A'}, Nick: {self.nick}, Channels: {initial_channels_display}"
        )
        logger.info(
            f"IRCClient_Logic initialized for {self.server or 'Not configured'}:{self.port or 'N/A'} as {self.nick}. Channels: {initial_channels_display}"
        )
        self.max_history = app_config.MAX_HISTORY  # type: ignore
        self.reconnect_delay = int(app_config.RECONNECT_INITIAL_DELAY)  # type: ignore
        self.max_reconnect_delay = int(app_config.RECONNECT_MAX_DELAY)  # type: ignore
        self.connection_timeout = int(app_config.CONNECTION_TIMEOUT)  # type: ignore
        self.last_attempted_nick_change: Optional[str] = None
        self._final_quit_message = None
        self._handle_user_input = self._handle_user_input_impl
        self._update_ui = self._update_ui_impl


    def _add_status_message(self, text: str, color_key: str = "system"):
        color_attr = self.ui.colors.get(color_key, self.ui.colors.get("system", 0))
        logger.info(f"[StatusUpdate via Helper] ColorKey: '{color_key}', Text: {text}")
        self.add_message(text, color_attr, context_name="Status")

    def _initialize_connection_handlers(self):
        logger.debug("Initializing connection handlers (CAP, SASL, Registration)...")
        DEFAULT_GLOBAL_DESIRED_CAPS: Set[str] = {
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
        if (
            self.active_server_config
            and self.active_server_config.desired_caps is not None
            and isinstance(self.active_server_config.desired_caps, list)
        ):
            self.desired_caps_config = set(self.active_server_config.desired_caps)
        else:
            self.desired_caps_config = DEFAULT_GLOBAL_DESIRED_CAPS

        self.cap_negotiator = CapNegotiator(
            network_handler=self.network_handler,
            desired_caps=self.desired_caps_config,
            registration_handler=None,
            client_logic_ref=self,
        )
        sasl_pass = (
            self.active_server_config.sasl_password
            if self.active_server_config
            else (self.nickserv_password if self.nickserv_password else None)
        )
        self.sasl_authenticator = SaslAuthenticator(
            network_handler=self.network_handler,
            cap_negotiator=self.cap_negotiator,
            password=sasl_pass,
            client_logic_ref=self,
        )
        reg_initial_nick = self.nick
        reg_username = (
            self.active_server_config.username
            if self.active_server_config
            and self.active_server_config.username is not None
            else reg_initial_nick
        )
        reg_realname = (
            self.active_server_config.realname
            if self.active_server_config
            and self.active_server_config.realname is not None
            else reg_initial_nick
        )

        self.registration_handler = RegistrationHandler(
            network_handler=self.network_handler,
            command_handler=self.command_handler,
            initial_nick=reg_initial_nick,
            username=reg_username,
            realname=reg_realname,
            server_password=self.password,
            nickserv_password=self.nickserv_password,
            initial_channels_to_join=self.initial_channels_list[:],
            cap_negotiator=self.cap_negotiator,
            client_logic_ref=self,
        )
        self.cap_negotiator.registration_handler = self.registration_handler
        if hasattr(self.cap_negotiator, "set_sasl_authenticator"):
            self.cap_negotiator.set_sasl_authenticator(self.sasl_authenticator)
        if hasattr(self.registration_handler, "set_sasl_authenticator"):
            self.registration_handler.set_sasl_authenticator(self.sasl_authenticator)
        logger.debug("Connection handlers initialized.")

    def add_message(
        self,
        text: str,
        color_attr_or_key: Any,
        prefix_time: bool = True,
        context_name: Optional[str] = None,
        source_full_ident: Optional[str] = None,
        is_privmsg_or_notice: bool = False,
    ):
        resolved_color_attr: int
        if isinstance(color_attr_or_key, str):
            resolved_color_attr = self.ui.colors.get(
                color_attr_or_key, self.ui.colors.get("default", 0)
            )
        elif isinstance(color_attr_or_key, int):
            resolved_color_attr = color_attr_or_key
        else:
            logger.warning(
                f"add_message: Unexpected type for color_attr_or_key: {type(color_attr_or_key)}. Using default color."
            )
            resolved_color_attr = self.ui.colors.get("default", 0)

        target_context_name = (
            context_name
            if context_name is not None
            else self.context_manager.active_context_name
        )
        if not target_context_name:
            target_context_name = "Status"

        if (
            is_privmsg_or_notice
            and source_full_ident
            and app_config.is_source_ignored(source_full_ident)
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
            if not self.context_manager.create_context(
                target_context_name,
                context_type=context_type,
                initial_join_status_for_channel=initial_join_status_for_new_channel,
            ):
                status_ctx_for_error = self.context_manager.get_context("Status")
                if not status_ctx_for_error:
                    self.context_manager.create_context("Status", context_type="status")
                self.context_manager.add_message_to_context(
                    "Status",
                    f"[CtxErr for {target_context_name}] {text}",
                    resolved_color_attr,
                )
                self.ui_needs_update.set()
                return

        target_context_obj = self.context_manager.get_context(target_context_name)
        if not target_context_obj:
            logger.critical(
                f"Context {target_context_name} unexpectedly None. Message lost: {text}"
            )
            return

        max_w = self.ui.msg_win_width - 1 if self.ui.msg_win_width > 1 else 80
        timestamp = time.strftime("%H:%M:%S ") if prefix_time else ""
        full_message = (
            f"{timestamp}{text}" if not text.startswith(timestamp.strip()) else text
        )

        lines = []
        current_line = ""
        for word in full_message.split(" "):
            if current_line and (len(current_line) + len(word) + 1 > max_w):
                lines.append(current_line)
                current_line = word
            else:
                current_line += (" " if current_line else "") + word
        if current_line:
            lines.append(current_line)
        if not lines and full_message:
            lines.append(full_message)

        num_lines_added_for_this_message = len(lines)
        for line_part in lines:
            self.context_manager.add_message_to_context(
                target_context_name, line_part, resolved_color_attr, 1
            )

        if target_context_obj.type == "channel":
            channel_logger = self.channel_logger_manager.get_channel_logger(target_context_name)
            if channel_logger:
                channel_logger.info(text)
        elif target_context_obj.name == "Status":
            status_logger = self.channel_logger_manager.get_status_logger()
            if status_logger:
                status_logger.info(text)

        if (
            target_context_name == self.context_manager.active_context_name
            and hasattr(target_context_obj, "scrollback_offset")
            and target_context_obj.scrollback_offset > 0
        ):
            target_context_obj.scrollback_offset += num_lines_added_for_this_message

        # Dispatch the message added event
        if hasattr(self, 'event_manager') and self.event_manager:
            self.event_manager.dispatch_message_added_to_context(
                context_name=target_context_name,
                text=text,
                color_key=color_attr_or_key if isinstance(color_attr_or_key, str) else "system",
                source_full_ident=source_full_ident,
                is_privmsg_or_notice=is_privmsg_or_notice
            )

        self.ui_needs_update.set()

    def handle_server_message(self, line: str):
        if self.show_raw_log_in_ui:
            self._add_status_message(f"S << {line.strip()}")

        parsed_msg = IRCMessage.parse(line)
        if parsed_msg and parsed_msg.command in ("PRIVMSG", "NOTICE"):
            message_content = (
                parsed_msg.trailing if parsed_msg.trailing is not None else ""
            )

            if message_content.startswith("\x01") and message_content.endswith("\x01"):
                ctcp_payload = message_content[1:-1]

                if (
                    ctcp_payload.upper().startswith("DCC ")
                    and hasattr(self, "dcc_manager")
                    and self.dcc_manager
                ):
                    nick_from_parser = (
                        parsed_msg.source_nick
                        if parsed_msg.source_nick
                        else "UnknownNick"
                    )
                    full_userhost_from_parser = (
                        parsed_msg.prefix
                        if parsed_msg.prefix
                        else f"{nick_from_parser}!UnknownUser@UnknownHost"
                    )

                    logger.debug(
                        f"Passing to DCCManager: nick={nick_from_parser}, host={full_userhost_from_parser}, payload={ctcp_payload}"
                    )
                    self.dcc_manager.handle_incoming_dcc_ctcp(
                        nick_from_parser, full_userhost_from_parser, ctcp_payload
                    )
                    return

        irc_protocol.handle_server_message(self, line)

    def send_ctcp_privmsg(self, target: str, ctcp_message: str):
        if not target or not ctcp_message:
            logger.warning("send_ctcp_privmsg: Target or message is empty.")
            return
        payload = ctcp_message.strip("\x01")
        full_ctcp_command = f"\x01{payload}\x01"
        self.network_handler.send_raw(f"PRIVMSG {target} :{full_ctcp_command}")
        logger.debug(f"Sent CTCP PRIVMSG to {target}: {full_ctcp_command}")

    def switch_active_context(self, direction: str):
        context_names = self.context_manager.get_all_context_names()
        if not context_names:
            return

        status_context = "Status"
        dcc_context = "DCC"
        regular_contexts = [
            name for name in context_names if name not in [status_context, dcc_context]
        ]
        regular_contexts.sort(key=lambda x: x.lower())
        sorted_context_names = []
        if status_context in context_names:
            sorted_context_names.append(status_context)
        sorted_context_names.extend(regular_contexts)
        if dcc_context in context_names:
            sorted_context_names.append(dcc_context)

        current_active_name = self.context_manager.active_context_name
        if not current_active_name and sorted_context_names:
            current_active_name = sorted_context_names[0]
        elif not current_active_name:
            return

        try:
            current_idx = sorted_context_names.index(current_active_name)
        except ValueError:
            current_idx = 0
            current_active_name = (
                sorted_context_names[0] if sorted_context_names else ""
            )
        if not current_active_name:
            return

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
                            "error",
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
                            "error",
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
                                "error",
                                context_name=current_active_name,
                            )
                            return

        if new_active_context_name:
            self.context_manager.set_active_context(new_active_context_name)
            self.ui_needs_update.set()

    def switch_active_channel(self, direction: str):
        all_context_names = self.context_manager.get_all_context_names()
        channel_names_only: List[str] = []
        for name in all_context_names:
            context_obj = self.context_manager.get_context(name)
            if context_obj and context_obj.type == "channel":
                channel_names_only.append(name)
        channel_names_only.sort(key=lambda x: x.lower())

        cyclable_contexts = channel_names_only[:]
        if "Status" in all_context_names:
            cyclable_contexts.append("Status")

        if not cyclable_contexts:
            self.add_message(
                "No channels or Status window to switch to.",
                "system",
                context_name=self.context_manager.active_context_name or "Status",
            )
            return

        current_active_name_str: Optional[str] = (
            self.context_manager.active_context_name
        )
        current_idx = -1
        if current_active_name_str:
            try:
                current_idx = cyclable_contexts.index(current_active_name_str)
            except ValueError:
                current_idx = -1

        new_active_channel_name_to_set: Optional[str] = None
        num_cyclable = len(cyclable_contexts)
        if num_cyclable == 0:
            return

        if current_idx == -1:
            new_active_channel_name_to_set = cyclable_contexts[0] # Corrected from cycl_contexts
        elif direction == "next":
            new_idx = (current_idx + 1) % num_cyclable
            new_active_channel_name_to_set = cyclable_contexts[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + num_cyclable) % num_cyclable
            new_active_channel_name_to_set = cyclable_contexts[new_idx]

        if new_active_channel_name_to_set:
            if self.context_manager.set_active_context(new_active_channel_name_to_set):
                logger.debug(
                    f"Switched active channel/status to: {self.context_manager.active_context_name}"
                )
                self.ui_needs_update.set()
            else:
                logger.error(
                    f"Failed to set active channel/status to {new_active_channel_name_to_set}."
                )
                self.add_message(
                    f"Error switching to '{new_active_channel_name_to_set}'.",
                    "error",
                    context_name=current_active_name_str or "Status",
                )

    def is_cap_negotiation_pending(self) -> bool:
        return self.cap_negotiator.is_cap_negotiation_pending()

    def is_sasl_completed(self) -> bool:
        return (
            self.sasl_authenticator.is_completed() if self.sasl_authenticator else True
        )

    def get_enabled_caps(self) -> Set[str]:
        return self.cap_negotiator.get_enabled_caps() if self.cap_negotiator else set()

    def handle_channel_fully_joined(self, channel_name: str):
        logger.info(
            f"[CLIENT_LOGIC_DEBUG] handle_channel_fully_joined called for {channel_name}"
        )
        normalized_channel_name = self.context_manager._normalize_context_name(
            channel_name
        )
        logger.info(f"Channel {normalized_channel_name} reported as fully joined.")
        if hasattr(self, "event_manager") and self.event_manager:
            self.event_manager.dispatch_channel_fully_joined(
                normalized_channel_name, raw_line=""
            )
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
                normalized_initial_channels = {
                    self.context_manager._normalize_context_name(ch)
                    for ch in self.initial_channels_list
                }
                if normalized_channel_name in normalized_initial_channels:
                    logger.info(
                        f"Auto-joined initial channel {normalized_channel_name} is now fully joined. Setting active."
                    )
                    self.context_manager.set_active_context(normalized_channel_name)
                    self.ui_needs_update.set()

    def _execute_python_trigger(
        self, code: str, event_data: Dict[str, Any], trigger_info_for_error: str
    ):
        current_context_name = self.context_manager.active_context_name or "Status"
        try:
            python_trigger_api = PythonTriggerAPI(self)
            execution_globals = {
                "__builtins__": {
                    "print": lambda *args, **kwargs: python_trigger_api.add_message_to_context(
                        current_context_name, " ".join(map(str, args)), "system"
                    ),
                    "eval": eval,
                    "str": str,
                    "int": int,
                    "float": float,
                    "list": list,
                    "dict": dict,
                    "True": True,
                    "False": False,
                    "None": None,
                    "len": len,
                    "isinstance": isinstance,
                    "hasattr": hasattr,
                    "getattr": getattr,
                    "setattr": setattr,
                    "delattr": delattr,
                    "Exception": Exception,
                }
            }
            execution_locals = {
                "client": self,
                "api": python_trigger_api,
                "event_data": event_data,
                "logger": logging.getLogger(
                    f"pyrc.trigger.python_exec.{trigger_info_for_error.replace(' ','_')[:20]}"
                ),
            }
            exec(code, execution_globals, execution_locals)
        except Exception as e:
            error_message = f"Error executing Python trigger ({trigger_info_for_error}): {type(e).__name__}: {e}"
            logger.error(error_message, exc_info=True)
            self._add_status_message(error_message, "error")

    def process_trigger_event(
        self, event_type: str, event_data: Dict[str, Any]
    ) -> Optional[str]:
        if (
            not app_config.ENABLE_TRIGGER_SYSTEM
            or not hasattr(self, "trigger_manager")
            or not self.trigger_manager
        ):
            return None
        logger.debug(
            f"Processing trigger event: Type='{event_type}', DataKeys='{list(event_data.keys())}'"
        )
        result = self.trigger_manager.process_trigger(event_type, event_data)
        if not result:
            logger.debug(f"No trigger matched for event type '{event_type}'.")
            return None

        action_type = result.get("type")
        logger.info(
            f"Trigger matched! Event: '{event_type}', Pattern: '{result.get('pattern', 'N/A')}', ActionType: '{action_type}'"
        )

        if action_type == ActionType.COMMAND:
            action_content = result.get("content")
            logger.info(f"Trigger action is COMMAND: '{action_content}'")
            return action_content
        elif action_type == ActionType.PYTHON:
            code = result.get("code")
            if code:
                trigger_info = (
                    f"Event: {event_type}, Pattern: {result.get('pattern', 'N/A')}"
                )
                logger.info(
                    f"Trigger action is PYTHON. Executing code snippet for trigger: {trigger_info}"
                )
                self._execute_python_trigger(
                    code, result.get("event_data", {}), trigger_info
                )
        return None

    def handle_text_input(self, text: str):
        active_ctx_name = self.context_manager.active_context_name
        if not active_ctx_name:
            self._add_status_message("No active window to send message to.", "error")
            return
        active_ctx = self.context_manager.get_context(active_ctx_name)
        if not active_ctx:
            self._add_status_message(
                f"Error: Active context '{active_ctx_name}' not found.", "error"
            )
            return

        if active_ctx.type == "channel":
            if active_ctx.join_status == ChannelJoinStatus.FULLY_JOINED:
                self.network_handler.send_raw(f"PRIVMSG {active_ctx_name} :{text}")
                if "echo-message" not in self.get_enabled_caps():
                    self.add_message(
                        f"<{self.nick}> {text}",
                        "my_message",
                        context_name=active_ctx_name,
                    )
                elif self.echo_sent_to_status:
                    self.add_message(
                        f"To {active_ctx_name}: <{self.nick}> {text}",
                        "my_message",
                        context_name="Status",
                    )
            else:
                self.add_message(
                    f"Cannot send message: Channel {active_ctx_name} not fully joined (Status: {active_ctx.join_status.name if active_ctx.join_status else 'N/A'}).",
                    "error",
                    context_name=active_ctx_name,
                )
        elif active_ctx.type == "query":
            self.network_handler.send_raw(f"PRIVMSG {active_ctx_name} :{text}")
            if "echo-message" not in self.get_enabled_caps():
                self.add_message(
                    f"<{self.nick}> {text}", "my_message", context_name=active_ctx_name
                )
            elif self.echo_sent_to_status:
                self.add_message(
                    f"To {active_ctx_name}: <{self.nick}> {text}",
                    "my_message",
                    context_name="Status",
                )
        else:
            self._add_status_message(
                f"Cannot send messages to '{active_ctx_name}' (type: {active_ctx.type}). Try a command like /msg.",
                "error",
            )

    def handle_rehash_config(self):
        logger.info("Attempting to reload configuration via /rehash...")
        try:
            app_config.reload_all_config_values()
            self.verify_ssl_cert = app_config.VERIFY_SSL_CERT
            # Update the channel logger manager with new config values
            self.channel_logger_manager.channel_log_enabled = app_config.CHANNEL_LOG_ENABLED
            self.channel_logger_manager.channel_log_level = app_config.LOG_LEVEL
            self.channel_logger_manager.channel_log_max_bytes = app_config.LOG_MAX_BYTES
            self.channel_logger_manager.channel_log_backup_count = app_config.LOG_BACKUP_COUNT

            if hasattr(self.context_manager, "max_history"):
                self.context_manager.max_history = app_config.MAX_HISTORY
            self._add_status_message(
                "Configuration reloaded. Some changes (like main log file settings or server connection details if manually edited in INI) may require a /reconnect or client restart to fully apply."
            )
            logger.info(
                "Configuration successfully reloaded and applied where possible."
            )
            self.ui_needs_update.set()
        except Exception as e:
            logger.error(f"Error during /rehash: {e}", exc_info=True)
            self._add_status_message(f"Error reloading configuration: {e}", "error")
            self.ui_needs_update.set()

    def run_main_loop(self):
        logger.info("Starting main client loop (headless=%s).", self.is_headless)
        try:
            if self.server and self.port is not None:
                logger.info(f"Initializing connection to {self.server}:{self.port}")
                if not self.network_handler:
                    logger.error("Network handler not initialized")
                    return
                self.network_handler.update_connection_params(
                    server=self.server,
                    port=self.port,
                    use_ssl=self.use_ssl,
                    channels_to_join=self.initial_channels_list,
                )
                if not self.network_handler._network_thread:
                    self.network_handler.start()
                    logger.info("Network handler started")

            while not self.should_quit:
                try:
                    if not self.is_headless:
                        self._handle_user_input()
                    self._update_ui()
                    time.sleep(0.01)

                except KeyboardInterrupt:
                    logger.info("Keyboard interrupt received, initiating shutdown...")
                    self.should_quit = True
                    break
                except curses.error as e:
                    logger.error(f"curses error in main loop: {e}")
                    if not self.is_headless:
                        self.ui_needs_update.set()
                except Exception as e:
                    logger.error(f"Error in main loop: {e}", exc_info=True)
                    if not self.is_headless:
                        self.ui_needs_update.set()

        except Exception as e:
            logger.critical(f"Critical error in main client loop: {e}", exc_info=True)
        finally:
            if hasattr(self, "_final_quit_message"):
                quit_message = self._final_quit_message
            else:
                quit_message = "Client shutting down"

            if self.network_handler:
                self.network_handler.disconnect_gracefully(quit_message)
            logger.info("Main client loop ended.")

    def initialize(self) -> bool:
        try:
            self.network_handler = NetworkHandler(self)
            self.script_manager = ScriptManager(self, app_config.BASE_DIR)
            # disabled_scripts is now handled by ScriptManager's __init__ using app_config
            self.script_manager.disabled_scripts = app_config.DISABLED_SCRIPTS # Ensure this is a Set
            self.script_manager.load_scripts()
            if app_config.ENABLE_TRIGGER_SYSTEM:
                self.trigger_manager = TriggerManager(os.path.join(app_config.BASE_DIR, "config"))
                self.trigger_manager.load_triggers()
            else:
                self.trigger_manager = None
            return True
        except Exception as e:
            logger.error(f"Failed to initialize client: {str(e)}")
            return False

    def connect(self, server: str, port: int, use_ssl: bool = False) -> bool:
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
        if self.network_handler:
            self.network_handler.disconnect_gracefully(quit_message)

    def handle_reconnect(self) -> None:
        if self.reconnect_delay < self.max_reconnect_delay:
            self.reconnect_delay *= 2
        logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")

    def reset_reconnect_delay(self) -> None:
        self.reconnect_delay = int(app_config.RECONNECT_INITIAL_DELAY)


    def _reset_state_for_new_connection(self):
        logger.debug("Resetting client state for new server connection.")

        # Preserve Status window messages and scroll offset if possible
        status_context = self.context_manager.get_context("Status")
        current_status_msgs = []
        status_scroll_offset = 0
        if status_context:
            current_status_msgs = list(status_context.messages) # Make a copy
            if hasattr(status_context, "scrollback_offset"):
                status_scroll_offset = status_context.scrollback_offset

        # Clear all existing contexts
        self.context_manager.contexts.clear()

        # Recreate Status window and restore its messages/scroll
        self.context_manager.create_context("Status", context_type="status")
        new_status_context = self.context_manager.get_context("Status")
        if new_status_context:
            for msg_tuple in current_status_msgs:
                # Ensure msg_tuple is valid before trying to access elements
                if isinstance(msg_tuple, tuple) and len(msg_tuple) >= 2:
                    new_status_context.add_message(msg_tuple[0], msg_tuple[1])
                else:
                    logger.warning(f"Skipping invalid message tuple during Status restore: {msg_tuple}")
            if hasattr(new_status_context, "scrollback_offset"):
                new_status_context.scrollback_offset = status_scroll_offset

        # Recreate initial channels (now based on the potentially new server config)
        # self.initial_channels_list should have been updated by /server command before this point
        for ch_name in self.initial_channels_list:
            self.context_manager.create_context(
                ch_name,
                context_type="channel",
                initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN,
            )

        # Set active context: to the first initial channel, or Status if no initial channels
        if self.initial_channels_list:
            # Ensure the first initial channel actually resulted in a created context
            first_initial_channel_normalized = self.context_manager._normalize_context_name(self.initial_channels_list[0])
            if self.context_manager.get_context(first_initial_channel_normalized):
                self.context_manager.set_active_context(first_initial_channel_normalized)
            else:
                self.context_manager.set_active_context("Status") # Fallback
        else:
            self.context_manager.set_active_context("Status")

        # Clear other relevant client state
        self.currently_joined_channels.clear()
        self.last_join_command_target = None
        self.user_modes.clear() # Clear user modes specific to the old server

        # If a /server switch is pending and waiting for disconnect, signal it
        # This is the new part:
        if self._server_switch_disconnect_event and not self._server_switch_disconnect_event.is_set():
            logger.info("Signaling /server command that disconnect is complete via _server_switch_disconnect_event.")
            self._server_switch_disconnect_event.set()
            # The server_command handler will pick up from here.
            # Do not clear _server_switch_target_config_name here, the command handler will use it.

        logger.info(
            f"Client state reset. Active context set to '{self.context_manager.active_context_name}'."
        )
        self.ui_needs_update.set() # Signal UI to refresh with new context layout

    def _handle_user_input_impl(self):
        if self.input_handler and self.ui:
            key_code = self.ui.get_input_char()
            if key_code != curses.ERR:
                self.input_handler.handle_key_press(key_code)
            if self.ui_needs_update.is_set() or key_code != curses.ERR:
                self.ui.refresh_all_windows()
                if self.ui_needs_update.is_set():
                    self.ui_needs_update.clear()

    def _update_ui_impl(self):
        if self.ui_needs_update.is_set():
            if not self.is_headless and self.ui:
                self.ui.refresh_all_windows()
            self.ui_needs_update.clear()
