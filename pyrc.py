import curses
import argparse
import time
import logging
import logging.handlers  # For RotatingFileHandler
import os  # For log directory creation
from typing import List, Optional

from config import (
    IRC_SERVER,
    IRC_PORT,
    IRC_NICK,
    IRC_CHANNELS,
    IRC_PASSWORD,
    NICKSERV_PASSWORD,
    IRC_SSL,
    DEFAULT_PORT,  # Keep for logic if config port is somehow not set
    DEFAULT_SSL_PORT,  # Keep for logic if config port is somehow not set
    LOG_ENABLED,
    LOG_FILE,
    LOG_LEVEL_STR,
    LOG_LEVEL,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    BASE_DIR,  # For creating log directory if needed
    CHANNEL_LOG_ENABLED,
)
from irc_client_logic import IRCClient_Logic
from ui_manager import UIManager

logger = logging.getLogger("pyrc")


def setup_logging():
    if not LOG_ENABLED:
        logging.disable(logging.CRITICAL + 1)  # Disable all logging
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Ensure log directory exists
    log_dir = os.path.join(BASE_DIR, "logs")
    log_file_path = ""  # Initialize to ensure it's defined
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
            log_file_path = os.path.join(log_dir, LOG_FILE)
        except OSError as e:
            print(f"Error creating log directory {log_dir}: {e}")
            log_file_path = os.path.join(BASE_DIR, LOG_FILE)  # Fallback
    else:
        log_file_path = os.path.join(log_dir, LOG_FILE)

    # Use RotatingFileHandler
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Use the 'pyrc' specific logger for this message, it will propagate to root.
        logging.getLogger("pyrc").info("Logging initialized.")
    except Exception as e:
        print(f"Failed to initialize file logging: {e}")
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        logging.getLogger("pyrc").error(
            f"File logging setup failed. Using console logging. Error: {e}"
        )

    # Channel logs will go directly into the 'log_dir' (e.g., "logs/")
    # The 'log_dir' is already created above if LOG_ENABLED.
    # No separate subdirectory for channel logs is needed as per user feedback.
    if LOG_ENABLED and CHANNEL_LOG_ENABLED:
        logger.info(
            f"Per-channel logging is enabled. Channel logs will be placed in: {log_dir}"
        )


def main_curses_wrapper(stdscr, args):
    logger.info("Starting PyRC curses wrapper.")
    client = None
    try:
        # Initialize the client with the correct parameters
        client = IRCClient_Logic(
            stdscr=stdscr,
            args=args,
            # server_addr, port, nick, etc. are now handled internally by IRCClient_Logic using args
        )
        client.run_main_loop()
    except Exception as e:
        logger.critical(f"Critical error in main loop: {e}", exc_info=True)
        if client:
            client.should_quit = True
    finally:
        logger.info("Shutting down PyRC (UI mode).")
        if client:
            client.should_quit = True  # Ensure it's set
            # Network thread joining is now handled inside client.run_main_loop's finally
            # or by the network_handler.stop() if called explicitly.
            # We just ensure client.run_main_loop() has completed.

        # UI cleanup FIRST
        if stdscr:
            try:
                curses.curs_set(1)
                stdscr.clear()
                stdscr.refresh()
                curses.endwin()
                logger.debug("Curses UI shut down.")
            except Exception as e_curses_end:
                logger.error(f"Error during curses.endwin(): {e_curses_end}")

        # THEN dispatch final shutdown event if client was initialized
        if client and hasattr(client, "script_manager"):
            try:
                logger.info(
                    "Dispatching CLIENT_SHUTDOWN_FINAL from main_curses_wrapper."
                )
                client.script_manager.dispatch_event("CLIENT_SHUTDOWN_FINAL", {})
            except Exception as e_dispatch:
                logger.error(f"Error dispatching CLIENT_SHUTDOWN_FINAL: {e_dispatch}")
        logger.info("PyRC UI mode shutdown sequence complete.")


def parse_arguments(
    default_server: Optional[str],
    default_port: Optional[int],
    default_nick: Optional[str],
    default_channels: List[str], # Remains List[str] as app_config.IRC_CHANNELS is List[str]
    default_password: Optional[str],
    default_nickserv_password: Optional[str],
    default_ssl: Optional[bool], # Changed to Optional[bool]
) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="PyRC IRC Client")
    parser.add_argument(
        "--server",
        default=None, # Was default_server
        help=f"IRC server address. Overrides config. (Config default: {default_server})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None, # Was default_port
        help=f"IRC server port. Overrides config. (Config default: {default_port})",
    )
    parser.add_argument(
        "--nick",
        default=None, # Was default_nick
        help=f"IRC nickname. Overrides config. (Config default: {default_nick})",
    )
    parser.add_argument(
        "--channel",
        action="append",
        default=None, # Was default_channels. If not used, args.channel will be None.
        help="IRC channel to join. Can be used multiple times. Overrides config channels.",
    )
    parser.add_argument(
        "--password",
        default=None, # Was default_password
        help="IRC server password. Overrides config.",
    )
    parser.add_argument(
        "--nickserv-password",
        default=None, # Was default_nickserv_password
        help="NickServ password. Overrides config.",
    )
    parser.add_argument(
        "--ssl",
        action="store_true", # If not present, args.ssl will be False.
        default=False, # Explicitly set False, help string indicates config default.
        help=f"Use SSL/TLS connection. Overrides config. (Config default for default server: {default_ssl})",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (no UI)",
    )
    parser.add_argument(
        "--disable-script",
        action="append",
        default=[],
        metavar="SCRIPT_NAME",
        help="Disable a specific script by its module name (e.g., default_fun_commands). Can be used multiple times.",
    )
    return parser.parse_args()


def main():
    setup_logging()
    logger.info("Starting PyRC.")

    args = parse_arguments(
        IRC_SERVER,
        IRC_PORT,
        IRC_NICK,
        IRC_CHANNELS,
        IRC_PASSWORD,
        NICKSERV_PASSWORD,
        IRC_SSL,
    )

    if args.headless:
        logger.info("Starting PyRC in headless mode.")
        client = None
        try:
            client = IRCClient_Logic(
                stdscr=None,
                args=args,
                # server_addr, port, nick, etc. are now handled internally by IRCClient_Logic using args
            )
            client.run_main_loop()  # This loop now blocks until should_quit

            # The main thread in headless mode simply waits for run_main_loop to finish
            # (which happens when client.should_quit is True)
            # The network thread joining is handled within run_main_loop's finally.

        except (
            KeyboardInterrupt
        ):  # This might catch Ctrl+C if run_main_loop itself doesn't
            logger.info(
                "Keyboard interrupt received in headless main(). Signaling client to quit."
            )
            if client:
                client.should_quit = True
                # Wait for the client's own shutdown mechanisms to run
                if (
                    client.network_handler
                    and client.network_handler.network_thread
                    and client.network_handler.network_thread.is_alive()
                ):
                    client.network_handler.network_thread.join(timeout=3.0)
        except Exception as e:
            logger.critical(f"Critical error in headless mode: {e}", exc_info=True)
            if client:
                client.should_quit = True
        finally:
            logger.info("Shutting down PyRC headless mode.")
            if client and hasattr(client, "script_manager"):
                # Ensure network thread is stopped and joined if not already
                if (
                    client.network_handler
                    and client.network_handler.network_thread
                    and client.network_handler.network_thread.is_alive()
                ):
                    logger.debug(
                        "Headless main: Ensuring network thread is stopped and joined."
                    )
                    client.network_handler.stop()  # Signal again just in case
                    client.network_handler.network_thread.join(timeout=2.0)

                logger.info("Dispatching CLIENT_SHUTDOWN_FINAL from headless main().")
                client.script_manager.dispatch_event("CLIENT_SHUTDOWN_FINAL", {})
            logger.info("PyRC headless mode shutdown sequence complete.")
    else:
        # UI mode - create a closure to capture args
        def curses_wrapper(stdscr):
            return main_curses_wrapper(stdscr, args)

        curses.wrapper(curses_wrapper)


if __name__ == "__main__":
    main()
