import logging
from typing import Dict, Any

logger = logging.getLogger("pyrc.event_test_script")


class EventTestScript:
    def __init__(self, api_handler):
        self.api = api_handler
        self.script_name = self.__class__.__module__

    def load(self):
        """Initialize the script and subscribe to events."""
        self.api.log_info("EventTestScript loading...")

        # Subscribe to client lifecycle events
        self.api.subscribe_to_event("CLIENT_CONNECTED", self.handle_client_connected)
        self.api.subscribe_to_event(
            "CLIENT_DISCONNECTED", self.handle_client_disconnected
        )

        # Subscribe to IRC events
        self.api.subscribe_to_event("PRIVMSG", self.handle_privmsg)
        self.api.subscribe_to_event("JOIN", self.handle_join)
        self.api.subscribe_to_event("PART", self.handle_part)
        self.api.subscribe_to_event("QUIT", self.handle_quit)
        self.api.subscribe_to_event("NICK", self.handle_nick)
        self.api.subscribe_to_event("NOTICE", self.handle_notice)
        self.api.subscribe_to_event("MODE", self.handle_mode)
        self.api.subscribe_to_event("TOPIC", self.handle_topic)
        self.api.subscribe_to_event("CHGHOST", self.handle_chghost)

        self.api.log_info("EventTestScript loaded and subscribed to events.")

    def handle_client_connected(self, event_data: Dict[str, Any]):
        """Handle CLIENT_CONNECTED event."""
        server = event_data.get("server", "unknown")
        port = event_data.get("port", "unknown")
        nick = event_data.get("nick", "unknown")
        self.api.log_info(f"Connected to {server}:{port} as {nick}")

    def handle_client_disconnected(self, event_data: Dict[str, Any]):
        """Handle CLIENT_DISCONNECTED event."""
        server = event_data.get("server", "unknown")
        port = event_data.get("port", "unknown")
        self.api.log_info(f"Disconnected from {server}:{port}")

    def handle_privmsg(self, event_data: Dict[str, Any]):
        """Handle PRIVMSG event."""
        nick = event_data.get("nick", "unknown")
        target = event_data.get("target", "unknown")
        message = event_data.get("message", "")
        is_channel = event_data.get("is_channel_msg", False)

        if is_channel:
            self.api.log_info(f"Channel message from {nick} in {target}: {message}")
        else:
            self.api.log_info(f"Private message from {nick}: {message}")

    def handle_join(self, event_data: Dict[str, Any]):
        """Handle JOIN event."""
        nick = event_data.get("nick", "unknown")
        channel = event_data.get("channel", "unknown")
        is_self = event_data.get("is_self", False)

        if is_self:
            self.api.log_info(f"Joined channel {channel}")
        else:
            self.api.log_info(f"{nick} joined {channel}")

    def handle_part(self, event_data: Dict[str, Any]):
        """Handle PART event."""
        nick = event_data.get("nick", "unknown")
        channel = event_data.get("channel", "unknown")
        reason = event_data.get("reason", "")
        is_self = event_data.get("is_self", False)

        if is_self:
            self.api.log_info(
                f"Left channel {channel}" + (f" ({reason})" if reason else "")
            )
        else:
            self.api.log_info(
                f"{nick} left {channel}" + (f" ({reason})" if reason else "")
            )

    def handle_quit(self, event_data: Dict[str, Any]):
        """Handle QUIT event."""
        nick = event_data.get("nick", "unknown")
        reason = event_data.get("reason", "")
        self.api.log_info(f"{nick} quit" + (f" ({reason})" if reason else ""))

    def handle_nick(self, event_data: Dict[str, Any]):
        """Handle NICK event."""
        old_nick = event_data.get("old_nick", "unknown")
        new_nick = event_data.get("new_nick", "unknown")
        is_self = event_data.get("is_self", False)

        if is_self:
            self.api.log_info(f"Changed nick to {new_nick}")
        else:
            self.api.log_info(f"{old_nick} changed nick to {new_nick}")

    def handle_notice(self, event_data: Dict[str, Any]):
        """Handle NOTICE event."""
        nick = event_data.get("nick", "unknown")
        target = event_data.get("target", "unknown")
        message = event_data.get("message", "")
        is_channel = event_data.get("is_channel_notice", False)

        if is_channel:
            self.api.log_info(f"Channel notice from {nick} in {target}: {message}")
        else:
            self.api.log_info(f"Notice from {nick}: {message}")

    def handle_mode(self, event_data: Dict[str, Any]):
        """Handle MODE event."""
        nick = event_data.get("nick", "unknown")
        target = event_data.get("target", "unknown")
        modes = event_data.get("modes_and_params", "")
        self.api.log_info(f"Mode change by {nick} on {target}: {modes}")

    def handle_topic(self, event_data: Dict[str, Any]):
        """Handle TOPIC event."""
        nick = event_data.get("nick", "unknown")
        channel = event_data.get("channel", "unknown")
        topic = event_data.get("topic", "")
        self.api.log_info(f"Topic change by {nick} in {channel}: {topic}")

    def handle_chghost(self, event_data: Dict[str, Any]):
        """Handle CHGHOST event."""
        nick = event_data.get("nick", "unknown")
        new_ident = event_data.get("new_ident", "?")
        new_host = event_data.get("new_host", "?")
        self.api.log_info(f"CHGHOST: {nick} is now {new_ident}@{new_host}")


# Entry point for ScriptManager
def get_script_instance(api_handler):
    return EventTestScript(api_handler)
