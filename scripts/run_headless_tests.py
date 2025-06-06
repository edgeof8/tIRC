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

from pyrc import IRCClient_Logic
from config import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT


def setup_logging():
    """Set up logging for the test run."""
    log_dir = project_root / "logs"
    try:
        os.makedirs(log_dir, exist_ok=True)
        headless_log_file = log_dir / "headless_test_run.log"
        pyrc_log_file = log_dir / LOG_FILE

        # Configure root logger (for PyRC core logs)
        pyrc_logger = logging.getLogger("pyrc")
        pyrc_logger.setLevel(logging.DEBUG)

        # File handler for pyrc.log
        fh_pyrc = logging.handlers.RotatingFileHandler(
            pyrc_log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        fh_pyrc.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        pyrc_logger.addHandler(fh_pyrc)

        # Configure test runner logger
        test_runner_logger = logging.getLogger("pyrc.test.runner")
        test_runner_logger.setLevel(logging.INFO)

        # File handler for headless_test_run.log
        fh_headless = logging.handlers.RotatingFileHandler(
            headless_log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        fh_headless.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        test_runner_logger.addHandler(fh_headless)

        # Console handler for test_runner_logger
        ch_console = logging.StreamHandler(sys.stdout)
        ch_console.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        test_runner_logger.addHandler(ch_console)

        test_runner_logger.info("Test runner logging configured.")
        pyrc_logger.info(f"Main PyRC logging to: {pyrc_log_file}")
        test_runner_logger.info(f"Headless test runner logging to: {headless_log_file}")

    except Exception as e:
        print(f"Error setting up logging: {e}", file=sys.stderr)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        logging.getLogger("pyrc.test.runner").error(
            "File logging setup failed, using basic console logging."
        )


def main():
    """Main entry point for running headless tests."""
    setup_logging()
    logger = logging.getLogger("pyrc.test.runner")
    logger.info("Logging setup complete in main() of run_headless_tests.py")

    args = argparse.Namespace(
        server="testnet.ergo.chat",
        port=6667,
        nick=f"PyRCHTBot{int(time.time()) % 1000}",
        channel=[],  # No initial auto-join
        headless=True,
        ssl=False,
        verify_ssl_cert=False,
        password=None,
        nickserv_password=None,
        disable_script=["ai_api_test_script", "event_test_script"],
    )

    logger.info("Starting headless test run")
    logger.info(f"Effective Configuration: {vars(args)}")
    logger.info(
        "Disabled scripts: ai_api_test_script, event_test_script to prevent flood interference"
    )

    client = None
    try:
        client = IRCClient_Logic(stdscr=None, args=args)
        logger.info("IRCClient_Logic initialized successfully")

        logger.info("Network thread starting...")
        client.network_handler.start()
        logger.info("Network thread started")

        logger.info("Running main client loop...")
        client.run_main_loop()
        logger.info("Main loop completed")

    except KeyboardInterrupt:
        logger.info(
            "KeyboardInterrupt received in run_headless_tests.py. Signaling client to quit."
        )
        if client:
            client.should_quit = True
            if (
                client.network_handler
                and client.network_handler._network_thread
                and client.network_handler._network_thread.is_alive()
            ):
                logger.info(
                    "Waiting for network thread to join due to KeyboardInterrupt..."
                )
                client.network_handler._network_thread.join(timeout=3.0)
    except Exception as e:
        logger.error(f"Test run failed with error: {e}", exc_info=True)
        if client:
            client.should_quit = True
        return 1
    finally:
        logger.info("run_headless_tests.py finally block executing.")
        if (
            client
            and client.network_handler
            and client.network_handler._network_thread
            and client.network_handler._network_thread.is_alive()
        ):
            logger.info(
                "Ensuring network thread is stopped in run_headless_tests.py finally."
            )
            if client.network_handler._network_thread.is_alive():
                client.network_handler._network_thread.join(timeout=2.0)
                if client.network_handler._network_thread.is_alive():
                    logger.warning(
                        "Network thread did not join in time from run_headless_tests.py finally."
                    )
                else:
                    logger.info(
                        "Network thread joined successfully from run_headless_tests.py finally."
                    )
            else:
                logger.info(
                    "Network thread was already stopped before run_headless_tests.py finally."
                )
        else:
            logger.info(
                "No active network thread to join in run_headless_tests.py finally."
            )

    logger.info("Test run completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
