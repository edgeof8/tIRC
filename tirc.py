# tirc.py
import curses
import argparse
import time
import logging
import logging.handlers
import os
import sys
import asyncio  # Import asyncio
import tracemalloc # For more detailed tracebacks
from typing import List, Optional
import sys # Added for sys.exit

# Import the new AppConfig class and other necessary components
from tirc_core.app_config import AppConfig
from tirc_core.config_defs import ServerConfig, DEFAULT_NICK, DEFAULT_SSL_PORT, DEFAULT_PORT
from tirc_core.client.irc_client_logic import IRCClient_Logic
from tirc_core.client.dummy_ui import DummyUI
from tirc_core.client.ui_manager import UIManager

# Define logger at module level for broader access
main_ui_logger = logging.getLogger("tirc.main_ui")


def setup_logging(config: AppConfig):
    """Set up logging for the application using the config object."""
    if not config.log_enabled:
        logging.disable(logging.CRITICAL + 1)
        print("Logging is disabled in configuration.")
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Clear existing handlers to prevent duplication on rehash
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    log_dir = os.path.join(config.BASE_DIR, "logs")
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
        except OSError as e:
            print(f"Error creating log directory {log_dir}: {e}. Logging to project root.")
            log_dir = config.BASE_DIR

    try:
        full_log_path = os.path.join(log_dir, config.log_file)
        full_handler = logging.handlers.RotatingFileHandler(
            full_log_path,
            maxBytes=config.log_max_bytes,
            backupCount=config.log_backup_count,
            encoding="utf-8",
        )
        full_handler.setFormatter(formatter)
        full_handler.setLevel(config.log_level_int)
        root_logger.addHandler(full_handler)

        error_log_path = os.path.join(log_dir, config.log_error_file)
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_path,
            maxBytes=config.log_max_bytes,
            backupCount=config.log_backup_count,
            encoding="utf-8",
        )
        error_handler.setFormatter(formatter)
        error_handler.setLevel(config.log_error_level_int)
        root_logger.addHandler(error_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO) # Console output can remain INFO
        root_logger.addHandler(console_handler)

        # Explicitly set the level for the 'tirc' logger namespace to ensure
        # all sub-loggers (tirc.config, tirc.logic, etc.) inherit this level
        # for the file handlers.
        tirc_base_logger = logging.getLogger("tirc")
        tirc_base_logger.setLevel(config.log_level_int) # Set to configured level, e.g., DEBUG

        # Now use this logger for the initial messages
        tirc_base_logger.info(f"Logging initialized. Full log: {full_log_path}, Error log: {error_log_path}")
        tirc_base_logger.info(f"'tirc' base logger set to level: {logging.getLevelName(tirc_base_logger.level)} (effective: {logging.getLevelName(tirc_base_logger.getEffectiveLevel())}, target: {config.log_level_str})")

        # Explicitly set levels for known sub-loggers to ensure they adhere to the file log level
        loggers_to_set = ["tirc.config", "tirc.logic", "tirc.script_manager", "tirc.network", "tirc.command_handler", "tirc.event_manager", "tirc.main_app", "tirc.main_ui", "tirc.irc", "tirc.dcc"]
        for logger_name in loggers_to_set:
            specific_logger = logging.getLogger(logger_name)
            specific_logger.setLevel(config.log_level_int)
            tirc_base_logger.info(f"Logger '{logger_name}' explicitly set to level: {logging.getLevelName(specific_logger.level)} (effective: {logging.getLevelName(specific_logger.getEffectiveLevel())})")

        if config.channel_log_enabled:
            tirc_base_logger.info(f"Per-channel logging is enabled. Channel logs will be placed in: {log_dir}")

    except Exception as e:
        print(f"Failed to initialize advanced file logging: {e}")
        logging.basicConfig(
            level=config.log_level_int,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        logging.getLogger("tirc").error(f"Advanced file logging setup failed. Using basic console logging. Error: {e}")


async def main_curses_wrapper(stdscr, client: IRCClient_Logic, args: argparse.Namespace, config: AppConfig):
    """Core application logic when running with curses."""
    main_ui_logger.info("main_curses_wrapper: Initializing client and UI.")
    try:
        # Client is now created in curses_wrapper_with_args and passed in.
        # Initialize UI elements that depend on stdscr if client needs it (already done in IRCClient_Logic constructor)
        await client.add_status_message("tIRC Initializing... Please wait.")
        client.ui_needs_update.set()

        await client.run_main_loop() # Main execution path

    except (asyncio.CancelledError, GeneratorExit) as e:
        # These are expected if the task is cancelled from outside (e.g., by KeyboardInterrupt in curses_wrapper_with_args)
        main_ui_logger.info(f"main_curses_wrapper: Main client loop was cancelled or exited ({type(e).__name__}). Client shutdown should be handled by IRCClient_Logic.")
        # client.run_main_loop()'s finally block is responsible for setting shutdown_complete_event
    except Exception as e: # Catch any other unexpected error from client.run_main_loop()
        main_ui_logger.critical(f"Critical unhandled error in main_curses_wrapper from client.run_main_loop(): {e}", exc_info=True)
        if client: # pragma: no cover
            client.request_shutdown(f"Critical Error in main_curses_wrapper: {e}")
            # The shutdown_complete_event will be awaited by curses_wrapper_with_args
    finally:
        main_ui_logger.info("main_curses_wrapper: Entering final curses cleanup.")
        if stdscr:
            try:
                curses.curs_set(1)
                stdscr.clear()
                stdscr.refresh()
                curses.endwin()
                main_ui_logger.debug("Curses UI shut down by main_curses_wrapper.")
            except Exception as e_curses_end: # pragma: no cover
                main_ui_logger.error(f"Error during curses.endwin() in main_curses_wrapper: {e_curses_end}")
        main_ui_logger.info("main_curses_wrapper: Curses cleanup complete.")


def parse_arguments(default_server_config: Optional[ServerConfig]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="tIRC IRC Client")

    # Get defaults from the config object for help text
    default_server = default_server_config.address if default_server_config else "N/A"
    default_port_val = default_server_config.port if default_server_config else "N/A"
    default_nick_val = default_server_config.nick if default_server_config else DEFAULT_NICK
    default_ssl_val = default_server_config.ssl if default_server_config is not None else False

    parser.add_argument("--server", default=None, help=f"IRC server address. Overrides config. (Default: {default_server})")
    parser.add_argument("--port", type=int, default=None, help=f"IRC server port. Overrides config. (Default: {default_port_val})")
    parser.add_argument("--nick", default=None, help=f"IRC nickname. Overrides config. (Default: {default_nick_val})")
    parser.add_argument("--channel", action="append", default=None, help="IRC channel to join. Can be used multiple times.")
    parser.add_argument("--password", default=None, help="IRC server password. Overrides config.")
    parser.add_argument("--nickserv-password", default=None, help="NickServ password. Overrides config.")
    parser.add_argument("--ssl", action=argparse.BooleanOptionalAction, default=None, help=f"Use SSL/TLS. Overrides config. (Default: {default_ssl_val})")
    parser.add_argument("--verify-ssl-cert", action=argparse.BooleanOptionalAction, default=None, help="Verify SSL/TLS certificate. Overrides config. (Default: True)")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode (no UI)")
    parser.add_argument("--disable-script", action="append", default=[], metavar="SCRIPT_NAME", help="Disable a specific script.")
    parser.add_argument( # NEW
        "--send-raw", # NEW
        metavar="\"COMMAND\"", # NEW
        help="Send a raw command to a running tIRC instance and exit." # NEW
    ) # NEW

    return parser.parse_args()


def main():
    tracemalloc.start() # Start tracemalloc
    # Instantiate the configuration object first
    app_config = AppConfig()

    # Setup logging using the config object
    setup_logging(app_config)
    app_logger = logging.getLogger("tirc.main_app") # This logger should now respect the file handler's level

    # Log critical config values AFTER logging is set up
    app_logger.info(f"--- Post-setup_logging Config Check ---")
    app_logger.info(f"AppConfig.log_level_str: '{app_config.log_level_str}'")
    app_logger.info(f"AppConfig.log_level_int: {app_config.log_level_int} (DEBUG is {logging.DEBUG}, INFO is {logging.INFO})")
    app_logger.info(f"AppConfig.disabled_scripts: {app_config.disabled_scripts}")
    # Check the effective level of a logger to ensure it's DEBUG for the file.
    # The 'tirc.logic' logger is used by IRCClient_Logic where we expect DEBUG messages.
    logic_logger_level = logging.getLogger("tirc.logic").getEffectiveLevel()
    app_logger.info(f"Effective level of 'tirc.logic' logger: {logging.getLevelName(logic_logger_level)}")
    app_logger.info(f"--- End Post-setup_logging Config Check ---")

    app_logger.info("Starting tIRC application.")

    # Get the default server config for argument help text
    default_server_conf = None
    if app_config.default_server_config_name:
        default_server_conf = app_config.all_server_configs.get(app_config.default_server_config_name)

    args = parse_arguments(default_server_conf)

    if args.send_raw: # NEW
        # This is an IPC client call, not a full app startup. # NEW
        # We need a small, separate async function to handle this. # NEW
        try: # NEW
            asyncio.run(send_remote_command(args.send_raw, app_config)) # NEW
        except Exception as e: # NEW
            print(f"Error sending command: {e}", file=sys.stderr) # NEW
            sys.exit(1) # NEW
        sys.exit(0) # Exit successfully after sending. # NEW

    if args.headless:
        app_logger.info("Starting tIRC in headless mode.")
        client_headless = IRCClient_Logic(stdscr=None, args=args, config=app_config)
        try:
            # Enable asyncio debug mode for asyncio.run
            asyncio.run(client_headless.run_main_loop(), debug=True)
        except KeyboardInterrupt: # pragma: no cover
            app_logger.info("Keyboard interrupt received in headless main(). Requesting client shutdown.")
            if client_headless:
                client_headless.request_shutdown("KeyboardInterrupt in headless mode")
            # asyncio.run should ideally wait for run_main_loop to finish its finally block.
        except Exception as e: # pragma: no cover
            app_logger.critical(f"Critical error in headless mode: {e}", exc_info=True)
            if client_headless:
                client_headless.request_shutdown(f"Critical error: {e}")
        finally:
            # This finally block in main() for headless mode might be redundant if asyncio.run()
            # ensures run_main_loop() completes fully, including its own extensive finally block.
            # However, ensuring request_shutdown is called if the loop exited unexpectedly without
            # should_quit being set can be a safeguard.
            if client_headless and not client_headless.should_quit.is_set(): # pragma: no cover
                 app_logger.info("Headless main() finally: Requesting shutdown as should_quit was not set.")
                 client_headless.request_shutdown("Headless mode normal exit from main()")
            app_logger.info("tIRC headless mode shutdown sequence in main() complete.")
    else:
        app_logger.info("Starting tIRC in UI mode.")
        # Define a synchronous wrapper for curses.wrapper
        def curses_wrapper_with_args(stdscr):
            main_ui_logger.debug("curses_wrapper_with_args: Creating new event loop.")
            loop = asyncio.new_event_loop()
            main_ui_logger.debug(f"curses_wrapper_with_args: New event loop created: {loop}")
            loop.set_debug(True)
            asyncio.set_event_loop(loop)

            client_instance: Optional[IRCClient_Logic] = None # To hold the client instance for shutdown
            main_task: Optional[asyncio.Task] = None

            try:
                # Create client instance here so it's accessible in KeyboardInterrupt
                client_instance = IRCClient_Logic(stdscr=stdscr, args=args, config=app_config)

                main_ui_logger.debug("curses_wrapper_with_args: Creating main_task from main_curses_wrapper.")
                main_task = loop.create_task(main_curses_wrapper(stdscr, client_instance, args, app_config))

                main_ui_logger.debug("curses_wrapper_with_args: Calling loop.run_until_complete(main_task).")
                loop.run_until_complete(main_task)
                main_ui_logger.debug("curses_wrapper_with_args: loop.run_until_complete(main_task) returned normally.")

            except KeyboardInterrupt:
                main_ui_logger.info("curses_wrapper_with_args: KeyboardInterrupt caught. Initiating graceful shutdown.")
                if client_instance:
                    main_ui_logger.info("curses_wrapper_with_args (KBInt): Requesting client shutdown.")
                    client_instance.request_shutdown("KeyboardInterrupt in curses_wrapper_with_args")

                    if hasattr(client_instance, 'shutdown_complete_event'):
                        if not client_instance.shutdown_complete_event.is_set():
                            main_ui_logger.info("curses_wrapper_with_args (KBInt): Waiting for client.shutdown_complete_event.")
                            try:
                                # Run a new run_until_complete just for the shutdown event
                                loop.run_until_complete(asyncio.wait_for(client_instance.shutdown_complete_event.wait(), timeout=30.0)) # Increased timeout
                                main_ui_logger.info("curses_wrapper_with_args (KBInt): Client shutdown_complete_event received.")
                            except asyncio.TimeoutError:
                                main_ui_logger.error("curses_wrapper_with_args (KBInt): Timeout waiting for client.shutdown_complete_event.")
                            except RuntimeError as e_rt_kb: # Loop might be closing due to other issues
                                main_ui_logger.error(f"curses_wrapper_with_args (KBInt): RuntimeError waiting for shutdown event: {e_rt_kb}")
                            except Exception as e_wait_kb: # pragma: no cover
                                main_ui_logger.error(f"curses_wrapper_with_args (KBInt): Error waiting for shutdown event: {e_wait_kb}", exc_info=True)
                        else:
                            main_ui_logger.info("curses_wrapper_with_args (KBInt): Client shutdown_complete_event was already set.")
                    else: # pragma: no cover
                        main_ui_logger.warning("curses_wrapper_with_args (KBInt): Client has no shutdown_complete_event.")
                else: # pragma: no cover
                    main_ui_logger.warning("curses_wrapper_with_args (KBInt): Client instance not available for shutdown.")

                if main_task and not main_task.done(): # pragma: no cover
                    main_ui_logger.info("curses_wrapper_with_args (KBInt): Cancelling main_task.")
                    main_task.cancel()
                    try:
                        # Await the task to allow it to process cancellation
                        loop.run_until_complete(main_task)
                    except asyncio.CancelledError:
                        main_ui_logger.info("curses_wrapper_with_args (KBInt): main_task successfully cancelled.")
                    except Exception as e_task_cancel: # pragma: no cover
                         main_ui_logger.error(f"curses_wrapper_with_args (KBInt): Error awaiting cancelled main_task: {e_task_cancel}")

            except Exception as e_curses_run: # Catch any other exception from run_until_complete
                main_ui_logger.error(f"curses_wrapper_with_args: Unhandled exception from loop.run_until_complete(main_task): {e_curses_run}", exc_info=True)
                # Similar shutdown logic as KeyboardInterrupt might be needed here if client_instance exists
                if client_instance: # pragma: no cover
                    client_instance.request_shutdown(f"Exception in curses_wrapper_with_args: {type(e_curses_run).__name__}")
                    if hasattr(client_instance, 'shutdown_complete_event') and not client_instance.shutdown_complete_event.is_set():
                        try: loop.run_until_complete(asyncio.wait_for(client_instance.shutdown_complete_event.wait(), timeout=5.0))
                        except: pass # Best effort
            finally:
                main_ui_logger.debug("curses_wrapper_with_args: Entering finally block for loop closure.")

                # Ensure main_task is cancelled if it's still around and not done (e.g. if run_until_complete exited due to an error not KeyboardInterrupt)
                if main_task and not main_task.done(): # pragma: no cover
                    main_ui_logger.warning("curses_wrapper_with_args finally: main_task still pending. Cancelling.")
                    main_task.cancel()
                    try:
                        loop.run_until_complete(main_task) # Give it a chance to process cancellation
                    except asyncio.CancelledError:
                        main_ui_logger.info("curses_wrapper_with_args finally: main_task cancelled.")
                    except Exception: # pragma: no cover
                        pass # Ignore errors during this final cancellation attempt

                if not loop.is_closed():
                    main_ui_logger.info("Closing curses event loop in curses_wrapper_with_args finally.")
                    # Add a small sleep to allow any final cleanup tasks to run
                    asyncio.run(asyncio.sleep(0.1)) # Run sleep in the current loop context
                    loop.close()
                    main_ui_logger.debug("curses_wrapper_with_args: Event loop closed.")
                else:
                    main_ui_logger.warning("curses_wrapper_with_args: Event loop was already closed when entering outer finally block.")

        curses.wrapper(curses_wrapper_with_args)

async def send_remote_command(command: str, config: AppConfig): # NEW
    ipc_port = config.ipc_port # Get port from config # NEW
    try: # NEW
        reader, writer = await asyncio.open_connection('127.0.0.1', ipc_port) # NEW
        print(f"Connecting to running tIRC instance on port {ipc_port}...") # NEW
        # Ensure the command is correctly formatted with a newline # NEW
        writer.write(command.encode() + b'\n') # NEW
        await writer.drain() # NEW
        print("Command sent successfully.") # NEW
        writer.close() # NEW
        await writer.wait_closed() # NEW
    except ConnectionRefusedError: # NEW
        print("Error: Could not connect to a running tIRC instance.", file=sys.stderr) # NEW
        print("Please ensure tIRC is running.", file=sys.stderr) # NEW
        raise # NEW

if __name__ == "__main__":
    main()
