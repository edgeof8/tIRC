# START OF MODIFIED FILE: features/triggers/trigger_manager.py
import json
import logging
import os
import re
import time  # Import the time module
from enum import Enum
from typing import Dict, List, Optional, Any, Union

logger = logging.getLogger("tirc.features.triggers")

TRIGGERS_FILE = "triggers.json"


class ActionType(Enum):
    COMMAND = "COMMAND"
    PYTHON = "PYTHON"

    @classmethod
    def from_string(cls, s: str) -> Optional["ActionType"]:
        try:
            return cls[s.upper()]
        except KeyError:
            return None


class Trigger:
    def __init__(
        self,
        trigger_id: int,
        event_type: str,
        pattern: str,
        action_type: ActionType,
        action_content: str,
        is_enabled: bool = True,
        is_regex: bool = True,
        ignore_case: bool = True,
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
        created_by: str = "system",
        description: str = "",
    ):
        self.id = trigger_id
        self.event_type = event_type.upper()
        self.pattern = pattern
        self.action_type = action_type
        self.action_content = action_content
        self.is_enabled = is_enabled
        self.is_regex = is_regex
        self.ignore_case = ignore_case

        current_time = time.time()
        self.created_at = created_at if created_at is not None else current_time
        self.updated_at = (
            updated_at if updated_at is not None else current_time
        )
        self.created_by = created_by
        self.description = description

        self.compiled_pattern: Optional[re.Pattern] = None
        if self.is_regex and self.pattern:  # Only compile if pattern is not empty
            try:
                flags = re.IGNORECASE if self.ignore_case else 0
                self.compiled_pattern = re.compile(self.pattern, flags)
            except re.error as e:
                logger.error(
                    f"Invalid regex pattern for trigger ID {self.id} ('{self.pattern}'): {e}"
                )
                self.compiled_pattern = None
                self.is_enabled = False
        elif (
            not self.is_regex and not self.pattern
        ):  # Non-regex trigger with empty pattern
            logger.warning(
                f"Trigger ID {self.id} is non-regex but has an empty pattern. It will match any event of its type if enabled."
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "pattern": self.pattern,
            "action_type": self.action_type.name,
            "action_content": self.action_content,
            "is_enabled": self.is_enabled,
            "is_regex": self.is_regex,
            "ignore_case": self.ignore_case,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional["Trigger"]:
        action_type_enum = ActionType.from_string(data.get("action_type", ""))
        if not action_type_enum:
            logger.error(
                f"Invalid action_type '{data.get('action_type')}' for trigger ID {data.get('id')}. Skipping."
            )
            return None

        return cls(
            trigger_id=data["id"],
            event_type=data["event_type"],
            pattern=data["pattern"],
            action_type=action_type_enum,
            action_content=data["action_content"],
            is_enabled=data.get("is_enabled", True),
            is_regex=data.get("is_regex", True),
            ignore_case=data.get("ignore_case", True),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            created_by=data.get("created_by", "loaded_from_file"),
            description=data.get("description", ""),
        )


class TriggerManager:
    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.triggers_file_path = os.path.join(config_dir, TRIGGERS_FILE)
        self.triggers: Dict[int, Trigger] = {}
        self.next_trigger_id = 1
        self._load_triggers_from_file()  # Renamed for consistency

    def load_triggers(self):  # Public method if needed for reloads
        self._load_triggers_from_file()

    def _load_triggers_from_file(self):
        if not os.path.exists(self.triggers_file_path):
            logger.info(
                f"Triggers file not found at {self.triggers_file_path}. No triggers loaded."
            )
            return
        try:
            with open(self.triggers_file_path, "r", encoding="utf-8") as f:
                triggers_data = json.load(f)

            loaded_triggers_count = 0
            max_id_found = 0
            temp_triggers: Dict[int, Trigger] = {}
            for data in triggers_data:
                trigger = Trigger.from_dict(data)
                if trigger:
                    if (
                        trigger.id in temp_triggers
                    ):  # Check against temp_triggers to handle duplicates in file
                        logger.warning(
                            f"Duplicate trigger ID {trigger.id} found in file. Using first instance."
                        )
                        continue
                    temp_triggers[trigger.id] = trigger
                    loaded_triggers_count += 1
                    if trigger.id > max_id_found:
                        max_id_found = trigger.id

            self.triggers = temp_triggers  # Assign loaded triggers
            self.next_trigger_id = max_id_found + 1
            logger.info(
                f"Loaded {len(self.triggers)} triggers from {self.triggers_file_path}. Next ID: {self.next_trigger_id}"
            )

        except json.JSONDecodeError:
            logger.error(
                f"Error decoding JSON from {self.triggers_file_path}. No triggers loaded."
            )
        except Exception as e:
            logger.error(
                f"Error loading triggers from {self.triggers_file_path}: {e}",
                exc_info=True,
            )

    def _save_triggers_to_file(self):
        try:
            triggers_data = [trigger.to_dict() for trigger in self.triggers.values()]
            with open(self.triggers_file_path, "w", encoding="utf-8") as f:
                json.dump(triggers_data, f, indent=4)
            logger.info(
                f"Saved {len(self.triggers)} triggers to {self.triggers_file_path}"
            )
        except Exception as e:
            logger.error(
                f"Error saving triggers to {self.triggers_file_path}: {e}",
                exc_info=True,
            )

    def add_trigger(
        self,
        event_type_str: str,
        pattern: str,
        action_type_str: str,
        action_content: str,
        is_enabled: bool = True,
        is_regex: bool = True,
        ignore_case: bool = True,
        created_by: str = "user",
        description: str = "",
    ) -> Optional[int]:

        action_type = ActionType.from_string(action_type_str)
        if not action_type:
            logger.error(f"Invalid action_type '{action_type_str}' for new trigger.")
            return None

        trigger_id = self.next_trigger_id
        trigger = Trigger(
            trigger_id=trigger_id,
            event_type=event_type_str,
            pattern=pattern,
            action_type=action_type,
            action_content=action_content,
            is_enabled=is_enabled,
            is_regex=is_regex,
            ignore_case=ignore_case,
            created_by=created_by,
            description=description,
            created_at=time.time(),
            updated_at=time.time(),
        )

        if trigger.is_regex and trigger.pattern and not trigger.compiled_pattern:
            logger.error(f"Cannot add trigger with invalid regex pattern: '{pattern}'")
            return None

        self.triggers[trigger_id] = trigger
        self.next_trigger_id += 1
        self._save_triggers_to_file()
        logger.info(
            f"Added trigger ID {trigger_id}: Event='{event_type_str}', Pattern='{pattern}', Action='{action_type_str}'"
        )
        return trigger_id

    def remove_trigger(self, trigger_id: int) -> bool:
        if trigger_id in self.triggers:
            del self.triggers[trigger_id]
            self._save_triggers_to_file()
            logger.info(f"Removed trigger ID {trigger_id}")
            return True
        logger.warning(f"Trigger ID {trigger_id} not found for removal.")
        return False

    def set_trigger_enabled(self, trigger_id: int, enabled: bool) -> bool:
        if trigger_id in self.triggers:
            self.triggers[trigger_id].is_enabled = enabled
            self.triggers[trigger_id].updated_at = time.time()
            self._save_triggers_to_file()
            logger.info(
                f"Trigger ID {trigger_id} {'enabled' if enabled else 'disabled'}."
            )
            return True
        logger.warning(f"Trigger ID {trigger_id} not found for enable/disable.")
        return False

    def list_triggers(self, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        result = []
        for trigger in self.triggers.values():
            if event_type is None or trigger.event_type == event_type.upper():
                result.append(trigger.to_dict())
        return result

    def get_trigger(self, trigger_id: int) -> Optional[Trigger]:
        return self.triggers.get(trigger_id)

    def process_trigger(
        self, event_type: str, event_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        event_type_upper = event_type.upper()
        text_to_check = ""

        if event_type_upper in ["TEXT", "ACTION", "NOTICE"]:
            text_to_check = event_data.get("message", "")
        elif event_type_upper == "RAW":
            text_to_check = event_data.get("raw_line", "")

        for trigger_id, trigger in self.triggers.items():
            if not trigger.is_enabled or trigger.event_type != event_type_upper:
                continue

            match_obj: Union[re.Match[str], bool, None] = None  # Type hint for clarity

            if not trigger.pattern:
                match_obj = True
            elif trigger.is_regex:
                if trigger.compiled_pattern:
                    match_obj = trigger.compiled_pattern.search(text_to_check)
                else:
                    continue
            else:
                flags = re.IGNORECASE if trigger.ignore_case else 0
                if re.search(re.escape(trigger.pattern), text_to_check, flags):
                    match_obj = True

            if match_obj:
                logger.info(
                    f"Trigger ID {trigger_id} matched event type '{event_type}' with pattern '{trigger.pattern}' on text: '{text_to_check[:100]}...'"
                )

                event_data_with_captures = event_data.copy()
                action_content = trigger.action_content

                # Only try to get groups if it was a regex match and not just 'True'
                if trigger.is_regex and isinstance(match_obj, re.Match):
                    groups = match_obj.groups()  # Tuple[Optional[str], ...]
                    event_data_with_captures["captures"] = groups
                    safe_groups_for_join: List[str] = []
                    for i, group_val in enumerate(groups):
                        event_data_with_captures[f"${i+1}"] = (
                            group_val if group_val is not None else ""
                        )
                        if group_val is not None:
                            safe_groups_for_join.append(group_val)

                    if safe_groups_for_join:  # Only join if there are non-None groups
                        event_data_with_captures["$*"] = " ".join(safe_groups_for_join)
                    else:
                        event_data_with_captures["$*"] = ""

                    if trigger.action_type == ActionType.COMMAND:
                        action_content = action_content.replace(
                            "$nick", event_data.get("nick", "")
                        )
                        action_content = action_content.replace(
                            "$channel",
                            event_data.get("channel", event_data.get("target", "")),
                        )
                        action_content = action_content.replace(
                            "$target", event_data.get("target", "")
                        )
                        action_content = action_content.replace(
                            "$message", event_data.get("message", "")
                        )
                        action_content = action_content.replace("$$", "$")

                        try:
                            action_content = action_content.replace(
                                "$0", match_obj.group(0) or ""
                            )
                        except IndexError:
                            pass

                        for i in range(1, 10):
                            try:
                                group_val = match_obj.group(i)
                                action_content = action_content.replace(
                                    f"${i}", group_val if group_val is not None else ""
                                )
                            except IndexError:
                                action_content = action_content.replace(f"${i}", "")
                elif (
                    trigger.action_type == ActionType.COMMAND
                ):  # Non-regex match, or regex with no groups, still do basic subs
                    action_content = action_content.replace(
                        "$nick", event_data.get("nick", "")
                    )
                    action_content = action_content.replace(
                        "$channel",
                        event_data.get("channel", event_data.get("target", "")),
                    )
                    action_content = action_content.replace(
                        "$target", event_data.get("target", "")
                    )
                    action_content = action_content.replace(
                        "$message", event_data.get("message", "")
                    )
                    action_content = action_content.replace("$$", "$")

                return {
                    "type": trigger.action_type,
                    "content": (
                        action_content
                        if trigger.action_type == ActionType.COMMAND
                        else None
                    ),
                    "code": (
                        trigger.action_content
                        if trigger.action_type == ActionType.PYTHON
                        else None
                    ),
                    "event_data": event_data_with_captures,
                    "pattern": trigger.pattern,
                }
        return None


# END OF MODIFIED FILE: features/triggers/trigger_manager.py
