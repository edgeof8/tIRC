# START OF MODIFIED FILE: scripts/ai_api_test_script.py
import logging
from typing import Dict, Any, TYPE_CHECKING, Optional, List, Tuple
import time
import threading
import re
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
            "leanaitest",  # Command name
            self.handle_leanaitest_command,
            help_text="Usage: /leanaitest - Runs focused tests.",
            aliases=["lat"],
        )
        self.api.subscribe_to_event("CLIENT_REGISTERED", self.handle_client_registered)
        self.api.subscribe_to_event(
            "CHANNEL_FULLY_JOINED", self.handle_channel_fully_joined_for_tests
        )
        self.api.log_info("[Lean AI Test] LeanAiApiTestScript Loaded.")

    def handle_leanaitest_command(
        self, args_str: str, event_data_command: Dict[str, Any]
    ):
        active_ctx_name = event_data_command.get("active_context_name", "Status")
        self.api.add_message_to_context(
            active_ctx_name,
            "Lean AI Test command executed. Re-running focused tests.",
            "system",
        )

        test_channel = self.api.client_logic.context_manager._normalize_context_name(
            DEFAULT_TEST_CHANNEL
        )
        current_active_normalized = (
            self.api.client_logic.context_manager._normalize_context_name(
                active_ctx_name
            )
        )

        if current_active_normalized == test_channel:
            self.api.log_info(
                f"[Lean AI Test] Re-running focused tests on {test_channel} via command."
            )
            with self.test_execution_lock:
                self.tests_scheduled_this_session = False
            self.handle_channel_fully_joined_for_tests({"channel_name": test_channel})
        else:
            self.api.add_message_to_context(
                active_ctx_name, f"Please run /leanaitest from {test_channel}", "error"
            )

    def handle_client_registered(self, event_data: Dict[str, Any]):
        logger.info(
            f"[Lean AI Test] Client registered. Auto-joining {DEFAULT_TEST_CHANNEL}"
        )
        self.api.join_channel(DEFAULT_TEST_CHANNEL)

    def handle_channel_fully_joined_for_tests(self, event_data: Dict[str, Any]):
        channel_name = event_data.get("channel_name")
        normalized_channel_name_from_event = (
            self.api.client_logic.context_manager._normalize_context_name(
                channel_name or ""
            )
        )
        normalized_default_test_channel = (
            self.api.client_logic.context_manager._normalize_context_name(
                DEFAULT_TEST_CHANNEL
            )
        )

        if (
            not channel_name
            or normalized_channel_name_from_event != normalized_default_test_channel
        ):
            logger.info(
                f"[Lean AI Test] Joined {channel_name}, but specifically waiting for {DEFAULT_TEST_CHANNEL} to run tests."
            )
            return

        logger.info(
            f"[Lean AI Test] Fully joined test channel: {channel_name}. Scheduling focused tests."
        )
        with self.test_execution_lock:
            if self.tests_scheduled_this_session:
                logger.info(
                    "[Lean AI Test] Focused tests already run/scheduled this session."
                )
                return
            self.tests_scheduled_this_session = True

        test_thread = threading.Timer(7.0, self._run_focused_tests, args=[channel_name])
        test_thread.daemon = True
        test_thread.start()

    def _run_focused_tests(self, channel_name: str):
        logger.info(f"[Lean AI Test] --- Starting Focused Tests on {channel_name} ---")

        time.sleep(2)
        self._test_help_system_general(channel_name)
        time.sleep(3)
        self._test_trigger_functionality(channel_name)

        logger.info(f"[Lean AI Test] --- Focused Tests on {channel_name} Completed ---")

    def _check_help_output(
        self,
        command_to_execute_with_slash: str,
        expected_strings: List[str],
        test_label: str,
        context_to_check: str,
    ):
        self.api.log_info(
            f"[Lean AI Test] Testing {test_label}: Executing '{command_to_execute_with_slash}'"
        )
        self.api.execute_client_command(f"/window {context_to_check}")
        time.sleep(0.3)

        initial_messages_raw = self.api.get_context_messages(context_to_check)
        initial_msg_count = len(initial_messages_raw) if initial_messages_raw else 0

        self.api.execute_client_command(command_to_execute_with_slash)
        time.sleep(2.0)

        all_messages_raw = self.api.get_context_messages(context_to_check)
        all_messages = all_messages_raw if all_messages_raw else []
        new_messages = all_messages[initial_msg_count:]

        logger.info(
            f"[Lean AI Test] {test_label}: New messages in '{context_to_check}' ({len(new_messages)} lines):"
        )
        # Only log all lines if DEBUG for help_command is not sufficient
        # for i, msg_tuple in enumerate(new_messages):
        #     # logger.info(f"[Lean AI Test] Help Output Line {i}: {msg_tuple[0]}")

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
            logger.info(
                f"[Lean AI Test] PASSED: {test_label}. Found all expected strings."
            )
        else:
            logger.error(
                f"[Lean AI Test] FAILED: {test_label}. Missing: {missing_strings}. First 10 new messages: {new_messages[:10]}"
            )
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
                "Commands from script Ai Api Test Script:",  # Corrected based on filename 'ai_api_test_script.py'
                "Use /help <command> for detailed help",
            ],
            test_label="/help (general)",
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
            logger.error(
                f"[Lean AI Test] {test_label}: FAILED. No messages in context '{channel_name}' to check."
            )
            return False
        if not client_nick_for_check:
            logger.error(
                f"[Lean AI Test] {test_label}: FAILED. Client nick is None, cannot verify echo."
            )
            return False

        logger.info(
            f"[Lean AI Test] {test_label}: Checking {len(messages)} messages in {channel_name} for output from '{client_nick_for_check}'. Looking for: '{action_message_content}'"
        )

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
                        logger.info(
                            f"[Lean AI Test] {test_label}: PASSED. Found exact echoed message content: '{full_reconstructed_message}'"
                        )
                    else:
                        logger.error(
                            f"[Lean AI Test] {test_label}: FAILED. Trigger fired when it should not have. Found message: '{full_reconstructed_message}'"
                        )
                    break
                elif action_message_content in full_reconstructed_message:
                    found = True
                    if expect_trigger:
                        logger.info(
                            f"[Lean AI Test] {test_label}: PASSED (lenient). Found content '{action_message_content}' within reconstructed '{full_reconstructed_message}'"
                        )
                    else:
                        logger.error(
                            f"[Lean AI Test] {test_label}: FAILED. Trigger fired when it should not have. Found content '{action_message_content}' within '{full_reconstructed_message}'"
                        )
                    break

        if not found:
            if expect_trigger:
                logger.error(
                    f"[Lean AI Test] {test_label}: FAILED. Output message '{action_message_content}' (echoed as from '{client_nick_for_check}') not found or not matched correctly in {channel_name}."
                )
                if messages:
                    last_msgs_text = [
                        m[0][:100] + ("..." if len(m[0]) > 100 else "")
                        for m in messages[-15:]
                    ]
            else:
                logger.info(
                    f"[Lean AI Test] {test_label}: PASSED. Trigger correctly did not fire when disabled (no matching message found)."
                )
        return found if expect_trigger else not found

    def _test_trigger_functionality(self, channel_name: str):
        logger.info(f"[Lean AI Test] --- Testing Trigger Functionality ---")

        self.api.execute_client_command(f"/window {channel_name}")
        time.sleep(0.3)

        timestamp_for_trigger = str(time.time())
        trigger_pattern_unique_part = (
            f"PYRC_UNIQUE_ACTIVATION_{timestamp_for_trigger[-6:]}"
        )
        activating_message_content = f"This message contains the phrase: {trigger_pattern_unique_part} for the test."
        trigger_pattern_for_activation = (
            rf".*\b{re.escape(trigger_pattern_unique_part)}\b.*"
        )

        triggered_action_message_content = f"ACTION_CONFIRMED_FOR_TRIGGER_{timestamp_for_trigger[-5:]}"  # Unique action message

        logger.info(
            f"[Lean AI Test] Adding trigger: Pattern='{trigger_pattern_for_activation}', Action='/msg {channel_name} {triggered_action_message_content}'"
        )
        trigger_id = self.api.add_trigger(
            event_type="TEXT",
            pattern=trigger_pattern_for_activation,
            action_type="COMMAND",
            action_content=f"/msg {channel_name} {triggered_action_message_content}",
        )

        if trigger_id is None:
            logger.error("[Lean AI Test] FAILED to add trigger (Initial).")
            return
        client_nick_for_check = self.api.get_client_nick()

        # Test 1: Initial trigger fire
        if hasattr(self.api, "DEV_TEST_ONLY_clear_context_messages"):
            self.api.DEV_TEST_ONLY_clear_context_messages(channel_name)
            time.sleep(0.2)
        logger.info(
            f"[Lean AI Test] Trigger added (ID: {trigger_id}). Sending activating message: '{activating_message_content}'"
        )
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
            logger.error(
                f"[Lean AI Test] Aborting further trigger tests for ID {trigger_id} due to initial fire failure."
            )
            if trigger_id is not None:
                self.api.remove_trigger(trigger_id)
            return

        # Test 2: Trigger disabled
        self.api.set_trigger_enabled(trigger_id, False)
        logger.info(
            f"[Lean AI Test] Disabled trigger {trigger_id}. Sending activating message again (should NOT trigger)."
        )
        if hasattr(self.api, "DEV_TEST_ONLY_clear_context_messages"):
            self.api.DEV_TEST_ONLY_clear_context_messages(channel_name)
            time.sleep(0.2)
        self.api.send_message(
            channel_name, activating_message_content + " (disabled test flag)"
        )
        time.sleep(3.5)

        disabled_fire_passed = self._verify_trigger_fired_and_message_sent(
            channel_name,
            triggered_action_message_content,
            client_nick_for_check,
            f"Disabled fire check (ID: {trigger_id})",
            expect_trigger=False,
        )
        if disabled_fire_passed:
            logger.info(
                f"[Lean AI Test] PASSED: Trigger {trigger_id} correctly did not fire when disabled."
            )
        else:
            logger.error(
                f"[Lean AI Test] FAILED: Trigger {trigger_id} fired its command even when disabled."
            )

        # Test 3: Trigger re-enabled
        self.api.set_trigger_enabled(trigger_id, True)
        logger.info(
            f"[Lean AI Test] Re-enabled trigger {trigger_id}. Sending activating message again (should trigger)."
        )
        if hasattr(self.api, "DEV_TEST_ONLY_clear_context_messages"):
            self.api.DEV_TEST_ONLY_clear_context_messages(channel_name)
            time.sleep(0.2)
        self.api.send_message(
            channel_name, activating_message_content + " (reenabled test flag)"
        )
        time.sleep(4.5)
        self._verify_trigger_fired_and_message_sent(
            channel_name,
            triggered_action_message_content,
            client_nick_for_check,
            f"Re-enabled fire (ID: {trigger_id})",
            expect_trigger=True,
        )

        logger.info(f"[Lean AI Test] Removing trigger {trigger_id}.")
        if trigger_id is not None:
            self.api.remove_trigger(trigger_id)


def get_script_instance(api_handler: "ScriptAPIHandler"):
    return LeanAiApiTestScript(api_handler)


# END OF MODIFIED FILE: scripts/ai_api_test_script.py
