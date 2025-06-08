# START OF MODIFIED FILE: scripts/run_headless_tests.py
import os
import sys
import logging
import logging.handlers
import argparse
from pathlib import Path
import time

# Add the parent directory to the Python path
current_file_path = Path(__file__).resolve()
project_root = current_file_path.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from pyrc_core.app_config import AppConfig
from pyrc_core.client.irc_client_logic import IRCClient_Logic


def setup_logging(config: AppConfig):
    """Set up logging for the test run using the provided AppConfig."""
    log_dir = Path(config.BASE_DIR) / "logs"
    try:
        os.makedirs(log_dir, exist_ok=True)
        headless_log_file = log_dir / "headless_test_run.log"
        pyrc_log_file_path = log_dir / config.log_file

        # Configure root logger (for PyRC core logs)
        # Note: PyRC's own setup_logging in pyrc.py will also configure logging.
        # This might lead to duplicate handlers if not managed carefully.
        # For a test runner, it might be better to let PyRC's main logging take over
        # and just have this script's logger output to console or its specific file.
        # However, to ensure test runner specific logs are captured, we set it up here.

        pyrc_core_logger = logging.getLogger("pyrc") # Target the base 'pyrc' logger
        pyrc_core_logger.setLevel(logging.DEBUG) # Set PyRC core to DEBUG for detailed test logs

        # File handler for main pyrc_core.log
        # Check if handlers already exist to avoid duplication if pyrc.py's setup_logging runs first
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) and h.baseFilename == str(pyrc_log_file_path) for h in pyrc_core_logger.handlers):
            fh_pyrc = logging.handlers.RotatingFileHandler(
                pyrc_log_file_path, maxBytes=config.log_max_bytes, backupCount=config.log_backup_count, encoding="utf-8"
            )
            fh_pyrc.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
            pyrc_core_logger.addHandler(fh_pyrc)
        else:
            logging.getLogger("pyrc.test.runner").info("Main PyRC file logger already configured.")


        # Configure test runner logger
        test_runner_logger = logging.getLogger("pyrc.test.runner")
        test_runner_logger.setLevel(config.get_log_level_int_from_str(config.log_level_str, logging.INFO)) # Use config's log level

        # File handler for headless_test_run.log
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) and h.baseFilename == str(headless_log_file) for h in test_runner_logger.handlers):
            fh_headless = logging.handlers.RotatingFileHandler(
                headless_log_file, maxBytes=config.log_max_bytes, backupCount=config.log_backup_count, encoding="utf-8"
            )
            fh_headless.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
            test_runner_logger.addHandler(fh_headless)

        # Console handler for test_runner_logger
        if not any(isinstance(h, logging.StreamHandler) for h in test_runner_logger.handlers):
            ch_console = logging.StreamHandler(sys.stdout)
            ch_console.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
            test_runner_logger.addHandler(ch_console)

        test_runner_logger.info("Test runner logging configured.")
        # PyRC's own setup_logging will also log its initialization.

    except Exception as e:
        print(f"Error setting up logging in test_runner: {e}", file=sys.stderr)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        logging.getLogger("pyrc.test.runner").error(
            "Test runner file logging setup failed, using basic console logging."
        )


def main():
    """Main entry point for running headless tests."""
    # Create AppConfig instance first
    app_config_instance = AppConfig()

    # Setup logging using the AppConfig instance
    setup_logging(app_config_instance)
    logger = logging.getLogger("pyrc.test.runner") # Use the test runner specific logger

    args = argparse.Namespace(
        server="testnet.ergo.chat", # Using a test network
        port=6667,
        nick=f"PyRCHTBot{int(time.time()) % 1000}",
        channel=[],
        headless=True, # Crucial for IRCClient_Logic to use DummyUI
        ssl=False,
        # verify_ssl_cert should be taken from ServerConfig in IRCClient_Logic based on args or default
        # Forcing it here might override intended logic if ServerConfig was used.
        # Let IRCClient_Logic handle this based on its config loading.
        # verify_ssl_cert=False,
        password=None,
        nickserv_password=None,
        # Disable scripts that might interfere or auto-join channels not intended for this test
        disable_script=["ai_api_test_script", "event_test_script", "default_fun_commands", "default_random_messages"],
    )

    logger.info("Starting headless test run")
    logger.info(f"Effective Configuration for IRCClient_Logic: {vars(args)}")

    client = None
    try:
        # Pass the AppConfig instance to IRCClient_Logic
        client = IRCClient_Logic(stdscr=None, args=args, config=app_config_instance)
        logger.info("IRCClient_Logic initialized successfully for headless test.")

        # DO NOT start client.network_handler here.
        # client.run_main_loop() will handle the initial connection setup.
        # logger.info("Network thread starting...")
        # client.network_handler.start()
        # logger.info("Network thread started")

        logger.info("Running main client loop (will initiate connection)...")
        client.run_main_loop() # This will block until client.should_quit is True
        logger.info("Main client loop completed or exited.")

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received in run_headless_tests.py. Signaling client to quit.")
        if client:
            client.should_quit = True
            # Wait for network thread to clean up if it's running
            if client.network_handler and client.network_handler._network_thread and client.network_handler._network_thread.is_alive():
                logger.info("Waiting for network thread to join due to KeyboardInterrupt...")
                client.network_handler._network_thread.join(timeout=3.0)
    except Exception as e:
        logger.error(f"Test run failed with error: {e}", exc_info=True)
        if client:
            client.should_quit = True # Ensure client attempts to shut down
        # sys.exit(1) # Exit with error code
    finally:
        logger.info("run_headless_tests.py finally block executing.")
        if client and client.network_handler and client.network_handler._network_thread and client.network_handler._network_thread.is_alive():
            logger.info("Ensuring network thread is stopped in run_headless_tests.py finally.")
            client.network_handler.stop() # Gracefully stop the handler
            if client.network_handler._network_thread.is_alive(): # Check again after stop
                client.network_handler._network_thread.join(timeout=2.0)
                if client.network_handler._network_thread.is_alive():
                    logger.warning("Network thread did not join in time from run_headless_tests.py finally.")

        # Dispatch final shutdown event if client was initialized and has event_manager
        if client and hasattr(client, "event_manager") and client.event_manager:
            logger.info("Dispatching CLIENT_SHUTDOWN_FINAL from headless test runner.")
            client.event_manager.dispatch_client_shutdown_final(raw_line="CLIENT_SHUTDOWN_FINAL from headless_test_runner")

    logger.info("Headless test run script finished.")
    # sys.exit(0) # Exit with success code if not already exited by an error
class Script:
    """Dummy Script class for headless tests to allow ScriptManager to load."""
    def __init__(self, api):
        self.api = api
        self.name = "run_headless_tests"

    def load(self):
        self.api.logger.info(f"Script '{self.name}' loaded.")

    def unload(self):
        self.api.logger.info(f"Script '{self.name}' unloaded.")

def get_script_instance(api):
    return Script(api)

if __name__ == "__main__":
    # If this script is run directly, sys.exit will be called by main()
    exit_code = main()
    sys.exit(exit_code if isinstance(exit_code, int) else 0)

# END OF MODIFIED FILE: scripts/run_headless_tests.py
