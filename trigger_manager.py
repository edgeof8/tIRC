import os
import json
import re
from dataclasses import asdict, dataclass
from typing import List, Optional, Dict, Pattern
from log import logger
from enums import TriggerType, ActionType
from config import ENABLE_TRIGGER_SYSTEM


@dataclass
class Trigger:
    id: str
    event_type: str
    pattern: str
    action_content: str
    action_type: str
    is_enabled: bool = True
    compiled_pattern: Optional[Pattern] = None

    def __post_init__(self):
        try:
            self.compiled_pattern = re.compile(self.pattern)
        except re.error as e:
            logger.error(f"Invalid regex pattern '{self.pattern}': {str(e)}")
            self.compiled_pattern = None


class TriggerManager:
    def __init__(self):
        self.triggers: Dict[str, Trigger] = {}
        self.enabled = ENABLE_TRIGGER_SYSTEM
        self.config_dir = "config"
        self.triggers_file = os.path.join(self.config_dir, "triggers.json")
        self.load_triggers()

    def is_enabled(self) -> bool:
        """Check if the trigger system is enabled."""
        return self.enabled

    def enable(self) -> None:
        """Enable the trigger system."""
        self.enabled = True
        logger.info("Trigger system enabled")

    def disable(self) -> None:
        """Disable the trigger system."""
        self.enabled = False
        logger.info("Trigger system disabled")

    def save_triggers(self) -> bool:
        """Save triggers to file."""
        if not self.enabled:
            logger.debug("Trigger system disabled, skipping save")
            return True

        try:
            os.makedirs(self.config_dir, exist_ok=True)
            triggers_data = []
            for trigger in self.triggers.values():
                trigger_dict = asdict(trigger)
                # Exclude non-serializable fields
                trigger_dict.pop("compiled_pattern", None)
                # Convert enums to strings
                trigger_dict["event_type"] = str(trigger_dict["event_type"])
                trigger_dict["action_type"] = str(trigger_dict["action_type"])
                triggers_data.append(trigger_dict)

            with open(self.triggers_file, "w") as f:
                json.dump(triggers_data, f, indent=2)
            logger.info(f"Saved {len(triggers_data)} triggers to {self.triggers_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save triggers: {str(e)}")
            return False

    def load_triggers(self) -> bool:
        """Load triggers from file."""
        if not self.enabled:
            logger.debug("Trigger system disabled, skipping load")
            return True

        try:
            if not os.path.exists(self.triggers_file):
                logger.info(f"No triggers file found at {self.triggers_file}")
                return True

            with open(self.triggers_file, "r") as f:
                triggers_data = json.load(f)

            self.triggers.clear()
            for trigger_dict in triggers_data:
                try:
                    # Create trigger without compiled_pattern
                    trigger = Trigger(
                        id=trigger_dict["id"],
                        event_type=trigger_dict["event_type"],
                        pattern=trigger_dict["pattern"],
                        action_content=trigger_dict["action_content"],
                        action_type=trigger_dict["action_type"],
                        is_enabled=trigger_dict.get("is_enabled", True),
                    )
                    self.triggers[trigger.id] = trigger
                except Exception as e:
                    logger.error(f"Failed to load trigger: {str(e)}")
                    continue

            logger.info(
                f"Loaded {len(self.triggers)} triggers from {self.triggers_file}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to load triggers: {str(e)}")
            return False

    def add_trigger(self, trigger: Trigger) -> bool:
        """Add a new trigger."""
        if not self.enabled:
            logger.debug("Trigger system disabled, cannot add trigger")
            return False

        if trigger.id in self.triggers:
            logger.warning(f"Trigger with ID {trigger.id} already exists")
            return False

        self.triggers[trigger.id] = trigger
        logger.info(f"Added trigger: {trigger.id}")
        return self.save_triggers()

    def remove_trigger(self, trigger_id: str) -> bool:
        """Remove a trigger by ID."""
        if not self.enabled:
            logger.debug("Trigger system disabled, cannot remove trigger")
            return False

        if trigger_id not in self.triggers:
            logger.warning(f"Trigger with ID {trigger_id} not found")
            return False

        del self.triggers[trigger_id]
        logger.info(f"Removed trigger: {trigger_id}")
        return self.save_triggers()

    def get_trigger(self, trigger_id: str) -> Optional[Trigger]:
        """Get a trigger by ID."""
        return self.triggers.get(trigger_id)

    def get_all_triggers(self) -> List[Trigger]:
        """Get all triggers."""
        return list(self.triggers.values())

    def process_event(self, event_type: str, data: str) -> Optional[str]:
        """Process an event and return action content if a trigger matches."""
        if not self.enabled:
            return None

        for trigger in self.triggers.values():
            if not trigger.is_enabled:
                continue

            if trigger.event_type != event_type:
                continue

            if trigger.compiled_pattern and trigger.compiled_pattern.search(data):
                logger.debug(f"Trigger {trigger.id} matched event: {event_type}")
                return trigger.action_content

        return None
