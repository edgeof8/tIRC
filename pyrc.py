import curses
import argparse
import time
import logging
import logging.handlers  # For RotatingFileHandler
import os  # For log directory creation

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
            server_addr=args.server,
            port=args.port,
            nick=args.nick,
            initial_channels_raw=args.channel if args.channel else [],
            password=args.password,
            nickserv_password=args.nickserv_password,
            use_ssl=args.ssl,
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
    cfg_server,
    cfg_port,
    cfg_nick,
    cfg_channels,
    cfg_password,
    cfg_nickserv_password,
    cfg_ssl,
):
    parser = argparse.ArgumentParser(
        description="Simple Terminal IRC Client. Uses pyterm_irc_config.ini for defaults."
    )
    parser.add_argument(
        "--server",
        default=None,
        help=f"IRC server (default: {cfg_server})",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=None,  # This default means 'not specified by user'
        help=f"Server port (default from config: {cfg_port}, or auto-adjusts for SSL)",
    )
    parser.add_argument(
        "-n", "--nick", default=None, help=f"Nickname (default: {cfg_nick})"
    )

    default_channel_display = cfg_channels[0] if cfg_channels else "None"
    parser.add_argument(
        "-c",
        "--channel",
        default=None,
        help=f"Channel to join (e.g., #lobby). Overrides config (default first: {default_channel_display})",
    )
    parser.add_argument(
        "-s",
        "--ssl",
        action=argparse.BooleanOptionalAction,  # Allows --ssl and --no-ssl
        default=None,  # None means user didn't specify, so use config
        help=f"Use SSL/TLS (default: {cfg_ssl})",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Server password (optional, overrides config)",
    )
    # Add headless mode argument
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode without UI (for scripting)",
    )
    # NickServ password is not exposed as a CLI argument for now, taken from config.
    # If CLI exposure is desired, add an argument here.

    args = parser.parse_args()

    args.server = args.server if args.server is not None else cfg_server
    args.nick = args.nick if args.nick is not None else cfg_nick

    # SSL: CLI takes precedence. If not set by CLI (--ssl or --no-ssl), use config.
    if args.ssl is None:  # User did not specify --ssl or --no-ssl
        args.ssl = cfg_ssl
    # Now args.ssl is the final SSL status (True or False)

    # Port determination logic:
    # 1. If user specified --port via CLI (args.port will not be None), use that value.
    # 2. Else (user did not specify --port, so args.port is None), use the port from config (cfg_port).
    # 3. If cfg_port is also None (or invalid, though config.py should handle this),
    #    then fall back to default based on the final SSL status (args.ssl).
    if args.port is not None:
        # User specified a port via CLI, this takes highest precedence.
        # args.port already has the user-supplied value.
        pass  # Port is already set from CLI
    elif cfg_port is not None:
        # User did not specify port via CLI, so use config port.
        args.port = cfg_port
    else:
        # User did not specify port via CLI, AND config port is not set (or invalid).
        # Fallback to default based on final SSL status.
        args.port = DEFAULT_SSL_PORT if args.ssl else DEFAULT_PORT

    # Channel:
    # If CLI --channel is provided, it becomes the single channel to join.
    # Otherwise, use the list from config.
    if args.channel is not None:  # User specified a channel
        args.channel = [args.channel.lstrip("#")]
    else:  # User did not specify a channel, use config
        args.channel = cfg_channels if cfg_channels else []  # Ensure it's a list

    args.password = args.password if args.password is not None else cfg_password
    args.nickserv_password = cfg_nickserv_password

    # Final check for server (must exist)
    if not args.server:
        parser.error("A server must be specified either via CLI or config file.")

    return args


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
                server_addr=args.server,
                port=args.port,
                nick=args.nick,
                initial_channels_raw=args.channel if args.channel else [],
                password=args.password,
                nickserv_password=args.nickserv_password,
                use_ssl=args.ssl,
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
        # UI mode
        curses.wrapper(main_curses_wrapper, args)


if __name__ == "__main__":
    main()
