import os
from typing import TYPE_CHECKING

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
