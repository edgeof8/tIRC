import logging
from typing import TYPE_CHECKING
from pyrc_core.state_manager import StateChange, ConnectionState

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
        # Register more handlers for other state keys as needed
        
    def _safe_add_status_message(self, message: str, msg_type: str = "info"):
        """Safely add a status message if the client supports it."""
        try:
            if hasattr(self.client, '_add_status_message') and callable(self.client._add_status_message):
                self.client._add_status_message(message, msg_type)
            else:
                logger.debug(f"Skipping status message (UI not available): {message}")
        except Exception as e:
            logger.warning(f"Failed to add status message: {e}", exc_info=True)

    def on_connection_state_change(self, change: StateChange[ConnectionState]):
        """
        Handles changes to the connection state and updates the UI if available.
        
        Args:
            change: The state change event containing the new state and metadata
        """
        if not change or not hasattr(change, 'new_value'):
            logger.warning("Invalid state change event received")
            return
            
        new_state: ConnectionState = change.new_value
        metadata = change.metadata or {}
        
        try:
            # Log the state change for debugging
            state_name = getattr(new_state, 'name', str(new_state))
            logger.debug(f"Connection state changed to: {state_name}")
            
            # Update status messages if UI is available
            if new_state == ConnectionState.CONNECTING:
                self._safe_add_status_message("Connecting to server...")
            elif new_state == ConnectionState.CONNECTED:
                self._safe_add_status_message("Connection established. Negotiating capabilities...")
            elif new_state == ConnectionState.REGISTERED:
                self._safe_add_status_message("Successfully registered with the server.", "info")
            elif new_state == ConnectionState.DISCONNECTED:
                self._safe_add_status_message("Disconnected from server.", "warning")
            elif new_state == ConnectionState.ERROR:
                error_msg = metadata.get("error", "An unknown connection error occurred.")
                logger.error(f"Connection error: {error_msg}")
                self._safe_add_status_message(f"Connection Error: {error_msg}", "error")
            elif new_state == ConnectionState.CONFIG_ERROR:
                error_msg = metadata.get("error", "Invalid configuration.")
                logger.error(f"Configuration error: {error_msg}")
                self._safe_add_status_message(f"Configuration Error: {error_msg}", "error")
            else:
                logger.debug(f"Unhandled connection state: {state_name}")

            # Trigger UI update if available
            if hasattr(self.client, 'ui_needs_update') and hasattr(self.client.ui_needs_update, 'set'):
                try:
                    self.client.ui_needs_update.set()
                except Exception as e:
                    logger.warning(f"Failed to set UI update flag: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error in connection state change handler: {e}", exc_info=True)
            # Try to at least log the error to the UI if possible
            self._safe_add_status_message(f"Error handling state change: {str(e)}", "error")
