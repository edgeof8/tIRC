# tirc_core/scripting/script_api_handler.py
import logging
import os
import json
from typing import TYPE_CHECKING, List, Optional, Dict, Any, Callable, Union, Set, Tuple # Added Tuple
import asyncio # Import asyncio
from dataclasses import asdict # Added asdict
from tirc_core.scripting.python_trigger_api import PythonTriggerAPI # Added PythonTriggerAPI

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.script_manager import ScriptManager
    from tirc_core.state_manager import ConnectionState # Import ConnectionState

# Define ScriptMetadata type alias for clarity
ScriptMetadata = Dict[str, Any]

class ScriptAPIHandler:
    def __init__(
        self,
        client_logic_ref: "IRCClient_Logic",
        script_manager_ref: "ScriptManager",
        script_name: str,
    ):
        self.client_logic = client_logic_ref
        self.script_manager = script_manager_ref
        self.script_name = script_name # Store the script name
        self.logger = logging.getLogger(f"tirc.script_api.{script_name}") # Keep logger name for now
        self.metadata: ScriptMetadata = self._load_metadata()

    def _load_metadata(self) -> ScriptMetadata:
        """Loads script metadata from script_metadata.json in the script's directory."""
        metadata_file_path = os.path.join(self.get_script_dir(), "script_metadata.json")
        default_metadata: ScriptMetadata = {
            "name": self.script_name,
            "version": "0.0.0",
            "description": "No description provided.",
            "author": "Unknown",
            "dependencies": [],
            "min_tirc_version": "0.0.0", # Changed from min_pyrc_version
            "is_enabled_by_default": True,
        }
        if os.path.exists(metadata_file_path):
            try:
                with open(metadata_file_path, "r", encoding="utf-8") as f:
                    loaded_meta = json.load(f)
                    # Merge with defaults, ensuring all keys are present
                    merged_meta = {**default_metadata, **loaded_meta}
                    # Ensure dependencies is always a list
                    if not isinstance(merged_meta.get("dependencies"), list):
                        self.logger.warning(f"Script '{self.script_name}' metadata 'dependencies' is not a list. Defaulting to empty list.")
                        merged_meta["dependencies"] = []
                    return merged_meta
            except json.JSONDecodeError as e:
                logging.getLogger("tirc.script_metadata").error(
                    f"Error loading metadata from {metadata_file_path}: {e}"
                )
            except Exception as e:
                 logging.getLogger("tirc.script_metadata").error(
                    f"Unexpected error loading metadata from {metadata_file_path}: {e}"
                )
        return default_metadata

    def _save_metadata(self) -> None:
        """Saves current script metadata to script_metadata.json."""
        metadata_file_path = os.path.join(self.get_script_dir(), "script_metadata.json")
        try:
            os.makedirs(os.path.dirname(metadata_file_path), exist_ok=True)
            with open(metadata_file_path, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, indent=4)
        except Exception as e:
            logging.getLogger("tirc.script_metadata").error(
                f"Error saving metadata to {metadata_file_path}: {e}"
            )

    def check_dependencies(self) -> Tuple[bool, List[str]]:
        """Checks if all declared script dependencies are loaded and enabled."""
        dependencies = self.metadata.get("dependencies", [])
        if not dependencies:
            return True, []

        missing_or_disabled_deps = []
        for dep_name in dependencies:
            if not self.script_manager.is_script_enabled(dep_name):
                missing_or_disabled_deps.append(dep_name)

        if missing_or_disabled_deps:
            self.logger.warning(
                f"Script '{self.script_name}' has unmet dependencies: {', '.join(missing_or_disabled_deps)}"
            )
            return False, missing_or_disabled_deps
        return True, []


    # --- Logging ---
    def log_debug(self, message: str): self.logger.debug(message)
    def log_info(self, message: str): self.logger.info(message)
    def log_warning(self, message: str): self.logger.warning(message)
    def log_error(self, message: str, exc_info: bool = False): self.logger.error(message, exc_info=exc_info)
    def log_critical(self, message: str, exc_info: bool = False): self.logger.critical(message, exc_info=exc_info)

    # --- Command Registration ---
    def register_command(
        self,
        name: str,
        handler: Callable, # Changed to generic Callable
        help_info: Union[str, Dict[str, Any]], # help_info can be str or dict
        aliases: Optional[List[str]] = None,
    ) -> None:
        self.client_logic.command_handler.register_script_command(
            name, handler, help_info, aliases or [], script_name=self.script_name
        )

    def unregister_command(self, name: str) -> None:
        # This needs to be implemented in CommandHandler
        # For now, scripts might not be able to unregister commands dynamically post-load
        # Or, ScriptManager handles this during script unload.
        self.logger.warning(f"Unregistering command '{name}' from API is not fully implemented yet in CommandHandler.")
        # Placeholder: self.client_logic.command_handler.unregister_script_command(name, self.script_name)

    # --- Event Handling ---
    def subscribe_to_event(self, event_name: str, handler_function: Callable) -> None:
        self.client_logic.event_manager.subscribe(event_name.upper(), handler_function, self.script_name)

    def unsubscribe_from_event(self, event_name: str, handler_function: Callable) -> None:
        self.client_logic.event_manager.unsubscribe(event_name.upper(), handler_function, self.script_name)

    # --- Client Interaction ---
    async def send_raw(self, data: str) -> None:
        await self.client_logic.network_handler.send_raw(data)

    async def send_message(self, target: str, message: str) -> None:
        await self.client_logic.network_handler.send_raw(f"PRIVMSG {target} :{message}")

    async def send_action(self, target: str, action_text: str) -> None:
        await self.send_ctcp_privmsg(target, f"ACTION {action_text}")

    async def send_notice(self, target: str, message: str) -> None:
        await self.client_logic.network_handler.send_raw(f"NOTICE {target} :{message}")

    async def send_ctcp_privmsg(self, target: str, ctcp_message: str) -> None:
        await self.client_logic.send_ctcp_privmsg(target, ctcp_message)

    async def join_channel(self, channel_name: str, key: Optional[str] = None) -> None:
        if key:
            await self.client_logic.network_handler.send_raw(f"JOIN {channel_name} {key}")
        else:
            await self.client_logic.network_handler.send_raw(f"JOIN {channel_name}")

    async def part_channel(self, channel_name: str, reason: Optional[str] = None) -> None:
        if reason:
            await self.client_logic.network_handler.send_raw(f"PART {channel_name} :{reason}")
        else:
            await self.client_logic.network_handler.send_raw(f"PART {channel_name}")

    async def set_nick(self, new_nick: str) -> None:
        await self.client_logic.network_handler.send_raw(f"NICK {new_nick}")

    async def execute_client_command(self, command_line: str) -> None:
        """Executes a client command as if the user typed it."""
        # Ensure command_handler.process_user_command is awaitable if it does async work
        await self.client_logic.command_handler.process_user_command(command_line)


    # --- UI Interaction ---
    async def add_message_to_context(
        self,
        context_name: str,
        text: str,
        color_key: str = "system", # Use color key, UIManager resolves to pair_id
        prefix_time: bool = False,
        source_full_ident: Optional[str] = None,
        is_privmsg_or_notice: bool = False,
        **kwargs # Allow other kwargs to be passed through
    ) -> None:
        # Get the color pair ID from UIManager using the color_key
        color_pair_id = self.client_logic.ui.colors.get(color_key, self.client_logic.ui.colors.get("system", 0))

        await self.client_logic.add_message(
            text,
            color_pair_id, # Pass the resolved pair_id
            context_name,
            prefix_time,
            source_full_ident=source_full_ident,
            is_privmsg_or_notice=is_privmsg_or_notice,
            **kwargs # Pass through other kwargs
        )

    # --- Information Retrieval ---
    def get_client_nick(self) -> Optional[str]:
        conn_info = self.client_logic.state_manager.get_connection_info()
        return conn_info.nick if conn_info else None

    def get_current_context_name(self) -> Optional[str]:
        return self.client_logic.context_manager.active_context_name

    def get_context_messages(self, context_name: str, count: Optional[int] = None) -> List[Tuple[str, Any]]:
        """Retrieves messages from a context. Returns list of (text, color_pair_id) tuples."""
        messages_raw = self.client_logic.context_manager.get_context_messages_raw(context_name, count=count)
        return messages_raw if messages_raw is not None else []


    def get_client_state(self, key: str, default: Optional[Any] = None) -> Any:
        return self.client_logic.state_manager.get(key, default)

    def get_connection_state(self) -> Optional[str]: # Returns ConnectionState enum name
        """Returns the current connection state as a string (enum name)."""
        state_enum = self.client_logic.state_manager.get_connection_state()
        return state_enum.name if state_enum else None

    def get_connection_info(self) -> Optional[Dict[str, Any]]: # Returns dict representation
        """Returns the current ConnectionInfo as a dictionary, or None."""
        conn_info_obj = self.client_logic.state_manager.get_connection_info()
        return asdict(conn_info_obj) if conn_info_obj else None

    def get_joined_channels(self) -> Set[str]:
        """Returns a set of currently joined channel names."""
        conn_info = self.client_logic.state_manager.get_connection_info()
        return conn_info.currently_joined_channels.copy() if conn_info else set()

    def get_context_info(self, context_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves information about a specific context.
        Returns a dictionary with keys like 'name', 'type', 'topic', 'users', 'join_status', etc.
        """
        context = self.client_logic.context_manager.get_context(context_name)
        if not context:
            return None
        return {
            "name": context.name,
            "type": context.type,
            "topic": context.topic,
            "users": context.users.copy(), # Return a copy
            "user_prefixes": context.user_prefixes.copy(), # Return a copy
            "modes": list(context.modes), # Return a copy
            "unread_count": context.unread_count,
            "join_status": context.join_status.name if context.join_status else None,
        }


    # --- Script Data Management ---
    def get_script_dir(self) -> str:
        """Returns the absolute path to the directory where the current script file is located."""
        # This assumes scripts are in <base_dir>/scripts/<script_name>.py
        # or <base_dir>/scripts/<script_name_as_dir>/<main_module>.py
        # For simplicity, let's assume script_name is the file name without .py
        # and it's directly in the scripts_dir.
        # If scripts can be in subdirectories, this needs adjustment.
        return os.path.join(self.script_manager.scripts_dir, self.script_name.replace('.', os.sep))


    def request_data_file_path(self, data_filename: str) -> str:
        """
        Requests the full path for a data file specific to this script.
        The file will be located in <project_root>/scripts/data/<script_name>/<data_filename>.
        The directory is created if it doesn't exist.
        """
        return self.script_manager.get_data_file_path_for_script(self.script_name, data_filename)

    # --- Trigger Management (if TriggerManager is available) ---
    def add_trigger(self, event_type: str, pattern: str, action_type: str, action_content: str,
                    is_enabled: bool = True, is_regex: bool = True, ignore_case: bool = True,
                    created_by: Optional[str] = None, description: str = "") -> Optional[int]:
        if self.client_logic.trigger_manager:
            return self.client_logic.trigger_manager.add_trigger(
                event_type, pattern, action_type, action_content,
                is_enabled, is_regex, ignore_case,
                created_by or self.script_name, description
            )
        self.log_warning("Trigger system not enabled, cannot add trigger.")
        return None

    def remove_trigger(self, trigger_id: int) -> bool:
        if self.client_logic.trigger_manager:
            return self.client_logic.trigger_manager.remove_trigger(trigger_id)
        self.log_warning("Trigger system not enabled, cannot remove trigger.")
        return False

    def set_trigger_enabled(self, trigger_id: int, enabled: bool) -> bool:
        if self.client_logic.trigger_manager:
            return self.client_logic.trigger_manager.set_trigger_enabled(trigger_id, enabled)
        self.log_warning("Trigger system not enabled, cannot enable/disable trigger.")
        return False

    def list_triggers(self, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.client_logic.trigger_manager:
            return self.client_logic.trigger_manager.list_triggers(event_type)
        self.log_warning("Trigger system not enabled, cannot list triggers.")
        return []

    # --- DCC API (Simplified access to DCCManager methods) ---
    async def dcc_send_file(self, peer_nick: str, local_filepath: str, passive: bool = False) -> Optional[str]:
        """Initiates a DCC SEND file transfer. Returns transfer ID or None on failure."""
        if self.client_logic.dcc_manager:
            transfer_ids = await self.client_logic.dcc_manager.initiate_sends(
                peer_nick, [local_filepath], passive
            )
            return transfer_ids[0] if transfer_ids else None
        self.log_warning("DCC system not enabled or DCCManager not available.")
        return None

    async def dcc_accept_passive_offer(self, peer_nick: str, filename: str, token: str) -> Optional[str]:
        """Accepts a passive DCC SEND offer using a token. Returns transfer ID or None."""
        if self.client_logic.dcc_manager:
            transfer = await self.client_logic.dcc_manager.accept_passive_offer_by_token(
                peer_nick, filename, token
            )
            return transfer.id if transfer else None
        self.log_warning("DCC system not enabled or DCCManager not available.")
        return None

    def get_dcc_transfer_status(self, transfer_id: str) -> Optional[Dict[str, Any]]:
        """Gets the status of a DCC transfer by its ID."""
        if self.client_logic.dcc_manager:
            return self.client_logic.dcc_manager.get_transfer_status_dict(transfer_id)
        self.log_warning("DCC system not enabled or DCCManager not available.")
        return None

    def list_dcc_transfers(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists DCC transfers, optionally filtered by status (e.g., "ACTIVE", "COMPLETED")."""
        if self.client_logic.dcc_manager:
            return self.client_logic.dcc_manager.list_transfers_as_dicts(status_filter)
        self.log_warning("DCC system not enabled or DCCManager not available.")
        return []

    async def dcc_cancel_transfer(self, transfer_id_or_token_prefix: str) -> bool:
        """Cancels an active DCC transfer or a pending passive offer."""
        if self.client_logic.dcc_manager:
            return await self.client_logic.dcc_manager.cancel_transfer_by_id_or_token(transfer_id_or_token_prefix)
        self.log_warning("DCC system not enabled or DCCManager not available.")
        return False

    # --- Python Trigger API (for /on ... PY <code>) ---
    def get_python_trigger_api(self) -> "PythonTriggerAPI":
        """Returns an instance of PythonTriggerAPI for executing Python code triggers."""
        # This assumes PythonTriggerAPI is initialized by IRCClient_Logic or similar
        # and made available. For now, let's assume it's on client_logic.
        if hasattr(self.client_logic, 'python_trigger_api_instance') and self.client_logic.python_trigger_api_instance:
            return self.client_logic.python_trigger_api_instance
        else:
            # Fallback or error handling if not found
            self.log_error("PythonTriggerAPI instance not found on client_logic.")
            # You might want to raise an exception or return a dummy API
            # For now, returning a new instance, but this might not be ideal
            # as it won't be the one used by the trigger manager.
            # This indicates a setup issue if reached.
            # from tirc_core.scripting.python_trigger_api import PythonTriggerAPI # Local import - already imported at top
            return PythonTriggerAPI(self.client_logic)
