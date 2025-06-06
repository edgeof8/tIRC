# START OF MODIFIED FILE: script_manager.py
import os
import importlib.util
import logging
import configparser
import time
import sys
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Any, Set, Tuple, Union
import threading
from config import DISABLED_SCRIPTS, ENABLE_TRIGGER_SYSTEM

from script_api_handler import ScriptAPIHandler

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic


logger = logging.getLogger("pyrc.script_manager")

SCRIPTS_DIR_NAME = "scripts"
HELP_INI_FILENAME = "command_help.ini"
HELP_INI_PATH = os.path.join("data", "default_help", HELP_INI_FILENAME)


class ScriptManager:
    def __init__(
        self,
        client_logic_ref: "IRCClient_Logic",
        base_dir: str,
        disabled_scripts: Optional[Set[str]] = None,
    ):
        self.client_logic_ref = client_logic_ref
        self.base_dir = base_dir
        self.scripts_dir = os.path.join(self.base_dir, SCRIPTS_DIR_NAME)
        self.scripts = {}
        self.disabled_scripts = disabled_scripts or set()
        self.logger = logging.getLogger(__name__)  # Use specific logger

        self.registered_commands: Dict[str, Dict[str, Any]] = {}
        self.command_aliases: Dict[str, str] = {}
        self.event_subscriptions: Dict[str, List[Dict[str, Any]]] = {}
        self.registered_help_texts: Dict[str, Dict[str, Any]] = (
            {}
        )  # For api.register_help_text
        self.ini_help_texts: Dict[str, Dict[str, str]] = {}
        self._load_help_texts()

    def _load_help_texts(self):
        help_ini_full_path = os.path.join(self.base_dir, HELP_INI_PATH)  # Use base_dir
        if not os.path.exists(help_ini_full_path):
            self.logger.warning(
                f"Help file '{help_ini_full_path}' not found. No INI help texts will be loaded."
            )
            return
        try:
            config = configparser.ConfigParser()
            config.read(help_ini_full_path, encoding="utf-8")
            for section in config.sections():
                self.ini_help_texts[section] = {}
                for command, help_text in config[section].items():
                    self.ini_help_texts[section][
                        command.lower()
                    ] = help_text  # Store command lowercase
            self.logger.info(
                f"Successfully loaded help texts from '{help_ini_full_path}'"
            )
        except Exception as e:
            self.logger.error(
                f"Error loading help texts from '{help_ini_full_path}': {e}",
                exc_info=True,
            )

    def get_data_file_path_for_script(
        self, script_name: str, data_filename: str
    ) -> str:
        # script_name is module name like "ai_api_test_script"
        # Corrected path to look inside the 'scripts' directory
        data_dir = os.path.join(
            self.scripts_dir, "data", script_name
        )  # Store data in <project_root>/scripts/data/<script_name>/
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
        self.logger.info(f"Loading scripts from: {self.scripts_dir}")
        if not os.path.exists(self.scripts_dir):
            self.logger.warning(f"Scripts directory does not exist: {self.scripts_dir}")
            return

        for script_file in os.listdir(self.scripts_dir):
            if script_file.endswith(".py") and not script_file.startswith("__"):
                script_name = script_file[:-3]
                if script_name in self.disabled_scripts:
                    self.logger.info(f"Skipping disabled script: {script_name}")
                    continue
                try:
                    script_module = importlib.import_module(f"scripts.{script_name}")
                    api_handler = ScriptAPIHandler(
                        self.client_logic_ref, self, script_name
                    )
                    if hasattr(script_module, "get_script_instance"):
                        script_instance = script_module.get_script_instance(api_handler)
                        if script_instance:
                            self.scripts[script_name] = script_instance
                            if hasattr(script_instance, "load") and callable(
                                script_instance.load
                            ):
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
                    self.logger.error(
                        f"Failed to load script {script_name}: {e}", exc_info=True
                    )  # Log full traceback

    def get_script(self, script_name: str) -> Optional[Any]:
        if script_name in self.disabled_scripts:
            self.logger.debug(f"Script {script_name} is disabled")
            return None
        return self.scripts.get(script_name)

    def is_script_enabled(self, script_name: str) -> bool:
        return script_name not in self.disabled_scripts and script_name in self.scripts

    def register_command_from_script(
        self,
        command_name: str,
        handler: Callable,
        help_info: Union[str, Dict[str, Any]],  # Changed from help_text to help_info
        aliases: Optional[List[str]] = None,
        script_name: Optional[str] = None,
    ) -> None:
        """Register a command from a script.

        Args:
            command_name: The name of the command (without leading slash)
            handler: The function that handles the command
            help_info: Either a string or a dictionary containing help information.
                      If a dictionary, it should have 'usage' and 'description' keys,
                      and optionally an 'aliases' key.
            aliases: Optional list of command aliases. If help_info is a dict and contains
                    aliases, those will be used instead of this parameter.
            script_name: The name of the script registering the command
        """
        if aliases is None:
            aliases = []
        if script_name is None:
            script_name = "UnknownScriptFromRegisterCommand"  # Fallback

        cmd_name_lower = command_name.lower()

        # Store the help info as is - it can be either string or dict
        self.registered_commands[cmd_name_lower] = {
            "handler": handler,
            "help_info": help_info,  # Store the help info directly
            "aliases": [alias.lower() for alias in aliases],
            "script_name": script_name,
        }

        # Register aliases
        for alias in aliases:
            self.command_aliases[alias.lower()] = cmd_name_lower

        self.logger.info(
            f"Script '{script_name}' registered command: /{cmd_name_lower}"
        )

    def register_help_text_from_script(
        self,
        command_name: str,
        help_text: str,
        aliases: Optional[List[str]] = None,
        script_name: Optional[str] = None,
    ) -> None:
        if aliases is None:
            aliases = []
        if script_name is None:
            script_name = "UnknownScriptFromRegisterHelp"

        cmd_name_lower = command_name.lower()
        self.registered_help_texts[cmd_name_lower] = {
            "help_text": help_text,
            "aliases": [alias.lower() for alias in aliases],
            "script_name": script_name,
            "is_alias": False,
        }
        self.logger.info(
            f"Script '{script_name}' registered explicit help text for command: /{cmd_name_lower}"
        )
        for alias in aliases:
            alias_lower = alias.lower()
            self.registered_help_texts[alias_lower] = {
                "help_text": help_text,
                "aliases": [cmd_name_lower]
                + [a.lower() for a in aliases if a.lower() != alias_lower],
                "script_name": script_name,
                "is_alias": True,
                "primary_command": cmd_name_lower,
            }

    def get_help_text_for_command(self, command_name: str) -> Optional[Dict[str, Any]]:
        """Get help text for a command, handling both string and dictionary help formats.

        Args:
            command_name: The name of the command to get help for

        Returns:
            Optional[Dict[str, Any]]: A dictionary containing help information, or None if not found
        """
        cmd_lower = command_name.lower()

        # Priority: 1. Explicitly registered help, 2. Help from command registration, 3. INI
        if cmd_lower in self.registered_help_texts:
            return self.registered_help_texts[cmd_lower]

        if cmd_lower in self.registered_commands:
            cmd_data = self.registered_commands[cmd_lower]
            help_info = cmd_data.get("help_info", "")

            # If help_info is a dict, format it into a help_text string
            if isinstance(help_info, dict):
                help_text = help_info.get("usage", "")
                if help_info.get("description"):
                    help_text += f"\n{help_info['description']}"
            else:
                help_text = str(help_info)

            return {
                "help_text": help_text,
                "aliases": cmd_data.get("aliases", []),
                "script_name": cmd_data.get("script_name", "script"),
                "is_alias": False,
                "help_info": help_info,  # Include the original help_info
            }

        # Check aliases for commands in self.registered_commands
        if cmd_lower in self.command_aliases:
            primary_cmd_name = self.command_aliases[cmd_lower]
            if primary_cmd_name in self.registered_commands:
                cmd_data = self.registered_commands[primary_cmd_name]
                help_info = cmd_data.get("help_info", "")

                # If help_info is a dict, format it into a help_text string
                if isinstance(help_info, dict):
                    help_text = help_info.get("usage", "")
                    if help_info.get("description"):
                        help_text += f"\n{help_info['description']}"
                else:
                    help_text = str(help_info)

                all_aliases = cmd_data.get("aliases", [])
                # Construct aliases list for this alias, pointing to primary and other aliases
                alias_list_for_this = [primary_cmd_name] + [
                    a for a in all_aliases if a != cmd_lower
                ]
                return {
                    "help_text": help_text,
                    "aliases": alias_list_for_this,
                    "script_name": cmd_data.get("script_name", "script"),
                    "is_alias": True,
                    "primary_command": primary_cmd_name,
                    "help_info": help_info,  # Include the original help_info
                }

        # Check INI help texts
        for section_name, section_content in self.ini_help_texts.items():
            if cmd_lower in section_content:
                return {
                    "help_text": section_content[cmd_lower],
                    "aliases": [],
                    "script_name": "core_ini",
                    "is_alias": False,
                }
        return None

    def get_all_help_texts(self) -> Dict[str, Dict[str, Any]]:
        """Gets all help texts, prioritizing script-registered ones."""
        all_help = {}

        # Start with INI, script-registered will override
        for section_name, section_content in self.ini_help_texts.items():
            for cmd, text in section_content.items():
                # Only add if not already defined by a more specific source later
                if cmd not in all_help:
                    all_help[cmd] = {
                        "help_text": text,
                        "script_name": "core_ini",
                        "aliases": [],
                    }

        # Add from commands registered by scripts
        for cmd_name, cmd_data in self.registered_commands.items():
            help_info = cmd_data.get("help_info", "")

            # If help_info is a dict, format it into a help_text string
            if isinstance(help_info, dict):
                help_text = help_info.get("usage", "")
                if help_info.get("description"):
                    help_text += f"\n{help_info['description']}"
            else:
                help_text = str(help_info)

            all_help[cmd_name] = {
                "help_text": help_text,
                "aliases": cmd_data.get("aliases", []),
                "script_name": cmd_data.get("script_name", "UnknownScript"),
                "help_info": help_info,  # Include the original help_info
            }

        # Override with explicitly registered help texts (has highest priority)
        for cmd_name, help_data in self.registered_help_texts.items():
            if not help_data.get("is_alias"):  # Only process primary commands here
                all_help[cmd_name] = {
                    "help_text": help_data["help_text"],
                    "aliases": help_data.get("aliases", []),
                    "script_name": help_data["script_name"],
                }
        return all_help

    def get_loaded_scripts(self) -> List[str]:
        return list(self.scripts.keys())

    def subscribe_script_to_event(
        self, event_name: str, handler_function: Callable, script_name: str
    ) -> None:
        if not callable(handler_function):
            self.logger.error(
                f"Script '{script_name}' attempted to subscribe non-callable handler for event '{event_name}'."
            )
            return
        if event_name not in self.event_subscriptions:
            self.event_subscriptions[event_name] = []
        for sub in self.event_subscriptions[event_name]:
            if sub["handler"] == handler_function and sub["script_name"] == script_name:
                self.logger.warning(
                    f"Script '{script_name}' handler already subscribed to event '{event_name}'. Ignoring duplicate."
                )
                return
        self.event_subscriptions[event_name].append(
            {"handler": handler_function, "script_name": script_name, "enabled": True}
        )
        self.logger.info(
            f"Script '{script_name}' subscribed to event '{event_name}' with handler '{handler_function.__name__}'."
        )

    def unsubscribe_script_from_event(
        self, event_name: str, handler_function: Callable, script_name: str
    ):
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
        if event_data is None:
            event_data = {}
        if "timestamp" not in event_data:
            event_data["timestamp"] = time.time()
        if "raw_line" not in event_data:
            event_data["raw_line"] = ""
        if "client_nick" not in event_data and hasattr(self.client_logic_ref, "nick"):
            event_data["client_nick"] = self.client_logic_ref.nick

        self.logger.debug(f"Dispatching event '{event_name}' with data: {event_data}")
        if event_name in self.event_subscriptions:
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
                    error_message = f"Error in script '{script_name}' event handler for '{event_name}': {e}"
                    self.client_logic_ref.add_message(
                        error_message,
                        self.client_logic_ref.ui.colors.get("error", 0),
                        context_name="Status",
                    )
                    subscription["enabled"] = False
                    self.logger.warning(
                        f"Disabled event handler '{handler.__name__}' from script '{script_name}' due to error."
                    )
        else:
            self.logger.debug(f"No subscriptions found for event '{event_name}'.")

    def get_random_quit_message_from_scripts(
        self, variables: Dict[str, str]
    ) -> Optional[str]:
        for script_name, instance in self.scripts.items():
            if hasattr(instance, "get_quit_message") and callable(
                instance.get_quit_message
            ):
                try:
                    message_obj = instance.get_quit_message(variables)
                    if message_obj is not None:
                        if isinstance(message_obj, str):
                            return message_obj
                        else:
                            self.logger.warning(
                                f"Script '{script_name}' get_quit_message returned non-string type. Ignoring."
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
        for script_name, instance in self.scripts.items():
            if hasattr(instance, "get_part_message") and callable(
                instance.get_part_message
            ):
                try:
                    message_obj = instance.get_part_message(variables)
                    if message_obj is not None:
                        if isinstance(message_obj, str):
                            return message_obj
                        else:
                            self.logger.warning(
                                f"Script '{script_name}' get_part_message returned non-string type. Ignoring."
                            )
                except Exception as e:
                    self.logger.error(
                        f"Error calling get_part_message on script '{script_name}': {e}",
                        exc_info=True,
                    )
        return None

    def enable_script(self, script_name: str) -> bool:
        if script_name in self.disabled_scripts:
            self.disabled_scripts.remove(script_name)
            try:
                module = importlib.import_module(f"scripts.{script_name}")
                if hasattr(module, "get_script_instance"):
                    api_handler = ScriptAPIHandler(
                        self.client_logic_ref, self, script_name
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
                self.logger.error(f"Failed to enable script {script_name}: {e}")
        return False

    def disable_script(self, script_name: str) -> bool:
        if script_name in self.scripts:
            self.disabled_scripts.add(script_name)
            del self.scripts[script_name]
            self.logger.info(f"Disabled script: {script_name}")
            return True
        return False

    def reload_script(self, script_name: str) -> bool:
        if script_name in self.scripts:
            try:
                # Unload first if an unload method exists
                if hasattr(self.scripts[script_name], "unload") and callable(
                    self.scripts[script_name].unload
                ):
                    self.scripts[script_name].unload()

                # Remove existing subscriptions and command registrations for this script
                self.event_subscriptions = {
                    event: [sub for sub in subs if sub["script_name"] != script_name]
                    for event, subs in self.event_subscriptions.items()
                }
                self.registered_commands = {
                    cmd: data
                    for cmd, data in self.registered_commands.items()
                    if data["script_name"] != script_name
                }
                self.command_aliases = {
                    alias: target
                    for alias, target in self.command_aliases.items()
                    if self.registered_commands.get(target, {}).get("script_name")
                    != script_name
                }
                self.registered_help_texts = {
                    cmd: data
                    for cmd, data in self.registered_help_texts.items()
                    if data["script_name"] != script_name
                }

                module_to_reload = sys.modules[f"scripts.{script_name}"]
                reloaded_module = importlib.reload(module_to_reload)

                if hasattr(reloaded_module, "get_script_instance"):
                    api_handler = ScriptAPIHandler(
                        self.client_logic_ref, self, script_name
                    )
                    script_instance = reloaded_module.get_script_instance(api_handler)
                    if script_instance:
                        self.scripts[script_name] = script_instance
                        if hasattr(script_instance, "load") and callable(
                            script_instance.load
                        ):
                            script_instance.load()  # Call load on the new instance
                        self.logger.info(f"Reloaded script: {script_name}")
                        return True
                else:
                    self.logger.warning(
                        f"Reloaded script {script_name} has no 'get_script_instance' method"
                    )
            except Exception as e:
                self.logger.error(
                    f"Failed to reload script {script_name}: {e}", exc_info=True
                )
                # If reload fails, try to restore the old instance if it was saved, or remove it
                if script_name in self.scripts:
                    del self.scripts[script_name]  # Remove broken script
        return False

    def get_disabled_scripts(self) -> List[str]:
        return list(self.disabled_scripts)

    def get_all_script_commands_with_help(self) -> Dict[str, Dict[str, Any]]:
        """Get all script commands with their help text and metadata.
        Returns a dictionary grouped by script name, containing command data.
        """
        commands_by_script = {}

        # First, collect commands from registered_commands
        for cmd_name, cmd_data in self.registered_commands.items():
            script_name = cmd_data.get("script_name", "UnknownScript")
            # Normalize script name (remove any module prefixes)
            if "." in script_name:
                script_name = script_name.split(".")[-1]

            if script_name not in commands_by_script:
                commands_by_script[script_name] = {}

            # Only add if not already present (to avoid duplicates)
            if cmd_name not in commands_by_script[script_name]:
                commands_by_script[script_name][cmd_name] = {
                    "help_text": cmd_data.get("help_text", "No help text provided."),
                    "aliases": cmd_data.get("aliases", []),
                    "script_name": script_name,
                }

        # Then, override with explicitly registered help texts
        for cmd_name, help_data in self.registered_help_texts.items():
            if not help_data.get("is_alias"):  # Only process primary commands
                script_name = help_data.get("script_name", "UnknownScript")
                # Normalize script name (remove any module prefixes)
                if "." in script_name:
                    script_name = script_name.split(".")[-1]

                if script_name not in commands_by_script:
                    commands_by_script[script_name] = {}

                # Override or add the command data
                commands_by_script[script_name][cmd_name] = {
                    "help_text": help_data.get("help_text", "No help text provided."),
                    "aliases": help_data.get("aliases", []),
                    "script_name": script_name,
                }

        # Remove any empty script sections
        commands_by_script = {
            script_name: commands
            for script_name, commands in commands_by_script.items()
            if commands
        }

        return commands_by_script

    def get_script_command_handler_and_data(
        self, command_name: str
    ) -> Optional[Dict[str, Any]]:
        cmd_name_lower = command_name.lower()
        if cmd_name_lower in self.registered_commands:
            return self.registered_commands[cmd_name_lower]
        elif cmd_name_lower in self.command_aliases:
            alias_target = self.command_aliases[cmd_name_lower]
            if alias_target in self.registered_commands:  # Ensure target exists
                return self.registered_commands[alias_target]
        return None


# END OF MODIFIED FILE: script_manager.py
