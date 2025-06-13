# tirc_core/client/irc_client_logic.py
from __future__ import annotations
from typing import TYPE_CHECKING
import asyncio
import concurrent.futures  # For running blocking calls in a thread pool
from collections import deque
from typing import Optional, Any, List, Set, Dict, Tuple, cast
import logging
import logging.handlers
import os
import platform
import sys # Import sys for sys.exit
import time # Import time
from enum import Enum
from dataclasses import asdict

# Conditional import for curses based on platform
if platform.system() == "Windows":
    try:
        import curses
    except ImportError:
        print("Error: 'windows-curses' is required on Windows. Please run 'pip install windows-curses'")
        sys.exit(1)
else:
    import curses

from tirc_core import app_config
from tirc_core.app_config import AppConfig, ServerConfig
from tirc_core.state_manager import StateManager, ConnectionInfo, ConnectionState
from tirc_core.client.state_change_ui_handler import StateChangeUIHandler
from tirc_core.logging.channel_logger import ChannelLoggerManager
from tirc_core.script_manager import ScriptManager
from tirc_core.event_manager import EventManager
from tirc_core.context_manager import ContextManager, ChannelJoinStatus
from tirc_core.client.ui_manager import UIManager
from tirc_core.network_handler import NetworkHandler
from tirc_core.commands.command_handler import CommandHandler
from tirc_core.client.input_handler import InputHandler
from tirc_core.features.triggers.trigger_manager import TriggerManager, ActionType
from tirc_core.irc import irc_protocol
from tirc_core.irc.irc_message import IRCMessage
from tirc_core.irc.cap_negotiator import CapNegotiator
from tirc_core.irc.sasl_authenticator import SaslAuthenticator
from tirc_core.irc.registration_handler import RegistrationHandler
from tirc_core.scripting.python_trigger_api import PythonTriggerAPI
from tirc_core.dcc.dcc_manager import DCCManager
from tirc_core.client.connection_orchestrator import ConnectionOrchestrator
from tirc_core.client.client_shutdown_coordinator import ClientShutdownCoordinator
from tirc_core.client.client_view_manager import ClientViewManager
from tirc_core.client.dummy_ui import DummyUI
from tirc_core.client.initial_state_builder import InitialStateBuilder
from tirc_core.ipc_manager import IPCManager

logger = logging.getLogger("tirc.logic")

class IRCClient_Logic:
    def __init__(self, stdscr: Optional[curses.window], args: Any, config: AppConfig):
        # --- Stage 1: Basic Attribute Initialization ---
        self.stdscr = stdscr
        self.is_headless = stdscr is None
        self.args = args
        self.config: AppConfig = config
        self.loop = asyncio.get_event_loop()

        self.should_quit = asyncio.Event()
        self.shutdown_complete_event = asyncio.Event()
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

        self._network_task_ref: Optional[asyncio.Task] = None
        self._input_reader_task_ref: Optional[asyncio.Task] = None
        self._input_processor_task_ref: Optional[asyncio.Task] = None

        self._pending_initial_joins_internal: Set[str] = set()
        self.all_initial_joins_processed = asyncio.Event()
        self._switched_to_initial_channel = False


        # --- Stage 2: Initialize All Manager Components ---
        self.state_manager = StateManager()
        self.state_manager.reset_session_state()
        self.channel_logger_manager = ChannelLoggerManager(self.config)
        self.context_manager = ContextManager(max_history_per_context=self.config.max_history)
        self.network_handler: NetworkHandler = NetworkHandler(self)

        cli_disabled_scripts = set(self.args.disable_script if hasattr(self.args, "disable_script") and self.args.disable_script else [])
        config_disabled_scripts = self.config.disabled_scripts if self.config.disabled_scripts else set()
        final_disabled_scripts = cli_disabled_scripts.union(config_disabled_scripts)
        self.script_manager: ScriptManager = ScriptManager(self, self.config.BASE_DIR, disabled_scripts=final_disabled_scripts)
        self.event_manager = EventManager(self)
        self.dcc_manager = DCCManager(self, self.event_manager)
        self.ui: UIManager | DummyUI = UIManager(stdscr, self) if not self.is_headless else DummyUI()
        self.input_handler: Optional[InputHandler] = InputHandler(self) if not self.is_headless else None
        self.command_handler = CommandHandler(self)
        self.trigger_manager: Optional[TriggerManager] = TriggerManager(os.path.join(self.config.BASE_DIR, "config")) if self.config.enable_trigger_system else None
        self.python_trigger_api_instance = PythonTriggerAPI(self)

        self.cap_negotiator: Optional[CapNegotiator] = None
        self.sasl_authenticator: Optional[SaslAuthenticator] = None
        self.registration_handler: Optional[RegistrationHandler] = None

        self.state_ui_handler = StateChangeUIHandler(self)
        self.connection_orchestrator = ConnectionOrchestrator(self)
        self.shutdown_coordinator = ClientShutdownCoordinator(self)
        self.view_manager = ClientViewManager(self)
        self.ipc_manager = IPCManager(self)

        self.event_manager.subscribe(
            "CLIENT_READY", self.view_manager._handle_client_ready_for_ui_switch, "IRCClient_Logic_Internal"
        )
        self.event_manager.subscribe(
            "RAW_SERVER_MESSAGE", self.handle_raw_server_message, "IRCClient_Logic_Internal"
        )
        self.event_manager.subscribe(
            "CHANNEL_FULLY_JOINED", self.view_manager._handle_auto_channel_fully_joined, "IRCClient_Logic_Internal"
        )

        state_builder = InitialStateBuilder(self.config, self.args)
        conn_info = state_builder.build()
        logger.debug(f"IRCClient_Logic: InitialStateBuilder built conn_info: {conn_info}")

        if conn_info:
            try:
                set_success = self.loop.run_until_complete(self.state_manager.set_connection_info(conn_info))
                logger.debug(f"IRCClient_Logic: state_manager.set_connection_info(conn_info) result: {set_success}")

                if not set_success:
                    logger.error("Initial state creation failed: ConnectionInfo validation error.")
                    config_errors = self.state_manager.get_config_errors()
                    error_summary = "; ".join(config_errors) if config_errors else "Unknown validation error."
                    self.loop.create_task(self.add_status_message(f"Initial Configuration Error: {error_summary}", "error"))
                    current_conn_info = self.state_manager.get_connection_info()
                    if current_conn_info:
                        current_conn_info.auto_connect = False
                        self.loop.create_task(self.state_manager.set_connection_info(current_conn_info))
                    elif conn_info:
                        conn_info.auto_connect = False
                        self.loop.create_task(self.state_manager.set_connection_info(conn_info))
                else:
                    if conn_info.initial_channels:
                        self.pending_initial_joins = {self.context_manager._normalize_context_name(ch) for ch in conn_info.initial_channels if ch}
                        if not self.pending_initial_joins: self.all_initial_joins_processed.set()
                        else: self.all_initial_joins_processed.clear()
                    else:
                        self.all_initial_joins_processed.set()
                        logger.debug("No initial channels configured.")
            except Exception as e:
                logger.critical(f"Error setting initial connection info synchronously: {e}", exc_info=True)
                self.all_initial_joins_processed.set()
        else:
            logger.info("No initial connection info built. Starting without auto-connect.")
            self.all_initial_joins_processed.set()

        self.context_manager.create_context("Status", context_type="status")
        if self.config.dcc.enabled:
            self.context_manager.create_context("DCC", context_type="dcc_transfers")
        if conn_info and conn_info.initial_channels:
            for ch in conn_info.initial_channels:
                self.context_manager.create_context(ch, context_type="channel", initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN)
        self.context_manager.set_active_context("Status")

    async def execute_python_trigger_code(self, code_string: str, event_data: Dict[str, Any]):
        """Executes a Python code string from a trigger in a controlled environment."""
        if not code_string:
            logger.warning("execute_python_trigger_code called with empty code string.")
            return

        # Prepare the execution scope
        # Provide the script API and event data to the executed code
        execution_globals = {
            "api": self.python_trigger_api_instance, # The safe API for scripts
            "event": event_data,
            "client": self, # Exposing full client logic can be risky, consider if needed
            "asyncio": asyncio, # Allow async operations within the trigger code
            "logger": logging.getLogger(f"tirc.trigger.python_code"), # Dedicated logger
            # Add other safe utilities or modules as needed
            "__builtins__": {
                "print": lambda *args, **kwargs: logging.getLogger(f"tirc.trigger.python_code.print").info(" ".join(map(str,args))), # Redirect print
                "len": len, "str": str, "int": int, "float": float, "bool": bool,
                "list": list, "dict": dict, "set": set, "tuple": tuple,
                "True": True, "False": False, "None": None,
                "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
                "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
                "Exception": Exception, # Allow raising common exceptions
            }
        }

        # Ensure the code is treated as an async function body if it uses await
        # This is a simplified approach; a more robust solution might involve ast parsing.
        # For now, we assume simple scripts or that users will manage async correctly.
        # If the code needs to be `async def`, it should be defined and called.
        # A common pattern for trigger code is to be a block of statements.
        # If it's simple, exec might work. For async, it's more complex.

        # For simplicity, if 'await' is in the code, wrap it to be awaitable.
        # This is a basic heuristic and might not cover all async scenarios.
        is_async_code = "await " in code_string

        try:
            if is_async_code:
                # Wrap the code in an async function and execute it
                # This allows 'await' to be used directly in the trigger code string
                wrapped_code = f"async def __trigger_code_runner__():\n"
                for line in code_string.splitlines():
                    wrapped_code += f"    {line}\n"
                wrapped_code += f"asyncio.create_task(__trigger_code_runner__())" # Schedule it

                temp_locals: Dict[str, Any] = {}
                exec(compile(wrapped_code, '<trigger_code>', 'exec'), execution_globals, temp_locals)
                # The task is created and runs in the background.
                # If direct result or completion waiting is needed, this needs adjustment.
            else:
                # Execute synchronous code directly
                exec(code_string, execution_globals)

            logger.info(f"Successfully executed Python trigger code snippet.")

        except Exception as e:
            logger.error(f"Error executing Python trigger code: {e}\nCode:\n{code_string}", exc_info=True)
            await self.add_status_message(f"Error in Python trigger: {e}", "error")


    def process_trigger_event(self, event_type: str, event_data: Dict[str, Any]):
        if self.trigger_manager:
            trigger_action = self.trigger_manager.process_trigger(event_type, event_data)
            if trigger_action:
                if trigger_action["type"] == ActionType.COMMAND:
                    asyncio.create_task(self.command_handler.process_user_command(trigger_action["content"]))
                elif trigger_action["type"] == ActionType.PYTHON and trigger_action["code"]:
                    asyncio.create_task(self.execute_python_trigger_code(trigger_action["code"], trigger_action["event_data"]))
        else:
            logger.debug(f"Trigger system not enabled, skipping event: {event_type}")

    async def _process_input_queue_loop(self):
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
                await asyncio.sleep(0.1)

    async def run_main_loop(self):
        logger.info("Starting main client loop (headless=%s).", self.is_headless)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        try:
            self.connection_orchestrator.initialize_handlers()
            self.script_manager.load_scripts()
            await self._log_startup_status()
            await self.ipc_manager.start_server()

            conn_info = self.state_manager.get_connection_info()
            if conn_info and conn_info.auto_connect:
                logger.info(f"Auto-connecting to {conn_info.server}:{conn_info.port} via ConnectionOrchestrator")
                await self.connection_orchestrator.establish_connection(conn_info)
                logger.info("Auto-connection initiated via ConnectionOrchestrator.")

            if not self.network_handler._network_task or self.network_handler._network_task.done():
                logger.info("Network task not running or is done, attempting to start it now in run_main_loop.")
                await self.network_handler.start()
            self._network_task_ref = self.network_handler._network_task

            # Start DCC periodic cleanup task if DCC is enabled
            if self.dcc_manager and self.dcc_manager.dcc_config.enabled:
                await self.dcc_manager.start_periodic_task()

            if not self.is_headless and self.input_handler:
                self._input_reader_task_ref = asyncio.create_task(self.input_handler.async_input_reader(self._executor))
                self._input_processor_task_ref = asyncio.create_task(self._process_input_queue_loop())

            try:
                while not self.should_quit.is_set():
                    try:
                        await self._update_ui()
                        await asyncio.sleep(0.01)
                    except asyncio.CancelledError:
                        logger.info("Main operational loop's sleep/update cancelled externally.")
                        self.should_quit.set()
                        break
                    except curses.error as e:
                        logger.error(f"curses error in main operational loop: {e}")
                        if not self.is_headless: self.ui_needs_update.set()
                    except Exception as e:
                        logger.critical(f"Error in main operational loop's inner try: {e}", exc_info=True)
                        self.should_quit.set()
                        if not self.is_headless: self.ui_needs_update.set()
                        break
            except GeneratorExit:
                logger.warning("run_main_loop: GeneratorExit caught in main operational loop. Setting should_quit.")
                self.should_quit.set()
        except asyncio.CancelledError:
            logger.info("run_main_loop task itself was cancelled. Proceeding to finally for cleanup.")
            self.should_quit.set()
        except Exception as e:
            logger.critical(f"Critical error in main client loop setup or outer execution: {e}", exc_info=True)
            self.should_quit.set()
        finally:
            logger.info("run_main_loop: Entering finally block, delegating to ClientShutdownCoordinator.")
            await self.shutdown_coordinator.initiate_graceful_shutdown(self._final_quit_message or "Client shutting down")
            logger.info("run_main_loop: Shutdown coordinator finished. Main loop finally block complete.")

    @property
    def pending_initial_joins(self) -> Set[str]:
        return self._pending_initial_joins_internal

    @pending_initial_joins.setter
    def pending_initial_joins(self, value: Set[str]):
        logger.debug(f"IRCClient_Logic: pending_initial_joins BEING SET. Old: {self._pending_initial_joins_internal}, New: {value}", stack_info=False)
        self._pending_initial_joins_internal = value

    def request_shutdown(self, final_quit_message: Optional[str] = "Client shutting down"):
        logger.info(f"request_shutdown called with message: '{final_quit_message}'")
        if final_quit_message:
            self._final_quit_message = final_quit_message
        self.should_quit.set()

    async def _unload_all_scripts(self):
        logger.info("Unloading all scripts...")
        for script_name, script_instance in list(self.script_manager.scripts.items()):
            try:
                if hasattr(script_instance, "unload") and callable(script_instance.unload):
                    logger.info(f"Unloading script: {script_name}")
                    unload_method = script_instance.unload
                    if asyncio.iscoroutinefunction(unload_method):
                        await unload_method()
                    else:
                        unload_method()
                if script_name in self.script_manager.scripts:
                    del self.script_manager.scripts[script_name]
            except Exception as e:
                logger.error(f"Error unloading script {script_name}: {e}", exc_info=True)
        logger.info("All scripts unloaded.")

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


    async def _join_initial_channels(self):
        conn_info = self.state_manager.get_connection_info()
        if conn_info and conn_info.initial_channels:
            logger.info(f"IRCClient_Logic._join_initial_channels: Joining initial channels: {conn_info.initial_channels}")
            for channel_name in conn_info.initial_channels:
                await self.network_handler.send_raw(f"JOIN {channel_name}")
        else:
            logger.info("IRCClient_Logic._join_initial_channels: No initial channels to join.")

    async def _update_ui(self):
        if self.ui and self.ui_needs_update.is_set():
            await self.ui.refresh_all_windows() # Added await
            self.ui_needs_update.clear()

    async def _log_startup_status(self):
        await self.add_status_message("tIRC Client starting...")
        conn_info = self.state_manager.get_connection_info()
        if conn_info and conn_info.server and conn_info.port:
            channels_display = ", ".join(conn_info.initial_channels) if conn_info.initial_channels else "None"
            await self.add_status_message(f"Target: {conn_info.server}:{conn_info.port}, Nick: {conn_info.nick}, Channels: {channels_display}")
        else:
            await self.add_status_message("No default server configured. Use /server or /connect.", "warning")
        logger.info("IRCClient_Logic initialization complete.")

    def _create_script_manager(self):
        cli_disabled_scripts = set(self.args.disable_script if hasattr(self.args, "disable_script") and self.args.disable_script else [])
        config_disabled_scripts = self.config.disabled_scripts if self.config.disabled_scripts else set()
        final_disabled_scripts = cli_disabled_scripts.union(config_disabled_scripts)
        return ScriptManager(self, self.config.BASE_DIR, disabled_scripts=final_disabled_scripts)

    def _initialize_trigger_manager(self):
        if not self.config.enable_trigger_system:
            self.trigger_manager = None
            return
        config_dir_triggers = os.path.join(self.config.BASE_DIR, "config")
        if not os.path.exists(config_dir_triggers):
            try: os.makedirs(config_dir_triggers, exist_ok=True)
            except OSError as e_mkdir:
                logger.error(f"Could not create config directory for triggers: {e_mkdir}")
                self.trigger_manager = None
                return
        self.trigger_manager = TriggerManager(config_dir_triggers)
        if self.trigger_manager: self.trigger_manager.load_triggers()

    async def add_message(self, text: str, color_pair_id: int, context_name: str, prefix_time: bool = False, **kwargs):
        final_text = text
        if prefix_time:
            timestamp = time.strftime("%H:%M:%S")
            final_text = f"[{timestamp}] {text}"

        logger.debug(f"IRCClient_Logic.add_message: Adding to context='{context_name}', text='{final_text[:100]}...', color_pair_id={color_pair_id}, kwargs={kwargs}")
        self.context_manager.add_message_to_context(context_name=context_name, text_line=final_text, color_pair_id=color_pair_id, **kwargs)
        if self.ui: self.ui_needs_update.set()
        else: logger.info(f"[Message to {context_name}] {text}")

    async def add_status_message(self, text: str, color_key: str = "system"):
        color_pair_id = self.ui.colors.get(color_key, self.ui.colors.get("system", 0)) if self.ui and hasattr(self.ui, 'colors') else 0
        await self.add_message(text, color_pair_id, "Status", prefix_time=False)

    async def _configure_from_server_config(self, config_data: ServerConfig, config_name: str) -> bool:
        try:
            conn_info_data = asdict(config_data)
            if 'address' in conn_info_data:
                conn_info_data['server'] = conn_info_data.pop('address')
            if 'channels' in conn_info_data:
                 conn_info_data['initial_channels'] = conn_info_data.pop('channels')

            expected_fields = ConnectionInfo.__annotations__.keys()
            for field in expected_fields:
                if field not in conn_info_data:
                    if field == 'username': conn_info_data[field] = conn_info_data.get('nick')
                    elif field == 'realname': conn_info_data[field] = conn_info_data.get('nick')
                    elif field == 'verify_ssl_cert': conn_info_data[field] = True
                    elif field == 'auto_connect': conn_info_data[field] = False
                    elif field == 'initial_channels': conn_info_data[field] = []
                    elif field == 'desired_caps': conn_info_data[field] = []

            filtered_conn_info_data = {k: v for k, v in conn_info_data.items() if k in expected_fields}
            conn_info_obj = ConnectionInfo(**filtered_conn_info_data)

            if not await self.state_manager.set_connection_info(conn_info_obj):
                logger.error(f"Configuration for server '{config_name}' failed validation.")
                await self.state_manager.set_connection_state(ConnectionState.CONFIG_ERROR,
                                                              f"Validation failed for {config_name}",
                                                              self.state_manager.get_config_errors())
                return False
            logger.info(f"Successfully validated and set server config: {config_name} in StateManager.")
            return True
        except Exception as e:
            logger.error(f"Error configuring from server config {config_name}: {str(e)}", exc_info=True)
            await self.state_manager.set_connection_state(ConnectionState.CONFIG_ERROR, f"Internal error processing config {config_name}")
            return False

    async def handle_raw_server_message(self, event_data: Dict[str, Any]):
        line = event_data.get("line")
        if line is None: return
        await irc_protocol.handle_server_message(self, line)

    async def send_ctcp_privmsg(self, target: str, ctcp_message: str):
        if not target or not ctcp_message: return
        payload = ctcp_message.strip("\x01")
        full_ctcp_command = f"\x01{payload}\x01"
        await self.network_handler.send_raw(f"PRIVMSG {target} :{full_ctcp_command}")
        logger.debug(f"Sent CTCP PRIVMSG to {target}: {full_ctcp_command}")

    async def rehash_configuration(self):
        logger.info("Attempting to rehash configuration...")
        if self.config.rehash():
            self.channel_logger_manager = ChannelLoggerManager(self.config)
            if self.config.enable_trigger_system:
                if not self.trigger_manager:
                    config_dir_triggers = os.path.join(self.config.BASE_DIR, "config")
                    self.trigger_manager = TriggerManager(config_dir_triggers)
                if self.trigger_manager: # Check again in case initialization failed
                    self.trigger_manager.triggers.clear()
                    self.trigger_manager.load_triggers()
            elif not self.config.enable_trigger_system and self.trigger_manager:
                logger.info("Trigger system disabled via rehash. Clearing existing triggers.")
                self.trigger_manager.triggers.clear()
            await self.add_status_message("Configuration rehashed successfully.", "system")
            logger.info("Configuration rehashed successfully.")
            await self.add_status_message("Some configuration changes may require a client restart.", "warning")
        else:
            await self.add_status_message("Failed to rehash configuration. Check logs.", "error")
            logger.error("Failed to rehash configuration.")

    async def handle_channel_fully_joined(self, channel_name: str):
        logger.info(f"IRCClient_Logic.handle_channel_fully_joined: Channel {channel_name} is now fully joined.")
        normalized_channel_name = self.context_manager._normalize_context_name(channel_name)
        if normalized_channel_name in self._pending_initial_joins_internal:
            self._pending_initial_joins_internal.remove(normalized_channel_name)
            if not self._pending_initial_joins_internal:
                self.all_initial_joins_processed.set()
        if hasattr(self, "event_manager") and self.event_manager:
            await self.event_manager.dispatch_event("CHANNEL_FULLY_JOINED", {"channel_name": channel_name, "client_nick": self.nick})
        self.ui_needs_update.set()
