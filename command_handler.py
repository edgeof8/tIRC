import logging
from typing import TYPE_CHECKING, List, Optional, Tuple
from features.triggers.trigger_commands import TriggerCommands
from context_manager import ChannelJoinStatus, Context
from channel_commands_handler import ChannelCommandsHandler
from server_commands_handler import ServerCommandsHandler
from information_commands_handler import InformationCommandsHandler
from config import (
    get_all_settings,
    set_config_value,
    get_config_value,
    config as global_config_parser,
    add_ignore_pattern,
    remove_ignore_pattern,
    IGNORED_PATTERNS,
    save_current_config,
)

if TYPE_CHECKING:
    from irc_client_logic import (
        IRCClient_Logic,
    )

from context_manager import Context as CTX_Type

logger = logging.getLogger("pyrc.command_handler")


class CommandHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic
        self.trigger_commands = TriggerCommands(client_logic)
        self.channel_commands = ChannelCommandsHandler(client_logic)
        self.server_commands = ServerCommandsHandler(client_logic)
        self.info_commands = InformationCommandsHandler(client_logic)

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
            "help": self._handle_help_command,
            "h": self._handle_help_command,
            "ignore": self._handle_ignore_command,
            "unignore": self._handle_unignore_command,
            "listignores": self._handle_listignores_command,
            "ban": self.channel_commands.handle_ban_command,
            "unban": self.channel_commands.handle_unban_command,
            "mode": self.channel_commands.handle_mode_command,
            "op": self.channel_commands.handle_op_command,
            "o": self.channel_commands.handle_op_command,
            "deop": self.channel_commands.handle_deop_command,
            "do": self.channel_commands.handle_deop_command,
            "voice": self.channel_commands.handle_voice_command,
            "v": self.channel_commands.handle_voice_command,
            "devoice": self.channel_commands.handle_devoice_command,
            "dv": self.channel_commands.handle_devoice_command,
            "who": self.info_commands.handle_who_command,
            "whowas": self.info_commands.handle_whowas_command,
            "list": self.info_commands.handle_list_command,
            "names": self.info_commands.handle_names_command,
            # New commands
            "reconnect": self.server_commands.handle_reconnect_command,
            "rehash": self._handle_rehash_command,
            "rawlog": self._handle_rawlog_command,
            "save": self._handle_save_command,
            "lastlog": self._handle_lastlog_command,
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
        """Handle the /help command"""
        system_color = self.client.ui.colors["system"]
        error_color = self.client.ui.colors["error"]
        active_context_name = self.client.context_manager.active_context_name

        if not args_str:
            # Show general help
            self.client.add_message(
                "\nAvailable commands:",
                system_color,
                context_name=active_context_name,
            )

            # Get all help texts
            help_texts = self.client.script_manager.get_all_help_texts()

            # Group commands by script
            commands_by_script = {}
            for cmd, help_text in help_texts.items():
                # For core commands, help_text is a string
                # For script commands, help_text is a dict with 'help_text' and 'script_name'
                if isinstance(help_text, dict):
                    script_name = help_text.get("script_name", "core")
                    help_text_str = help_text.get("help_text", "")
                else:
                    script_name = "core"
                    help_text_str = help_text

                if script_name not in commands_by_script:
                    commands_by_script[script_name] = []
                commands_by_script[script_name].append((cmd, help_text_str))

            # Display commands grouped by script
            for script_name, commands in sorted(commands_by_script.items()):
                if script_name != "core":
                    self.client.add_message(
                        f"\nCommands from script '{script_name}':",
                        system_color,
                        context_name=active_context_name,
                    )
                else:
                    self.client.add_message(
                        "\nCore commands:",
                        system_color,
                        context_name=active_context_name,
                    )

                for cmd, help_text in sorted(commands):
                    summary = help_text.split("\n")[0]
                    self.client.add_message(
                        f"/{cmd}: {summary}",
                        system_color,
                        context_name=active_context_name,
                    )

            self.client.add_message(
                "\nUse /help <command> for detailed help on a specific command.",
                system_color,
                context_name=active_context_name,
            )
            return

        # Show help for specific command
        command_name_from_user = args_str.strip().lower()
        help_data = self.client.script_manager.get_help_text_for_command(
            command_name_from_user
        )

        if help_data:
            # Check if this is an alias
            if help_data.get("is_alias"):
                primary_cmd = help_data.get("primary_command")
                self.client.add_message(
                    f"(Showing help for '/{primary_cmd}', as '/{command_name_from_user}' is an alias)",
                    system_color,
                    context_name=active_context_name,
                )

            # Show the help text
            help_text = help_data.get("help_text", "")
            for line in help_text.splitlines():
                self.client.add_message(
                    line, system_color, context_name=active_context_name
                )

            # Show script name if it's from a script
            if help_data.get("script_name") and help_data["script_name"] != "core":
                self.client.add_message(
                    f"(Help from script: {help_data['script_name']})",
                    system_color,
                    context_name=active_context_name,
                )
        else:
            self.client.add_message(
                f"No help available for command: {command_name_from_user}",
                error_color,
                context_name=active_context_name,
            )

    def _handle_msg_command(self, args_str: str):
        """Handle the /msg command"""
        help_data = self.client.script_manager.get_help_text_for_command("msg")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /msg <nick> <message>"
        )
        parts = self._ensure_args(args_str, usage_msg, num_expected_parts=2)
        if not parts:
            return
        target = parts[0]
        message = parts[1]
        self.client.network.send_raw(f"PRIVMSG {target} :{message}")

    def _handle_query_command(self, args_str: str):
        """Handle the /query command"""
        help_data = self.client.script_manager.get_help_text_for_command("query")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /query <nick> [message]"
        )
        parts = self._ensure_args(args_str, usage_msg, num_expected_parts=1)
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
        help_data = self.client.script_manager.get_help_text_for_command("nick")
        usage_msg = help_data["help_text"] if help_data else "Usage: /nick <newnick>"
        parts = self._ensure_args(args_str, usage_msg)
        if not parts:
            return
        new_nick = parts[0]
        self.client.network.send_raw(f"NICK {new_nick}")

    def _handle_whois_command(self, args_str: str):
        """Handle the /whois command"""
        help_data = self.client.script_manager.get_help_text_for_command("whois")
        usage_msg = help_data["help_text"] if help_data else "Usage: /whois <nick>"
        parts = self._ensure_args(args_str, usage_msg)
        if not parts:
            return
        target = parts[0]
        self.client.network.send_raw(f"WHOIS {target}")

    def _handle_me_command(self, args_str: str):
        """Handle the /me command"""
        help_data = self.client.script_manager.get_help_text_for_command("me")
        usage_msg = help_data["help_text"] if help_data else "Usage: /me <action>"
        if not self._ensure_args(args_str, usage_msg):
            return
        action_text = args_str
        current_context_obj = self.client.context_manager.get_active_context()
        if not current_context_obj:
            self.client.add_message(
                "Cannot /me: No active context.",
                self.client.ui.colors["error"],
                context_name="Status",
            )
            return

        if current_context_obj.type == "channel":
            if (
                hasattr(current_context_obj, "join_status")
                and current_context_obj.join_status == ChannelJoinStatus.FULLY_JOINED
            ):
                self.client.network.send_raw(
                    f"PRIVMSG {current_context_obj.name} :\x01ACTION {action_text}\x01"
                )
            else:
                self.client.add_message(
                    f"Cannot /me: Channel {current_context_obj.name} not fully joined.",
                    self.client.ui.colors["error"],
                    context_name=current_context_obj.name,
                )
        elif current_context_obj.type == "query":
            self.client.network.send_raw(
                f"PRIVMSG {current_context_obj.name} :\x01ACTION {action_text}\x01"
            )
        else:
            self.client.add_message(
                "Cannot /me in this window.",
                self.client.ui.colors["error"],
                context_name=current_context_obj.name,
            )

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
        help_data = self.client.script_manager.get_help_text_for_command("window")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /window <name|number>"
        )
        parts = self._ensure_args(args_str, usage_msg)
        if not parts:
            return
        target = parts[0]
        self.client.context_manager.set_active_context(target)

    def _close_channel_context(self, channel_context: "CTX_Type"):
        """Helper to handle closing (parting) a channel context."""
        if hasattr(channel_context, "join_status"):
            channel_context.join_status = ChannelJoinStatus.PARTING

        # Try to get a random part message from scripts
        variables = {"nick": self.client.nick, "channel": channel_context.name}
        part_message = self.client.script_manager.get_random_part_message_from_scripts(
            variables
        )
        if not part_message:
            part_message = "Leaving"  # Fallback if no script provides a message

        self.client.network.send_raw(f"PART {channel_context.name} :{part_message}")
        self.client.add_message(
            f"Parting {channel_context.name}...",
            self.client.ui.colors["system"],
            context_name=channel_context.name,
        )

    def _close_query_or_generic_context(self, context_obj: "CTX_Type"):
        """Helper to handle closing a query or generic context."""
        context_name_to_close = context_obj.name
        self.client.context_manager.remove_context(context_name_to_close)
        self.client.add_message(
            f"Closed window: {context_name_to_close}",
            self.client.ui.colors["system"],
            context_name="Status",
        )

    def _handle_close_command(self, args_str: str):
        """Handle the /close, /wc, /partchannel command."""
        active_ctx_name = self.client.context_manager.active_context_name
        if not active_ctx_name:
            self.client.add_message(
                "No active window to close.",
                self.client.ui.colors["error"],
                context_name="Status",
            )
            return

        current_context = self.client.context_manager.get_context(active_ctx_name)
        if not current_context:
            logger.error(
                f"/close: Active context '{active_ctx_name}' not found in manager."
            )
            return

        if current_context.type == "channel":
            self._close_channel_context(current_context)
        elif (
            current_context.type == "query"
            or current_context.type == "generic"
            or current_context.type == "list_results"
        ):
            self._close_query_or_generic_context(current_context)
        elif current_context.type == "status":
            self.client.add_message(
                "Cannot close the Status window.",
                self.client.ui.colors["error"],
                context_name="Status",
            )

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
                context_name=self.client.context_manager.active_context_name
                or "Status",
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
                    context_name=active_ctx.name,
                )
        self.client.ui_needs_update.set()

    def _handle_status_command(self, args_str: str):
        """Handle the /status command"""
        self.client.context_manager.set_active_context("Status")

    def _handle_notice_command(self, args_str: str):
        """Handle the /notice command"""
        help_data = self.client.script_manager.get_help_text_for_command("notice")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /notice <target> <message>"
        )
        parts = self._ensure_args(args_str, usage_msg, num_expected_parts=2)
        if not parts:
            return
        target = parts[0]
        message = parts[1]
        self.client.network.send_raw(f"NOTICE {target} :{message}")

    def _handle_set_command(self, args_str: str):
        """Handle the /set command"""
        help_data = self.client.script_manager.get_help_text_for_command("set")
        usage_msg = (
            help_data["help_text"]
            if help_data
            else "Usage: /set [<section.key> [<value>]]"
        )
        active_context_name = (
            self.client.context_manager.active_context_name or "Status"
        )
        system_color = self.client.ui.colors.get("system", 0)
        error_color = self.client.ui.colors.get("error", 0)

        stripped_args = args_str.strip()

        if not stripped_args:
            all_settings = get_all_settings()
            if not all_settings:
                self.client.add_message(
                    "No settings found.", system_color, context_name=active_context_name
                )
                return

            self.client.add_message(
                "Current settings (use /help set for usage):",
                system_color,
                context_name=active_context_name,
            )
            for section, settings_in_section in all_settings.items():
                self.client.add_message(
                    f"[{section}]", system_color, context_name=active_context_name
                )
                for key, val in settings_in_section.items():
                    self.client.add_message(
                        f"  {key} = {val}",
                        system_color,
                        context_name=active_context_name,
                    )
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
                    self.client.add_message(
                        f"Invalid format for variable: '{variable_arg}'. Use 'key' or 'section.key'.",
                        error_color,
                        context_name=active_context_name,
                    )
                    return

            found_settings_messages = []
            all_current_settings = get_all_settings()

            if section_name_filter:
                if (
                    section_name_filter in all_current_settings
                    and key_name_filter in all_current_settings[section_name_filter]
                ):
                    value = all_current_settings[section_name_filter][key_name_filter]
                    found_settings_messages.append(
                        f"{section_name_filter}.{key_name_filter} = {value}"
                    )
                else:
                    self.client.add_message(
                        f"Setting '{variable_arg}' not found.",
                        error_color,
                        context_name=active_context_name,
                    )
                    return
            else:
                for sec, settings_in_sec in all_current_settings.items():
                    if key_name_filter in settings_in_sec:
                        found_settings_messages.append(
                            f"{sec}.{key_name_filter} = {settings_in_sec[key_name_filter]}"
                        )

            if not found_settings_messages:
                self.client.add_message(
                    f"Setting '{key_name_filter}' not found in any section.",
                    error_color,
                    context_name=active_context_name,
                )
            else:
                for setting_str in found_settings_messages:
                    self.client.add_message(
                        setting_str, system_color, context_name=active_context_name
                    )
            return

        elif len(parts) == 2:
            value_arg = parts[1]

            if "." not in variable_arg:
                self.client.add_message(
                    "For setting a value, 'section.key' format is required.",
                    error_color,
                    context_name=active_context_name,
                )
                self.client.add_message(
                    usage_msg, error_color, context_name=active_context_name
                )
                return

            try:
                section_to_set, key_to_set = variable_arg.split(".", 1)
                if not section_to_set or not key_to_set:
                    raise ValueError("Section or key part is empty for setting.")
            except ValueError:
                self.client.add_message(
                    f"Invalid format for variable: '{variable_arg}'. Use 'section.key'.",
                    error_color,
                    context_name=active_context_name,
                )
                return

            if set_config_value(section_to_set, key_to_set, value_arg):
                self.client.add_message(
                    f"Set {section_to_set}.{key_to_set} = {value_arg}",
                    system_color,
                    context_name=active_context_name,
                )
                self.client.add_message(
                    "Note: Some settings may require an application restart to take full effect.",
                    system_color,
                    context_name=active_context_name,
                )
            else:
                self.client.add_message(
                    f"Failed to set {section_to_set}.{key_to_set}.",
                    error_color,
                    context_name=active_context_name,
                )
            return

        self.client.add_message(
            usage_msg, error_color, context_name=active_context_name
        )

    def _handle_ignore_command(self, args_str: str):
        help_data = self.client.script_manager.get_help_text_for_command("ignore")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /ignore <nick|hostmask>"
        )
        active_context_name = (
            self.client.context_manager.active_context_name or "Status"
        )
        parts = self._ensure_args(args_str, usage_msg)
        if not parts:
            return

        pattern_to_ignore = parts[0]
        if "!" not in pattern_to_ignore and "@" not in pattern_to_ignore:
            if "*" not in pattern_to_ignore and "?" not in pattern_to_ignore:
                pattern_to_ignore = f"{pattern_to_ignore}!*@*"
                self.client.add_message(
                    f"Interpreting '{parts[0]}' as hostmask pattern: '{pattern_to_ignore}'",
                    self.client.ui.colors["system"],
                    context_name=active_context_name,
                )

        if add_ignore_pattern(pattern_to_ignore):
            self.client.add_message(
                f"Now ignoring: {pattern_to_ignore}",
                self.client.ui.colors["system"],
                context_name=active_context_name,
            )
        else:
            self.client.add_message(
                f"Pattern '{pattern_to_ignore}' is already in the ignore list or is empty.",
                self.client.ui.colors["warning"],
                context_name=active_context_name,
            )

    def _handle_unignore_command(self, args_str: str):
        help_data = self.client.script_manager.get_help_text_for_command("unignore")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /unignore <nick|hostmask>"
        )
        active_context_name = (
            self.client.context_manager.active_context_name or "Status"
        )
        parts = self._ensure_args(args_str, usage_msg)
        if not parts:
            return

        pattern_to_unignore = parts[0]
        original_pattern_arg = pattern_to_unignore
        attempted_patterns = [pattern_to_unignore.lower()]

        if "!" not in pattern_to_unignore and "@" not in pattern_to_unignore:
            if "*" not in pattern_to_unignore and "?" not in pattern_to_unignore:
                attempted_patterns.append(f"{pattern_to_unignore.lower()}!*@*")

        removed = False
        for p_attempt in attempted_patterns:
            if remove_ignore_pattern(p_attempt):
                self.client.add_message(
                    f"Removed from ignore list: {p_attempt}",
                    self.client.ui.colors["system"],
                    context_name=active_context_name,
                )
                removed = True
                break

        if not removed:
            self.client.add_message(
                f"Pattern '{original_pattern_arg}' (or its derived hostmask) not found in ignore list.",
                self.client.ui.colors["error"],
                context_name=active_context_name,
            )

    def _handle_listignores_command(self, args_str: str):
        active_context_name = (
            self.client.context_manager.active_context_name or "Status"
        )
        if not IGNORED_PATTERNS:
            self.client.add_message(
                "Ignore list is empty.",
                self.client.ui.colors["system"],
                context_name=active_context_name,
            )
            return

        self.client.add_message(
            "Current ignore patterns:",
            self.client.ui.colors["system"],
            context_name=active_context_name,
        )
        for pattern in sorted(list(IGNORED_PATTERNS)):
            self.client.add_message(
                f"- {pattern}",
                self.client.ui.colors["system"],
                context_name=active_context_name,
            )

    def _handle_rehash_command(self, args_str: str):
        """Handles the /rehash command."""
        if hasattr(self.client, "handle_rehash_config"):
            self.client.handle_rehash_config()
            # Feedback message is handled within IRCClient_Logic.handle_rehash_config
        else:
            logger.error("IRCClient_Logic does not have handle_rehash_config method.")
            self.client.add_message(
                "Error: Rehash functionality not fully implemented in client logic.",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )

    def _handle_rawlog_command(self, args_str: str):
        """Handles the /rawlog [on|off|toggle] command."""
        help_data = self.client.script_manager.get_help_text_for_command("rawlog")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /rawlog [on|off|toggle]"
        )
        arg = args_str.strip().lower()
        current_status = self.client.show_raw_log_in_ui

        if arg == "on":
            self.client.show_raw_log_in_ui = True
        elif arg == "off":
            self.client.show_raw_log_in_ui = False
        elif arg == "toggle" or not arg:  # Empty arg also toggles
            self.client.show_raw_log_in_ui = not current_status
        else:
            self.client.add_message(
                usage_msg,
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )

    def _handle_lastlog_command(self, args_str: str):
        """Handles the /lastlog command."""
        help_data = self.client.script_manager.get_help_text_for_command("lastlog")
        usage_msg = help_data["help_text"] if help_data else "Usage: /lastlog <pattern>"
        active_context_obj = self.client.context_manager.get_active_context()
        active_context_name = (
            self.client.context_manager.active_context_name or "Status"
        )
        system_color = self.client.ui.colors.get("system", 0)
        error_color = self.client.ui.colors.get("error", 0)

        if not args_str.strip():
            self.client.add_message(
                usage_msg,
                error_color,
                context_name=active_context_name,
            )
            return

        pattern = args_str.strip()

        if not active_context_obj:
            self.client.add_message(
                "Cannot use /lastlog: No active window.",
                error_color,
                context_name="Status",
            )
            return

        self.client.add_message(
            f'Searching lastlog for "{pattern}" in {active_context_obj.name}...',
            system_color,
            context_name=active_context_name,
        )

        found_matches = False
        # Iterate a copy in case messages are added during iteration
        messages_to_search = list(active_context_obj.messages)

        for msg_text, color_attr in messages_to_search:
            if pattern.lower() in msg_text.lower():
                self.client.add_message(
                    f"[LastLog] {msg_text}",
                    color_attr,
                    context_name=active_context_name,
                )
                found_matches = True

        if not found_matches:
            self.client.add_message(
                f'No matches found for "{pattern}" in the current log.',
                system_color,
                context_name=active_context_name,
            )
        self.client.add_message(
            "End of lastlog search.", system_color, context_name=active_context_name
        )

        feedback_action = "enabled" if self.client.show_raw_log_in_ui else "disabled"
        self.client.add_message(
            f"Raw IRC message logging to UI {feedback_action}.",
            self.client.ui.colors["system"],
            context_name=self.client.context_manager.active_context_name or "Status",
        )

    def _handle_save_command(self, args_str: str):
        """Handles the /save command."""
        if save_current_config():
            self.client.add_message(
                "Configuration saved to pyterm_irc_config.ini.",
                self.client.ui.colors["system"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
        else:
            self.client.add_message(
                "Failed to save configuration.",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )

    def get_available_commands_for_tab_complete(self) -> List[str]:
        """
        Returns a list of commands primarily for tab-completion,
        dynamically generated from the command_map.
        """
        core_cmds = ["/" + cmd for cmd in self.command_map.keys()]
        script_cmds_data = (
            self.client.script_manager.get_all_script_commands_with_help()
        )

        script_cmds_and_aliases = []
        for scmd_data in script_cmds_data:
            script_cmds_and_aliases.append("/" + scmd_data["name"])
            for alias in scmd_data.get("aliases", []):
                script_cmds_and_aliases.append("/" + alias)

        return sorted(list(set(core_cmds + script_cmds_and_aliases)))

    def _ensure_args(
        self, args_str: str, usage_message: str, num_expected_parts: int = 1
    ) -> Optional[List[str]]:
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
                context_name=self.client.context_manager.active_context_name
                or "Status",
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
                context_name=self.client.context_manager.active_context_name
                or "Status",
            )
            return None

        return parts

    def process_user_command(self, line: str) -> bool:
        """Process a user command (starts with /) or a channel message"""
        if not line.startswith("/"):
            # ... (existing message handling)
            if self.client.context_manager.active_context_name:
                self.client.handle_text_input(line)
                return True
            else:
                self.client.add_message(
                    "No active window to send message to.",
                    self.client.ui.colors["error"],
                    context_name="Status",
                )
                return False

        command_parts = line[1:].split(" ", 1)
        cmd = command_parts[0].lower()
        args_str = command_parts[1] if len(command_parts) > 1 else ""

        if cmd in self.command_map:
            self.command_map[cmd](args_str)
            return True
        else:
            # Check for script-registered commands
            script_cmd_data = (
                self.client.script_manager.get_script_command_handler_and_data(cmd)
            )
            if script_cmd_data and callable(script_cmd_data.get("handler")):
                script_handler = script_cmd_data["handler"]
                # Prepare basic event_data for script command handlers
                event_data_for_script = {
                    "client_logic_ref": self.client,  # Allows script to access client logic via API if needed
                    "raw_line": line,
                    "command": cmd,
                    "args_str": args_str,
                    "client_nick": self.client.nick,
                    "active_context_name": self.client.context_manager.active_context_name,
                    "script_name": script_cmd_data.get("script_name", "UnknownScript"),
                }
                try:
                    script_handler(args_str, event_data_for_script)
                except Exception as e:
                    logger.error(
                        f"Error executing script command '/{cmd}' from script '{script_cmd_data.get('script_name')}': {e}",
                        exc_info=True,
                    )
                    self.client.add_message(
                        f"Error in script command /{cmd}: {e}",
                        self.client.ui.colors["error"],
                        context_name=self.client.context_manager.active_context_name
                        or "Status",
                    )
                return True
            else:
                self.client.add_message(
                    f"Unknown command: {cmd}",
                    self.client.ui.colors["error"],
                    context_name=self.client.context_manager.active_context_name
                    or "Status",
                )
                return True  # Command was processed (as unknown)
