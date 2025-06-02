# scripts/default_fun_commands.py
import random
import re
import os # For os.path.exists, though api.request_data_file_path handles path construction
import logging # Added for script-specific logging
from typing import TYPE_CHECKING, List, Dict, Any, Optional

if TYPE_CHECKING:
    from script_manager import ScriptAPIHandler

# Use a logger specific to this script for better traceability
script_logger = logging.getLogger("pyrc.scripts.default_fun_commands")

class FunCommandsScript:
    def __init__(self, api_handler: 'ScriptAPIHandler'):
        self.api = api_handler
        self.slap_items: List[str] = []
        self.eight_ball_answers: List[str] = []

        self.pyfiglet_available = False
        try:
            import pyfiglet # pyfiglet is an optional import for /ascii
            self.pyfiglet_available = True
            script_logger.info("pyfiglet library found and enabled for /ascii command.")
        except ImportError:
            self.pyfiglet_available = False
            script_logger.info("pyfiglet library not found. /ascii command will be disabled.")


    def _load_data_file(self, filename: str, default_items: List[str]) -> List[str]:
        """Helper to load items from a data file or return defaults."""
        items = []
        try:
            # self.api.log_info(f"Requesting data file path for: {filename}") # Debug log
            file_path = self.api.request_data_file_path(filename)
            # self.api.log_info(f"Received data file path: {file_path}") # Debug log

            if not os.path.exists(file_path):
                 self.api.log_warning(f"Data file '{filename}' not found at '{file_path}'. Using default items.")
                 return default_items.copy()

            with open(file_path, "r", encoding="utf-8") as f:
                items = [line.strip() for line in f if line.strip()]

            if not items:
                self.api.log_warning(f"Data file '{filename}' is empty. Using default items.")
                return default_items.copy()
            # self.api.log_info(f"Successfully loaded {len(items)} items from '{filename}'.") # Debug log
            return items
        except Exception as e:
            self.api.log_error(f"Error loading data file '{filename}': {e}. Using default items.")
            return default_items.copy()

    def load(self):
        self.api.log_info("FunCommandsScript loading data...")
        self.slap_items = self._load_data_file("slap_items.txt", ["a large trout", "a wet noodle", "a rubber chicken"])
        self.eight_ball_answers = self._load_data_file(
            "magic_eight_ball_answers.txt",
            [
                "It is certain.", "It is decidedly so.", "Without a doubt.", "Yes – definitely.",
                "You may rely on it.", "As I see it, yes.", "Most likely.", "Outlook good.",
                "Yes.", "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
                "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
                "Don't count on it.", "My reply is no.", "My sources say no.",
                "Outlook not so good.", "Very doubtful."
            ]
        )

        if not self.pyfiglet_available:
            self.api.log_warning("/ascii command disabled: pyfiglet library not found. Install with: pip install pyfiglet")

        self.api.register_command(
            "slap", self.handle_slap_command, "Usage: /slap <nickname> - Slaps <nickname> with a random item."
        )
        self.api.register_command(
            "8ball", self.handle_8ball_command, "Usage: /8ball <question> - Asks the Magic 8-Ball a question."
        )
        self.api.register_command(
            "dice", self.handle_dice_command, "Usage: /dice <NdN> (e.g., 2d6) - Rolls NdN dice.", aliases=["roll"]
        )
        self.api.register_command(
            "rainbow", self.handle_rainbow_command, "Usage: /rainbow <text> - Sends <text> in rainbow colors."
        )
        self.api.register_command(
            "reverse", self.handle_reverse_command, "Usage: /reverse <text> - Sends <text> reversed."
        )
        self.api.register_command(
            "wave", self.handle_wave_command, "Usage: /wave <text> - Sends <text> with a wave effect."
        )
        if self.pyfiglet_available:
            self.api.register_command(
                "ascii", self.handle_ascii_command, "Usage: /ascii <text> - Converts <text> to ASCII art and sends it."
            )

        self.api.log_info("FunCommandsScript loaded and commands registered.")

    def _ensure_args(self, args_str: str, usage_message: str, current_context: Optional[str]) -> bool:
        if not args_str.strip():
            self.api.add_message_to_context(current_context or "Status", usage_message, "error")
            return False
        return True

    def handle_slap_command(self, args_str: str, event_data: Dict[str, Any]):
        target_user = args_str.strip()
        current_context = self.api.get_current_context_name()
        active_context_type = self.api.get_active_context_type()

        if not self._ensure_args(args_str, "Usage: /slap <nickname>", current_context):
            return

        if active_context_type in ["channel", "query"] and current_context:
            if not self.slap_items:
                self.api.log_error("Slap items list is empty, even after defaults. This should not happen.")
                item = "a very confused look" # Fallback if somehow defaults also failed
            else:
                item = random.choice(self.slap_items)
            self.api.send_action(current_context, f"slaps {target_user} around a bit with {item}")
        else:
            self.api.add_message_to_context(current_context or "Status", "Cannot /slap here. Try in a channel or query.", "error")

    def handle_8ball_command(self, args_str: str, event_data: Dict[str, Any]):
        current_context = self.api.get_current_context_name()
        if not self._ensure_args(args_str, "Usage: /8ball <question>", current_context):
            return

        if not self.eight_ball_answers:
             self.api.log_error("8-ball answers list is empty, even after defaults. This should not happen.")
             answer = "The mists are cloudy today." # Fallback
        else:
            answer = random.choice(self.eight_ball_answers)

        # Send to current context if channel/query, otherwise to Status for local display
        target_send_context = current_context
        active_context_type = self.api.get_active_context_type()
        message_to_send = f"🎱 {answer}"

        if active_context_type in ["channel", "query"] and target_send_context:
            self.api.send_raw(f"PRIVMSG {target_send_context} :{message_to_send}")
        else:
            self.api.add_message_to_context(target_send_context or "Status", message_to_send, "system")


    def handle_dice_command(self, args_str: str, event_data: Dict[str, Any]):
        current_context = self.api.get_current_context_name()
        if not self._ensure_args(args_str, "Usage: /dice <NdN> (e.g., 2d6)", current_context):
            return

        match = re.match(r"(\d+)d(\d+)", args_str.strip(), re.IGNORECASE)
        if not match:
            self.api.add_message_to_context(current_context or "Status", "Invalid dice format. Use NdN (e.g., 2d6)", "error")
            return

        num_dice = int(match.group(1))
        sides = int(match.group(2))

        if num_dice <= 0 or sides <= 0:
            self.api.add_message_to_context(current_context or "Status", "Number of dice and sides must be positive.", "error")
            return
        if num_dice > 100 or sides > 1000:
            self.api.add_message_to_context(current_context or "Status", "Too many dice or sides! Keep it reasonable (max 100d1000).", "error")
            return

        rolls = [random.randint(1, sides) for _ in range(num_dice)]
        total = sum(rolls)

        message = f"🎲 Rolled {num_dice}d{sides}: {', '.join(map(str, rolls))} = {total}" if num_dice > 1 else f"🎲 Rolled a d{sides}: {total}"

        target_send_context = current_context
        active_context_type = self.api.get_active_context_type()
        if active_context_type in ["channel", "query"] and target_send_context:
            self.api.send_raw(f"PRIVMSG {target_send_context} :{message}")
        else:
            self.api.add_message_to_context(target_send_context or "Status", message, "system")


    def handle_rainbow_command(self, args_str: str, event_data: Dict[str, Any]):
        current_context = self.api.get_current_context_name()
        if not self._ensure_args(args_str, "Usage: /rainbow <text>", current_context):
            return

        colors = ["\x0304", "\x0308", "\x0309", "\x0311", "\x0302", "\x0306"]
        reset_color = "\x0f" # Or "\x03" if you want to reset to default mIRC color

        rainbow_text_parts = [f"{colors[i % len(colors)]}{char}" for i, char in enumerate(args_str)]
        rainbow_text = "".join(rainbow_text_parts) + reset_color

        active_context_type = self.api.get_active_context_type()
        if active_context_type in ["channel", "query"] and current_context:
            self.api.send_raw(f"PRIVMSG {current_context} :{rainbow_text}")
        else:
            self.api.add_message_to_context(current_context or "Status", "Cannot /rainbow here. Try in a channel or query.", "error")

    def handle_reverse_command(self, args_str: str, event_data: Dict[str, Any]):
        current_context = self.api.get_current_context_name()
        if not self._ensure_args(args_str, "Usage: /reverse <text>", current_context):
            return

        reversed_text = args_str[::-1]
        active_context_type = self.api.get_active_context_type()
        if active_context_type in ["channel", "query"] and current_context:
            self.api.send_raw(f"PRIVMSG {current_context} :{reversed_text}")
        else:
            # For non-messageable contexts, display locally or error. Let's display locally.
            self.api.add_message_to_context(current_context or "Status", f"Reversed: {reversed_text}", "system")

    def handle_wave_command(self, args_str: str, event_data: Dict[str, Any]):
        current_context = self.api.get_current_context_name()
        if not self._ensure_args(args_str, "Usage: /wave <text>", current_context):
            return

        wave_chars = list("~-.~")
        waved_text_parts = [
            (wave_chars[i % len(wave_chars)] + char if not char.isspace() else char)
            for i, char in enumerate(args_str)
        ]
        waved_text = "".join(waved_text_parts)

        active_context_type = self.api.get_active_context_type()
        if active_context_type in ["channel", "query"] and current_context:
            self.api.send_raw(f"PRIVMSG {current_context} :{waved_text}")
        else:
            self.api.add_message_to_context(current_context or "Status", "Cannot /wave here. Try in a channel or query.", "error")

    def handle_ascii_command(self, args_str: str, event_data: Dict[str, Any]):
        current_context = self.api.get_current_context_name()
        active_context_type = self.api.get_active_context_type()

        if not self.pyfiglet_available:
            self.api.add_message_to_context(current_context or "Status", "ASCII art requires pyfiglet. Install with: pip install pyfiglet", "error")
            return
        if not self._ensure_args(args_str, "Usage: /ascii <text>", current_context):
            return

        try:
            import pyfiglet
            # Consider allowing font selection via args_str if desired later
            # For now, use default font
            ascii_art = pyfiglet.figlet_format(args_str)

            if active_context_type in ["channel", "query"] and current_context:
                # Send each line of ASCII art as a separate message
                for line_art in ascii_art.split("\n"):
                    if line_art.strip():
                        self.api.send_raw(f"PRIVMSG {current_context} :{line_art}")
            else:
                # Display locally in Status or current non-messageable window
                self.api.add_message_to_context(current_context or "Status", "--- ASCII Art ---", "system")
                for line_art in ascii_art.split("\n"):
                    if line_art.strip():
                        self.api.add_message_to_context(current_context or "Status", line_art, "system")
                self.api.add_message_to_context(current_context or "Status", "--- End ASCII Art ---", "system")
                if current_context != "Status": # If it wasn't status, also inform about channel/query
                     self.api.add_message_to_context(current_context or "Status", "(Displayed locally as current window is not a channel/query)", "system_italic")


        except Exception as e:
            self.api.log_error(f"Error creating ASCII art: {e}")
            self.api.add_message_to_context(current_context or "Status", f"Error creating ASCII art: {e}", "error")

# Entry point for ScriptManager
def get_script_instance(api_handler: 'ScriptAPIHandler'):
    return FunCommandsScript(api_handler)
