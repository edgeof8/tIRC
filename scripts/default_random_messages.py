import random
import os
from typing import Dict, List
from script_base import ScriptBase


class RandomMessagesScript(ScriptBase):
    def __init__(self, api):
        super().__init__(api)
        self.quit_messages: List[str] = []
        self.part_messages: List[str] = []
        self.api.log_info("RandomMessagesScript initialized.")

    def load(self):
        """Load quit and part messages from data files."""
        try:
            # Load quit messages
            quit_messages_path = os.path.join(
                self.get_script_data_dir(), "quit_messages.txt"
            )
            if os.path.exists(quit_messages_path):
                with open(quit_messages_path, "r", encoding="utf-8") as f:
                    self.quit_messages = [line.strip() for line in f if line.strip()]
                self.api.log_info(f"Loaded {len(self.quit_messages)} quit messages.")
            else:
                self.api.log_warning(
                    f"Quit messages file not found: {quit_messages_path}"
                )

            # Load part messages
            part_messages_path = os.path.join(
                self.get_script_data_dir(), "part_messages.txt"
            )
            if os.path.exists(part_messages_path):
                with open(part_messages_path, "r", encoding="utf-8") as f:
                    self.part_messages = [line.strip() for line in f if line.strip()]
                self.api.log_info(f"Loaded {len(self.part_messages)} part messages.")
            else:
                self.api.log_warning(
                    f"Part messages file not found: {part_messages_path}"
                )

        except Exception as e:
            self.api.log_error(f"Error loading random messages: {e}")

    def _substitute_variables(self, message: str, variables: Dict[str, str]) -> str:
        """Substitute variables in a message template."""
        result = message
        for key, value in variables.items():
            result = result.replace(f"${key}", str(value))
        return result

    def get_random_quit_message(self, variables: Dict[str, str]) -> str:
        """Get a random quit message with variables substituted."""
        if not self.quit_messages:
            return "Client shutting down"
        import random

        template = random.choice(self.quit_messages)
        return self._substitute_variables(template, variables)

    def get_random_part_message(self, variables: Dict[str, str]) -> str:
        """Get a random part message with variables substituted."""
        if not self.part_messages:
            return "Leaving"
        import random

        template = random.choice(self.part_messages)
        return self._substitute_variables(template, variables)


def get_script_instance(api):
    """Factory function to create and return a script instance."""
    return RandomMessagesScript(api)
