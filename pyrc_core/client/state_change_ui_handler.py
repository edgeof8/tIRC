# pyrc_core/client/state_change_ui_handler.py
import logging
from typing import TYPE_CHECKING, Optional
from pyrc_core.state_manager import StateChange, ConnectionState, ConnectionInfo

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.state_ui_handler")

class StateChangeUIHandler:
    def __init__(self, client: "IRCClient_Logic"):
        self.client = client
        self.state_manager = client.state_manager
        self.register_handlers()

    def register_handlers(self):
        """Register handlers for specific state changes."""
        self.state_manager.register_change_handler("connection_state", self.on_connection_state_change)
        self.state_manager.register_change_handler("connection_info", self.on_connection_info_change)
        # Add more handlers as state affecting UI is identified.

    async def _safe_add_status_message(self, message: str, color_key: str = "system"):
        """Safely add a status message if the client and UI are available."""
        try:
            if hasattr(self.client, 'add_status_message') and callable(self.client.add_status_message):
                await self.client.add_status_message(message, color_key)
            elif hasattr(self.client, 'ui') and self.client.ui:
                logger.debug(f"Skipping status message (add_status_message not available): {message}")
            else:
                logger.debug(f"Skipping status message (UI not available): {message}")
        except Exception as e:
            logger.warning(f"Failed to add status message: {e}", exc_info=True)

    def _trigger_ui_update(self):
        """Safely trigger a UI update if the client and UI are available."""
        try:
            if hasattr(self.client, 'ui') and self.client.ui and \
               hasattr(self.client, 'ui_needs_update') and \
               hasattr(self.client.ui_needs_update, 'set'):
                self.client.ui_needs_update.set()
            else:
                logger.debug("Skipping UI update trigger (UI or ui_needs_update not available).")
        except Exception as e:
            logger.warning(f"Failed to trigger UI update: {e}", exc_info=True)


    async def on_connection_state_change(self, change: StateChange[ConnectionState]):
        """Handles changes to the connection state and updates the UI if available."""
        if not change or not hasattr(change, 'new_value'):
            logger.warning("Invalid connection_state change event received.")
            return

        new_state: Optional[ConnectionState] = change.new_value
        if new_state is None:
            logger.warning("Connection state change event received with None new_value.")
            return

        metadata = change.metadata or {}

        try:
            state_name = getattr(new_state, 'name', str(new_state))
            logger.debug(f"UI Handler: Connection state changed to: {state_name}")

            if new_state == ConnectionState.CONNECTING:
                await self._safe_add_status_message("Connecting to server...")
            elif new_state == ConnectionState.CONNECTED:
                await self._safe_add_status_message("Connection established. Negotiating capabilities...")
            elif new_state == ConnectionState.REGISTERED:
                await self._safe_add_status_message("Successfully registered with the server.", "info")
            elif new_state == ConnectionState.DISCONNECTED:
                # Get the server details from the old_value if possible, or current state if not
                server_details = "server"
                old_conn_info: Optional[ConnectionInfo] = None
                # Check if connection_info_snapshot is available in metadata
                old_conn_info_dict = metadata.get("connection_info_snapshot")
                if old_conn_info_dict and isinstance(old_conn_info_dict, dict):
                    try:
                        old_conn_info = ConnectionInfo(**old_conn_info_dict)
                    except TypeError as e:
                        logger.warning(f"Failed to reconstruct ConnectionInfo from snapshot: {e}")

                if not old_conn_info: # Fallback to current state_manager connection info
                    old_conn_info = self.state_manager.get_connection_info()

                if old_conn_info and old_conn_info.server:
                    server_details = f"{old_conn_info.server}:{old_conn_info.port}"

                await self._safe_add_status_message(f"Disconnected from {server_details}.", "warning")

            elif new_state == ConnectionState.ERROR:
                error_msg = metadata.get("error", "An unknown connection error occurred.")
                logger.error(f"UI Handler: Connection error: {error_msg}")
                await self._safe_add_status_message(f"Connection Error: {error_msg}", "error")
            elif new_state == ConnectionState.CONFIG_ERROR:
                error_msg = metadata.get("error", "Invalid configuration.")
                logger.error(f"UI Handler: Configuration error: {error_msg}")
                await self._safe_add_status_message(f"Configuration Error: {error_msg}", "error")
            else:
                logger.debug(f"UI Handler: Unhandled connection state for UI message: {state_name}")

            self._trigger_ui_update()
        except Exception as e:
            logger.error(f"Error in on_connection_state_change UI handler: {e}", exc_info=True)
            await self._safe_add_status_message(f"Error handling connection state UI: {str(e)}", "error")

    async def on_connection_info_change(self, change: StateChange[Optional[ConnectionInfo]]):
        """Handles changes to the connection_info (e.g., nick change, server details)."""
        if not change:
            logger.warning("Invalid connection_info change event received.")
            return

        old_info: Optional[ConnectionInfo] = change.old_value
        new_info: Optional[ConnectionInfo] = change.new_value

        # Nick change
        if old_info and new_info and old_info.nick != new_info.nick:
            await self._safe_add_status_message(f"Your nick changed from {old_info.nick} to {new_info.nick}.", "info")
            logger.debug(f"UI Handler: Nick changed from {old_info.nick} to {new_info.nick}")

        # Server/port change (less common to change mid-session without disconnect/reconnect, but good to handle)
        if old_info and new_info and (old_info.server != new_info.server or old_info.port != new_info.port):
            await self._safe_add_status_message(f"Connection details updated to {new_info.server}:{new_info.port}.", "system")
            logger.debug(f"UI Handler: Connection details changed to {new_info.server}:{new_info.port}")
        elif not old_info and new_info: # Initial connection info set
            await self._safe_add_status_message(f"Configured for {new_info.server}:{new_info.port} as {new_info.nick}.", "system")
            logger.debug(f"UI Handler: Initial connection info set for {new_info.server}:{new_info.port}")


        # Potentially other UI updates based on ConnectionInfo changes (e.g., status bar)
        self._trigger_ui_update()
