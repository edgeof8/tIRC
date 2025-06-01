# fun_commands_handler.py
import logging
import random
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.fun_commands_handler")

class FunCommandsHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic

    def handle_slap_command(self, args_str: str):
        """Handle the /slap command - slap someone with a random item"""
        parts = self.client.command_handler._ensure_args(args_str, "Usage: /slap <nickname>")
        if not parts:
            return

        target = parts[0]
        slap_items_file_path = "slap_items.txt"
        items = []
        default_items = [
            "a large trout", "a wet noodle", "a rubber chicken", "a sock full of pennies",
            "a dictionary", "a rubber duck", "a pillow", "a keyboard", "a mouse",
            "a monitor", "a coffee cup", "a banana", "a cactus", "a fish", "a brick"
        ]

        if not os.path.exists(slap_items_file_path):
            self.client.add_message(
                f"Warning: Slap items file not found at '{slap_items_file_path}'. Using default items.",
                self.client.ui.colors["warning"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            items = default_items
        else:
            try:
                with open(slap_items_file_path, "r") as f:
                    items = [line.strip() for line in f if line.strip()]
                if not items:  # File exists but is empty or only whitespace
                    self.client.add_message(
                        f"Warning: Slap items file '{slap_items_file_path}' is empty. Using default items.",
                        self.client.ui.colors["warning"],
                        context_name=self.client.context_manager.active_context_name or "Status",
                    )
                    items = default_items
            except Exception as e:
                logger.error(f"Error reading slap items file: {e}")
                self.client.add_message(
                    f"Error reading slap items file: {e}. Using default items.",
                    self.client.ui.colors["error"],
                    context_name=self.client.context_manager.active_context_name or "Status",
                )
                items = default_items

        if not items: # Should only happen if default_items was somehow empty
            items = ["a generic item"] # Absolute fallback

        item = random.choice(items)
        # Construct the message to be sent to the channel/query
        action_message = f"*slaps {target} around a bit with {item}*"

        # Send as a CTCP ACTION if in a channel or query
        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if current_context and (current_context.type == "channel" or current_context.type == "query"):
             self.client.network.send_raw(
                 f"PRIVMSG {current_context.name} :\x01ACTION slaps {target} around a bit with {item}\x01"
             )
        else: # Fallback to just displaying locally if not in a suitable context
            self.client.add_message(action_message, self.client.ui.colors.get("action", self.client.ui.colors["system"]))


    def handle_8ball_command(self, args_str: str):
        """Handle the /8ball command - get a random fortune"""
        if not self.client.command_handler._ensure_args(args_str, "Usage: /8ball <question>"):
            return

        answers_file_path = "magic_eight_ball_answers.txt"
        answers = []

        if not os.path.exists(answers_file_path):
            self.client.add_message(
                f"Error: Magic 8-ball answers file not found at '{answers_file_path}'. Please create it.",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            answers = ["Cannot predict now, answers file missing."]
        else:
            try:
                with open(answers_file_path, "r") as f:
                    answers = [line.strip() for line in f if line.strip()]
                if not answers:
                    self.client.add_message(
                        f"Warning: Magic 8-ball answers file '{answers_file_path}' is empty. Using a default answer.",
                        self.client.ui.colors["warning"],
                        context_name=self.client.context_manager.active_context_name or "Status",
                    )
                    answers = ["The file is empty, ask again later."]
            except Exception as e:
                logger.error(f"Error reading 8ball answers file: {e}")
                self.client.add_message(
                    f"Error reading answers file: {e}. Using a default answer.",
                    self.client.ui.colors["error"],
                    context_name=self.client.context_manager.active_context_name or "Status",
                )
                answers = ["Error reading answers, try again."]

        if not answers:
            answers = ["Concentrate and ask again."]

        answer = random.choice(answers)
        self.client.add_message(f"🎱 {answer}", self.client.ui.colors["system"])

    def handle_dice_command(self, args_str: str):
        """Handle the /dice command - roll dice in NdN format"""
        parts = self.client.command_handler._ensure_args(args_str, "Usage: /dice <NdN> (e.g., 2d6 for two six-sided dice)")
        if not parts:
            return

        match = re.match(r"(\d+)d(\d+)", args_str) # args_str is parts[0] if ensure_args used num_expected_parts=1
        if not match:
            self.client.add_message(
                "Invalid dice format. Use NdN (e.g., 2d6)",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return

        num_dice = int(match.group(1))
        sides = int(match.group(2))

        if num_dice <= 0 or sides <= 0:
            self.client.add_message(
                "Number of dice and sides must be positive.",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return
        if num_dice > 100 or sides > 1000: # Adjusted sides limit
            self.client.add_message(
                "Too many dice or sides! Keep it reasonable (max 100d1000).",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return

        rolls = [random.randint(1, sides) for _ in range(num_dice)]
        total = sum(rolls)

        if num_dice == 1:
            message = f"🎲 Rolled a {total}"
        else:
            message = f"🎲 Rolled {rolls} = {total}"

        self.client.add_message(message, self.client.ui.colors["system"])

    def handle_rainbow_command(self, args_str: str):
        """Handle the /rainbow command - make text colorful"""
        if not self.client.command_handler._ensure_args(args_str, "Usage: /rainbow <text>"):
            return

        colors = [
            "\x0304",  # Red (IRC color code)
            "\x0308",  # Yellow
            "\x0309",  # Green
            "\x0311",  # Cyan
            "\x0302",  # Blue
            "\x0306",  # Magenta
        ]
        reset = "\x0f" # IRC reset color

        rainbow_text_parts = []
        for i, char in enumerate(args_str):
            color = colors[i % len(colors)]
            rainbow_text_parts.append(f"{color}{char}")
        rainbow_text = "".join(rainbow_text_parts) + reset

        # Send as a message to the current channel/query
        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if current_context and (current_context.type == "channel" or current_context.type == "query"):
            self.client.network.send_raw(
                f"PRIVMSG {current_context.name} :{rainbow_text}"
            )
            # Optionally, also display it locally if server doesn't echo own messages with color
            # self.client.add_message(rainbow_text, self.client.ui.colors["system"])
        else:
            self.client.add_message("Cannot /rainbow here. Try in a channel or query.", self.client.ui.colors["error"])


    def handle_reverse_command(self, args_str: str):
        """Handle the /reverse command - reverse text"""
        if not self.client.command_handler._ensure_args(args_str, "Usage: /reverse <text>"):
            return

        reversed_text = args_str[::-1]
        # Send as a message to the current channel/query
        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if current_context and (current_context.type == "channel" or current_context.type == "query"):
            self.client.network.send_raw(
                f"PRIVMSG {current_context.name} :{reversed_text}"
            )
        else:
             self.client.add_message(reversed_text, self.client.ui.colors["system"])


    def handle_wave_command(self, args_str: str):
        """Handle the /wave command - make text wave (sends to channel/query)"""
        if not self.client.command_handler._ensure_args(args_str, "Usage: /wave <text>"):
            return

        wave_chars = list("~-.~") # Simple wave pattern
        waved_text_parts = []
        for i, char in enumerate(args_str):
            if char.isspace():
                waved_text_parts.append(char)
            else:
                waved_text_parts.append(wave_chars[i % len(wave_chars)] + char)
        waved_text = "".join(waved_text_parts)

        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if current_context and (current_context.type == "channel" or current_context.type == "query"):
            self.client.network.send_raw(
                f"PRIVMSG {current_context.name} :{waved_text}"
            )
        else:
            self.client.add_message(waved_text, self.client.ui.colors["system"])


    def handle_ascii_command(self, args_str: str):
        """Handle the /ascii command - convert text to ASCII art (sends to channel/query)"""
        try:
            import pyfiglet
        except ImportError:
            self.client.add_message(
                "ASCII art requires pyfiglet. Install with: pip install pyfiglet",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return

        if not self.client.command_handler._ensure_args(args_str, "Usage: /ascii <text>"):
            return

        try:
            ascii_art = pyfiglet.figlet_format(args_str)

            current_context = self.client.context_manager.get_context(
                self.client.context_manager.active_context_name or "Status"
            )
            if current_context and (current_context.type == "channel" or current_context.type == "query"):
                # Send line by line to avoid potential message length limits on server
                for line_art in ascii_art.split("\n"):
                    if line_art.strip(): # Only send non-empty lines
                        self.client.network.send_raw(
                            f"PRIVMSG {current_context.name} :{line_art}"
                        )
            else: # Fallback to local display if not in a suitable context
                 for line_art in ascii_art.split("\n"):
                    if line_art.strip():
                        self.client.add_message(line_art, self.client.ui.colors["system"])

        except Exception as e:
            self.client.add_message(
                f"Error creating ASCII art: {str(e)}",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
