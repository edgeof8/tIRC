# START OF MODIFIED FILE: script_api_handler.py
import logging
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Callable,
    Tuple,
    Set,
    TYPE_CHECKING,
    Union,
)
import json
import os
from datetime import datetime
from dataclasses import dataclass

import pyrc_core.app_config as app_config

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    from pyrc_core.scripting.script_manager import ScriptManager


@dataclass
class ScriptMetadata:
    name: str
    version: str
    description: str
    author: str
    dependencies: List[str]
    min_pyrc_version: str
    created_at: datetime
    updated_at: datetime
    tags: List[str]
    is_enabled: bool = True
    # ... (rest of ScriptMetadata is unchanged) ...
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "dependencies": self.dependencies,
            "min_pyrc_version": self.min_pyrc_version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
            "is_enabled": self.is_enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScriptMetadata":
        """Create metadata from dictionary."""
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", "Unknown"),
            dependencies=data.get("dependencies", []),
            min_pyrc_version=data.get("min_pyrc_version", "1.0.0"),
            created_at=datetime.fromisoformat(
                data.get("created_at", datetime.now().isoformat())
            ),
            updated_at=datetime.fromisoformat(
                data.get("updated_at", datetime.now().isoformat())
            ),
            tags=data.get("tags", []),
            is_enabled=data.get("is_enabled", True),
        )

    @classmethod
    def load_from_file(cls, file_path: str) -> Optional["ScriptMetadata"]:
        """Load metadata from a JSON file."""
        try:
            if not os.path.exists(file_path):
                return None
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except Exception as e:
            logging.getLogger("pyrc.script_metadata").error(
                f"Error loading metadata from {file_path}: {e}"
            )
            return None

    def save_to_file(self, file_path: str) -> bool:
        """Save metadata to a JSON file."""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=4)
            return True
        except Exception as e:
            logging.getLogger("pyrc.script_metadata").error(
                f"Error saving metadata to {file_path}: {e}"
            )
            return False

class ScriptAPIHandler:
    def __init__(
        self,
        client_logic_ref: "IRCClient_Logic",
        script_manager_ref: "ScriptManager",
        script_name: str,
    ):
        self.client_logic = client_logic_ref
        self.script_manager = script_manager_ref
        self.script_name = script_name
        self.logger = logging.getLogger(f"pyrc.script_api.{script_name}")
        self.metadata: ScriptMetadata = self._load_metadata()
        self._is_loaded: bool = False
        self._last_error: Optional[Exception] = None
        self._performance_metrics: Dict[str, Any] = {
            "start_time": datetime.now(),
            "command_calls": 0,
            "event_handlers": 0,
            "errors": 0,
        }

    def _load_metadata(self) -> ScriptMetadata:
        metadata_path = self.script_manager.get_data_file_path_for_script(
            self.script_name, "metadata.json"
        )
        if os.path.exists(metadata_path):
            try:
                metadata = ScriptMetadata.load_from_file(metadata_path)
                if metadata:
                    return metadata
            except Exception as e:
                self.log_error(f"Error loading metadata: {e}")
        return self._create_default_metadata()

    def _create_default_metadata(self) -> ScriptMetadata:
        return ScriptMetadata(
            name=self.script_name,
            version="1.0.0",
            description="",
            author="Unknown",
            dependencies=[],
            min_pyrc_version="1.0.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            tags=[],
            is_enabled=True,
        )

    def check_dependencies(self) -> Tuple[bool, List[str]]:
        missing = []
        for dep in self.metadata.dependencies:
            if not self.script_manager.is_script_enabled(dep):
                missing.append(dep)
        return len(missing) == 0, missing

    def log_info(self, message: str):
        self.logger.info(message)

    def log_warning(self, message: str):
        self.logger.warning(message)

    def log_error(self, message: str):
        self.logger.error(message)

    def add_trigger(
        self, event_type: str, pattern: str, action_type: str, action_content: str
    ) -> Optional[int]:
        if not app_config.ENABLE_TRIGGER_SYSTEM:
            self.log_warning("Trigger system is disabled. Cannot add trigger.")
            return None
        if (
            not hasattr(self.client_logic, "trigger_manager")
            or not self.client_logic.trigger_manager
        ):
            self.log_warning("Trigger manager not available. Cannot add trigger.")
            return None
        try:
            return self.client_logic.trigger_manager.add_trigger(
                event_type_str=event_type,
                pattern=pattern,
                action_type_str=action_type,
                action_content=action_content,
            )
        except Exception as e:
            self.log_error(f"Error adding trigger: {e}")
            return None

    def remove_trigger(self, trigger_id: int) -> bool:
        if not app_config.ENABLE_TRIGGER_SYSTEM:
            self.log_warning("Trigger system is disabled. Cannot remove trigger.")
            return False
        if (
            not hasattr(self.client_logic, "trigger_manager")
            or not self.client_logic.trigger_manager
        ):
            self.log_warning("Trigger manager not available. Cannot remove trigger.")
            return False
        try:
            return self.client_logic.trigger_manager.remove_trigger(trigger_id)
        except Exception as e:
            self.log_error(f"Error removing trigger: {e}")
            return False

    def list_triggers(
        self, event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if not app_config.ENABLE_TRIGGER_SYSTEM:
            self.log_warning("Trigger system is disabled. Cannot list triggers.")
            return []
        if (
            not hasattr(self.client_logic, "trigger_manager")
            or not self.client_logic.trigger_manager
        ):
            self.log_warning("Trigger manager not available. Cannot list triggers.")
            return []
        try:
            return self.client_logic.trigger_manager.list_triggers(
                event_type=event_type
            )
        except Exception as e:
            self.log_error(f"Error listing triggers: {e}")
            return []

    def set_trigger_enabled(self, trigger_id: int, enabled: bool) -> bool:
        if not app_config.ENABLE_TRIGGER_SYSTEM:
            self.log_warning("Trigger system is disabled. Cannot set trigger state.")
            return False
        if (
            not hasattr(self.client_logic, "trigger_manager")
            or not self.client_logic.trigger_manager
        ):
            self.log_warning("Trigger manager not available. Cannot set trigger state.")
            return False
        try:
            return self.client_logic.trigger_manager.set_trigger_enabled(
                trigger_id, enabled
            )
        except Exception as e:
            self.log_error(f"Error setting trigger state: {e}")
            return False

    def subscribe_to_event(self, event_name: str, handler_function: Callable):
        self.script_manager.subscribe_script_to_event(
            event_name, handler_function, self.script_name
        )

    def unsubscribe_from_event(
        self, event_name: str, handler_function: Callable
    ):
        self.script_manager.unsubscribe_script_from_event(
            event_name, handler_function, self.script_name
        )

    def create_command_help(
        self, usage: str, description: str, aliases: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        help_data: Dict[str, Any] = {"usage": usage, "description": description}
        if aliases:
            help_data["aliases"] = aliases
        return help_data

    def register_command(
        self,
        command_name: str,
        handler_function: Callable,
        help_info: Union[str, Dict[str, Any]] = "",
        aliases: Optional[List[str]] = None,
    ):
        effective_aliases: List[str] = aliases if aliases is not None else []

        if isinstance(help_info, dict):
            # Ensure 'aliases' from help_info is a list of strings if it exists
            help_info_aliases = help_info.get("aliases")
            if isinstance(help_info_aliases, list):
                # Use aliases from help_info if provided and valid, otherwise keep effective_aliases
                # This prioritizes aliases from the help_info dict if present.
                effective_aliases = [str(a) for a in help_info_aliases if isinstance(a, str)]
            # If help_info is a dict but 'aliases' key is missing or not a list,
            # effective_aliases will retain the value from the 'aliases' parameter.

        self.script_manager.register_command_from_script(
            command_name,
            handler_function,
            help_info,
            effective_aliases,
            script_name=self.script_name,
        )

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

    def request_data_file_path(self, data_filename: str) -> str:
        return self.script_manager.get_data_file_path_for_script(
            self.script_name, data_filename
        )

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

    def quit_client(self, reason: Optional[str] = None):
        self.log_info(
            f"Script '{self.script_name}' initiated client quit. Reason: {reason}"
        )
        self.client_logic.should_quit = True

    def execute_client_command(self, command_line_with_slash: str) -> bool:
        if not command_line_with_slash.startswith("/"):
            self.log_error(
                f"execute_client_command: Command line '{command_line_with_slash}' must start with '/'"
            )
            return False
        self.log_info(f"Executing client command via API: {command_line_with_slash}")
        return self.client_logic.command_handler.process_user_command(
            command_line_with_slash
        )

    def get_client_nick(self) -> Optional[str]:
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
        if hasattr(context, "unread_count"):
            info["unread_count"] = context.unread_count
        if context.type == "channel":
            if hasattr(context, "topic"):
                info["topic"] = context.topic
            if hasattr(context, "users"):
                info["user_count"] = len(context.users)
            if hasattr(context, "join_status") and context.join_status:
                info["join_status"] = context.join_status.name
        return info

    def get_context_messages(
        self, context_name: str, count: Optional[int] = None
    ) -> Optional[List[Tuple[str, Any]]]:
        return self.client_logic.context_manager.get_context_messages_raw(
            context_name, count
        )

    def DEV_TEST_ONLY_clear_context_messages(self, context_name: str) -> bool:
        self.log_warning(
            f"DEV_TEST_ONLY_clear_context_messages called for {context_name}"
        )
        ctx = self.client_logic.context_manager.get_context(context_name)
        if ctx:
            if hasattr(ctx, "messages") and callable(
                getattr(ctx.messages, "clear", None)
            ):
                ctx.messages.clear()
                self.client_logic.ui_needs_update.set()
                self.log_info(
                    f"DEV_TEST_ONLY: Messages cleared for context {context_name}"
                )
                return True
            else:
                self.log_error(
                    f"DEV_TEST_ONLY: Context {context_name} does not have a clearable messages attribute."
                )
                return False
        else:
            self.log_error(f"DEV_TEST_ONLY: Context {context_name} not found.")
            return False

    def get_script_stats(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "performance": self._performance_metrics,
            "last_error": str(self._last_error) if self._last_error else None,
            "is_loaded": self._is_loaded,
            "uptime": (
                datetime.now() - self._performance_metrics["start_time"]
            ).total_seconds(),
            "command_calls": self._performance_metrics["command_calls"],
            "event_handlers": self._performance_metrics["event_handlers"],
            "errors": self._performance_metrics["errors"],
        }

    def get_script_health(self) -> Dict[str, Any]:
        satisfied, missing = self.check_dependencies()
        return {
            "is_healthy": satisfied and not self._last_error,
            "dependencies_satisfied": satisfied,
            "missing_dependencies": missing,
            "has_error": bool(self._last_error),
            "last_error": str(self._last_error) if self._last_error else None,
            "is_enabled": self.metadata.is_enabled,
            "is_loaded": self._is_loaded,
        }

    def get_script_config(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "data_directory": self.get_script_data_dir(),
            "is_enabled": self.metadata.is_enabled,
            "dependencies": self.metadata.dependencies,
            "min_pyrc_version": self.metadata.min_pyrc_version,
        }

    def get_script_data_dir(self) -> str:
        return self.script_manager.get_data_file_path_for_script(self.script_name, "")

    def save_script_data(self, data: Dict[str, Any], filename: str) -> bool:
        try:
            file_path = self.script_manager.get_data_file_path_for_script(
                self.script_name, filename
            )
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            return True
        except Exception as e:
            self.log_error(f"Error saving script data: {e}")
            return False

    def load_script_data(self, filename: str) -> Optional[Dict[str, Any]]:
        try:
            file_path = self.script_manager.get_data_file_path_for_script(
                self.script_name, filename
            )
            if not os.path.exists(file_path):
                return None
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.log_error(f"Error loading script data: {e}")
            return None

    def get_script_events(self) -> List[str]:
        return [
            event_name
            for event_name, handlers in self.script_manager.event_subscriptions.items()
            if any(handler["script_name"] == self.script_name for handler in handlers)
        ]

    def get_script_commands(self) -> List[Dict[str, Any]]:
        return [
            cmd_data
            for cmd_name, cmd_data in self.script_manager.registered_commands.items()
            if cmd_data.get("script_name") == self.script_name
        ]

    def get_script_triggers(self) -> List[Dict[str, Any]]:
        if (
            not hasattr(self.client_logic, "trigger_manager")
            or not self.client_logic.trigger_manager
        ):
            return []
        return [
            trigger.to_dict()
            for trigger in self.client_logic.trigger_manager.triggers.values()
            if trigger.created_by == self.script_name
        ]

# END OF MODIFIED FILE: script_api_handler.py
