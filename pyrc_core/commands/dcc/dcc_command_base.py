import argparse
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Type, Callable

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc.base")

class DCCCommandResult:
    """Represents the outcome of a DCC command execution."""
    def __init__(self, success: bool, message: str, **kwargs):
        self.success = success
        self.message = message
        self.data = kwargs

    def __bool__(self):
        return self.success

    def __repr__(self):
        return f"DCCCommandResult(success={self.success}, message='{self.message}', data={self.data})"

class DCCCommandHandler(ABC):
    """
    Abstract base class for all DCC subcommand handlers.
    Provides common functionality and enforces a standard interface.
    """
    command_name: str = ""
    command_aliases: List[str] = []
    command_help: Dict[str, str] = {
        "usage": "",
        "description": "",
        "aliases": ""
    }

    def __init__(self, client_logic: 'IRCClient_Logic'):
        self.client_logic = client_logic
        self.dcc_m = client_logic.dcc_manager
        self.active_context_name = client_logic.context_manager.active_context_name or "Status"
        self.dcc_context_name = "DCC"

    @abstractmethod
    def execute(self, cmd_args: List[str]):
        """
        Executes the specific DCC subcommand logic.
        Must be implemented by subclasses.
        """
        pass

    def check_dcc_available(self, subcommand_name: str = "DCC"):
        """Checks if the DCC system is initialized and enabled."""
        if not self.dcc_m:
            self.client_logic.add_message(f"{subcommand_name} system not available.", "error", context_name=self.active_context_name)
            return False
        if not self.dcc_m.dcc_config.get("enabled"):
            self.client_logic.add_message(f"{subcommand_name} is currently disabled in the configuration.", "error", context_name=self.active_context_name)
            return False
        return True

    def ensure_dcc_context(self):
        """Switches the active context to 'DCC' if not already there."""
        if self.client_logic.context_manager.active_context_name != self.dcc_context_name:
            self.client_logic.switch_active_context(self.dcc_context_name)

    def handle_error(self, message: str, log_level: int = logging.ERROR, exc_info: bool = False, context_name: Optional[str] = None):
        """Handles and logs an error, adding it to the client messages."""
        if context_name is None:
            context_name = self.active_context_name
        logger.log(log_level, message, exc_info=exc_info)
        self.client_logic.add_message(message, "error", context_name=context_name)

class DCCCommandRegistry:
    """
    Manages the registration and retrieval of DCC subcommand handlers.
    """
    def __init__(self):
        self._commands: Dict[str, Type[DCCCommandHandler]] = {}
        self._aliases: Dict[str, str] = {}

    def register_command(self, handler_class: Type[DCCCommandHandler]):
        """Registers a DCC command handler class."""
        if not issubclass(handler_class, DCCCommandHandler):
            raise ValueError("Handler class must inherit from DCCCommandHandler")

        cmd_name = handler_class.command_name.lower()
        if not cmd_name:
            logger.warning(f"Skipping registration of {handler_class.__name__}: command_name not set.")
            return

        if cmd_name in self._commands:
            logger.warning(f"DCC Command '{cmd_name}' already registered. Overwriting with {handler_class.__name__}.")
        self._commands[cmd_name] = handler_class
        logger.debug(f"Registered DCC command: {cmd_name} with handler {handler_class.__name__}")

        for alias in handler_class.command_aliases:
            alias_lower = alias.lower()
            if alias_lower in self._aliases and self._aliases[alias_lower] != cmd_name:
                logger.warning(f"DCC Command alias '{alias_lower}' already points to '{self._aliases[alias_lower]}'. Overwriting to point to '{cmd_name}'.")
            self._aliases[alias_lower] = cmd_name
            logger.debug(f"Registered DCC command alias: {alias_lower} -> {cmd_name}")

    def get_handler_class(self, subcommand: str) -> Optional[Type[DCCCommandHandler]]:
        """Retrieves a handler class for a given subcommand or alias."""
        subcommand_lower = subcommand.lower()
        if subcommand_lower in self._commands:
            return self._commands[subcommand_lower]
        if subcommand_lower in self._aliases:
            return self._commands.get(self._aliases[subcommand_lower])
        return None

    def get_all_command_names(self) -> List[str]:
        """Returns a list of all registered command names."""
        return sorted(list(self._commands.keys()))

    def get_command_help(self, subcommand: str) -> Optional[Dict[str, str]]:
        """Retrieves help information for a specific subcommand."""
        handler_class = self.get_handler_class(subcommand)
        if handler_class:
            return handler_class.command_help
        return None

# Global registry instance
dcc_command_registry = DCCCommandRegistry()

# Example of how to register commands (will be done in dcc_commands.py or similar entry point)
# from .dcc_send_command import DCCSendCommandHandler
# dcc_command_registry.register_command(DCCSendCommandHandler)
