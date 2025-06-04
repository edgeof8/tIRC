import logging
from typing import TYPE_CHECKING, Optional, List
from enum import Enum  # Added for isinstance check
from .trigger_manager import TriggerType, ActionType

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

        parts = args_str.split(" ", 1)
        sub_command = parts[0].lower()
        remaining_args_str = parts[1] if len(parts) > 1 else ""

        if sub_command == "add":
            return self._handle_add(remaining_args_str)
        elif sub_command == "list":
            return self._handle_list(remaining_args_str)
        elif sub_command == "remove":
            return self._handle_remove(remaining_args_str)
        elif sub_command == "enable":
            return self._handle_enable(remaining_args_str)
        elif sub_command == "disable":
            return self._handle_disable(remaining_args_str)
        else:
            self._show_usage()
            return True

    def _show_usage(self):
        """Show usage information for the /on command."""
        usage = (
            "Usage:\n"
            "  /on add <event> <pattern> <CMD|PY> <action_content>\n"
            "    - Adds a new trigger. CMD for client command, PY for Python code.\n"
            '    - Example CMD: /on add TEXT "hello there" CMD /say General Kenobi!\n'
            "    - Example PY:  /on add TEXT \"calc (.*)\" PY client.add_message(f\"Result: {eval(event_data['$1'])}\", client.ui.colors['system'])\n"
            "  /on list [event]\n"
            "    - Lists triggers, optionally filtered by event type.\n"
            "  /on remove <id>\n"
            "    - Removes a trigger by its ID.\n"
            "  /on enable <id>\n"
            "    - Enables a trigger by its ID.\n"
            "  /on disable <id>\n"
            "    - Disables a trigger by its ID.\n"
            "\nEvents: TEXT, ACTION, JOIN, PART, QUIT, KICK, MODE, TOPIC, NICK, NOTICE, INVITE, CTCP, RAW"
        )
        self.client.add_message(
            usage,
            "system",
            context_name=self.client.context_manager.active_context_name or "Status",
        )

    def _handle_add(self, args_str: str) -> bool:
        """Handle /on add <event> <pattern> <TYPE> <action_content>."""
        usage_msg = "Usage: /on add <event> <pattern> <CMD|PY> <action_content>"

        args = args_str.split(
            " ", 3
        )  # event, pattern, type, action_content (action_content can have spaces)

        if len(args) < 4:
            self.client.add_message(
                usage_msg,
                "error",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        event_type_str, pattern, action_type_input, action_content_str = args
        action_type_str_upper = action_type_input.upper()

        if action_type_str_upper not in [at.name for at in ActionType]:
            self.client.add_message(
                f"Invalid action type '{action_type_input}'. Must be CMD or PY.\n{usage_msg}",
                "error",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        if not self.client.trigger_manager:
            self.client.add_message(
                "Trigger system is disabled. Cannot add trigger.",
                "error",
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return True
        trigger_id = self.client.trigger_manager.add_trigger(
            event_type_str, pattern, action_type_str_upper, action_content_str
        )

        if trigger_id is not None:
            self.client.add_message(
                f"Trigger added with ID {trigger_id}",
                "system",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        else:
            self.client.add_message(
                f"Failed to add trigger. Check event type ('{event_type_str}'), pattern, or action type ('{action_type_str_upper}').",
                "error",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        return True

    def _handle_list(self, args_str: str) -> bool:
        """Handle /on list [event]."""
        # args_str might be empty or contain the event type
        event_type = args_str.strip() if args_str else None
        if not self.client.trigger_manager:
            self.client.add_message(
                "Trigger system is disabled. Cannot list triggers.",
                "error",
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return True
        triggers = self.client.trigger_manager.list_triggers(event_type)

        if not triggers:
            self.client.add_message(
                "No triggers found"
                + (f" for event {event_type}" if event_type else ""),
                "system",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        for trigger in triggers:
            status = "Enabled" if trigger["is_enabled"] else "Disabled"
            # trigger['action_type'] is already a string from TriggerManager.list_triggers
            trigger_info = (
                f"ID: {trigger['id']} | Event: {trigger['event_type']} | Type: {trigger['action_type']} | "
                f"Pattern: \"{trigger['pattern']}\" | Action: \"{trigger['action_content']}\" | {status}"
            )
            # Ensure event_type from trigger dict is string for display
            event_type_display = trigger["event_type"]
            if isinstance(
                event_type_display, Enum
            ):  # Should be string from manager, but defensive
                event_type_display = event_type_display.name

            trigger_info = (
                f"ID: {trigger['id']} | Evt: {event_type_display} | Type: {trigger['action_type']} | "
                f"Ptrn: \"{trigger['pattern']}\" | Act: \"{trigger['action_content']}\" | {status}"
            )
            self.client.add_message(
                trigger_info,
                "system",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        return True

    def _handle_remove(self, args_str: str) -> bool:
        """Handle /on remove <id>."""
        if not args_str.strip():
            self.client.add_message(
                "Usage: /on remove <id>",
                "error",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        try:
            trigger_id_str = args_str.strip()
            trigger_id = int(trigger_id_str)
            if not self.client.trigger_manager:
                self.client.add_message(
                    "Trigger system is disabled. Cannot remove trigger.",
                    "error",
                    context_name=self.client.context_manager.active_context_name or "Status",
                )
                return True
            if self.client.trigger_manager.remove_trigger(trigger_id):
                self.client.add_message(
                    f"Trigger {trigger_id} removed",
                    "system",
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
            else:
                self.client.add_message(
                    f"Trigger {trigger_id} not found",
                    "error",
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
        except ValueError:
            self.client.add_message(
                "Invalid trigger ID",
                "error",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        return True

    def _handle_enable(self, args_str: str) -> bool:
        """Handle /on enable <id>."""
        if not args_str.strip():
            self.client.add_message(
                "Usage: /on enable <id>",
                "error",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        try:
            trigger_id_str = args_str.strip()
            trigger_id = int(trigger_id_str)
            if not self.client.trigger_manager:
                self.client.add_message(
                    "Trigger system is disabled. Cannot enable trigger.",
                    "error",
                    context_name=self.client.context_manager.active_context_name or "Status",
                )
                return True
            if self.client.trigger_manager.set_trigger_enabled(trigger_id, True):
                self.client.add_message(
                    f"Trigger {trigger_id} enabled",
                    "system",
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
            else:
                self.client.add_message(
                    f"Trigger {trigger_id} not found",
                    "error",
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
        except ValueError:
            self.client.add_message(
                "Invalid trigger ID",
                "error",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        return True

    def _handle_disable(self, args_str: str) -> bool:
        """Handle /on disable <id>."""
        if not args_str.strip():
            self.client.add_message(
                "Usage: /on disable <id>",
                "error",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return True

        try:
            trigger_id_str = args_str.strip()
            trigger_id = int(trigger_id_str)
            if not self.client.trigger_manager:
                self.client.add_message(
                    "Trigger system is disabled. Cannot disable trigger.",
                    "error",
                    context_name=self.client.context_manager.active_context_name or "Status",
                )
                return True
            if self.client.trigger_manager.set_trigger_enabled(trigger_id, False):
                self.client.add_message(
                    f"Trigger {trigger_id} disabled",
                    "system",
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
            else:
                self.client.add_message(
                    f"Trigger {trigger_id} not found",
                    "error",
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
        except ValueError:
            self.client.add_message(
                "Invalid trigger ID",
                "error",
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        return True
