import logging
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import threading
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
        """Test joining a channel."""
        self.current_test_start = time.time()
        test_channel = "#pyrc-testing-setup"  # Use the already joined channel
        self.log_test_event(f"Running channel PART/JOIN test for {test_channel}...")

        # PART the channel first
        self.api.log_info(f"Attempting to PART {test_channel}")
        self.api.part_channel(test_channel, "Testing re-join")
        time.sleep(2.0)  # Give server time to process PART

        # Now attempt to JOIN it back
        self.api.log_info(f"Attempting to JOIN {test_channel} again")
        self.api.join_channel(test_channel)
        self.log_test_event(f"Sent JOIN command for {test_channel}")

        # Wait for join confirmation with a timeout
        join_timeout = 15.0  # seconds
        join_confirmed = False
        start_wait_time = time.time()
        while time.time() - start_wait_time < join_timeout:
            joined_channels = self.api.get_joined_channels()
            normalized_test_channel = (
                client_logic.context_manager._normalize_context_name(test_channel)
            )

            current_joined_normalized = {
                client_logic.context_manager._normalize_context_name(ch)
                for ch in joined_channels
            }

            if normalized_test_channel in current_joined_normalized:
                # Additional check: ensure the join_status is FULLY_JOINED
                ctx = client_logic.context_manager.get_context(normalized_test_channel)
                if ctx and ctx.join_status == ChannelJoinStatus.FULLY_JOINED:
                    join_confirmed = True
                    self.api.log_info(
                        f"Channel {test_channel} confirmed in joined_channels and status is FULLY_JOINED."
                    )
                    break
                elif ctx:
                    self.api.log_info(
                        f"Channel {test_channel} in joined_channels, but status is {ctx.join_status.name}. Waiting..."
                    )
                else:
                    self.api.log_info(
                        f"Channel {test_channel} in joined_channels, but context object not found. Waiting..."
                    )
            time.sleep(0.2)  # Check every 200ms

        duration = time.time() - self.current_test_start
        if join_confirmed:
            return TestResult(
                "Channel Re-Join",
                True,
                f"Successfully PARTed and re-JOINed channel {test_channel}",
                duration,
            )
        else:
            joined_channels_at_timeout = self.api.get_joined_channels()
            ctx_status_at_timeout = "N/A"
            ctx_at_timeout = client_logic.context_manager.get_context(
                client_logic.context_manager._normalize_context_name(test_channel)
            )
            if ctx_at_timeout and ctx_at_timeout.join_status:
                ctx_status_at_timeout = ctx_at_timeout.join_status.name

            return TestResult(
                "Channel Re-Join",
                False,
                f"Failed to confirm re-join for channel {test_channel} within {join_timeout}s. Currently joined: {joined_channels_at_timeout}. Context status: {ctx_status_at_timeout}",
                duration,
            )

    def run_message_send_test(self, client_logic) -> TestResult:
        """Test sending a message to a channel."""
        self.current_test_start = time.time()
        test_channel = "#pyrc-testing-setup"  # Use the channel we know we're in
        test_message = f"Automated test message {int(time.time())}"

        self.log_test_event(f"Running message send test to {test_channel}...")
        self.api.send_message(test_channel, test_message)
        self.log_test_event(f"Sent message to {test_channel}: {test_message}")

        # Wait for message to be processed and potentially echoed
        time.sleep(2.0)

        message_found = False
        verification_details = "Verification not attempted."

        try:
            # Get recent messages from the channel
            recent_messages = self.api.get_context_messages(test_channel, count=10)
            capabilities = self.api.get_server_capabilities()
            client_nick = self.api.get_client_nick()

            # Determine what message format to look for based on echo-message capability
            if "echo-message" in capabilities:
                expected_message = test_message
                verification_details = (
                    f"Checking for '{expected_message}' (echo-message active)"
                )
            else:
                expected_message = f"<{client_nick}> {test_message}"
                verification_details = (
                    f"Checking for '{expected_message}' (echo-message not active)"
                )

            if recent_messages:
                self.log_test_event(
                    f"Recent messages in {test_channel}: {recent_messages}"
                )
                for msg_tuple in recent_messages:
                    if isinstance(msg_tuple, tuple) and len(msg_tuple) > 0:
                        msg_text = msg_tuple[0]
                        if expected_message in msg_text:
                            message_found = True
                            verification_details += " Message found in buffer."
                            break

                if not message_found:
                    verification_details += " Message not found in buffer."
            else:
                verification_details = f"No messages found in {test_channel} buffer."
                self.log_test_event(verification_details)

        except Exception as e:
            self.log_test_event(f"Error during message verification: {e}")
            verification_details = f"Exception during verification: {e}"

        duration = time.time() - self.current_test_start
        if message_found:
            return TestResult(
                "Message Send",
                True,
                f"Successfully sent and verified message in {test_channel}. {verification_details}",
                duration,
            )
        else:
            return TestResult(
                "Message Send",
                False,
                f"Failed to verify sent message in {test_channel}. {verification_details}",
                duration,
            )

    def run_all_tests(self, client_logic) -> List[TestResult]:
        self.log_test_event("Starting test suite (Connection Test Only)...")
        self.test_results = [self.run_connection_test(client_logic)]

        # Comment out additional tests for now to isolate connection issues
        # if self.test_results[0].passed: # Only proceed if connection test passed
        #     self.test_results.append(self.run_channel_join_test(client_logic))
        #     if self.test_results[-1].passed: # If join passed
        #          self.test_results.append(self.run_message_send_test(client_logic))

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
