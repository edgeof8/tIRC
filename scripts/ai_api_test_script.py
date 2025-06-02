import logging
from typing import Dict, Any, TYPE_CHECKING
import time
import threading

if TYPE_CHECKING:
    from script_manager import ScriptAPIHandler

logger = logging.getLogger("pyrc.script.ai_api_test")


class AIAPITestScript:
    def __init__(self, api: "ScriptAPIHandler"):
        self.api = api
        self.api.register_command(
            "aitest", self.handle_aitest_command, "Test various API methods", ["at"]
        )

        # Subscribe to events
        self.api.subscribe_to_event("CLIENT_CONNECTED", self.handle_client_connected)
        self.api.subscribe_to_event("JOIN", self.handle_join)
        self.api.subscribe_to_event("PRIVMSG", self.handle_privmsg)
        self.api.subscribe_to_event("NOTICE", self.handle_notice)
        self.api.subscribe_to_event("RAW_IRC_NUMERIC", self.handle_raw_numeric)
        self.api.subscribe_to_event("CHANNEL_MODE_APPLIED", self.handle_channel_mode)
        self.api.subscribe_to_event("CLIENT_NICK_CHANGED", self.handle_nick_change)

    def handle_aitest_command(self, args: list) -> None:
        """Handle the /aitest command with various subcommands."""
        if not args:
            self.api.send_message(
                "Status",
                "Usage: /aitest [info|channels|users|capabilities|triggers|addtrigger|removetrigger|enabletrigger]",
            )
            return

        subcommand = args[0].lower()
        if subcommand == "info":
            server_info = self.api.get_server_info()
            self.api.send_message("Status", f"Server Info: {server_info}")
        elif subcommand == "channels":
            channels = self.api.get_joined_channels()
            self.api.send_message("Status", f"Joined Channels: {channels}")
        elif subcommand == "users":
            if len(args) < 2:
                self.api.send_message("Status", "Usage: /aitest users <channel>")
                return
            channel = args[1]
            users = self.api.get_channel_users(channel)
            self.api.send_message("Status", f"Users in {channel}: {users}")
        elif subcommand == "capabilities":
            caps = self.api.get_server_capabilities()
            self.api.send_message("Status", f"Server Capabilities: {caps}")
        elif subcommand == "triggers":
            triggers = self.api.list_triggers()
            self.api.send_message("Status", f"Configured Triggers: {triggers}")
        elif subcommand == "addtrigger":
            if len(args) < 4:
                self.api.send_message(
                    "Status",
                    "Usage: /aitest addtrigger <event_type> <pattern> <action_type> <action_content>",
                )
                return
            event_type = args[1]
            pattern = args[2]
            action_type = args[3]
            action_content = " ".join(args[4:]) if len(args) > 4 else ""
            trigger_id = self.api.add_trigger(
                event_type, pattern, action_type, action_content
            )
            self.api.send_message("Status", f"Added trigger with ID: {trigger_id}")
        elif subcommand == "removetrigger":
            if len(args) < 2:
                self.api.send_message("Status", "Usage: /aitest removetrigger <id>")
                return
            try:
                trigger_id = int(args[1])
                self.api.remove_trigger(trigger_id)
                self.api.send_message("Status", f"Removed trigger {trigger_id}")
            except ValueError:
                self.api.send_message("Status", "Error: Trigger ID must be a number")
        elif subcommand == "enabletrigger":
            if len(args) < 3:
                self.api.send_message(
                    "Status", "Usage: /aitest enabletrigger <id> <true|false>"
                )
                return
            try:
                trigger_id = int(args[1])
                enabled = args[2].lower() == "true"
                self.api.set_trigger_enabled(trigger_id, enabled)
                self.api.send_message(
                    "Status",
                    f"{'Enabled' if enabled else 'Disabled'} trigger {trigger_id}",
                )
            except ValueError:
                self.api.send_message("Status", "Error: Trigger ID must be a number")
        else:
            self.api.send_message("Status", f"Unknown subcommand: {subcommand}")

    def handle_client_connected(self, event_data: Dict[str, Any]) -> None:
        """Handle CLIENT_CONNECTED event."""
        logger.info(f"Client connected to server. Event data: {event_data}")
        server_info = self.api.get_server_info()
        logger.info(f"Server info: {server_info}")
        caps = self.api.get_server_capabilities()
        logger.info(f"Server capabilities: {caps}")

    def handle_join(self, event_data: Dict[str, Any]) -> None:
        """Handle JOIN events."""
        logger.info(f"Join event: {event_data}")

        # Test message tags by sending a message after joining
        if event_data.get("nick") == self.api.get_nick():
            logger.info("Self joined channel, sending test message...")

            # Schedule message after 2 seconds
            def send_test_message():
                time.sleep(2)  # Wait 2 seconds
                channel = event_data.get("channel")
                if channel:
                    test_msg = "Testing message tags with echo-message capability"
                    logger.info(f"Sending test message to {channel}: {test_msg}")
                    self.api.send_message(channel, test_msg)

            # Start message sending in a separate thread to avoid blocking
            threading.Thread(target=send_test_message, daemon=True).start()

    def handle_privmsg(self, event_data: Dict[str, Any]) -> None:
        """Handle PRIVMSG events."""
        logger.info(f"PRIVMSG event: {event_data}")
        # Log message tags specifically
        if "tags" in event_data:
            logger.info(f"Message tags: {event_data['tags']}")
        else:
            logger.info("No message tags present")

    def handle_notice(self, event_data: Dict[str, Any]) -> None:
        """Handle NOTICE event."""
        logger.info(f"NOTICE event: {event_data}")
        # Log message tags if present
        if "tags" in event_data:
            logger.info(f"Message tags: {event_data['tags']}")

    def handle_raw_numeric(self, event_data: Dict[str, Any]) -> None:
        """Handle RAW_IRC_NUMERIC event."""
        logger.info(f"Raw numeric event: {event_data}")
        # Log numeric code, source, parameters, and trailing data
        logger.info(f"Numeric code: {event_data.get('numeric')}")
        logger.info(f"Source: {event_data.get('source')}")
        logger.info(f"Parameters: {event_data.get('parameters')}")
        logger.info(f"Trailing: {event_data.get('trailing')}")

        # Test nick change after successful connection (001)
        if event_data["numeric"] == 1:  # RPL_WELCOME
            logger.info("Connection successful, scheduling nick change test...")

            # Schedule nick change after 5 seconds
            def change_nick():
                time.sleep(5)  # Wait 5 seconds
                new_nick = f"{self.api.get_nick()}_test"
                logger.info(f"Attempting to change nick to: {new_nick}")
                self.api.set_nick(new_nick)

            # Start nick change in a separate thread to avoid blocking
            threading.Thread(target=change_nick, daemon=True).start()

    def handle_channel_mode(self, event_data: Dict[str, Any]) -> None:
        """Handle CHANNEL_MODE_APPLIED event."""
        logger.info(f"Channel mode event: {event_data}")
        # Log channel, setter, and mode changes
        logger.info(f"Channel: {event_data.get('channel')}")
        logger.info(f"Setter: {event_data.get('setter')}")
        logger.info(f"Mode changes: {event_data.get('mode_changes')}")

    def handle_nick_change(self, event_data: Dict[str, Any]) -> None:
        """Handle CLIENT_NICK_CHANGED event."""
        logger.info(f"Nick change event: {event_data}")
        # Log old and new nicknames
        logger.info(f"Old nick: {event_data.get('old_nick')}")
        logger.info(f"New nick: {event_data.get('new_nick')}")

    def handle_client_nick_changed(self, event_data):
        """Handle client nick change events."""
        logger.info(f"Client nick changed event: {event_data}")
        # Verify the event data structure
        if "old_nick" in event_data and "new_nick" in event_data:
            logger.info(
                f"Nick change confirmed: {event_data['old_nick']} -> {event_data['new_nick']}"
            )
        else:
            logger.warning("Nick change event missing expected fields")


def get_script_instance(api: "ScriptAPIHandler") -> AIAPITestScript:
    """Factory function to create an instance of the script."""
    return AIAPITestScript(api)
