import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.app_config import AppConfig

logger = logging.getLogger(__name__)

class IPCManager:
    """
    Manages the Inter-Process Communication (IPC) server for receiving remote commands.
    """
    def __init__(self, client: 'IRCClient_Logic'):
        self.client = client
        self.server: asyncio.Server | None = None
        self.ipc_port = self.client.config.ipc_port
        logger.debug(f"IPCManager initialized with port: {self.ipc_port}")

    async def start_server(self):
        """
        Starts the local TCP socket server to listen for incoming IPC commands.
        """
        try:
            self.server = await asyncio.start_server(
                self._handle_ipc_client, '127.0.0.1', self.ipc_port
            )
            addr = self.server.sockets[0].getsockname()
            logger.info(f"IPC server listening on {addr}")
        except OSError as e:
            logger.error(f"Failed to start IPC server on port {self.ipc_port}: {e}")
            self.server = None # Ensure server is None if startup fails
        except Exception as e:
            logger.exception(f"An unexpected error occurred while starting IPC server: {e}")
            self.server = None

    async def _handle_ipc_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Handles a single incoming IPC client connection, reads the command, and processes it.
        """
        addr = writer.get_extra_info('peername')
        logger.debug(f"IPC client connected from {addr}")
        try:
            data = await reader.readline()
            command = data.decode().strip()
            if command:
                logger.info(f"Received remote command: '{command}' from {addr}")
                # Pass the command to the IRCClient_Logic's command handler
                await self.client.command_handler.process_user_command(command)
            else:
                logger.warning(f"Received empty command from {addr}")
        except Exception as e:
            logger.error(f"Error handling IPC client {addr}: {e}")
        finally:
            logger.debug(f"Closing IPC client connection from {addr}")
            writer.close()
            await writer.wait_closed()

    async def stop_server(self):
        """
        Gracefully stops the IPC server.
        """
        if self.server:
            logger.info("Stopping IPC server...")
            self.server.close()
            await self.server.wait_closed()
            logger.info("IPC server stopped.")
        else:
            logger.debug("IPC server not running or already stopped.")
