# START OF MODIFIED FILE: pyrc.py
import curses
import argparse
import time
import logging
import logging.handlers  # For RotatingFileHandler
import os  # For log directory creation
import sys # Added for console handler output
from typing import List, Optional

from config import (
    IRC_SERVER,
    IRC_PORT,
    IRC_NICK,
    IRC_CHANNELS,
    IRC_PASSWORD,
    NICKSERV_PASSWORD,
    IRC_SSL,
    DEFAULT_PORT,
    DEFAULT_SSL_PORT,
    LOG_ENABLED,
    LOG_FILE,
    LOG_LEVEL_STR, # The string representation, e.g., "INFO", "DEBUG"
    LOG_LEVEL,     # The integer value, e.g., logging.INFO, logging.DEBUG
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    BASE_DIR,
    CHANNEL_LOG_ENABLED, # Though channel log setup is mainly in IRCClient_Logic
)
from irc_client_logic import IRCClient_Logic
# UIManager is only directly used if not headless, but good to have for context
from ui_manager import UIManager


def setup_logging():
    """Set up logging for the application."""
    if not LOG_ENABLED:
        logging.disable(logging.CRITICAL + 1)  # Disable all logging levels
        print("Logging is disabled in configuration.")
        return

    # Get the root logger.
    root_logger = logging.getLogger()
    # Set the root logger level to the most verbose level we might want for any handler.
    # Individual handlers will then filter based on their own levels.
    root_logger.setLevel(LOG_LEVEL) # Capture all messages from LOG_LEVEL upwards

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Ensure log directory exists
    log_dir = os.path.join(BASE_DIR, "logs")
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
        except OSError as e:
            # Fallback if directory creation fails (e.g., permissions)
            print(f"Error creating log directory {log_dir}: {e}. Logging to project root.")
            log_dir = BASE_DIR

    log_file_path = os.path.join(log_dir, LOG_FILE)

    try:
        # File Handler - respects LOG_LEVEL from config
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(LOG_LEVEL)  # Use the configured level for this handler
        root_logger.addHandler(file_handler)

        # Console Handler - can be set to a different level for development/debugging
        # For instance, always show DEBUG on console regardless of file log level.
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(LOG_LEVEL) # Match file handler or set as desired (e.g., INFO)
        root_logger.addHandler(console_handler)

        # Specific logger level overrides if needed (example)
        # logging.getLogger("pyrc.commands.help").setLevel(logging.INFO) # Keep if frequently needed, otherwise remove or set to INFO
        # logging.getLogger("pyrc.logic").setLevel(logging.INFO)
        # logging.getLogger("pyrc.protocol").setLevel(logging.INFO)
        # logging.getLogger("pyrc.handlers.message").setLevel(logging.INFO)


        # Initial log message using a specific logger for the application itself
        app_init_logger = logging.getLogger("pyrc")
        app_init_logger.info(f"Logging initialized. Main log: {log_file_path}. Configured file LOG_LEVEL: {LOG_LEVEL_STR} ({LOG_LEVEL})")
        if CHANNEL_LOG_ENABLED:
            app_init_logger.info(f"Per-channel logging is enabled. Channel logs will be placed in: {log_dir}")

    except Exception as e:
        # Fallback to basicConfig if advanced setup fails
        print(f"Failed to initialize advanced file logging: {e}")
        logging.basicConfig(
            level=LOG_LEVEL, # Use the configured default level
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)] # Ensure console output
        )
        logging.getLogger("pyrc").error(
            f"Advanced file logging setup failed. Using basic console logging. Error: {e}"
        )


def main_curses_wrapper(stdscr, args: argparse.Namespace):
    """Wraps the main application logic for curses compatibility."""
    # Use a logger specific to this function or the main 'pyrc' logger
    main_ui_logger = logging.getLogger("pyrc.main_ui")
    main_ui_logger.info("Starting PyRC curses wrapper.")
    client = None
    try:
        # Initialize the client with the correct parameters
        client = IRCClient_Logic(
            stdscr=stdscr,
            args=args,
        )
        client.run_main_loop() # This will block until client.should_quit
    except Exception as e:
        main_ui_logger.critical(f"Critical error in main UI loop: {e}", exc_info=True)
        if client:
            client.should_quit = True # Ensure quit is signaled
    finally:
        main_ui_logger.info("Shutting down PyRC (UI mode).")
        if client:
            # Ensure should_quit is True so all threads know to stop
            client.should_quit = True
            # Network thread joining is handled within client.run_main_loop()'s finally block
            # or by network_handler.stop() if called explicitly before this.

        # UI cleanup should happen before dispatching final events if possible,
        # as curses might interfere with print statements from scripts.
        if stdscr:
            try:
                curses.curs_set(1) # Make cursor visible again
                stdscr.clear()
                stdscr.refresh()
                curses.endwin()
                main_ui_logger.debug("Curses UI shut down.")
            except Exception as e_curses_end:
                main_ui_logger.error(f"Error during curses.endwin(): {e_curses_end}")

        # Dispatch final shutdown event if client was initialized
        if client and hasattr(client, "event_manager") and client.event_manager:
            try:
                main_ui_logger.info("Dispatching CLIENT_SHUTDOWN_FINAL from main_curses_wrapper.")
                # Pass an empty dict or relevant data if needed by handlers
                client.event_manager.dispatch_client_shutdown_final(raw_line="CLIENT_SHUTDOWN_FINAL from UI wrapper")
            except Exception as e_dispatch:
                main_ui_logger.error(f"Error dispatching CLIENT_SHUTDOWN_FINAL: {e_dispatch}", exc_info=True)
        main_ui_logger.info("PyRC UI mode shutdown sequence complete.")


def parse_arguments(
    default_server: Optional[str],
    default_port: Optional[int],
    default_nick: Optional[str],
    default_channels: List[str],
    default_password: Optional[str],
    default_nickserv_password: Optional[str],
    default_ssl: Optional[bool],
) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="PyRC IRC Client")
    parser.add_argument(
        "--server",
        default=None,
        help=f"IRC server address. Overrides config. (Config default: {default_server})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"IRC server port. Overrides config. (Config default: {default_port})",
    )
    parser.add_argument(
        "--nick",
        default=None,
        help=f"IRC nickname. Overrides config. (Config default: {default_nick})",
    )
    parser.add_argument(
        "--channel",
        action="append", # Allows multiple --channel arguments
        default=None,
        help="IRC channel to join (e.g., #channel). Can be used multiple times. Overrides config channels.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="IRC server password. Overrides config.",
    )
    parser.add_argument(
        "--nickserv-password",
        default=None,
        help="NickServ password. Overrides config.",
    )
    parser.add_argument(
        "--ssl",
        action=argparse.BooleanOptionalAction, # Provides --ssl and --no-ssl
        default=None, # Will be None if not specified, allowing config to take precedence
        help=f"Use SSL/TLS. Overrides config. (Config default for default server: {default_ssl})",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (no UI)",
    )
    parser.add_argument(
        "--disable-script",
        action="append",
        default=[], # Initialize as empty list
        metavar="SCRIPT_NAME",
        help="Disable a specific script by its module name (e.g., default_fun_commands). Can be used multiple times.",
    )
    return parser.parse_args()


def main():
    # Setup logging as the very first step
    setup_logging()
    app_logger = logging.getLogger("pyrc.main_app")
    app_logger.info("Starting PyRC application.")

    # Parse arguments using defaults from config
    # Note: IRC_SSL from config might be None if not set; handle this if necessary for help string
    ssl_default_for_help = IRC_SSL if IRC_SSL is not None else False

    args = parse_arguments(
        IRC_SERVER, IRC_PORT, IRC_NICK, IRC_CHANNELS,
        IRC_PASSWORD, NICKSERV_PASSWORD, ssl_default_for_help,
    )

    # If --ssl or --no-ssl was used, it overrides config.
    # If neither was used (args.ssl is None), then IRCClient_Logic will use config's SSL setting.
    # We pass args directly to IRCClient_Logic, which will handle merging CLI args with config.

    if args.headless:
        app_logger.info("Starting PyRC in headless mode.")
        client = None
        try:
            client = IRCClient_Logic(stdscr=None, args=args)
            client.run_main_loop()
        except KeyboardInterrupt:
            app_logger.info("Keyboard interrupt received in headless main(). Signaling client to quit.")
            if client:
                client.should_quit = True
                if client.network_handler and client.network_handler._network_thread and \
                   client.network_handler._network_thread.is_alive():
                    app_logger.info("Waiting for network thread to join (headless Ctrl+C)...")
                    client.network_handler._network_thread.join(timeout=3.0)
        except Exception as e:
            app_logger.critical(f"Critical error in headless mode: {e}", exc_info=True)
            if client: client.should_quit = True
        finally:
            app_logger.info("Shutting down PyRC headless mode.")
            if client and hasattr(client, "event_manager") and client.event_manager:
                if client.network_handler and client.network_handler._network_thread and \
                   client.network_handler._network_thread.is_alive():
                    app_logger.debug("Headless main: Ensuring network thread is stopped and joined.")
                    client.network_handler.stop()
                    client.network_handler._network_thread.join(timeout=2.0)
                app_logger.info("Dispatching CLIENT_SHUTDOWN_FINAL from headless main().")
                client.event_manager.dispatch_client_shutdown_final(raw_line="CLIENT_SHUTDOWN_FINAL from headless main")
            app_logger.info("PyRC headless mode shutdown sequence complete.")
    else:
        # UI mode
        def curses_wrapper_with_args(stdscr): # Renamed to avoid conflict
            return main_curses_wrapper(stdscr, args)

        curses.wrapper(curses_wrapper_with_args)


if __name__ == "__main__":
    main()
# END OF MODIFIED FILE: pyrc.py
