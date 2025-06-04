# START OF MODIFIED FILE: scripts/ai_api_test_script.py
import logging
from typing import Dict, Any, TYPE_CHECKING, Optional, List, Tuple
import time
import threading
from config import HEADLESS_MAX_HISTORY
from context_manager import ChannelJoinStatus

if TYPE_CHECKING:
    from script_manager import ScriptAPIHandler

logger = logging.getLogger("pyrc.script.ai_api_test_lean")

DEFAULT_TEST_CHANNEL = "#pyrc-testing-lean"

class LeanAiApiTestScript:
    def __init__(self, api_handler: "ScriptAPIHandler"):
        self.api = api_handler
        self.tests_scheduled_this_session: bool = False
        self.test_execution_lock = threading.Lock()
        logger.info("LeanAiApiTestScript initialized")

    def load(self):
        self.api.log_info("[Lean AI Test] LeanAiApiTestScript Loading...")
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
        active_ctx_name = event_data_command.get("active_context_name", "Status")
        self.api.add_message_to_context(active_ctx_name, "Lean AI Test command executed. Re-running focused tests.", "system")

        test_channel = self.api.client_logic.context_manager._normalize_context_name(DEFAULT_TEST_CHANNEL)
        current_active_normalized = self.api.client_logic.context_manager._normalize_context_name(active_ctx_name)

        if current_active_normalized == test_channel:
            self.api.log_info(f"[Lean AI Test] Re-running focused tests on {test_channel} via command.")
            with self.test_execution_lock: # Allow re-running for manual testing
                self.tests_scheduled_this_session = False
            self.handle_channel_fully_joined_for_tests({"channel_name": test_channel})
        else:
            self.api.add_message_to_context(active_ctx_name, f"Please run /leanaitest from {test_channel}", "error")


    def handle_client_registered(self, event_data: Dict[str, Any]):
        logger.info(f"[Lean AI Test] Client registered. Auto-joining {DEFAULT_TEST_CHANNEL}")
        self.api.join_channel(DEFAULT_TEST_CHANNEL)

    def handle_channel_fully_joined_for_tests(self, event_data: Dict[str, Any]):
        channel_name = event_data.get("channel_name")
        normalized_channel_name_from_event = self.api.client_logic.context_manager._normalize_context_name(channel_name or "")
        normalized_default_test_channel = self.api.client_logic.context_manager._normalize_context_name(DEFAULT_TEST_CHANNEL)

        if not channel_name or normalized_channel_name_from_event != normalized_default_test_channel:
            logger.info(f"[Lean AI Test] Joined {channel_name}, but specifically waiting for {DEFAULT_TEST_CHANNEL} to run tests.")
            return

        logger.info(f"[Lean AI Test] Fully joined test channel: {channel_name}. Scheduling focused tests.")
        with self.test_execution_lock:
            if self.tests_scheduled_this_session:
                logger.info("[Lean AI Test] Focused tests already run/scheduled this session.")
                return
            self.tests_scheduled_this_session = True

        test_thread = threading.Timer(7.0, self._run_focused_tests, args=[channel_name]) # Slightly longer initial delay
        test_thread.daemon = True
        test_thread.start()


    def _run_focused_tests(self, channel_name: str):
        logger.info(f"[Lean AI Test] --- Starting Focused Tests on {channel_name} ---")

        time.sleep(2)
        self._test_help_system_general(channel_name)
        time.sleep(3)
        self._test_trigger_functionality(channel_name)

        logger.info(f"[Lean AI Test] --- Focused Tests on {channel_name} Completed ---")

    def _check_help_output(self, command_to_execute_with_slash: str, expected_strings: List[str], test_label: str, context_to_check: str):
        self.api.log_info(f"[Lean AI Test] Testing {test_label}: Executing '{command_to_execute_with_slash}'")
        self.api.execute_client_command(f"/window {context_to_check}")
        time.sleep(0.3)

        initial_messages_raw = self.api.get_context_messages(context_to_check)
        initial_msg_count = len(initial_messages_raw) if initial_messages_raw else 0

        self.api.execute_client_command(command_to_execute_with_slash)
        time.sleep(2.0) # Increased time for help generation

        all_messages_raw = self.api.get_context_messages(context_to_check)
        all_messages = all_messages_raw if all_messages_raw else []
        new_messages = all_messages[initial_msg_count:]

        logger.info(f"[Lean AI Test] {test_label}: New messages in '{context_to_check}' ({len(new_messages)} lines):")
        for i, msg_tuple in enumerate(new_messages):
            logger.info(f"[Lean AI Test] Help Output Line {i}: {msg_tuple[0]}")


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
            logger.error(f"[Lean AI Test] FAILED: {test_label}. Missing: {missing_strings}. First 10 new messages: {new_messages[:10]}")
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
                "Commands from script Lean Ai Api Test Script:",
                "Use /help <command> for detailed help"
            ],
            test_label="/help (general)",
            context_to_check=channel_name
        )

    def _test_trigger_functionality(self, channel_name: str):
        logger.info(f"[Lean AI Test] --- Testing Trigger Functionality ---")

        self.api.execute_client_command(f"/window {channel_name}")
        time.sleep(0.3)

        trigger_pattern_unique_part = f"activate_trigger_{int(time.time())}" # Unique phrase for activation
        activating_message_content = f"This message contains the phrase: {trigger_pattern_unique_part}."
        trigger_pattern_for_activation = rf".*\b{trigger_pattern_unique_part}\b.*"

        # This message should NOT contain trigger_pattern_unique_part
        triggered_action_message_content = f"CONFIRMED: Trigger action for phrase ending {str(time.time())[-4:]} was processed!"

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

        # Clear context before sending activating message for cleaner verification
        if hasattr(self.api, 'DEV_TEST_ONLY_clear_context_messages'):
            self.api.DEV_TEST_ONLY_clear_context_messages(channel_name)
            time.sleep(0.2)


        logger.info(f"[Lean AI Test] Trigger added (ID: {trigger_id}). Sending activating message: '{activating_message_content}'")
        self.api.send_message(channel_name, activating_message_content)
        time.sleep(4.0) # Increased sleep significantly

        messages = self.api.get_context_messages(channel_name)
        triggered_message_found = False
        client_nick_for_check = self.api.get_client_nick()

        if messages:
            logger.info(f"[Lean AI Test] Checking {len(messages)} messages in {channel_name} for trigger output...")
            for msg_tuple in reversed(messages): # Check recent first
                msg_text = msg_tuple[0]
                if isinstance(msg_text, str) and triggered_action_message_content in msg_text:
                    expected_echo_format = ""
                    if client_nick_for_check:
                       expected_echo_format = f"<{client_nick_for_check}> {triggered_action_message_content}"

                    if expected_echo_format and expected_echo_format == msg_text.strip():
                        triggered_message_found = True
                        logger.info(f"[Lean AI Test] PASSED: Trigger {trigger_id} fired. Found echoed message: '{msg_text}'")
                        break
                    elif client_nick_for_check:
                         logger.info(f"[Lean AI Test] Trigger content '{triggered_action_message_content}' found in '{msg_text}', but full echo format '<{client_nick_for_check}> ...' did not match exactly. Actual: '{msg_text.strip()}' vs Expected: '{expected_echo_format}'")

        if not triggered_message_found:
            logger.error(f"[Lean AI Test] FAILED: Trigger {trigger_id} (pattern: '{trigger_pattern_for_activation}') did NOT fire as expected OR its output message '{triggered_action_message_content}' (echoed as from '{client_nick_for_check}') not found in {channel_name}.")
            if messages:
                logger.info(f"[Lean AI Test] All messages in {channel_name} for trigger debug: {messages}")
        else: # Test disable/enable only if the first fire worked
            self.api.set_trigger_enabled(trigger_id, False)
            logger.info(f"[Lean AI Test] Disabled trigger {trigger_id}. Sending activating message again (should NOT trigger command).")
            self.api.send_message(channel_name, activating_message_content + " (disabled test)")
            time.sleep(3.0) # Allow time for potential incorrect trigger and echo

            messages_after_disabled_send = self.api.get_context_messages(channel_name) # Get all
            action_message_found_when_disabled = False
            if messages_after_disabled_send:
                # Count occurrences of triggered_action_message_content *after* the initial successful one
                count_initial_trigger = 0
                count_after_disable_trigger = 0
                initial_trigger_echo = f"<{client_nick_for_check}> {triggered_action_message}" if client_nick_for_check else triggered_action_message

                for msg_tuple in messages: # Check original list
                    if isinstance(msg_tuple[0], str) and initial_trigger_echo == msg_tuple[0].strip():
                        count_initial_trigger +=1

                for msg_tuple in messages_after_disabled_send: # Check current list
                     if isinstance(msg_tuple[0], str) and initial_trigger_echo == msg_tuple[0].strip():
                        count_after_disable_trigger +=1

                if count_after_disable_trigger > count_initial_trigger : # If more instances appeared
                    action_message_found_when_disabled = True

            if action_message_found_when_disabled:
                logger.error(f"[Lean AI Test] FAILED: Trigger {trigger_id} fired its command even when disabled.")
            else:
                logger.info(f"[Lean AI Test] PASSED: Trigger {trigger_id} did not fire command when disabled.")

            self.api.set_trigger_enabled(trigger_id, True)
            logger.info(f"[Lean AI Test] Re-enabled trigger {trigger_id}. Sending activating message again (should trigger command).")
            self.api.send_message(channel_name, activating_message_content + " (reenabled test)")
            time.sleep(3.0)

            messages_after_reenabled_send = self.api.get_context_messages(channel_name)
            action_message_found_when_reenabled = False
            if messages_after_reenabled_send:
                # Count occurrences again
                count_before_reenable_trigger = count_after_disable_trigger # from previous check
                count_after_reenable_trigger = 0
                for msg_tuple in messages_after_reenabled_send:
                     if isinstance(msg_tuple[0], str) and initial_trigger_echo == msg_tuple[0].strip():
                        count_after_reenable_trigger +=1

                if count_after_reenable_trigger > count_before_reenable_trigger:
                    action_message_found_when_reenabled = True

            if not action_message_found_when_reenabled:
                logger.error(f"[Lean AI Test] FAILED: Trigger {trigger_id} did NOT fire command when re-enabled. Counts: before={count_before_reenable_trigger}, after={count_after_reenable_trigger}")
            else:
                logger.info(f"[Lean AI Test] PASSED: Trigger {trigger_id} fired command when re-enabled.")

        logger.info(f"[Lean AI Test] Removing trigger {trigger_id}.")
        self.api.remove_trigger(trigger_id)


def get_script_instance(api_handler: "ScriptAPIHandler"):
    return LeanAiApiTestScript(api_handler)

# END OF MODIFIED FILE: scripts/ai_api_test_script.py
