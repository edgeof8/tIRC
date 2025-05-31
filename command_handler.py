# command_handler.py
import logging
from typing import TYPE_CHECKING, List, Optional
from features.triggers.trigger_commands import TriggerCommands

if TYPE_CHECKING:
    from irc_client_logic import (
        IRCClient_Logic,
    )  # To avoid circular import for type hinting

# Get a logger instance
logger = logging.getLogger("pyrc.command_handler")


class CommandHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic
        self.trigger_commands = TriggerCommands(client_logic)

    def get_available_commands_for_tab_complete(self) -> List[str]:
        """
        Returns a list of commands primarily for tab-completion.
        This list is curated from the original do_tab_complete method.
        """
        return [
            "/join",
            "/j",
            "/part",
            "/p",
            "/msg",
            "/m",
            "/query",
            "/nick",
            "/n",
            "/quit",
            "/q",
            "/whois",
            "/w",
            "/me",
            "/away",
            "/invite",
            "/topic",
            "/raw",
            "/quote",
            "/connect",
            "/server",
            "/s",  # Alias for /connect or /server
            "/disconnect",
            "/clear",
            "/next",
            "/nextwindow",
            "/prev",
            "/prevwindow",
            "/win",
            "/window",
            "/close",
            "/wc",
            "/partchannel",
            "/cyclechannel",
            "/cc",  # Added
            "/prevchannel",
            "/pc",  # Added
            "/userlistscroll",  # Added
            "/u",  # Alias for /userlistscroll
            "/status",  # Added
            "/t",  # Alias for /topic
            "/c",  # Alias for /clear
            "/d",  # Alias for /disconnect
            "/i",  # Alias for /invite
            "/a",  # Alias for /away
            "/r",  # Alias for /raw, /quote
            "/kick",
            "/k",  # Alias for /kick
            "/notice",
            "/no",  # Alias for /notice
            "/set",
            "/se",  # Alias for /set
            "on",
            # Fun commands
            "/slap",
            "/8ball",
            "/dice",
            "/roll",
            "/rainbow",
            "/reverse",
            "/wave",
            "/ascii",
        ]

    def _ensure_args(self, args_str: str, usage_message: str, num_expected_parts: int = 1) -> Optional[List[str]]:
        """
        Validates if args_str is present and optionally contains a minimum number of parts.
        Adds a usage message and returns None if validation fails.
        Returns a list of parts if validation succeeds.
        """
        if not args_str:
            self.client.add_message(
                usage_message,
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return None

        parts = args_str.split(" ", num_expected_parts -1 if num_expected_parts > 0 else 0) # Split only as many times as needed for validation

        # If num_expected_parts is 1, we just need args_str to be non-empty, which is already checked.
        # If num_expected_parts > 1, we need at least that many parts after split.
        if num_expected_parts > 1 and len(parts) < num_expected_parts :
            self.client.add_message(
                usage_message,
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return None

        # For commands that take the rest of the string as one argument after the first part (e.g. /msg nick message)
        # the split needs to be specific. For now, this helper is simpler.
        # We will return all parts as split by space for now if num_expected_parts is not specific enough.
        # A more robust version might take the actual split parts as an argument.
        # For now, let's return the full args_str split by default if num_expected_parts is 1 or not met by split(" ", num_expected_parts-1)

        # If num_expected_parts is 1, parts will be [args_str] due to split behavior with maxsplit=0
        # If num_expected_parts > 1, parts will have at most num_expected_parts elements.
        # The check `len(parts) < num_expected_parts` handles if not enough parts were found.

        # Return the parts as split by space for general use.
        # If a command needs specific splitting (e.g. "nick message"), it should handle it after this check.
        return args_str.split() # General split for now, command can re-split if needed.


    def _handle_topic_command(self, args_str: str):
        topic_parts = args_str.split(" ", 1)
        current_active_ctx_name = self.client.context_manager.active_context_name
        target_channel_ctx_name = current_active_ctx_name  # Default to current
        new_topic = None

        if not target_channel_ctx_name:
            self.client.add_message(
                "No active window to get/set topic from.",
                self.client.ui.colors["error"],
                context_name="Status",
            )
            return

        current_context = self.client.context_manager.get_context(
            target_channel_ctx_name
        )

        if (
            not topic_parts or not topic_parts[0]
        ):  # /topic (view/set for current channel)
            if not (current_context and current_context.type == "channel"):
                self.client.add_message(
                    "Not in a channel to get/set topic. Current window is not a channel.",
                    self.client.ui.colors["error"],
                    context_name=target_channel_ctx_name,
                )
                return
            # If no args, it's a request for current topic (handled by new_topic is None below)
        elif topic_parts[0].startswith("#"):  # /topic #channel [new_topic]
            target_channel_ctx_name = topic_parts[0]
            # current_context = self.client.context_manager.get_context(target_channel_ctx_name) # Re-evaluate if needed
            if len(topic_parts) > 1:
                new_topic = topic_parts[1]
        else:  # /topic new topic for current channel
            if not (current_context and current_context.type == "channel"):
                self.client.add_message(
                    "Not in a channel to set topic. Current window is not a channel.",
                    self.client.ui.colors["error"],
                    context_name=target_channel_ctx_name,
                )
                return
            new_topic = args_str  # The whole arg string is the new topic

        if target_channel_ctx_name.startswith("#"):
            self.client.context_manager.create_context(
                target_channel_ctx_name, context_type="channel"
            )

        if new_topic is not None:
            self.client.network.send_raw(
                f"TOPIC {target_channel_ctx_name} :{new_topic}"
            )
        else:
            self.client.network.send_raw(f"TOPIC {target_channel_ctx_name}")

    def _handle_connect_command(self, args_str: str):
        from config import DEFAULT_PORT, DEFAULT_SSL_PORT

        conn_args = args_str.split()
        if not conn_args:
            self.client.add_message(
                "Usage: /connect <server[:port]> [ssl|nossl]",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return
        new_server_host, new_port, new_ssl = conn_args[0], None, self.client.use_ssl
        if ":" in new_server_host:
            new_server_host, port_str = new_server_host.split(":", 1)
            try:
                new_port = int(port_str)
            except ValueError:
                self.client.add_message(
                    f"Invalid port: {port_str}",
                    self.client.ui.colors["error"],
                    context_name=self.client.context_manager.active_context_name,
                )
                return
        if len(conn_args) > 1:
            ssl_arg = conn_args[1].lower()
            if ssl_arg == "ssl":
                new_ssl = True
            elif ssl_arg == "nossl":
                new_ssl = False
        if new_port is None:
            new_port = DEFAULT_SSL_PORT if new_ssl else DEFAULT_PORT

        if self.client.network.connected:
            self.client.network.disconnect_gracefully("Changing servers")

        self.client.server = new_server_host
        self.client.port = new_port
        self.client.use_ssl = new_ssl

        self.client.add_message(
            f"Attempting to connect to: {self.client.server}:{self.client.port} (SSL: {self.client.use_ssl})",
            self.client.ui.colors["system"],
            context_name="Status",
        )
        logger.info(
            f"Attempting new connection to: {self.client.server}:{self.client.port} (SSL: {self.client.use_ssl})"
        )

        logger.debug("Clearing existing contexts for new server connection.")
        status_context = self.client.context_manager.get_context("Status")
        current_status_msgs = list(status_context.messages) if status_context else []
        status_scroll_offset = (
            status_context.scrollback_offset
            if status_context and hasattr(status_context, "scrollback_offset")
            else 0
        )

        self.client.context_manager.contexts.clear()
        self.client.context_manager.create_context("Status", context_type="status")
        new_status_context = self.client.context_manager.get_context("Status")
        if new_status_context:
            for msg_tuple in current_status_msgs:
                new_status_context.add_message(msg_tuple[0], msg_tuple[1])
            if hasattr(new_status_context, "scrollback_offset"):
                new_status_context.scrollback_offset = status_scroll_offset

        logger.debug(
            f"Restored {len(current_status_msgs)} messages to 'Status' context."
        )

        for ch_name in self.client.initial_channels_list:
            self.client.context_manager.create_context(ch_name, context_type="channel")
            logger.debug(f"Re-created initial channel context: {ch_name}")

        if self.client.initial_channels_list:
            self.client.context_manager.set_active_context(
                self.client.initial_channels_list[0]
            )
        else:
            self.client.context_manager.set_active_context("Status")
        logger.info(
            f"Set active context to '{self.client.context_manager.active_context_name}' after server change."
        )
        self.client.ui_needs_update.set()
        logger.info(
            f"CommandHandler: Before update_connection_params. Server: {self.client.server}, Port: {self.client.port}, SSL: {self.client.use_ssl}, Verify SSL: {self.client.verify_ssl_cert}"
        )
        self.client.network.update_connection_params(
            self.client.server, self.client.port, self.client.use_ssl
        )

    def process_user_command(self, line: str) -> bool:
        """Process a user command (starts with /) or a channel message"""
        if not line.startswith("/"):
            # This is not a slash command, treat as a message to the active context
            if self.client.context_manager.active_context_name:  # Ensure there's an active context
                self.client.handle_text_input(line)  # New method in IRCClient_Logic
                return True  # Indicate it was handled
            else:
                # No active context to send a message to
                self.client.add_message(
                    "No active window to send message to.",
                    self.client.ui.colors["error"],
                    context_name="Status"
                )
                return False # Not handled

        # Existing command processing logic
        command = line[1:].split(" ", 1)
        cmd = command[0].lower()
        args = command[1] if len(command) > 1 else ""

        # Map commands to their handlers
        command_map = {
            "join": self._handle_join_command,
            "j": self._handle_join_command,
            "part": self._handle_part_command,
            "p": self._handle_part_command,
            "msg": self._handle_msg_command,
            "m": self._handle_msg_command,
            "query": self._handle_query_command,
            "nick": self._handle_nick_command,
            "n": self._handle_nick_command,
            "quit": self._handle_quit_command,
            "q": self._handle_quit_command,
            "whois": self._handle_whois_command,
            "w": self._handle_whois_command,
            "me": self._handle_me_command,
            "away": self._handle_away_command,
            "invite": self._handle_invite_command,
            "i": self._handle_invite_command,
            "topic": self._handle_topic_command,
            "t": self._handle_topic_command,
            "raw": self._handle_raw_command,
            "quote": self._handle_raw_command,
            "r": self._handle_raw_command,
            "connect": self._handle_connect_command,
            "server": self._handle_connect_command,
            "s": self._handle_connect_command,
            "disconnect": self._handle_disconnect_command,
            "d": self._handle_disconnect_command,
            "clear": self._handle_clear_command,
            "c": self._handle_clear_command,
            "next": self._handle_next_window_command,
            "nextwindow": self._handle_next_window_command,
            "prev": self._handle_prev_window_command,
            "prevwindow": self._handle_prev_window_command,
            "win": self._handle_window_command,
            "window": self._handle_window_command,
            "close": self._handle_close_command,
            "wc": self._handle_close_command,
            "partchannel": self._handle_close_command,
            "cyclechannel": self._handle_cycle_channel_command,
            "cc": self._handle_cycle_channel_command,
            "prevchannel": self._handle_prev_channel_command,
            "pc": self._handle_prev_channel_command,
            "userlistscroll": self._handle_userlist_scroll_command,
            "u": self._handle_userlist_scroll_command,
            "status": self._handle_status_command,
            "kick": self._handle_kick_command,
            "k": self._handle_kick_command,
            "notice": self._handle_notice_command,
            "no": self._handle_notice_command,
            "set": self._handle_set_command,
            "se": self._handle_set_command,
            "on": self.trigger_commands.handle_on_command,
            # Fun commands
            "slap": self._handle_slap_command,
            "8ball": self._handle_8ball_command,
            "dice": self._handle_dice_command,
            "roll": self._handle_dice_command,
            "rainbow": self._handle_rainbow_command,
            "reverse": self._handle_reverse_command,
            "wave": self._handle_wave_command,
            "ascii": self._handle_ascii_command,
        }

        if cmd in command_map:
            command_map[cmd](args)
            return True
        else:
            self.client.add_message(
                f"Unknown command: {cmd}",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return True

    def _handle_slap_command(self, args_str: str):
        """Handle the /slap command - slap someone with a random item"""
        import random

        parts = self._ensure_args(args_str, "Usage: /slap <nickname>")
        if not parts:
            return

        target = parts[0]
        items = [
            "a large trout",
            "a wet noodle",
            "a rubber chicken",
            "a sock full of pennies",
            "a dictionary",
            "a rubber duck",
            "a pillow",
            "a keyboard",
            "a mouse",
            "a monitor",
            "a coffee cup",
            "a banana",
            "a cactus",
            "a fish",
            "a brick",
        ]

        item = random.choice(items)
        message = f"*slaps {target} around a bit with {item}*"
        self.client.add_message(message, self.client.ui.colors["action"])

    def _handle_8ball_command(self, args_str: str):
        """Handle the /8ball command - get a random fortune"""
        import random

        if not self._ensure_args(args_str, "Usage: /8ball <question>"):
            return

        answers = [
            "It is certain.",
            "It is decidedly so.",
            "Without a doubt.",
            "Yes, definitely.",
            "You may rely on it.",
            "As I see it, yes.",
            "Most likely.",
            "Outlook good.",
            "Yes.",
            "Signs point to yes.",
            "Reply hazy, try again.",
            "Ask again later.",
            "Better not tell you now.",
            "Cannot predict now.",
            "Concentrate and ask again.",
            "Don't count on it.",
            "My reply is no.",
            "My sources say no.",
            "Outlook not so good.",
            "Very doubtful.",
        ]

        answer = random.choice(answers)
        self.client.add_message(f"🎱 {answer}", self.client.ui.colors["system"])

    def _handle_dice_command(self, args_str: str):
        """Handle the /dice command - roll dice in NdN format"""
        import random
        import re

        parts = self._ensure_args(args_str, "Usage: /dice <NdN> (e.g., 2d6 for two six-sided dice)")
        if not parts:
            return

        # args_str is confirmed to be present by _ensure_args
        match = re.match(r"(\d+)d(\d+)", args_str)
        if not match:
            self.client.add_message(
                "Invalid dice format. Use NdN (e.g., 2d6)",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return

        num_dice = int(match.group(1))
        sides = int(match.group(2))

        if num_dice > 100 or sides > 100:
            self.client.add_message(
                "Too many dice or sides! Keep it reasonable.",
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

    def _handle_rainbow_command(self, args_str: str):
        """Handle the /rainbow command - make text colorful"""
        if not self._ensure_args(args_str, "Usage: /rainbow <text>"):
            return

        # ANSI color codes for rainbow
        colors = [
            "\033[31m",  # Red
            "\033[33m",  # Yellow
            "\033[32m",  # Green
            "\033[36m",  # Cyan
            "\033[34m",  # Blue
            "\033[35m",  # Magenta
        ]

        reset = "\033[0m"
        rainbow_text = ""
        for i, char in enumerate(args_str):
            color = colors[i % len(colors)]
            rainbow_text += f"{color}{char}{reset}"

        self.client.add_message(rainbow_text, self.client.ui.colors["system"])

    def _handle_reverse_command(self, args_str: str):
        """Handle the /reverse command - reverse text"""
        if not self._ensure_args(args_str, "Usage: /reverse <text>"):
            return

        reversed_text = args_str[::-1] # args_str is confirmed present by _ensure_args
        self.client.add_message(reversed_text, self.client.ui.colors["system"])

    def _handle_wave_command(self, args_str: str):
        """Handle the /wave command - make text wave"""
        if not self._ensure_args(args_str, "Usage: /wave <text>"):
            return

        # args_str is confirmed present by _ensure_args
        wave_chars = " .,-~:;=!*#$@"
        wave_text = ""
        for i, char in enumerate(args_str):
            if char.isspace():
                wave_text += char
            else:
                wave_char = wave_chars[i % len(wave_chars)]
                wave_text += wave_char

        self.client.add_message(wave_text, self.client.ui.colors["system"])

    def _handle_ascii_command(self, args_str: str):
        """Handle the /ascii command - convert text to ASCII art"""
        try:
            import pyfiglet
        except ImportError:
            self.client.add_message(
                "ASCII art requires pyfiglet. Install with: pip install pyfiglet",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return

        if not self._ensure_args(args_str, "Usage: /ascii <text>"):
            return

        # args_str is confirmed present by _ensure_args
        try:
            ascii_art = pyfiglet.figlet_format(args_str)
            for line in ascii_art.split("\n"):
                if line.strip():  # Only print non-empty lines
                    self.client.add_message(line, self.client.ui.colors["system"])
        except Exception as e:
            self.client.add_message(
                f"Error creating ASCII art: {str(e)}",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )

    def _handle_join_command(self, args_str: str):
        """Handle the /join command"""
        parts = self._ensure_args(args_str, "Usage: /join <channel>")
        if not parts:
            return
        channel = parts[0]
        if not channel.startswith("#"):
            channel = f"#{channel}"
        self.client.network.send_raw(f"JOIN {channel}")

    def _handle_part_command(self, args_str: str):
        """Handle the /part command"""
        # This command can have 1 or 2 parts (channel, or channel + reason)
        # _ensure_args with num_expected_parts=1 checks if args_str is present.
        # The specific splitting logic for channel and reason needs to remain here.
        if not self._ensure_args(args_str, "Usage: /part [channel] [reason]"):
            return

        parts = args_str.split(" ", 1) # args_str is confirmed present
        channel = parts[0]
        reason = parts[1] if len(parts) > 1 else None
        if not channel.startswith("#"):
            channel = f"#{channel}"
        if reason:
            self.client.network.send_raw(f"PART {channel} :{reason}")
        else:
            self.client.network.send_raw(f"PART {channel}")

    def _handle_msg_command(self, args_str: str):
        """Handle the /msg command"""
        parts = self._ensure_args(args_str, "Usage: /msg <nick> <message>", num_expected_parts=2)
        if not parts: # _ensure_args already showed usage if needed
            return

        # args_str is confirmed present and has at least 2 parts if num_expected_parts=2
        # For msg, we need to split specifically for "target" and "the rest is message"
        target_and_message = args_str.split(" ", 1)
        target = target_and_message[0]
        message = target_and_message[1] # This is safe due to num_expected_parts=2 check
        self.client.network.send_raw(f"PRIVMSG {target} :{message}")

    def _handle_query_command(self, args_str: str):
        """Handle the /query command"""
        # This command needs at least a target nick.
        if not self._ensure_args(args_str, "Usage: /query <nick> [message]"):
            return

        parts = args_str.split(" ", 1) # args_str is confirmed present
        target = parts[0]
        message = parts[1] if len(parts) > 1 else None
        self.client.context_manager.create_context(target, context_type="query")
        self.client.context_manager.set_active_context(target)
        if message:
            self.client.network.send_raw(f"PRIVMSG {target} :{message}")

    def _handle_nick_command(self, args_str: str):
        """Handle the /nick command"""
        parts = self._ensure_args(args_str, "Usage: /nick <newnick>")
        if not parts:
            return
        new_nick = parts[0]
        self.client.network.send_raw(f"NICK {new_nick}")

    def _handle_quit_command(self, args_str: str):
        """Handle the /quit command"""
        reason = args_str if args_str else "Leaving"
        self.client.network.disconnect_gracefully(reason)

    def _handle_whois_command(self, args_str: str):
        """Handle the /whois command"""
        parts = self._ensure_args(args_str, "Usage: /whois <nick>")
        if not parts:
            return
        target = parts[0]
        self.client.network.send_raw(f"WHOIS {target}")

    def _handle_me_command(self, args_str: str):
        """Handle the /me command"""
        if not self._ensure_args(args_str, "Usage: /me <action>"):
            return
        # args_str is confirmed present by _ensure_args
        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if not current_context:
            return
        if current_context.type == "channel":
            self.client.network.send_raw(
                f"PRIVMSG {current_context.name} :\x01ACTION {args_str}\x01"
            )
        elif current_context.type == "query":
            self.client.network.send_raw(
                f"PRIVMSG {current_context.name} :\x01ACTION {args_str}\x01"
            )

    def _handle_away_command(self, args_str: str):
        """Handle the /away command"""
        if not args_str:
            self.client.network.send_raw("AWAY")
        else:
            self.client.network.send_raw(f"AWAY :{args_str}")

    def _handle_invite_command(self, args_str: str):
        """Handle the /invite command"""
        parts = self._ensure_args(args_str, "Usage: /invite <nick> [channel]")
        if not parts:
            return

        # parts is confirmed to have at least one element
        nick = parts[0]
        channel = (
            parts[1]
            if len(parts) > 1
            else (self.client.context_manager.active_context_name or "Status")
        )
        if channel and not channel.startswith("#"):
            channel = f"#{channel}"
        self.client.network.send_raw(f"INVITE {nick} {channel}")

    def _handle_raw_command(self, args_str: str):
        """Handle the /raw command"""
        if not self._ensure_args(args_str, "Usage: /raw <raw IRC command>"):
            return
        # args_str is confirmed present
        self.client.network.send_raw(args_str)

    def _handle_disconnect_command(self, args_str: str):
        """Handle the /disconnect command"""
        reason = args_str if args_str else "Disconnecting"
        self.client.network.disconnect_gracefully(reason)

    def _handle_clear_command(self, args_str: str):
        """Handle the /clear command"""
        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if current_context:
            current_context.messages.clear()
            self.client.ui_needs_update.set()

    def _handle_next_window_command(self, args_str: str):
        """Handle the /next command"""
        self.client.switch_active_context("next")

    def _handle_prev_window_command(self, args_str: str):
        """Handle the /prev command"""
        self.client.switch_active_context("prev")

    def _handle_window_command(self, args_str: str):
        """Handle the /window command"""
        parts = self._ensure_args(args_str, "Usage: /window <window name>")
        if not parts:
            return
        target = parts[0]
        self.client.context_manager.set_active_context(target)

    def _handle_close_command(self, args_str: str):
        """Handle the /close command"""
        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if not current_context:
            return
        if current_context.type == "channel":
            self.client.network.send_raw(f"PART {current_context.name}")
        self.client.context_manager.remove_context(current_context.name)

    def _handle_cycle_channel_command(self, args_str: str):
        """Handle the /cycle command"""
        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if not current_context or current_context.type != "channel":
            self.client.add_message(
                "Not in a channel to cycle",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return
        channel = current_context.name
        self.client.network.send_raw(f"PART {channel}")
        self.client.network.send_raw(f"JOIN {channel}")

    def _handle_prev_channel_command(self, args_str: str):
        """Handle the /prevchannel command"""
        self.client.switch_active_channel("prev")

    def _handle_userlist_scroll_command(self, args_str: str):
        """Handle the /userlistscroll command"""
        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if not current_context or current_context.type != "channel":
            return
        try:
            if args_str:
                offset = int(args_str)
            else:
                # If no args, scroll down by 1
                offset = current_context.user_list_scroll_offset + 1
            current_context.user_list_scroll_offset = offset
            self.client.ui_needs_update.set()
        except ValueError:
            pass

    def _handle_status_command(self, args_str: str):
        """Handle the /status command"""
        self.client.context_manager.set_active_context("Status")

    def _handle_kick_command(self, args_str: str):
        """Handle the /kick command"""
        # Needs at least a target nick
        if not self._ensure_args(args_str, "Usage: /kick <nick> [reason]"):
            return

        parts = args_str.split(" ", 1) # args_str is confirmed present
        target = parts[0]
        reason = parts[1] if len(parts) > 1 else None
        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if not current_context or current_context.type != "channel":
            self.client.add_message(
                "Not in a channel to kick from",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return
        if reason:
            self.client.network.send_raw(
                f"KICK {current_context.name} {target} :{reason}"
            )
        else:
            self.client.network.send_raw(f"KICK {current_context.name} {target}")

    def _handle_notice_command(self, args_str: str):
        """Handle the /notice command"""
        parts = self._ensure_args(args_str, "Usage: /notice <target> <message>", num_expected_parts=2)
        if not parts:
            return

        # args_str is confirmed present and has at least 2 parts if num_expected_parts=2
        target_and_message = args_str.split(" ", 1)
        target = target_and_message[0]
        message = target_and_message[1] # Safe due to num_expected_parts=2
        self.client.network.send_raw(f"NOTICE {target} :{message}")

    def _handle_set_command(self, args_str: str):
        """Handle the /set command"""
        parts = self._ensure_args(args_str, "Usage: /set <option> <value>", num_expected_parts=2)
        if not parts:
            return

        # args_str is confirmed present and has at least 2 parts if num_expected_parts=2
        # For set, we need to split specifically for "option" and "the rest is value"
        option_and_value = args_str.split(" ", 1)
        option = option_and_value[0]
        value = option_and_value[1] # Safe due to num_expected_parts=2
        # TODO: Implement setting configuration options
        self.client.add_message(
            f"Setting {option} to {value}",
            self.client.ui.colors["system"],
            context_name=self.client.context_manager.active_context_name,
        )
