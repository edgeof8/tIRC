# START OF MODIFIED FILE: script_api_handler.py
import logging
from typing import Any, Dict, List, Optional, Callable, Tuple, Set, TYPE_CHECKING # Added Tuple, Set, TYPE_CHECKING

from config import ENABLE_TRIGGER_SYSTEM
# Removed IRCClient_Logic and ScriptManager direct imports to avoid circularity if ScriptAPIHandler is defined first
# They will be type hinted with forward references if needed, or rely on constructor injection.
# from irc_client_logic import IRCClient_Logic
# from script_manager import ScriptManager

if TYPE_CHECKING: # Use this for type hinting to avoid circular imports at runtime
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
        self.client_logic = client_logic_ref # Renamed for clarity
        self.script_manager = script_manager_ref # Renamed for clarity
        self.script_name = script_name
        # Use a logger specific to this API handler instance for the script
        self.logger = logging.getLogger(f"pyrc.script_api.{script_name}")
        # Removed script-specific attributes that are managed by ScriptManager
        # self.script_instance = None
        # self.registered_commands = {}
        # self.registered_events = set()
        # self.help_texts = {}
        # self.quit_messages = []

    # --- Logging methods ---
    def log_info(self, message: str):
        self.logger.info(message)

    def log_warning(self, message: str):
        self.logger.warning(message)

    def log_error(self, message: str):
        self.logger.error(message)

    # --- Trigger Management Methods ---
    def add_trigger(
        self, event_type: str, pattern: str, action_type: str, action_content: str
    ) -> Optional[int]:
        if not ENABLE_TRIGGER_SYSTEM:
            self.log_warning("Trigger system is disabled. Cannot add trigger.")
            return None
        # Access trigger_manager via client_logic
        if not hasattr(self.client_logic, 'trigger_manager') or not self.client_logic.trigger_manager:
            self.log_warning("Trigger manager not available. Cannot add trigger.")
            return None
        try:
            return self.client_logic.trigger_manager.add_trigger(
                event_type_str=event_type,
                pattern=pattern,
                action_type_str=action_type, # Pass as string
                action_content=action_content,
            )
        except Exception as e:
            self.log_error(f"Error adding trigger: {e}")
            return None

    def remove_trigger(self, trigger_id: int) -> bool:
        if not ENABLE_TRIGGER_SYSTEM:
            self.log_warning("Trigger system is disabled. Cannot remove trigger.")
            return False
        if not hasattr(self.client_logic, 'trigger_manager') or not self.client_logic.trigger_manager:
            self.log_warning("Trigger manager not available. Cannot remove trigger.")
            return False
        try:
            return self.client_logic.trigger_manager.remove_trigger(trigger_id)
        except Exception as e:
            self.log_error(f"Error removing trigger: {e}")
            return False

    def list_triggers(self, event_type: Optional[str] = None) -> List[Dict[str, Any]]: # Added event_type filter
        if not ENABLE_TRIGGER_SYSTEM:
            self.log_warning("Trigger system is disabled. Cannot list triggers.")
            return []
        if not hasattr(self.client_logic, 'trigger_manager') or not self.client_logic.trigger_manager:
            self.log_warning("Trigger manager not available. Cannot list triggers.")
            return []
        try:
            return self.client_logic.trigger_manager.list_triggers(event_type=event_type)
        except Exception as e:
            self.log_error(f"Error listing triggers: {e}")
            return []

    def set_trigger_enabled(self, trigger_id: int, enabled: bool) -> bool:
        if not ENABLE_TRIGGER_SYSTEM:
            self.log_warning("Trigger system is disabled. Cannot set trigger state.")
            return False
        if not hasattr(self.client_logic, 'trigger_manager') or not self.client_logic.trigger_manager:
            self.log_warning("Trigger manager not available. Cannot set trigger state.")
            return False
        try:
            return self.client_logic.trigger_manager.set_trigger_enabled(
                trigger_id, enabled
            )
        except Exception as e:
            self.log_error(f"Error setting trigger state: {e}")
            return False

    # --- Event Subscription ---
    def subscribe_to_event(self, event_name: str, handler_function: Callable):
        self.script_manager.subscribe_script_to_event(
            event_name, handler_function, self.script_name
        )

    def unsubscribe_from_event( # Added this method for completeness
        self, event_name: str, handler_function: Callable
    ):
        self.script_manager.unsubscribe_script_from_event(
            event_name, handler_function, self.script_name
        )

    # --- Command Registration ---
    def register_command(
        self,
        command_name: str,
        handler_function: Callable,
        help_text: str = "", # Default help_text to empty string
        aliases: Optional[List[str]] = None,
    ):
        if aliases is None:
            aliases = []
        self.script_manager.register_command_from_script(
            command_name,
            handler_function,
            help_text,
            aliases,
            script_name=self.script_name,
        )

    # --- Help Text Registration ---
    def register_help_text(
        self,
        command_name: str,
        usage_str: str,
        description_str: str = "",
        aliases: Optional[List[str]] = None,
    ):
        if aliases is None:
            aliases = []
        help_text = usage_str
        if description_str:
            help_text += f"\n{description_str}"
        self.script_manager.register_help_text_from_script(
            command_name=command_name,
            help_text=help_text,
            aliases=aliases,
            script_name=self.script_name,
        )

    # --- Data File Path ---
    def request_data_file_path(self, data_filename: str) -> str: # Renamed from get_data_file_path
        return self.script_manager.get_data_file_path_for_script(
            self.script_name, data_filename
        )

    # --- Message Sending & UI ---
    def add_message_to_context(
        self,
        context_name: str,
        text: str,
        color_key: str = "system",
        prefix_time: bool = True,
    ):
        color_attr = self.client_logic.ui.colors.get(
            color_key, self.client_logic.ui.colors["system"]
        )
        self.client_logic.add_message(
            text, color_attr, prefix_time=prefix_time, context_name=context_name
        )

    # --- Direct IRC Commands ---
    def send_raw(self, command_string: str):
        self.client_logic.network_handler.send_raw(command_string)

    def send_message(self, target: str, message: str):
        self.send_raw(f"PRIVMSG {target} :{message}")

    def send_action(self, target: str, action_text: str):
        if not target or not action_text:
            self.log_warning(
                f"send_action called with empty target ('{target}') or action_text ('{action_text}')."
            )
            return
        self.send_raw(f"PRIVMSG {target} :\x01ACTION {action_text}\x01")

    def send_notice(self, target: str, message: str):
        self.send_raw(f"NOTICE {target} :{message}")

    def join_channel(self, channel_name: str, key: Optional[str] = None):
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name
        cmd = f"JOIN {channel_name}"
        if key:
            cmd += f" {key}"
        self.send_raw(cmd)

    def part_channel(self, channel_name: str, reason: Optional[str] = None):
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name
        cmd = f"PART {channel_name}"
        if reason:
            cmd += f" :{reason}"
        self.send_raw(cmd)

    def set_nick(self, new_nick: str):
        self.send_raw(f"NICK {new_nick}")

    def set_topic(self, channel_name: str, new_topic: str):
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name
        self.send_raw(f"TOPIC {channel_name} :{new_topic}")

    def set_channel_mode(self, channel_name: str, modes: str, *mode_params: str):
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name
        cmd = f"MODE {channel_name} {modes}"
        if mode_params:
            cmd += " " + " ".join(mode_params)
        self.send_raw(cmd)

    def kick_user(self, channel_name: str, nick: str, reason: Optional[str] = None):
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name
        cmd = f"KICK {channel_name} {nick}"
        if reason:
            cmd += f" :{reason}"
        self.send_raw(cmd)

    def invite_user(self, nick: str, channel_name: str):
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name
        self.send_raw(f"INVITE {nick} {channel_name}")

    def quit_client(self, reason: Optional[str] = None): # Renamed from quit
        """Signals the client to quit the IRC server and shut down."""
        self.log_info(f"Script '{self.script_name}' initiated client quit. Reason: {reason}")
        self.client_logic.should_quit = True # Signal main loop to exit
        # The actual QUIT command to server is handled by client_logic's shutdown sequence


    # --- Information Retrieval ---
    def get_client_nick(self) -> Optional[str]: # Changed from get_nick
        return self.client_logic.nick

    def get_current_context_name(self) -> Optional[str]:
        return self.client_logic.context_manager.active_context_name

    def get_active_context_type(self) -> Optional[str]:
        active_ctx = self.client_logic.context_manager.get_active_context()
        return active_ctx.type if active_ctx else None

    def is_connected(self) -> bool:
        return self.client_logic.network_handler.connected

    def get_server_info(self) -> Dict[str, Any]:
        return {
            "server": self.client_logic.server,
            "port": self.client_logic.port,
            "ssl": self.client_logic.use_ssl,
        }

    def get_server_capabilities(self) -> Set[str]:
        return self.client_logic.get_enabled_caps()

    def get_joined_channels(self) -> List[str]:
        return list(self.client_logic.currently_joined_channels)

    def get_channel_users(self, channel_name: str) -> Optional[Dict[str, str]]:
        context = self.client_logic.context_manager.get_context(channel_name)
        if context and context.type == "channel":
            return context.users.copy() if hasattr(context, "users") else {}
        return None

    def get_channel_topic(self, channel_name: str) -> Optional[str]:
        context = self.client_logic.context_manager.get_context(channel_name)
        if context and context.type == "channel":
            return context.topic if hasattr(context, "topic") else None
        return None

    def get_context_info(self, context_name: str) -> Optional[Dict[str, Any]]:
        context = self.client_logic.context_manager.get_context(context_name)
        if not context:
            return None
        info: Dict[str, Any] = {"name": context.name, "type": context.type}
        if hasattr(context, "unread_count"): info["unread_count"] = context.unread_count
        if context.type == "channel":
            if hasattr(context, "topic"): info["topic"] = context.topic
            if hasattr(context, "users"): info["user_count"] = len(context.users)
            if hasattr(context, "join_status") and context.join_status:
                info["join_status"] = context.join_status.name
        return info

    def get_context_messages(
        self, context_name: str, count: Optional[int] = None
    ) -> Optional[List[Tuple[str, Any]]]: # Added type hint for tuple elements
        return self.client_logic.context_manager.get_context_messages_raw(context_name, count)

# END OF MODIFIED FILE: script_api_handler.py
