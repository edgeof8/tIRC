import json
import os
import logging
from typing import Any, Dict, List, Optional, Set, Callable, TypeVar, Generic
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
import threading
from pathlib import Path

# Type variable for state value
T = TypeVar("T")


class StateChangeType(Enum):
    """Types of state changes that can occur."""

    CREATED = auto()
    UPDATED = auto()
    DELETED = auto()
    VALIDATED = auto()
    INVALIDATED = auto()


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

        # Load initial state
        self._load_state()

        # Start auto-save timer if enabled
        if self.auto_save:
            self._start_auto_save()

    def _load_state(self) -> None:
        """Load state from file."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self._state = json.load(f)
                self.logger.info(f"Loaded state from {self.state_file}")
        except Exception as e:
            self.logger.error(f"Error loading state: {e}")
            self._state = {}

    def _save_state(self) -> None:
        """Save state to file."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=4)
            self.logger.info(f"Saved state to {self.state_file}")
        except Exception as e:
            self.logger.error(f"Error saving state: {e}")

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
