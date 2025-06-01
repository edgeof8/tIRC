import logging
from typing import TYPE_CHECKING, List, Optional, Tuple
from features.triggers.trigger_commands import TriggerCommands
from context_manager import ChannelJoinStatus, Context
from fun_commands_handler import FunCommandsHandler
from channel_commands_handler import ChannelCommandsHandler
from server_commands_handler import ServerCommandsHandler
from config import (
    get_all_settings, set_config_value, get_config_value, config as global_config_parser,
    add_ignore_pattern, remove_ignore_pattern, IGNORED_PATTERNS
)

if TYPE_CHECKING:
    from irc_client_logic import (
        IRCClient_Logic,
    )

from context_manager import Context as CTX_Type
logger = logging.getLogger("pyrc.command_handler")


class CommandHandler:
    COMMAND_USAGE_STRINGS = {
        "join": "Usage: /join <channel> - Joins the specified channel.",
        "part": "Usage: /part [channel] [reason] - Leaves the specified or current channel. If [channel] is omitted, parts the active channel.",
        "msg": "Usage: /msg <nick> <message> - Sends a private message to <nick>.",
        "query": "Usage: /query <nick> [message] - Opens a private message window with <nick> and optionally sends an initial message.",
        "nick": "Usage: /nick <newnick> - Changes your nickname to <newnick>.",
        "quit": "Usage: /quit [message] - Disconnects from the server with an optional quit message.",
        "whois": "Usage: /whois <nick> - Retrieves WHOIS information for <nick>.",
        "me": "Usage: /me <action> - Sends an action (CTCP ACTION) to the current channel or query.",
        "away": "Usage: /away [message] - Sets your away status. No message marks you as back.",
        "invite": "Usage: /invite <nick> [channel] - Invites <nick> to [channel] (current channel if omitted).",
        "topic": "Usage: /topic [newtopic] - Shows current topic or sets a new one for the active channel.",
        "raw": "Usage: /raw <raw IRC command> - Sends a raw command line to the server.",
        "connect": "Usage: /connect <server[:port]> [ssl|nossl] - Connects to the specified server.",
        "disconnect": "Usage: /disconnect [reason] - Disconnects from the current server.",
        "clear": "Usage: /clear - Clears messages from the current window.",
        "nextwindow": "Usage: /nextwindow (aliases: /next, Ctrl+N) - Switches to the next window.",
        "prevwindow": "Usage: /prevwindow (aliases: /prev, Ctrl+P) - Switches to the previous window.",
        "window": "Usage: /window <name|number> - Switches to the window specified by name or number.",
        "close": "Usage: /close (aliases: /wc, /partchannel) - Closes the current query window or parts the current channel.",
        "cyclechannel": "Usage: /cyclechannel (alias: /cc) - Parts and rejoins the current channel.",
        "prevchannel": "Usage: /prevchannel (alias: /pc) - Switches to the previously active channel/context (implementation might vary).",
        "userlistscroll": "Usage: /userlistscroll [offset] (aliases: /u [offset], Ctrl+U) - Scrolls user list. Ctrl+U pages. [offset] sets absolute scroll.",
        "status": "Usage: /status - Switches to the Status window.",
        "kick": "Usage: /kick <nick> [reason] - Kicks <nick> from the current channel.",
        "notice": "Usage: /notice <target> <message> - Sends a NOTICE to <target> (nick or channel).",
        "set": (
            "Usage: /set [<section.key> [<value>]] (alias: /se)\n"
            "/set : Lists all current settings.\n"
            "/set <key> : Shows value of <key> (searches all sections).\n"
            "/set <section.key> : Shows value of <section.key>.\n"
            "/set <section.key> <value> : Modifies the setting and saves it to pyterm_irc_config.ini."
        ),
        "on": (
            "Usage: /on <subcommand> [args] - Manages event triggers. Type /on for detailed subcommands.\n"
            "See also: /on add, /on list, /on remove, /on enable, /on disable."
        ),
        "slap": "Usage: /slap <nickname> - Slaps <nickname> with a random item.",
        "8ball": "Usage: /8ball <question> - Asks the Magic 8-Ball a question.",
        "dice": "Usage: /dice <NdN> (e.g., 2d6, alias /roll) - Rolls NdN dice.",
        "rainbow": "Usage: /rainbow <text> - Sends <text> in rainbow colors to the current channel/query.",
        "reverse": "Usage: /reverse <text> - Sends <text> reversed to the current channel/query.",
        "wave": "Usage: /wave <text> - Sends <text> with a wave effect to the current channel/query.",
        "ascii": "Usage: /ascii <text> - Converts <text> to ASCII art and sends it to the current channel/query.",
        "help": "Usage: /help [command] - Shows this help message or help for a specific command.",
        "ignore": "Usage: /ignore <nick|hostmask> - Ignores messages from the specified user or hostmask. Wildcards * and ? can be used (e.g., *!*@*.someisp.com).",
        "unignore": "Usage: /unignore <nick|hostmask> - Removes an ignore pattern.",
        "listignores": "Usage: /listignores - Lists all current ignore patterns.",
    }


    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic
        self.trigger_commands = TriggerCommands(client_logic)
        self.fun_commands = FunCommandsHandler(client_logic)
        self.channel_commands = ChannelCommandsHandler(client_logic)
        self.server_commands = ServerCommandsHandler(client_logic)

        self.command_map = {
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
            "partchannel": self._handle_close_command,
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
            "slap": self.fun_commands.handle_slap_command,
            "8ball": self.fun_commands.handle_8ball_command,
            "dice": self.fun_commands.handle_dice_command,
            "roll": self.fun_commands.handle_dice_command,
            "rainbow": self.fun_commands.handle_rainbow_command,
            "reverse": self.fun_commands.handle_reverse_command,
            "wave": self.fun_commands.handle_wave_command,
            "ascii": self.fun_commands.handle_ascii_command,
            "help": self._handle_help_command,
            "h": self._handle_help_command,
            "ignore": self._handle_ignore_command,
            "unignore": self._handle_unignore_command,
            "listignores": self._handle_listignores_command,
        }

        self.command_primary_map = {}
        seen_handlers = {}
        for cmd_name, handler_func in self.command_map.items():
            if cmd_name in ["help", "h"]:
                continue

            if handler_func in seen_handlers:
                primary_name = seen_handlers[handler_func]
                self.command_primary_map[cmd_name] = primary_name
            else:
                seen_handlers[handler_func] = cmd_name

    def _handle_help_command(self, args_str: str):
        active_context_name = self.client.context_manager.active_context_name or "Status"
        system_color = self.client.ui.colors.get("system", 0)
        error_color = self.client.ui.colors.get("error", 0)

        if not args_str:
            self.client.add_message("Available commands (use /help <command> for details):", system_color, context_name=active_context_name)

            commands_to_list = sorted([cmd for cmd in self.command_map.keys() if cmd not in ["h"]])

            line_buffer = []
            current_line_len = 0
            max_line_width = getattr(self.client.ui, 'msg_win_width', 70) - 5

            for cmd_name in commands_to_list:
                display_cmd = f"/{cmd_name}"
                if not line_buffer or current_line_len + len(display_cmd) + 2 > max_line_width:
                    if line_buffer:
                        self.client.add_message(", ".join(line_buffer), system_color, context_name=active_context_name)
                    line_buffer = [display_cmd]
                    current_line_len = len(display_cmd)
                else:
                    line_buffer.append(display_cmd)
                    current_line_len += len(display_cmd) + 2

            if line_buffer:
                self.client.add_message(", ".join(line_buffer), system_color, context_name=active_context_name)

            self.client.add_message("Common aliases: /j (join), /p (part), /m (msg), /q (quit), /w (whois), /r (raw), /s (connect/server), /d (disconnect), /c (clear), /wc (close), /k (kick), /pc (prevchannel), /u (userlistscroll), /se (set), /no (notice), /cc (cyclechannel), /h (help).", system_color, context_name=active_context_name)
            self.client.add_message("For event triggers, type /on for specific help.", system_color, context_name=active_context_name)

        else:
            command_name_from_user = args_str.lower().lstrip('/')

            primary_command_name = self.command_primary_map.get(command_name_from_user, command_name_from_user)

            if primary_command_name == "on":
                self.trigger_commands._show_usage()
                return

            if primary_command_name in self.COMMAND_USAGE_STRINGS:
                usage = self.COMMAND_USAGE_STRINGS[primary_command_name]
                if primary_command_name != command_name_from_user:
                     self.client.add_message(f"(Showing help for '/{primary_command_name}', as '/{command_name_from_user}' is an alias)", system_color, context_name=active_context_name)
                for line in usage.splitlines():
                     self.client.add_message(line, system_color, context_name=active_context_name)
            else:
                self.client.add_message(f"No help available for command: {command_name_from_user}", error_color, context_name=active_context_name)


    def get_available_commands_for_tab_complete(self) -> List[str]:
        """
        Returns a list of commands primarily for tab-completion,
        dynamically generated from the command_map.
        """
        return ["/" + cmd for cmd in self.command_map.keys()]

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
            if self.client.context_manager.active_context_name:
                self.client.handle_text_input(line)
                return True
            else:
                self.client.add_message(
                    "No active window to send message to.",
                    self.client.ui.colors["error"],
                    context_name="Status"
                )
                return False

        command_parts = line[1:].split(" ", 1)
        cmd = command_parts[0].lower()
        args = command_parts[1] if len(command_parts) > 1 else ""

        if cmd in self.command_map:
            self.command_map[cmd](args)
            return True
        else:
            self.client.add_message(
                f"Unknown command: {cmd}",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return True

    def _handle_msg_command(self, args_str: str):
        """Handle the /msg command"""
        parts = self._ensure_args(args_str, self.COMMAND_USAGE_STRINGS["msg"], num_expected_parts=2)
        if not parts:
            return
        target = parts[0]
        message = parts[1]
        self.client.network.send_raw(f"PRIVMSG {target} :{message}")

    def _handle_query_command(self, args_str: str):
        """Handle the /query command"""
        parts = self._ensure_args(args_str, self.COMMAND_USAGE_STRINGS["query"], num_expected_parts=1)
        if not parts:
            return
        query_parts = args_str.split(" ", 1)
        target_nick = query_parts[0]
        message = query_parts[1] if len(query_parts) > 1 else None
        self.client.context_manager.create_context(target_nick, context_type="query")
        self.client.context_manager.set_active_context(target_nick)
        if message:
            self.client.network.send_raw(f"PRIVMSG {target_nick} :{message}")

    def _handle_nick_command(self, args_str: str):
        """Handle the /nick command"""
        parts = self._ensure_args(args_str, self.COMMAND_USAGE_STRINGS["nick"])
        if not parts:
            return
        new_nick = parts[0]
        self.client.network.send_raw(f"NICK {new_nick}")

    def _handle_whois_command(self, args_str: str):
        """Handle the /whois command"""
        parts = self._ensure_args(args_str, self.COMMAND_USAGE_STRINGS["whois"])
        if not parts:
            return
        target = parts[0]
        self.client.network.send_raw(f"WHOIS {target}")

    def _handle_me_command(self, args_str: str):
        """Handle the /me command"""
        if not self._ensure_args(args_str, self.COMMAND_USAGE_STRINGS["me"]):
            return
        action_text = args_str
        current_context_obj = self.client.context_manager.get_active_context()
        if not current_context_obj:
            self.client.add_message("Cannot /me: No active context.", self.client.ui.colors["error"], context_name="Status")
            return

        if current_context_obj.type == "channel":
            if hasattr(current_context_obj, 'join_status') and current_context_obj.join_status == ChannelJoinStatus.FULLY_JOINED:
                self.client.network.send_raw(
                    f"PRIVMSG {current_context_obj.name} :\x01ACTION {action_text}\x01"
                )
            else:
                self.client.add_message(f"Cannot /me: Channel {current_context_obj.name} not fully joined.", self.client.ui.colors["error"], context_name=current_context_obj.name)
        elif current_context_obj.type == "query":
            self.client.network.send_raw(
                f"PRIVMSG {current_context_obj.name} :\x01ACTION {action_text}\x01"
            )
        else:
            self.client.add_message("Cannot /me in this window.", self.client.ui.colors["error"], context_name=current_context_obj.name)

    def _handle_away_command(self, args_str: str):
        """Handle the /away command"""
        if not args_str:
            self.client.network.send_raw("AWAY")
        else:
            self.client.network.send_raw(f"AWAY :{args_str}")

    def _handle_clear_command(self, args_str: str):
        """Handle the /clear command"""
        current_context = self.client.context_manager.get_active_context()
        if current_context:
            current_context.messages.clear()
            self.client.ui_needs_update.set()

    def _handle_next_window_command(self, args_str: str):
        """Handle the /next or /nextwindow command"""
        self.client.switch_active_context("next")

    def _handle_prev_window_command(self, args_str: str):
        """Handle the /prev or /prevwindow command"""
        self.client.switch_active_context("prev")

    def _handle_window_command(self, args_str: str):
        """Handle the /window or /win command"""
        parts = self._ensure_args(args_str, self.COMMAND_USAGE_STRINGS["window"])
        if not parts:
            return
        target = parts[0]
        self.client.context_manager.set_active_context(target)

    def _close_channel_context(self, channel_context: 'CTX_Type'):
        """Helper to handle closing (parting) a channel context."""
        if hasattr(channel_context, 'join_status'):
            channel_context.join_status = ChannelJoinStatus.PARTING
        self.client.network.send_raw(f"PART {channel_context.name}")
        self.client.add_message(
            f"Parting {channel_context.name}...",
            self.client.ui.colors["system"],
            context_name=channel_context.name
        )

    def _close_query_or_generic_context(self, context_obj: 'CTX_Type'):
        """Helper to handle closing a query or generic context."""
        context_name_to_close = context_obj.name
        self.client.context_manager.remove_context(context_name_to_close)
        self.client.add_message(
            f"Closed window: {context_name_to_close}",
            self.client.ui.colors["system"],
            context_name="Status"
        )

    def _handle_close_command(self, args_str: str):
        """Handle the /close, /wc, /partchannel command."""
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
        """Handle the /userlistscroll or /u command"""
        active_ctx = self.client.context_manager.get_active_context()
        if not active_ctx or active_ctx.type != "channel":
            self.client.add_message(
                "User list scroll is only available in channel windows.",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status"
            )
            return

        if not args_str:
             self.client.ui.scroll_user_list("pagedown")
        else:
            try:
                arg_lower = args_str.lower()
                if arg_lower in ["up", "down", "pageup", "pagedown", "top", "bottom"]:
                    self.client.ui.scroll_user_list(arg_lower)
                else:
                    offset = int(args_str)
                    if offset > 0:
                        self.client.ui.scroll_user_list("down", lines_arg=offset)
                    elif offset < 0:
                        self.client.ui.scroll_user_list("up", lines_arg=abs(offset))
            except ValueError:
                self.client.add_message(
                    f"Invalid argument for userlistscroll: '{args_str}'. Use up, down, pageup, pagedown, top, bottom, or a number.",
                    self.client.ui.colors["error"],
                    context_name=active_ctx.name
                )
        self.client.ui_needs_update.set()


    def _handle_status_command(self, args_str: str):
        """Handle the /status command"""
        self.client.context_manager.set_active_context("Status")

    def _handle_notice_command(self, args_str: str):
        """Handle the /notice command"""
        parts = self._ensure_args(args_str, self.COMMAND_USAGE_STRINGS["notice"], num_expected_parts=2)
        if not parts:
            return
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
        system_color = self.client.ui.colors.get("system", 0)
        error_color = self.client.ui.colors.get("error", 0)

        stripped_args = args_str.strip()

        if not stripped_args:
            all_settings = get_all_settings()
            if not all_settings:
                self.client.add_message("No settings found.", system_color, context_name=active_context_name)
                return

            self.client.add_message("Current settings (use /help set for usage):", system_color, context_name=active_context_name)
            for section, settings_in_section in all_settings.items():
                self.client.add_message(f"[{section}]", system_color, context_name=active_context_name)
                for key, val in settings_in_section.items():
                    self.client.add_message(f"  {key} = {val}", system_color, context_name=active_context_name)
            return

        parts = stripped_args.split(" ", 1)
        variable_arg = parts[0]

        if len(parts) == 1:
            section_name_filter: Optional[str] = None
            key_name_filter: str = variable_arg

            if "." in variable_arg:
                try:
                    section_name_filter, key_name_filter = variable_arg.split(".", 1)
                    if not section_name_filter or not key_name_filter:
                        raise ValueError("Section or key part is empty.")
                except ValueError:
                    self.client.add_message(f"Invalid format for variable: '{variable_arg}'. Use 'key' or 'section.key'.", error_color, context_name=active_context_name)
                    return

            found_settings_messages = []
            all_current_settings = get_all_settings()

            if section_name_filter:
                if section_name_filter in all_current_settings and key_name_filter in all_current_settings[section_name_filter]:
                    value = all_current_settings[section_name_filter][key_name_filter]
                    found_settings_messages.append(f"{section_name_filter}.{key_name_filter} = {value}")
                else:
                    self.client.add_message(f"Setting '{variable_arg}' not found.", error_color, context_name=active_context_name)
                    return
            else:
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
            value_arg = parts[1]

            if "." not in variable_arg:
                self.client.add_message("For setting a value, 'section.key' format is required.", error_color, context_name=active_context_name)
                usage_lines_set = self.COMMAND_USAGE_STRINGS["set"].splitlines()
                for line_usage in usage_lines_set:
                    self.client.add_message(line_usage, error_color, context_name=active_context_name)
                return

            try:
                section_to_set, key_to_set = variable_arg.split(".", 1)
                if not section_to_set or not key_to_set:
                    raise ValueError("Section or key part is empty for setting.")
            except ValueError:
                self.client.add_message(f"Invalid format for variable: '{variable_arg}'. Use 'section.key'.", error_color, context_name=active_context_name)
                return

            if set_config_value(section_to_set, key_to_set, value_arg):
                self.client.add_message(f"Set {section_to_set}.{key_to_set} = {value_arg}", system_color, context_name=active_context_name)
                self.client.add_message("Note: Some settings may require an application restart to take full effect.", system_color, context_name=active_context_name)
            else:
                self.client.add_message(f"Failed to set {section_to_set}.{key_to_set}.", error_color, context_name=active_context_name)
            return

        usage_lines = self.COMMAND_USAGE_STRINGS["set"].splitlines()
        for line in usage_lines:
            self.client.add_message(line, error_color, context_name=active_context_name)

    def _handle_ignore_command(self, args_str: str):
        active_context_name = self.client.context_manager.active_context_name or "Status"
        parts = self._ensure_args(args_str, self.COMMAND_USAGE_STRINGS["ignore"])
        if not parts:
            return

        pattern_to_ignore = parts[0]
        if '!' not in pattern_to_ignore and '@' not in pattern_to_ignore:
            if '*' not in pattern_to_ignore and '?' not in pattern_to_ignore:
                pattern_to_ignore = f"{pattern_to_ignore}!*@*"
                self.client.add_message(
                    f"Interpreting '{parts[0]}' as hostmask pattern: '{pattern_to_ignore}'",
                    self.client.ui.colors["system"],
                    context_name=active_context_name
                )

        if add_ignore_pattern(pattern_to_ignore):
            self.client.add_message(
                f"Now ignoring: {pattern_to_ignore}",
                self.client.ui.colors["system"],
                context_name=active_context_name
            )
        else:
            self.client.add_message(
                f"Pattern '{pattern_to_ignore}' is already in the ignore list or is empty.",
                self.client.ui.colors["warning"],
                context_name=active_context_name
            )

    def _handle_unignore_command(self, args_str: str):
        active_context_name = self.client.context_manager.active_context_name or "Status"
        parts = self._ensure_args(args_str, self.COMMAND_USAGE_STRINGS["unignore"])
        if not parts:
            return

        pattern_to_unignore = parts[0]
        original_pattern_arg = pattern_to_unignore
        attempted_patterns = [pattern_to_unignore.lower()]

        if '!' not in pattern_to_unignore and '@' not in pattern_to_unignore:
             if '*' not in pattern_to_unignore and '?' not in pattern_to_unignore:
                attempted_patterns.append(f"{pattern_to_unignore.lower()}!*@*")

        removed = False
        for p_attempt in attempted_patterns:
            if remove_ignore_pattern(p_attempt):
                self.client.add_message(
                    f"Removed from ignore list: {p_attempt}",
                    self.client.ui.colors["system"],
                    context_name=active_context_name
                )
                removed = True
                break

        if not removed:
            self.client.add_message(
                f"Pattern '{original_pattern_arg}' (or its derived hostmask) not found in ignore list.",
                self.client.ui.colors["error"],
                context_name=active_context_name
            )

    def _handle_listignores_command(self, args_str: str):
        active_context_name = self.client.context_manager.active_context_name or "Status"
        if not IGNORED_PATTERNS:
            self.client.add_message(
                "Ignore list is empty.",
                self.client.ui.colors["system"],
                context_name=active_context_name
            )
            return

        self.client.add_message(
            "Current ignore patterns:",
            self.client.ui.colors["system"],
            context_name=active_context_name
        )
        for pattern in sorted(list(IGNORED_PATTERNS)):
            self.client.add_message(
                f"- {pattern}",
                self.client.ui.colors["system"],
                context_name=active_context_name
            )
