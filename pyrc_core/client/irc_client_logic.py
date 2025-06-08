# pyrc_core/client/irc_client_logic.py
from __future__ import annotations
import curses
import asyncio
import concurrent.futures # For running blocking calls in a thread pool
from collections import deque
from typing import Optional, Any, List, Set, Dict, Tuple, cast
import logging
import logging.handlers
import os
import platform
from enum import Enum
from dataclasses import asdict # Import asdict
# typing.Optional is already imported by __future__.annotations if Python >= 3.9
# from typing import Optional # Keep for clarity if preferred

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
from pyrc_core.client.connection_orchestrator import ConnectionOrchestrator

logger = logging.getLogger("pyrc.logic")

class DummyUI:
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
    def shutdown(self):
        pass

    async def add_message_to_context(
        self, text: str, color_attr: int, prefix_time: bool, context_name: str
    ):
        """Dummy method for headless UI, does nothing."""
        pass

class IRCClient_Logic:
    def __init__(self, stdscr: Optional[curses.window], args: Any, config: AppConfig):
        # --- Stage 1: Basic Attribute Initialization ---
        self.stdscr = stdscr
        self.is_headless = stdscr is None
        self.args = args
        self.config: AppConfig = config
        self.loop = asyncio.get_event_loop()

        self.should_quit = asyncio.Event() # Use asyncio.Event for graceful shutdown
        self.ui_needs_update = asyncio.Event()
        self._server_switch_disconnect_event: Optional[asyncio.Event] = None
        self._server_switch_target_config_name: Optional[str] = None
        self.echo_sent_to_status = True
        self.show_raw_log_in_ui: bool = False
        self.last_join_command_target: Optional[str] = None
        self.active_list_context_name: Optional[str] = None
        self._final_quit_message: Optional[str] = None
        self.max_reconnect_delay: float = 300.0
        self.last_attempted_nick_change: Optional[str] = None
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

        # --- Stage 2: Initialize All Manager Components ---
        self.state_manager = StateManager()
        self.channel_logger_manager = ChannelLoggerManager(self.config)
        self.context_manager = ContextManager(max_history_per_context=self.config.max_history)

        self.network_handler: NetworkHandler = NetworkHandler(self)

        self.script_manager: ScriptManager = ScriptManager(self, self.config.BASE_DIR, disabled_scripts=self.config.disabled_scripts)
        self.event_manager = EventManager(self, self.script_manager)

        # Initialize DCCManager *before* UIManager
        self.dcc_manager = DCCManager(self, self.event_manager, self.config)

        # Now UIManager can be initialized as it depends on dcc_manager (via MessagePanelRenderer)
        self.ui: UIManager | DummyUI = UIManager(stdscr, self) if not self.is_headless else DummyUI()
        self.input_handler: Optional[InputHandler] = InputHandler(self) if not self.is_headless else None

        self.command_handler = CommandHandler(self)
        self.trigger_manager: Optional[TriggerManager] = TriggerManager(os.path.join(self.config.BASE_DIR, "config")) if self.config.enable_trigger_system else None

        self.cap_negotiator: Optional[CapNegotiator] = None
        self.sasl_authenticator: Optional[SaslAuthenticator] = None
        self.registration_handler: Optional[RegistrationHandler] = None

        self.state_ui_handler = StateChangeUIHandler(self)

        self.connection_orchestrator = ConnectionOrchestrator(self)

        self.script_manager.subscribe_script_to_event(
            "CLIENT_READY", self._handle_client_ready_for_ui_switch, "IRCClient_Logic_Internal_UI_Switch"
        )

    async def run_main_loop(self):
        """Main asyncio loop to handle user input and update the UI."""
        logger.info("Starting main client loop (headless=%s).", self.is_headless)

        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

        try:
            await self._create_initial_state()
            self.connection_orchestrator.initialize_handlers()
            self.script_manager.load_scripts()
            await self._log_startup_status()

            conn_info = self.state_manager.get_connection_info()
            if conn_info and conn_info.auto_connect:
                logger.info(f"Auto-connecting to {conn_info.server}:{conn_info.port}")
                await self._start_connection_if_auto()
                logger.info("Auto-connection initiated.")

            network_task = asyncio.create_task(self.network_handler._network_loop())
            input_task = None
            if not self.is_headless and self.input_handler:
                input_task = asyncio.create_task(self.input_handler.async_input_reader(self._executor))

            while not self.should_quit.is_set():
                try:
                    await self._update_ui()
                    await asyncio.sleep(0.01)

                except asyncio.CancelledError:
                    logger.info("Main loop cancelled.")
                    break
                except curses.error as e:
                    logger.error(f"curses error in main loop: {e}")
                    if not self.is_headless:
                        self.ui_needs_update.set()
                except Exception as e:
                    logger.critical(f"Error in main loop: {e}", exc_info=True)
                    if not self.is_headless:
                        self.ui_needs_update.set()

        except Exception as e:
            logger.critical(f"Critical error in main client loop setup or outer execution: {e}", exc_info=True)
        finally:
            quit_msg = self._final_quit_message or "Client shutting down"
            if self.network_handler:
                await self.network_handler.disconnect_gracefully(quit_msg)

            if not self.is_headless and self.ui and hasattr(self.ui, 'shutdown') and callable(self.ui.shutdown):
                logger.info("Shutting down UI (from main_loop finally).")
                self.ui.shutdown()

            if self.dcc_manager:
                self.dcc_manager.shutdown()

            if self._executor:
                self._executor.shutdown(wait=True)
                logger.info("ThreadPoolExecutor shut down.")

            logger.info("Main client loop ended.")


    @property
    def nick(self) -> Optional[str]:
        info = self.state_manager.get_connection_info()
        return info.nick if info else None

    @property
    def server(self) -> Optional[str]:
        info = self.state_manager.get_connection_info()
        return info.server if info else None

    @property
    def port(self) -> Optional[int]:
        info = self.state_manager.get_connection_info()
        return info.port if info else None

    @property
    def use_ssl(self) -> Optional[bool]:
        info = self.state_manager.get_connection_info()
        return info.ssl if info else None

    @property
    def currently_joined_channels(self) -> Set[str]:
        return self.context_manager.get_all_channels()

    async def _create_initial_state(self):
        """
        Determines the initial connection state from CLI args and AppConfig,
        then populates the StateManager.
        """
        active_config_for_initial_state: Optional[ServerConfig] = None
        default_server_for_nick: Optional[ServerConfig] = None

        if self.config.default_server_config_name:
             default_server_for_nick = self.config.all_server_configs.get(self.config.default_server_config_name)

        if self.args.server:
            port = self.args.port
            ssl = self.args.ssl
            if port is None:
                if ssl is None:
                    ssl = False
                port = app_config.DEFAULT_SSL_PORT if ssl else app_config.DEFAULT_PORT
            elif ssl is None:
                ssl = (port == app_config.DEFAULT_SSL_PORT)

            cli_nick = self.args.nick or (default_server_for_nick.nick if default_server_for_nick else app_config.DEFAULT_NICK)

            active_config_for_initial_state = ServerConfig(
                server_id="CommandLine",
                address=self.args.server,
                port=port,
                ssl=ssl,
                nick=cli_nick,
                username=cli_nick, # Defaulting, __post_init__ will handle if None
                realname=cli_nick, # Defaulting, __post_init__ will handle if None
                channels=self.args.channel or [],
                server_password=self.args.password,
                nickserv_password=self.args.nickserv_password,
                sasl_username=None, # Will be defaulted by ServerConfig post_init if applicable
                sasl_password=None, # Will be defaulted by ServerConfig post_init if applicable
                verify_ssl_cert=True, # Default for CLI
                auto_connect=True, # CLI implies auto-connect
                desired_caps=[] # Default for CLI
            )
        elif self.config.default_server_config_name:
            active_config_for_initial_state = self.config.all_server_configs.get(self.config.default_server_config_name)

        if active_config_for_initial_state:
            server_config_dict = asdict(active_config_for_initial_state)

            # Map ServerConfig fields to ConnectionInfo fields
            conn_info = ConnectionInfo(
                server=server_config_dict["address"],
                port=server_config_dict["port"],
                ssl=server_config_dict["ssl"],
                nick=server_config_dict["nick"],
                username=server_config_dict["username"],
                realname=server_config_dict["realname"],
                server_password=server_config_dict["server_password"],
                nickserv_password=server_config_dict["nickserv_password"],
                sasl_username=server_config_dict["sasl_username"],
                sasl_password=server_config_dict["sasl_password"],
                verify_ssl_cert=server_config_dict["verify_ssl_cert"],
                auto_connect=server_config_dict["auto_connect"],
                initial_channels=server_config_dict["channels"],
                desired_caps=server_config_dict["desired_caps"]
            )
            if not self.state_manager.set_connection_info(conn_info):
                logger.error("Initial state creation failed: ConnectionInfo validation error.")
                config_errors = self.state_manager.get_config_errors()
                error_summary = "; ".join(config_errors) if config_errors else "Unknown validation error."
                await self._add_status_message(f"Initial Configuration Error: {error_summary}", "error")
                current_conn_info = self.state_manager.get_connection_info()
                if current_conn_info:
                    current_conn_info.auto_connect = False
                    self.state_manager.set_connection_info(current_conn_info)
                elif conn_info: # Should be the one that just failed validation
                    conn_info.auto_connect = False # Prevent auto-connect on invalid config
                    # Attempt to set it again, but it might still fail if other issues persist beyond auto_connect
                    self.state_manager.set_connection_info(conn_info)


        self.context_manager.create_context("Status", context_type="status")
        if self.config.dcc_enabled:
            self.context_manager.create_context("DCC", context_type="dcc_transfers")

        if active_config_for_initial_state and active_config_for_initial_state.channels:
            for ch in active_config_for_initial_state.channels:
                self.context_manager.create_context(ch, context_type="channel", initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN)

        self.context_manager.set_active_context("Status")


    async def _handle_client_ready_for_ui_switch(self, event_data: Dict[str, Any]):
        """Handle the CLIENT_READY event and trigger a UI update."""
        logger.debug("CLIENT_READY event received. Checking for auto-joined channel switch.")
        conn_info = self.state_manager.get_connection_info()
        if conn_info and conn_info.initial_channels:
            for ch_name in conn_info.initial_channels:
                normalized_ch_name = self.context_manager._normalize_context_name(ch_name)
                channel_context = self.context_manager.get_context(normalized_ch_name)
                if channel_context and channel_context.join_status == ChannelJoinStatus.FULLY_JOINED:
                    current_active_ctx_name = self.context_manager.active_context_name
                    if not current_active_ctx_name or current_active_ctx_name == "Status":
                        logger.info(f"CLIENT_READY: Auto-joined channel {normalized_ch_name} is fully joined. Setting active context.")
                        self.context_manager.set_active_context(normalized_ch_name)
                        self.ui_needs_update.set()
                        break
                    else:
                        logger.debug(f"CLIENT_READY: Auto-joined channel {normalized_ch_name} is fully joined, but active context is already {current_active_ctx_name}. No switch needed.")
                else:
                    logger.debug(f"CLIENT_READY: Channel {normalized_ch_name} not fully joined yet or context not found.")
        else:
            logger.debug("CLIENT_READY: No initial channels configured for auto-switch.")
        self.ui_needs_update.set()

    async def _update_ui(self):
        """Update the UI if needed."""
        if self.ui and self.ui_needs_update.is_set():
            self.ui.refresh_all_windows()
            self.ui_needs_update.clear()


    async def _start_connection_if_auto(self):
        conn_info = self.state_manager.get_connection_info()
        if conn_info and conn_info.auto_connect:
            await self.connection_orchestrator.establish_connection(conn_info)


    async def _log_startup_status(self):
        await self._add_status_message("PyRC Client starting...")
        conn_info = self.state_manager.get_connection_info()
        if conn_info:
            channels_display = ", ".join(conn_info.initial_channels) if conn_info.initial_channels else "None"
            await self._add_status_message(f"Target: {conn_info.server}:{conn_info.port}, Nick: {conn_info.nick}, Channels: {channels_display}")
        else:
            await self._add_status_message("No default server configured. Use /server or /connect.", "warning")
        logger.info("IRCClient_Logic initialization complete.")


    def _create_script_manager(self):
        """Create and configure the script manager."""
        cli_disabled_scripts = set(self.args.disable_script if hasattr(self.args, "disable_script") and self.args.disable_script else [])
        config_disabled_scripts = self.config.disabled_scripts if self.config.disabled_scripts else set()

        final_disabled_scripts = cli_disabled_scripts.union(config_disabled_scripts)

        return ScriptManager(
            self,
            self.config.BASE_DIR,
            disabled_scripts=final_disabled_scripts
        )

    def _initialize_trigger_manager(self):
        """Initialize the trigger manager if enabled."""
        if not self.config.enable_trigger_system:
            self.trigger_manager = None
            return

        config_dir_triggers = os.path.join(self.config.BASE_DIR, "config")
        if not os.path.exists(config_dir_triggers):
            try:
                os.makedirs(config_dir_triggers, exist_ok=True)
            except OSError as e_mkdir:
                logger.error(f"Could not create config directory for triggers: {e_mkdir}")
                self.trigger_manager = None
                return

        self.trigger_manager = TriggerManager(config_dir_triggers)
        if self.trigger_manager:
            self.trigger_manager.load_triggers()


    async def _add_status_message(self, text: str, color_key: str = "system"):
        if self.ui:
            color_attr = self.ui.colors.get(color_key, self.ui.colors.get("system", 0))
            await self.add_message(text, color_attr, context_name="Status")
        else:
            logger.info(f"[StatusUpdate via Helper - No UI] ColorKey: '{color_key}', Text: {text}")


    async def _configure_from_server_config(self, config_data: ServerConfig, config_name: str) -> bool:
        """
        Initialize connection info from a ServerConfig and update state.
        """
        try:
            # username = config_data.username # Not needed, __post_init__ in ServerConfig and ConnectionInfo handle this
            # realname = config_data.realname # Not needed

            config_data_dict = asdict(config_data)

            conn_info_obj = ConnectionInfo(
                server=config_data_dict["address"],
                port=config_data_dict["port"],
                ssl=config_data_dict["ssl"],
                nick=config_data_dict["nick"],
                username=config_data_dict["username"],
                realname=config_data_dict["realname"],
                server_password=config_data_dict["server_password"],
                nickserv_password=config_data_dict["nickserv_password"],
                sasl_username=config_data_dict["sasl_username"],
                sasl_password=config_data_dict["sasl_password"],
                verify_ssl_cert=config_data_dict["verify_ssl_cert"],
                auto_connect=config_data_dict["auto_connect"],
                initial_channels=config_data_dict["channels"],
                desired_caps=config_data_dict["desired_caps"]
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


    async def handle_server_message(self, line: str):
        if self.show_raw_log_in_ui:
            await self._add_status_message(f"S << {line.strip()}")

        parsed_msg = IRCMessage.parse(line)
        if not parsed_msg:
            logger.error(f"Failed to parse IRC message: {line.strip()}")
            await self._add_status_message(f"[UNPARSED] {line.strip()}", "error")
            return

        if parsed_msg.command in ("PRIVMSG", "NOTICE"):
            message_content = parsed_msg.trailing if parsed_msg.trailing is not None else ""
            if message_content.startswith("\x01") and message_content.endswith("\x01"):
                ctcp_payload = message_content[1:-1]
                if ctcp_payload.upper().startswith("DCC ") and self.dcc_manager:
                    nick_from_parser = parsed_msg.source_nick or "UnknownNick"
                    full_userhost_from_parser = parsed_msg.prefix or f"{nick_from_parser}!UnknownUser@UnknownHost"
                    logger.debug(f"Passing to DCCManager: nick={nick_from_parser}, host={full_userhost_from_parser}, payload={ctcp_payload}")
                    self.dcc_manager.handle_incoming_dcc_ctcp(nick_from_parser, full_userhost_from_parser, ctcp_payload)
                    return

        await irc_protocol.handle_server_message(self, line)


    async def send_ctcp_privmsg(self, target: str, ctcp_message: str):
        if not target or not ctcp_message:
            logger.warning("send_ctcp_privmsg: Target or message is empty.")
            return
        payload = ctcp_message.strip("\x01")
        full_ctcp_command = f"\x01{payload}\x01"
        await self.network_handler.send_raw(f"PRIVMSG {target} :{full_ctcp_command}")
        logger.debug(f"Sent CTCP PRIVMSG to {target}: {full_ctcp_command}")

    async def switch_active_context(self, direction: str):
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
        if dcc_context in context_names and dcc_context not in sorted_context_names : # ensure DCC is added if present
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
            if not sorted_context_names: return
            current_active_name = sorted_context_names[0]

        if not current_active_name: # Should not happen if logic above is correct
            return

        new_active_context_name = None
        num_contexts = len(sorted_context_names)
        if num_contexts == 0: return

        if direction == "next":
            new_idx = (current_idx + 1) % num_contexts
            new_active_context_name = sorted_context_names[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + num_contexts) % num_contexts
            new_active_context_name = sorted_context_names[new_idx]
        else:
            if direction in sorted_context_names:
                new_active_context_name = direction
            else:
                try:
                    num_idx = int(direction) - 1
                    if 0 <= num_idx < num_contexts:
                        new_active_context_name = sorted_context_names[num_idx]
                    else:
                        await self.add_message(
                            f"Invalid window number: {direction}. Max: {num_contexts}",
                            self.ui.colors["error"], context_name=current_active_name,
                        )
                        return
                except ValueError:
                    found_ctx = [name for name in sorted_context_names if direction.lower() in name.lower()]
                    if len(found_ctx) == 1:
                        new_active_context_name = found_ctx[0]
                    elif len(found_ctx) > 1:
                        await self.add_message(
                            f"Ambiguous window name '{direction}'. Matches: {', '.join(sorted(found_ctx))}",
                            self.ui.colors["error"], context_name=current_active_name,
                        )
                        return
                    else:
                        exact_match_case_insensitive = [name for name in sorted_context_names if direction.lower() == name.lower()]
                        if len(exact_match_case_insensitive) == 1:
                             new_active_context_name = exact_match_case_insensitive[0]
                        else:
                            await self.add_message(
                                f"Window '{direction}' not found.",
                                self.ui.colors["error"], context_name=current_active_name,
                            )
                            return
        if new_active_context_name:
            self.context_manager.set_active_context(new_active_context_name)
            self.ui_needs_update.set()


    async def switch_active_channel(self, direction: str):
        all_context_names = self.context_manager.get_all_context_names()
        channel_names_only: List[str] = []
        for name in all_context_names:
            context_obj = self.context_manager.get_context(name)
            if context_obj and context_obj.type == "channel":
                channel_names_only.append(name)
        channel_names_only.sort(key=lambda x: x.lower())

        cyclable_contexts = channel_names_only[:]
        if "Status" in all_context_names:
            if "Status" not in cyclable_contexts: # Ensure Status is only added if not already part of channels (unlikely)
                 cyclable_contexts.append("Status")

        if not cyclable_contexts:
            await self.add_message(
                "No channels or Status window to switch to.",
                self.ui.colors["system"], context_name=self.context_manager.active_context_name or "Status",
            )
            return

        current_active_name_str: Optional[str] = self.context_manager.active_context_name
        current_idx = -1
        if current_active_name_str and current_active_name_str in cyclable_contexts:
            current_idx = cyclable_contexts.index(current_active_name_str)

        new_active_channel_name_to_set: Optional[str] = None
        num_cyclable = len(cyclable_contexts)
        if num_cyclable == 0: return

        if current_idx == -1: # If current active is not in cyclable (e.g. a query), default to first
            new_active_channel_name_to_set = cyclable_contexts[0]
        elif direction == "next":
            new_idx = (current_idx + 1) % num_cyclable
            new_active_channel_name_to_set = cyclable_contexts[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + num_cyclable) % num_cyclable
            new_active_channel_name_to_set = cyclable_contexts[new_idx]

        if new_active_channel_name_to_set:
            if self.context_manager.set_active_context(new_active_channel_name_to_set):
                logger.debug(f"Switched active channel/status to: {self.context_manager.active_context_name}")
                self.ui_needs_update.set()
            else:
                logger.error(f"Failed to set active channel/status to {new_active_channel_name_to_set}.")
                await self.add_message(
                    f"Error switching to '{new_active_channel_name_to_set}'.",
                    self.ui.colors["error"], context_name=current_active_name_str or "Status",
                )


    def is_cap_negotiation_pending(self) -> bool:
        """Check if CAP negotiation is still pending."""
        if self.cap_negotiator is not None:
            return self.cap_negotiator.cap_negotiation_pending
        return False


    def is_sasl_completed(self) -> bool:
        if self.sasl_authenticator is not None:
            sasl = cast(SaslAuthenticator, self.sasl_authenticator)
            return sasl.is_completed()
        return True # If no SASL authenticator, SASL phase is effectively "completed" (as in, not pending)


    def get_enabled_caps(self) -> Set[str]:
        return self.cap_negotiator.get_enabled_caps() if self.cap_negotiator else set()


    async def handle_channel_fully_joined(self, channel_name: str):
        logger.info(f"ClientLogic: handle_channel_fully_joined called for {channel_name}")
        normalized_channel_name = self.context_manager._normalize_context_name(channel_name)

        if hasattr(self, "event_manager") and self.event_manager: # Check for event_manager existence
            await self.event_manager.dispatch_channel_fully_joined(normalized_channel_name, raw_line="") # Added await

        if self.last_join_command_target and \
           self.context_manager._normalize_context_name(self.last_join_command_target) == normalized_channel_name:
            logger.info(f"Setting active context to recently /join-ed channel: {normalized_channel_name}")
            self.context_manager.set_active_context(normalized_channel_name)
            self.last_join_command_target = None
            self.ui_needs_update.set()
        else: # Check if it's an initial channel and current context is Status
            active_ctx = self.context_manager.get_active_context()
            if not active_ctx or active_ctx.name == "Status":
                conn_info = self.state_manager.get_connection_info()
                if conn_info and conn_info.initial_channels:
                    normalized_initial_channels = {self.context_manager._normalize_context_name(ch) for ch in conn_info.initial_channels}
                    if normalized_channel_name in normalized_initial_channels:
                        logger.info(f"Auto-joined initial channel {normalized_channel_name} is now fully joined. Setting active.")
                        self.context_manager.set_active_context(normalized_channel_name)
                        self.ui_needs_update.set()


    async def _execute_python_trigger(
        self, code: str, event_data: Dict[str, Any], trigger_info_for_error: str
    ):
        current_context_name = self.context_manager.active_context_name or "Status"
        try:
            python_trigger_api = PythonTriggerAPI(self, script_name=f"trigger_{trigger_info_for_error[:10]}")

            async def async_add_message_to_context_wrapper(context, text, color_key):
                await python_trigger_api.add_message_to_context(context, text, color_key)

            execution_globals = {
                "__builtins__": {
                    "print": lambda *args, **kwargs: asyncio.create_task(async_add_message_to_context_wrapper(
                        current_context_name, " ".join(map(str, args)), "system"
                    )),
                    "eval": eval, "str": str, "int": int, "float": float, "list": list,
                    "dict": dict, "True": True, "False": False, "None": None, "len": len,
                    "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
                    "setattr": setattr, "delattr": delattr, "Exception": Exception,
                }
            }
            execution_locals = {
                "client": self,
                "api": python_trigger_api,
                "event_data": event_data,
                "logger": logging.getLogger(f"pyrc.trigger.python_exec.{trigger_info_for_error.replace(' ','_')[:20]}")
            }

            if self._executor:
                await asyncio.to_thread(exec, code, execution_globals, execution_locals)
            else:
                logger.error("Executor not available for Python trigger execution.")
                await self._add_status_message("Error: Executor not available for trigger.", "error")

        except Exception as e:
            error_message = f"Error executing Python trigger ({trigger_info_for_error}): {type(e).__name__}: {e}"
            logger.error(error_message, exc_info=True)
            await self._add_status_message(error_message, "error")


    async def process_trigger_event(
        self, event_type: str, event_data: Dict[str, Any]
    ) -> Optional[str]:
        if not self.config.enable_trigger_system or not self.trigger_manager:
            return None

        logger.debug(f"Processing trigger event: Type='{event_type}', DataKeys='{list(event_data.keys())}'")
        result = self.trigger_manager.process_trigger(event_type, event_data)
        if not result:
            logger.debug(f"No trigger matched for event type '{event_type}'.")
            return None

        action_type_enum = result.get("type")

        action_type_name: str
        if action_type_enum is not None and isinstance(action_type_enum, Enum):
            action_type_name = action_type_enum.name
        elif action_type_enum is None:
            action_type_name = "UNKNOWN_ACTION_TYPE_NONE" # Should not happen
            logger.error(f"Trigger result had None for action type. Result: {result}")
            return None
        else: # Defensive: if type is not an Enum instance for some reason
            action_type_name = str(action_type_enum)
            logger.warning(f"Trigger action type is not an Enum instance: {action_type_enum}")


        logger.info(f"Trigger matched! Event: '{event_type}', Pattern: '{result.get('pattern', 'N/A')}', ActionType: '{action_type_name}'")

        if action_type_enum == ActionType.COMMAND:
            action_content = result.get("content")
            logger.info(f"Trigger action is COMMAND: '{action_content}'")
            return action_content
        elif action_type_enum == ActionType.PYTHON:
            code = result.get("code")
            if code:
                trigger_info = f"Event: {event_type}, Pattern: {result.get('pattern', 'N/A')}"
                logger.info(f"Trigger action is PYTHON. Executing code snippet for trigger: {trigger_info}")
                await self._execute_python_trigger(code, result.get("event_data", {}), trigger_info)
        return None


    async def handle_text_input(self, text: str):
        active_ctx_name = self.context_manager.active_context_name
        if not active_ctx_name:
            await self._add_status_message("No active window to send message to.", "error")
            return
        active_ctx = self.context_manager.get_context(active_ctx_name)
        if not active_ctx:
            await self._add_status_message(f"Error: Active context '{active_ctx_name}' not found.", "error")
            return

        if active_ctx.type == "channel":
            if hasattr(active_ctx, 'join_status') and isinstance(active_ctx.join_status, ChannelJoinStatus) and \
               active_ctx.join_status == ChannelJoinStatus.FULLY_JOINED:
                await self.network_handler.send_raw(f"PRIVMSG {active_ctx_name} :{text}")
                if "echo-message" not in self.get_enabled_caps():
                    conn_info = self.state_manager.get_connection_info()
                    current_nick = conn_info.nick if conn_info and hasattr(conn_info, 'nick') else "unknown"
                    await self.add_message(f"<{current_nick}> {text}", self.ui.colors["my_message"], context_name=active_ctx_name)
                elif self.echo_sent_to_status:
                    conn_info = self.state_manager.get_connection_info()
                    current_nick = conn_info.nick if conn_info and hasattr(conn_info, 'nick') else "unknown"
                    await self.add_message(f"To {active_ctx_name}: <{current_nick}> {text}", self.ui.colors["my_message"], context_name="Status")
            else:
                join_status_name = active_ctx.join_status.name if hasattr(active_ctx, 'join_status') and active_ctx.join_status else 'N/A'
                await self.add_message(
                    f"Cannot send message: Channel {active_ctx_name} not fully joined (Status: {join_status_name}).",
                    self.ui.colors["error"], context_name=active_ctx_name,
                )
        elif active_ctx.type == "query":
            await self.network_handler.send_raw(f"PRIVMSG {active_ctx_name} :{text}")
            if "echo-message" not in self.get_enabled_caps():
                conn_info = self.state_manager.get_connection_info()
                current_nick = conn_info.nick if conn_info and hasattr(conn_info, 'nick') else "unknown"
                await self.add_message(f"<{current_nick}> {text}", self.ui.colors["my_message"], context_name=active_ctx_name)
            elif self.echo_sent_to_status:
                conn_info = self.state_manager.get_connection_info()
                current_nick = conn_info.nick if conn_info and hasattr(conn_info, 'nick') else "unknown"
                await self.add_message(f"To {active_ctx_name}: <{current_nick}> {text}", self.ui.colors["my_message"], context_name="Status")
        else:
            await self._add_status_message(
                f"Cannot send messages to '{active_ctx_name}' (type: {active_ctx.type}). Try a command like /msg.",
                "error",
            )


    async def handle_rehash_config(self):
        logger.info("Attempting to reload configuration via /rehash...")
        try:
            self.config = AppConfig(config_file_path=self.config.CONFIG_FILE_PATH) # Re-initialize AppConfig

            self.channel_logger_manager = ChannelLoggerManager(self.config) # Re-initialize with new config
            if self.context_manager: # Check if it exists
                 self.context_manager.max_history = self.config.max_history
            if self.dcc_manager: # Check if it exists
                self.dcc_manager.config = self.config # Update DCCManager's config reference
                self.dcc_manager.dcc_config = self.dcc_manager._load_dcc_config() # Reload DCC specific parts

            if self.script_manager: # Check if it exists
                self.script_manager.disabled_scripts = self.config.disabled_scripts
                # Consider if scripts need full reload: self.script_manager.reload_scripts()

            await self._add_status_message(
                "Configuration reloaded from INI. Some changes may require /reconnect or client restart."
            )
            logger.info("Configuration successfully reloaded from INI.")
            self.ui_needs_update.set()
        except Exception as e:
            logger.error(f"Error during /rehash: {e}", exc_info=True)
            await self._add_status_message(f"Error reloading configuration: {e}", "error")
            self.ui_needs_update.set()


    async def initialize(self) -> bool:
        """
        Initializes or re-initializes components. Less critical now with robust __init__.
        """
        try:
            logger.info("IRCClient_Logic.initialize() called. Most initialization now in __init__.")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize client components (in .initialize()): {str(e)}")
            return False


    async def connect(self, server: str, port: int, use_ssl: bool = False, initial_channels: Optional[List[str]] = None) -> bool:
        """
        Connects to a server. Delegates to ConnectionOrchestrator.
        """
        if not self.network_handler:
            logger.error("Network handler not initialized, cannot connect.")
            return False

        current_nick_from_state = (ci.nick if (ci := self.state_manager.get_connection_info()) else None) or app_config.DEFAULT_NICK

        desired_caps_to_use = []
        if self.config.default_server_config_name: # Check if default_server_config_name exists
            default_conf = self.config.all_server_configs.get(self.config.default_server_config_name)
            if default_conf and default_conf.desired_caps: # Check if default_conf and desired_caps exist
                desired_caps_to_use = default_conf.desired_caps

        # For temporary connection info created from `connect` method arguments
        temp_conn_info = ConnectionInfo(
            server=server,
            port=port,
            ssl=use_ssl,
            nick=current_nick_from_state,
            initial_channels=initial_channels or [],
            desired_caps=desired_caps_to_use
            # Other fields will use their defaults from ConnectionInfo definition
        )

        if not self.state_manager.set_connection_info(temp_conn_info):
            logger.error(f"Failed to set connection info for {server}:{port}. Validation failed.")
            await self._add_status_message(f"Connection config error for {server}:{port}. Check logs.", "error")
            return False

        await self.connection_orchestrator.establish_connection(temp_conn_info)
        return True


    async def disconnect(self, quit_message: str = "Client disconnecting") -> None:
        if self.network_handler:
            await self.network_handler.disconnect_gracefully(quit_message)
        self.should_quit.set()


    async def handle_reconnect(self) -> None:
        logger.info("IRCClient_Logic.handle_reconnect called. Reconnection logic is primarily in NetworkHandler.")
        if self.network_handler:
            self.network_handler.reconnect_delay = self.config.reconnect_initial_delay


    async def reset_reconnect_delay(self) -> None:
        if self.network_handler:
            self.network_handler.reconnect_delay = int(self.config.reconnect_initial_delay)


    async def _handle_user_input_impl(self):
        if self.input_handler and self.ui:
            key_code = await asyncio.to_thread(self.ui.get_input_char)
            if key_code != curses.ERR:
                await self.input_handler.handle_key_press(key_code)


    async def _update_ui_impl(self):
        if self.ui and self.ui_needs_update.is_set():
            if not self.is_headless:
                self.ui.refresh_all_windows()
            self.ui_needs_update.clear()

    async def add_message(
        self,
        text: str,
        color_attr: int,
        prefix_time: bool = True,
        context_name: Optional[str] = None,
        log_level: int = logging.INFO,
        source_full_ident: Optional[str] = None, # Added for ignore list check
        is_privmsg_or_notice: bool = False, # Added to differentiate message types for ignore
    ):
        if not self.ui:
            return

        active_context_name_str = context_name or self.context_manager.active_context_name

        if active_context_name_str is None:
            logger.warning(f"Attempted to add message with no active context and no context_name provided: {text}")
            if self.context_manager.get_context("Status"):
                await self.ui.add_message_to_context(
                    text, color_attr, prefix_time, "Status"
                )
                self.channel_logger_manager.log_message(
                    "Status", text, log_level
                )
                self.ui_needs_update.set()
            else:
                logger.error(
                    f"Could not add message to any context, including Status: {text}"
                )
            return

        current_context = self.context_manager.get_context(active_context_name_str)

        if current_context:
            await self.ui.add_message_to_context(
                text, color_attr, prefix_time, current_context.name
            )
            self.channel_logger_manager.log_message(
                current_context.name, text, log_level
            )
            self.ui_needs_update.set()
        else:
            logger.warning(
                f"Attempted to add message to non-existent context '{active_context_name_str}': {text}"
            )
            if self.context_manager.get_context("Status"): # Fallback to status
                await self.ui.add_message_to_context(
                    text, color_attr, prefix_time, "Status"
                )
                self.channel_logger_manager.log_message("Status", text, log_level)
                self.ui_needs_update.set()
            else:
                logger.error(
                    f"Could not add message to any context, including Status: {text}"
                )
