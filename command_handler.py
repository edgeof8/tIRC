# START OF MODIFIED FILE: command_handler.py
import logging
import os
import importlib
from typing import TYPE_CHECKING, List, Optional, Tuple, Dict, Callable, Any
from features.triggers.trigger_commands import TriggerCommands
from context_manager import ChannelJoinStatus, Context
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
    from irc_client_logic import IRCClient_Logic
    CommandHandlerCallable = Callable[[IRCClient_Logic, str], Any]

from context_manager import Context as CTX_Type

logger = logging.getLogger("pyrc.command_handler")


class CommandHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic
        self.trigger_commands = TriggerCommands(client_logic)
        self.registered_command_help = {}
        self._processing_depth = 0 # For re-entrancy check

        self.command_map: Dict[str, "CommandHandlerCallable"] = {
            "on": lambda client, args_str: self.trigger_commands.handle_on_command(args_str),
        }

        commands_dir_path = os.path.join(self.client.script_manager.base_dir, "commands")
        logger.info(f"Starting dynamic command loading from: {commands_dir_path}")

        all_py_files_found = []
        for root, _, files in os.walk(commands_dir_path):
            for filename in files:
                if filename.endswith(".py") and filename != "__init__.py":
                    full_path = os.path.join(root, filename)
                    all_py_files_found.append(full_path)
        logger.debug(f"All .py files discovered by os.walk for command loading: {all_py_files_found}")


        for root, _, files in os.walk(commands_dir_path):
            for filename in files:
                if filename.endswith(".py") and filename != "__init__.py":
                    module_path_on_disk = os.path.join(root, filename)
                    logger.debug(f"Processing potential command module: {module_path_on_disk}")

                    relative_path_from_commands_dir = os.path.relpath(module_path_on_disk, commands_dir_path)
                    module_name_parts = relative_path_from_commands_dir[:-3].split(os.sep)
                    python_module_name = "commands." + ".".join(module_name_parts)

                    try:
                        logger.debug(f"Attempting to import module: {python_module_name}")
                        module = importlib.import_module(python_module_name)
                        logger.debug(f"Successfully imported module: {python_module_name}")

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
                        else:
                             logger.debug(f"Module {python_module_name} does not have COMMAND_DEFINITIONS.")

                    except ImportError as e:
                        logger.error(f"Failed to import module {python_module_name}: {e}", exc_info=True)
                    except Exception as e:
                        logger.error(f"Error processing module {python_module_name}: {e}", exc_info=True)
        logger.info("Finished dynamic command loading.")

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


    def get_available_commands_for_tab_complete(self) -> List[str]:
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
        stripped_args_str = args_str.strip()

        if num_expected_parts == 0: # No arguments expected
            return [] if not stripped_args_str else [stripped_args_str] # Return [] if truly empty, else the unexpected args

        if not stripped_args_str: # Arguments expected but none given
            self.client.add_message(
                usage_message, self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return None

        if num_expected_parts == 1:
            return [stripped_args_str]

        parts = stripped_args_str.split(" ", num_expected_parts - 1)
        if len(parts) < num_expected_parts:
            self.client.add_message(
                usage_message, self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return None
        return parts

    def process_user_command(self, line: str) -> bool:
        self._processing_depth += 1
        if self._processing_depth > 1: # Basic re-entrancy check
            # More sophisticated checks might involve checking the exact line or command type
            # to allow certain benign re-entrant calls if absolutely necessary.
            logger.error(f"RE-ENTRANCY DETECTED in process_user_command for line: '{line}'. Current depth: {self._processing_depth}. Aborting this call.")
            self._processing_depth -= 1
            return False # Indicate command was not processed due to re-entrancy

        try:
            if not line.startswith("/"):
                if self.client.context_manager.active_context_name:
                    self.client.handle_text_input(line)
                    return True
                else:
                    self.client.add_message(
                        "No active window to send message to.",
                        self.client.ui.colors["error"], context_name="Status",
                    )
                    return False

            command_parts = line[1:].split(" ", 1)
            cmd = command_parts[0].lower()
            args_str = command_parts[1] if len(command_parts) > 1 else ""

            logger.info(f"--- PROCESSING COMMAND (Depth: {self._processing_depth}) ---")
            logger.info(f"Raw line: '{line}'")
            logger.info(f"Parsed cmd: '{cmd}'")
            logger.info(f"Parsed args_str: '{args_str}'")

            is_in_map = cmd in self.command_map
            logger.info(f"Is '{cmd}' in command_map? {is_in_map}")
            if not is_in_map:
                map_keys_full_list = sorted(list(self.command_map.keys()))
                logger.debug(f"Full command_map keys for missing command '{cmd}': {map_keys_full_list}")

            if cmd in self.command_map:
                handler_func = self.command_map[cmd]
                logger.info(f"CommandHandler: Dispatching '{cmd}'. Handler: {getattr(handler_func, '__module__', 'N/A')}.{getattr(handler_func, '__name__', 'N/A')}")
                try:
                    handler_func(self.client, args_str)
                except Exception as e_handler:
                    logger.error(f"Error executing handler for command '{cmd}': {e_handler}", exc_info=True)
                    self.client.add_message(f"Error in command /{cmd}: {e_handler}", self.client.ui.colors["error"], context_name=self.client.context_manager.active_context_name or "Status")
                return True
            else:
                script_cmd_data = self.client.script_manager.get_script_command_handler_and_data(cmd)
                if script_cmd_data and callable(script_cmd_data.get("handler")):
                    script_handler = script_cmd_data["handler"]
                    event_data_for_script = {
                        "client_logic_ref": self.client, "raw_line": line, "command": cmd,
                        "args_str": args_str, "client_nick": self.client.nick,
                        "active_context_name": self.client.context_manager.active_context_name,
                        "script_name": script_cmd_data.get("script_name", "UnknownScript"),
                    }
                    try:
                        script_handler(args_str, event_data_for_script)
                    except Exception as e:
                        logger.error(f"Error executing script command '/{cmd}' from script '{script_cmd_data.get('script_name')}': {e}", exc_info=True)
                        self.client.add_message(f"Error in script command /{cmd}: {e}", self.client.ui.colors["error"],
                                                context_name=self.client.context_manager.active_context_name or "Status")
                    return True
                else:
                    logger.warning(f"CommandHandler: Command '{cmd}' NOT found in command_map AND not a known script command. Treating as unknown.")
                    self.client.add_message(f"Unknown command: {cmd}", self.client.ui.colors["error"],
                                            context_name=self.client.context_manager.active_context_name or "Status")
                    return True # Still True because we "handled" it as unknown
        finally:
            self._processing_depth -= 1
# END OF MODIFIED FILE: command_handler.py
