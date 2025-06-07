# START OF MODIFIED FILE: scripts/ai_api_test_script.py
import logging
from typing import Dict, Any, TYPE_CHECKING, Optional, List, Tuple
import time
import threading
import re
import os
# from pyrc_core.app_config import HEADLESS_MAX_HISTORY # Not used directly in this snippet
from pyrc_core.context_manager import ChannelJoinStatus

if TYPE_CHECKING:
    from pyrc_core.scripting.script_api_handler import ScriptAPIHandler

# Create a dedicated test logger
test_logger = logging.getLogger("pyrc.test.ai_api_test")
test_logger.setLevel(logging.INFO)

# Create logs directory if it doesn't exist
log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Create a file handler for test-specific logging
test_log_file = os.path.join(log_dir, "ai_api_test.log")
test_file_handler = logging.FileHandler(test_log_file, encoding='utf-8')
test_file_handler.setLevel(logging.INFO)

# Create a formatter for test logs
test_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
test_file_handler.setFormatter(test_formatter)

# Add the handler to the test logger
test_logger.addHandler(test_file_handler)

# Keep the original logger for compatibility
logger = logging.getLogger("pyrc.script.ai_api_test_lean")

DEFAULT_TEST_CHANNEL = "#pyrc-testing-lean"


class LeanAiApiTestScript:
    def __init__(self, api_handler: "ScriptAPIHandler"):
        self.api = api_handler
        self.tests_scheduled_this_session: bool = False
        self.test_execution_lock = threading.Lock()
        test_logger.info("=== Starting New Test Session ===")
        test_logger.info("LeanAiApiTestScript initialized")

    # --- ADDITION: Local normalizer ---
    def _normalize_channel_name_for_test(self, name: str) -> str:
        if name.startswith(("#", "&", "!", "+")):
            return name.lower()
        return name

    def load(self):
        self.api.log_info("[Lean AI Test] LeanAiApiTestScript Loading...")
        test_logger.info("Script loading...")
        self.api.register_command(
            "leanaitest",
            self.handle_leanaitest_command,
            help_info="Usage: /leanaitest - Runs focused tests.",
            aliases=["lat"],
        )
        self.api.subscribe_to_event("CLIENT_REGISTERED", self.handle_client_registered)
        self.api.subscribe_to_event(
            "CHANNEL_FULLY_JOINED", self.handle_channel_fully_joined_for_tests
        )
        test_logger.info("Script loaded successfully")

    def handle_leanaitest_command(
        self, args_str: str, event_data_command: Dict[str, Any]
    ):
        active_ctx_name = event_data_command.get("active_context_name", "Status")
        test_logger.info(f"Manual test execution requested from {active_ctx_name}")
        self.api.add_message_to_context(
            active_ctx_name,
            "Lean AI Test command executed. Re-running focused tests.",
            "system",
        )

        # --- MODIFICATION: Use local normalizer ---
        test_channel = self._normalize_channel_name_for_test(DEFAULT_TEST_CHANNEL)
        current_active_normalized = self._normalize_channel_name_for_test(active_ctx_name)

        if current_active_normalized == test_channel:
            test_logger.info(f"Re-running focused tests on {test_channel} via command")
            with self.test_execution_lock:
                self.tests_scheduled_this_session = False
            self.handle_channel_fully_joined_for_tests({"channel_name": test_channel})
        else:
            test_logger.warning(f"Test command executed from wrong channel: {active_ctx_name}")
            self.api.add_message_to_context(
                active_ctx_name, f"Please run /leanaitest from {test_channel}", "error"
            )

    def handle_client_registered(self, event_data: Dict[str, Any]):
        test_logger.info(f"Client registered. Auto-joining {DEFAULT_TEST_CHANNEL}")
        self.api.join_channel(DEFAULT_TEST_CHANNEL) # API handles normalization if needed

    def handle_channel_fully_joined_for_tests(self, event_data: Dict[str, Any]):
        channel_name = event_data.get("channel_name")
        # --- MODIFICATION: Use local normalizer ---
        normalized_channel_name_from_event = self._normalize_channel_name_for_test(channel_name or "")
        normalized_default_test_channel = self._normalize_channel_name_for_test(DEFAULT_TEST_CHANNEL)

        if (
            not channel_name
            or normalized_channel_name_from_event != normalized_default_test_channel
        ):
            test_logger.info(f"Joined {channel_name}, waiting for {DEFAULT_TEST_CHANNEL}")
            return

        test_logger.info(f"Fully joined test channel: {channel_name}. Scheduling tests")
        with self.test_execution_lock:
            if self.tests_scheduled_this_session:
                test_logger.info("Tests already run/scheduled this session")
                return
            self.tests_scheduled_this_session = True

        # --- MODIFICATION: Reduced delay for faster testing if appropriate ---
        test_thread = threading.Timer(5.0, self._run_focused_tests, args=[channel_name]) # Reduced from 7.0
        test_thread.daemon = True
        test_thread.start()

    def _run_focused_tests(self, channel_name: str):
        test_logger.info("=== Starting Test Suite ===")
        test_logger.info(f"Running tests on channel: {channel_name}")

        time.sleep(1) # Reduced from 2
        self._test_help_system_general(channel_name)
        time.sleep(2) # Reduced from 3
        self._test_trigger_functionality(channel_name)

        test_logger.info("=== Test Suite Completed ===")
        test_logger.info("All tests completed. Quitting client...")
        self.api.execute_client_command("/quit Tests completed successfully")

    def _check_help_output(
        self,
        command_to_execute_with_slash: str,
        expected_strings: List[str],
        test_label: str,
        context_to_check: str,
    ):
        test_logger.info(f"Running test: {test_label}")
        test_logger.info(f"Executing command: {command_to_execute_with_slash}")

        self.api.execute_client_command(f"/window {context_to_check}")
        time.sleep(0.3)

        initial_messages_raw = self.api.get_context_messages(context_to_check)
        initial_msg_count = len(initial_messages_raw) if initial_messages_raw else 0

        self.api.execute_client_command(command_to_execute_with_slash)
        time.sleep(2.0)

        all_messages_raw = self.api.get_context_messages(context_to_check)
        all_messages = all_messages_raw if all_messages_raw else []
        new_messages = all_messages[initial_msg_count:]

        test_logger.info(f"Received {len(new_messages)} new messages")

        all_found = True
        missing_strings = []
        if expected_strings:
            for expected_str in expected_strings:
                if not any(
                    expected_str.lower() in msg_tuple[0].lower()
                    for msg_tuple in new_messages
                ):
                    all_found = False
                    missing_strings.append(expected_str)

        if all_found:
            test_logger.info(f"PASSED: {test_label}")
        else:
            test_logger.error(f"FAILED: {test_label}")
            test_logger.error(f"Missing strings: {missing_strings}")
            test_logger.error(f"First 10 messages: {new_messages[:10]}")
        return all_found

    def _test_help_system_general(self, channel_name: str):
        test_logger.info("=== Testing Help System ===")
        self._check_help_output(
            command_to_execute_with_slash="/help",
            expected_strings=[
                "Help Categories:",
                "Core Command Categories:",
                "/help core",
                "/help channel",
                "Script Command Categories:",
                "/help script default_fun_commands",
                "/help script ai_api_test_script",
                "Use /help <category_name>",
            ],
            test_label="/help (general categories)",
            context_to_check=channel_name,
        )

        self._check_help_output(
            command_to_execute_with_slash="/help core",
            expected_strings=[
                "Core Commands:",
                "/help",
                "/quit",
                "/join",
                "/msg",
            ],
            test_label="/help core",
            context_to_check=channel_name,
        )

    def _verify_trigger_fired_and_message_sent(
        self,
        channel_name: str,
        action_message_content: str,
        client_nick_for_check: Optional[str],
        test_label: str,
        expect_trigger: bool = True,
    ) -> bool:
        messages = self.api.get_context_messages(channel_name)
        found = False
        if not messages:
            test_logger.error(f"{test_label}: No messages in context '{channel_name}'")
            return False
        if not client_nick_for_check:
            test_logger.error(f"{test_label}: Client nick is None")
            return False

        test_logger.info(f"{test_label}: Checking {len(messages)} messages for output from '{client_nick_for_check}'")

        for i in range(len(messages)):
            msg_text_full_line, _ = messages[i]
            if not isinstance(msg_text_full_line, str):
                continue

            msg_text_content_part = msg_text_full_line
            if (
                len(msg_text_full_line) > 9
                and msg_text_full_line[2] == ":"
                and msg_text_full_line[5] == ":"
            ):
                msg_text_content_part = msg_text_full_line[9:]
            msg_text_content_part = msg_text_content_part.strip()

            expected_prefix_lower = f"<{client_nick_for_check}>".lower()

            if msg_text_content_part.lower().startswith(expected_prefix_lower):
                reconstructed_message_parts = [
                    msg_text_content_part[len(expected_prefix_lower) :].strip()
                ]

                for j in range(i + 1, len(messages)):
                    next_msg_text_full_line, _ = messages[j]
                    if not isinstance(next_msg_text_full_line, str):
                        continue

                    next_msg_content_part = next_msg_text_full_line
                    if (
                        len(next_msg_text_full_line) > 9
                        and next_msg_text_full_line[2] == ":"
                        and next_msg_text_full_line[5] == ":"
                    ):
                        next_msg_content_part = next_msg_text_full_line[9:]
                    next_msg_content_part = next_msg_content_part.strip()

                    is_new_message_from_anyone = False
                    if next_msg_content_part.startswith("<"):
                        parts = next_msg_content_part.split(">", 1)
                        if len(parts) > 0 and parts[0].endswith(""):
                            is_new_message_from_anyone = True

                    if not is_new_message_from_anyone:
                        reconstructed_message_parts.append(next_msg_content_part)
                    else:
                        break

                full_reconstructed_message = " ".join(reconstructed_message_parts)

                if action_message_content == full_reconstructed_message:
                    found = True
                    if expect_trigger:
                        test_logger.info(f"{test_label}: PASSED - Found exact message: '{full_reconstructed_message}'")
                    else:
                        test_logger.error(f"{test_label}: FAILED - Trigger fired when disabled. Message: '{full_reconstructed_message}'")
                    break
                elif action_message_content in full_reconstructed_message:
                    found = True
                    if expect_trigger:
                        test_logger.info(f"{test_label}: PASSED - Found content within message: '{full_reconstructed_message}'")
                    else:
                        test_logger.error(f"{test_label}: FAILED - Trigger fired when disabled. Found content in: '{full_reconstructed_message}'")
                    break

        if not found:
            if expect_trigger:
                test_logger.error(f"{test_label}: FAILED - Expected message not found")
                if messages:
                    test_logger.error(f"Last messages: {[m[0][:100] + '...' if len(m[0]) > 100 else m[0] for m in messages[-15:]]}")
            else:
                test_logger.info(f"{test_label}: PASSED - Trigger correctly did not fire")
        return found if expect_trigger else not found

    def _test_trigger_functionality(self, channel_name: str):
        test_logger.info("=== Testing Trigger Functionality ===")

        self.api.execute_client_command(f"/window {channel_name}")
        time.sleep(0.3)

        # Test 1: Basic trigger
        timestamp_for_trigger = str(time.time())
        trigger_pattern_unique_part = f"PYRC_UNIQUE_ACTIVATION_{timestamp_for_trigger[-6:]}"
        activating_message_content = f"This message contains the phrase: {trigger_pattern_unique_part} for the test."
        trigger_pattern_for_activation = rf".*\b{re.escape(trigger_pattern_unique_part)}\b.*"
        triggered_action_message_content = f"ACTION_CONFIRMED_FOR_TRIGGER_{timestamp_for_trigger[-5:]}"

        test_logger.info(f"Adding trigger with pattern: {trigger_pattern_for_activation}")
        trigger_id = self.api.add_trigger(
            event_type="TEXT",
            pattern=trigger_pattern_for_activation,
            action_type="COMMAND",
            action_content=f"/msg {channel_name} {triggered_action_message_content}",
        )

        if trigger_id is None:
            test_logger.error("Failed to add trigger")
            return
        client_nick_for_check = self.api.get_client_nick()

        # Test trigger fire
        if hasattr(self.api, "DEV_TEST_ONLY_clear_context_messages"):
            self.api.DEV_TEST_ONLY_clear_context_messages(channel_name)
            time.sleep(0.2)

        self.api.send_message(channel_name, activating_message_content)
        time.sleep(4.5)

        initial_fire_passed = self._verify_trigger_fired_and_message_sent(
            channel_name,
            triggered_action_message_content,
            client_nick_for_check,
            f"Initial fire (ID: {trigger_id})",
            expect_trigger=True,
        )

        if not initial_fire_passed:
            test_logger.error(f"Aborting trigger tests due to initial fire failure")
            if trigger_id is not None:
                self.api.remove_trigger(trigger_id)
            return

        # Test 2: Trigger disabled
        self.api.set_trigger_enabled(trigger_id, False)
        test_logger.info(f"Testing disabled trigger {trigger_id}")

        if hasattr(self.api, "DEV_TEST_ONLY_clear_context_messages"):
            self.api.DEV_TEST_ONLY_clear_context_messages(channel_name)
            time.sleep(0.2)

        self.api.send_message(channel_name, activating_message_content + " (disabled test flag)")
        time.sleep(3.5)

        disabled_fire_passed = self._verify_trigger_fired_and_message_sent(
            channel_name,
            triggered_action_message_content,
            client_nick_for_check,
            f"Disabled fire check (ID: {trigger_id})",
            expect_trigger=False,
        )

        # Clean up
        test_logger.info(f"Removing trigger {trigger_id}")
        if trigger_id is not None:
            self.api.remove_trigger(trigger_id)


def get_script_instance(api_handler: "ScriptAPIHandler"):
    return LeanAiApiTestScript(api_handler)


# END OF MODIFIED FILE: scripts/ai_api_test_script.py
