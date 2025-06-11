# START OF MODIFIED FILE: script_manager.py
import os
import importlib.util
import logging
import configparser
import time
import sys
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Any, Set, Tuple, Union
import threading
from pyrc_core.app_config import AppConfig

from pyrc_core.scripting.script_api_handler import ScriptAPIHandler

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic


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

        self.event_subscriptions: Dict[str, List[Dict[str, Any]]] = {}
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

        # Initialization for dependency resolution
        scripts_metadata: Dict[str, List[str]] = {}  # script_name -> list_of_dependency_names
        script_load_candidates: List[str] = []  # script_names that are valid files and not disabled

        # Pass 1: Collect Metadata and Initial Candidates
        self.logger.info("Pass 1: Collecting script metadata for dependency resolution.")
        for script_file in os.listdir(self.scripts_dir):
            if script_file.endswith(".py") and not script_file.startswith("__"):
                script_name = script_file[:-3]

                if script_name in self.disabled_scripts:
                    self.logger.info(f"Skipping disabled script '{script_name}' during metadata collection.")
                    continue

                try:
                    # Temporarily create ScriptAPIHandler to load metadata
                    # This relies on ScriptAPIHandler's __init__ calling _load_metadata
                    temp_api = ScriptAPIHandler(self.client_logic_ref, self, script_name)  # type: ignore[arg-type]
                    dependencies = temp_api.metadata.dependencies
                    scripts_metadata[script_name] = dependencies
                    script_load_candidates.append(script_name)
                    self.logger.debug(f"Script '{script_name}' metadata collected. Dependencies: {dependencies}")
                except Exception as e:
                    self.logger.error(f"Failed to collect metadata for script '{script_name}': {e}. This script or its dependents may not be loaded.", exc_info=True)
                    # Do not add to script_load_candidates if metadata collection fails

        # Pass 2: Iterative Dependency Resolution and Loading
        self.logger.info("Pass 2: Resolving dependencies and loading scripts.")
        loaded_script_names: Set[str] = set()
        scripts_to_attempt_load: List[str] = list(script_load_candidates)

        # Safety break for complex cases or circular dependencies
        max_iterations = len(scripts_to_attempt_load) + 5
        iterations = 0
        made_progress_in_iteration = True

        while scripts_to_attempt_load and iterations < max_iterations and made_progress_in_iteration:
            made_progress_in_iteration = False
            iterations += 1
            still_pending_this_round: List[str] = []

            for script_name in scripts_to_attempt_load:
                dependencies = scripts_metadata.get(script_name, [])
                deps_met = True
                missing_deps_for_log = []

                for dep_name in dependencies:
                    if dep_name not in loaded_script_names:
                        # Check if the dependency is a known script or explicitly disabled
                        if dep_name not in scripts_metadata and dep_name not in self.disabled_scripts:
                            self.logger.error(f"Script '{script_name}' has an unknown dependency '{dep_name}'. Cannot load '{script_name}'.")
                            deps_met = False
                            missing_deps_for_log.append(f"{dep_name} (unknown)")
                            break  # Hard failure, cannot proceed with this script
                        elif dep_name in self.disabled_scripts:
                            self.logger.warning(f"Script '{script_name}' depends on disabled script '{dep_name}'. Cannot load '{script_name}'.")
                            deps_met = False
                            missing_deps_for_log.append(f"{dep_name} (disabled)")
                            break  # Hard failure, cannot proceed with this script
                        else:
                            # Dependency exists but is not yet loaded
                            deps_met = False
                            missing_deps_for_log.append(f"{dep_name} (pending)")
                            # No break here, continue to check other deps for this script

                if deps_met:
                    # Actual script loading logic (moved from original loop)
                    try:
                        script_module = importlib.import_module(f"scripts.{script_name}")
                        api_handler = ScriptAPIHandler(self.client_logic_ref, self, script_name)  # type: ignore[arg-type]

                        # Double check dependencies using the actual API handler now that deps should be loaded
                        satisfied, missing_runtime_deps = api_handler.check_dependencies()
                        if not satisfied:
                            self.logger.error(f"Runtime dependency check failed for '{script_name}': Missing {missing_runtime_deps}. Skipping load.")
                            still_pending_this_round.append(script_name)  # Put back for next round, maybe its dep will load
                            continue

                        if hasattr(script_module, "get_script_instance"):
                            script_instance = script_module.get_script_instance(api_handler)
                            if script_instance:
                                self.scripts[script_name] = script_instance
                                if hasattr(script_instance, "load") and callable(script_instance.load):
                                    script_instance.load()
                                self.logger.info(f"Successfully loaded and initialized script (deps met): {script_name}")
                                loaded_script_names.add(script_name)
                                made_progress_in_iteration = True
                            else:
                                self.logger.warning(f"Script {script_name} get_script_instance returned None. Skipping load.")
                        else:
                            self.logger.warning(f"Script {script_name} has no get_script_instance function. Skipping load.")
                    except Exception as e:
                        self.logger.error(f"Failed to load script {script_name} (even with deps met): {e}", exc_info=True)
                else:
                    # Script's dependencies are not yet met, keep it for the next round
                    still_pending_this_round.append(script_name)
                    if missing_deps_for_log:
                        self.logger.debug(f"Script '{script_name}' still pending due to missing dependencies: {', '.join(missing_deps_for_log)}")

            scripts_to_attempt_load = still_pending_this_round

        # Post-Loop Check
        if scripts_to_attempt_load:
            unloaded_scripts_details = []
            for script_name in scripts_to_attempt_load:
                dependencies = scripts_metadata.get(script_name, [])
                missing_deps = [
                    dep for dep in dependencies
                    if dep not in loaded_script_names and dep not in self.disabled_scripts
                ]
                status = ""
                if script_name in self.disabled_scripts:
                    status = " (disabled)"
                elif script_name not in scripts_metadata:
                    status = " (metadata collection failed)"
                elif missing_deps:
                    status = f" (missing: {', '.join(missing_deps)})"
                else:
                    status = " (likely circular dependency or internal error)"
                unloaded_scripts_details.append(f"'{script_name}'{status}")

            self.logger.error(f"Could not load some scripts due to missing, disabled, or circular dependencies: {'; '.join(unloaded_scripts_details)}")

    def get_script(self, script_name: str) -> Optional[Any]:
        if script_name in self.disabled_scripts:
            self.logger.debug(f"Script {script_name} is disabled")
            return None
        return self.scripts.get(script_name)

    def is_script_enabled(self, script_name: str) -> bool:
        return script_name not in self.disabled_scripts and script_name in self.scripts


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

    async def dispatch_event(
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
                    await self.client_logic_ref.add_message(
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
                        self.client_logic_ref, self, script_name  # type: ignore[arg-type]
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

                module_to_reload = sys.modules[f"scripts.{script_name}"]
                reloaded_module = importlib.reload(module_to_reload)

                if hasattr(reloaded_module, "get_script_instance"):
                    api_handler = ScriptAPIHandler(
                        self.client_logic_ref, self, script_name  # type: ignore[arg-type]
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


# END OF MODIFIED FILE: script_manager.py
