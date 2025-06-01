# command_handler.py
import logging
from typing import TYPE_CHECKING, List, Optional, Tuple # Added Tuple
from features.triggers.trigger_commands import TriggerCommands
from context_manager import ChannelJoinStatus, Context # Added import, Added Context
from fun_commands_handler import FunCommandsHandler
from channel_commands_handler import ChannelCommandsHandler
from server_commands_handler import ServerCommandsHandler
from config import get_all_settings, set_config_value, get_config_value, config as global_config_parser # Added for /set command

if TYPE_CHECKING:
    from irc_client_logic import (
        IRCClient_Logic,
    )  # To avoid circular import for type hinting

from context_manager import Context as CTX_Type # For type hinting
# Get a logger instance
logger = logging.getLogger("pyrc.command_handler")


class CommandHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic
        self.trigger_commands = TriggerCommands(client_logic)
        self.fun_commands = FunCommandsHandler(client_logic)
        self.channel_commands = ChannelCommandsHandler(client_logic)
        self.server_commands = ServerCommandsHandler(client_logic)

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
        Returns a list of parts split appropriately if validation succeeds.
        - If num_expected_parts is 1, returns [args_str] (if args_str is not empty).
        - If num_expected_parts > 1, returns args_str.split(" ", num_expected_parts - 1).
        """
        if not args_str:
            self.client.add_message(
                usage_message,
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return None

        if num_expected_parts == 1:
            # For num_expected_parts = 1, we just need args_str to be non-empty (checked above).
            # Return it as a single-element list, consistent with splitting behavior.
            return [args_str]

        # For num_expected_parts > 1
        # Split only up to num_expected_parts - 1 times to get the required initial parts,
        # with the last element containing the rest of the string.
        parts = args_str.split(" ", num_expected_parts - 1)

        if len(parts) < num_expected_parts:
            self.client.add_message(
                usage_message,
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return None

        return parts

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
            "join": self.channel_commands.handle_join_command,
            "j": self.channel_commands.handle_join_command,
            "part": self.channel_commands.handle_part_command,
            "p": self.channel_commands.handle_part_command,
            "msg": self._handle_msg_command,
            "m": self._handle_msg_command,
            "query": self._handle_query_command,
            "nick": self._handle_nick_command,
            "n": self._handle_nick_command,
            "quit": self.server_commands.handle_quit_command,
            "q": self.server_commands.handle_quit_command,
            "whois": self._handle_whois_command,
            "w": self._handle_whois_command,
            "me": self._handle_me_command,
            "away": self._handle_away_command,
            "invite": self.channel_commands.handle_invite_command,
            "i": self.channel_commands.handle_invite_command,
            "topic": self.channel_commands.handle_topic_command,
            "t": self.channel_commands.handle_topic_command,
            "raw": self.server_commands.handle_raw_command,
            "quote": self.server_commands.handle_raw_command,
            "r": self.server_commands.handle_raw_command,
            "connect": self.server_commands.handle_connect_command,
            "server": self.server_commands.handle_connect_command,
            "s": self.server_commands.handle_connect_command,
            "disconnect": self.server_commands.handle_disconnect_command,
            "d": self.server_commands.handle_disconnect_command,
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
            "partchannel": self._handle_close_command, # This is an alias for /close, might need review if its behavior should differ for channels specifically.
            "cyclechannel": self.channel_commands.handle_cycle_channel_command,
            "cc": self.channel_commands.handle_cycle_channel_command,
            "prevchannel": self._handle_prev_channel_command,
            "pc": self._handle_prev_channel_command,
            "userlistscroll": self._handle_userlist_scroll_command,
            "u": self._handle_userlist_scroll_command,
            "status": self._handle_status_command,
            "kick": self.channel_commands.handle_kick_command,
            "k": self.channel_commands.handle_kick_command,
            "notice": self._handle_notice_command,
            "no": self._handle_notice_command,
            "set": self._handle_set_command,
            "se": self._handle_set_command,
            "on": self.trigger_commands.handle_on_command,
            # Fun commands
            "slap": self.fun_commands.handle_slap_command,
            "8ball": self.fun_commands.handle_8ball_command,
            "dice": self.fun_commands.handle_dice_command,
            "roll": self.fun_commands.handle_dice_command,
            "rainbow": self.fun_commands.handle_rainbow_command,
            "reverse": self.fun_commands.handle_reverse_command,
            "wave": self.fun_commands.handle_wave_command,
            "ascii": self.fun_commands.handle_ascii_command,
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

    def _handle_msg_command(self, args_str: str):
        """Handle the /msg command"""
        parts = self._ensure_args(args_str, "Usage: /msg <nick> <message>", num_expected_parts=2)
        if not parts: # _ensure_args already showed usage if needed
            return

        # 'parts' will be [target, message_body] due to num_expected_parts=2
        target = parts[0]
        message = parts[1]
        self.client.network.send_raw(f"PRIVMSG {target} :{message}")

    def _handle_query_command(self, args_str: str):
        """Handle the /query command"""
        # This command needs at least a target nick. Can optionally have a message.
        # num_expected_parts=1 ensures target is present.
        # num_expected_parts=2 would ensure target and start of message.
        # Let's use num_expected_parts=1 to get the target, then check for message.
        parts = self._ensure_args(args_str, "Usage: /query <nick> [message]", num_expected_parts=1)
        if not parts:
            return

        target = parts[0] # This is args_str if num_expected_parts=1, or first part if more.
                         # Actually, if num_expected_parts=1, parts is [args_str]
                         # So target will be the full args_str. We need to re-split if there's a message.

        # Re-split args_str to separate target and potential message
        query_parts = args_str.split(" ", 1)
        target_nick = query_parts[0]
        message = query_parts[1] if len(query_parts) > 1 else None

        self.client.context_manager.create_context(target_nick, context_type="query")
        self.client.context_manager.set_active_context(target_nick)
        if message:
            self.client.network.send_raw(f"PRIVMSG {target_nick} :{message}")

    def _handle_nick_command(self, args_str: str):
        """Handle the /nick command"""
        parts = self._ensure_args(args_str, "Usage: /nick <newnick>")
        if not parts:
            return
        new_nick = parts[0]
        self.client.network.send_raw(f"NICK {new_nick}")

    def _handle_whois_command(self, args_str: str):
        """Handle the /whois command"""
        parts = self._ensure_args(args_str, "Usage: /whois <nick>")
        if not parts:
            return
        target = parts[0]
        self.client.network.send_raw(f"WHOIS {target}")

    def _handle_me_command(self, args_str: str):
        """Handle the /me command"""
        # _ensure_args with num_expected_parts=1 ensures args_str (the action) is present
        if not self._ensure_args(args_str, "Usage: /me <action>"):
            return

        action_text = args_str # Since num_expected_parts=1, parts[0] would be args_str

        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if not current_context:
            self.client.add_message("Cannot /me: No active context.", self.client.ui.colors["error"], context_name="Status")
            return

        if current_context.type == "channel":
            if hasattr(current_context, 'join_status') and current_context.join_status == ChannelJoinStatus.FULLY_JOINED:
                self.client.network.send_raw(
                    f"PRIVMSG {current_context.name} :\x01ACTION {action_text}\x01"
                )
            else:
                self.client.add_message(f"Cannot /me: Channel {current_context.name} not fully joined.", self.client.ui.colors["error"], context_name=current_context.name)
        elif current_context.type == "query":
            self.client.network.send_raw(
                f"PRIVMSG {current_context.name} :\x01ACTION {action_text}\x01"
            )
        else: # Status window or other
            self.client.add_message("Cannot /me in this window.", self.client.ui.colors["error"], context_name=current_context.name)

    def _handle_away_command(self, args_str: str):
        """Handle the /away command"""
        if not args_str:
            self.client.network.send_raw("AWAY")
        else:
            self.client.network.send_raw(f"AWAY :{args_str}")

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

    def _close_channel_context(self, channel_context: 'CTX_Type'):
        """Helper to handle closing (parting) a channel context."""
        if hasattr(channel_context, 'join_status'): # Defensive check
            channel_context.join_status = ChannelJoinStatus.PARTING
        self.client.network.send_raw(f"PART {channel_context.name}")
        self.client.add_message(
            f"Parting {channel_context.name}...",
            self.client.ui.colors["system"],
            context_name=channel_context.name
        )
        # Context removal for channels is expected to be handled upon receiving server PART confirmation.

    def _close_query_or_generic_context(self, context_obj: 'CTX_Type'):
        """Helper to handle closing a query or generic context."""
        context_name_to_close = context_obj.name # Store before removal for the message
        self.client.context_manager.remove_context(context_name_to_close)
        self.client.add_message(
            f"Closed window: {context_name_to_close}",
            self.client.ui.colors["system"],
            context_name="Status" # Message about closed window goes to Status window
        )

    def _handle_close_command(self, args_str: str): # args_str is kept for dispatcher compatibility
        """Handle the /close command. For channels, it parts. For others, it just removes the context."""
        active_ctx_name = self.client.context_manager.active_context_name
        if not active_ctx_name:
            self.client.add_message("No active window to close.", self.client.ui.colors["error"], context_name="Status")
            return

        current_context = self.client.context_manager.get_context(active_ctx_name)
        if not current_context:
            logger.error(f"/close: Active context '{active_ctx_name}' not found in manager.")
            return

        if current_context.type == "channel":
            self._close_channel_context(current_context)
        elif current_context.type == "query" or current_context.type == "generic":
            self._close_query_or_generic_context(current_context)
        elif current_context.type == "status":
            self.client.add_message("Cannot close the Status window.", self.client.ui.colors["error"], context_name="Status")

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

    def _handle_notice_command(self, args_str: str):
        """Handle the /notice command"""
        parts = self._ensure_args(args_str, "Usage: /notice <target> <message>", num_expected_parts=2)
        if not parts:
            return

        # 'parts' will be [target, message_body]
        target = parts[0]
        message = parts[1]
        self.client.network.send_raw(f"NOTICE {target} :{message}")

    def _handle_set_command(self, args_str: str):
        """
        Handle the /set command.
        - /set : Lists all settings.
        - /set <key> : Shows value of <key>. Searches all sections.
        - /set <section.key> : Shows value of <section.key>.
        - /set <section.key> <value> : Sets <section.key> to <value>.
        """
        active_context_name = self.client.context_manager.active_context_name or "Status"
        system_color = self.client.ui.colors.get("system", 0) # Use .get for safety
        error_color = self.client.ui.colors.get("error", 0)   # Use .get for safety

        stripped_args = args_str.strip()

        if not stripped_args:
            # Case 1: /set (list all settings)
            all_settings = get_all_settings()
            if not all_settings:
                self.client.add_message("No settings found.", system_color, context_name=active_context_name)
                return

            self.client.add_message("Current settings:", system_color, context_name=active_context_name)
            for section, settings in all_settings.items():
                self.client.add_message(f"[{section}]", system_color, context_name=active_context_name)
                for key, val in settings.items():
                    self.client.add_message(f"  {key} = {val}", system_color, context_name=active_context_name)
            return

        parts = stripped_args.split(" ", 1)
        variable_arg = parts[0]

        if len(parts) == 1:
            # Case 2: /set <variable> (view a setting)
            section_name_filter: Optional[str] = None
            key_name_filter: str = variable_arg

            if "." in variable_arg:
                try:
                    section_name_filter, key_name_filter = variable_arg.split(".", 1)
                    if not section_name_filter or not key_name_filter: # Ensure both parts are non-empty
                        raise ValueError("Section or key part is empty.")
                except ValueError:
                    self.client.add_message(f"Invalid format for variable: '{variable_arg}'. Use 'key' or 'section.key'.", error_color, context_name=active_context_name)
                    return

            found_settings_messages = []
            all_current_settings = get_all_settings() # Get fresh settings

            if section_name_filter:
                # Specific section.key provided
                if section_name_filter in all_current_settings and key_name_filter in all_current_settings[section_name_filter]:
                    value = all_current_settings[section_name_filter][key_name_filter]
                    found_settings_messages.append(f"{section_name_filter}.{key_name_filter} = {value}")
                else:
                    self.client.add_message(f"Setting '{variable_arg}' not found.", error_color, context_name=active_context_name)
                    return
            else:
                # Key only, search all sections
                for sec, settings_in_sec in all_current_settings.items():
                    if key_name_filter in settings_in_sec:
                        found_settings_messages.append(f"{sec}.{key_name_filter} = {settings_in_sec[key_name_filter]}")

            if not found_settings_messages:
                self.client.add_message(f"Setting '{key_name_filter}' not found in any section.", error_color, context_name=active_context_name)
            else:
                for setting_str in found_settings_messages:
                    self.client.add_message(setting_str, system_color, context_name=active_context_name)
            return

        elif len(parts) == 2:
            # Case 3: /set <variable> <value> (set a setting)
            value_arg = parts[1] # This will be the rest of the string

            if "." not in variable_arg:
                self.client.add_message("Usage: /set <section.key> <value>", error_color, context_name=active_context_name)
                self.client.add_message("For setting a value, 'section.key' format is required.", error_color, context_name=active_context_name)
                return

            try:
                section_to_set, key_to_set = variable_arg.split(".", 1)
                if not section_to_set or not key_to_set: # Ensure both parts are non-empty
                    raise ValueError("Section or key part is empty for setting.")
            except ValueError:
                self.client.add_message(f"Invalid format for variable: '{variable_arg}'. Use 'section.key'.", error_color, context_name=active_context_name)
                return

            if set_config_value(section_to_set, key_to_set, value_arg):
                self.client.add_message(f"Set {section_to_set}.{key_to_set} = {value_arg}", system_color, context_name=active_context_name)
                self.client.add_message("Note: Some settings may require an application restart to take full effect.", system_color, context_name=active_context_name)
                # The application's global config variables (like IRC_NICK) are loaded at startup.
                # For changes to take effect dynamically, those variables would need to be reloaded,
                # or the components using them would need to re-fetch from config.
                # This is beyond the scope of just saving to the INI file.
            else:
                self.client.add_message(f"Failed to set {section_to_set}.{key_to_set}.", error_color, context_name=active_context_name)
            return

        # This part should ideally not be reached if the logic for 0, 1, or 2+ parts is correct.
        # Adding a general usage message as a fallback.
        self.client.add_message("Usage: /set [<section.key> [<value>]]", error_color, context_name=active_context_name)
