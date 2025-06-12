import logging
import importlib
import pkgutil # Import pkgutil
from typing import TYPE_CHECKING, List, Optional, Tuple, Dict, Callable, Any, Awaitable, Union
import asyncio # Import asyncio
import inspect # Import inspect to check for coroutines
import os # New import
import configparser # New import

# Import the commands package itself to access __path__ and __name__
import pyrc_core.commands

from pyrc_core.features.triggers.trigger_commands import TriggerCommands
from pyrc_core.context_manager import ChannelJoinStatus, Context

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    CommandHandlerCallable = Callable[["IRCClient_Logic", str], Awaitable[Any]]
    ScriptCommandHandlerCallable = Callable[[str, Dict[str, Any]], Awaitable[Any]] # This is for the script's handler
    # Type for the handler stored in CommandHandler's script_commands
    InternalScriptCommandHandlerCallable = Callable[..., Awaitable[Any]]


from pyrc_core.context_manager import Context as CTX_Type

logger = logging.getLogger("pyrc.command_handler")

HELP_INI_FILENAME = "command_help.ini"
# HELP_INI_PATH is now relative to pyrc_core's base_dir (which is self.client.base_dir)
HELP_INI_PATH = os.path.join("data", "default_help", HELP_INI_FILENAME)


class CommandHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic
        self.trigger_commands = TriggerCommands(client_logic)
        self.registered_command_help: Dict[str, Dict[str, Any]] = {} # For core commands
        self._processing_depth = 0 # For re-entrancy check

        self.command_map: Dict[str, Tuple[Callable, bool]] = { # For core commands
            "on": (self.trigger_commands.handle_on_command, False), # Assume sync for now, adjust if needed
        }

        # For script commands
        self.script_commands: Dict[str, Dict[str, Any]] = {}
        self.script_command_aliases: Dict[str, str] = {}

        # For INI help texts
        self.ini_help_texts: Dict[str, Dict[str, str]] = {}
        self._load_help_texts() # Load INI help texts first

        logger.info(f"Starting dynamic command loading using pkgutil from package: {pyrc_core.commands.__name__}")
        logger.info(f"pkgutil.walk_packages path: {pyrc_core.commands.__path__}, prefix: {pyrc_core.commands.__name__ + '.'}")

        for module_loader, module_name, is_pkg in pkgutil.walk_packages(
            path=pyrc_core.commands.__path__,  # Path to the commands package
            prefix=pyrc_core.commands.__name__ + '.',  # Prefix for full module names
            onerror=lambda x: logger.error(f"Error importing module during walk_packages: {x}")
        ):
            logger.debug(f"Discovered module: {module_name}, is_pkg: {is_pkg}")
            # If it's a package's __init__.py, skip it unless it explicitly defines commands
            if module_name.endswith('.__init__'):
                logger.debug(f"Skipping __init__.py module: {module_name}")
                continue

            # module_name is the full Python path to the module, e.g., 'pyrc_core.commands.core.help_command'
            python_module_name = module_name

            try:
                logger.debug(f"Attempting to import module: {python_module_name}")
                module = importlib.import_module(python_module_name)
                logger.debug(f"Successfully imported module: {python_module_name}")

                if hasattr(module, 'COMMAND_DEFINITIONS'):
                    logger.info(f"Found COMMAND_DEFINITIONS in {python_module_name}. Definitions: {getattr(module, 'COMMAND_DEFINITIONS')}")
                    # Add debug log to check if 'help' command is being processed
                    for cmd_def in module.COMMAND_DEFINITIONS:
                        cmd_name = cmd_def["name"].lower()
                        logger.debug(f"Checking command definition: {cmd_name} from {python_module_name}")
                        handler_name_str = cmd_def["handler"]
                        handler_func = getattr(module, handler_name_str, None)
                        is_async_handler = inspect.iscoroutinefunction(handler_func)
                        logger.debug(f"Processing command definition: name='{cmd_name}', handler='{handler_name_str}', is_async: {is_async_handler}")

                        if handler_func and callable(handler_func):
                            if cmd_name in self.command_map:
                                logger.warning(f"Command '{cmd_name}' from {python_module_name} conflicts with existing command. Overwriting.")
                            self.command_map[cmd_name] = (handler_func, is_async_handler)

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
                                    self.command_map[alias] = (handler_func, is_async_handler)
                                    self.registered_command_help[alias] = {
                                        "help_text": f"{help_info['usage']}\n  {help_info['description']}",
                                        "aliases": [cmd_name] + [a.lower() for a in help_info.get("aliases", []) if a.lower() != alias],
                                        "script_name": "core",
                                        "is_alias": True,
                                        "primary_command": cmd_name,
                                        "module_path": python_module_name
                                    }
                            logger.info(f"Registered command '{cmd_name}' (and aliases) from {python_module_name} handled by {handler_name_str}. Is async: {is_async_handler}.")
                        else:
                            logger.error(f"Could not find or call handler '{handler_name_str}' in {python_module_name} for command '{cmd_name}'.")
                else: # This else block was missing, causing "Module ... does not have COMMAND_DEFINITIONS." to be logged incorrectly
                    logger.debug(f"Module {python_module_name} does not have COMMAND_DEFINITIONS.")

            except ImportError as e:
                logger.error(f"Failed to import module {python_module_name}: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Error processing module {python_module_name}: {e}", exc_info=True)
        logger.info("Finished dynamic command loading.")

        self.command_primary_map = {} # For core commands
        seen_handlers = {} # For core commands
        for cmd_name, (handler_func, is_async) in self.command_map.items():
            if cmd_name in ["help", "h"]: # Assuming help is a core command
                continue

            if handler_func in seen_handlers:
                primary_name = seen_handlers[handler_func]
                self.command_primary_map[cmd_name] = primary_name
            else:
                seen_handlers[handler_func] = cmd_name

    def _load_help_texts(self):
        # Construct path from pyrc_core's directory (self.client.config.BASE_DIR)
        help_ini_full_path = os.path.join(self.client.config.BASE_DIR, HELP_INI_PATH)
        if not os.path.exists(help_ini_full_path):
            logger.warning(
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
            logger.info(
                f"Successfully loaded help texts from '{help_ini_full_path}'"
            )
        except Exception as e:
            logger.error(
                f"Error loading help texts from '{help_ini_full_path}': {e}",
                exc_info=True,
            )

    def get_help_text_for_command(self, command_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves help text for a given command, prioritizing sources.
        Order of priority:
        1. Core command definitions (from COMMAND_DEFINITIONS in modules)
        2. Script command definitions (registered by scripts)
        3. INI help texts (from command_help.ini)
        """
        cmd_name_lower = command_name.lower()

        # 1. Check core command definitions
        if cmd_name_lower in self.registered_command_help:
            help_data = self.registered_command_help[cmd_name_lower].copy()
            help_data["source"] = "core"
            return help_data

        # 2. Check script command definitions
        script_cmd_data = self.get_script_command_handler(cmd_name_lower)
        if script_cmd_data:
            # The help_info from script_cmd_data can be a string or a dict
            help_info = script_cmd_data.get("help_info")
            # Construct a unified help data dictionary
            help_data = {
                "help_info": help_info if isinstance(help_info, dict) else None,
                "help_text": help_info if isinstance(help_info, str) else None,
                "aliases": script_cmd_data.get("aliases", []),
                "script_name": script_cmd_data.get("script_name", "UnknownScript"),
                "is_alias": script_cmd_data.get("is_alias_call", False),
                "primary_command": script_cmd_data.get("primary_command", cmd_name_lower),
                "source": "script"
            }
            return help_data

        # 3. Check INI help texts
        # INI help texts are typically categorized by section (e.g., "core", "script_name")
        # We need to search all sections for the command.
        for section, commands_in_section in self.ini_help_texts.items():
            if cmd_name_lower in commands_in_section:
                return {
                    "help_text": commands_in_section[cmd_name_lower],
                    "source": "ini",
                    "script_name": section # Use section name as script_name for INI source
                }
        return None

    def get_all_commands_help(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns a dictionary of all registered commands and their help information.
        Keys are command names (lowercase), values are dictionaries containing
        help_text, aliases, script_name (or 'core'), and source ('core', 'script', 'ini').
        Aliases will point to their primary command's help.
        """
        all_help: Dict[str, Dict[str, Any]] = {}

        # 1. Add core commands
        for cmd_name, help_data in self.registered_command_help.items():
            if not help_data.get("is_alias"): # Only add primary commands here
                all_help[cmd_name] = help_data.copy()
                all_help[cmd_name]["source"] = "core"

        # 2. Add script commands
        for cmd_name, script_data in self.script_commands.items():
            # Ensure we don't overwrite a core command with a script command of the same name
            if cmd_name not in all_help:
                help_info = script_data.get("help_info")
                all_help[cmd_name] = {
                    "help_info": help_info if isinstance(help_info, dict) else None,
                    "help_text": help_info if isinstance(help_info, str) else None,
                    "aliases": script_data.get("aliases", []),
                    "script_name": script_data.get("script_name", "UnknownScript"),
                    "is_alias": False, # This is the primary script command
                    "source": "script"
                }

        # Add script aliases pointing to their primary command's help
        for alias, primary_cmd in self.script_command_aliases.items():
            if primary_cmd in all_help: # Ensure primary command exists
                # Create an alias entry that points to the primary command's help
                # This is a simplified entry, the help_command will fetch the full help via get_help_text_for_command
                all_help[alias] = {
                    "help_text": f"Alias for /{primary_cmd}",
                    "aliases": [primary_cmd],
                    "script_name": all_help[primary_cmd].get("script_name", "UnknownScript"),
                    "is_alias": True,
                    "primary_command": primary_cmd,
                    "source": "script"
                }

        # 3. Add INI help texts (only if no core or script command exists with the same name)
        for section, commands_in_section in self.ini_help_texts.items():
            for cmd_name, help_text in commands_in_section.items():
                if cmd_name not in all_help:
                    all_help[cmd_name] = {
                        "help_text": help_text,
                        "aliases": [], # INI doesn't define aliases directly for commands
                        "script_name": section, # Use section name as script_name for INI source
                        "is_alias": False,
                        "source": "ini"
                    }
        return all_help

    def register_script_command(
        self,
        command_name: str,
        handler: Callable, # Changed to generic Callable
        help_info: Union[str, Dict[str, Any]],
        aliases: Optional[List[str]] = None,
        script_name: Optional[str] = None,
    ) -> None:
        """Register a command from a script."""
        if aliases is None:
            aliases = []
        if script_name is None:
            script_name = "UnknownScript" # Fallback

        cmd_name_lower = command_name.lower()

        if cmd_name_lower in self.command_map or cmd_name_lower in self.script_commands:
            logger.warning(f"Script command '{cmd_name_lower}' from script '{script_name}' conflicts with an existing core or script command. Overwriting.")

        # Ensure handler is callable
        if not callable(handler):
            logger.error(f"Handler for script command '{cmd_name_lower}' from script '{script_name}' is not callable. Command not registered.")
            return

        self.script_commands[cmd_name_lower] = {
            "handler": handler,
            "help_info": help_info,
            "aliases": [alias.lower() for alias in aliases],
            "script_name": script_name,
            "is_async": inspect.iscoroutinefunction(handler), # Store if handler is async
        }

        for alias in aliases:
            alias_lower = alias.lower()
            if alias_lower in self.command_map or alias_lower in self.script_commands or alias_lower in self.script_command_aliases:
                 logger.warning(f"Alias '{alias_lower}' for script command '{cmd_name_lower}' (script: {script_name}) conflicts with an existing command or alias. Overwriting.")
            self.script_command_aliases[alias_lower] = cmd_name_lower

        logger.info(
            f"Script '{script_name}' registered command: /{cmd_name_lower} (aliases: {aliases})"
        )

    def get_script_command_handler(self, command_name: str) -> Optional[Dict[str, Any]]:
        """Retrieves script command handler and its data."""
        cmd_name_lower = command_name.lower()
        if cmd_name_lower in self.script_commands:
            return self.script_commands[cmd_name_lower]
        elif cmd_name_lower in self.script_command_aliases:
            primary_cmd_name = self.script_command_aliases[cmd_name_lower]
            if primary_cmd_name in self.script_commands:
                # Return a copy of the data, but indicate it's an alias call
                data = self.script_commands[primary_cmd_name].copy()
                data["is_alias_call"] = True
                data["called_as"] = cmd_name_lower
                return data
        return None


    def get_available_commands_for_tab_complete(self) -> List[str]:
        cmds = set()
        # Core commands and their aliases
        for cmd_name in self.command_map.keys():
            cmds.add("/" + cmd_name)

        # Script commands and their aliases
        for cmd_name in self.script_commands.keys():
            cmds.add("/" + cmd_name)
        for alias_name in self.script_command_aliases.keys():
            cmds.add("/" + alias_name)

        return sorted(list(cmds))

    async def _ensure_args(
        self, args_str: str, usage_message: str, num_expected_parts: int = 1
    ) -> Optional[List[str]]:
        stripped_args_str = args_str.strip()

        if num_expected_parts == 0:
            return [] if not stripped_args_str else [stripped_args_str]

        if not stripped_args_str:
            await self.client.add_message(
                usage_message, self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return None

        if num_expected_parts == 1:
            return [stripped_args_str]

        parts = stripped_args_str.split(" ", num_expected_parts - 1)
        if len(parts) < num_expected_parts:
            await self.client.add_message(
                usage_message, self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return None
        return parts

    async def process_user_command(self, line: str) -> bool:
        self._processing_depth += 1
        if self._processing_depth > 1:
            logger.error(f"RE-ENTRANCY DETECTED in process_user_command for line: '{line}'. Current depth: {self._processing_depth}. Aborting this call.")
            self._processing_depth -= 1
            return False

        try:
            if not line.startswith("/"):
                active_context_name = self.client.context_manager.active_context_name
                if active_context_name:
                    # Send message to the active context (channel or query)
                    await self.client.network_handler.send_raw(f"PRIVMSG {active_context_name} :{line}")
                    # Also add the message to the local UI for display, formatted with nick
                    client_nick = self.client.nick or "Me" # Fallback to "Me" if nick is somehow None
                    formatted_line = f"<{client_nick}> {line}"
                    await self.client.add_message(
                        formatted_line,
                        self.client.ui.colors.get("my_message", 0), # Use my_message color for sent messages
                        context_name=active_context_name # This is safe due to the 'if active_context_name:' check
                    )
                    return True
                else: # Corrected indentation: this else corresponds to 'if active_context_name:'
                    await self.client.add_message(
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
                handler_func, is_async_handler = self.command_map[cmd]
                logger.info(f"CommandHandler: Dispatching '{cmd}'. Handler: {getattr(handler_func, '__module__', 'N/A')}.{getattr(handler_func, '__name__', 'N/A')}. Is async: {is_async_handler}")
                try:
                    if is_async_handler:
                        await handler_func(self.client, args_str)
                    else:
                        if self.client._executor: # Run sync handlers in executor
                            await asyncio.to_thread(handler_func, self.client, args_str)
                        else:
                            logger.error("Executor not available for synchronous command handler.")
                            await self.client.add_message(f"Error: Executor not available for command /{cmd}.", self.client.ui.colors["error"], context_name="Status")
                            return False
                except Exception as e_handler:
                    logger.error(f"Error executing handler for command '{cmd}': {e_handler}", exc_info=True)
                    await self.client.add_message(f"Error in command /{cmd}: {e_handler}", self.client.ui.colors["error"], context_name=self.client.context_manager.active_context_name or "Status")
                return True
            else: # Not a core command, check script commands
                script_cmd_data = self.get_script_command_handler(cmd) # Use new method
                if script_cmd_data and callable(script_cmd_data.get("handler")):
                    script_handler: Callable = script_cmd_data["handler"] # Changed to generic Callable
                    # is_script_handler_async = inspect.iscoroutinefunction(script_handler)
                    # The 'is_async' flag is now stored in script_cmd_data
                    is_script_handler_async = script_cmd_data.get("is_async", False)

                    # Prepare event_data for the script handler
                    # This structure should match what ScriptAPIHandler's command handlers expect
                    event_data_for_script = {
                        "client_logic_ref": self.client, # The ScriptAPIHandler will provide its own 'api'
                        "raw_line": line,
                        "command": cmd, # The command called (could be an alias)
                        "args_str": args_str,
                        "client_nick": (lambda:
                            (conn_info := self.client.state_manager.get_connection_info()) and
                            hasattr(conn_info, 'nick') and
                            conn_info.nick or "unknown")(),
                        "active_context_name": self.client.context_manager.active_context_name,
                        "script_name": script_cmd_data.get("script_name", "UnknownScript"),
                        # Potentially add primary command name if called via alias
                        "primary_command_name": self.script_command_aliases.get(cmd, cmd)
                    }
                    logger.info(f"CommandHandler: Dispatching script command '{cmd}'. Handler from script: '{script_cmd_data.get('script_name')}'. Is async: {is_script_handler_async}")
                    try:
                        if is_script_handler_async:
                            await script_handler(args_str, event_data_for_script)
                        else:
                            if self.client._executor:
                                await asyncio.to_thread(script_handler, args_str, event_data_for_script)
                            else:
                                logger.error(f"Executor not available for synchronous script command handler for /{cmd}.")
                                await self.client.add_message(f"Error: Executor not available for script command /{cmd}.", self.client.ui.colors["error"], context_name="Status")
                                return False
                    except Exception as e:
                        logger.error(f"Error executing script command '/{cmd}' from script '{script_cmd_data.get('script_name')}': {e}", exc_info=True)
                        await self.client.add_message(f"Error in script command /{cmd}: {e}", self.client.ui.colors["error"],
                                                context_name=self.client.context_manager.active_context_name or "Status")
                    return True
                else:
                    logger.warning(f"CommandHandler: Command '{cmd}' NOT found in core command_map OR script_commands. Treating as unknown.")
                    await self.client.add_message(f"Unknown command: {cmd}", self.client.ui.colors["error"],
                                            context_name=self.client.context_manager.active_context_name or "Status")
                    return True
        finally:
            self._processing_depth -= 1
