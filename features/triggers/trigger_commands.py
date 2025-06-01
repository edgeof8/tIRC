import logging
from typing import TYPE_CHECKING, Optional
from .trigger_manager import TriggerType, Trigger

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.triggers.commands")


class TriggerCommands:
    def __init__(self, client: "IRCClient_Logic"):
        self.client = client

    def handle_on_command(self, args_str: str) -> bool:
        """Handle the /on command and its subcommands."""
        if not args_str:
            self._show_usage()
            return True

        parts = args_str.split(" ", 2)
        sub_command = parts[0].lower()

        if sub_command == "add":
            return self._handle_add(parts[1:])
        elif sub_command == "list":
            return self._handle_list(parts[1:])
        elif sub_command == "remove":
            return self._handle_remove(parts[1:])
        elif sub_command == "enable":
            return self._handle_enable(parts[1:])
        elif sub_command == "disable":
            return self._handle_disable(parts[1:])
        else:
            self._show_usage()
            return True

    def _show_usage(self):
        """Show usage information for the /on command."""
        usage = (
            "Usage:\n"
            "/on add <event> <pattern> <action> - Add a new trigger\n"
            "/on list [event] - List all triggers or triggers for a specific event\n"
            "/on remove <id> - Remove a trigger by ID\n"
            "/on enable <id> - Enable a trigger\n"
            "/on disable <id> - Disable a trigger\n"
            "\nEvents: TEXT, ACTION, JOIN, PART, QUIT, KICK, MODE, TOPIC, NICK, NOTICE, INVITE, CTCP, RAW"
        )
        self.client.add_message(
            usage,
            self.client.ui.colors["system"],
            context_name=self.client.context_manager.active_context_name or "Status",
        )

    def _handle_add(self, args: list) -> bool:
        """Handle /on add <event> <pattern> <action>."""
        if len(args) < 3:
            self.client.add_message(
                "Usage: /on add <event> <pattern> <action>",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        event_type, pattern, action = args
        trigger_id = self.client.trigger_manager.add_trigger(
            event_type, pattern, action
        )

        if trigger_id is not None:
            self.client.add_message(
                f"Trigger added with ID {trigger_id}",
                self.client.ui.colors["system"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        else:
            self.client.add_message(
                "Failed to add trigger. Check event type and pattern.",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        return True

    def _handle_list(self, args: list) -> bool:
        """Handle /on list [event]."""
        event_type = args[0] if args else None
        triggers = self.client.trigger_manager.list_triggers(event_type)

        if not triggers:
            self.client.add_message(
                "No triggers found"
                + (f" for event {event_type}" if event_type else ""),
                self.client.ui.colors["system"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        for trigger in triggers:
            status = "Enabled" if trigger["is_enabled"] else "Disabled"
            trigger_info = (
                f"ID: {trigger['id']} | Event: {trigger['event_type']} | "
                f"Pattern: {trigger['pattern']} | Action: {trigger['action']} | {status}"
            )
            self.client.add_message(
                trigger_info,
                self.client.ui.colors["system"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        return True

    def _handle_remove(self, args: list) -> bool:
        """Handle /on remove <id>."""
        if not args:
            self.client.add_message(
                "Usage: /on remove <id>",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        try:
            trigger_id = int(args[0])
            if self.client.trigger_manager.remove_trigger(trigger_id):
                self.client.add_message(
                    f"Trigger {trigger_id} removed",
                    self.client.ui.colors["system"],
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
            else:
                self.client.add_message(
                    f"Trigger {trigger_id} not found",
                    self.client.ui.colors["error"],
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
        except ValueError:
            self.client.add_message(
                "Invalid trigger ID",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        return True

    def _handle_enable(self, args: list) -> bool:
        """Handle /on enable <id>."""
        if not args:
            self.client.add_message(
                "Usage: /on enable <id>",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        try:
            trigger_id = int(args[0])
            if self.client.trigger_manager.set_trigger_enabled(trigger_id, True):
                self.client.add_message(
                    f"Trigger {trigger_id} enabled",
                    self.client.ui.colors["system"],
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
            else:
                self.client.add_message(
                    f"Trigger {trigger_id} not found",
                    self.client.ui.colors["error"],
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
        except ValueError:
            self.client.add_message(
                "Invalid trigger ID",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        return True

    def _handle_disable(self, args: list) -> bool:
        """Handle /on disable <id>."""
        if not args:
            self.client.add_message(
                "Usage: /on disable <id>",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        try:
            trigger_id = int(args[0])
            if self.client.trigger_manager.set_trigger_enabled(trigger_id, False):
                self.client.add_message(
                    f"Trigger {trigger_id} disabled",
                    self.client.ui.colors["system"],
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
            else:
                self.client.add_message(
                    f"Trigger {trigger_id} not found",
                    self.client.ui.colors["error"],
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
        except ValueError:
            self.client.add_message(
                "Invalid trigger ID",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        return True
