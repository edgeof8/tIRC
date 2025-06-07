# scripts/test_headless.py
import logging
import time
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
import threading

from pyrc_core.context_manager import ChannelJoinStatus # Already imported
from pyrc_core.state_manager import ConnectionState # Import ConnectionState

logger = logging.getLogger("pyrc.test_headless_script")


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    duration: float


class HeadlessTestRunner:
    def __init__(self, api_handler): # api_handler is ScriptAPIHandler
        self.test_results: List[TestResult] = []
        self.current_test_start = 0.0
        self.api = api_handler
        self.expected_events: Dict[str, threading.Event] = {}
        self.received_event_data: Dict[str, Optional[Dict[str, Any]]] = {}

    def _normalize_channel_name_for_test(self, name: str) -> str:
        # Local helper for tests to avoid direct context_manager access
        if name.startswith(("#", "&", "!", "+")):
            return name.lower()
        return name # For nicks or other non-channel names

    def _setup_event_wait(self, unique_key: str) -> None:
        self.expected_events[unique_key] = threading.Event()
        self.received_event_data[unique_key] = None
        self.log_test_event(f"Set up event wait for '{unique_key}'")

    def _event_handler_for_test(self, unique_key: str, condition_func: Callable[[Dict[str, Any]], bool], event_data: Dict[str, Any]) -> None:
        if unique_key in self.expected_events and not self.expected_events[unique_key].is_set():
            # Check if the event_data itself is None, which can happen if an event is dispatched with None data
            if event_data is None:
                self.log_test_event(f"Received None event_data for '{unique_key}'. Condition check skipped.")
                return

            try:
                if condition_func(event_data):
                    self.log_test_event(f"Condition met for '{unique_key}' with event: {event_data.get('raw_line', str(event_data)[:100])}")
                    self.received_event_data[unique_key] = event_data
                    self.expected_events[unique_key].set()
            except Exception as e:
                self.log_test_event(f"Error in condition_func for '{unique_key}': {e}. Event data: {event_data}")


    def _await_event(self, unique_key: str, timeout: float) -> Optional[Dict[str, Any]]:
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
        self.api.unsubscribe_from_event(event_name, handler_ref)
        if unique_key in self.expected_events:
            del self.expected_events[unique_key]
        if unique_key in self.received_event_data:
            del self.received_event_data[unique_key]
        self.log_test_event(f"Cleaned up event wait for '{unique_key}'")

    def log_test_event(self, message: str):
        self.api.log_info(f"[TEST RUNNER] {message}")

    def run_connection_test(self, client_logic) -> TestResult: # client_logic is IRCClient_Logic
        self.current_test_start = time.time()
        self.log_test_event("Running connection test (verifying client is connected via CLIENT_READY event)...")

        # --- MODIFICATION: Use StateManager for connection state ---
        is_connected_state = client_logic.state_manager.get_connection_state() in [ConnectionState.CONNECTED, ConnectionState.REGISTERED, ConnectionState.READY]
        # Or more simply, use the API if it reflects the desired state
        # is_connected_api = self.api.is_connected() # Assuming this reflects being fully ready or at least registered

        if is_connected_state: # Or use is_connected_api
            return TestResult("Connection", True, "Client connected and registered (signaled by CLIENT_READY event).", time.time() - self.current_test_start)
        else:
            current_state_val = client_logic.state_manager.get_connection_state()
            current_state_name = current_state_val.name if current_state_val else "Unknown"
            return TestResult("Connection", False, f"Client not in a connected state (Current: {current_state_name}) despite CLIENT_READY event (unexpected state).", time.time() - self.current_test_start)

    def run_channel_join_test(self, client_logic) -> TestResult:
        self.current_test_start = time.time()
        test_channel = "#pyrc-testing-setup"
        # --- MODIFICATION: Use local normalizer ---
        normalized_test_channel = self._normalize_channel_name_for_test(test_channel)
        self.log_test_event(f"Running channel PART/JOIN test for {normalized_test_channel}...")

        part_key = f"part_{normalized_test_channel}"
        self._setup_event_wait(part_key)
        # --- MODIFICATION: Use API for client_nick ---
        current_client_nick = self.api.get_client_nick()
        def part_condition(data: Dict[str, Any]) -> bool:
            return (data.get("channel") == normalized_test_channel and data.get("nick") == current_client_nick)
        part_event_handler = lambda data: self._event_handler_for_test(part_key, part_condition, data)
        self.api.subscribe_to_event("PART", part_event_handler)

        self.api.part_channel(test_channel, "Testing re-join")
        part_event_data = self._await_event(part_key, timeout=10.0)
        self._cleanup_event_wait(part_key, "PART", part_event_handler)

        if not part_event_data:
            return TestResult("Channel Part", False, f"Timeout or failure waiting for self PART from {normalized_test_channel}", time.time() - self.current_test_start)

        join_key = f"join_{normalized_test_channel}"
        self._setup_event_wait(join_key)
        def join_condition(data: Dict[str, Any]) -> bool:
            return data.get("channel_name") == normalized_test_channel
        join_event_handler = lambda data: self._event_handler_for_test(join_key, join_condition, data)
        self.api.subscribe_to_event("CHANNEL_FULLY_JOINED", join_event_handler)

        self.api.join_channel(test_channel)
        self.log_test_event(f"Sent JOIN command for {normalized_test_channel}")
        join_event_data = self._await_event(join_key, timeout=15.0)
        self._cleanup_event_wait(join_key, "CHANNEL_FULLY_JOINED", join_event_handler)

        duration = time.time() - self.current_test_start
        if join_event_data:
            return TestResult("Channel Re-Join", True, f"Successfully PARTed and re-JOINed (fully) channel {normalized_test_channel}", duration)
        else:
            joined_channels = self.api.get_joined_channels()
            # --- MODIFICATION: Access context via client_logic.context_manager ---
            ctx = client_logic.context_manager.get_context(normalized_test_channel)
            ctx_status = ctx.join_status.name if ctx and hasattr(ctx, 'join_status') and ctx.join_status else "N/A"
            return TestResult("Channel Re-Join", False, f"Failed to confirm full re-join for {normalized_test_channel} within timeout. Currently joined: {joined_channels}. Context status: {ctx_status}", duration)

    def run_message_send_test(self, client_logic) -> TestResult:
        self.current_test_start = time.time()
        test_channel = "#pyrc-testing-setup"
        # --- MODIFICATION: Use local normalizer ---
        normalized_test_channel = self._normalize_channel_name_for_test(test_channel)
        timestamp_str = time.strftime("%H%M%S")
        test_message_content = f"[{timestamp_str}] Test message from headless test"

        self.log_test_event(f"Running message send test to {normalized_test_channel}...")

        msg_buffer_key = f"msg_buffer_{normalized_test_channel}_{timestamp_str}"
        self._setup_event_wait(msg_buffer_key)

        client_nick = self.api.get_client_nick()
        expected_text_in_buffer_segment = f"<{client_nick}> {test_message_content}"

        def buffer_condition(data: Dict[str, Any]) -> bool:
            return (data.get("context_name") == normalized_test_channel and
                    expected_text_in_buffer_segment in data.get("text", ""))

        buffer_event_handler = lambda data: self._event_handler_for_test(msg_buffer_key, buffer_condition, data)
        self.api.subscribe_to_event("CLIENT_MESSAGE_ADDED_TO_CONTEXT", buffer_event_handler)

        self.api.send_message(normalized_test_channel, test_message_content)
        self.log_test_event(f"Sent message to {normalized_test_channel}: {test_message_content}")

        buffer_event_data = self._await_event(msg_buffer_key, timeout=10.0)
        self._cleanup_event_wait(msg_buffer_key, "CLIENT_MESSAGE_ADDED_TO_CONTEXT", buffer_event_handler)

        duration = time.time() - self.current_test_start
        if buffer_event_data:
            return TestResult("Message Send & Buffer", True, f"Successfully verified message in buffer for {normalized_test_channel}. Event text: {buffer_event_data.get('text')}", duration)
        else:
            recent_messages = self.api.get_context_messages(normalized_test_channel, count=5)
            manual_check_passed = False
            if recent_messages:
                for msg_tuple in recent_messages:
                    if expected_text_in_buffer_segment in msg_tuple[0]:
                        manual_check_passed = True
                        break
            if manual_check_passed:
                 return TestResult("Message Send & Buffer (Manual Fallback)", True, f"Verified message in buffer for {normalized_test_channel} via manual check (event not caught).", duration)
            return TestResult("Message Send & Buffer", False, f"Failed to verify message in buffer for {normalized_test_channel} via event or manual check.", duration)


    def run_nick_change_test(self, client_logic) -> TestResult:
        self.current_test_start = time.time()
        original_nick = self.api.get_client_nick()
        if not original_nick:
            return TestResult("Nick Change", False, "Failed to get original nickname", time.time() - self.current_test_start)

        timestamp = int(time.time()) % 1000
        new_test_nick = f"PyRCNTest{timestamp}"[:9]

        self.log_test_event(f"Attempting to change nick from '{original_nick}' to '{new_test_nick}'...")

        server_nick_event_key = f"server_nick_change_{new_test_nick}"
        client_nick_event_key = f"client_state_nick_change_{new_test_nick}"
        self._setup_event_wait(server_nick_event_key)
        self._setup_event_wait(client_nick_event_key)

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

        self.api.execute_client_command(f"/nick {new_test_nick}")

        server_nick_event_data = self._await_event(server_nick_event_key, timeout=10.0)
        client_state_nick_event_data = self._await_event(client_nick_event_key, timeout=5.0) # Shorter timeout, should be quick

        self._cleanup_event_wait(server_nick_event_key, "NICK", server_nick_handler)
        self._cleanup_event_wait(client_nick_event_key, "CLIENT_NICK_CHANGED", client_state_nick_handler)

        current_nick_after_change = self.api.get_client_nick()
        passed = bool(server_nick_event_data and client_state_nick_event_data and (current_nick_after_change == new_test_nick))

        self.log_test_event(f"Attempting to revert nick to '{original_nick}'...")
        self.api.execute_client_command(f"/nick {original_nick}")

        # Wait for revert confirmation (optional, but good for test hygiene)
        revert_key = f"revert_nick_{original_nick}"
        self._setup_event_wait(revert_key)
        revert_condition = lambda data: (data.get("new_nick") == original_nick and data.get("is_self") is True)
        revert_handler = lambda data: self._event_handler_for_test(revert_key, revert_condition, data)
        self.api.subscribe_to_event("NICK", revert_handler)
        self._await_event(revert_key, timeout=10.0)
        self._cleanup_event_wait(revert_key, "NICK", revert_handler)


        duration = time.time() - self.current_test_start
        if passed:
            return TestResult("Nick Change", True, f"Successfully changed nick from '{original_nick}' to '{new_test_nick}' and verified. Reverted.", duration)
        else:
            error_details = []
            if not server_nick_event_data: error_details.append("No server NICK event")
            if not client_state_nick_event_data: error_details.append("No CLIENT_NICK_CHANGED event")
            if current_nick_after_change != new_test_nick: error_details.append(f"Nick mismatch: expected {new_test_nick}, got {current_nick_after_change}")
            return TestResult("Nick Change", False, f"Failed to verify nick change: {', '.join(error_details)}", duration)

    def run_all_tests(self, client_logic) -> List[TestResult]:
        self.log_test_event("Starting test suite...")
        self.test_results = [self.run_connection_test(client_logic)]

        if self.test_results[0].passed:
            self.log_test_event("Connection test passed, proceeding to channel join test.")
            time.sleep(2.0) # Allow time for any post-connection events to settle
            self.test_results.append(self.run_channel_join_test(client_logic))

            if self.test_results[-1].passed:
                self.log_test_event("Channel join test passed, proceeding to message send test.")
                time.sleep(2.0)
                self.test_results.append(self.run_message_send_test(client_logic))

                if self.test_results[-1].passed:
                    self.log_test_event("Message send test passed, proceeding to nick change test.")
                    time.sleep(2.0)
                    self.test_results.append(self.run_nick_change_test(client_logic))
                else:
                    self.log_test_event("Message send test FAILED, skipping nick change test.")
            else:
                self.log_test_event("Channel join test FAILED, skipping message send and nick change tests.")
        else:
            self.log_test_event("Connection test FAILED, skipping further tests.")

        passed_count = sum(1 for result in self.test_results if result.passed)
        total_count = len(self.test_results)
        self.log_test_event(f"Test suite completed: {passed_count}/{total_count} tests passed")

        for result in self.test_results:
            status = "PASSED" if result.passed else "FAILED"
            self.api.log_info(f"[TEST RUNNER] {result.name}: {status} ({result.duration:.2f}s) - {result.message}")
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

        client_logic_ref = event_data.get("client_logic_ref")
        if not client_logic_ref:
            self.api.log_error("CLIENT_READY event: No client_logic_ref in event data")
            return

        self.api.log_info("CLIENT_READY event received. Preparing to start test thread with 15s delay...")

        test_thread = threading.Thread(target=self._run_tests_after_delay, args=(client_logic_ref,))
        test_thread.daemon = True
        self.api.log_info(f"Starting test_thread: {test_thread.name}")
        test_thread.start()
        self.api.log_info("Test thread started successfully.")

    def _run_tests_after_delay(self, client_logic_ref): # client_logic_ref is IRCClient_Logic
        # Increased delay to allow server connection and initial messages to settle more reliably.
        delay_seconds = 20.0
        self.api.log_info(f"Waiting {delay_seconds}s before starting tests...")
        time.sleep(delay_seconds)
        self.api.log_info("Starting headless tests from HeadlessTestScript...")

        self.runner = HeadlessTestRunner(self.api)
        results = self.runner.run_all_tests(client_logic_ref)

        all_passed = all(result.passed for result in results)
        if all_passed:
            self.api.log_info("All headless tests passed successfully!")
            # self.api.log_info("Staying connected for 60 seconds to observe stability...")
            # time.sleep(60.0) # Reduced observation time or make configurable
        else:
            self.api.log_error("Some headless tests failed!")

        self.api.log_info("Headless tests completed. Sending QUIT.")
        self.api.send_raw("QUIT :Headless tests finished.")

        # Give a moment for QUIT to be sent before forcing client shutdown
        time.sleep(2.0)
        if hasattr(client_logic_ref, "should_quit"):
            client_logic_ref.should_quit = True
            self.api.log_info("Set client_logic_ref.should_quit = True")


def get_script_instance(api_handler):
    return HeadlessTestScript(api_handler)
