# tirc_core/client/client_shutdown_coordinator.py
import logging
import asyncio
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.shutdown_coordinator")

class ClientShutdownCoordinator:
    """Handles the graceful shutdown sequence for the IRC client."""

    def __init__(self, client_logic_ref: "IRCClient_Logic"):
        self.client_logic = client_logic_ref
        self.shutdown_initiated = False
        self.shutdown_lock = asyncio.Lock() # Ensures shutdown runs only once

    async def initiate_graceful_shutdown(self, reason: str = "Client shutting down"):
        """
        Coordinates the entire shutdown process.
        This method is idempotent.
        """
        async with self.shutdown_lock:
            if self.shutdown_initiated:
                logger.info("Shutdown already in progress or completed.")
                return
            self.shutdown_initiated = True
            logger.info(f"Initiating graceful shutdown. Reason: {reason}")

            if self.client_logic.ipc_manager:
                logger.debug("Shutting down IPCManager.")
                await self.client_logic.ipc_manager.stop_server()

            if self.client_logic.dcc_manager and self.client_logic.dcc_manager.dcc_config.enabled:
                logger.debug("Shutting down DCCManager.")
                await self.client_logic.dcc_manager.shutdown()

            if self.client_logic.network_handler and self.client_logic.network_handler.connected:
                logger.debug(f"Disconnecting from server with quit message: {reason}")
                await self.client_logic.network_handler.disconnect_gracefully(quit_message=reason)
                logger.info("Graceful disconnect initiated.")

            if self.client_logic.network_handler:
                logger.debug("Ensuring NetworkHandler is stopped.")
                await self.client_logic.network_handler.stop()

            if self.client_logic.input_handler:
                logger.debug("Stopping InputHandler tasks.")
                if self.client_logic._input_reader_task_ref and not self.client_logic._input_reader_task_ref.done():
                    self.client_logic._input_reader_task_ref.cancel()
                    try:
                        await self.client_logic._input_reader_task_ref
                    except asyncio.CancelledError:
                        logger.info("Input reader task cancelled.")
                if self.client_logic._input_processor_task_ref and not self.client_logic._input_processor_task_ref.done():
                    self.client_logic._input_processor_task_ref.cancel()
                    try:
                        await self.client_logic._input_processor_task_ref
                    except asyncio.CancelledError:
                        logger.info("Input processor task cancelled.")

            if self.client_logic.script_manager:
                logger.debug("Unloading scripts via IRCClient_Logic._unload_all_scripts.")
                await self.client_logic._unload_all_scripts()

            if self.client_logic.state_manager:
                logger.debug("Shutting down StateManager (will save state if auto_save is on).")
                self.client_logic.state_manager.shutdown()

            if self.client_logic.ui and hasattr(self.client_logic.ui, 'shutdown_ui_components'):
                logger.debug("Shutting down UI components via UIManager.")
                # self.client_logic.ui.shutdown_ui_components()

            # The NetworkHandler.stop() should handle cancelling its own loop,
            # which includes any auto-reconnection logic within that loop.
            # No separate auto_reconnect_task needs to be cancelled here.

            logger.info("Client shutdown sequence complete from coordinator.")

            if hasattr(self.client_logic, 'shutdown_complete_event'):
                self.client_logic.shutdown_complete_event.set()
