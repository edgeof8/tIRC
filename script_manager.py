import os
import importlib.util
import logging
import configparser
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Any

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
    # Added script_module_name to constructor
    def __init__(
        self,
        client_logic_ref: "IRCClient_Logic",
        script_manager_ref: "ScriptManager",
        script_module_name: str,
    ):
        self.client_logic = client_logic_ref
        self.script_manager = script_manager_ref
        self.script_module_name = script_module_name  # Store the script's module name

    def send_raw(self, command_string: str):
        self.client_logic.network.send_raw(command_string)

    # Added send_action based on plan
    def send_action(self, target: str, action_text: str):
        if not target or not action_text:
            self.log_warning(
                f"send_action called with empty target ('{target}') or action_text ('{action_text}')."
            )
            return
        self.client_logic.network.send_raw(
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
        logger.info(f"ScriptManager: Loading scripts from {self.scripts_dir}")
        if not os.path.isdir(self.scripts_dir):
            logger.warning(
                f"Scripts directory '{self.scripts_dir}' not found. No scripts will be loaded."
            )
            # Optional: Create scripts/ directory if it doesn't exist
            try:
                os.makedirs(
                    self.scripts_dir, exist_ok=True
                )  # exist_ok=True means no error if it exists
                logger.info(f"Ensured scripts directory exists: {self.scripts_dir}")
            except OSError as e:
                logger.error(
                    f"Failed to create scripts directory {self.scripts_dir}: {e}"
                )
                return  # Cannot proceed if scripts dir cannot be accessed/created
            # Also ensure scripts/data/ directory exists
            scripts_data_main_dir = os.path.join(self.scripts_dir, "data")
            if not os.path.isdir(scripts_data_main_dir):
                try:
                    os.makedirs(scripts_data_main_dir, exist_ok=True)
                    logger.info(
                        f"Ensured main script data directory exists: {scripts_data_main_dir}"
                    )
                except OSError as e:
                    logger.error(
                        f"Failed to create main script data directory {scripts_data_main_dir}: {e}"
                    )
                    # Scripts might still load but fail if they need data dirs.

        for filename in os.listdir(self.scripts_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                script_name = filename[:-3]  # This is the module name
                script_path = os.path.join(self.scripts_dir, filename)
                logger.debug(
                    f"Attempting to load script: {script_name} from {script_path}"
                )
                try:
                    spec = importlib.util.spec_from_file_location(
                        script_name, script_path
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)

                        if hasattr(module, "get_script_instance"):
                            # Instantiate ScriptAPIHandler per script, passing the script_name (module name)
                            script_specific_api_handler = ScriptAPIHandler(
                                self.client_logic_ref, self, script_name
                            )
                            script_instance = module.get_script_instance(
                                script_specific_api_handler
                            )

                            if hasattr(script_instance, "load"):
                                script_instance.load()
                                self.loaded_script_instances[script_name] = (
                                    script_instance
                                )
                                logger.info(
                                    f"Successfully loaded and initialized script: {script_name}"
                                )
                            else:
                                logger.warning(
                                    f"Script {script_name} loaded but has no 'load' method."
                                )
                        else:
                            logger.warning(
                                f"Script {script_name} has no 'get_script_instance' function."
                            )
                    else:
                        logger.error(
                            f"Could not create spec for script {script_name} at {script_path}"
                        )
                except Exception as e:
                    logger.error(
                        f"Error loading script {script_name}: {e}", exc_info=True
                    )
                    # Use client_logic_ref directly to add message if API handler instantiation failed
                    self.client_logic_ref.add_message(
                        f"Error loading script '{script_name}': {e}",
                        self.client_logic_ref.ui.colors["error"],
                        context_name="Status",
                    )

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

        # Add timestamp to event data
        event_data["timestamp"] = time.time()

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
