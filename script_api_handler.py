import logging
from typing import Any, Dict, List, Optional, Callable

from config import ENABLE_TRIGGER_SYSTEM
from irc_client_logic import IRCClient_Logic
from script_manager import ScriptManager


class ScriptAPIHandler:
    """Handles API calls from scripts."""

    def __init__(
        self,
        client_logic_ref: "IRCClient_Logic",
        script_manager_ref: "ScriptManager",
        script_name: str,
    ):
        """Initialize the script API handler.

        Args:
            client_logic_ref: Reference to the IRC client logic instance.
            script_manager_ref: Reference to the script manager instance.
            script_name: Name of the script using this handler.
        """
        self.client_logic_ref = client_logic_ref
        self.script_manager_ref = script_manager_ref
        self.script_name = script_name
        self.logger = logging.getLogger(__name__)

    def add_trigger(
        self, event_type: str, pattern: str, action_type: str, action_content: str
    ) -> Optional[int]:
        """Add a trigger.

        Args:
            event_type: Type of event to trigger on (e.g., "TEXT", "JOIN").
            pattern: Regular expression pattern to match.
            action_type: Type of action to take (e.g., "COMMAND", "PYTHON").
            action_content: Content to use in the action.

        Returns:
            ID of the newly created trigger if successful, None otherwise.
        """
        if not ENABLE_TRIGGER_SYSTEM:
            self.logger.warning(
                f"Trigger system is disabled. Cannot add trigger from script '{self.script_name}'."
            )
            return None

        if not self.client_logic_ref.trigger_manager:
            self.logger.warning(
                f"Trigger manager not available. Cannot add trigger from script '{self.script_name}'."
            )
            return None

        try:
            return self.client_logic_ref.trigger_manager.add_trigger(
                event_type_str=event_type,
                pattern=pattern,
                action_type_str=action_type,
                action_content=action_content,
            )
        except Exception as e:
            self.logger.error(
                f"Error adding trigger from script '{self.script_name}': {e}"
            )
            return None

    def remove_trigger(self, trigger_id: int) -> bool:
        """Remove a trigger.

        Args:
            trigger_id: ID of the trigger to remove.

        Returns:
            True if the trigger was removed successfully, False otherwise.
        """
        if not ENABLE_TRIGGER_SYSTEM:
            self.logger.warning(
                f"Trigger system is disabled. Cannot remove trigger from script '{self.script_name}'."
            )
            return False

        if not self.client_logic_ref.trigger_manager:
            self.logger.warning(
                f"Trigger manager not available. Cannot remove trigger from script '{self.script_name}'."
            )
            return False

        try:
            result = self.client_logic_ref.trigger_manager.remove_trigger(trigger_id)
            return bool(result)
        except Exception as e:
            self.logger.error(
                f"Error removing trigger from script '{self.script_name}': {e}"
            )
            return False

    def list_triggers(self) -> List[Dict[str, Any]]:
        """List all triggers.

        Returns:
            List of trigger dictionaries.
        """
        if not ENABLE_TRIGGER_SYSTEM:
            self.logger.warning(
                f"Trigger system is disabled. Cannot list triggers from script '{self.script_name}'."
            )
            return []

        if not self.client_logic_ref.trigger_manager:
            self.logger.warning(
                f"Trigger manager not available. Cannot list triggers from script '{self.script_name}'."
            )
            return []

        try:
            return self.client_logic_ref.trigger_manager.list_triggers()
        except Exception as e:
            self.logger.error(
                f"Error listing triggers from script '{self.script_name}': {e}"
            )
            return []

    def set_trigger_enabled(self, trigger_id: int, enabled: bool) -> bool:
        """Set whether a trigger is enabled.

        Args:
            trigger_id: ID of the trigger.
            enabled: Whether the trigger should be enabled.

        Returns:
            True if the trigger's enabled state was set successfully, False otherwise.
        """
        if not ENABLE_TRIGGER_SYSTEM:
            self.logger.warning(
                f"Trigger system is disabled. Cannot set trigger state from script '{self.script_name}'."
            )
            return False

        if not self.client_logic_ref.trigger_manager:
            self.logger.warning(
                f"Trigger manager not available. Cannot set trigger state from script '{self.script_name}'."
            )
            return False

        try:
            result = self.client_logic_ref.trigger_manager.set_trigger_enabled(
                trigger_id, enabled
            )
            return bool(result)
        except Exception as e:
            self.logger.error(
                f"Error setting trigger state from script '{self.script_name}': {e}"
            )
            return False

    def subscribe_to_event(self, event_name: str, handler_function: Callable) -> None:
        """Subscribe to an event.

        Args:
            event_name: Name of the event to subscribe to.
            handler_function: Function to call when the event occurs.
        """
        self.script_manager_ref.subscribe_script_to_event(
            event_name, handler_function, self.script_name
        )

    def unsubscribe_from_event(
        self, event_name: str, handler_function: Callable
    ) -> None:
        """Unsubscribe from an event.

        Args:
            event_name: Name of the event to unsubscribe from.
            handler_function: Function to remove from the event's handlers.
        """
        self.script_manager_ref.unsubscribe_script_from_event(
            event_name, handler_function, self.script_name
        )

    def register_command(
        self,
        command_name: str,
        handler_function: Callable,
        help_text: str,
        aliases: Optional[List[str]] = None,
    ) -> None:
        """Register a command.

        Args:
            command_name: Name of the command.
            handler_function: Function to handle the command.
            help_text: Help text for the command.
            aliases: List of command aliases.
        """
        if aliases is None:
            aliases = []
        self.script_manager_ref.register_command_from_script(
            command_name, handler_function, help_text, aliases, self.script_name
        )

    def get_data_file_path(self, data_filename: str) -> str:
        """Get the path to a data file for this script.

        Args:
            data_filename: Name of the data file.

        Returns:
            Path to the data file.
        """
        return self.script_manager_ref.get_data_file_path_for_script(
            self.script_name, data_filename
        )

    def add_message(
        self, message: str, color: int = 0, context_name: Optional[str] = None
    ) -> None:
        """Add a message to the UI.

        Args:
            message: Message to add.
            color: Color to use for the message.
            context_name: Name of the context to add the message to.
        """
        self.client_logic_ref.add_message(
            text=message,
            color_attr=color,
            prefix_time=True,
            context_name=context_name or "Status",
        )

    def get_nick(self) -> str:
        """Get the current nick.

        Returns:
            The current nick.
        """
        return self.client_logic_ref.nick

    def get_server(self) -> str:
        """Get the server address.

        Returns:
            The server address.
        """
        return self.client_logic_ref.server

    def get_port(self) -> int:
        """Get the server port.

        Returns:
            The server port.
        """
        return self.client_logic_ref.port

    def get_channels(self) -> List[str]:
        """Get the list of channels.

        Returns:
            List of channel names.
        """
        return list(self.client_logic_ref.currently_joined_channels)

    def send_message(self, target: str, message: str) -> None:
        """Send a message to a target.

        Args:
            target: Target to send the message to.
            message: Message to send.
        """
        self.client_logic_ref.network_handler.send_raw(f"PRIVMSG {target} :{message}")

    def send_command(self, command: str) -> None:
        """Send a command to the server.

        Args:
            command: Command to send.
        """
        self.client_logic_ref.network_handler.send_raw(command)

    def join_channel(self, channel: str) -> None:
        """Join a channel.

        Args:
            channel: Channel to join.
        """
        if not channel.startswith(("#", "&", "+", "!")):
            channel = "#" + channel
        self.client_logic_ref.network_handler.send_raw(f"JOIN {channel}")

    def part_channel(self, channel: str, reason: Optional[str] = None) -> None:
        """Leave a channel.

        Args:
            channel: Channel to leave.
            reason: Optional reason for leaving.
        """
        if not channel.startswith(("#", "&", "+", "!")):
            channel = "#" + channel
        if reason:
            self.client_logic_ref.network_handler.send_raw(f"PART {channel} :{reason}")
        else:
            self.client_logic_ref.network_handler.send_raw(f"PART {channel}")

    def quit(self, reason: Optional[str] = None) -> None:
        """Quit the IRC server.

        Args:
            reason: Optional reason for quitting.
        """
        if reason:
            self.client_logic_ref.network_handler.send_raw(f"QUIT :{reason}")
        else:
            self.client_logic_ref.network_handler.send_raw("QUIT")
