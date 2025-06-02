import logging
from typing import Dict, Any, TYPE_CHECKING, Optional, List, Tuple
import time
import threading
from config import HEADLESS_MAX_HISTORY

if TYPE_CHECKING:
    from script_manager import ScriptAPIHandler

logger = logging.getLogger("pyrc.script.ai_api_test")


class AiApiTestScript:
    def __init__(self, api_handler: "ScriptAPIHandler"):
        self.api = api_handler
        self.original_nick_for_test: Optional[str] = None
        self.initial_original_nick_for_test: Optional[str] = None
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
        self.api.subscribe_to_event("JOIN", self.handle_join)
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
        server_info = self.api.get_server_info()
        self.api.log_info(f"[AI Test] Server info: {server_info}")
        capabilities = self.api.get_server_capabilities()
        self.api.log_info(f"[AI Test] Server capabilities (on connect): {capabilities}")
        self.original_nick_for_test = self.api.get_client_nick()
        self.initial_original_nick_for_test = self.api.get_client_nick()

    def _test_nick_change_sequence(self):
        if not self.original_nick_for_test:
            self.api.log_error(
                "[AI Test] Original nick not captured for nick change test."
            )
            return

        new_nick = f"{self.original_nick_for_test}_test"
        self.api.log_info(f"[AI Test] Attempting to change nick to: {new_nick}")
        self.api.set_nick(new_nick)

        # Schedule revert after a delay
        threading.Timer(5.0, self._revert_nick_change).start()

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

        # Test trigger API
        self.api.log_info("[AI Test] Testing trigger API...")
        trigger_pattern = f"secret word {int(time.time())}"  # Unique pattern
        trigger_id = self.api.add_trigger(
            event_type="TEXT",  # Using TEXT for text-based triggers
            pattern=rf".*{trigger_pattern}.*",  # Regex to match anywhere
            action_type="COMMAND",  # Using COMMAND to match ActionType enum
            action_content=f"/msg {channel_name} Trigger for '{trigger_pattern}' fired!",
        )
        if trigger_id is not None:
            self.api.log_info(
                f"[AI Test] Added trigger with ID: {trigger_id}, pattern: '{trigger_pattern}'"
            )
            triggers = self.api.list_triggers()
            self.api.log_info(f"[AI Test] Current triggers: {triggers}")
            self.api.send_message(
                channel_name, f"The {trigger_pattern} has been spoken."
            )

            # Test disable/enable
            time.sleep(1)  # Give time for first trigger
            self.api.set_trigger_enabled(trigger_id, False)
            self.api.log_info(
                f"[AI Test] Disabled trigger {trigger_id}. Sending message again (should not trigger)."
            )
            self.api.send_message(
                channel_name,
                f"Another message with {trigger_pattern}, should be ignored.",
            )
            time.sleep(1)
            self.api.set_trigger_enabled(trigger_id, True)
            self.api.log_info(
                f"[AI Test] Enabled trigger {trigger_id}. Sending message again (should trigger)."
            )
            self.api.send_message(
                channel_name, f"Final message with {trigger_pattern} to test re-enable."
            )

            time.sleep(1)
            if self.api.remove_trigger(trigger_id):
                self.api.log_info(f"[AI Test] Removed trigger {trigger_id}")
            else:
                self.api.log_error(f"[AI Test] Failed to remove trigger {trigger_id}")
        else:
            self.api.log_error("[AI Test] Failed to add trigger via API.")

    def _test_channel_modes(self, channel_name: str):
        if not self.original_nick_for_test:
            self.api.log_error("[AI Test] Original nick not captured for mode test.")
            return
        self.api.log_info(
            f"[AI Test] Testing mode changes on {channel_name} for {self.original_nick_for_test}"
        )
        self.api.set_channel_mode(channel_name, "+v", str(self.original_nick_for_test))
        threading.Timer(
            2.0,
            lambda: self.api.set_channel_mode(
                channel_name, "-v", str(self.original_nick_for_test)
            ),
        ).start()

    def _test_history_limit(self, channel_name: str):
        """
        Tests the message history limit functionality by sending messages and verifying the buffer size.

        Args:
            channel_name: The channel to test with.
        """
        # Get the configured history limit
        history_limit = HEADLESS_MAX_HISTORY
        self.api.log_info(
            f"Testing history limit of {history_limit} messages in {channel_name}"
        )

        # Send more messages than the limit
        test_messages = history_limit + 2
        for i in range(test_messages):
            self.api.send_message(
                channel_name, f"Test message {i+1} for history limit testing"
            )
            time.sleep(0.1)  # Small delay between messages

        # Get messages and verify count
        messages = self.api.get_context_messages(channel_name)
        if messages is None:
            self.api.log_error(f"Failed to get messages for {channel_name}")
            return

        actual_count = len(messages)
        self.api.log_info(
            f"Channel {channel_name} has {actual_count} messages in buffer"
        )

        if actual_count > history_limit:
            self.api.log_warning(
                f"Buffer size {actual_count} exceeds configured limit {history_limit}"
            )
        else:
            self.api.log_info(
                f"Buffer size {actual_count} is within configured limit {history_limit}"
            )

    def handle_join(self, event_data: Dict[str, Any]):
        self.api.log_info(f"[AI Test] Join event: {event_data}")
        channel = event_data.get("channel")
        if event_data.get("is_self") and channel:
            self.api.log_info(
                f"[AI Test] Self joined channel {channel}, scheduling tests."
            )
            # Schedule tests with delays to allow server processing
            threading.Timer(
                2.0, lambda: self._test_message_tags_and_triggers(channel)
            ).start()
            threading.Timer(
                15.0, lambda: self._test_channel_modes(channel)
            ).start()  # Run mode test after potential nick changes
            threading.Timer(2.0, self._test_history_limit, args=[channel]).start()

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
        self.api.log_info(f"[AI Test] Channel: {event_data.get('channel')}")
        self.api.log_info(
            f"[AI Test] Setter: {event_data.get('setter')} ({event_data.get('setter_userhost')})"
        )
        self.api.log_info(f"[AI Test] Mode changes: {event_data.get('mode_changes')}")
        self.api.log_info(
            f"[AI Test] Current channel modes: {event_data.get('current_modes')}"
        )

    def handle_client_nick_changed(self, event_data: Dict[str, Any]):
        self.api.log_info(f"[AI Test] CLIENT_NICK_CHANGED event: {event_data}")
        self.api.log_info(
            f"[AI Test] Old nick: {event_data.get('old_nick')}, New nick: {event_data.get('new_nick')}"
        )
        # If our nick changed, update original_nick_for_test if it was the one that changed
        if (
            self.original_nick_for_test
            and event_data.get("old_nick") == self.original_nick_for_test
        ):
            self.original_nick_for_test = event_data.get("new_nick")
            self.api.log_info(
                f"[AI Test] Updated original_nick_for_test to {self.original_nick_for_test}"
            )
        elif (
            self.original_nick_for_test
            and event_data.get("old_nick") == f"{self.original_nick_for_test}_test"
        ):
            self.original_nick_for_test = event_data.get(
                "new_nick"
            )  # Should be back to original
            self.api.log_info(
                f"[AI Test] Updated original_nick_for_test to {self.original_nick_for_test} after revert."
            )

    def handle_raw_numeric(self, event_data: Dict[str, Any]):
        """Handle RAW_IRC_NUMERIC events."""
        numeric = event_data.get("numeric")
        params_list = event_data.get("params_list", [])
        display_params_list = event_data.get("display_params_list", [])

        logger.info(f"RAW_IRC_NUMERIC {numeric}:")
        logger.info(f"  params_list: {params_list}")
        logger.info(f"  display_params_list: {display_params_list}")
        self.api.log_info(f"[AI Test] Numeric code: {numeric}")
        self.api.log_info(f"[AI Test] Source: {event_data.get('source')}")
        self.api.log_info(f"[AI Test] Params list: {params_list}")
        self.api.log_info(f"[AI Test] Display Params list: {display_params_list}")
        self.api.log_info(f"[AI Test] Trailing: {event_data.get('trailing')}")
        self.api.log_info(f"[AI Test] Tags: {event_data.get('tags')}")

        if numeric == 1:  # RPL_WELCOME
            self.api.log_info(
                "[AI Test] Received RPL_WELCOME, scheduling nick change sequence in 7s."
            )
            if (
                not self.original_nick_for_test
            ):  # Capture if not already set by CLIENT_CONNECTED
                self.original_nick_for_test = self.api.get_client_nick()
            threading.Timer(7.0, self._test_nick_change_sequence).start()

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
