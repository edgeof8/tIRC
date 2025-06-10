import os
from typing import TYPE_CHECKING, List, Optional, Tuple, Dict, Any, Set

if TYPE_CHECKING:
    from pyrc_core.scripting.script_api_handler import ScriptAPIHandler


class ScriptBase:
    """Base class for all PyRC scripts.

    This class provides common functionality and interface that all scripts should implement.
    Scripts should inherit from this class and override the load() and unload() methods as needed.
    """

    def __init__(self, api: "ScriptAPIHandler"):
        """Initialize the script with the API handler.

        Args:
            api: The ScriptAPIHandler instance for this script
        """
        self.api = api
        # Get the script name from the API handler
        self.script_name = api.script_name

    def create_command_help(
        self, usage: str, description: str, aliases: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Helper method to create a structured help dictionary for commands.

        Args:
            usage: The command usage string (e.g., "/command <args>")
            description: A detailed description of what the command does
            aliases: Optional list of command aliases

        Returns:
            Dict[str, Any]: A dictionary with usage, description, and optional aliases
        """
        help_data: Dict[str, Any] = {"usage": usage, "description": description}
        if aliases:
            help_data["aliases"] = aliases
        return help_data

    def load(self):
        """Called when the script is loaded. Override this method to perform initialization.

        This is where you should:
        - Register commands
        - Subscribe to events
        - Load configuration
        - Initialize any script-specific state
        """
        pass

    def unload(self):
        """Called when the script is unloaded. Override this method to perform cleanup.

        This is where you should:
        - Clean up any resources
        - Save any pending state
        - Unsubscribe from events
        """
        pass

    def get_script_data_dir(self) -> str:
        """Returns the path to this script's dedicated data directory.

        Example: if script is 'my_script.py', returns '<project_root>/scripts/data/my_script/'

        Returns:
            str: The absolute path to the script's data directory

        Note:
            The directory will be created if it doesn't exist.
            This is handled by ScriptManager.get_data_file_path_for_script().
        """
        # To get the script's data directory, we call get_data_file_path_for_script
        # from the ScriptManager via the API, passing an empty string for the data_filename.
        # This returns the path to the script's specific data directory.
        data_dir_path = self.api.script_manager.get_data_file_path_for_script(
            self.api.script_name,
            "",  # Pass empty filename to get the directory path
        )
        return data_dir_path

    def load_list_from_data_file(self, filename: str, default_items: list) -> list:
        """Load a list of items from a data file or return default items if file not found/empty.

        Args:
            filename: The name of the data file to load
            default_items: List of default items to return if file not found/empty

        Returns:
            list: The loaded items or default_items if file not found/empty
        """
        items = []
        try:
            file_path = self.api.request_data_file_path(filename)
            if not os.path.exists(file_path):
                self.api.log_warning(
                    f"Data file '{filename}' not found at '{file_path}'. Using default items."
                )
                return default_items.copy()

            with open(file_path, "r", encoding="utf-8") as f:
                items = [line.strip() for line in f if line.strip()]

            if not items:
                self.api.log_warning(
                    f"Data file '{filename}' is empty. Using default items."
                )
                return default_items.copy()

            self.api.log_info(
                f"Successfully loaded {len(items)} items from '{filename}'."
            )
            return items
        except Exception as e:
            self.api.log_error(
                f"Error loading data file '{filename}': {e}. Using default items."
            )
            return default_items.copy()

    def get_enabled_caps(self) -> Set[str]:
        """Get the set of currently enabled capabilities from the cap negotiator.

        Returns:
            Set[str]: Set of enabled capability names, or empty set if CAP not supported/initialized
        """
        if hasattr(self.api.client_logic, 'cap_negotiator') and self.api.client_logic.cap_negotiator:
            return self.api.client_logic.cap_negotiator.get_enabled_caps()
        return set()

    async def ensure_command_args(
        self, args_str: str, command_name: str, num_expected_parts: int = 1
    ) -> Optional[List[str]]:
        """Helper method to validate command arguments and display usage message if needed.

        Args:
            args_str: The raw arguments string from the command
            command_name: The name of the command (used to fetch help text)
            num_expected_parts: The number of space-separated parts expected in args_str

        Returns:
            Optional[List[str]]: List of argument parts if valid, None if invalid
        """
        # Get help text for the command
        help_data = self.api.script_manager.get_help_text_for_command(command_name)
        usage_msg = (
            help_data.get("help_text", f"Usage: /{command_name}")
            if help_data
            else f"Usage: /{command_name}"
        )

        # Split args and check count
        parts = args_str.strip().split()
        if len(parts) < num_expected_parts:
            await self.api.add_message_to_context(
                self.api.get_current_context_name() or "Status", usage_msg, "error"
            )
            return None

        return parts
