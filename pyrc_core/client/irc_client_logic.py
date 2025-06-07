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
from typing import Optional

from pyrc_core import app_config
from pyrc_core.app_config import AppConfig, ServerConfig
from pyrc_core.state_manager import StateManager, ConnectionInfo, ConnectionState
from pyrc_core.client.state_change_ui_handler import StateChangeUIHandler
from pyrc_core.logging.channel_logger import ChannelLoggerManager
from pyrc_core.scripting.script_manager import ScriptManager
from pyrc_core.event_manager import EventManager
from pyrc_core.context_manager import ContextManager, ChannelJoinStatus
from pyrc_core.client.ui_manager import UIManager
from pyrc_core.network_handler import NetworkHandler
from pyrc_core.commands.command_handler import CommandHandler
from pyrc_core.client.input_handler import InputHandler
from pyrc_core.features.triggers.trigger_manager import TriggerManager, ActionType
from pyrc_core.irc import irc_protocol
from pyrc_core.irc.irc_message import IRCMessage
from pyrc_core.irc.cap_negotiator import CapNegotiator
from pyrc_core.irc.sasl_authenticator import SaslAuthenticator
from pyrc_core.irc.registration_handler import RegistrationHandler
from pyrc_core.scripting.python_trigger_api import PythonTriggerAPI
from pyrc_core.dcc.dcc_manager import DCCManager

logger = logging.getLogger("pyrc.logic")

class DummyUI:
    # ... (DummyUI class remains unchanged) ...
    def __init__(self):
        self.colors = {"default": 0, "system": 0, "join_part": 0, "nick_change": 0, "my_message": 0, "other_message": 0, "highlight": 0, "error": 0, "status_bar": 0, "sidebar_header": 0, "sidebar_item": 0, "sidebar_user": 0, "input": 0, "pm": 0, "user_prefix": 0, "warning": 0, "info": 0, "debug": 0, "timestamp": 0, "nick": 0, "channel": 0, "query": 0, "status": 0, "list": 0, "list_selected": 0, "list_header": 0, "list_footer": 0, "list_highlight": 0, "list_selected_highlight": 0, "list_selected_header": 0, "list_selected_footer": 0, "list_selected_highlight_header": 0, "list_selected_highlight_footer": 0}
        self.split_mode_active = False
        self.active_split_pane = "top"
        self.top_pane_context_name = ""
        self.bottom_pane_context_name = ""
        self.msg_win_width = 80
        self.msg_win_height = 24
    def refresh_all_windows(self): pass
    def scroll_messages(self, direction: str, lines: int = 1): pass
    def get_input_char(self) -> int: return curses.ERR if curses else -1
    def setup_layout(self): pass
    def scroll_user_list(self, direction: str, lines_arg: int = 1): pass
    def _calculate_available_lines_for_user_list(self) -> int: return 0

class IRCClient_Logic:
    def __init__(self, stdscr: Optional[curses.window], args: Any, config: AppConfig):
        # --- Stage 1: Basic Attribute Initialization ---
        self.stdscr = stdscr
        self.is_headless = stdscr is None
        self.args = args
        self.config = config
        self.should_quit = False
        self.ui_needs_update = threading.Event()
        self._server_switch_disconnect_event: Optional[threading.Event] = None
        self._server_switch_target_config_name: Optional[str] = None
        self.echo_sent_to_status: bool = True
        self.show_raw_log_in_ui: bool = False
        self.last_join_command_target: Optional[str] = None
        self.active_list_context_name: Optional[str] = None
        self._final_quit_message: Optional[str] = None
        self.max_reconnect_delay: float = 300.0  # 5 minutes

        # --- Stage 2: Initialize All Manager Components ---
        self.state_manager = StateManager()
        self.channel_logger_manager = ChannelLoggerManager(self.config)
        self.context_manager = ContextManager(max_history_per_context=self.config.max_history)
        self.ui = UIManager(stdscr, self) if not self.is_headless else DummyUI()
        self.input_handler = InputHandler(self) if not self.is_headless else None
        self.network_handler = NetworkHandler(self)
        self.script_manager = ScriptManager(self, self.config.BASE_DIR, disabled_scripts=self.config.disabled_scripts)
        self.event_manager = EventManager(self, self.script_manager)
        self.dcc_manager = DCCManager(self, self.event_manager, self.config)
        self.command_handler = CommandHandler(self)
        self.trigger_manager = TriggerManager(os.path.join(self.config.BASE_DIR, "config")) if self.config.enable_trigger_system else None
        self.cap_negotiator: Optional[CapNegotiator] = None
        self.state_ui_handler = StateChangeUIHandler(self)

        # Register event handler for CLIENT_READY to ensure UI switches to joined channel
        # This is registered with the script_manager as it handles all event subscriptions.
        self.script_manager.subscribe_script_to_event(
            "CLIENT_READY", self._handle_client_ready_for_ui_switch, "IRCClient_Logic_Internal_UI_Switch"
        )

        # --- Stage 3: Configure State and Handlers ---
        self._create_initial_state()
        self._initialize_connection_handlers()

        # --- Stage 4: Load Scripts and Start Network ---
        self.script_manager.load_scripts()
        self._start_connection_if_auto()

        # --- Stage 5: Final UI Messages ---
        self._log_startup_status()

    @property
    def nick(self) -> Optional[str]:
        info = self.state_manager.get_connection_info()
        return info.nick if info else None

    @property
    def server(self) -> Optional[str]:
        info = self.state_manager.get_connection_info()
        return info.server if info else None

    def _create_initial_state(self):
        """
        Determines the initial connection state from CLI args and AppConfig,
        then populates the StateManager.
        """
        active_config: Optional[ServerConfig] = None

        # CLI arguments take highest precedence
        if self.args.server:
            port = self.args.port
            ssl = self.args.ssl
            if port is None:
                if ssl is None:
                    ssl = False
                port = app_config.DEFAULT_SSL_PORT if ssl else app_config.DEFAULT_PORT
            elif ssl is None:
                ssl = (port == app_config.DEFAULT_SSL_PORT)

            default_nick = app_config.DEFAULT_NICK
            if self.config.default_server_config_name:
                default_server = self.config.all_server_configs.get(self.config.default_server_config_name)
                if default_server:
                    default_nick = default_server.nick

            active_config = ServerConfig(
                server_id="CommandLine",
                address=self.args.server,
                port=port,
                ssl=ssl,
                nick=self.args.nick or default_nick,
                channels=self.args.channel or [],
                server_password=self.args.password,
                nickserv_password=self.args.nickserv_password,
                auto_connect=True
            )
        # If no CLI args, use the default from the config file
        elif self.config.default_server_config_name:
            active_config = self.config.all_server_configs.get(self.config.default_server_config_name)

        if active_config:
            conn_info = ConnectionInfo(
                server=active_config.address,
                port=active_config.port,
                ssl=active_config.ssl,
                nick=active_config.nick,
                username=active_config.username,
                realname=active_config.realname,
                server_password=active_config.server_password,
                nickserv_password=active_config.nickserv_password,
                sasl_username=active_config.sasl_username,
                sasl_password=active_config.sasl_password,
                verify_ssl_cert=active_config.verify_ssl_cert,
                auto_connect=active_config.auto_connect,
                initial_channels=active_config.channels,
                desired_caps=active_config.desired_caps
            )
            if not self.state_manager.set_connection_info(conn_info):
                logger.error("Initial state creation failed: ConnectionInfo validation error.")
                config_errors = self.state_manager.get_config_errors()
                error_summary = "; ".join(config_errors) if config_errors else "Unknown validation error."
                self._add_status_message(f"Initial Configuration Error: {error_summary}", "error")
                conn_info.auto_connect = False
                if self.state_manager.get_connection_info():
                    updated_conn_info = self.state_manager.get_connection_info()
                    if updated_conn_info:
                        updated_conn_info.auto_connect = False
                        self.state_manager.set("connection_info", updated_conn_info)

        # --- START OF FIX ---
        # Create core contexts first.
        self.context_manager.create_context("Status", context_type="status")
        if self.config.dcc_enabled:
            self.context_manager.create_context("DCC", context_type="dcc_transfers")

        # Create contexts for initial channels but DO NOT set them as active.
        if active_config and active_config.channels:
            for ch in active_config.channels:
                self.context_manager.create_context(ch, context_type="channel", initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN)

        # ALWAYS set "Status" as the initial active context. The logic in
        # handle_channel_fully_joined will handle switching to a channel
        # upon a successful join.
        self.context_manager.set_active_context("Status")
        # --- END OF FIX ---

    def _handle_user_input(self):
        """Handle user input from the UI."""
        if self.input_handler and not self.is_headless:
            key = self.ui.get_input_char()
            if key != -1:  # -1 indicates no input
                self.input_handler.handle_key_press(key)

    def _update_ui(self):
        """Update the UI if needed."""
        if self.ui_needs_update.is_set():
            self.ui.refresh_all_windows()
            self.ui_needs_update.clear()


    def _start_connection_if_auto(self):
        conn_info = self.state_manager.get_connection_info()
        if conn_info and conn_info.auto_connect:
            self.network_handler.update_connection_params(
                server=conn_info.server, port=conn_info.port, use_ssl=conn_info.ssl
            )

    def _log_startup_status(self):
        self._add_status_message("PyRC Client starting...")
        conn_info = self.state_manager.get_connection_info()
        if conn_info:
            channels_display = ", ".join(conn_info.initial_channels) if conn_info.initial_channels else "None"
            self._add_status_message(f"Target: {conn_info.server}:{conn_info.port}, Nick: {conn_info.nick}, Channels: {channels_display}")
        else:
            self._add_status_message("No default server configured. Use /server or /connect.", "warning")
        logger.info("IRCClient_Logic initialization complete.")


    def _create_script_manager(self):
        """Create and configure the script manager."""
        cli_disabled = (
            set(self.args.disable_script)
            if hasattr(self.args, "disable_script") and self.args.disable_script
            else set()
        )
        config_disabled = self.config.disabled_scripts
        return ScriptManager(
            self,
            self.config.BASE_DIR,
            disabled_scripts=cli_disabled.union(config_disabled)
        )

    def _initialize_trigger_manager(self):
        """Initialize the trigger manager if enabled."""
        config_dir_triggers = os.path.join(self.config.BASE_DIR, "config")
        if not os.path.exists(config_dir_triggers):
            try:
                os.makedirs(config_dir_triggers, exist_ok=True)
            except OSError as e_mkdir:
                logger.error(f"Could not create config directory for triggers: {e_mkdir}")
                self.trigger_manager = None
                return

        self.trigger_manager = TriggerManager(config_dir_triggers)
        self.trigger_manager.load_triggers()

    def _add_status_message(self, text: str, color_key: str = "system"):
        color_attr = self.ui.colors.get(color_key, self.ui.colors.get("system", 0))
        logger.info(f"[StatusUpdate via Helper] ColorKey: '{color_key}', Text: {text}")
        self.add_message(text, color_attr, context_name="Status")

    def _configure_from_server_config(self, config_data: ServerConfig, config_name: str) -> bool:
        """
        Initialize connection info from a ServerConfig and update state.
        """
        try:
            conn_info_obj = ConnectionInfo(
                server=config_data.address,
                port=config_data.port,
                ssl=config_data.ssl,
                nick=config_data.nick,
                username=config_data.username or config_data.nick,
                realname=config_data.realname or config_data.nick,
                server_password=config_data.server_password,
                nickserv_password=config_data.nickserv_password,
                sasl_username=config_data.sasl_username,
                sasl_password=config_data.sasl_password,
                verify_ssl_cert=config_data.verify_ssl_cert,
                auto_connect=config_data.auto_connect,
                initial_channels=config_data.channels or [],
                desired_caps=config_data.desired_caps or []
            )

            if not self.state_manager.set_connection_info(conn_info_obj):
                logger.error(f"Configuration for server '{config_name}' failed validation.")
                return False

            logger.info(f"Successfully validated and set server config: {config_name} in StateManager.")
            return True

        except Exception as e:
            logger.error(f"Error configuring from server config {config_name}: {str(e)}", exc_info=True)
            self.state_manager.set_connection_state(ConnectionState.CONFIG_ERROR, f"Internal error processing config {config_name}")
            return False

    def _initialize_connection_handlers(self):
        logger.debug("Initializing connection handlers (CAP, SASL, Registration)...")
        conn_info = self.state_manager.get_connection_info()
        if not conn_info:
            logger.error("Cannot initialize connection handlers - no connection info")
            return

        self.cap_negotiator = CapNegotiator(
            network_handler=self.network_handler,
            desired_caps=set(conn_info.desired_caps),
            registration_handler=None,
            client_logic_ref=self,
        )

        self.sasl_authenticator = SaslAuthenticator(
            network_handler=self.network_handler,
            cap_negotiator=self.cap_negotiator,
            password=conn_info.sasl_password or conn_info.nickserv_password,
            client_logic_ref=self,
        )

        conn_info = self.state_manager.get_connection_info()
        if conn_info:
            self.registration_handler = RegistrationHandler(
                network_handler=self.network_handler,
                command_handler=self.command_handler,
                state_manager=self.state_manager,
                cap_negotiator=self.cap_negotiator,
                client_logic_ref=self,
            )
        else:
            logger.error("Cannot initialize registration handler - no connection info")
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
            and self.config.is_source_ignored(source_full_ident)
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
        """Check if CAP negotiation is still pending."""
        # --- MODIFICATION START ---
        if self.cap_negotiator is not None:
            return self.cap_negotiator.cap_negotiation_pending
        else:
            return False
        # --- MODIFICATION END ---

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
            # This block handles auto-joined channels
            active_ctx = self.context_manager.get_active_context()
            if not active_ctx or active_ctx.name == "Status":
                conn_info = self.state_manager.get_connection_info()
                normalized_initial_channels = {
                    self.context_manager._normalize_context_name(ch)
                    for ch in (conn_info.initial_channels if conn_info else [])
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
            not self.config.enable_trigger_system
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
                    conn_info = self.state_manager.get_connection_info()
                    current_nick = conn_info.nick if conn_info and hasattr(conn_info, 'nick') else "unknown"
                    self.add_message(
                        f"<{current_nick}> {text}",
                        "my_message",
                        context_name=active_ctx_name,
                    )
                elif self.echo_sent_to_status:
                    conn_info = self.state_manager.get_connection_info()
                    current_nick = conn_info.nick if conn_info and hasattr(conn_info, 'nick') else "unknown"
                    self.add_message(
                        f"To {active_ctx_name}: <{current_nick}> {text}",
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
                conn_info = self.state_manager.get_connection_info()
                current_nick = conn_info.nick if conn_info and hasattr(conn_info, 'nick') else "unknown"
                self.add_message(
                    f"<{current_nick}> {text}",
                    "my_message",
                    context_name=active_ctx_name
                )
            elif self.echo_sent_to_status:
                conn_info = self.state_manager.get_connection_info()
                current_nick = conn_info.nick if conn_info and hasattr(conn_info, 'nick') else "unknown"
                self.add_message(
                    f"To {active_ctx_name}: <{current_nick}> {text}",
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
            self.config._load_all_settings()
            self.config._load_server_configurations()
            self.config._load_ignore_list()
            # Update the channel logger manager with new config values
            self.channel_logger_manager.channel_log_enabled = self.config.channel_log_enabled
            self.channel_logger_manager.channel_log_level = self.config.log_level_str
            self.channel_logger_manager.channel_log_max_bytes = self.config.log_max_bytes
            self.channel_logger_manager.channel_log_backup_count = self.config.log_backup_count

            if hasattr(self.context_manager, "max_history"):
                self.context_manager.max_history = self.config.max_history
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
            conn_info = self.state_manager.get_connection_info()
            if conn_info and conn_info.server and conn_info.port is not None:
                logger.info(f"Initializing connection to {conn_info.server}:{conn_info.port}")
                if not self.network_handler:
                    logger.error("Network handler not initialized")
                    return
                self.network_handler.update_connection_params(
                    server=conn_info.server,
                    port=conn_info.port,
                    use_ssl=conn_info.ssl,
                    channels_to_join=conn_info.initial_channels,
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
        """
        Initializes components that might need re-initialization or
        are part of a deferred setup.
        """
        try:
            # Re-initialize script manager if needed, passing the config
            self.script_manager = ScriptManager(self, self.config.BASE_DIR, disabled_scripts=self.config.disabled_scripts)
            self.script_manager.load_scripts()

            # Re-initialize trigger manager if enabled, passing the config
            if self.config.enable_trigger_system:
                self.trigger_manager = TriggerManager(os.path.join(self.config.BASE_DIR, "config"))
                self.trigger_manager.load_triggers()
            else:
                self.trigger_manager = None
            return True
        except Exception as e:
            logger.error(f"Failed to initialize client components: {str(e)}")
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
        self.reconnect_delay = int(self.config.reconnect_initial_delay)


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
        conn_info = self.state_manager.get_connection_info()
        if conn_info:
            for ch_name in conn_info.initial_channels:
                self.context_manager.create_context(
                    ch_name,
                    context_type="channel",
                    initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN,
                )

        # Set active context: to the first initial channel, or Status if no initial channels
        conn_info = self.state_manager.get_connection_info()
        if conn_info and conn_info.initial_channels:
            # Ensure the first initial channel actually resulted in a created context
            first_initial_channel_normalized = self.context_manager._normalize_context_name(conn_info.initial_channels[0])
            if self.context_manager.get_context(first_initial_channel_normalized):
                self.context_manager.set_active_context(first_initial_channel_normalized)
            else:
                self.context_manager.set_active_context("Status") # Fallback
        else:
            self.context_manager.set_active_context("Status")

        # Clear other relevant client state
        conn_info = self.state_manager.get_connection_info()
        if conn_info:
            conn_info.currently_joined_channels.clear()
            self.state_manager.set_connection_info(conn_info)
        self.last_join_command_target = None
        conn_info = self.state_manager.get_connection_info()
        if conn_info:
            conn_info.user_modes.clear()
            self.state_manager.set_connection_info(conn_info)

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

    def _handle_client_ready_for_ui_switch(self, event_data: Dict[str, Any]):
        """
        Handler for CLIENT_READY event to ensure UI switches to the first
        auto-joined channel if applicable.
        """
        logger.debug("CLIENT_READY event received. Checking for auto-joined channel switch.")

        # Ensure client_logic_ref is available in event_data, though it should be self here.
        # This handler is part of IRCClient_Logic, so 'self' is the client_logic_ref.

        conn_info = self.state_manager.get_connection_info()
        if conn_info and conn_info.initial_channels:
            for ch_name in conn_info.initial_channels:
                normalized_ch_name = self.context_manager._normalize_context_name(ch_name)
                channel_context = self.context_manager.get_context(normalized_ch_name)

                # Only switch if the channel is fully joined and we are currently in Status
                if channel_context and channel_context.join_status == ChannelJoinStatus.FULLY_JOINED:
                    current_active_ctx_name = self.context_manager.active_context_name
                    if not current_active_ctx_name or current_active_ctx_name == "Status":
                        logger.info(f"CLIENT_READY: Auto-joined channel {normalized_ch_name} is fully joined. Setting active context.")
                        self.context_manager.set_active_context(normalized_ch_name)
                        self.ui_needs_update.set()
                        break # Only switch to the first one
                    else:
                        logger.debug(f"CLIENT_READY: Auto-joined channel {normalized_ch_name} is fully joined, but active context is already {current_active_ctx_name}. No switch needed.")
                else:
                    logger.debug(f"CLIENT_READY: Channel {normalized_ch_name} not fully joined yet or context not found.")
        else:
            logger.debug("CLIENT_READY: No initial channels configured for auto-switch.")
