# START OF MODIFIED FILE: network_handler.py
import asyncio
import inspect
import socket
import ssl
import logging
import concurrent.futures
from typing import List, Optional, Set, cast, TYPE_CHECKING, Coroutine, Any  # Added TYPE_CHECKING
from pyrc_core.app_config import AppConfig
from pyrc_core.state_manager import ConnectionState, ConnectionInfo

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic  # Guarded import


logger = logging.getLogger("pyrc.network")


class NetworkHandler:
    def __init__(self, client_logic_ref: "IRCClient_Logic"):
        self.client_logic_ref = client_logic_ref
        self.config: AppConfig = client_logic_ref.config
        self.connected = False
        self.connection_params = None
        self._network_task: Optional[asyncio.Task] = None
        self._task_start_lock = asyncio.Lock()
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
        stack = inspect.stack()
        self.logger.info(f"NetworkHandler.start called by {stack[1].filename}:{stack[1].lineno} - {stack[1].function}")
        try:
            async with self._task_start_lock:
                if self._network_task is not None and not self._network_task.done():
                    self.logger.warning(f"Network task already running. Called by {stack[1].filename}:{stack[1].lineno}")
                    return False

                self.logger.info("Lock acquired, starting network task...")
                self._stop_event.clear()
                self.logger.info("Creating and starting network task...")
                self._network_task = asyncio.create_task(self.network_loop())
                self.logger.info("Network task creation initiated.")
                return True
        except Exception as e:
            self.logger.error(f"Error starting network task: {e}", exc_info=True)
            return False
        finally:
            pass  # Ensure lock is released in network_loop

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
        return False  # Ensure a boolean is always returned at the end

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
            #asyncio.create_task(self.start())  # Remove this line
        else:
            logger.debug(
                "Network task is alive. Setting connected=False to force re-evaluation in loop."
            )
            # Reset critical handshake components
            if (
                hasattr(self.client_logic_ref, "cap_negotiator")
                and self.client_logic_ref.cap_negotiator
            ):
                await self.client_logic_ref.cap_negotiator.reset_negotiation_state()
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

            self.connected = False  # This will trigger connect_socket in the loop

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
        self.logger.info(
            f"Resetting connection state. Dispatch disconnect event: {dispatch_event}. Called by: {inspect.stack()[1].filename}:{inspect.stack()[1].lineno} - {inspect.stack()[1].function}"
        )

        was_connected = self.connected # Capture state before changing
        self.connected = False # Set connected to False at the very beginning
        self.is_handling_nick_collision = False

        self._reader = None # Set reader to None immediately
        writer_to_close = self._writer # Store writer in local variable
        self._writer = None # Set writer to None immediately

        if writer_to_close: # Operate on the local variable
            try:
                if not writer_to_close.is_closing(): # Only close if not already closing
                    writer_to_close.close()
                await writer_to_close.wait_closed() # Wait for actual close
                self.logger.debug("Writer closed by _reset_connection_state.")
            except Exception as e:
                self.logger.error(f"Error closing writer in reset: {e}") # SSL error might happen here

        # Update StateManager state only if it was previously in a connected-like state
        if self.client_logic_ref: # Ensure client_logic_ref exists
            current_sm_state = self.client_logic_ref.state_manager.get_connection_state()
            if current_sm_state not in [ConnectionState.DISCONNECTED, ConnectionState.ERROR, ConnectionState.CONFIG_ERROR]:
                 self.client_logic_ref.state_manager.set_connection_state(ConnectionState.DISCONNECTED)

            # Reset handshake components
            if hasattr(self.client_logic_ref, "cap_negotiator") and self.client_logic_ref.cap_negotiator:
                await self.client_logic_ref.cap_negotiator.reset_negotiation_state()
            if hasattr(self.client_logic_ref, "sasl_authenticator") and self.client_logic_ref.sasl_authenticator:
                self.client_logic_ref.sasl_authenticator.reset_authentication_state()
            if hasattr(self.client_logic_ref, "registration_handler") and self.client_logic_ref.registration_handler:
                self.client_logic_ref.registration_handler.reset_registration_state()

            if (
                dispatch_event
                and was_connected # Use the captured state
                and not self._disconnect_event_sent_for_current_session
            ):
                # Try to get connection info from snapshot if available, else current
                conn_info_snapshot_dict = self.client_logic_ref.state_manager.get("connection_info_snapshot")
                conn_info_to_use: Optional[ConnectionInfo] = None

                if isinstance(conn_info_snapshot_dict, dict):
                    try:
                        # Reconstruct ConnectionInfo from the dictionary snapshot
                        conn_info_to_use = ConnectionInfo(**conn_info_snapshot_dict)
                    except TypeError: # pragma: no cover
                        self.logger.warning("Failed to reconstruct ConnectionInfo from snapshot in _reset_connection_state.")
                        conn_info_to_use = self.client_logic_ref.state_manager.get_connection_info()
                else:
                    conn_info_to_use = self.client_logic_ref.state_manager.get_connection_info()

                if conn_info_to_use and conn_info_to_use.server and conn_info_to_use.port is not None:
                    await self.client_logic_ref.event_manager.dispatch_client_disconnected(
                        conn_info_to_use.server, conn_info_to_use.port, raw_line=""
                    )
                    self._disconnect_event_sent_for_current_session = True
                    # Clear the snapshot after using it
                    self.client_logic_ref.state_manager.delete("connection_info_snapshot")
                else:
                    self.logger.warning("Could not dispatch disconnect event: server/port info missing from current or snapshot.")

        self.buffer = b"" # Clear any partial data
        self.logger.debug("Connection state reset complete")


    async def _connect_socket(self) -> bool:
        self.logger.info(f"NetworkHandler._connect_socket: Entered. Current connected state: {self.connected}")
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
            self.logger.error(f"NetworkHandler._connect_socket: {error_msg}")
            if self.client_logic_ref:
                self.client_logic_ref.state_manager.set_connection_state(
                    ConnectionState.ERROR,
                    error_msg
                )
            return False

        if self.client_logic_ref:
            self.client_logic_ref.state_manager.set_connection_state(ConnectionState.CONNECTING)
        try:
            if not conn_info:
                error_msg = "Cannot connect - no connection info available (secondary check)"
                self.logger.error(error_msg)
                if self.client_logic_ref:
                    self.client_logic_ref.state_manager.set_connection_state(
                        ConnectionState.ERROR,
                        error=error_msg
                    )
                return False

            server = conn_info.server
            port = conn_info.port
            use_ssl = conn_info.ssl if conn_info.ssl is not None else False

            self.logger.info(
                f"Attempting asyncio.open_connection to {server}:{port} (SSL: {use_ssl})"
            )

            ssl_context = None
            if use_ssl:
                self.logger.debug("SSL is enabled, creating SSL context.")
                ssl_context = ssl.create_default_context()
                try:
                    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                    self.logger.info(f"Set SSLContext minimum_version to TLSv1_2 for {server}")
                except AttributeError:
                    self.logger.warning(
                        "ssl.TLSVersion.TLSv1_2 not available. Default TLS settings will be used."
                    )

                verify_ssl = conn_info.verify_ssl_cert if conn_info.verify_ssl_cert is not None else True
                if not verify_ssl:
                    self.logger.warning(
                        "SSL certificate verification is DISABLED. This is insecure."
                    )
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                else:
                    ssl_context.check_hostname = True
                    ssl_context.verify_mode = ssl.CERT_REQUIRED
                    self.logger.info(f"SSL certificate verification ENABLED for {server}.")

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
                self.logger.debug("CapNegotiator found on client object during _connect_socket. Starting CAP negotiation.")
                #await self.client_logic_ref.cap_negotiator.start_negotiation() # Moved to RegistrationHandler after connect
            else:
                logger.warning("NetworkHandler: cap_negotiator not found on client object during _connect_socket. CAP negotiation will not start.")
                await self.client_logic_ref.add_status_message("Warning: CAP negotiator not initialized.", "warning")

            if (
                hasattr(self.client_logic_ref, "registration_handler")
                and self.client_logic_ref.registration_handler
            ):
                await self.client_logic_ref.registration_handler.on_connection_established()
            else:
                logger.error("RegistrationHandler not found on client object during _connect_socket.")
                await self.client_logic_ref.add_status_message("Error: Registration handler not initialized.", "error")
                return False

            if (
                self.client_logic_ref
                and hasattr(self.client_logic_ref, "event_manager")
                and self.client_logic_ref.event_manager
            ):
                await self.client_logic_ref.event_manager.dispatch_client_connected(
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
                error_msg
            )
        except Exception as e:
            error_msg = f"Unexpected error during connection: {e}"
            logger.critical(error_msg, exc_info=True)
            self.client_logic_ref.state_manager.set_connection_state(
                ConnectionState.ERROR,
                error_msg
            )

        await self._reset_connection_state()
        return False

    async def send_raw(self, data: str):
        # Re-check connection status and writer state immediately before sending
        if not self._writer or not self.connected or self._writer.is_closing(): # Added is_closing check
            self.logger.warning(
                f"Attempted to send data while not truly connected, no writer, or writer closing: {data.strip()}"
            )
            if self.client_logic_ref and hasattr(self.client_logic_ref, 'add_status_message'): # pragma: no cover
                await self.client_logic_ref.add_status_message(
                    "Cannot send: Not connected or connection closing.", "error"
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
            # Mask sensitive information before logging
            if log_data.upper().startswith("PASS "):
                log_data = "PASS ******"
            elif log_data.upper().startswith("AUTHENTICATE ") and len(log_data) > 15: # Check length to avoid splitting short non-sensitive AUTHENTICATE
                log_data = log_data.split(" ", 1)[0] + " ******"
            elif log_data.upper().startswith("PRIVMSG NICKSERV :IDENTIFY"):
                parts = log_data.split(" ", 3)
                if len(parts) >= 3: # Ensure enough parts to avoid index error
                    log_data = f"{parts[0]} {parts[1]} {parts[2]} ******"
                else: # pragma: no cover
                    log_data = "PRIVMSG NickServ :IDENTIFY ******" # Fallback if split fails unexpectedly

            self.logger.debug(f"C >> {log_data}")

            if (
                self.client_logic_ref
                and hasattr(self.client_logic_ref, "show_raw_log_in_ui")
                and self.client_logic_ref.show_raw_log_in_ui
                and hasattr(self.client_logic_ref, 'add_status_message') # Ensure method exists
            ):
                await self.client_logic_ref.add_status_message(
                    f"C >> {log_data}",
                    "system" # Use a semantic color key if available, or direct attribute
                )

            if data.upper().startswith("NICK "):
                self.is_handling_nick_collision = False # Reset flag after sending NICK
        except (
            OSError, # Covers a range of OS-level I/O errors
            ConnectionError, # More specific connection errors like ConnectionResetError
            ssl.SSLError, # Specific SSL errors during send
        ) as e: # pragma: no cover
            self.logger.error(f"Network error sending data: {e}", exc_info=False) # exc_info=False for common network errors
            if self.client_logic_ref and hasattr(self.client_logic_ref, 'add_status_message'):
                await self.client_logic_ref.add_status_message(
                    f"Error sending data: {e}", "error"
                )
                if not self.client_logic_ref.is_headless:
                    self.client_logic_ref.ui_needs_update.set()
            # Critical: Reset connection state if send fails due to network issue
            await self._reset_connection_state(
                dispatch_event=True # Ensure disconnect event is dispatched
            )
        except Exception as e_unhandled_send: # pragma: no cover
            # Catch any other unexpected errors during send
            self.logger.critical(
                f"Unhandled critical error sending data: {e_unhandled_send}", exc_info=True
            )
            if self.client_logic_ref and hasattr(self.client_logic_ref, 'add_status_message'):
                await self.client_logic_ref.add_status_message(
                    f"Critical send error: {e_unhandled_send}",
                    "error"
                )
            # Reset connection state on unhandled critical send errors
            await self._reset_connection_state(dispatch_event=True)

    async def network_loop(self) -> None:
        """Main network handling loop."""
        try:
            self.logger.info("Network loop initiated.")
            while not self._stop_event.is_set():
                if not self.connected or not self._reader or not self._writer: # Added _writer check
                    current_sm_state = self.client_logic_ref.state_manager.get_connection_state() if self.client_logic_ref else ConnectionState.DISCONNECTED

                    if current_sm_state == ConnectionState.CONNECTING:
                        self.logger.info("Network_loop: StateManager reports CONNECTING. Waiting for external connection process.")
                        await asyncio.sleep(0.2) # Wait for the explicit connect call to complete/fail
                        continue # Re-evaluate main loop condition

                    conn_info = self.client_logic_ref.state_manager.get_connection_info() if self.client_logic_ref else None
                    if conn_info and conn_info.server and conn_info.port is not None:
                        self.logger.info(
                            f"Network_loop: Not connected. Attempting to connect to {conn_info.server}:{conn_info.port}"
                        )
                        # _connect_socket will set ConnectionState.CONNECTING
                        if await self._connect_socket():
                            self.logger.info(f"Network_loop: Successfully connected via _connect_socket. self.connected: {self.connected}, StateManager: {self.client_logic_ref.state_manager.get_connection_state().name}")
                            self._disconnect_event_sent_for_current_session = False
                        else:
                            self.logger.warning(
                                f"Network_loop: _connect_socket failed. self.connected: {self.connected}. Will retry after delay."
                            )
                            self.connected = False # Ensure this is explicitly set to False if _connect_socket fails
                            await self._reset_connection_state()
                            await asyncio.sleep(self.reconnect_delay)
                            self.reconnect_delay = min(self.reconnect_delay * 2, self.config.reconnect_max_delay if self.config else 60)
                    else:
                        self.logger.debug("Network_loop: No connection parameters available, waiting...")
                        await asyncio.sleep(0.5) # Increased sleep
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
                        logger.error(f"Connection error in network loop: {e}", exc_info=True)
                        await self._reset_connection_state()
                        continue
                    except ssl.SSLError as e:
                        logger.error(f"SSL error in network loop: {e}", exc_info=True)
                        if self.client_logic_ref:
                            await self.client_logic_ref.add_status_message(f"SSL Error: {e}", "error")
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
            self.connected = False # Ensure connected is false before reset
            await self._reset_connection_state(dispatch_event=True)
            self.logger.info("Network loop ended and cleaned up.") # Modified log

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
                    # Capture client reference in case it changes during await
                    client_ref = self.client_logic_ref
                    if client_ref is None:
                        logger.warning("Skipping message processing - client_logic_ref is None")
                        continue

                    if hasattr(client_ref, 'event_manager'):
                        await client_ref.event_manager.dispatch_raw_server_message(client=client_ref, line=decoded_line)
                    else:
                        logger.warning("IRCClient_Logic instance has no event_manager")
                except UnicodeDecodeError as e:
                    logger.error(f"Error decoding received data: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing received line: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error in _process_received_data: {e}", exc_info=True)
            # Don't clear buffer on error to avoid losing data
            pass

# END OF MODIFIED FILE: network_handler.py
