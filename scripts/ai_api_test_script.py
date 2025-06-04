# START OF MODIFIED FILE: scripts/ai_api_test_script.py
import logging
from typing import Dict, Any, TYPE_CHECKING, Optional, List, Tuple
import time
import threading
from config import HEADLESS_MAX_HISTORY
from context_manager import ChannelJoinStatus

if TYPE_CHECKING:
    from script_manager import ScriptAPIHandler

logger = logging.getLogger("pyrc.script.ai_api_test")

TEST_HISTORY_MESSAGES_COUNT = 3
DEFAULT_TEST_CHANNEL = "#pyrc-testing-auto"

class AiApiTestScript:
    def __init__(self, api_handler: "ScriptAPIHandler"):
        self.api = api_handler
        self.original_nick_for_test: Optional[str] = None
        self.initial_original_nick_for_test: Optional[str] = None
        self.tests_scheduled_this_session: bool = False
        self.last_connection_time: float = 0.0
        self.test_execution_lock = threading.Lock()
        logger.info("AIAPITestScript initialized")

    def load(self):
        self.api.log_info("[AI Test] AiApiTestScript Loading...")
        self.api.register_command(
            "aitest",
            self.handle_aitest_command,
            help_text="Usage: /aitest <subcommand> [args] - Tests AI API features.",
            aliases=["at"],
        )
        self.api.subscribe_to_event("CLIENT_CONNECTED", self.handle_client_connected)
        self.api.subscribe_to_event("CLIENT_REGISTERED", self.handle_client_registered)
        self.api.subscribe_to_event("CHANNEL_FULLY_JOINED", self.handle_channel_fully_joined_for_tests)

        self.api.subscribe_to_event("JOIN", self.handle_join_event_for_logging_only)
        self.api.subscribe_to_event("PRIVMSG", self.handle_privmsg)
        self.api.subscribe_to_event("NOTICE", self.handle_notice)
        self.api.subscribe_to_event("RAW_IRC_NUMERIC", self.handle_raw_numeric)
        self.api.subscribe_to_event(
            "CHANNEL_MODE_APPLIED", self.handle_channel_mode_applied
        )
        self.api.subscribe_to_event(
            "CLIENT_NICK_CHANGED", self.handle_client_nick_changed
        )
        self.api.log_info(
            "[AI Test] AiApiTestScript Loaded and events/commands registered."
        )

    def handle_client_connected(self, event_data: Dict[str, Any]):
        self.api.log_info(
            f"[AI Test] Client connected to server. Event data: {event_data}"
        )
        with self.test_execution_lock:
            self.tests_scheduled_this_session = False
        self.last_connection_time = time.time() # Record connection time
        server_info = self.api.get_server_info()
        self.api.log_info(f"[AI Test] Server info: {server_info}")
        capabilities = self.api.get_server_capabilities()
        self.api.log_info(f"[AI Test] Server capabilities (on connect): {capabilities}")

        current_nick = self.api.get_client_nick()
        self.original_nick_for_test = current_nick
        self.initial_original_nick_for_test = current_nick
        self.api.log_info(f"[AI Test] Initial nicks set: original_nick_for_test='{self.original_nick_for_test}', initial_original_nick_for_test='{self.initial_original_nick_for_test}'")


    def handle_client_registered(self, event_data: Dict[str, Any]):
        self.api.log_info(f"[AI Test] Client registered (001 received). Event data: {event_data}")

        confirmed_nick = event_data.get("nick")
        if confirmed_nick:
            self.original_nick_for_test = confirmed_nick
            if not self.initial_original_nick_for_test:
                 self.initial_original_nick_for_test = confirmed_nick
            self.api.log_info(f"[AI Test] Nicks updated after 001: original_nick_for_test='{self.original_nick_for_test}', initial_original_nick_for_test='{self.initial_original_nick_for_test}'")

        threading.Timer(10.0, self._test_nick_change_sequence).start()

        if not self.api.client_logic.initial_channels_list:
            self.api.log_info(f"[AI Test] No initial channels to auto-join. Attempting to join default test channel: {DEFAULT_TEST_CHANNEL}")
            self.api.join_channel(DEFAULT_TEST_CHANNEL)
        else:
            # Auto-join for initial channels is handled by RegistrationHandler.
            # We just wait for CHANNEL_FULLY_JOINED.
            self.api.log_info(f"[AI Test] Initial channels {self.api.client_logic.initial_channels_list} will be auto-joined. Waiting for CHANNEL_FULLY_JOINED.")


    def handle_channel_fully_joined_for_tests(self, event_data: Dict[str, Any]):
        channel_name = event_data.get("channel_name")
        if not channel_name:
            self.api.log_warning("[AI Test] CHANNEL_FULLY_JOINED event missing channel_name.")
            return

        self.api.log_info(f"[AI Test] Event CHANNEL_FULLY_JOINED received for {channel_name}.")

        with self.test_execution_lock:
            if self.tests_scheduled_this_session:
                self.api.log_info(f"[AI Test] Tests already run/scheduled this session. Ignoring for {channel_name}.")
                return

            # Check debounce only if we are considering running tests.
            # The first time, we don't need a long debounce from connection,
            # just a short delay after full join.
            # Subsequent attempts (if any, due to multiple channels) might use a longer debounce.
            # For now, let's assume tests run on the *first* channel that becomes fully joined.

            # Simplified: run tests on the first channel that reports fully joined for this session.
            self.api.log_info(f"[AI Test] Scheduling tests for channel {channel_name} after 5s delay (first fully joined channel this session).")

            test_thread = threading.Timer(5.0, self._run_tests_on_channel, args=[channel_name])
            test_thread.daemon = True
            test_thread.start()
            self.tests_scheduled_this_session = True # Mark that tests have been scheduled for this session


    def _run_tests_on_channel(self, channel_name: str):
        self.api.log_info(f"[AI Test] Preparing to run tests on channel {channel_name}")

        normalized_test_channel = self.api.client_logic.context_manager._normalize_context_name(channel_name)

        # Double-check status before running, though the event should guarantee it.
        ctx_info = self.api.get_context_info(normalized_test_channel)
        is_fully_joined = False
        if ctx_info and ctx_info.get("type") == "channel":
            join_status_str = ctx_info.get("join_status")
            if join_status_str == ChannelJoinStatus.FULLY_JOINED.name:
                is_fully_joined = True

        if not is_fully_joined:
            self.api.log_error(f"[AI Test] Pre-test check failed: Not fully joined to {normalized_test_channel}. Status: {ctx_info.get('join_status') if ctx_info else 'N/A'}. Aborting tests.")
            return

        self.api.log_info(f"[AI Test] Confirmed fully joined to {normalized_test_channel}. Proceeding with tests.")

        self.api.log_info("[AI Test] Starting _test_message_tags_and_triggers...")
        self._test_message_tags_and_triggers(normalized_test_channel)
        time.sleep(5.0)

        self.api.log_info("[AI Test] Starting _test_channel_modes...")
        self._test_channel_modes(normalized_test_channel)
        time.sleep(5.0)

        self.api.log_info("[AI Test] Starting _test_history_limit...")
        self._test_history_limit(normalized_test_channel)

        self.api.log_info(f"[AI Test] All scheduled sub-tests for {normalized_test_channel} have been completed.")


    def _test_nick_change_sequence(self):
        if not self.initial_original_nick_for_test:
            current_nick = self.api.get_client_nick()
            if not current_nick:
                self.api.log_error("[AI Test] Nick not available for nick change test.")
                return
            self.initial_original_nick_for_test = current_nick
            self.api.log_info(f"[AI Test] Initial original nick set to '{current_nick}' for nick change test.")

        new_nick = f"{self.initial_original_nick_for_test}_test"
        self.api.log_info(f"[AI Test] Attempting to change nick to: {new_nick}")
        self.api.set_nick(new_nick)
        threading.Timer(7.0, self._revert_nick_change).start()

    def _revert_nick_change(self):
        if self.initial_original_nick_for_test:
            self.api.log_info(
                f"[AI Test] Attempting to revert nick to initial: {self.initial_original_nick_for_test}"
            )
            self.api.set_nick(self.initial_original_nick_for_test)
        else:
            self.api.log_error(
                "[AI Test] Cannot revert nick, initial_original_nick_for_test was not set."
            )

    def _test_message_tags_and_triggers(self, channel_name: str):
        test_msg = "Testing message tags with echo-message capability from PyRC"
        self.api.log_info(
            f"[AI Test] Sending test message to {channel_name}: {test_msg}"
        )
        self.api.send_message(channel_name, test_msg)
        time.sleep(1.5)

        self.api.log_info("[AI Test] Testing trigger API...")
        trigger_pattern = f"secret word {int(time.time())}"

        trigger_id = self.api.add_trigger(
            event_type="TEXT",
            pattern=rf".*{trigger_pattern}.*",
            action_type="COMMAND",
            action_content=f"/msg {channel_name} Trigger for '{trigger_pattern}' fired!",
        )

        if trigger_id is not None:
            self.api.log_info(
                f"[AI Test] Added trigger with ID: {trigger_id}, pattern: '{trigger_pattern}'"
            )
            self.api.send_message(
                channel_name, f"The {trigger_pattern} has been spoken."
            )
            time.sleep(1.5)

            self.api.set_trigger_enabled(trigger_id, False)
            self.api.log_info(
                f"[AI Test] Disabled trigger {trigger_id}. Sending message again (should not trigger)."
            )
            self.api.send_message(
                channel_name,
                f"Another message with {trigger_pattern}, should be ignored.",
            )
            time.sleep(1.5)
            self.api.set_trigger_enabled(trigger_id, True)
            self.api.log_info(
                f"[AI Test] Enabled trigger {trigger_id}. Sending message again (should trigger)."
            )
            self.api.send_message(
                channel_name, f"Final message with {trigger_pattern} to test re-enable."
            )

            time.sleep(1.5)
            if self.api.remove_trigger(trigger_id):
                self.api.log_info(f"[AI Test] Removed trigger {trigger_id}")
            else:
                self.api.log_error(f"[AI Test] Failed to remove trigger {trigger_id}")
        else:
            self.api.log_error("[AI Test] Failed to add trigger via API.")


    def _test_channel_modes(self, channel_name: str):
        nick_for_mode_test = self.api.get_client_nick()
        if not nick_for_mode_test:
            self.api.log_error("[AI Test] Current nick not available for mode test.")
            return

        self.api.log_info(
            f"[AI Test] Testing mode changes on {channel_name} for {nick_for_mode_test}"
        )
        self.api.set_channel_mode(channel_name, "+v", str(nick_for_mode_test))
        time.sleep(2.5)
        self.api.set_channel_mode(channel_name, "-v", str(nick_for_mode_test))

    def _test_history_limit(self, channel_name: str):
        history_test_count = TEST_HISTORY_MESSAGES_COUNT
        configured_limit = HEADLESS_MAX_HISTORY

        self.api.log_info(
            f"Testing history limit: sending {history_test_count} messages to {channel_name} (configured limit is {configured_limit})"
        )

        for i in range(history_test_count):
            self.api.send_message(
                channel_name, f"Test message {i+1} for history limit testing"
            )
            time.sleep(0.3)

        messages = self.api.get_context_messages(channel_name)
        if messages is None:
            self.api.log_error(f"Failed to get messages for {channel_name}")
            return

        actual_count = len(messages)
        self.api.log_info(
            f"Channel {channel_name} has {actual_count} messages in buffer after sending {history_test_count}."
        )

        if actual_count > configured_limit and history_test_count > configured_limit :
            self.api.log_warning(
                f"Buffer size {actual_count} exceeds configured limit {configured_limit}"
            )
        else:
            self.api.log_info(
                f"Buffer size {actual_count} is within/below configured limit {configured_limit} (or test sent fewer messages than limit)."
            )

    def handle_join_event_for_logging_only(self, event_data: Dict[str, Any]):
        self.api.log_info(f"[AI Test] Join event (logging only): {event_data}")


    def handle_privmsg(self, event_data: Dict[str, Any]):
        self.api.log_info(f"[AI Test] PRIVMSG event: {event_data}")
        tags = event_data.get("tags", {})
        self.api.log_info(f"[AI Test] Message tags: {tags}")

    def handle_notice(self, event_data: Dict[str, Any]):
        self.api.log_info(f"[AI Test] NOTICE event: {event_data}")
        tags = event_data.get("tags", {})
        self.api.log_info(f"[AI Test] Message tags: {tags}")

    def handle_channel_mode_applied(self, event_data: Dict[str, Any]):
        self.api.log_info(f"[AI Test] CHANNEL_MODE_APPLIED event: {event_data}")


    def handle_client_nick_changed(self, event_data: Dict[str, Any]):
        old_nick = event_data.get('old_nick')
        new_nick = event_data.get('new_nick')
        self.api.log_info(f"[AI Test] CLIENT_NICK_CHANGED event: Old: {old_nick}, New: {new_nick}")

        if self.api.get_client_nick() == new_nick:
            if self.original_nick_for_test and old_nick == self.original_nick_for_test:
                self.original_nick_for_test = new_nick
                self.api.log_info(f"[AI Test] Updated original_nick_for_test to {new_nick} (was tracking old).")

            if self.initial_original_nick_for_test and new_nick == self.initial_original_nick_for_test:
                self.original_nick_for_test = new_nick
                self.api.log_info(f"[AI Test] Nick reverted to initial '{new_nick}'. Updated original_nick_for_test.")


    def handle_raw_numeric(self, event_data: Dict[str, Any]):
        numeric = event_data.get("numeric")
        self.api.log_info(f"[AI Test] Numeric code: {numeric}")
        # RPL_WELCOME (001) is now handled by CLIENT_REGISTERED for test scheduling
        # Nick change sequence is also triggered from there.

    def handle_aitest_command(self, args_str: str, event_data_command: Dict[str, Any]):
        args = args_str.split()
        if not args:
            self.api.add_message_to_context(
                event_data_command["active_context_name"],
                "Usage: /aitest <info|channels|users <channel>|capabilities|triggers|addtrigger|removetrigger|enabletrigger>",
                "error",
            )
            return

        sub_command = args[0].lower()
        cmd_args = args[1:]
        active_ctx = event_data_command["active_context_name"] or "Status"

        if sub_command == "info":
            server_info = self.api.get_server_info()
            connected = self.api.is_connected()
            self.api.add_message_to_context(
                active_ctx,
                f"Server Info: {server_info}, Connected: {connected}",
                "system",
            )
        elif sub_command == "triggers":
            triggers = self.api.list_triggers()
            if triggers:
                self.api.add_message_to_context(
                    active_ctx, "Configured Triggers:", "system"
                )
                for t in triggers:
                    self.api.add_message_to_context(
                        active_ctx,
                        f"  ID: {t['id']}, Event: {t['event_type']}, Pattern: '{t['pattern']}', "
                        f"Action: {t['action_type']} '{t['action_content']}', Enabled: {t['is_enabled']}",
                        "system",
                    )
            else:
                self.api.add_message_to_context(
                    active_ctx, "No triggers configured.", "system"
                )
        # ... (rest of aitest subcommands unchanged)
        elif sub_command == "addtrigger" and len(cmd_args) >= 4:
            event_type, pattern, action_type, *action_content_parts = cmd_args
            action_content = " ".join(action_content_parts)
            trigger_id = self.api.add_trigger(
                event_type.upper(), pattern, action_type.upper(), action_content
            )
            if trigger_id is not None:
                self.api.add_message_to_context(
                    active_ctx, f"Trigger added with ID: {trigger_id}", "system"
                )
            else:
                self.api.add_message_to_context(
                    active_ctx, "Failed to add trigger.", "error"
                )
        elif sub_command == "removetrigger" and len(cmd_args) == 1:
            try:
                trigger_id = int(cmd_args[0])
                if self.api.remove_trigger(trigger_id):
                    self.api.add_message_to_context(
                        active_ctx, f"Trigger {trigger_id} removed.", "system"
                    )
                else:
                    self.api.add_message_to_context(
                        active_ctx, f"Failed to remove trigger {trigger_id}.", "error"
                    )
            except ValueError:
                self.api.add_message_to_context(
                    active_ctx, "Invalid trigger ID.", "error"
                )
        elif sub_command == "enabletrigger" and len(cmd_args) == 2:
            try:
                trigger_id = int(cmd_args[0])
                enabled = cmd_args[1].lower() == "true"
                if self.api.set_trigger_enabled(trigger_id, enabled):
                    self.api.add_message_to_context(
                        active_ctx,
                        f"Trigger {trigger_id} {'enabled' if enabled else 'disabled'}.",
                        "system",
                    )
                else:
                    self.api.add_message_to_context(
                        active_ctx, f"Failed to update trigger {trigger_id}.", "error"
                    )
            except ValueError:
                self.api.add_message_to_context(
                    active_ctx, "Invalid trigger ID for enable/disable.", "error"
                )
        else:
            self.api.add_message_to_context(
                active_ctx,
                f"Unknown /aitest subcommand or wrong arguments: {sub_command}",
                "error",
            )


def get_script_instance(api_handler: "ScriptAPIHandler"):
    return AiApiTestScript(api_handler)

# END OF MODIFIED FILE: scripts/ai_api_test_script.py
