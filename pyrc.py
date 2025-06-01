# pyrc.py
import curses
import argparse
import time
import logging
import logging.handlers  # For RotatingFileHandler
import os  # For log directory creation

# Import necessary configuration variables
from config import (
    IRC_SERVER,
    IRC_PORT,
    IRC_NICK,
    IRC_CHANNELS,
    IRC_PASSWORD,
    NICKSERV_PASSWORD,  # Added
    IRC_SSL,
    DEFAULT_PORT,  # Keep for logic if config port is somehow not set
    DEFAULT_SSL_PORT,  # Keep for logic if config port is somehow not set
    # Logging config
    LOG_ENABLED,
    LOG_FILE,
    LOG_LEVEL_STR, # Added for diagnostic print
    LOG_LEVEL,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    BASE_DIR,  # For creating log directory if needed
)
from irc_client_logic import IRCClient_Logic

# --- Global Logger Setup ---
logger = logging.getLogger("pyrc")


def setup_logging():
    if not LOG_ENABLED:
        logging.disable(logging.CRITICAL + 1)  # Disable all logging
        return

    # Get the root logger
    # --- Removed diagnostic print statement ---

    root_logger = logging.getLogger()
    # --- Force DEBUG level for diagnostics ---
    root_logger.setLevel(logging.DEBUG)
    # ---

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Ensure log directory exists
    log_dir = os.path.join(BASE_DIR, "logs")
    log_file_path = "" # Initialize to ensure it's defined
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
            log_file_path = os.path.join(log_dir, LOG_FILE)
        except OSError as e:
            print(f"Error creating log directory {log_dir}: {e}")
            log_file_path = os.path.join(BASE_DIR, LOG_FILE) # Fallback
    else:
        log_file_path = os.path.join(log_dir, LOG_FILE)

    # Use RotatingFileHandler
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path,
            maxBytes=LOG_MAX_BYTES, # Assuming LOG_MAX_BYTES is from config import
            backupCount=LOG_BACKUP_COUNT, # Assuming LOG_BACKUP_COUNT is from config import
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        # --- Force DEBUG level for handler ---
        file_handler.setLevel(logging.DEBUG)
        # ---
        root_logger.addHandler(file_handler)

        # Use the 'pyrc' specific logger for this message, it will propagate to root.
        logging.getLogger("pyrc").info("Logging initialized.")
    except Exception as e:
        print(f"Failed to initialize file logging: {e}")
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        # --- Force DEBUG level for console fallback ---
        console_handler.setLevel(logging.DEBUG)
        # ---
        root_logger.addHandler(console_handler)
        logging.getLogger("pyrc").error(f"File logging setup failed. Using console logging. Error: {e}")


def main_curses_wrapper(stdscr, args):
    logger.info("Starting PyRC curses wrapper.")
    # Ensure args.channel is a list, as expected by IRCClient_Logic
    channels_to_join = args.channel
    if isinstance(channels_to_join, str):
        channels_to_join = [channels_to_join]
    elif not channels_to_join:  # If it's None or empty list from config
        channels_to_join = []  # Default to empty list if no channels specified

    client = IRCClient_Logic(
        stdscr,
        args.server,
        args.port,
        args.nick,
        channels_to_join,
        args.password,
        args.nickserv_password,  # Added
        args.ssl,
    )
    try:
        client.run_main_loop()
    except Exception as e:
        logger.exception("Unhandled exception in main_curses_wrapper run_main_loop.")
        raise  # Re-raise the exception to be caught by the outer try-except
    finally:
        logger.info("Shutting down PyRC.")
        client.should_quit = True
        if client.network.network_thread and client.network.network_thread.is_alive():
            logger.debug("Joining network thread.")
            client.network.network_thread.join(timeout=1.0)
            logger.debug("Network thread joined.")
        if client.network.sock:
            try:
                logger.debug("Closing network socket.")
                client.network.sock.close()
                logger.debug("Network socket closed.")
            except Exception as e:
                logger.error(f"Error closing socket: {e}")
                pass


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
        "server",
        nargs="?",
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
    # NickServ password is not exposed as a CLI argument for now, taken from config.
    # If CLI exposure is desired, add an argument here.

    args = parser.parse_args()

    # Determine final values: CLI > Config > Fallback Defaults
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

    # Password:
    args.password = args.password if args.password is not None else cfg_password
    args.nickserv_password = cfg_nickserv_password  # Added: always use config for now

    # Final check for server (must exist)
    if not args.server:
        parser.error("A server must be specified either via CLI or config file.")

    return args


if __name__ == "__main__":
    setup_logging()  # Initialize logging first
    logger.info("PyRC application started.")

    # Pass loaded config values to parse_arguments
    # This makes them available as defaults if not overridden by CLI args
    cli_args = parse_arguments(
        IRC_SERVER,
        IRC_PORT,
        IRC_NICK,
        IRC_CHANNELS,
        IRC_PASSWORD,
        NICKSERV_PASSWORD,
        IRC_SSL,
    )

    try:
        logger.debug(f"Parsed CLI arguments: {cli_args}")
        curses.wrapper(main_curses_wrapper, cli_args)
    except curses.error as e:
        logger.error(f"Curses initialization error: {e}", exc_info=True)
        print(f"Curses initialization error: {e}")
        print("Ensure your terminal supports curses and is large enough.")
        print("(e.g., Windows Terminal, or cmd.exe with 'pip install windows-curses')")
    except Exception as e:
        logger.critical(f"An unexpected critical error occurred: {e}", exc_info=True)
        print(f"An unexpected error occurred: {e}")
        import traceback

        traceback.print_exc()  # Still print to console for immediate visibility
    finally:
        logger.info("PyRC exited.")
        print("PyRC exited.")
