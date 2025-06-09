# pyrc_core/client/irc_client_logic.py
from __future__ import annotations
from typing import TYPE_CHECKING
import curses
import asyncio
import concurrent.futures  # For running blocking calls in a thread pool
from collections import deque
from typing import Optional, Any, List, Set, Dict, Tuple, cast
import logging
import logging.handlers
import os
import platform
from enum import Enum
from dataclasses import asdict  # Import asdict
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
        self.colors = {"default": 0, "system": 0, "join_part": 0, "nick_change": 0, "my_message": 0, "other_message": 0, "highlight": 0, "error": 0, "status_bar": 0, "sidebar_header": 0, "sidebar_item": 0, "sidebar_user": 0, "input": 0, "pm": 0, "user_prefix": 0, "warning": 0, "info": 0, "debug": 0, "timestamp": 0, "nick": 0, "channel": 0, "query": 0, "status": 0, "list": 0, "list_selected": 0, "list_header": 0, "list_footer": 0, "list_highlight": 0, "list_selected_highlight": 0, "list_selected_header": 0, "list_selected_highlight_footer": 0}
        self.split_mode_active = False
        self.active_split_pane = "top"
        self.top_pane_context_name = ""
        self.bottom_pane_context_name = ""
        self.msg_win_width = 80
        self.msg_win_height = 24

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

        self.should_quit = asyncio.Event()  # Use asyncio.Event for graceful shutdown
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
        self.script_manager.subscribe_script_to_event(
            "RAW_SERVER_MESSAGE", self.handle_raw_server_message, "IRCClient_Logic_Internal_Server_Message"
        )

    def process_trigger_event(self, event_type: str, event_data: Dict[str, Any]):
        """Process an event through the trigger system if enabled."""
        if self.trigger_manager:
            self.trigger_manager.process_trigger(event_type, event_data)
        else:
            logger.debug(f"Trigger system not enabled, skipping event: {event_type}")

    async def run_main_loop(self):
        """Main asyncio loop to handle user input and update the UI."""
        logger.info("Starting main client loop (headless=%s).", self.is_headless)

        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

        network_task = None
        input_task = None
        tasks_to_await_on_shutdown = set()  # To hold tasks that need graceful shutdown

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

            # Start tasks
            network_task = asyncio.create_task(self.network_handler.network_loop())
            tasks_to_await_on_shutdown.add(network_task)

            if not self.is_headless and self.input_handler:
                input_task = asyncio.create_task(self.input_handler.async_input_reader(self._executor))
                tasks_to_await_on_shutdown.add(input_task)

            while not self.should_quit.is_set():
                try:
                    await self._update_ui()
                    await asyncio.sleep(0.01)  # Small sleep to yield control

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
            logger.info("Main client loop finally block executing.")
            # Signal all tasks to stop
            self.should_quit.set()

            # Attempt graceful disconnect from IRC server
            quit_msg = self._final_quit_message or "Client shutting down"
            if self.network_handler:
                logger.info(f"Attempting graceful network disconnect with message: '{quit_msg}'")
                await self.network_handler.disconnect_gracefully(quit_msg)
            else:
                logger.warning("NetworkHandler not available during shutdown.")

            # Cancel and await remaining tasks to ensure they clean up
            async def cancel_and_wait(task: asyncio.Task, name: str):
                try:
                    if not task.done():
                        logger.info(f"Cancelling task: {name}")
                        task.cancel()
                        await task
                except asyncio.CancelledError:
                    logger.info(f"Task cancelled: {name}")
                except Exception as e:
                    logger.error(f"Error awaiting cancelled task {name}: {e}", exc_info=True)

            if network_task:
                await cancel_and_wait(network_task, "network_task")
            if input_task:
                await cancel_and_wait(input_task, "input_task")

            # Shutdown UI if active
            if not self.is_headless and self.ui and hasattr(self.ui, 'shutdown') and callable(self.ui.shutdown):
                logger.info("Shutting down UI (from main_loop finally).")
                self.ui.shutdown()

            # Shutdown DCC manager
            if self.dcc_manager:
                self.dcc_manager.shutdown()

            # Shutdown thread pool executor
            if self._executor:
                logger.info("Shutting down ThreadPoolExecutor...")
                self._executor.shutdown(wait=True, cancel_futures=True)
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
    def use_ssl(self) -> Optional[str]:
        info = self.state_manager.get_connection_info()
        return str(info.ssl) if info else None

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
                username=cli_nick,  # Defaulting, __post_init__ will handle if None
                realname=cli_nick,  # Defaulting, __post_init__ will handle if None
                channels=self.args.channel or [],
                server_password=self.args.password,
                nickserv_password=self.args.nickserv_password,
                sasl_username=None,  # Will be defaulted by ServerConfig post_init if applicable
                sasl_password=None,  # Will be defaulted by ServerConfig post_init if applicable
                verify_ssl_cert=self.args.verify_ssl_cert if self.args.verify_ssl_cert is not None else True,  # Use CLI arg or default to True
                auto_connect=True,  # CLI implies auto-connect
                desired_caps=[]  # Default for CLI
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
                await self.add_status_message(f"Initial Configuration Error: {error_summary}", "error")
                current_conn_info = self.state_manager.get_connection_info()
                if current_conn_info:
                    current_conn_info.auto_connect = False
                    self.state_manager.set_connection_info(current_conn_info)
                elif conn_info:  # Should be the one that just failed validation
                    conn_info.auto_connect = False  # Prevent auto-connect on invalid config
                    # Attempt to set it again, but it might still fail if other issues persist beyond auto_connect
                    self.state_manager.set_connection_info(conn_info)

        self.context_manager.create_context("Status", context_type="status")
        if TYPE_CHECKING:
            if self.config.dcc.enabled:
                self.context_manager.create_context("DCC", context_type="dcc_transfers")
        else:
            if self.config.dcc.enabled:
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
        if conn_info and conn_info.auto_connect and (not self.network_handler._network_task or self.network_handler._network_task.done()):
            if conn_info:
                await self.connection_orchestrator.establish_connection(conn_info)
                if self.cap_negotiator:
                    await self.cap_negotiator.start_negotiation()

    async def _log_startup_status(self):
        await self.add_status_message("PyRC Client starting...")
        conn_info = self.state_manager.get_connection_info()
        if conn_info and conn_info.server and conn_info.port:
            channels_display = ", ".join(conn_info.initial_channels) if conn_info.initial_channels else "None"
            await self.add_status_message(f"Target: {conn_info.server}:{conn_info.port}, Nick: {conn_info.nick}, Channels: {channels_display}")
        else:
            await self.add_status_message("No default server configured. Use /server or /connect.", "warning")
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

    async def add_message(self, text: str, color_attr: int, context_name: str, prefix_time: bool = False, **kwargs):
        """Add a message to a specific context, ignoring extra keyword arguments"""
        if self.ui:
            await self.ui.add_message_to_context(text, color_attr, prefix_time, context_name)
        else:
            logger.info(f"[Message to {context_name}] {text}")

    async def add_status_message(self, text: str, color_key: str = "system"):
        """Add a status message to the Status context"""
        color_attr = self.ui.colors.get(color_key, self.ui.colors.get("system", 0)) if self.ui else 0
        await self.add_message(text, color_attr, "Status", prefix_time=False)

    async def _configure_from_server_config(self, config_data: ServerConfig, config_name: str) -> bool:
        """
        Initialize connection info from a ServerConfig and update state.
        """
        try:
            # username = config_data.username # Not needed, __post_init__ in ServerConfig and ConnectionInfo handle this
            # realname = config_data.realname # Not needed

            conn_info_obj = ConnectionInfo(
                server=config_data.address,
                port=config_data.port,
                ssl=config_data.ssl,
                nick=config_data.nick,
                username=config_data.username,
                realname=config_data.realname,
                server_password=config_data.server_password,
                nickserv_password=config_data.nickserv_password,
                sasl_username=config_data.sasl_username,
                sasl_password=config_data.sasl_password,
                verify_ssl_cert=config_data.verify_ssl_cert,
                auto_connect=config_data.auto_connect,
                initial_channels=config_data.channels,
                desired_caps=config_data.desired_caps
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

    async def handle_raw_server_message(self, event_data: Dict[str, Any]):
        """Handles the RAW_SERVER_MESSAGE event."""
        client = event_data.get("client")
        line = event_data.get("line")

        if client is None:
            logger.warning("RAW_SERVER_MESSAGE: Client is None. Skipping message processing.")
            return

        if line is None:
            logger.warning("RAW_SERVER_MESSAGE: Line is None. Skipping message processing.")
            return

        await irc_protocol.handle_server_message(client, line)

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
        if dcc_context in context_names and dcc_context not in sorted_context_names:  # ensure DCC is added if present
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
            if not sorted_context_names:
                return
            current_active_name = sorted_context_names[0]

        if not current_active_name:  # Should not happen if logic above is correct
            return

        new_active_context_name = None
        num_contexts = len(sorted_context_names)
        if num_contexts == 0:
            return

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
                except ValueError:
                    found_ctx = [name for name in sorted_context_names if direction.lower() in name.lower()]
                    if len(found_ctx) == 1:
                        new_active_context_name = found_ctx[0]
                    elif len(found_ctx) > 1:
                        await self.add_status_message(
                            f"Ambiguous window name '{direction}'. Matches: {', '.join(sorted(found_ctx))}",
                            "error",
                        )
                        return
                    else:
                        exact_match_case_insensitive = [name for name in sorted_context_names if direction.lower() == name.lower()]
                        if len(exact_match_case_insensitive) == 1:
                            new_active_context_name = exact_match_case_insensitive[0]
                        else:
                            await self.add_status_message(
                                f"Window '{direction}' not found.",
                                "error",
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
            if "Status" not in cyclable_contexts:  # Ensure Status is only added if not already part of channels (unlikely)
                cyclable_contexts.append("Status")

        if not cyclable_contexts:
            await self.add_status_message(
                "No channels or Status window to switch to.",
                "system",
            )
            return

        current_active_name_str: Optional[str] = self.context_manager.active_context_name
        current_idx = -1
        if current_active_name_str and current_active_name_str in cyclable_contexts:
            current_idx = cyclable_contexts.index(current_active_name_str)

        new_active_channel_name_to_set: Optional[str] = None
        num_cyclable = len(cyclable_contexts)
        if num_cyclable == 0:
            return

        if current_idx == -1:  # If current active is not in cyclable (e.g. a query), default to first
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
                await self.add_status_message(
                    f"Error switching to '{new_active_channel_name_to_set}'.",
                    "error",
                )

    def is_cap_negotiation_pending(self) -> bool:
        """Check if CAP negotiation is still pending."""
        return False
