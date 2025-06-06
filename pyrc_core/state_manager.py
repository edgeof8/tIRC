import json
import os
import logging
import dataclasses
from typing import Any, Dict, List, Optional, Set, Callable, TypeVar, Generic, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum, auto
import threading
from pathlib import Path
import time
from json import JSONEncoder

# Type variable for state value
T = TypeVar("T")


class StateChangeType(Enum):
    """Types of state changes that can occur."""

    CREATED = auto()
    UPDATED = auto()
    DELETED = auto()
    VALIDATED = auto()
    INVALIDATED = auto()


class ConnectionState(Enum):
    """Possible connection states."""

    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    REGISTERED = auto()
    READY = auto()
    ERROR = auto()
    CONFIG_ERROR = auto()  # New state for configuration issues


@dataclass
class ConnectionInfo:
    """Holds all state related to a single server connection."""
    server: str
    port: int
    ssl: bool
    nick: str
    username: Optional[str] = None
    realname: Optional[str] = None
    server_password: Optional[str] = None
    nickserv_password: Optional[str] = None
    sasl_username: Optional[str] = None
    sasl_password: Optional[str] = None
    verify_ssl_cert: bool = True
    auto_connect: bool = False
    initial_channels: List[str] = field(default_factory=list)
    desired_caps: List[str] = field(default_factory=list)
    # Runtime state
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    connection_attempts: int = 0
    last_connection_attempt: Optional[datetime] = None
    last_successful_connection: Optional[datetime] = None
    config_errors: List[str] = field(default_factory=list)
    # Runtime state not from config
    user_modes: List[str] = field(default_factory=list)
    currently_joined_channels: Set[str] = field(default_factory=set)
    last_attempted_nick_change: Optional[str] = None


@dataclass
class StateChange(Generic[T]):
    """Represents a state change event."""

    key: str
    old_value: Optional[T]
    new_value: Optional[T]
    change_type: StateChangeType
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class StateValidator(Generic[T]):
    """Base class for state validators."""

    def validate(self, value: T) -> bool:
        """Validate a state value."""
        return True

    def get_error_message(self, value: T) -> Optional[str]:
        """Get error message for invalid state."""
        return None


class ConnectionStateValidator(StateValidator[ConnectionInfo]):
    """Validator for connection information."""

    def validate(self, value: ConnectionInfo) -> bool:
        """Validate connection information."""
        value.config_errors.clear()  # Clear previous errors

        if not value.server:
            value.config_errors.append("Server address is required")
            return False

        if not value.port or value.port < 1 or value.port > 65535:
            value.config_errors.append(
                f"Port must be between 1 and 65535 (got {value.port})"
            )
            return False

        if not value.nick:
            value.config_errors.append("Nickname is required")
            return False

        # Validate SSL configuration
        if value.ssl and value.port not in [6697, 6698, 6699]:
            value.config_errors.append(
                f"SSL typically uses ports 6697-6699 (got {value.port})"
            )
            return False

        # Validate SASL configuration
        if value.sasl_username and not value.sasl_password:
            value.config_errors.append("SASL username provided but no password")
            return False

        # Validate NickServ configuration
        if value.nickserv_password and not value.username:
            value.config_errors.append("NickServ password provided but no username")
            return False

        return True

    def get_error_message(self, value: ConnectionInfo) -> Optional[str]:
        """Get error message for invalid connection info."""
        if value.config_errors:
            return "\n".join(value.config_errors)
        return None


class StateManager:
    """Manages application state with persistence and validation."""

    def __init__(
        self,
        state_file: str = "state.json",
        auto_save: bool = True,
        save_interval: int = 60,  # seconds
        validate_on_change: bool = True,
    ):
        self.logger = logging.getLogger("pyrc.state_manager")
        self.state_file = state_file
        self.auto_save = auto_save
        self.save_interval = save_interval
        self.validate_on_change = validate_on_change

        # State storage
        self._state: Dict[str, Any] = {}
        self._validators: Dict[str, StateValidator] = {}
        self._change_handlers: Dict[str, List[Callable[[StateChange], None]]] = {}
        self._global_handlers: List[Callable[[StateChange], None]] = []

        # Thread safety
        self._lock = threading.RLock()
        self._save_timer: Optional[threading.Timer] = None

        # Initialize connection state
        self._state["connection_state"] = ConnectionState.DISCONNECTED
        self._state["connection_info"] = None
        self._state["last_error"] = None
        self._state["connection_attempts"] = 0
        self._state["last_connection_attempt"] = None
        self._state["last_successful_connection"] = None
        self._state["config_errors"] = []

        # Register connection state validator
        self.register_validator("connection_info", ConnectionStateValidator())

        # Load initial state
        self._load_state()

        # Start auto-save timer if enabled
        if self.auto_save:
            self._start_auto_save()

    def _load_state(self) -> None:
        """Load state from file with proper type conversion."""
        if not os.path.exists(self.state_file):
            self.logger.info(f"No state file found at {self.state_file}, using default state")
            return

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)

            # Deserialize special types
            if "connection_state" in loaded_data and loaded_data["connection_state"] is not None:
                try:
                    state_name = loaded_data["connection_state"]
                    if isinstance(state_name, str):
                        loaded_data["connection_state"] = ConnectionState[state_name]
                except (KeyError, TypeError) as e:
                    self.logger.warning(f"Invalid connection_state '{loaded_data.get('connection_state')}' in state file: {e}")
                    loaded_data["connection_state"] = ConnectionState.DISCONNECTED
            
            if "connection_info" in loaded_data and loaded_data["connection_info"] is not None:
                try:
                    # Convert string timestamps back to datetime objects
                    conn_info = loaded_data["connection_info"]
                    for time_field in ["last_error_time", "last_connection_attempt", "last_successful_connection"]:
                        if time_field in conn_info and conn_info[time_field] is not None:
                            conn_info[time_field] = datetime.fromisoformat(conn_info[time_field])
                    
                    # Re-create the ConnectionInfo dataclass from the dictionary
                    loaded_data["connection_info"] = ConnectionInfo(**conn_info)
                except (TypeError, KeyError, ValueError) as e:
                    self.logger.error(f"Failed to load connection_info from state file: {e}")
                    loaded_data["connection_info"] = None

            # Update the state with the loaded data
            self._state.update(loaded_data)
            self.logger.info(f"Successfully loaded state from {self.state_file}")

        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON from state file {self.state_file}: {e}")
            # Backup the corrupted file
            try:
                backup_file = f"{self.state_file}.bak_{int(time.time())}"
                os.rename(self.state_file, backup_file)
                self.logger.info(f"Backed up corrupted state file to {backup_file}")
            except OSError as backup_error:
                self.logger.error(f"Failed to backup corrupted state file: {backup_error}")
        except Exception as e:
            self.logger.error(f"Unexpected error loading state: {e}", exc_info=True)

    def _save_state(self) -> None:
        """Save state to file with proper serialization of custom types."""
        try:
            # Create a serializable copy of the state
            serializable_state = {}
            for key, value in self._state.items():
                if key == "connection_state" and value is not None:
                    # Convert Enum to its name
                    serializable_state[key] = value.name
                elif key == "connection_info" and value is not None:
                    # Convert ConnectionInfo to dict and handle datetime fields
                    conn_dict = asdict(value)
                    # Convert datetime objects to ISO format strings
                    for time_field in ["last_error_time", "last_connection_attempt", "last_successful_connection"]:
                        if time_field in conn_dict and conn_dict[time_field] is not None:
                            conn_dict[time_field] = conn_dict[time_field].isoformat()
                    serializable_state[key] = conn_dict
                else:
                    serializable_state[key] = value

            # Ensure the directory exists
            os.makedirs(os.path.dirname(os.path.abspath(self.state_file)), exist_ok=True)
            
            # Write to a temporary file first, then rename to ensure atomic write
            temp_file = f"{self.state_file}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(serializable_state, f, indent=4, ensure_ascii=False)
            
            # On Windows, we need to remove the destination file first if it exists
            if os.path.exists(self.state_file):
                os.replace(temp_file, self.state_file)
            else:
                os.rename(temp_file, self.state_file)
                
            self.logger.debug(f"Successfully saved state to {self.state_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving state to {self.state_file}: {e}", exc_info=True)
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception as cleanup_error:
                self.logger.error(f"Failed to clean up temporary file {temp_file}: {cleanup_error}")

    def _start_auto_save(self) -> None:
        """Start the auto-save timer."""
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(self.save_interval, self._auto_save)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _auto_save(self) -> None:
        """Auto-save callback."""
        with self._lock:
            self._save_state()
        self._start_auto_save()

    def register_validator(self, key: str, validator: StateValidator) -> None:
        """Register a validator for a state key."""
        with self._lock:
            self._validators[key] = validator

    def unregister_validator(self, key: str) -> None:
        """Unregister a validator for a state key."""
        with self._lock:
            self._validators.pop(key, None)

    def register_change_handler(
        self, key: str, handler: Callable[[StateChange], None]
    ) -> None:
        """Register a handler for state changes on a specific key."""
        with self._lock:
            if key not in self._change_handlers:
                self._change_handlers[key] = []
            self._change_handlers[key].append(handler)

    def register_global_handler(self, handler: Callable[[StateChange], None]) -> None:
        """Register a handler for all state changes."""
        with self._lock:
            self._global_handlers.append(handler)

    def unregister_change_handler(
        self, key: str, handler: Callable[[StateChange], None]
    ) -> None:
        """Unregister a handler for state changes on a specific key."""
        with self._lock:
            if key in self._change_handlers:
                self._change_handlers[key].remove(handler)

    def unregister_global_handler(self, handler: Callable[[StateChange], None]) -> None:
        """Unregister a global state change handler."""
        with self._lock:
            if handler in self._global_handlers:
                self._global_handlers.remove(handler)

    def _notify_handlers(self, change: StateChange) -> None:
        """Notify all relevant handlers of a state change."""
        # Notify key-specific handlers
        if change.key in self._change_handlers:
            for handler in self._change_handlers[change.key]:
                try:
                    handler(change)
                except Exception as e:
                    self.logger.error(f"Error in change handler: {e}")

        # Notify global handlers
        for handler in self._global_handlers:
            try:
                handler(change)
            except Exception as e:
                self.logger.error(f"Error in global handler: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a state value."""
        with self._lock:
            return self._state.get(key, default)

    def set(
        self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Set a state value with validation."""
        with self._lock:
            old_value = self._state.get(key)

            # Validate if enabled and validator exists
            if self.validate_on_change and key in self._validators:
                validator = self._validators[key]
                if not validator.validate(value):
                    error_msg = validator.get_error_message(value)
                    self.logger.error(f"State validation failed for {key}: {error_msg}")
                    return False

            # Update state
            self._state[key] = value

            # Create and notify of change
            change = StateChange(
                key=key,
                old_value=old_value,
                new_value=value,
                change_type=(
                    StateChangeType.CREATED
                    if old_value is None
                    else StateChangeType.UPDATED
                ),
                metadata=metadata or {},
            )
            self._notify_handlers(change)

            # Auto-save if enabled
            if self.auto_save:
                self._save_state()

            return True

    def delete(self, key: str) -> bool:
        """Delete a state value."""
        with self._lock:
            if key in self._state:
                old_value = self._state[key]
                del self._state[key]

                # Create and notify of change
                change = StateChange(
                    key=key,
                    old_value=old_value,
                    new_value=None,
                    change_type=StateChangeType.DELETED,
                )
                self._notify_handlers(change)

                # Auto-save if enabled
                if self.auto_save:
                    self._save_state()

                return True
            return False

    def clear(self) -> None:
        """Clear all state."""
        with self._lock:
            old_state = self._state.copy()
            self._state.clear()

            # Notify of all deletions
            for key, value in old_state.items():
                change = StateChange(
                    key=key,
                    old_value=value,
                    new_value=None,
                    change_type=StateChangeType.DELETED,
                )
                self._notify_handlers(change)

            # Auto-save if enabled
            if self.auto_save:
                self._save_state()

    def get_all(self) -> Dict[str, Any]:
        """Get all state values."""
        with self._lock:
            return self._state.copy()

    def validate_all(self) -> Dict[str, str]:
        """Validate all state values with registered validators."""
        errors = {}
        with self._lock:
            for key, validator in self._validators.items():
                if key in self._state:
                    value = self._state[key]
                    if not validator.validate(value):
                        error_msg = validator.get_error_message(value)
                        errors[key] = error_msg or "Validation failed"
        return errors

    def shutdown(self) -> None:
        """Clean up resources."""
        if self._save_timer:
            self._save_timer.cancel()
        if self.auto_save:
            self._save_state()

    # Connection state management methods
    def set_connection_state(
        self,
        state: ConnectionState,
        error: Optional[str] = None,
        config_errors: Optional[List[str]] = None,
    ) -> None:
        """Update connection state and optionally set error."""
        with self._lock:
            old_state = self._state.get("connection_state")
            self._state["connection_state"] = state

            if error:
                self._state["last_error"] = error

            if config_errors:
                self._state["config_errors"] = config_errors
                if state != ConnectionState.CONFIG_ERROR:
                    self.logger.warning(f"Setting config errors but state is {state}")

            change = StateChange(
                key="connection_state",
                old_value=old_state,
                new_value=state,
                change_type=StateChangeType.UPDATED,
                metadata=(
                    {"error": error, "config_errors": config_errors}
                    if error or config_errors
                    else {}
                ),
            )
            self._notify_handlers(change)

    def set_connection_info(self, info: ConnectionInfo) -> bool:
        """Set connection information with validation."""
        with self._lock:
            # Validate connection info
            validator = self._validators.get("connection_info")
            if validator and not validator.validate(info):
                error_msg = validator.get_error_message(info)
                self.set_connection_state(
                    ConnectionState.CONFIG_ERROR, error_msg, info.config_errors
                )
                return False

            # Update connection info
            success = self.set("connection_info", info)
            if success:
                # Clear any previous config errors
                self._state["config_errors"] = []
            return success

    def get_connection_state(self) -> ConnectionState:
        """Get current connection state."""
        with self._lock:
            return self._state.get("connection_state", ConnectionState.DISCONNECTED)

    def get_connection_info(self) -> Optional[ConnectionInfo]:
        """Get current connection information."""
        with self._lock:
            return self._state.get("connection_info")

    def get_last_error(self) -> Optional[str]:
        """Get last connection error."""
        with self._lock:
            return self._state.get("last_error")

    def get_config_errors(self) -> List[str]:
        """Get current configuration errors."""
        with self._lock:
            return self._state.get("config_errors", [])

    def update_connection_attempt(
        self,
        success: bool,
        error: Optional[str] = None,
        config_errors: Optional[List[str]] = None,
    ) -> None:
        """Update connection attempt statistics."""
        with self._lock:
            info = self._state.get("connection_info")
            if info:
                info.connection_attempts += 1
                info.last_connection_attempt = datetime.now()
                if success:
                    info.last_successful_connection = datetime.now()
                    info.last_error = None
                    info.last_error_time = None
                    info.config_errors = []
                else:
                    info.last_error = error
                    info.last_error_time = datetime.now()
                    if config_errors:
                        info.config_errors = config_errors
                self.set("connection_info", info)

            # Update global connection statistics
            self._state["connection_attempts"] = (
                self._state.get("connection_attempts", 0) + 1
            )
            self._state["last_connection_attempt"] = datetime.now()
            if success:
                self._state["last_successful_connection"] = datetime.now()
                self._state["last_error"] = None
                self._state["config_errors"] = []
            else:
                self._state["last_error"] = error
                if config_errors:
                    self._state["config_errors"] = config_errors

    def get_connection_statistics(self) -> Dict[str, Any]:
        """Get connection statistics."""
        with self._lock:
            return {
                "connection_attempts": self._state.get("connection_attempts", 0),
                "last_connection_attempt": self._state.get("last_connection_attempt"),
                "last_successful_connection": self._state.get(
                    "last_successful_connection"
                ),
                "last_error": self._state.get("last_error"),
                "config_errors": self._state.get("config_errors", []),
                "current_state": self.get_connection_state().name,
            }
