import os
import importlib.util
import logging
import configparser
import time
import sys
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Any, Set, Tuple
import threading
from config import DISABLED_SCRIPTS, ENABLE_TRIGGER_SYSTEM

from script_api_handler import ScriptAPIHandler

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


class ScriptManager:
    """Manages loading and execution of Python scripts."""

    def __init__(
        self,
        client_logic_ref: "IRCClient_Logic",
        base_dir: str,
        disabled_scripts: Optional[Set[str]] = None,
    ):
        """Initialize the script manager.

        Args:
            client_logic_ref: Reference to the IRC client logic instance.
            base_dir: Base directory for script files.
            disabled_scripts: Optional set of script names to disable.
        """
        self.client_logic_ref = client_logic_ref
        self.base_dir = base_dir
        self.scripts_dir = os.path.join(self.base_dir, SCRIPTS_DIR_NAME)
        self.scripts = {}
        self.disabled_scripts = disabled_scripts or set()
        self.logger = logging.getLogger(__name__)

        # Command and event management
        self.registered_commands: Dict[str, Dict[str, Any]] = {}
        self.command_aliases: Dict[str, str] = {}
        self.event_subscriptions: Dict[str, List[Dict[str, Any]]] = {}

        # Help text storage
        self.ini_help_texts: Dict[str, Dict[str, str]] = {}
        self.registered_help_texts: Dict[str, Dict[str, Any]] = {}

        # Load help texts from INI file
        self._load_help_texts()

    def _load_help_texts(self):
        """Load help texts from the command_help.ini file."""
        help_ini_path = os.path.join(self.scripts_dir, HELP_INI_PATH)
        if not os.path.exists(help_ini_path):
            self.logger.warning(
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

            self.logger.info(f"Successfully loaded help texts from '{help_ini_path}'")
        except Exception as e:
            self.logger.error(
                f"Error loading help texts from '{help_ini_path}': {e}", exc_info=True
            )

    def get_data_file_path_for_script(
        self, script_name: str, data_filename: str
    ) -> str:
        """Get the path to a data file for a specific script.

        Args:
            script_name: Name of the script module.
            data_filename: Name of the data file.

        Returns:
            Path to the data file.
        """
        data_dir = os.path.join(self.scripts_dir, "data", script_name)
        if not os.path.exists(data_dir):
            try:
                os.makedirs(data_dir, exist_ok=True)
                self.logger.info(
                    f"Created data directory for script '{script_name}': {data_dir}"
                )
            except OSError as e:
                self.logger.error(
                    f"Failed to create data directory {data_dir} for script '{script_name}': {e}"
                )
        return os.path.join(data_dir, data_filename)

    def load_scripts(self) -> None:
        """Load all scripts from the scripts directory."""
        self.logger.info("Loading scripts...")

        if not os.path.exists(self.scripts_dir):
            self.logger.warning(f"Scripts directory does not exist: {self.scripts_dir}")
            return

        for script_file in os.listdir(self.scripts_dir):
            if script_file.endswith(".py") and not script_file.startswith("__"):
                script_name = script_file[:-3]  # Remove .py extension

                if script_name in self.disabled_scripts:
                    self.logger.info(f"Skipping disabled script: {script_name}")
                    continue

                try:
                    # Import the script module
                    script_module = importlib.import_module(f"scripts.{script_name}")

                    # Create ScriptAPIHandler instance for this script
                    api_handler = ScriptAPIHandler(
                        self.client_logic_ref,
                        self,
                        script_name,
                    )

                    # Get script instance using the correctly initialized api_handler
                    if hasattr(script_module, "get_script_instance"):
                        script_instance = script_module.get_script_instance(api_handler)
                        if script_instance:
                            self.scripts[script_name] = script_instance
                            self.logger.info(f"Loaded script: {script_name}")

                            # Call load() if it exists
                            if hasattr(script_instance, "load"):
                                script_instance.load()
                                self.logger.info(
                                    f"Successfully loaded and initialized script: {script_name}"
                                )
                            else:
                                self.logger.debug(
                                    f"Script {script_name} instance created, but no 'load' method found."
                                )
                    else:
                        self.logger.warning(
                            f"Script {script_name} has no get_script_instance function"
                        )
                except Exception as e:
                    self.logger.error(f"Failed to load script {script_name}: {str(e)}")
                    continue

    def get_script(self, script_name: str) -> Optional[Any]:
        """Get a loaded script by name.

        Args:
            script_name: Name of the script to retrieve.

        Returns:
            The script module if found and enabled, None otherwise.
        """
        if script_name in self.disabled_scripts:
            self.logger.debug(f"Script {script_name} is disabled")
            return None
        return self.scripts.get(script_name)

    def is_script_enabled(self, script_name: str) -> bool:
        """Check if a script is enabled.

        Args:
            script_name: Name of the script to check.

        Returns:
            True if the script is enabled, False otherwise.
        """
        return script_name not in self.disabled_scripts and script_name in self.scripts

    def register_command_from_script(
        self,
        command_name: str,
        handler: Callable,
        help_text: str,
        aliases: List[str],
        script_name: str,
    ) -> None:
        """Register a command from a script.

        Args:
            command_name: Name of the command.
            handler: Function to handle the command.
            help_text: Help text for the command.
            aliases: List of command aliases.
            script_name: Name of the script registering the command.
        """
        cmd_name_lower = command_name.lower()

        # Store the command
        self.registered_commands[cmd_name_lower] = {
            "handler": handler,
            "help_text": help_text,
            "aliases": [alias.lower() for alias in aliases],
            "script_name": script_name,
        }

        # Store aliases
        for alias in aliases:
            alias_lower = alias.lower()
            self.command_aliases[alias_lower] = cmd_name_lower

        self.logger.info(
            f"Script '{script_name}' registered command: /{cmd_name_lower}"
        )

    def register_help_text_from_script(
        self, command_name: str, help_text: str, aliases: List[str], script_name: str
    ) -> None:
        """Register help text for a command from a script.

        Args:
            command_name: The name of the command.
            help_text: The help text (usage + description).
            aliases: List of command aliases.
            script_name: Name of the script registering the help text.
        """
        cmd_name_lower = command_name.lower()

        # Store the help text
        self.registered_help_texts[cmd_name_lower] = {
            "help_text": help_text,
            "aliases": [alias.lower() for alias in aliases],
            "script_name": script_name,
        }
        self.logger.info(
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
            self.logger.info(
                f"Script '{script_name}' registered help text for alias: /{alias_lower}"
            )

    def get_help_text_for_command(self, command_name: str) -> Optional[Dict[str, Any]]:
        """Get help text for a command, checking both INI-loaded and script-registered help texts.

        Args:
            command_name: The name of the command to get help for.

        Returns:
            Dict containing help text and metadata, or None if not found.
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

        Args:
            section: Section to get help texts from.

        Returns:
            Dictionary of command names to help texts.
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

    def get_loaded_scripts(self) -> List[str]:
        """Get list of currently loaded script names."""
        return list(self.scripts.keys())

    def subscribe_script_to_event(
        self, event_name: str, handler_function: Callable, script_name: str
    ) -> None:
        """Subscribe a script's handler function to an event.

        Args:
            event_name: The name of the event to subscribe to.
            handler_function: The function to call when the event occurs.
            script_name: The name of the script subscribing to the event.
        """
        if not callable(handler_function):
            self.logger.error(
                f"Script '{script_name}' attempted to subscribe non-callable handler for event '{event_name}'."
            )
            return

        if event_name not in self.event_subscriptions:
            self.event_subscriptions[event_name] = []

        # Check if this specific handler from this script is already subscribed
        for sub in self.event_subscriptions[event_name]:
            if sub["handler"] == handler_function and sub["script_name"] == script_name:
                self.logger.warning(
                    f"Script '{script_name}' handler already subscribed to event '{event_name}'. Ignoring duplicate."
                )
                return

        # Add the subscription with enabled=True by default
        self.event_subscriptions[event_name].append(
            {"handler": handler_function, "script_name": script_name, "enabled": True}
        )
        self.logger.info(
            f"Script '{script_name}' subscribed to event '{event_name}' with handler '{handler_function.__name__}'."
        )

    def unsubscribe_script_from_event(
        self, event_name: str, handler_function: Callable, script_name: str
    ) -> None:
        """Unsubscribe a script's handler function from an event.

        Args:
            event_name: The name of the event to unsubscribe from.
            handler_function: The function to remove from the event's handlers.
            script_name: The name of the script unsubscribing from the event.
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
            self.logger.info(
                f"Script '{script_name}' unsubscribed handler '{handler_function.__name__}' from event '{event_name}'."
            )

    def dispatch_event(
        self, event_name: str, event_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Dispatch an event to all subscribed handlers.

        Args:
            event_name: The name of the event to dispatch.
            event_data: Optional dictionary containing event data.
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

        self.logger.debug(f"Dispatching event '{event_name}' with data: {event_data}")
        if event_name in self.event_subscriptions:
            # Iterate over a copy in case a handler tries to unsubscribe during dispatch
            for subscription in list(self.event_subscriptions[event_name]):
                if not subscription.get("enabled", True):
                    continue

                handler = subscription["handler"]
                script_name = subscription["script_name"]
                try:
                    self.logger.debug(
                        f"Calling handler '{handler.__name__}' from script '{script_name}' for event '{event_name}'."
                    )
                    handler(event_data)
                except Exception as e:
                    self.logger.error(
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
                    self.logger.warning(
                        f"Disabled event handler '{handler.__name__}' from script '{script_name}' due to error."
                    )
        else:
            self.logger.debug(f"No subscriptions found for event '{event_name}'.")

    def get_random_quit_message_from_scripts(
        self, variables: Dict[str, str]
    ) -> Optional[str]:
        """Get a random quit message from scripts.

        Args:
            variables: Dictionary of variables to use in the message.

        Returns:
            A random quit message or None if no scripts provide one.
        """
        for script_name, instance in self.scripts.items():
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
                            self.logger.info(
                                f"Script '{script_name}' provided quit message: '{message_str[:50]}...'"
                            )
                            return message_str
                        else:
                            self.logger.warning(
                                f"Script '{script_name}' get_quit_message returned non-string type: {type(message_obj)}. Ignoring."
                            )
                except Exception as e:
                    self.logger.error(
                        f"Error calling get_quit_message on script '{script_name}': {e}",
                        exc_info=True,
                    )
        return None

    def get_random_part_message_from_scripts(
        self, variables: Dict[str, str]
    ) -> Optional[str]:
        """Get a random part message from scripts.

        Args:
            variables: Dictionary of variables to use in the message.

        Returns:
            A random part message or None if no scripts provide one.
        """
        for script_name, instance in self.scripts.items():
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
                            self.logger.info(
                                f"Script '{script_name}' provided part message: '{message_str[:50]}...'"
                            )
                            return message_str
                        else:
                            self.logger.warning(
                                f"Script '{script_name}' get_part_message returned non-string type: {type(message_obj)}. Ignoring."
                            )
                except Exception as e:
                    self.logger.error(
                        f"Error calling get_part_message on script '{script_name}': {e}",
                        exc_info=True,
                    )
        return None

    def enable_script(self, script_name: str) -> bool:
        """Enable a previously disabled script.

        Args:
            script_name: Name of the script to enable.

        Returns:
            True if the script was enabled successfully, False otherwise.
        """
        if script_name in self.disabled_scripts:
            self.disabled_scripts.remove(script_name)
            try:
                module = importlib.import_module(f"scripts.{script_name}")
                if hasattr(module, "get_script_instance"):
                    api_handler = ScriptAPIHandler(
                        self.client_logic_ref,
                        self,
                        script_name,
                    )
                    script_instance = module.get_script_instance(api_handler)
                    if script_instance:
                        self.scripts[script_name] = script_instance
                        self.logger.info(f"Enabled and loaded script: {script_name}")
                        return True
                else:
                    self.logger.warning(
                        f"Script {script_name} has no 'get_script_instance' method"
                    )
            except Exception as e:
                self.logger.error(f"Failed to enable script {script_name}: {str(e)}")
        return False

    def disable_script(self, script_name: str) -> bool:
        """Disable a currently loaded script.

        Args:
            script_name: Name of the script to disable.

        Returns:
            True if the script was disabled successfully, False otherwise.
        """
        if script_name in self.scripts:
            self.disabled_scripts.add(script_name)
            del self.scripts[script_name]
            self.logger.info(f"Disabled script: {script_name}")
            return True
        return False

    def reload_script(self, script_name: str) -> bool:
        """Reload a script by name.

        Args:
            script_name: Name of the script to reload.

        Returns:
            True if the script was reloaded successfully, False otherwise.
        """
        if script_name in self.scripts:
            try:
                module = importlib.reload(self.scripts[script_name])
                if hasattr(module, "get_script_instance"):
                    api_handler = ScriptAPIHandler(
                        self.client_logic_ref,
                        self,
                        script_name,
                    )
                    script_instance = module.get_script_instance(api_handler)
                    if script_instance:
                        self.scripts[script_name] = script_instance
                        self.logger.info(f"Reloaded script: {script_name}")
                        return True
            except Exception as e:
                self.logger.error(f"Failed to reload script {script_name}: {str(e)}")
        return False

    def get_disabled_scripts(self) -> List[str]:
        """Get list of disabled script names."""
        return list(self.disabled_scripts)

    def get_all_script_commands_with_help(self) -> Dict[str, Dict[str, Any]]:
        """Get all script commands with their help text and metadata.

        Returns:
            Dictionary mapping command names to their help text and metadata.
        """
        commands = {}
        for cmd_name, cmd_data in self.registered_commands.items():
            help_data = self.get_help_text_for_command(cmd_name)
            if help_data:
                commands[cmd_name] = {
                    "help_text": help_data["help_text"],
                    "aliases": cmd_data["aliases"],
                    "script_name": cmd_data["script_name"],
                }
        return commands

    def get_script_command_handler_and_data(
        self, command_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get the handler function and metadata for a script command.

        Args:
            command_name: Name of the command to get handler for.

        Returns:
            Dictionary containing handler function and metadata, or None if not found.
        """
        cmd_name_lower = command_name.lower()
        if cmd_name_lower in self.registered_commands:
            return self.registered_commands[cmd_name_lower]
        elif cmd_name_lower in self.command_aliases:
            alias_target = self.command_aliases[cmd_name_lower]
            return self.registered_commands[alias_target]
        return None
