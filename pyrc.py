# pyrc.py
import curses
import argparse
import time
import logging
import logging.handlers
import os
import sys
import asyncio  # Import asyncio
from typing import List, Optional

# Import the new AppConfig class and other necessary components
from pyrc_core.app_config import AppConfig, ServerConfig, DEFAULT_NICK, DEFAULT_SSL_PORT, DEFAULT_PORT
from pyrc_core.client.irc_client_logic import IRCClient_Logic
from pyrc_core.client.ui_manager import UIManager


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
        console_handler.setLevel(logging.INFO)
        root_logger.addHandler(console_handler)

        app_init_logger = logging.getLogger("pyrc")
        app_init_logger.info(f"Logging initialized. Full log: {full_log_path}, Error log: {error_log_path}")
        if config.channel_log_enabled:
            app_init_logger.info(f"Per-channel logging is enabled. Channel logs will be placed in: {log_dir}")

    except Exception as e:
        print(f"Failed to initialize advanced file logging: {e}")
        logging.basicConfig(
            level=config.log_level_int,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        logging.getLogger("pyrc").error(f"Advanced file logging setup failed. Using basic console logging. Error: {e}")


async def main_curses_wrapper(stdscr, args: argparse.Namespace, config: AppConfig):
    """Wraps the main application logic for curses compatibility."""
    main_ui_logger = logging.getLogger("pyrc.main_ui")
    main_ui_logger.info("Starting PyRC curses wrapper.")
    client = None
    try:
        client = IRCClient_Logic(stdscr=stdscr, args=args, config=config)
        await client.run_main_loop()
    except Exception as e:
        main_ui_logger.critical(f"Critical error in main UI loop: {e}", exc_info=True)
        if client:
            client.should_quit.set()  # Use .set() for asyncio.Event
    finally:
        main_ui_logger.info("Shutting down PyRC (UI mode).")
        if client:
            client.should_quit.set()  # Use .set() for asyncio.Event

        if stdscr:
            try:
                curses.curs_set(1)
                stdscr.clear()
                stdscr.refresh()
                curses.endwin()
                main_ui_logger.debug("Curses UI shut down.")
            except Exception as e_curses_end:
                main_ui_logger.error(f"Error during curses.endwin(): {e_curses_end}")

        if client and hasattr(client, "event_manager") and client.event_manager:
            try:
                main_ui_logger.info("Dispatching CLIENT_SHUTDOWN_FINAL from main_curses_wrapper.")
                await client.event_manager.dispatch_client_shutdown_final(raw_line="CLIENT_SHUTDOWN_FINAL from UI wrapper")
            except Exception as e_dispatch:
                main_ui_logger.error(f"Error dispatching CLIENT_SHUTDOWN_FINAL: {e_dispatch}", exc_info=True)
        main_ui_logger.info("PyRC UI mode shutdown sequence complete.")


def parse_arguments(default_server_config: Optional[ServerConfig]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="PyRC IRC Client")

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

    return parser.parse_args()


def main():
    # Instantiate the configuration object first
    app_config = AppConfig()

    # Setup logging using the config object
    setup_logging(app_config)
    app_logger = logging.getLogger("pyrc.main_app")
    app_logger.info("Starting PyRC application.")

    # Get the default server config for argument help text
    default_server_conf = None
    if app_config.default_server_config_name:
        default_server_conf = app_config.all_server_configs.get(app_config.default_server_config_name)

    args = parse_arguments(default_server_conf)

    if args.headless:
        app_logger.info("Starting PyRC in headless mode.")
        client = None
        try:
            # For headless, we run the async main loop directly
            asyncio.run(IRCClient_Logic(stdscr=None, args=args, config=app_config).run_main_loop())
        except KeyboardInterrupt:
            app_logger.info("Keyboard interrupt received in headless main(). Signaling client to quit.")
            # If client is not explicitly available here, the run_main_loop would need to handle its own shutdown.
            # For simplicity, we'll assume the loop naturally exits on KeyboardInterrupt.
        except Exception as e:
            app_logger.critical(f"Critical error in headless mode: {e}", exc_info=True)
        finally:
            app_logger.info("PyRC headless mode shutdown sequence complete.")
    else:
        app_logger.info("Starting PyRC in UI mode.")
        # Define a synchronous wrapper for curses.wrapper
        def curses_wrapper_with_args(stdscr):
            # Create a new event loop for curses and run the async main_curses_wrapper
            # This ensures curses runs in its own context without conflicting with an outer loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(main_curses_wrapper(stdscr, args, app_config))
            finally:
                pass
                # loop.close()

        curses.wrapper(curses_wrapper_with_args)

if __name__ == "__main__":
    main()
