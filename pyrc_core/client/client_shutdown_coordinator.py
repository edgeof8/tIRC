# pyrc_core/client/client_shutdown_coordinator.py
import asyncio
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.shutdown_coordinator")

class ClientShutdownCoordinator:
    def __init__(self, client: "IRCClient_Logic"):
        self.client = client

    async def execute_shutdown(self, final_quit_message: Optional[str]):
        """
        Executes the full client shutdown sequence.
        Moved from IRCClient_Logic.run_main_loop's finally block.
        """
        logger.info("ClientShutdownCoordinator: Executing full client shutdown sequence.")
        self.client.should_quit.set() # Ensure it's set

        quit_msg_to_send = final_quit_message or "Client shutting down"

        # 1. Gracefully disconnect network (sends QUIT, stops network_handler task)
        if not self.client.loop.is_closed():
            if self.client.network_handler:
                logger.info(f"ClientShutdownCoordinator: Attempting graceful network disconnect with message: '{quit_msg_to_send}'")
                try:
                    await self.client.network_handler.disconnect_gracefully(quit_msg_to_send)
                except Exception as e_net_disc: # pragma: no cover
                    logger.error(f"ClientShutdownCoordinator: Error during network_handler.disconnect_gracefully: {e_net_disc}", exc_info=True)
            else: # pragma: no cover
                logger.warning("ClientShutdownCoordinator: NetworkHandler not available.")
        else:
            logger.warning("ClientShutdownCoordinator: Loop closed, skipping network disconnect.")

        # 2. Cancel and await other client-level tasks
        async def cancel_and_await_task(task: Optional[asyncio.Task], name: str):
            if task and not task.done():
                logger.info(f"ClientShutdownCoordinator: Attempting to cancel task: {name}")
                if not self.client.loop.is_closed(): # Check loop before attempting cancel
                    task.cancel() # This might still raise if loop closes between check and call
                    try:
                        # Only await if the loop is still not closed before awaiting
                        if not self.client.loop.is_closed():
                            await task
                        else:
                            logger.warning(f"ClientShutdownCoordinator: Loop closed before awaiting cancelled task {name}. Task state: {task}")
                    except asyncio.CancelledError:
                        logger.info(f"ClientShutdownCoordinator: Task {name} successfully cancelled and awaited.")
                    except Exception as e_await_cancel: # pragma: no cover
                        logger.error(f"ClientShutdownCoordinator: Error awaiting cancelled task {name}: {e_await_cancel}", exc_info=True)
                else:
                    logger.warning(f"ClientShutdownCoordinator: Loop closed, cannot initiate cancel for task {name}. Task state: {task}")

        # Guard the entire block of these sensitive operations
        if not self.client.loop.is_closed():
            logger.info("ClientShutdownCoordinator: Loop is open, proceeding with input task cancellations.")
            await cancel_and_await_task(self.client._input_reader_task_ref, "_input_reader_task_ref")
            if not self.client.loop.is_closed(): # Re-check before next task
                await cancel_and_await_task(self.client._input_processor_task_ref, "_input_processor_task_ref")
            else:
                logger.warning("ClientShutdownCoordinator: Loop closed before cancelling _input_processor_task_ref.")
        else:
            logger.warning("ClientShutdownCoordinator: Loop was already closed before attempting any input task cancellations.")
            # Log state of tasks if loop is closed
            if self.client._input_reader_task_ref and not self.client._input_reader_task_ref.done():
                logger.warning(f"ClientShutdownCoordinator: _input_reader_task_ref not cancelled as loop is closed. State: {self.client._input_reader_task_ref}")
            if self.client._input_processor_task_ref and not self.client._input_processor_task_ref.done():
                logger.warning(f"ClientShutdownCoordinator: _input_processor_task_ref not cancelled as loop is closed. State: {self.client._input_processor_task_ref}")

        # self.client._network_task_ref is handled by network_handler.disconnect_gracefully -> stop()
        # disconnect_gracefully itself checks if the loop is closed.

        # 3. Shutdown synchronous components
        if self.client.script_manager:
            logger.info("ClientShutdownCoordinator: Unloading all scripts.")
            await self.client._unload_all_scripts() # Await the async unload

        if self.client.dcc_manager:
            logger.info("ClientShutdownCoordinator: Shutting down DCCManager.")
            self.client.dcc_manager.shutdown()

        if self.client._executor:
            logger.info("ClientShutdownCoordinator: Shutting down ThreadPoolExecutor...")
            self.client._executor.shutdown(wait=True, cancel_futures=True)
            self.client._executor = None
            logger.info("ClientShutdownCoordinator: ThreadPoolExecutor shut down.")

        # UI shutdown is handled by pyrc.py after run_main_loop completes.

        # Dispatch final shutdown event as the last async operation of the client
        if not self.client.loop.is_closed():
            if hasattr(self.client, "event_manager") and self.client.event_manager:
                try:
                    logger.info("ClientShutdownCoordinator: Dispatching CLIENT_SHUTDOWN_FINAL.")
                    await self.client.event_manager.dispatch_client_shutdown_final(raw_line="CLIENT_SHUTDOWN_FINAL from ClientShutdownCoordinator")
                except Exception as e_dispatch_final: # pragma: no cover
                    logger.error(f"ClientShutdownCoordinator: Error dispatching CLIENT_SHUTDOWN_FINAL: {e_dispatch_final}", exc_info=True)
        else:
            logger.warning("ClientShutdownCoordinator: Loop closed, skipping CLIENT_SHUTDOWN_FINAL dispatch.")

        logger.info("ClientShutdownCoordinator: Full client shutdown sequence complete.")
        self.client.shutdown_complete_event.set() # Signal that all cleanup is done
