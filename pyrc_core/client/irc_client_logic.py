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
import time # Import time
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
        self.shutdown_complete_event = asyncio.Event() # Event to signal full shutdown completion
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
        # self._shutdown_initiated = False # Flag removed, shutdown logic consolidated in run_main_loop's finally

        # To store references to tasks created in run_main_loop for graceful shutdown
        self._network_task_ref: Optional[asyncio.Task] = None
        self._input_reader_task_ref: Optional[asyncio.Task] = None
        self._input_processor_task_ref: Optional[asyncio.Task] = None

        self.pending_initial_joins: Set[str] = set()
        self.all_initial_joins_processed = asyncio.Event()
        self._switched_to_initial_channel = False # Flag to track if we've switched to the first successfully auto-joined channel


        # --- Stage 2: Initialize All Manager Components ---
        self.state_manager = StateManager()

        # Debug: Verify StateManager methods exist immediately after instantiation
        logger = logging.getLogger("pyrc.debug")
        required_methods = ['set_connection_info', 'get_connection_info']
        missing_methods = [m for m in required_methods if not hasattr(self.state_manager, m)]
        if missing_methods:
            logger.error(f"StateManager MISSING METHODS: {', '.join(missing_methods)}")
        else:
            logger.debug("StateManager has all required methods")

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
        self.script_manager.subscribe_script_to_event(
            "CHANNEL_FULLY_JOINED", self._handle_auto_channel_fully_joined, "IRCClient_Logic_Internal_Auto_Join_UI_Switch"
        )

    def process_trigger_event(self, event_type: str, event_data: Dict[str, Any]):
        """Process an event through the trigger system if enabled."""
        if self.trigger_manager:
            self.trigger_manager.process_trigger(event_type, event_data)
        else:
            logger.debug(f"Trigger system not enabled, skipping event: {event_type}")

    async def _process_input_queue_loop(self):
        """Continuously pulls key codes from the input queue and dispatches them."""
        if not self.input_handler:
            logger.error("InputHandler is not initialized. Cannot process input queue.")
            return

        while True:
            try:
                key_code = await self.input_handler._input_queue.get()
                await self.input_handler.handle_key_press(key_code)
                self.input_handler._input_queue.task_done()
            except asyncio.CancelledError:
                logger.info("Input queue processing task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in _process_input_queue_loop: {e}", exc_info=True)
                await asyncio.sleep(0.1) # Prevent tight loop on continuous errors

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
                await self._start_connection_if_auto() # This starts network_handler if needed
                logger.info("Auto-connection initiated.")

            if not self.network_handler._network_task or self.network_handler._network_task.done():
                logger.info("Network task not running or is done, attempting to start it now in run_main_loop.")
                await self.network_handler.start()

            self._network_task_ref = self.network_handler._network_task # Store reference

            if not self.is_headless and self.input_handler:
                self._input_reader_task_ref = asyncio.create_task(self.input_handler.async_input_reader(self._executor))
                self._input_processor_task_ref = asyncio.create_task(self._process_input_queue_loop())

            # Main operational loop
            try:
                while not self.should_quit.is_set():
                    try:
                        await self._update_ui()
                        await asyncio.sleep(0.01)  # Main loop's own small delay
                    except asyncio.CancelledError: # pragma: no cover
                        logger.info("Main operational loop's sleep/update cancelled externally.")
                        self.should_quit.set() # Ensure shutdown pathway is triggered
                        break # Exit while loop
                    except curses.error as e:  # pragma: no cover
                        logger.error(f"curses error in main operational loop: {e}")
                        if not self.is_headless:
                            self.ui_needs_update.set()
                    except Exception as e:  # pragma: no cover
                        logger.critical(f"Error in main operational loop's inner try: {e}", exc_info=True)
                        self.should_quit.set() # Ensure shutdown on error
                        if not self.is_headless:
                            self.ui_needs_update.set()
                        break # Exit while loop on critical error
            except GeneratorExit: # pragma: no cover
                logger.warning("run_main_loop: GeneratorExit caught in main operational loop. Setting should_quit.")
                self.should_quit.set() # Ensure shutdown pathway is triggered
                # Do not re-raise GeneratorExit, allow it to proceed to finally
        except asyncio.CancelledError: # pragma: no cover
            logger.info("run_main_loop task itself was cancelled. Proceeding to finally for cleanup.")
            self.should_quit.set() # Ensure shutdown pathway is triggered
        except Exception as e: # pragma: no cover
            logger.critical(f"Critical error in main client loop setup or outer execution: {e}", exc_info=True)
            self.should_quit.set() # Ensure shutdown
        finally:
            logger.info("run_main_loop: Entering finally block for full client shutdown.")
            self.should_quit.set() # Ensure it's set

            quit_msg_to_send = self._final_quit_message or "Client shutting down"

            # 1. Gracefully disconnect network (sends QUIT, stops network_handler task)
            if not self.loop.is_closed():
                if self.network_handler:
                    logger.info(f"run_main_loop finally: Attempting graceful network disconnect with message: '{quit_msg_to_send}'")
                    try:
                        await self.network_handler.disconnect_gracefully(quit_msg_to_send)
                    except Exception as e_net_disc: # pragma: no cover
                        logger.error(f"run_main_loop finally: Error during network_handler.disconnect_gracefully: {e_net_disc}", exc_info=True)
                else: # pragma: no cover
                    logger.warning("run_main_loop finally: NetworkHandler not available.")
            else:
                logger.warning("run_main_loop finally: Loop closed, skipping network disconnect.")

            # 2. Cancel and await other client-level tasks
            async def cancel_and_await_task(task: Optional[asyncio.Task], name: str):
                if task and not task.done():
                    logger.info(f"run_main_loop finally: Attempting to cancel task: {name}")
                    if not self.loop.is_closed(): # Check loop before attempting cancel
                        task.cancel() # This might still raise if loop closes between check and call
                        try:
                            # Only await if the loop is still not closed before awaiting
                            if not self.loop.is_closed():
                                await task
                            else:
                                logger.warning(f"run_main_loop finally: Loop closed before awaiting cancelled task {name}. Task state: {task}")
                        except asyncio.CancelledError:
                            logger.info(f"run_main_loop finally: Task {name} successfully cancelled and awaited.")
                        except Exception as e_await_cancel: # pragma: no cover
                            logger.error(f"run_main_loop finally: Error awaiting cancelled task {name}: {e_await_cancel}", exc_info=True)
                    else:
                        logger.warning(f"run_main_loop finally: Loop closed, cannot initiate cancel for task {name}. Task state: {task}")

            # Guard the entire block of these sensitive operations
            if not self.loop.is_closed():
                logger.info("run_main_loop finally: Loop is open, proceeding with input task cancellations.")
                await cancel_and_await_task(self._input_reader_task_ref, "_input_reader_task_ref")
                if not self.loop.is_closed(): # Re-check before next task
                    await cancel_and_await_task(self._input_processor_task_ref, "_input_processor_task_ref")
                else:
                    logger.warning("run_main_loop finally: Loop closed before cancelling _input_processor_task_ref.")
            else:
                logger.warning("run_main_loop finally: Loop was already closed before attempting any input task cancellations.")
                # Log state of tasks if loop is closed
                if self._input_reader_task_ref and not self._input_reader_task_ref.done():
                    logger.warning(f"run_main_loop finally: _input_reader_task_ref not cancelled as loop is closed. State: {self._input_reader_task_ref}")
                if self._input_processor_task_ref and not self._input_processor_task_ref.done():
                    logger.warning(f"run_main_loop finally: _input_processor_task_ref not cancelled as loop is closed. State: {self._input_processor_task_ref}")

            # self._network_task_ref is handled by network_handler.disconnect_gracefully -> stop()
            # disconnect_gracefully itself checks if the loop is closed.

            # 3. Shutdown synchronous components
            if self.dcc_manager:
                logger.info("run_main_loop finally: Shutting down DCCManager.")
                self.dcc_manager.shutdown()

            if self._executor:
                logger.info("run_main_loop finally: Shutting down ThreadPoolExecutor...")
                self._executor.shutdown(wait=True, cancel_futures=True)
                self._executor = None
                logger.info("run_main_loop finally: ThreadPoolExecutor shut down.")

            # UI shutdown is handled by pyrc.py after run_main_loop completes.

            # Dispatch final shutdown event as the last async operation of the client
            if not self.loop.is_closed():
                if hasattr(self, "event_manager") and self.event_manager:
                    try:
                        logger.info("run_main_loop finally: Dispatching CLIENT_SHUTDOWN_FINAL.")
                        await self.event_manager.dispatch_client_shutdown_final(raw_line="CLIENT_SHUTDOWN_FINAL from IRCClient_Logic")
                    except Exception as e_dispatch_final: # pragma: no cover
                        logger.error(f"run_main_loop finally: Error dispatching CLIENT_SHUTDOWN_FINAL: {e_dispatch_final}", exc_info=True)
            else:
                logger.warning("run_main_loop finally: Loop closed, skipping CLIENT_SHUTDOWN_FINAL dispatch.")

            logger.info("run_main_loop: Full client shutdown sequence in finally block complete.")
            self.shutdown_complete_event.set() # Signal that all cleanup is done

    # Removed shutdown_client method as its logic is now in run_main_loop's finally block.

    def request_shutdown(self, final_quit_message: Optional[str] = "Client shutting down"):
        """Synchronous method to signal the client to start its shutdown process."""
        logger.info(f"request_shutdown called with message: '{final_quit_message}'")
        if final_quit_message:
            self._final_quit_message = final_quit_message
        self.should_quit.set()

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
                    current_conn_info.auto_connect = False # type: ignore
                    await self.state_manager.set_connection_info(current_conn_info) # type: ignore
                elif conn_info:  # Should be the one that just failed validation
                    conn_info.auto_connect = False  # Prevent auto-connect on invalid config
                    # Attempt to set it again, but it might still fail if other issues persist beyond auto_connect
                    await self.state_manager.set_connection_info(conn_info)
            else: # conn_info was successfully set
                if conn_info.initial_channels:
                    self.pending_initial_joins = {self.context_manager._normalize_context_name(ch) for ch in conn_info.initial_channels}
                    if not self.pending_initial_joins: # If initial_channels was empty or all normalized to empty strings
                        self.all_initial_joins_processed.set() # No initial channels to wait for
                    else:
                        self.all_initial_joins_processed.clear() # Ensure it's clear if there are channels to process
                    logger.debug(f"Initialized pending_initial_joins: {self.pending_initial_joins}")
                else: # No initial channels
                    self.all_initial_joins_processed.set()
                    logger.debug("No initial channels configured, all_initial_joins_processed set immediately.")


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

    async def _join_initial_channels(self):
        """Send JOIN commands for initial channels specified in the config."""
        conn_info = self.state_manager.get_connection_info()
        if conn_info and conn_info.initial_channels:
            logger.info(f"IRCClient_Logic._join_initial_channels: Joining initial channels: {conn_info.initial_channels}")
            for channel_name in conn_info.initial_channels:
                logger.debug(f"IRCClient_Logic._join_initial_channels: Attempting to join {channel_name}")
                # Context creation and join status update is handled by /join command or RegistrationHandler
                await self.network_handler.send_raw(f"JOIN {channel_name}")
                logger.debug(f"IRCClient_Logic._join_initial_channels: Sent JOIN command for {channel_name}")
        else:
            logger.info("IRCClient_Logic._join_initial_channels: No initial channels to join.")

    async def _handle_client_ready_for_ui_switch(self, event_data: Dict[str, Any]):
        """
        Handle the CLIENT_READY event.
        This event signifies that registration is complete and auto-join commands have been sent.
        """
        nick = event_data.get("nick", "N/A")
        initial_channels_attempted = event_data.get("channels", [])
        logger.info(f"CLIENT_READY event received for nick '{nick}'. Auto-join initiated for: {initial_channels_attempted}")
        await self.add_status_message(f"Client ready. Nick: {nick}. Attempting to join: {', '.join(initial_channels_attempted) if initial_channels_attempted else 'None'}.")

        # Default to Status window initially.
        # _handle_auto_channel_fully_joined will switch to the first successfully joined initial channel.
        if self.context_manager.active_context_name != "Status" and not any(
            self.context_manager.active_context_name == self.context_manager._normalize_context_name(ch) for ch in initial_channels_attempted if ch # Ensure ch is not None
        ):
             # If not already on status or an initial channel, switch to status.
            current_active = self.context_manager.active_context_name
            is_initial_channel_active = False
            if current_active and initial_channels_attempted:
                normalized_current_active = self.context_manager._normalize_context_name(current_active)
                for ch_name_config in initial_channels_attempted:
                    if ch_name_config and self.context_manager._normalize_context_name(ch_name_config) == normalized_current_active:
                        is_initial_channel_active = True
                        break

            if not is_initial_channel_active:
                 logger.debug(f"CLIENT_READY: Active context is '{current_active}', not an initial channel. Setting to 'Status'.")
                 self.context_manager.set_active_context("Status")

        self.ui_needs_update.set()

    async def _handle_auto_channel_fully_joined(self, event_data: Dict[str, Any]):
        """
        Handles the CHANNEL_FULLY_JOINED event.
        Switches UI to the first successfully joined *configured* initial channel
        if the UI is still on the "Status" window and a switch hasn't occurred yet.
        """
        joined_channel_name = event_data.get("channel_name")
        logger.debug(f"_handle_auto_channel_fully_joined: Called for channel '{joined_channel_name}'.")

        if not joined_channel_name:
            return

        conn_info = self.state_manager.get_connection_info()
        if not conn_info or not conn_info.initial_channels:
            logger.debug("_handle_auto_channel_fully_joined: No conn_info or no initial_channels configured. Returning.")
            return

        joined_channel_normalized = self.context_manager._normalize_context_name(joined_channel_name)
        # Ensure initial_channels from config are also normalized for comparison
        normalized_initial_channels = [self.context_manager._normalize_context_name(ch) for ch in conn_info.initial_channels if ch]


        current_active_context_name_or_status = self.context_manager.active_context_name or "Status"
        current_active_normalized = self.context_manager._normalize_context_name(current_active_context_name_or_status)

        logger.debug(
            f"_handle_auto_channel_fully_joined: Joined='{joined_channel_normalized}', ConfiguredInitialChannels='{normalized_initial_channels}', "
            f"IsStatusActive={current_active_normalized.lower() == 'status'}, SwitchedAlready={self._switched_to_initial_channel}, CurrentActive='{current_active_normalized}'"
        )

        # Switch to the first successfully joined *configured* initial channel if still on Status window
        # and we haven't already switched for another initial channel.
        if (
            joined_channel_normalized in normalized_initial_channels
            and current_active_normalized.lower() == "status"
            and not self._switched_to_initial_channel
        ):
            logger.info(f"_handle_auto_channel_fully_joined: Auto-switching to first successfully joined initial channel: {joined_channel_name}")
            self.context_manager.set_active_context(joined_channel_name) # Use original case for set_active_context
            if not self.is_headless and isinstance(self.ui, UIManager): # Check if it's UIManager
                # self.ui here would be an instance of UIManager
                cast(UIManager, self.ui).refresh_all_windows()
            self._switched_to_initial_channel = True # Mark that we've done the first switch
        elif joined_channel_normalized in normalized_initial_channels and self._switched_to_initial_channel:
            logger.debug(f"CHANNEL_FULLY_JOINED (auto-join): Initial channel '{joined_channel_normalized}' joined, but already switched to an earlier initial channel. No further auto-switch.")
        elif joined_channel_normalized in normalized_initial_channels and current_active_normalized.lower() != "status":
            logger.debug(f"CHANNEL_FULLY_JOINED (auto-join): Initial channel '{joined_channel_normalized}' joined, but UI is already on '{current_active_normalized}' (not Status). No auto-switch.")
        else: # Channel joined is not an initial channel, or some other condition not met
            logger.debug(
                f"CHANNEL_FULLY_JOINED: '{joined_channel_normalized}' is not one of the configured initial channels or other conditions not met. No auto-switch action based on this event."
            )

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
                pass # CAP negotiation is handled by RegistrationHandler.on_connection_established

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
        final_text = text
        if prefix_time:
            timestamp = time.strftime("%H:%M:%S")
            final_text = f"[{timestamp}] {text}"

        logger.debug(f"IRCClient_Logic.add_message: Adding to context='{context_name}', text='{final_text[:100]}...', color_attr={color_attr}, kwargs={kwargs}")

        self.context_manager.add_message_to_context(
            context_name=context_name, text_line=final_text, color_attr=color_attr, **kwargs
        )
        if self.ui: # Only set UI update flag if UI is active
            self.ui_needs_update.set()
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
            await self.state_manager.set_connection_state(ConnectionState.CONFIG_ERROR, f"Internal error processing config {config_name}")
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

    async def rehash_configuration(self):
        """Reloads the application configuration."""
        logger.info("Attempting to rehash configuration...")
        if self.config.rehash():
            # Update components that depend on self.config
            self.channel_logger_manager = ChannelLoggerManager(self.config)
            # self.context_manager.max_history_per_context = self.config.max_history # ContextManager uses this at init
            # ScriptManager might need re-evaluation of disabled_scripts
            # For now, we assume direct access to self.config.disabled_scripts is sufficient
            # or a restart is needed for script changes.

            # Re-evaluate TriggerManager based on new config
            if self.config.enable_trigger_system:
                if not self.trigger_manager:
                    self._initialize_trigger_manager() # Initialize if not already
                elif self.trigger_manager: # If it exists, reload its triggers
                    self.trigger_manager.triggers.clear()
                    self.trigger_manager.load_triggers()
            elif not self.config.enable_trigger_system and self.trigger_manager:
                logger.info("Trigger system disabled via rehash. Clearing existing triggers.")
                self.trigger_manager.triggers.clear() # Clear triggers, but manager object might persist
                # Or, self.trigger_manager = None # To fully disable

            await self.add_status_message("Configuration rehashed successfully.", "system")
            logger.info("Configuration rehashed successfully.")
            await self.add_status_message("Some configuration changes may require a client restart to take full effect.", "warning")
        else:
            await self.add_status_message("Failed to rehash configuration. Check logs.", "error")
            logger.error("Failed to rehash configuration.")

    async def switch_active_context(self, direction: str):
        logger.debug(f"switch_active_context called with direction: '{direction}'")
        context_names = self.context_manager.get_all_context_names()
        logger.debug(f"Available context names (raw from manager): {context_names}")
        if not context_names:
            logger.warning("switch_active_context: No context names returned from manager.")
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

        logger.debug(f"Sorted context names for cycling: {sorted_context_names}")

        current_active_name = self.context_manager.active_context_name
        logger.debug(f"Current active context name (from manager): {current_active_name}")

        if not current_active_name and sorted_context_names:
            current_active_name = sorted_context_names[0]
            logger.debug(f"Current active context was None, set to first sorted: {current_active_name}")
        elif not current_active_name: # Should be caught by the earlier check on context_names
            logger.warning("switch_active_context: Current active context is None and no sorted_context_names available. Returning.")
            return

        current_idx = -1
        if current_active_name: # current_active_name could still be None if sorted_context_names was empty
            try:
                current_idx = sorted_context_names.index(current_active_name)
            except ValueError:
                logger.warning(f"switch_active_context: Current active context '{current_active_name}' not found in sorted list. Defaulting to index 0.")
                current_idx = 0
                if sorted_context_names: # If list is not empty, set current_active_name to first element
                    current_active_name = sorted_context_names[0]
                else: # Should be caught by earlier checks
                    logger.error("switch_active_context: sorted_context_names is empty, cannot proceed.")
                    return

        logger.debug(f"Determined current_idx: {current_idx} for current_active_name: {current_active_name}")


        if not current_active_name:
            logger.error("switch_active_context: current_active_name is still None after attempting to default. This should not happen. Returning.")
            return

        new_active_context_name = None
        num_contexts = len(sorted_context_names)
        if num_contexts == 0: # Should be caught by earlier checks
            logger.warning("switch_active_context: num_contexts is 0. Returning.")
            return

        logger.debug(f"Cycling with num_contexts: {num_contexts}, current_idx: {current_idx}")

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
                    logger.debug(f"Attempting to set new active context to: {new_active_context_name}")
                    if self.context_manager.set_active_context(new_active_context_name):
                        logger.info(f"Successfully switched active context to: {new_active_context_name}")
                        self.ui_needs_update.set()
                    else:
                        logger.error(f"Failed to set active context to {new_active_context_name} via context_manager.")
                # This else was incorrectly placed; new_active_context_name could be None if direction was not found.
                # else:
                #    logger.warning(f"switch_active_context: new_active_context_name is None after processing direction '{direction}'. No switch.")
        # This block should be outside the final 'else' to apply to 'next' and 'prev' too.
        if new_active_context_name and new_active_context_name != current_active_name: # Ensure there's a change
            logger.debug(f"Final attempt to set new active context to: {new_active_context_name}")
            if self.context_manager.set_active_context(new_active_context_name):
                logger.info(f"Successfully switched active context from '{current_active_name}' to: {new_active_context_name}")
                self.ui_needs_update.set()
            else:
                logger.error(f"Final attempt: Failed to set active context to {new_active_context_name} via context_manager.")
        elif new_active_context_name == current_active_name:
            logger.debug(f"New active context '{new_active_context_name}' is same as current '{current_active_name}'. No switch needed.")
        else:
            logger.warning(f"switch_active_context: new_active_context_name is None after all processing for direction '{direction}'. No switch.")


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

    async def handle_channel_fully_joined(self, channel_name: str):
        """
        Handles logic for when a channel is fully joined (after RPL_ENDOFNAMES).
        """
        logger.info(f"IRCClient_Logic.handle_channel_fully_joined: Channel {channel_name} is now fully joined.")
        normalized_channel_name = self.context_manager._normalize_context_name(channel_name)

        if normalized_channel_name in self.pending_initial_joins:
            self.pending_initial_joins.remove(normalized_channel_name)
            logger.debug(f"IRCClient_Logic.handle_channel_fully_joined: Removed '{normalized_channel_name}' from pending_initial_joins. Remaining: {self.pending_initial_joins}")
            if not self.pending_initial_joins:
                logger.info("IRCClient_Logic.handle_channel_fully_joined: All initial joins processed. Setting all_initial_joins_processed event.")
                self.all_initial_joins_processed.set()

        # Dispatch an event indicating the channel is fully joined
        if hasattr(self, "event_manager") and self.event_manager:
            logger.debug(f"IRCClient_Logic.handle_channel_fully_joined: Dispatching CHANNEL_FULLY_JOINED event for {channel_name}.")
            await self.event_manager.dispatch_event(
                "CHANNEL_FULLY_JOINED",
                {
                    "channel_name": channel_name,
                    "client_nick": self.nick
                }
            )
            logger.debug(f"IRCClient_Logic.handle_channel_fully_joined: Dispatched CHANNEL_FULLY_JOINED event for {channel_name}.")
        else:
            logger.warning(f"IRCClient_Logic.handle_channel_fully_joined: Cannot dispatch CHANNEL_FULLY_JOINED for {channel_name}: EventManager not found.")

        self.ui_needs_update.set()
        logger.debug(f"IRCClient_Logic.handle_channel_fully_joined: UI update set for {channel_name}.")
