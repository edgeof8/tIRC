# START OF MODIFIED FILE: scripts/ai_api_test_script.py
import logging
from typing import Dict, Any, TYPE_CHECKING, Optional, List, Tuple
import time
import threading
from config import HEADLESS_MAX_HISTORY # Only if _test_history_limit is re-enabled
from context_manager import ChannelJoinStatus

if TYPE_CHECKING:
    from script_manager import ScriptAPIHandler

logger = logging.getLogger("pyrc.script.ai_api_test_lean") # New logger name for clarity

DEFAULT_TEST_CHANNEL = "#pyrc-testing-lean"

class LeanAiApiTestScript:
    def __init__(self, api_handler: "ScriptAPIHandler"):
        self.api = api_handler
        self.tests_scheduled_this_session: bool = False
        self.test_execution_lock = threading.Lock()
        logger.info("LeanAiApiTestScript initialized")

    def load(self):
        self.api.log_info("[Lean AI Test] LeanAiApiTestScript Loading...")
        # Register a command so this script appears in /help output
        self.api.register_command(
            "leanaitest",
            self.handle_leanaitest_command,
            help_text="Usage: /leanaitest - Runs focused tests.",
            aliases=["lat"],
        )
        self.api.subscribe_to_event("CLIENT_REGISTERED", self.handle_client_registered)
        self.api.subscribe_to_event("CHANNEL_FULLY_JOINED", self.handle_channel_fully_joined_for_tests)
        self.api.log_info("[Lean AI Test] LeanAiApiTestScript Loaded.")

    def handle_leanaitest_command(self, args_str: str, event_data_command: Dict[str, Any]):
        active_ctx = event_data_command.get("active_context_name", "Status")
        self.api.add_message_to_context(active_ctx, "Lean AI Test command executed.", "system")
        # Optionally, re-trigger tests from here if needed for manual testing
        # self.handle_channel_fully_joined_for_tests({"channel_name": active_ctx})


    def handle_client_registered(self, event_data: Dict[str, Any]):
        logger.info(f"[Lean AI Test] Client registered. Auto-joining {DEFAULT_TEST_CHANNEL}")
        self.api.join_channel(DEFAULT_TEST_CHANNEL)

    def handle_channel_fully_joined_for_tests(self, event_data: Dict[str, Any]):
        channel_name = event_data.get("channel_name")
        if not channel_name or self.api.client_logic.context_manager._normalize_context_name(channel_name) != self.api.client_logic.context_manager._normalize_context_name(DEFAULT_TEST_CHANNEL):
            logger.info(f"[Lean AI Test] Joined {channel_name}, but waiting for {DEFAULT_TEST_CHANNEL}.")
            return

        logger.info(f"[Lean AI Test] Fully joined test channel: {channel_name}. Scheduling focused tests.")
        with self.test_execution_lock:
            if self.tests_scheduled_this_session:
                logger.info("[Lean AI Test] Focused tests already run/scheduled this session.")
                return
            self.tests_scheduled_this_session = True

        # Using a direct call instead of Timer for simplicity in a leaner script
        self._run_focused_tests(channel_name)

    def _run_focused_tests(self, channel_name: str):
        logger.info(f"[Lean AI Test] --- Starting Focused Tests on {channel_name} ---")

        time.sleep(2) # Initial settle time
        self._test_help_system_general(channel_name)
        time.sleep(3)
        self._test_trigger_functionality(channel_name)

        logger.info(f"[Lean AI Test] --- Focused Tests on {channel_name} Completed ---")
        # self.api.quit_client("Focused tests finished.") # Optionally quit after tests

    def _check_help_output(self, command_to_execute_with_slash: str, expected_strings: List[str], test_label: str, context_to_check: str):
        self.api.log_info(f"[Lean AI Test] Testing {test_label}: Executing '{command_to_execute_with_slash}'")
        # Ensure help output goes to a predictable context, like the test channel
        self.api.execute_client_command(f"/window {context_to_check}")
        time.sleep(0.2)

        initial_messages_raw = self.api.get_context_messages(context_to_check)
        initial_msg_count = len(initial_messages_raw) if initial_messages_raw else 0

        self.api.execute_client_command(command_to_execute_with_slash)
        time.sleep(1.5) # Allow more time for help to generate and display

        all_messages_raw = self.api.get_context_messages(context_to_check)
        all_messages = all_messages_raw if all_messages_raw else []
        new_messages = all_messages[initial_msg_count:]

        logger.info(f"[Lean AI Test] {test_label}: New messages in '{context_to_check}' ({len(new_messages)}): {new_messages}")

        all_found = True
        missing_strings = []
        if expected_strings:
            for expected_str in expected_strings:
                if not any(expected_str.lower() in msg_tuple[0].lower() for msg_tuple in new_messages):
                    all_found = False
                    missing_strings.append(expected_str)

        if all_found:
            logger.info(f"[Lean AI Test] PASSED: {test_label}. Found all expected strings.")
        else:
            logger.error(f"[Lean AI Test] FAILED: {test_label}. Missing: {missing_strings}. New messages: {new_messages}")
        return all_found

    def _test_help_system_general(self, channel_name: str):
        logger.info(f"[Lean AI Test] --- Testing General /help Output ---")
        self._check_help_output(
            command_to_execute_with_slash="/help",
            expected_strings=[
                "Available commands:",
                "Core Commands:",
                "Channel Commands:",
                "Information Commands:",
                "Server Commands:",
                "Ui Commands:",
                "User Commands:",
                "Utility Commands:",
                "Commands from script Default Fun Commands:",
                "Commands from script Test Script:",
                "Commands from script Lean Ai Api Test Script:", # Expecting this script's commands
                "Use /help <command> for detailed help"
            ],
            test_label="/help (general)",
            context_to_check=channel_name # Output help to the test channel
        )

    def _test_trigger_functionality(self, channel_name: str):
        logger.info(f"[Lean AI Test] --- Testing Trigger Functionality ---")

        # Ensure the test channel is active for context of trigger action
        self.api.execute_client_command(f"/window {channel_name}")
        time.sleep(0.2)

        trigger_pattern_unique_part = f"trigger_test_phrase_{int(time.time())}"
        activating_message_content = f"Let's say {trigger_pattern_unique_part} now."
        # Make pattern very specific to the activating message
        trigger_pattern_for_activation = rf".*\b{trigger_pattern_unique_part}\b.*"

        triggered_action_message_content = f"Trigger ACTION for '{trigger_pattern_unique_part}' was successful!"

        logger.info(f"[Lean AI Test] Adding trigger: Pattern='{trigger_pattern_for_activation}', Action='/msg {channel_name} {triggered_action_message_content}'")
        trigger_id = self.api.add_trigger(
            event_type="TEXT",
            pattern=trigger_pattern_for_activation,
            action_type="COMMAND",
            action_content=f"/msg {channel_name} {triggered_action_message_content}",
        )

        if trigger_id is None:
            logger.error("[Lean AI Test] FAILED: Could not add trigger.")
            return

        logger.info(f"[Lean AI Test] Trigger added (ID: {trigger_id}). Sending activating message: '{activating_message_content}'")
        self.api.send_message(channel_name, activating_message_content)
        time.sleep(3.5) # Generous time for server echo and trigger processing

        messages = self.api.get_context_messages(channel_name, count=10) # Check recent 10
        triggered_message_found = False
        client_nick_for_check = self.api.get_client_nick()

        if messages:
            logger.info(f"[Lean AI Test] Last {len(messages)} messages in {channel_name} for trigger check: {messages}")
            for msg_tuple in reversed(messages): # Check recent first
                msg_text = msg_tuple[0]
                if isinstance(msg_text, str) and triggered_action_message_content in msg_text:
                    # Check if it's an echo of our own message (sent by the trigger)
                    expected_echo_format = f"<{client_nick_for_check}> {triggered_action_message_content}"
                    if client_nick_for_check and expected_echo_format == msg_text.strip():
                        triggered_message_found = True
                        logger.info(f"[Lean AI Test] PASSED: Trigger {trigger_id} fired. Found echoed message: '{msg_text}'")
                        break
                    elif client_nick_for_check:
                         logger.info(f"[Lean AI Test] Trigger content '{triggered_action_message_content}' found in '{msg_text}', but full echo format '<{client_nick_for_check}> ...' did not match exactly.")

        if not triggered_message_found:
            logger.error(f"[Lean AI Test] FAILED: Trigger {trigger_id} did not fire as expected OR its output message was not found in {channel_name}.")

        logger.info(f"[Lean AI Test] Removing trigger {trigger_id}.")
        self.api.remove_trigger(trigger_id)


def get_script_instance(api_handler: "ScriptAPIHandler"):
    return LeanAiApiTestScript(api_handler)

# END OF MODIFIED FILE: scripts/ai_api_test_script.py
