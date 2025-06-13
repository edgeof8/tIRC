import random
import logging
from typing import TYPE_CHECKING, List, Optional
from tirc_core.scripting.script_base import ScriptBase

if TYPE_CHECKING:
    from tirc_core.scripting.script_api_handler import ScriptAPIHandler

# Use a logger specific to this script for better traceability
script_logger = logging.getLogger("tirc.scripts.default_random_messages")


class RandomMessagesScript(ScriptBase):
    def __init__(self, api_handler: "ScriptAPIHandler"):
        super().__init__(api_handler)
        self.quit_messages: List[str] = []
        self.part_messages: List[str] = []

    async def load(self): # Changed to async
        self.api.log_info("RandomMessagesScript loading data...")
        self.quit_messages = await self.load_list_from_data_file( # Added await
            "quit_messages.txt", ["Goodbye, cruel world!", "See you later!", "Bye bye!"]
        )
        self.part_messages = await self.load_list_from_data_file( # Added await
            "part_messages.txt", ["Leaving the channel!", "See you later!", "Bye bye!"]
        )

        self.api.subscribe_to_event("CLIENT_SHUTDOWN", self.handle_client_shutdown)
        # self.api.subscribe_to_event("CHANNEL_PART", self.handle_channel_part) # Removed to avoid redundant PART messages
        self.api.log_info("RandomMessagesScript loaded and event handlers registered.")

    async def handle_client_shutdown(self, event_data: dict):
        """Handle client shutdown by sending a random quit message."""
        if not self.quit_messages:
            return

        message = random.choice(self.quit_messages)
        await self.api.send_raw(f"QUIT :{message}")

    # async def handle_channel_part(self, event_data: dict): # Removed to avoid redundant PART messages
    #     """Handle channel part by sending a random part message."""
    #     if not self.part_messages:
    #         return
    #
    #     channel = event_data.get("channel")
    #     if not channel:
    #         return
    #
    #     message = random.choice(self.part_messages)
    #     await self.api.send_raw(f"PART {channel} :{message}")


def get_script_instance(api):
    """Factory function to create and return a script instance."""
    return RandomMessagesScript(api)
