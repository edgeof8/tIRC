# trigger_manager.py
import re
import json
import logging
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum, auto

logger = logging.getLogger("pyrc.triggers")


class TriggerType(Enum):
    TEXT = auto()
    ACTION = auto()
    JOIN = auto()
    PART = auto()
    QUIT = auto()
    KICK = auto()
    MODE = auto()
    TOPIC = auto()
    NICK = auto()
    NOTICE = auto()
    INVITE = auto()
    CTCP = auto()
    RAW = auto()


@dataclass
class Trigger:
    id: int
    event_type: TriggerType
    pattern: str
    action: str
    is_enabled: bool = True
    compiled_pattern: Optional[re.Pattern] = None

    def __post_init__(self):
        try:
            self.compiled_pattern = re.compile(self.pattern)
        except re.error as e:
            logger.error(f"Invalid regex pattern '{self.pattern}': {e}")
            self.compiled_pattern = None


class TriggerManager:
    def __init__(self, config_dir: str):
        self.triggers: List[Trigger] = []
        self.next_id = 1
        self.config_dir = config_dir
        self.triggers_file = os.path.join(config_dir, "triggers.json")
        self.load_triggers()

    def add_trigger(self, event_type: str, pattern: str, action: str) -> Optional[int]:
        """Add a new trigger and return its ID if successful."""
        try:
            trigger_type = TriggerType[event_type.upper()]
        except KeyError:
            logger.error(f"Invalid event type: {event_type}")
            return None

        trigger = Trigger(
            id=self.next_id, event_type=trigger_type, pattern=pattern, action=action
        )

        if trigger.compiled_pattern is None:
            return None

        self.triggers.append(trigger)
        self.next_id += 1
        self.save_triggers()
        return trigger.id

    def remove_trigger(self, trigger_id: int) -> bool:
        """Remove a trigger by ID. Returns True if successful."""
        initial_length = len(self.triggers)
        self.triggers = [t for t in self.triggers if t.id != trigger_id]
        if len(self.triggers) < initial_length:
            self.save_triggers()
            return True
        return False

    def set_trigger_enabled(self, trigger_id: int, enabled: bool) -> bool:
        """Enable or disable a trigger by ID. Returns True if successful."""
        for trigger in self.triggers:
            if trigger.id == trigger_id:
                trigger.is_enabled = enabled
                self.save_triggers()
                return True
        return False

    def list_triggers(self, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all triggers, optionally filtered by event type."""
        triggers = self.triggers
        if event_type:
            try:
                trigger_type = TriggerType[event_type.upper()]
                triggers = [t for t in triggers if t.event_type == trigger_type]
            except KeyError:
                return []

        return [asdict(t) for t in triggers]

    def process_trigger(self, event_type: str, data: Dict[str, Any]) -> Optional[str]:
        """Process an event and return the action to execute if a trigger matches."""
        try:
            trigger_type = TriggerType[event_type.upper()]
        except KeyError:
            return None

        for trigger in self.triggers:
            if not trigger.is_enabled or trigger.event_type != trigger_type:
                continue

            # Determine which field to match against based on event type
            field_to_match = self._get_field_to_match(trigger_type)
            if not field_to_match or field_to_match not in data:
                continue

            if trigger.compiled_pattern and trigger.compiled_pattern.search(
                data[field_to_match]
            ):
                return self._substitute_variables(trigger.action, data)

        return None

    def _get_field_to_match(self, trigger_type: TriggerType) -> Optional[str]:
        """Determine which field in the data dict to match against for a given trigger type."""
        field_map = {
            TriggerType.TEXT: "message",
            TriggerType.ACTION: "message",
            TriggerType.NOTICE: "message",
            TriggerType.JOIN: "nick",
            TriggerType.PART: "nick",
            TriggerType.QUIT: "nick",
            TriggerType.KICK: "kicked_nick",
            TriggerType.MODE: "modes_str",
            TriggerType.TOPIC: "new_topic",
            TriggerType.NICK: "old_nick",
            TriggerType.INVITE: "channel",
            TriggerType.CTCP: "ctcp_command",
            TriggerType.RAW: "raw_line",
        }
        return field_map.get(trigger_type)

    def _substitute_variables(self, action: str, data: Dict[str, Any]) -> str:
        """Replace mIRC-style variables in the action string with their values."""
        # Basic variable mapping
        variable_map = {
            "$nick": data.get("nick", ""),
            "$channel": data.get("channel", ""),
            "$target": data.get("target", ""),
            "$me": data.get("client_nick", ""),
            "$msg": data.get("message", ""),
            "$message": data.get("message", ""),
            "$reason": data.get("reason", ""),
            "$mode": data.get("modes_str", ""),
            "$topic": data.get("new_topic", ""),
            "$raw": data.get("raw_line", ""),
            "$timestamp": data.get("timestamp", ""),
        }

        # Handle parameterized variables
        message_words = data.get("message_words", [])
        for i, word in enumerate(message_words, 1):
            variable_map[f"$${i}"] = word
            if i == 1:
                variable_map["$1-"] = " ".join(message_words[1:])
            elif i == 2:
                variable_map["$2-"] = " ".join(message_words[2:])

        # Replace all variables in the action string
        result = action
        for var, value in variable_map.items():
            result = result.replace(var, str(value))

        return result

    def save_triggers(self):
        """Save triggers to the JSON file."""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.triggers_file, "w") as f:
                json.dump([asdict(t) for t in self.triggers], f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save triggers: {e}")

    def load_triggers(self):
        """Load triggers from the JSON file."""
        try:
            if not os.path.exists(self.triggers_file):
                return

            with open(self.triggers_file, "r") as f:
                triggers_data = json.load(f)

            self.triggers = []
            for t_data in triggers_data:
                try:
                    trigger = Trigger(
                        id=t_data["id"],
                        event_type=TriggerType[t_data["event_type"]],
                        pattern=t_data["pattern"],
                        action=t_data["action"],
                        is_enabled=t_data["is_enabled"],
                    )
                    if trigger.compiled_pattern is not None:
                        self.triggers.append(trigger)
                        self.next_id = max(self.next_id, trigger.id + 1)
                except (KeyError, ValueError) as e:
                    logger.error(f"Failed to load trigger: {e}")

        except Exception as e:
            logger.error(f"Failed to load triggers: {e}")
