import os
import sys
import logging
import time
import socket
from pathlib import Path
import configparser
import threading
from typing import Optional, Dict, Any

# Add the parent directory to the Python path
current_file_path = Path(__file__).resolve()
project_root = current_file_path.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from pyrc import IRCClient_Logic
from config import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT, CONFIG_FILE_NAME
from dcc_transfer import DCCTransfer, DCCTransferType, DCCTransferStatus
from irc_client_logic import DummyUI

logger = logging.getLogger("pyrc.test.dcc")

def setup_test_config(config_path: str, advertised_ip: Optional[str] = None, cleanup_enabled: bool = True, cleanup_interval: int = 10) -> None:
    """Create a test configuration file with specified DCC settings."""
    config = configparser.ConfigParser()

    # Add DCC section with test settings
    config["DCC"] = {
        "enabled": "true",
        "download_dir": "test_downloads",
        "upload_dir": "test_uploads",
        "auto_accept": "false",
        "max_file_size": "1048576",  # 1MB
        "port_range_start": "1024",
        "port_range_end": "65535",
        "timeout": "30",
        "cleanup_enabled": str(cleanup_enabled).lower(),
        "cleanup_interval_seconds": str(cleanup_interval),
        "transfer_max_age_seconds": "30"  # Short max age for testing
    }

    if advertised_ip is not None:
        config["DCC"]["dcc_advertised_ip"] = advertised_ip

    # Write the config file
    with open(config_path, 'w') as f:
        config.write(f)

    logger.info(f"Created test config at {config_path} with advertised_ip={advertised_ip}, cleanup_enabled={cleanup_enabled}")

def run_dcc_ip_test(client: IRCClient_Logic, expected_ip: Optional[str] = None) -> None:
    """Test DCC IP detection/advertisement."""
    # Force reload of DCC config to ensure advertised IP is picked up
    client.dcc_manager.dcc_config = client.dcc_manager._load_dcc_config()

    actual_ip = client.dcc_manager._get_local_ip_for_ctcp()
    logger.info(f"DCC IP Test - Expected: {expected_ip}, Got: {actual_ip}")

    if expected_ip:
        assert actual_ip == expected_ip, f"Expected IP {expected_ip} but got {actual_ip}"
    else:
        # If no expected IP, verify it's a valid IP address
        try:
            socket.inet_aton(actual_ip)
            assert actual_ip != "127.0.0.1", "Auto-detected IP should not be localhost"
        except socket.error:
            assert False, f"Invalid IP address detected: {actual_ip}"

def run_dcc_cleanup_test(client: IRCClient_Logic, cleanup_enabled: bool) -> None:
    """Test DCC cleanup functionality."""
    # Force reload of DCC config to ensure cleanup settings are picked up
    client.dcc_manager.dcc_config = client.dcc_manager._load_dcc_config()

    # Create a test transfer
    transfer_id = client.dcc_manager._generate_transfer_id()
    test_transfer = DCCTransfer(
        transfer_id=transfer_id,
        transfer_type=DCCTransferType.SEND,
        peer_nick="test_peer",
        filename="test_file.txt",
        filesize=1024,
        local_filepath="/tmp/test_file.txt",
        dcc_manager_ref=client.dcc_manager
    )

    # Set status and end time
    test_transfer.status = DCCTransferStatus.COMPLETED
    test_transfer.end_time = time.monotonic() - 259300  # Make it old enough to be cleaned up

    # Add to transfers dict
    with client.dcc_manager._lock:
        client.dcc_manager.transfers[transfer_id] = test_transfer

    # Debug info before cleanup
    transfer_max_age = client.dcc_manager.dcc_config["transfer_max_age_seconds"]
    now = time.monotonic()
    logger.info(f"[DEBUG] transfer_max_age_seconds: {transfer_max_age}")
    logger.info(f"[DEBUG] now: {now}")
    logger.info(f"[DEBUG] transfer.end_time: {test_transfer.end_time}")
    logger.info(f"[DEBUG] now - end_time: {now - test_transfer.end_time}")
    print(f"[DEBUG] transfer_max_age_seconds: {transfer_max_age}")
    print(f"[DEBUG] now: {now}")
    print(f"[DEBUG] transfer.end_time: {test_transfer.end_time}")
    print(f"[DEBUG] now - end_time: {now - test_transfer.end_time}")

    # Manually trigger cleanup
    client.dcc_manager._scheduled_cleanup_task()

    # Debug info after cleanup
    with client.dcc_manager._lock:
        transfer_exists = transfer_id in client.dcc_manager.transfers
    logger.info(f"[DEBUG] transfer_exists after cleanup: {transfer_exists}")
    print(f"[DEBUG] transfer_exists after cleanup: {transfer_exists}")

    if cleanup_enabled:
        assert not transfer_exists, "Transfer should have been cleaned up"
    else:
        assert transfer_exists, "Transfer should not have been cleaned up"

def create_test_client(config_path: str) -> IRCClient_Logic:
    """Create a test client with the given config."""
    class Args:
        def __init__(self):
            self.server = 'testnet.ergo.chat'
            self.port = 6667
            self.nick = f'PyRCDCCBot{int(time.time()) % 1000}'
            self.channel = []
            self.headless = True
            self.ssl = False
            self.verify_ssl_cert = False
            self.config_file = str(config_path)

    # Create client with headless=True to ensure UI is initialized correctly
    client = IRCClient_Logic(stdscr=None, args=Args())
    return client

def main() -> int:
    """Main test runner."""
    # Setup logging
    log_dir = project_root / "logs"
    os.makedirs(log_dir, exist_ok=True)
    test_log_file = log_dir / "dcc_feature_test.log"

    # Set up logging to both file and console
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(test_log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

    print("Starting DCC feature tests")
    logger.info("Starting DCC feature tests")

    # Test cases for DCC Advertised IP
    ip_test_cases = [
        (None, "No configured IP - should auto-detect"),
        ("203.0.113.1", "Valid configured IP"),
        ("invalid.ip", "Invalid IP - should fall back to auto-detect"),
        ("", "Empty IP - should fall back to auto-detect")
    ]

    # Test cases for DCC Cleanup
    cleanup_test_cases = [
        (True, "Cleanup enabled"),
        (False, "Cleanup disabled")
    ]

    # Create test config directory
    test_config_dir = project_root / "test_configs"
    os.makedirs(test_config_dir, exist_ok=True)

    # Run IP tests
    print("\nRunning DCC Advertised IP tests")
    logger.info("Running DCC Advertised IP tests")
    for ip, description in ip_test_cases:
        print(f"\nTesting IP case: {description}")
        logger.info(f"Testing IP case: {description}")
        config_path = test_config_dir / f"dcc_ip_test_{ip or 'auto'}.ini"
        setup_test_config(str(config_path), ip)

        client = create_test_client(str(config_path))
        try:
            run_dcc_ip_test(client, ip if ip and ip != "invalid.ip" and ip != "" else None)
            print(f"IP test passed: {description}")
            logger.info(f"IP test passed: {description}")
        except AssertionError as e:
            print(f"IP test failed: {description} - {str(e)}")
            logger.error(f"IP test failed: {description} - {str(e)}")
        finally:
            client.dcc_manager.shutdown()

    # Run cleanup tests
    print("\nRunning DCC Cleanup tests")
    logger.info("Running DCC Cleanup tests")
    for cleanup_enabled, description in cleanup_test_cases:
        print(f"\nTesting cleanup case: {description}")
        logger.info(f"Testing cleanup case: {description}")
        config_path = test_config_dir / f"dcc_cleanup_test_{cleanup_enabled}.ini"
        setup_test_config(str(config_path), cleanup_enabled=cleanup_enabled)

        client = create_test_client(str(config_path))
        try:
            run_dcc_cleanup_test(client, cleanup_enabled)
            print(f"Cleanup test passed: {description}")
            logger.info(f"Cleanup test passed: {description}")
        except AssertionError as e:
            print(f"Cleanup test failed: {description} - {str(e)}")
            logger.error(f"Cleanup test failed: {description} - {str(e)}")
        finally:
            client.dcc_manager.shutdown()

    print("\nDCC feature tests completed")
    logger.info("DCC feature tests completed")
    return 0

if __name__ == "__main__":
    sys.exit(main())
