import os
import importlib.util
import logging
import configparser
import time
import sys
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Any, Set
import threading
from config import DISABLED_SCRIPTS

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

    # Renaming to avoid clash if ScriptManager is defined later in this file.
    # However, since ScriptManager uses ScriptAPIHandler, it's better if ScriptAPIHandler is defined first
    # or properly forward declared if ScriptManager needs to be defined first.
    # For this structure, ScriptAPIHandler defined first is fine.
    # class ScriptManagerFwdRef: pass # Not strictly needed with current order

logger = logging.getLogger("pyrc.script_manager")

SCRIPTS_DIR_NAME = "scripts"
HELP_INI_FILENAME = "command_help.ini"
HELP_INI_PATH = os.path.join("data", "default_help", HELP_INI_FILENAME)
# SCRIPTS_DATA_SUBDIR_NAME = "data" # Added for clarity, will be used in get_data_file_path


class ScriptAPIHandler:
    def __init__(
        self,
        client_logic_ref: "IRCClient_Logic",
        script_manager_ref: "ScriptManager",
        script_module_name: str,
    ):
        self.client_logic = client_logic_ref
        self.script_manager = script_manager_ref
        self.script_module_name = script_module_name
        self.script_instance = None
        self.registered_commands = {}
        self.registered_events = set()
        self.help_texts = {}
        self.quit_messages = []
        # Temporarily comment out trigger-related code for debugging
        # self.registered_triggers = {}
        # self.trigger_conditions = {}
        # self.trigger_actions = {}
        # self.trigger_cooldowns = {}
        # self.last_trigger_time = {}
        # self.trigger_enabled = {}
        # self.trigger_counters = {}
        # self.trigger_thresholds = {}
        # self.trigger_reset_times = {}
        # self.trigger_reset_timers = {}
        # self.trigger_reset_threads = {}
        # self.trigger_reset_events = {}
        # self.trigger_reset_lock = threading.Lock()
        # self.trigger_reset_condition = threading.Condition(self.trigger_reset_lock)
        # self.trigger_reset_running = True
        # self.trigger_reset_thread = threading.Thread(
        #     target=self._trigger_reset_loop, daemon=True
        # )
        # self.trigger_reset_thread.start()

    def send_raw(self, command_string: str):
        self.client_logic.network_handler.send_raw(command_string)

    # Added send_action based on plan
    def send_action(self, target: str, action_text: str):
        if not target or not action_text:
            self.log_warning(
                f"send_action called with empty target ('{target}') or action_text ('{action_text}')."
            )
            return
        self.client_logic.network_handler.send_raw(
            f"PRIVMSG {target} :\x01ACTION {action_text}\x01"
        )

    def add_message_to_context(
        self,
        context_name: str,
        text: str,
        color_key: str = "system",
        prefix_time: bool = True,
    ):
        color_attr = self.client_logic.ui.colors.get(
            color_key, self.client_logic.ui.colors["system"]
        )
        self.client_logic.add_message(
            text, color_attr, prefix_time=prefix_time, context_name=context_name
        )

    def get_client_nick(self) -> str:
        return self.client_logic.nick

    def get_current_context_name(self) -> Optional[str]:
        return self.client_logic.context_manager.active_context_name

    def get_active_context_type(self) -> Optional[str]:
        active_ctx = self.client_logic.context_manager.get_active_context()
        return active_ctx.type if active_ctx else None

    # --- Registration Methods (call back to ScriptManager) ---
    def register_command(
        self,
        command_name: str,
        handler_function: Callable,
        help_text: str = "",
        aliases: Optional[List[str]] = None,
    ):
        if aliases is None:
            aliases = []
        # Pass self.script_module_name to ScriptManager
        self.script_manager.register_command_from_script(
            command_name,
            handler_function,
            help_text,
            aliases,
            script_name=self.script_module_name,
        )

    # --- Logging methods now use self.script_module_name ---
    def log_info(self, message: str):  # Removed script_name param
        logger.info(f"[{self.script_module_name}] {message}")

    def log_warning(self, message: str):  # Removed script_name param
        logger.warning(f"[{self.script_module_name}] {message}")

    def log_error(self, message: str):  # Removed script_name param
        logger.error(f"[{self.script_module_name}] {message}")

    # --- New method for data file paths ---
    def request_data_file_path(self, data_filename: str) -> str:
        return self.script_manager.get_data_file_path_for_script(
            self.script_module_name, data_filename
        )

    # --- Event Subscription ---
    def subscribe_to_event(self, event_name: str, handler_function: Callable):
        self.script_manager.subscribe_script_to_event(
            event_name, handler_function, self.script_module_name
        )

    # --- Random Messages ---
    def get_random_quit_message(
        self, variables: Optional[Dict[str, str]] = None
    ) -> Optional[str]:
        if variables is None:
            variables = {}
        return self.script_manager.get_random_quit_message_from_scripts(variables)

    def get_random_part_message(
        self, variables: Optional[Dict[str, str]] = None
    ) -> Optional[str]:
        if variables is None:
            variables = {}
        return self.script_manager.get_random_part_message_from_scripts(variables)

    def register_help_text(
        self,
        command_name: str,
        usage_str: str,
        description_str: str = "",
        aliases: Optional[List[str]] = None,
    ):
        """Register help text for a command from a script.

        Args:
            command_name: The name of the command (e.g., 'testscript')
            usage_str: The usage string (e.g., 'Usage: /testscript [args]')
            description_str: Optional description of what the command does
            aliases: Optional list of command aliases
        """
        if aliases is None:
            aliases = []

        # Combine usage and description into a single help text
        help_text = usage_str
        if description_str:
            help_text += f"\n{description_str}"

        self.script_manager.register_help_text_from_script(
            command_name=command_name,
            help_text=help_text,
            aliases=aliases,
            script_name=self.script_module_name,
        )

    # --- State Querying Methods ---
    def get_channel_users(self, channel_name: str) -> Optional[Dict[str, str]]:
        """Get the user list for a channel.

        Args:
            channel_name: The name of the channel to get users from

        Returns:
            Dictionary mapping nicknames to prefixes (e.g., '@', '+', etc.) or None if channel doesn't exist
        """
        context = self.client_logic.context_manager.get_context(channel_name)
        if not context or context.type != "channel":
            return None
        return context.users if hasattr(context, "users") else None

    def get_channel_topic(self, channel_name: str) -> Optional[str]:
        """Get the topic for a channel.

        Args:
            channel_name: The name of the channel to get the topic from

        Returns:
            The channel topic or None if channel doesn't exist
        """
        context = self.client_logic.context_manager.get_context(channel_name)
        if not context or context.type != "channel":
            return None
        return context.topic if hasattr(context, "topic") else None

    def get_joined_channels(self) -> List[str]:
        """Get a list of channels the client is currently joined to.

        Returns:
            List of channel names
        """
        return list(self.client_logic.currently_joined_channels)

    def get_server_capabilities(self) -> Set[str]:
        """Get the set of currently enabled server capabilities.

        Returns:
            Set of enabled capability names
        """
        return self.client_logic.get_enabled_caps()

    def get_server_info(self) -> Dict[str, Any]:
        """Get information about the current server connection.

        Returns:
            Dictionary containing server, port, and SSL status
        """
        return {
            "server": self.client_logic.server,
            "port": self.client_logic.port,
            "ssl": self.client_logic.use_ssl,
        }

    def is_connected(self) -> bool:
        """Check if the client is currently connected to the server.

        Returns:
            True if connected, False otherwise
        """
        return self.client_logic.network_handler.connected

    def get_context_info(self, context_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific context.

        Args:
            context_name: The name of the context to get info for

        Returns:
            Dictionary containing context information or None if context doesn't exist
        """
        context = self.client_logic.context_manager.get_context(context_name)
        if not context:
            return None

        info = {
            "name": context.name,
            "type": context.type,
            "unread_count": (
                context.unread_count if hasattr(context, "unread_count") else 0
            ),
        }

        if context.type == "channel":
            info.update(
                {
                    "topic": context.topic if hasattr(context, "topic") else None,
                    "user_count": (
                        len(context.users) if hasattr(context, "users") else 0
                    ),
                    "join_status": (
                        context.join_status.name
                        if hasattr(context, "join_status")
                        and context.join_status is not None
                        else None
                    ),
                }
            )

        return info

    # --- Action Methods ---
    def join_channel(self, channel_name: str, key: Optional[str] = None):
        """Join a channel.

        Args:
            channel_name: The channel to join
            key: Optional channel key/password
        """
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name

        cmd = f"JOIN {channel_name}"
        if key:
            cmd += f" {key}"
        self.send_raw(cmd)

    def part_channel(self, channel_name: str, reason: Optional[str] = None):
        """Leave a channel.

        Args:
            channel_name: The channel to leave
            reason: Optional part message
        """
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name

        cmd = f"PART {channel_name}"
        if reason:
            cmd += f" :{reason}"
        self.send_raw(cmd)

    def send_message(self, target: str, message: str):
        """Send a message to a channel or user.

        Args:
            target: Channel or user to send to
            message: The message to send
        """
        self.send_raw(f"PRIVMSG {target} :{message}")

    def set_nick(self, new_nick: str):
        """Change your nickname.

        Args:
            new_nick: The new nickname to use
        """
        self.send_raw(f"NICK {new_nick}")

    def set_topic(self, channel_name: str, new_topic: str):
        """Set the topic for a channel.

        Args:
            channel_name: The channel to set the topic for
            new_topic: The new topic
        """
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name
        self.send_raw(f"TOPIC {channel_name} :{new_topic}")

    def set_channel_mode(self, channel_name: str, modes: str, *mode_params: str):
        """Set channel modes.

        Args:
            channel_name: The channel to set modes for
            modes: The mode string (e.g., "+o", "+v", etc.)
            mode_params: Optional parameters for the modes
        """
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name

        cmd = f"MODE {channel_name} {modes}"
        if mode_params:
            cmd += " " + " ".join(mode_params)
        self.send_raw(cmd)

    def kick_user(self, channel_name: str, nick: str, reason: Optional[str] = None):
        """Kick a user from a channel.

        Args:
            channel_name: The channel to kick from
            nick: The user to kick
            reason: Optional kick reason
        """
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name

        cmd = f"KICK {channel_name} {nick}"
        if reason:
            cmd += f" :{reason}"
        self.send_raw(cmd)

    def invite_user(self, nick: str, channel_name: str):
        """Invite a user to a channel.

        Args:
            nick: The user to invite
            channel_name: The channel to invite to
        """
        if not channel_name.startswith(("#", "&", "+", "!")):
            channel_name = "#" + channel_name
        self.send_raw(f"INVITE {nick} {channel_name}")

    # --- Trigger Management Methods ---
    def add_trigger(
        self, event_type: str, pattern: str, action_type: str, action_content: str
    ) -> Optional[int]:
        """Add a new trigger to the trigger manager.

        Args:
            event_type: The type of event to trigger on (e.g., "PRIVMSG", "JOIN")
            pattern: The pattern to match against the event data
            action_type: The type of action to take (e.g., "say", "command")
            action_content: The content of the action

        Returns:
            The ID of the newly created trigger, or None if creation failed
        """
        if not hasattr(self.client_logic, "trigger_manager"):
            self.log_error("Trigger manager not available")
            return None

        try:
            trigger_id = self.client_logic.trigger_manager.add_trigger(
                event_type_str=event_type,
                pattern=pattern,
                action_type_str=action_type,
                action_content=action_content,
            )
            return trigger_id
        except Exception as e:
            self.log_error(f"Failed to add trigger: {e}")
            return None

    def remove_trigger(self, trigger_id: int) -> bool:
        """Remove a trigger by its ID.

        Args:
            trigger_id: The ID of the trigger to remove

        Returns:
            True if the trigger was removed successfully, False otherwise
        """
        if not hasattr(self.client_logic, "trigger_manager"):
            self.log_error("Trigger manager not available")
            return False

        try:
            return self.client_logic.trigger_manager.remove_trigger(trigger_id)
        except Exception as e:
            self.log_error(f"Failed to remove trigger {trigger_id}: {e}")
            return False

    def list_triggers(self) -> list:
        """List all triggers.

        Returns:
            A list of dictionaries containing trigger information
        """
        if not hasattr(self.client_logic, "trigger_manager"):
            self.log_error("Trigger manager not available")
            return []

        try:
            return self.client_logic.trigger_manager.list_triggers()
        except Exception as e:
            self.log_error(f"Failed to list triggers: {e}")
            return []

    def set_trigger_enabled(self, trigger_id: int, enabled: bool) -> bool:
        """Enable or disable a trigger.

        Args:
            trigger_id: The ID of the trigger to modify
            enabled: Whether the trigger should be enabled

        Returns:
            True if the trigger was updated successfully, False otherwise
        """
        if not hasattr(self.client_logic, "trigger_manager"):
            self.log_error("Trigger manager not available")
            return False

        try:
            return self.client_logic.trigger_manager.set_trigger_enabled(
                trigger_id, enabled
            )
        except Exception as e:
            self.log_error(
                f"Failed to {'enable' if enabled else 'disable'} trigger {trigger_id}: {e}"
            )
            return False

    def get_nick(self) -> str:
        """Get the current nick of the client."""
        return self.client_logic.nick if self.client_logic else "Unknown"

    def _trigger_reset_loop(self):
        """Background thread to handle trigger resets."""
        pass  # Temporarily disabled for debugging


class ScriptManager:
    def __init__(self, client_logic_ref: "IRCClient_Logic", base_dir: str):
        self.client_logic_ref = client_logic_ref
        self.base_dir = base_dir
        # self.api_handler is no longer a single instance; it's created per script.

        self.scripts_dir = os.path.join(self.base_dir, SCRIPTS_DIR_NAME)
        self.loaded_script_instances: Dict[str, Any] = {}

        self.registered_commands: Dict[str, Dict[str, Any]] = {}
        self.command_aliases: Dict[str, str] = {}
        # Enhanced event subscriptions: event_name -> list of {'handler': callable, 'script_name': str, 'enabled': bool}
        self.event_subscriptions: Dict[str, List[Dict[str, Any]]] = {}

        # Help text storage
        self.ini_help_texts: Dict[str, Dict[str, str]] = (
            {}
        )  # Help texts loaded from INI
        self.registered_help_texts: Dict[str, Dict[str, Any]] = (
            {}
        )  # Help texts registered by scripts

        # Load help texts from INI file
        self._load_help_texts()

        self.scripts: Dict[str, Any] = {}
        self.disabled_scripts = set(DISABLED_SCRIPTS)
        self.script_dir = SCRIPTS_DIR_NAME

    def _load_help_texts(self):
        """Load help texts from the command_help.ini file."""
        help_ini_path = os.path.join(self.scripts_dir, HELP_INI_PATH)
        if not os.path.exists(help_ini_path):
            logger.warning(
                f"Help file '{help_ini_path}' not found. No help texts will be loaded."
            )
            return

        try:
            config = configparser.ConfigParser()
            config.read(help_ini_path, encoding="utf-8")

            for section in config.sections():
                self.ini_help_texts[section] = {}
                for command, help_text in config[section].items():
                    self.ini_help_texts[section][command] = help_text

            logger.info(f"Successfully loaded help texts from '{help_ini_path}'")
        except Exception as e:
            logger.error(
                f"Error loading help texts from '{help_ini_path}': {e}", exc_info=True
            )

    def register_help_text_from_script(
        self, command_name: str, help_text: str, aliases: List[str], script_name: str
    ):
        """Register help text for a command from a script.

        Args:
            command_name: The name of the command
            help_text: The help text (usage + description)
            aliases: List of command aliases
            script_name: Name of the script registering the help text
        """
        cmd_name_lower = command_name.lower()

        # Store the help text
        self.registered_help_texts[cmd_name_lower] = {
            "help_text": help_text,
            "aliases": [alias.lower() for alias in aliases],
            "script_name": script_name,
        }
        logger.info(
            f"Script '{script_name}' registered help text for command: /{cmd_name_lower}"
        )

        # Store help text for aliases too
        for alias in aliases:
            alias_lower = alias.lower()
            self.registered_help_texts[alias_lower] = {
                "help_text": help_text,
                "aliases": [cmd_name_lower]
                + [a.lower() for a in aliases if a != alias],
                "script_name": script_name,
                "is_alias": True,
                "primary_command": cmd_name_lower,
            }
            logger.info(
                f"Script '{script_name}' registered help text for alias: /{alias_lower}"
            )

    def get_help_text_for_command(self, command_name: str) -> Optional[Dict[str, Any]]:
        """Get help text for a command, checking both INI-loaded and script-registered help texts.

        Args:
            command_name: The name of the command to get help for

        Returns:
            Dict containing help text and metadata, or None if not found
        """
        cmd_lower = command_name.lower()

        # First check script-registered help texts
        if cmd_lower in self.registered_help_texts:
            return self.registered_help_texts[cmd_lower]

        # Then check INI-loaded help texts
        for section in self.ini_help_texts.values():
            if cmd_lower in section:
                return {
                    "help_text": section[cmd_lower],
                    "aliases": [],  # INI doesn't store aliases
                    "script_name": "core",  # Core commands are from INI
                    "is_alias": False,
                }

        return None

    def get_all_help_texts(self, section: str = "core") -> Dict[str, str]:
        """Get all help texts from the specified section.

        This combines both INI-loaded and script-registered help texts.
        """
        help_texts = {}

        # Add INI-loaded help texts
        if section in self.ini_help_texts:
            help_texts.update(self.ini_help_texts[section])

        # Add script-registered help texts
        for cmd_name, data in self.registered_help_texts.items():
            if not data.get("is_alias"):  # Only include primary commands, not aliases
                help_texts[cmd_name] = data["help_text"]

        return help_texts

    # --- New method to get data file path for a script ---
    def get_data_file_path_for_script(
        self, script_module_name: str, data_filename: str
    ) -> str:
        # Path will be: <base_dir>/scripts/data/<script_module_name>/<data_filename>
        data_dir = os.path.join(self.scripts_dir, "data", script_module_name)
        # Ensure the specific script's data directory exists
        if not os.path.exists(data_dir):
            try:
                os.makedirs(data_dir, exist_ok=True)
                logger.info(
                    f"Created data directory for script '{script_module_name}': {data_dir}"
                )
            except OSError as e:
                logger.error(
                    f"Failed to create data directory {data_dir} for script '{script_module_name}': {e}"
                )
                # Fallback or raise error? For now, path will be returned, open() will fail later.
        return os.path.join(data_dir, data_filename)

    def load_scripts(self):
        """Load all scripts from the scripts directory."""
        logger.info("Loading scripts...")

        if not os.path.exists(self.scripts_dir):
            logger.warning(f"Scripts directory does not exist: {self.scripts_dir}")
            return

        for script_file in os.listdir(self.scripts_dir):
            if script_file.endswith(".py") and not script_file.startswith("__"):
                script_name = script_file[:-3]  # Remove .py extension
                if script_name in self.disabled_scripts:
                    logger.info(f"Skipping disabled script: {script_name}")
                    continue
                try:
                    # Import the script module
                    script_module = importlib.import_module(f"scripts.{script_name}")

                    # Create ScriptAPIHandler instance for this script
                    api_handler = ScriptAPIHandler(
                        self.client_logic_ref,  # Correct: pass the client logic reference
                        self,  # Correct: pass the script manager reference
                        script_name,  # Correct: pass the script module name
                    )

                    # Get script instance using the correctly initialized api_handler
                    if hasattr(script_module, "get_script_instance"):
                        script_instance = script_module.get_script_instance(api_handler)
                        if script_instance:
                            self.loaded_script_instances[script_name] = script_instance
                            logger.info(f"Loaded script: {script_name}")

                            # Debug logging
                            logger.debug(
                                f"For script '{script_name}', api_handler type is: {type(api_handler)}"
                            )
                            logger.debug(
                                f"Script instance '{script_name}' has api: {hasattr(script_instance, 'api')}"
                            )
                            if hasattr(script_instance, "api"):
                                logger.debug(
                                    f"script_instance.api type is: {type(script_instance.api)}"
                                )
                                logger.debug(
                                    f"script_instance.api has subscribe_to_event: {hasattr(script_instance.api, 'subscribe_to_event')}"
                                )
                                logger.debug(
                                    f"script_instance.api has register_event: {hasattr(script_instance.api, 'register_event')}"
                                )

                            # Call load() if it exists
                            if hasattr(script_instance, "load"):
                                script_instance.load()
                                logger.info(
                                    f"Successfully loaded and initialized script: {script_name}"
                                )
                            else:
                                logger.debug(
                                    f"Script {script_name} instance created, but no 'load' method found. Ensure registrations happen in __init__ if intended."
                                )
                    else:
                        logger.warning(
                            f"Script {script_name} has no get_script_instance function"
                        )
                except Exception as e:
                    logger.error(f"Failed to load script {script_name}: {str(e)}")
                    continue

    # script_name is now reliably passed from ScriptAPIHandler
    def register_command_from_script(
        self,
        command_name: str,
        handler_function: Callable,
        help_text: str,
        aliases: List[str],
        script_name: str,
    ):  # script_name is now required
        cmd_name_lower = command_name.lower()

        # Check for conflicts with core commands (from CommandHandler.command_map)
        # This requires ScriptManager to have a reference to CommandHandler or for CommandHandler to expose its map.
        # For now, we'll only check against other script commands.
        # A more robust system might involve CommandHandler querying ScriptManager.
        if (
            cmd_name_lower in self.registered_commands
            or cmd_name_lower in self.command_aliases
        ):
            # Log details about the existing command
            existing_info = None
            if cmd_name_lower in self.registered_commands:
                existing_info = self.registered_commands.get(cmd_name_lower)
            else:
                aliased_command_name = self.command_aliases.get(cmd_name_lower)
                if aliased_command_name:
                    existing_info = self.registered_commands.get(aliased_command_name)

            existing_script = (
                existing_info.get("script_name", "another script")
                if existing_info
                else "unknown origin"
            )
            logger.warning(
                f"Script command '/{cmd_name_lower}' from script '{script_name}' conflicts with an existing command from '{existing_script}'. Overwriting."
            )

        self.registered_commands[cmd_name_lower] = {
            "handler": handler_function,
            "help": help_text,
            "aliases": [alias.lower() for alias in aliases],
            "script_name": script_name,
        }
        logger.info(f"Script '{script_name}' registered command: /{cmd_name_lower}")

        for alias_orig_case in aliases:
            alias = alias_orig_case.lower()
            if alias in self.registered_commands or alias in self.command_aliases:
                # Log details about the conflicting alias
                existing_alias_info = None
                if alias in self.registered_commands:
                    existing_alias_info = self.registered_commands.get(alias)
                else:
                    aliased_command_name_for_alias = self.command_aliases.get(alias)
                    if aliased_command_name_for_alias:
                        existing_alias_info = self.registered_commands.get(
                            aliased_command_name_for_alias
                        )

                existing_alias_script = (
                    existing_alias_info.get("script_name", "another script")
                    if existing_alias_info
                    else "unknown origin"
                )
                logger.warning(
                    f"Alias '/{alias}' for script command '/{cmd_name_lower}' (from '{script_name}') conflicts with an existing command/alias from '{existing_alias_script}'. Alias not registered."
                )
            else:
                self.command_aliases[alias] = cmd_name_lower
                logger.info(
                    f"Script '{script_name}' registered alias: /{alias} for /{cmd_name_lower}"
                )

    def get_script_command_handler_and_data(
        self, command_name: str
    ) -> Optional[Dict[str, Any]]:
        cmd_lower = command_name.lower()
        if cmd_lower in self.registered_commands:
            return self.registered_commands[cmd_lower]
        elif cmd_lower in self.command_aliases:
            primary_cmd_name = self.command_aliases[cmd_lower]
            return self.registered_commands.get(primary_cmd_name)
        return None

    def get_all_script_commands_with_help(self) -> List[Dict[str, Any]]:
        commands = []
        for cmd_name, data in self.registered_commands.items():
            commands.append(
                {
                    "name": cmd_name,
                    "help": data["help"],
                    "aliases": data["aliases"],
                    "script_name": data["script_name"],
                }
            )
        return commands

    # --- Event System Methods ---
    def subscribe_script_to_event(
        self, event_name: str, handler_function: Callable, script_name: str
    ):
        """Subscribe a script's handler function to an event.

        Args:
            event_name: The name of the event to subscribe to
            handler_function: The function to call when the event occurs
            script_name: The name of the script subscribing to the event
        """
        if not callable(handler_function):
            logger.error(
                f"Script '{script_name}' attempted to subscribe non-callable handler for event '{event_name}'."
            )
            return

        if event_name not in self.event_subscriptions:
            self.event_subscriptions[event_name] = []

        # Check if this specific handler from this script is already subscribed
        for sub in self.event_subscriptions[event_name]:
            if sub["handler"] == handler_function and sub["script_name"] == script_name:
                logger.warning(
                    f"Script '{script_name}' handler already subscribed to event '{event_name}'. Ignoring duplicate."
                )
                return

        # Add the subscription with enabled=True by default
        self.event_subscriptions[event_name].append(
            {"handler": handler_function, "script_name": script_name, "enabled": True}
        )
        logger.info(
            f"Script '{script_name}' subscribed to event '{event_name}' with handler '{handler_function.__name__}'."
        )

    def unsubscribe_script_from_event(
        self, event_name: str, handler_function: Callable, script_name: str
    ):
        """Unsubscribe a script's handler function from an event.

        Args:
            event_name: The name of the event to unsubscribe from
            handler_function: The function to remove from the event's handlers
            script_name: The name of the script unsubscribing from the event
        """
        if event_name in self.event_subscriptions:
            self.event_subscriptions[event_name] = [
                sub
                for sub in self.event_subscriptions[event_name]
                if not (
                    sub["handler"] == handler_function
                    and sub["script_name"] == script_name
                )
            ]
            logger.info(
                f"Script '{script_name}' unsubscribed handler '{handler_function.__name__}' from event '{event_name}'."
            )

    def dispatch_event(
        self, event_name: str, event_data: Optional[Dict[str, Any]] = None
    ):
        """Dispatch an event to all subscribed handlers.

        Args:
            event_name: The name of the event to dispatch
            event_data: Optional dictionary containing event data
        """
        if event_data is None:
            event_data = {}

        # Ensure consistent event data structure
        if "timestamp" not in event_data:
            event_data["timestamp"] = time.time()
        if "raw_line" not in event_data:
            event_data["raw_line"] = ""  # Empty string if no raw line available
        if "client_nick" not in event_data and hasattr(self.client_logic_ref, "nick"):
            event_data["client_nick"] = self.client_logic_ref.nick

        logger.debug(f"Dispatching event '{event_name}' with data: {event_data}")
        if event_name in self.event_subscriptions:
            # Iterate over a copy in case a handler tries to unsubscribe during dispatch
            for subscription in list(self.event_subscriptions[event_name]):
                if not subscription.get("enabled", True):
                    continue

                handler = subscription["handler"]
                script_name = subscription["script_name"]
                try:
                    logger.debug(
                        f"Calling handler '{handler.__name__}' from script '{script_name}' for event '{event_name}'."
                    )
                    handler(event_data)
                except Exception as e:
                    logger.error(
                        f"Error in event handler '{handler.__name__}' from script '{script_name}' for event '{event_name}': {e}",
                        exc_info=True,
                    )
                    # Add a message to the client's status window
                    error_message = f"Error in script '{script_name}' event handler for '{event_name}': {e}"
                    self.client_logic_ref.add_message(
                        error_message,
                        self.client_logic_ref.ui.colors.get("error", 0),
                        context_name="Status",
                    )
                    # Optionally disable the handler to prevent repeated errors
                    subscription["enabled"] = False
                    logger.warning(
                        f"Disabled event handler '{handler.__name__}' from script '{script_name}' due to error."
                    )
        else:
            logger.debug(f"No subscriptions found for event '{event_name}'.")

    # --- Random Message Methods ---
    def get_random_quit_message_from_scripts(
        self, variables: Dict[str, str]
    ) -> Optional[str]:
        for script_name, instance in self.loaded_script_instances.items():
            if hasattr(instance, "get_quit_message") and callable(
                instance.get_quit_message
            ):
                try:
                    message_obj = instance.get_quit_message(variables)
                    if (
                        message_obj is not None
                    ):  # First script to provide a message wins
                        if isinstance(message_obj, str):
                            message_str = message_obj  # Type is now confirmed as str
                            logger.info(
                                f"Script '{script_name}' provided quit message: '{message_str[:50]}...'"
                            )
                            return message_str
                        else:
                            logger.warning(
                                f"Script '{script_name}' get_quit_message returned non-string type: {type(message_obj)}. Ignoring."
                            )
                except Exception as e:
                    logger.error(
                        f"Error calling get_quit_message on script '{script_name}': {e}",
                        exc_info=True,
                    )
        return None

    def get_random_part_message_from_scripts(
        self, variables: Dict[str, str]
    ) -> Optional[str]:
        for script_name, instance in self.loaded_script_instances.items():
            if hasattr(instance, "get_part_message") and callable(
                instance.get_part_message
            ):
                try:
                    message_obj = instance.get_part_message(variables)
                    if (
                        message_obj is not None
                    ):  # First script to provide a message wins
                        if isinstance(message_obj, str):
                            message_str = message_obj  # Type is now confirmed as str
                            logger.info(
                                f"Script '{script_name}' provided part message: '{message_str[:50]}...'"
                            )
                            return message_str
                        else:
                            logger.warning(
                                f"Script '{script_name}' get_part_message returned non-string type: {type(message_obj)}. Ignoring."
                            )
                except Exception as e:
                    logger.error(
                        f"Error calling get_part_message on script '{script_name}': {e}",
                        exc_info=True,
                    )
        return None

    def enable_script(self, script_name: str) -> bool:
        """Enable a previously disabled script."""
        if script_name in self.disabled_scripts:
            self.disabled_scripts.remove(script_name)
            try:
                module = importlib.import_module(f"{self.script_dir}.{script_name}")
                if hasattr(module, "load"):
                    self.scripts[script_name] = module
                    logger.info(f"Enabled and loaded script: {script_name}")
                    return True
                else:
                    logger.warning(f"Script {script_name} has no 'load' method")
            except Exception as e:
                logger.error(f"Failed to enable script {script_name}: {str(e)}")
        return False

    def disable_script(self, script_name: str) -> bool:
        """Disable a currently loaded script."""
        if script_name in self.scripts:
            self.disabled_scripts.add(script_name)
            del self.scripts[script_name]
            logger.info(f"Disabled script: {script_name}")
            return True
        return False

    def get_script(self, script_name: str) -> Optional[Any]:
        """Get a loaded script by name."""
        return self.scripts.get(script_name)

    def get_loaded_scripts(self) -> List[str]:
        """Get list of currently loaded script names."""
        return list(self.scripts.keys())

    def get_disabled_scripts(self) -> List[str]:
        """Get list of disabled script names."""
        return list(self.disabled_scripts)

    def reload_script(self, script_name: str) -> bool:
        """Reload a script by name."""
        if script_name in self.scripts:
            try:
                module = importlib.reload(self.scripts[script_name])
                self.scripts[script_name] = module
                logger.info(f"Reloaded script: {script_name}")
                return True
            except Exception as e:
                logger.error(f"Failed to reload script {script_name}: {str(e)}")
        return False
