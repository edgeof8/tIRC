import os
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from script_manager import ScriptAPIHandler


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
        # self.api is an instance of ScriptAPIHandler
        # self.api.script_module_name is the name of the script (e.g., "default_random_messages")
        # self.api.script_manager is the ScriptManager instance
        # self.api.script_manager.get_data_file_path_for_script(script_module_name, data_filename)
        #   returns <scripts_dir>/data/<script_module_name>/<data_filename>

        # To get just the directory, we pass an empty string for data_filename
        # and then remove any trailing separator if present.
        path_with_dummy_file = self.api.script_manager.get_data_file_path_for_script(
            self.api.script_module_name,
            "",  # Pass empty filename to get the directory path
        )
        # get_data_file_path_for_script currently creates the dir <scripts_dir>/data/<script_module_name>
        # and returns os.path.join(data_dir, data_filename).
        # So, if data_filename is "", it returns <scripts_dir>/data/<script_module_name>
        # This is already the directory path.
        return path_with_dummy_file

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

    def ensure_command_args(
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
            self.api.add_message_to_context(
                self.api.get_current_context_name() or "Status", usage_msg, "error"
            )
            return None

        return parts
