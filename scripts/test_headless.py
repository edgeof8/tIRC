import logging
import time
import sys
import os
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
import threading
import argparse

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from context_manager import ChannelJoinStatus

logger = logging.getLogger("pyrc.test_headless_script")


@dataclass
class TestResult:
    """Represents the result of a test."""

    name: str
    passed: bool
    message: str
    duration: float


class HeadlessTestRunner:
    """Runs tests in headless mode."""

    def __init__(self, api_handler):
        self.test_results: List[TestResult] = []
        self.current_test_start = 0.0
        self.api = api_handler
        # Add dictionaries to store event-related state
        self.expected_events: Dict[str, threading.Event] = {}
        self.received_event_data: Dict[str, Optional[Dict[str, Any]]] = {}

    def _setup_event_wait(self, unique_key: str) -> None:
        """Set up event waiting infrastructure for a specific test step.

        Args:
            unique_key: A unique identifier for this event wait operation
        """
        self.expected_events[unique_key] = threading.Event()
        self.received_event_data[unique_key] = None
        self.log_test_event(f"Set up event wait for '{unique_key}'")

    def _event_handler_for_test(self, unique_key: str, condition_func: Callable[[Dict[str, Any]], bool], event_data: Dict[str, Any]) -> None:
        """Handle an event for a specific test step.

        Args:
            unique_key: The unique identifier for this event wait operation
            condition_func: A function that takes event_data and returns True if the condition is met
            event_data: The event data received from the server
        """
        if unique_key in self.expected_events and not self.expected_events[unique_key].is_set():
            if condition_func(event_data):
                self.log_test_event(f"Condition met for '{unique_key}' with event: {event_data.get('raw_line', str(event_data)[:100])}")
                self.received_event_data[unique_key] = event_data
                self.expected_events[unique_key].set()

    def _await_event(self, unique_key: str, timeout: float) -> Optional[Dict[str, Any]]:
        """Wait for an event to occur with a timeout.

        Args:
            unique_key: The unique identifier for this event wait operation
            timeout: Maximum time to wait in seconds

        Returns:
            Optional[Dict[str, Any]]: The event data if the event occurred, None if timeout
        """
        if unique_key not in self.expected_events:
            self.log_test_event(f"Error: No event setup for key '{unique_key}'")
            return None

        event_happened = self.expected_events[unique_key].wait(timeout)
        if event_happened:
            return self.received_event_data[unique_key]
        else:
            self.log_test_event(f"Timeout waiting for event '{unique_key}'")
            return None

    def _cleanup_event_wait(self, unique_key: str, event_name: str, handler_ref: Callable) -> None:
        """Clean up event waiting infrastructure after a test step.

        Args:
            unique_key: The unique identifier for this event wait operation
            event_name: The name of the event that was being waited for
            handler_ref: The handler function that was registered
        """
        self.api.unsubscribe_from_event(event_name, handler_ref)
        if unique_key in self.expected_events:
            del self.expected_events[unique_key]
        if unique_key in self.received_event_data:
            del self.received_event_data[unique_key]
        self.log_test_event(f"Cleaned up event wait for '{unique_key}'")

    def log_test_event(self, message: str):
        """Log a test event."""
        self.api.log_info(f"[TEST RUNNER] {message}")

    def wait_for_response(self, client, timeout: float = 5.0) -> bool:
        """
        Placeholder: Wait for a generic response or a specific numeric/message part.
        Actual tests should implement more specific event subscriptions or checks.
        """
        self.log_test_event(
            f"Waiting for response (timeout: {timeout}s)... Placeholder, relies on subsequent actions."
        )
        # For now, just sleep. Real tests would subscribe to events or check context messages.
        time.sleep(min(timeout, 1.0))  # Shorter sleep for placeholder
        return True  # Placeholder, actual tests need better verification

    def handle_message(self, event_data: Dict[str, Any]):
        """Handle regular messages from the server."""
        source = event_data.get("source", "")
        target = event_data.get("target", "")
        message = event_data.get("message", "")
        self.log_test_event(f"Message from {source} to {target}: {message}")

    def run_connection_test(self, client_logic) -> TestResult:
        """Test the initial connection (verified by CLIENT_READY event)."""
        self.current_test_start = time.time()
        self.log_test_event(
            "Running connection test (verifying client is connected via CLIENT_READY event)..."
        )

        if client_logic.network_handler.connected:
            return TestResult(
                "Connection",
                True,
                "Client connected and registered (signaled by CLIENT_READY event).",
                time.time() - self.current_test_start,
            )
        else:
            # This case should ideally not happen if on_client_ready was triggered.
            return TestResult(
                "Connection",
                False,
                "Client not connected despite CLIENT_READY event (unexpected state).",
                time.time() - self.current_test_start,
            )

    def run_channel_join_test(self, client_logic) -> TestResult:
        """Test joining a channel using event-driven verification."""
        self.current_test_start = time.time()
        test_channel = "#pyrc-testing-setup"  # Use the already joined channel
        normalized_test_channel = client_logic.context_manager._normalize_context_name(test_channel)

        self.log_test_event(f"Running channel PART/JOIN test for {test_channel}...")

        # PART the channel first
        part_key = f"part_{normalized_test_channel}"
        self._setup_event_wait(part_key)

        def part_condition(data: Dict[str, Any]) -> bool:
            return (data.get("channel") == normalized_test_channel and
                   data.get("nick") == client_logic.nick)

        part_event_handler = lambda data: self._event_handler_for_test(part_key, part_condition, data)
        self.api.subscribe_to_event("PART", part_event_handler)

        self.api.part_channel(test_channel, "Testing re-join")
        part_event_data = self._await_event(part_key, timeout=10.0)
        self._cleanup_event_wait(part_key, "PART", part_event_handler)

        if not part_event_data:
            return TestResult(
                "Channel Part",
                False,
                f"Timeout or failure waiting for self PART from {test_channel}",
                time.time() - self.current_test_start
            )

        # Now JOIN
        join_key = f"join_{normalized_test_channel}"
        self._setup_event_wait(join_key)

        def join_condition(data: Dict[str, Any]) -> bool:
            return data.get("channel_name") == normalized_test_channel

        join_event_handler = lambda data: self._event_handler_for_test(join_key, join_condition, data)
        self.api.subscribe_to_event("CHANNEL_FULLY_JOINED", join_event_handler)

        self.api.join_channel(test_channel)
        self.log_test_event(f"Sent JOIN command for {test_channel}")

        join_event_data = self._await_event(join_key, timeout=15.0)
        self._cleanup_event_wait(join_key, "CHANNEL_FULLY_JOINED", join_event_handler)

        duration = time.time() - self.current_test_start
        if join_event_data:
            return TestResult(
                "Channel Re-Join",
                True,
                f"Successfully PARTed and re-JOINed (fully) channel {test_channel}",
                duration
            )
        else:
            # Get final state for error message
            joined_channels = self.api.get_joined_channels()
            ctx = client_logic.context_manager.get_context(normalized_test_channel)
            ctx_status = ctx.join_status.name if ctx and ctx.join_status else "N/A"

            return TestResult(
                "Channel Re-Join",
                False,
                f"Failed to confirm full re-join for {test_channel} within timeout. "
                f"Currently joined: {joined_channels}. Context status: {ctx_status}",
                duration
            )

    def run_message_send_test(self, client_logic) -> TestResult:
        """Test sending a message to a channel using event-driven verification."""
        self.current_test_start = time.time()
        test_channel = "#pyrc-testing-setup"  # Use the channel we know we're in
        test_channel = client_logic.context_manager._normalize_context_name(test_channel)
        timestamp = time.strftime("%H:%M:%S")
        test_message = f"[{timestamp}] Test message from headless test"

        # First verify the message was sent via PRIVMSG event
        key = f"msg_send_{test_channel}_{timestamp}"
        self._setup_event_wait(key)

        def privmsg_condition(data):
            return (
                data.get("nick") == client_logic.nickname
                and data.get("target") == test_channel
                and data.get("message") == test_message
            )

        msg_event_handler = lambda data: self._event_handler_for_test(key, privmsg_condition, data)
        client_logic.event_manager.subscribe("PRIVMSG", msg_event_handler)

        # Now verify the message appears in the buffer
        buffer_key = f"msg_buffer_{test_channel}_{timestamp}"
        self._setup_event_wait(buffer_key)

        def buffer_condition(data):
            return (
                data.get("context_name") == test_channel
                and data.get("text") == test_message
            )

        buffer_event_handler = lambda data: self._event_handler_for_test(buffer_key, buffer_condition, data)
        client_logic.event_manager.subscribe(
            "CLIENT_MESSAGE_ADDED_TO_CONTEXT",
            buffer_event_handler
        )

        # Send the message using client_logic's send_message method
        client_logic.send_message(test_channel, test_message)

        # Wait for both events with increased timeouts
        privmsg_event_data = self._await_event(key, timeout=10.0)  # Increased from 5.0
        buffer_event_data = self._await_event(buffer_key, timeout=10.0)  # Increased from 5.0

        # Cleanup event subscriptions
        self._cleanup_event_wait(key, "PRIVMSG", msg_event_handler)
        self._cleanup_event_wait(buffer_key, "CLIENT_MESSAGE_ADDED_TO_CONTEXT", buffer_event_handler)

        duration = time.time() - self.current_test_start
        if privmsg_event_data and buffer_event_data:
            return TestResult(
                name="Message Send",
                passed=True,
                message=f"Successfully verified message send and buffer for {test_channel}",
                duration=duration
            )
        else:
            error_details = []
            if not privmsg_event_data:
                error_details.append("Failed to verify message send via PRIVMSG event")
            if not buffer_event_data:
                error_details.append("Failed to verify message in buffer")
            return TestResult(
                name="Message Send",
                passed=False,
                message=f"Failed to verify message send: {', '.join(error_details)} for {test_channel}",
                duration=duration
            )

    def run_nick_change_test(self, client_logic) -> TestResult:
        """Test changing the client's nickname using event-driven verification."""
        self.current_test_start = time.time()

        # Get original nick and generate new test nick
        original_nick = self.api.get_client_nick()
        if not original_nick:
            return TestResult(
                "Nick Change",
                False,
                "Failed to get original nickname",
                time.time() - self.current_test_start
            )

        # Generate a new test nick that's guaranteed to be valid
        timestamp = int(time.time()) % 1000
        new_test_nick = f"PyRCNTest{timestamp}"

        self.log_test_event(f"Attempting to change nick from '{original_nick}' to '{new_test_nick}'...")

        # Setup event waits for both server and client state changes
        server_nick_event_key = f"server_nick_change_{new_test_nick}"
        client_nick_event_key = f"client_state_nick_change_{new_test_nick}"
        self._setup_event_wait(server_nick_event_key)
        self._setup_event_wait(client_nick_event_key)

        # Define conditions and subscribe to events
        def server_nick_condition(data: Dict[str, Any]) -> bool:
            return (data.get("old_nick") == original_nick and
                    data.get("new_nick") == new_test_nick and
                    data.get("is_self") is True)

        def client_state_nick_condition(data: Dict[str, Any]) -> bool:
            return (data.get("old_nick") == original_nick and
                    data.get("new_nick") == new_test_nick)

        server_nick_handler = lambda data: self._event_handler_for_test(server_nick_event_key, server_nick_condition, data)
        client_state_nick_handler = lambda data: self._event_handler_for_test(client_nick_event_key, client_state_nick_condition, data)

        self.api.subscribe_to_event("NICK", server_nick_handler)
        self.api.subscribe_to_event("CLIENT_NICK_CHANGED", client_state_nick_handler)

        # Execute the nick change
        self.api.execute_client_command(f"/nick {new_test_nick}")

        # Await both events
        server_nick_event_data = self._await_event(server_nick_event_key, timeout=10.0)
        client_state_nick_event_data = self._await_event(client_nick_event_key, timeout=5.0)

        # Cleanup event subscriptions
        self._cleanup_event_wait(server_nick_event_key, "NICK", server_nick_handler)
        self._cleanup_event_wait(client_nick_event_key, "CLIENT_NICK_CHANGED", client_state_nick_handler)

        # Verify results
        current_nick = self.api.get_client_nick()
        passed = bool(server_nick_event_data and client_state_nick_event_data and (current_nick == new_test_nick))

        # Attempt to change nick back
        self.log_test_event(f"Attempting to revert nick to '{original_nick}'...")
        self.api.execute_client_command(f"/nick {original_nick}")
        time.sleep(1.0)  # Small pause to allow revert command to be sent

        duration = time.time() - self.current_test_start

        if passed:
            return TestResult(
                "Nick Change",
                True,
                f"Successfully changed nick from '{original_nick}' to '{new_test_nick}' and verified both server and client state changes",
                duration
            )
        else:
            error_details = []
            if not server_nick_event_data:
                error_details.append("No server NICK event received")
            if not client_state_nick_event_data:
                error_details.append("No CLIENT_NICK_CHANGED event received")
            if current_nick != new_test_nick:
                error_details.append(f"Current nick '{current_nick}' doesn't match expected '{new_test_nick}'")

            return TestResult(
                "Nick Change",
                False,
                f"Failed to verify nick change: {', '.join(error_details)}",
                duration
            )

    def run_all_tests(self, client_logic) -> List[TestResult]:
        self.log_test_event("Starting test suite...")
        self.test_results = [self.run_connection_test(client_logic)]

        if self.test_results[0].passed:  # Only proceed if connection test passed
            self.log_test_event("Connection test passed, proceeding to channel join test.")
            time.sleep(2.0)  # Give time for connection to stabilize
            self.test_results.append(self.run_channel_join_test(client_logic))

            # Check if the last added test (channel join) passed
            if self.test_results[-1].passed:
                self.log_test_event("Channel join test passed, proceeding to message send test.")
                time.sleep(2.0)  # Give time for channel join to stabilize
                self.test_results.append(self.run_message_send_test(client_logic))

                # Check if message send test passed
                if self.test_results[-1].passed:
                    self.log_test_event("Message send test passed, proceeding to nick change test.")
                    time.sleep(2.0)  # Give time for message send to stabilize
                    self.test_results.append(self.run_nick_change_test(client_logic))
                else:
                    self.log_test_event("Message send test FAILED, skipping nick change test.")
            else:
                self.log_test_event("Channel join test FAILED, skipping message send and nick change tests.")
        else:
            self.log_test_event("Connection test FAILED, skipping further tests.")

        passed = sum(1 for result in self.test_results if result.passed)
        total = len(self.test_results)
        self.log_test_event(f"Test suite completed: {passed}/{total} tests passed")

        for result in self.test_results:
            status = "PASSED" if result.passed else "FAILED"
            self.api.log_info(
                f"[TEST RUNNER] {result.name}: {status} ({result.duration:.2f}s) - {result.message}"
            )
        return self.test_results


class HeadlessTestScript:
    def __init__(self, api_handler):
        self.api = api_handler
        self.runner: Optional[HeadlessTestRunner] = None
        self.api.log_info("HeadlessTestScript initialized.")

    def load(self):
        self.api.log_info("HeadlessTestScript loading, subscribing to CLIENT_READY.")
        self.api.subscribe_to_event("CLIENT_READY", self.on_client_ready_handler)

    def on_client_ready_handler(self, event_data: Dict[str, Any]):
        self.api.log_info("ENTERED HeadlessTestScript.on_client_ready_handler.")
        self.api.log_info(f"Event data received: {event_data}")

        client_logic_ref = event_data.get("client_logic_ref")
        if not client_logic_ref:
            self.api.log_error("CLIENT_READY event: No client_logic_ref in event data")
            return

        self.api.log_info(
            "CLIENT_READY event received by HeadlessTestScript. Preparing to start test thread with 15s delay..."
        )

        test_thread = threading.Thread(
            target=self._run_tests_after_delay, args=(client_logic_ref,)
        )
        test_thread.daemon = True
        self.api.log_info(f"Starting test_thread: {test_thread.name}")
        test_thread.start()
        self.api.log_info("Test thread started successfully.")

    def _run_tests_after_delay(self, client_logic_ref):
        time.sleep(15.0)  # Initial delay to allow connection to stabilize
        self.api.log_info("Starting headless tests from HeadlessTestScript...")

        self.runner = HeadlessTestRunner(self.api)
        results = self.runner.run_all_tests(client_logic_ref)

        all_passed = all(result.passed for result in results)
        if all_passed:
            self.api.log_info("All headless tests passed successfully!")
            self.api.log_info(
                "Staying connected for 60 seconds to observe stability..."
            )
            time.sleep(60.0)  # Stay connected longer to observe stability
        else:
            self.api.log_error("Some headless tests failed!")

        self.api.log_info("Headless tests completed. Sending QUIT.")
        self.api.send_raw("QUIT :Headless tests finished.")

        time.sleep(1.0)
        if hasattr(client_logic_ref, "should_quit"):
            client_logic_ref.should_quit = True


def get_script_instance(api_handler):
    return HeadlessTestScript(api_handler)

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Import the real client components
    from irc_client_logic import IRCClient_Logic, DummyUI
    from network_handler import NetworkHandler
    from event_manager import EventManager
    from context_manager import ContextManager
    from script_api_handler import ScriptAPIHandler
    from script_manager import ScriptManager
    import os
    import argparse

    # Create args object
    args = argparse.Namespace()
    args.server = "irc.libera.chat"
    args.port = 6667
    args.nick = "PyRCTest"
    args.ssl = False
    args.password = None
    args.nickserv_password = None
    args.channel = []
    args.disable_script = []

    # Initialize components in correct order
    ui = DummyUI()
    client_logic = IRCClient_Logic(stdscr=None, args=args)  # Pass None for stdscr in headless mode
    client_logic.ui = ui  # Set the UI for the client logic
    client_logic.initialize()  # Initialize the client logic

    # Create script manager and event manager
    script_manager = ScriptManager(client_logic, base_dir="scripts")
    event_manager = EventManager(client_logic, script_manager)
    context_manager = ContextManager(max_history_per_context=1000)
    network_handler = NetworkHandler(client_logic)

    # Set the managers in client logic
    client_logic.script_manager = script_manager
    client_logic.event_manager = event_manager
    client_logic.context_manager = context_manager
    client_logic.network_handler = network_handler

    # Create API handler for the test runner
    api_handler = ScriptAPIHandler(client_logic, script_manager, "test_headless")

    # Create test runner
    test_runner = HeadlessTestRunner(api_handler)

    # Connect to IRC server
    server = "irc.libera.chat"  # Example server
    port = 6667
    nick = "PyRCTest"
    realname = "PyRC Test Bot"

    print(f"\nConnecting to {server}:{port} as {nick}...")
    client_logic.connect(server, port)

    print("\nRunning headless tests...\n")
    results = test_runner.run_all_tests(client_logic)

    print("\nTest Results Summary:")
    print("-" * 50)
    for result in results:
        status = "PASSED" if result.passed else "FAILED"
        print(f"{result.name}: {status} ({result.duration:.2f}s)")
        print(f"Message: {result.message}")
        print("-" * 50)

    # Clean up
    client_logic.disconnect()
