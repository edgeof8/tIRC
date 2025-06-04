import logging
import os # Added for dynamic loading
import importlib # Added for dynamic loading
from typing import TYPE_CHECKING, List, Optional, Tuple
from features.triggers.trigger_commands import TriggerCommands
from context_manager import ChannelJoinStatus, Context
from channel_commands_handler import ChannelCommandsHandler
from server_commands_handler import ServerCommandsHandler
from information_commands_handler import InformationCommandsHandler
# Removed: from commands.utility import set_command as set_command_module
# Removed: from commands.utility.rehash_command import handle_rehash_command
# Removed: from commands.utility.save_command import handle_save_command
# Removed: from commands.utility.clear_command import handle_clear_command
# Removed: from commands.utility.rawlog_command import handle_rawlog_command
# Removed: from commands.utility.lastlog_command import handle_lastlog_command
# Removed: from commands.ui.window_navigation_commands import handle_next_window_command, handle_prev_window_command, handle_window_command
# Removed: from commands.ui.status_command import handle_status_command
# Removed: from commands.ui.close_command import handle_close_command
# Removed: from commands.ui.userlist_scroll_command import handle_userlist_scroll_command
# Removed: from commands.ui.split_screen_commands import handle_split_command, handle_focus_command, handle_setpane_command
# Removed: from commands.user.nick_command import handle_nick_command
# Removed: from commands.user.away_command import handle_away_command
# Removed: from commands.user.me_command import handle_me_command
# Removed: from commands.user.msg_command import handle_msg_command
# Removed: from commands.user.query_command import handle_query_command
# Removed: from commands.user.notice_command import handle_notice_command
# Removed: from commands.user.whois_command import handle_whois_command
# Removed: from commands.user.ignore_commands import handle_ignore_command, handle_unignore_command, handle_listignores_command
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

        self.registered_command_help = {} # New dictionary to store help info

        self.command_map = {
            # Commands handled by dedicated handler class instances
            "join": self.channel_commands.handle_join_command,
            "j": self.channel_commands.handle_join_command,
            "part": self.channel_commands.handle_part_command,
            "p": self.channel_commands.handle_part_command,
            "invite": self.channel_commands.handle_invite_command,
            "i": self.channel_commands.handle_invite_command,
            "topic": self.channel_commands.handle_topic_command,
            "t": self.channel_commands.handle_topic_command,
            "quit": self.server_commands.handle_quit_command,
            "q": self.server_commands.handle_quit_command,
            "raw": self.server_commands.handle_raw_command,
            "quote": self.server_commands.handle_raw_command,
            "r": self.server_commands.handle_raw_command,
            "connect": self.server_commands.handle_connect_command,
            "server": self.server_commands.handle_server_command,
            "s": self.server_commands.handle_server_command,
            "disconnect": self.server_commands.handle_disconnect_command,
            "d": self.server_commands.handle_disconnect_command,
            "cyclechannel": self.channel_commands.handle_cycle_channel_command,
            "cc": self.channel_commands.handle_cycle_channel_command,
            "kick": self.channel_commands.handle_kick_command,
            "k": self.channel_commands.handle_kick_command,
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
            "reconnect": self.server_commands.handle_reconnect_command,
            "on": self.trigger_commands.handle_on_command, # TriggerCommands is still a handler

            # Commands still potentially handled directly by CommandHandler
            # "help": self._handle_help_command, # Removed, will be dynamically loaded
            # "h": self._handle_help_command,   # Removed, will be dynamically loaded
            # Removed "prevchannel" and "pc" as they are likely in a command module now
            # If _handle_prev_channel_command still exists and is used, it should be added back or moved.
            # For now, assuming it will be dynamically loaded if defined in a module.
        }

        # --- Dynamic command loading from 'commands/' directory ---
        commands_dir_path = os.path.join(self.client.script_manager.base_dir, "commands")
        logger.info(f"Starting dynamic command loading from: {commands_dir_path}")

        for root, _, files in os.walk(commands_dir_path):
            for filename in files:
                if filename.endswith(".py") and filename != "__init__.py":
                    module_path_on_disk = os.path.join(root, filename)
                    # Construct Python module name (e.g., commands.utility.set_command)
                    relative_path_from_commands_dir = os.path.relpath(module_path_on_disk, commands_dir_path)

                    module_name_parts = relative_path_from_commands_dir[:-3].split(os.sep)
                    python_module_name = "commands." + ".".join(module_name_parts)

                    try:
                        logger.debug(f"Attempting to import module: {python_module_name}")
                        module = importlib.import_module(python_module_name)

                        if hasattr(module, 'COMMAND_DEFINITIONS'):
                            logger.info(f"Found COMMAND_DEFINITIONS in {python_module_name}")
                            for cmd_def in module.COMMAND_DEFINITIONS:
                                cmd_name = cmd_def["name"].lower()
                                handler_name_str = cmd_def["handler"]
                                handler_func = getattr(module, handler_name_str, None)

                                if handler_func and callable(handler_func):
                                    if cmd_name in self.command_map:
                                        logger.warning(f"Command '{cmd_name}' from {python_module_name} conflicts with existing command. Overwriting.")
                                    self.command_map[cmd_name] = handler_func

                                    if "help" in cmd_def and cmd_def["help"]:
                                        help_info = cmd_def["help"]
                                        self.registered_command_help[cmd_name] = {
                                            "help_text": f"{help_info['usage']}\n  {help_info['description']}",
                                            "aliases": [a.lower() for a in help_info.get("aliases", [])],
                                            "script_name": "core",
                                            "is_alias": False,
                                            "module_path": python_module_name
                                        }
                                        for alias_raw in help_info.get("aliases", []):
                                            alias = alias_raw.lower()
                                            if alias in self.command_map:
                                                 logger.warning(f"Alias '{alias}' for command '{cmd_name}' from {python_module_name} conflicts with existing command. Overwriting.")
                                            self.command_map[alias] = handler_func
                                            self.registered_command_help[alias] = {
                                                "help_text": f"{help_info['usage']}\n  {help_info['description']}",
                                                "aliases": [cmd_name] + [a.lower() for a in help_info.get("aliases", []) if a.lower() != alias],
                                                "script_name": "core",
                                                "is_alias": True,
                                                "primary_command": cmd_name,
                                                "module_path": python_module_name
                                            }
                                    logger.info(f"Registered command '{cmd_name}' (and aliases) from {python_module_name} handled by {handler_name_str}.")
                                else:
                                    logger.error(f"Could not find or call handler '{handler_name_str}' in {python_module_name} for command '{cmd_name}'.")
                        # else:
                            # logger.debug(f"Module {python_module_name} does not have COMMAND_DEFINITIONS.")

                    except ImportError as e:
                        logger.error(f"Failed to import module {python_module_name}: {e}", exc_info=True)
                    except Exception as e:
                        logger.error(f"Error processing module {python_module_name}: {e}", exc_info=True)
        logger.info("Finished dynamic command loading.")
        # --- End of dynamic command loading ---

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

    # _handle_help_command method removed. Its logic is now in commands/core/help_command.py

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
            self.client.network_handler.send_raw(f"PRIVMSG {target_nick} :{message}")

    def _handle_prev_channel_command(self, args_str: str):
        """Handle the /prevchannel command"""
        self.client.switch_active_channel("prev")

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
        for cmd_name, cmd_data in script_cmds_data.items():
            script_cmds_and_aliases.append("/" + cmd_name)
            for alias in cmd_data.get("aliases", []):
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
            handler_func = self.command_map[cmd]
            import inspect # Moved import here as it's only used in this block
            # Check if the handler is a standalone function from 'commands.' module
            if hasattr(handler_func, '__module__') and \
               handler_func.__module__.startswith("commands.") and \
               not inspect.ismethod(handler_func): # Ensure it's not a method incorrectly caught
                handler_func(self.client, args_str)  # Pass client for new modular commands
            else:
                handler_func(args_str)  # Existing call for methods of handler classes
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

