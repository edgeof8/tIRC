import json
import os
import logging
import inspect

# Debug: Verify this file is being loaded
logger = logging.getLogger("tirc.debug")
logger.debug(f"Loading StateManager from: {os.path.abspath(__file__)}")

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
import asyncio

# Type variable for state value
T = TypeVar("T")


class StateEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle Enum, datetime, and set objects."""
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.name
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, '__contains__') and hasattr(obj, '__iter__') and hasattr(obj, '__len__'):
            return list(obj)
        return super().default(obj)


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
    """
    Holds all dynamic runtime state related to a single server connection.
    This dataclass is managed by `StateManager` and is distinct from `ServerConfig`
    which holds static configuration loaded from `AppConfig`.

    Attributes:
        server (str): The server address (hostname or IP).
        port (int): The port to connect to.
        ssl (bool): True if SSL/TLS should be used for the connection.
        nick (str): The current nickname in use.
        username (Optional[str]): The username sent during USER registration.
        realname (Optional[str]): The real name sent during USER registration.
        server_password (Optional[str]): Password for connecting to the server.
        nickserv_password (Optional[str]): Password for NickServ identification.
        sasl_username (Optional[str]): Username for SASL PLAIN authentication.
        sasl_password (Optional[str]): Password for SASL PLAIN authentication.
        verify_ssl_cert (bool): True to verify SSL certificates.
        auto_connect (bool): True if this server was configured for auto-connect.
        initial_channels (List[str]): Channels configured to auto-join.
        desired_caps (List[str]): IRCv3 capabilities requested.

        # Runtime state (not from AppConfig)
        last_error (Optional[str]): The last error message encountered during connection.
        last_error_time (Optional[datetime]): Timestamp of the last error.
        connection_attempts (int): Count of connection attempts.
        last_connection_attempt (Optional[datetime]): Timestamp of the last connection attempt.
        last_successful_connection (Optional[datetime]): Timestamp of the last successful connection.
        config_errors (List[str]): List of configuration validation errors.
        user_modes (List[str]): Current user modes (e.g., '+i', '+w').
        currently_joined_channels (Set[str]): Set of channels currently joined.
        last_attempted_nick_change (Optional[str]): The last nickname attempted to change to.
    """
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
    # Runtime state (not from config)
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    connection_attempts: int = 0
    last_connection_attempt: Optional[datetime] = None
    last_successful_connection: Optional[datetime] = None
    config_errors: List[str] = field(default_factory=list)
    user_modes: List[str] = field(default_factory=list)
    currently_joined_channels: Set[str] = field(default_factory=set)
    last_attempted_nick_change: Optional[str] = None


@dataclass
class StateChange(Generic[T]):
    """
    Represents a state change event, dispatched by the `StateManager`.

    Attributes:
        key (str): The key of the state that changed.
        old_value (Optional[T]): The value of the state before the change.
        new_value (Optional[T]): The new value of the state after the change.
        change_type (StateChangeType): The type of change (e.g., CREATED, UPDATED, DELETED).
        timestamp (datetime): The time when the change occurred.
        metadata (Dict[str, Any]): Additional metadata related to the change.
    """
    key: str
    old_value: Optional[T]
    new_value: Optional[T]
    change_type: StateChangeType
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class StateValidator(Generic[T]):
    """
    Base class for state validators. Subclasses implement specific validation logic
    for different parts of the application state.
    """

    def validate(self, value: T) -> bool:
        """
        Validates a given state value.

        Args:
            value (T): The state value to validate.

        Returns:
            bool: True if the value is valid, False otherwise.
        """
        return True

    def get_error_message(self, value: T) -> Optional[str]:
        """
        Returns an error message if the state value is invalid.

        Args:
            value (T): The state value that failed validation.

        Returns:
            Optional[str]: A string describing the validation error, or None if no error.
        """
        return None


class ConnectionStateValidator(StateValidator[ConnectionInfo]):
    """
    A specific validator for the `ConnectionInfo` dataclass, ensuring that
    connection parameters are valid before being set in the `StateManager`.
    """

    def validate(self, value: ConnectionInfo) -> bool:
        """
        Validates the provided `ConnectionInfo` object.
        Populates `value.config_errors` with specific error messages.

        Args:
            value (ConnectionInfo): The connection information to validate.

        Returns:
            bool: True if the `ConnectionInfo` is valid, False otherwise.
        """
        value.config_errors.clear()  # Clear previous errors

        if not value.server:
            value.config_errors.append("Server address is required.")

        if not value.port or not (1 <= value.port <= 65535):
            value.config_errors.append(
                f"Port must be between 1 and 65535 (got {value.port})."
            )

        if not value.nick:
            value.config_errors.append("Nickname is required.")

        # Validate SSL configuration
        if value.ssl and value.port not in [6697, 6698, 6699]:
            value.config_errors.append(
                f"SSL typically uses ports 6697-6699 (got {value.port})."
            )

        # Validate SASL configuration
        if value.sasl_username and not value.sasl_password:
            value.config_errors.append("SASL username provided but no password.")

        # Validate NickServ configuration
        # Note: NickServ can be used without a username if the server allows it,
        # but typically it's used with a registered username. This check
        # ensures consistency if a password is given but no username to associate it with.
        if value.nickserv_password and not value.username:
            value.config_errors.append("NickServ password provided but no username for registration.")

        return not bool(value.config_errors)


    def get_error_message(self, value: ConnectionInfo) -> Optional[str]:
        """
        Retrieves a consolidated error message from the `ConnectionInfo` object's
        `config_errors` list.

        Args:
            value (ConnectionInfo): The `ConnectionInfo` object containing validation errors.

        Returns:
            Optional[str]: A newline-separated string of error messages, or None if no errors.
        """
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
        self.logger = logging.getLogger("tirc.state_manager")

        # Debug: Verify methods exist on this instance
        required_methods = ['set_connection_info', 'get_connection_info']
        missing_methods = [m for m in required_methods if not hasattr(self, m)]
        if missing_methods:
            self.logger.error(f"StateManager instance MISSING METHODS: {', '.join(missing_methods)}")
        else:
            self.logger.debug("StateManager instance has all required methods")
        self.state_file = state_file
        self.auto_save = auto_save
        self.save_interval = save_interval
        self.validate_on_change = validate_on_change

        # State storage
        self._state: Dict[str, Any] = {}
        self._validators: Dict[str, StateValidator] = {}
        self._change_handlers: Dict[str, List[Callable[[StateChange], Any]]] = {}
        self._global_handlers: List[Callable[[StateChange], Any]] = []
        self.loop = None

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

                    # Explicitly convert lists back to sets for fields that are defined as sets
                    if "currently_joined_channels" in conn_info and isinstance(conn_info["currently_joined_channels"], list):
                        conn_info["currently_joined_channels"] = set(conn_info["currently_joined_channels"])  # type: ignore
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
                json.dump(serializable_state, f, indent=4, ensure_ascii=False, cls=StateEncoder)

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
        self, key: str, handler: Callable[[StateChange], Any]
    ) -> None:
        """Register a handler for state changes on a specific key."""
        with self._lock:
            if key not in self._change_handlers:
                self._change_handlers[key] = []
            self._change_handlers[key].append(handler)

    def register_global_handler(self, handler: Callable[[StateChange], Any]) -> None:
        """Register a handler for all state changes."""
        with self._lock:
            self._global_handlers.append(handler)

    def unregister_change_handler(
        self, key: str, handler: Callable[[StateChange], Any]
    ) -> None:
        """Unregister a handler for state changes on a specific key."""
        with self._lock:
            if key in self._change_handlers:
                self._change_handlers[key].remove(handler)

    def unregister_global_handler(self, handler: Callable[[StateChange], Any]) -> None:
        """Unregister a global state change handler."""
        with self._lock:
            if handler in self._global_handlers:
                self._global_handlers.remove(handler)

    async def _notify_handlers(self, change: StateChange) -> None:
        """Notify all relevant handlers of a state change."""
        # Notify key-specific handlers
        if change.key in self._change_handlers:
            for handler in self._change_handlers[change.key]:
                try:
                    result = handler(change)
                    if asyncio.iscoroutine(result):
                        if self.loop and self.loop.is_running():
                            await result
                        else:
                            self.logger.warning(f"Async handler for key '{change.key}' called when no loop is running: {handler.__name__}. Not awaiting.")
                    # If it's not a coroutine, just execute it (it's synchronous)
                except Exception as e:
                    self.logger.error(f"Error in change handler for key '{change.key}': {e}", exc_info=True)

        # Notify global handlers
        for handler in self._global_handlers:
            try:
                result = handler(change)
                if asyncio.iscoroutine(result):
                    if self.loop and self.loop.is_running():
                        await result
                    else:
                        self.logger.warning(f"Async global handler called when no loop is running: {handler.__name__}. Not awaiting.")
                # If it's not a coroutine, just execute it (it's synchronous)
            except Exception as e:
                self.logger.error(f"Error in global handler: {e}", exc_info=True)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a state value."""
        with self._lock:
            return self._state.get(key, default)

    async def set(
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
            await self._notify_handlers(change)

            # Auto-save if enabled
            if self.auto_save:
                self._save_state()

            return True

    async def delete(self, key: str) -> bool:
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
                await self._notify_handlers(change)

                # Auto-save if enabled
                if self.auto_save:
                    self._save_state()

                return True
            return False

    async def clear(self) -> None:
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
                await self._notify_handlers(change)

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

    def reset_session_state(self) -> None:
        """
        Resets the dynamic state for a new session, clearing any loaded
        connection info and related runtime data. This is called at startup
        to prevent stale data from `state.json` from affecting the new session.
        """
        with self._lock:
            self.logger.info("Resetting session state for new run...")
            self._state["connection_info"] = None
            self._state["connection_state"] = ConnectionState.DISCONNECTED
            self._state["last_error"] = None
            # We can keep connection_attempts for historical data, or reset it too.
            # For now, let's reset it for a truly clean session.
            self._state["connection_attempts"] = 0
            self.logger.info("Session state has been reset.")

    # Connection state management methods
    async def set_connection_state(
        self,
        state: ConnectionState,
        error: Optional[str] = None,
        config_errors: Optional[List[str]] = None,
    ) -> None:
        """Update connection state and optionally set error."""
        with self._lock:
            if self.loop is None:
                self.loop = asyncio.get_event_loop()
            old_state = self._state.get("connection_state")
            self._state["connection_state"] = state

            if error:
                self._state["last_error"] = error

            if config_errors:
                self._state["config_errors"] = config_errors
                if state != ConnectionState.CONFIG_ERROR:
                    self.logger.warning(f"Setting config errors but state is {state}")

            metadata_dict = {"error": error, "config_errors": config_errors} if error or config_errors else {}

            # If disconnecting, capture a snapshot of the current connection_info
            if state == ConnectionState.DISCONNECTED and self.get("connection_info") is not None:
                # Convert ConnectionInfo dataclass to a dictionary for serialization in metadata
                metadata_dict["connection_info_snapshot"] = asdict(self.get("connection_info"))

            change = StateChange(
                key="connection_state",
                old_value=old_state,
                new_value=state,
                change_type=StateChangeType.UPDATED,
                metadata=metadata_dict,
            )

            await self._notify_handlers(change)

    async def set_connection_info(self, info: ConnectionInfo) -> bool:
        """Set connection information with validation."""
        with self._lock:
            # Validate connection info
            validator = self._validators.get("connection_info")
            if validator and not validator.validate(info):
                error_msg = validator.get_error_message(info)
                await self.set_connection_state(
                    ConnectionState.CONFIG_ERROR, error_msg, info.config_errors
                )
                return False

            # Update connection info
            success = await self.set("connection_info", info)
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

    async def update_connection_attempt(
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
                await self.set("connection_info", info)

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
