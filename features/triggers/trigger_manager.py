import re
import json
import logging
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum, auto, unique

logger = logging.getLogger("pyrc.triggers")


@unique
class ActionType(Enum):
    COMMAND = auto()
    PYTHON = auto()


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
    action_content: str  # Stores the command string or Python code
    action_type: ActionType = ActionType.COMMAND  # Type of action
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

    def add_trigger(
        self, event_type_str: str, pattern: str, action_type_str: str, action_content: str
    ) -> Optional[int]:
        """Add a new trigger and return its ID if successful."""
        try:
            trigger_type = TriggerType[event_type_str.upper()]
        except KeyError:
            logger.error(f"Invalid event type: {event_type_str}")
            return None

        try:
            action_type = ActionType[action_type_str.upper()]
        except KeyError:
            logger.error(f"Invalid action type: {action_type_str}")
            return None

        trigger = Trigger(
            id=self.next_id,
            event_type=trigger_type,
            pattern=pattern,
            action_type=action_type,
            action_content=action_content,
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

        # Convert ActionType enum to string for serialization
        trigger_dicts = []
        for t in triggers:
            t_dict = asdict(t)
            t_dict["action_type"] = t.action_type.name
            trigger_dicts.append(t_dict)
        return trigger_dicts

    def _prepare_event_data(
        self, base_data: Dict[str, Any], match: Optional[re.Match]
    ) -> Dict[str, Any]:
        """Prepare the event data dictionary, including regex capture groups."""
        event_data = {
            "$nick": base_data.get("nick", ""),
            "$channel": base_data.get("channel", ""),
            "$target": base_data.get("target", ""),
            "$me": base_data.get("client_nick", ""),
            "$msg": base_data.get("message", ""),
            "$message": base_data.get("message", ""), # Alias for $msg
            "$reason": base_data.get("reason", ""),
            "$mode": base_data.get("modes_str", ""),
            "$topic": base_data.get("new_topic", ""),
            "$raw": base_data.get("raw_line", ""),
            "$timestamp": base_data.get("timestamp", ""),
            # Add other standard variables from base_data as needed
        }

        message_words = base_data.get("message_words", [])
        for i, word in enumerate(message_words, 1):
            event_data[f"$${i}"] = word # $$1, $$2, etc. for words
            if i == 1:
                event_data["$1-"] = " ".join(message_words[1:])
            elif i == 2:
                event_data["$2-"] = " ".join(message_words[2:])
            # Add $N- for other word ranges if desired

        if match:
            event_data["$0"] = match.group(0)  # Full match
            for i, group_val in enumerate(match.groups(), 1):
                event_data[f"${i}"] = group_val if group_val is not None else "" # $1, $2, etc.
            # For named capture groups, if any: event_data.update(match.groupdict())


        # Ensure all values are strings for substitution
        for key, value in event_data.items():
            event_data[key] = str(value)

        return event_data

    def _perform_string_substitutions(
        self, action_string: str, event_data: Dict[str, Any]
    ) -> str:
        """Replace variables in the action string with their values from event_data."""
        result = action_string
        # Sort keys by length descending to replace longer keys first (e.g., $message before $msg)
        # This is a simple approach; more robust templating could be used if needed.
        sorted_vars = sorted(event_data.keys(), key=len, reverse=True)
        for var_name in sorted_vars:
            result = result.replace(var_name, str(event_data[var_name]))
        return result

    def process_trigger(
        self, event_type_str: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Process an event. If a trigger matches, return a dictionary
        containing the action type, content, and event data.
        """
        try:
            trigger_type = TriggerType[event_type_str.upper()]
        except KeyError:
            return None

        for trigger in self.triggers:
            if not trigger.is_enabled or trigger.event_type != trigger_type:
                continue

            field_to_match = self._get_field_to_match(trigger_type)
            if not field_to_match or field_to_match not in data:
                continue

            match = None
            if trigger.compiled_pattern:
                match = trigger.compiled_pattern.search(data.get(field_to_match, ""))

            if match:
                event_data_for_action = self._prepare_event_data(data, match)

                if trigger.action_type == ActionType.COMMAND:
                    final_command_string = self._perform_string_substitutions(
                        trigger.action_content, event_data_for_action
                    )
                    return {
                        "type": ActionType.COMMAND,
                        "content": final_command_string,
                        # event_data not strictly needed by caller for COMMAND if already substituted
                    }
                elif trigger.action_type == ActionType.PYTHON:
                    return {
                        "type": ActionType.PYTHON,
                        "code": trigger.action_content,
                        "event_data": event_data_for_action,
                    }
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

    def save_triggers(self):
        """Save triggers to the JSON file."""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.triggers_file, "w") as f:
                triggers_to_save = []
                for t in self.triggers:
                    t_dict = asdict(t)
                    t_dict["event_type"] = t.event_type.name  # Save enum name
                    t_dict["action_type"] = t.action_type.name # Save enum name
                    triggers_to_save.append(t_dict)
                json.dump(triggers_to_save, f, indent=2)
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
                        event_type=TriggerType[t_data["event_type"]], # Already a string from save
                        pattern=t_data["pattern"],
                        action_content=t_data["action_content"], # New field name
                        action_type=ActionType[t_data.get("action_type", ActionType.COMMAND.name)], # Default for backward compatibility
                        is_enabled=t_data["is_enabled"],
                    )
                    # Ensure action_type is an enum member if loaded as string
                    if isinstance(trigger.action_type, str):
                         trigger.action_type = ActionType[trigger.action_type]

                    if trigger.compiled_pattern is not None:
                        self.triggers.append(trigger)
                        self.next_id = max(self.next_id, trigger.id + 1)
                except (KeyError, ValueError) as e:
                    logger.error(f"Failed to load trigger: {e}")

        except Exception as e:
            logger.error(f"Failed to load triggers: {e}")
