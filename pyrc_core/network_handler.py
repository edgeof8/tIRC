# START OF MODIFIED FILE: network_handler.py
import asyncio
import socket
import ssl
import logging
import concurrent.futures
from typing import List, Optional, Set, TYPE_CHECKING
from pyrc_core.app_config import AppConfig
from pyrc_core.state_manager import ConnectionState

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.network")


class NetworkHandler:
    def __init__(self, client_logic_ref: "IRCClient_Logic"):
        self.client_logic_ref = client_logic_ref
        self.config: AppConfig = client_logic_ref.config
        self.connected = False
        self.connection_params = None
        self._network_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self.logger = logging.getLogger("pyrc.network")
        self.reconnect_delay: int = self.config.reconnect_initial_delay
        self.channels_to_join_on_connect: List[str] = []
        self.is_handling_nick_collision: bool = False
        self.buffer: bytes = b""
        self._disconnect_event_sent_for_current_session = False

    async def start(self) -> bool:
        """Start the network handler and its asyncio task."""
        if self._network_task is not None and not self._network_task.done():
            self.logger.warning("Network task already running")
            return False

        self._stop_event.clear()
        self._network_task = asyncio.create_task(self._network_loop())
        self.logger.info("Network task started.")
        return True

    async def stop(self) -> bool:
        """Stop the network handler and wait for task completion."""
        if self._network_task is None or self._network_task.done():
            return True

        self.logger.info("Stopping network handler...")
        self._stop_event.set()

        try:
            # Wait for the network task to complete
            await asyncio.wait_for(self._network_task, timeout=3.0)
            self.logger.info("Network task stopped successfully.")
            return True
        except asyncio.TimeoutError:
            self.logger.warning("Network task did not complete in time, cancelling...")
            self._network_task.cancel()
            try:
                await self._network_task
            except asyncio.CancelledError:
                self.logger.info("Network task cancelled.")
                return True
            except Exception as e:
                self.logger.error(f"Error awaiting cancelled network task: {e}")
                return False
        except Exception as e:
            self.logger.error(f"Error stopping network task: {e}")
            return False
        return False # Ensure a boolean is always returned at the end

    async def disconnect_gracefully(self, quit_message: Optional[str] = None) -> None:
        """Disconnect from the server gracefully."""
        if self.connected and self._writer:
            try:
                if quit_message:
                    await self.send_raw(f"QUIT :{quit_message}")
                else:
                    await self.send_raw("QUIT :Client disconnected")
            except Exception as e:
                self.logger.error(f"Error sending QUIT message: {e}")

        await self.stop()
        self.connected = False
        if self._reader:
            try:
                self._reader = None
            except Exception as e:
                self.logger.error(f"Error clearing reader: {e}")
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
                self._writer = None
            except Exception as e:
                self.logger.error(f"Error closing writer: {e}")

    async def update_connection_params(
        self,
        server: str,
        port: int,
        use_ssl: bool,
        channels_to_join: Optional[List[str]] = None,
    ):
        logger.info(
            f"Updating connection parameters to: {server}:{port} SSL: {use_ssl}. Channels to join: {channels_to_join}"
        )
        if self.connected:
            logger.debug(
                "Currently connected, disconnecting gracefully before updating params."
            )
            conn_info = self.client_logic_ref.state_manager.get_connection_info()
            current_server_lower = (
                conn_info.server.lower()
                if conn_info and conn_info.server
                else ""
            )
            new_server_lower = server.lower()
            quit_msg = (
                f"Changing to {server}"
                if current_server_lower != new_server_lower
                else "Reconnecting"
            )
            await self.disconnect_gracefully(quit_msg)
            # Give some time for the disconnect to process if the network task is busy
            if self._network_task and not self._network_task.done():
                try:
                    await asyncio.wait_for(self._network_task, timeout=1.0)
                except asyncio.TimeoutError:
                    self.logger.warning("Previous network task did not stop gracefully in time.")
                except Exception as e:
                    self.logger.error(f"Error waiting for previous network task to stop: {e}")

        if channels_to_join is not None:
            self.channels_to_join_on_connect = channels_to_join
        else:
            # Get initial channels from the StateManager, not the client logic object
            conn_info = self.client_logic_ref.state_manager.get_connection_info()
            if conn_info and conn_info.initial_channels:
                self.channels_to_join_on_connect = conn_info.initial_channels[:]
            else:
                self.channels_to_join_on_connect = []

        self.reconnect_delay = self.config.reconnect_initial_delay

        if not self._network_task or self._network_task.done():
            logger.info("Network task not running, starting it after param update.")
            asyncio.create_task(self.start())
        else:
            logger.debug(
                "Network task is alive. Setting connected=False to force re-evaluation in loop."
            )
            # Reset critical handshake components
            if (
                hasattr(self.client_logic_ref, "cap_negotiator")
                and self.client_logic_ref.cap_negotiator
            ):
                self.client_logic_ref.cap_negotiator.reset_negotiation_state()
            if (
                hasattr(self.client_logic_ref, "sasl_authenticator")
                and self.client_logic_ref.sasl_authenticator
            ):
                self.client_logic_ref.sasl_authenticator.reset_authentication_state()
            if (
                hasattr(self.client_logic_ref, "registration_handler")
                and self.client_logic_ref.registration_handler
            ):
                self.client_logic_ref.registration_handler.reset_registration_state()

            self.connected = False  # This will trigger _connect_socket in the loop

    async def send_cap_ls(self, version: Optional[str] = "302"):
        if self.connected and self._writer:
            if version:
                await self.send_raw(f"CAP LS {version}")
            else:
                await self.send_raw("CAP LS")
        else:
            logger.warning("send_cap_ls called but not connected or no writer.")

    async def send_cap_req(self, capabilities: List[str]):
        if self.connected and self._writer:
            if capabilities:
                await self.send_raw(f"CAP REQ :{ ' '.join(capabilities)}")
        else:
            logger.warning("send_cap_req called but not connected or no writer.")

    async def send_cap_end(self):
        if self.connected and self._writer:
            logger.debug("Sending CAP END")
            await self.send_raw("CAP END")
        else:
            logger.warning("send_cap_end called but not connected or no writer.")

    async def send_authenticate(self, payload: str):
        if self.connected and self._writer:
            logger.debug(f"Sending AUTHENTICATE {payload[:20]}...")
            await self.send_raw(f"AUTHENTICATE {payload}")
        else:
            logger.warning("send_authenticate called but not connected or no writer.")

# In pyrc_core/network_handler.py

    async def _reset_connection_state(self, dispatch_event: bool = True):
        logger.debug(
            f"Resetting connection state. Dispatch disconnect event: {dispatch_event}"
        )

        if self._reader:
            self._reader = None
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
                logger.debug("Writer closed by _reset_connection_state.")
            except Exception as e:
                logger.error(f"Error closing writer in reset: {e}")
            finally:
                self._writer = None

        if self.connected:
            self.client_logic_ref.state_manager.set_connection_state(ConnectionState.DISCONNECTED)

        was_connected = self.connected
        self.connected = False
        self.is_handling_nick_collision = False

        if self.client_logic_ref:
            # --- START OF FIX ---
            # Reset all handshake components to prepare for a new connection
            if hasattr(self.client_logic_ref, "cap_negotiator") and self.client_logic_ref.cap_negotiator:
                self.client_logic_ref.cap_negotiator.reset_negotiation_state()
            if hasattr(self.client_logic_ref, "sasl_authenticator") and self.client_logic_ref.sasl_authenticator:
                self.client_logic_ref.sasl_authenticator.reset_authentication_state()
            if hasattr(self.client_logic_ref, "registration_handler") and self.client_logic_ref.registration_handler:
                self.client_logic_ref.registration_handler.reset_registration_state()
            # --- END OF FIX ---

            if (
                dispatch_event
                and was_connected
                and not self._disconnect_event_sent_for_current_session
            ):
                conn_info = self.client_logic_ref.state_manager.get_connection_info()
                if conn_info and conn_info.server and conn_info.port is not None:
                    self.client_logic_ref.event_manager.dispatch_client_disconnected(
                        conn_info.server, conn_info.port, raw_line=""
                    )
                    self._disconnect_event_sent_for_current_session = True

        self.buffer = b""
        logger.debug("Connection state reset complete")


    async def _connect_socket(self) -> bool:
        self.is_handling_nick_collision = False
        conn_info = (
            self.client_logic_ref.state_manager.get_connection_info()
            if self.client_logic_ref
            else None
        )
        if (
            not conn_info
            or not conn_info.server
            or conn_info.port is None
        ):
            error_msg = "Server or port not configured"
            logger.error(f"NetworkHandler._connect_socket: {error_msg}")
            self.client_logic_ref.state_manager.set_connection_state(
                ConnectionState.ERROR,
                error_msg
            )
            return False

        self.client_logic_ref.state_manager.set_connection_state(ConnectionState.CONNECTING)
        try:
            conn_info = self.client_logic_ref.state_manager.get_connection_info()
            if not conn_info:
                error_msg = "Cannot connect - no connection info available"
                logger.error(error_msg)
                self.client_logic_ref.state_manager.set_connection_state(
                    ConnectionState.ERROR,
                    error=error_msg
                )
                return False

            server = conn_info.server or ""
            port = conn_info.port or 6667
            use_ssl = conn_info.ssl if conn_info.ssl is not None else False

            logger.info(
                f"Attempting asyncio.open_connection to {server}:{port} (SSL: {use_ssl})"
            )

            ssl_context = None
            if use_ssl:
                logger.debug("SSL is enabled, creating SSL context.")
                ssl_context = ssl.create_default_context()
                try:
                    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                    logger.info(f"Set SSLContext minimum_version to TLSv1_2 for {server}")
                except AttributeError:
                    logger.warning(
                        "ssl.TLSVersion.TLSv1_2 not available. Default TLS settings will be used."
                    )

                verify_ssl = conn_info.verify_ssl_cert if conn_info.verify_ssl_cert is not None else True
                if not verify_ssl:
                    logger.warning(
                        "SSL certificate verification is DISABLED. This is insecure."
                    )
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

            # Use asyncio.open_connection
            self._reader, self._writer = await asyncio.open_connection(
                server,
                port,
                ssl=ssl_context,
                limit=4096,
                happy_eyeballs_delay=0.25
            )

            logger.debug("Asyncio connection established.")

            self.connected = True
            self.reconnect_delay = self.config.reconnect_initial_delay
            logger.info(
                f"Successfully connected to {server}:{port}. SSL: {use_ssl}"
            )
            self.client_logic_ref.state_manager.set_connection_state(ConnectionState.CONNECTED)

            if (
                hasattr(self.client_logic_ref, "cap_negotiator")
                and self.client_logic_ref.cap_negotiator
            ):
                self.client_logic_ref.cap_negotiator.start_negotiation()
            else:
                logger.error(
                    "NetworkHandler: cap_negotiator not found on client object during _connect_socket."
                )
                await self.client_logic_ref._add_status_message(
                    "Error: CAP negotiator not initialized.", "error"
                )

            if (
                self.client_logic_ref
                and hasattr(self.client_logic_ref, "event_manager")
                and self.client_logic_ref.event_manager
            ):
                self.client_logic_ref.event_manager.dispatch_client_connected(
                    server=server,
                    port=port,
                    nick=conn_info.nick or "",
                    ssl=use_ssl,
                    raw_line="",
                )

            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, socket.gaierror, ssl.SSLError) as e:
            error_msg = f"Connection error to {server}:{port}: {e}"
            logger.error(error_msg, exc_info=True)
            self.client_logic_ref.state_manager.set_connection_state(
                ConnectionState.ERROR,
                error=error_msg
            )
        except Exception as e:
            error_msg = f"Unexpected error during connection: {e}"
            logger.critical(error_msg, exc_info=True)
            self.client_logic_ref.state_manager.set_connection_state(
                ConnectionState.ERROR,
                error=error_msg
            )

        await self._reset_connection_state()
        return False

    async def send_raw(self, data: str):
        # Re-check connection status immediately before sending
        if not self._writer or not self.connected:
            logger.warning(
                f"Attempted to send data while not truly connected or no writer: {data.strip()}"
            )
            if (
                self.client_logic_ref
            ):
                await self.client_logic_ref._add_status_message(
                    "Cannot send: Not connected.", "error"
                )
                if not self.client_logic_ref.is_headless:
                    self.client_logic_ref.ui_needs_update.set()
            return

        try:
            if not data.endswith("\r\n"):
                data += "\r\n"
            self._writer.write(data.encode("utf-8", errors="replace"))
            await self._writer.drain()

            log_data = data.strip()
            if log_data.upper().startswith("PASS "):
                log_data = "PASS ******"
            elif log_data.upper().startswith("AUTHENTICATE ") and len(log_data) > 15:
                log_data = log_data.split(" ", 1)[0] + " ******"
            elif log_data.upper().startswith("PRIVMSG NICKSERV :IDENTIFY"):
                parts = log_data.split(" ", 3)
                if len(parts) >= 3:
                    log_data = f"{parts[0]} {parts[1]} {parts[2]} ******"
                else:
                    log_data = "PRIVMSG NickServ :IDENTIFY ******"

            logger.debug(f"C >> {log_data}")

            if (
                self.client_logic_ref
                and hasattr(self.client_logic_ref, "show_raw_log_in_ui")
                and self.client_logic_ref.show_raw_log_in_ui
            ):
                await self.client_logic_ref.add_message(
                    f"C >> {log_data}",
                    self.client_logic_ref.ui.colors["system"],
                    context_name="Status",
                    prefix_time=True,
                )

            if data.upper().startswith("NICK "):
                self.is_handling_nick_collision = False
        except (
            OSError,
            ConnectionError,
            ssl.SSLError,
        ) as e:
            logger.error(f"Error sending data: {e}", exc_info=True)
            if self.client_logic_ref:
                await self.client_logic_ref._add_status_message(
                    f"Error sending data: {e}", "error"
                )
                if not self.client_logic_ref.is_headless:
                    self.client_logic_ref.ui_needs_update.set()
            await self._reset_connection_state(
                dispatch_event=True
            )
        except Exception as e_unhandled_send:
            logger.critical(
                f"Unhandled error sending data: {e_unhandled_send}", exc_info=True
            )
            if self.client_logic_ref:
                await self.client_logic_ref.add_message(
                    f"Critical send error: {e_unhandled_send}",
                    self.client_logic_ref.ui.colors["error"],
                    context_name="Status",
                )
            await self._reset_connection_state(dispatch_event=True)

    async def _network_loop(self) -> None:
        """Main network handling loop."""
        try:
            while not self._stop_event.is_set():
                if not self.connected or not self._reader:
                    conn_info = (
                        self.client_logic_ref.state_manager.get_connection_info()
                        if self.client_logic_ref
                        else None
                    )
                    if (
                        conn_info
                        and conn_info.server
                        and conn_info.port is not None
                    ):
                        logger.info(
                            f"Attempting to connect to {conn_info.server}:{conn_info.port}"
                        )
                        if await self._connect_socket():
                            logger.info("Successfully connected to server")
                            self.connected = True
                            self._disconnect_event_sent_for_current_session = False
                        else:
                            logger.warning(
                                "Failed to connect, will retry in next iteration"
                            )
                            await asyncio.sleep(0.1)
                    else:
                        logger.debug("No connection parameters available, waiting...")
                        await asyncio.sleep(0.1)
                    continue

                try:
                    data = await self._reader.read(4096)

                    if not data:
                        logger.info("Connection closed by server")
                        await self._reset_connection_state()
                        continue

                    await self._process_received_data(data)

                except asyncio.IncompleteReadError:
                    logger.info("Server closed connection during read.")
                    await self._reset_connection_state()
                    continue
                except ConnectionError as e:
                    logger.error(f"Connection error in network loop: {e}")
                    await self._reset_connection_state()
                    continue
                except Exception as e:
                    logger.error(f"Error in network loop: {e}", exc_info=True)
                    await self._reset_connection_state()
                    continue

        except asyncio.CancelledError:
            logger.info("Network loop cancelled.")
        except Exception as e:
            logger.critical(f"Critical error in network loop: {e}", exc_info=True)
        finally:
            self.connected = False
            await self._reset_connection_state(dispatch_event=True)
            logger.info("Network loop shutdown complete.")

    async def _process_received_data(self, data: bytes) -> None:
        """Process received data from the network socket.

        Args:
            data: Raw bytes received from the socket
        """
        try:
            # Add new data to buffer
            self.buffer += data

            # Process complete lines
            while b"\r\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\r\n", 1)
                try:
                    # Decode the line and handle it
                    decoded_line = line.decode("utf-8", errors="replace")
                    if self.client_logic_ref:
                        await self.client_logic_ref.handle_server_message(decoded_line)
                except UnicodeDecodeError as e:
                    logger.error(f"Error decoding received data: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing received line: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error in _process_received_data: {e}", exc_info=True)
            # Don't clear buffer on error to avoid losing data
            pass


# END OF MODIFIED FILE: network_handler.py
