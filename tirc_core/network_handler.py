# START OF MODIFIED FILE: network_handler.py
import asyncio
import inspect
import socket
import ssl
import logging
import concurrent.futures
from typing import List, Optional, Set, cast, TYPE_CHECKING, Coroutine, Any  # Added TYPE_CHECKING
from tirc_core.app_config import AppConfig
from tirc_core.state_manager import ConnectionState, ConnectionInfo

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic  # Guarded import


logger = logging.getLogger("tirc.network")


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
        self.logger = logging.getLogger("tirc.network")
        self.reconnect_delay: int = self.config.reconnect_initial_delay
        self.channels_to_join_on_connect: List[str] = []
        self.is_handling_nick_collision: bool = False
        self.buffer: bytes = b""
        self._disconnect_event_sent_for_current_session = False
        self._reset_lock = asyncio.Lock()

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
        """Stop the network handler and wait for task completion if the loop is running."""
        if self._network_task is None or self._network_task.done():
            self.logger.debug("Network task already None or done in stop().")
            if self._network_task and self._network_task.done(): # Ensure it's cleared if done
                 self._network_task = None
            return True

        self.logger.info(f"Stopping network handler (task ID: {id(self._network_task)})...")
        self._stop_event.set()  # Signal the loop to stop

        loop = asyncio.get_event_loop()

        if not loop.is_closed():
            self.logger.debug(f"Event loop is not closed. Attempting graceful stop for task {id(self._network_task)}.")
            try:
                # Give the task a chance to finish cleanly after _stop_event is set
                await asyncio.wait_for(self._network_task, timeout=1.0)
                self.logger.info(f"Network task {id(self._network_task)} stopped successfully after wait_for.")
            except asyncio.TimeoutError:
                self.logger.warning(f"Network task {id(self._network_task)} did not complete in time via wait_for, cancelling...")
                if not self._network_task.done():  # Check again before cancelling
                    self._network_task.cancel()
                    try:
                        await self._network_task  # Await cancellation
                    except asyncio.CancelledError:
                        self.logger.info(f"Network task {id(self._network_task)} successfully cancelled.")
                    except Exception as e_await_cancel: # pragma: no cover
                        self.logger.error(f"Error awaiting cancelled network task {id(self._network_task)}: {e_await_cancel}", exc_info=True)
            except Exception as e_wait: # pragma: no cover
                self.logger.error(f"Error waiting for network task {id(self._network_task)}: {e_wait}", exc_info=True)
                if not self._network_task.done():
                    self._network_task.cancel()
                    self.logger.info(f"Network task {id(self._network_task)} cancelled due to other error during wait.")
        else: # pragma: no cover
            self.logger.warning(f"Event loop is closed. Attempting to cancel network task {id(self._network_task)} without awaiting.")
            if not self._network_task.done():
                self._network_task.cancel()
                self.logger.info(f"Network task {id(self._network_task)} cancellation requested (loop closed).")

        # Final check on task status
        if self._network_task and self._network_task.done():
            self.logger.info(f"Network task (ID: {id(self._network_task)}) is confirmed done.")
            try: # Accessing result or exception after done() can be informative
                if self._network_task.cancelled():
                    self.logger.info(f"Network task {id(self._network_task)} was cancelled (final check).")
                elif self._network_task.exception(): # pragma: no cover
                    self.logger.warning(f"Network task {id(self._network_task)} finished with exception: {self._network_task.exception()}")
            except asyncio.InvalidStateError: # pragma: no cover
                 self.logger.debug(f"Network task {id(self._network_task)} state was invalid for exception/cancelled check.")
            self._network_task = None  # Clear the task reference
            return True
        elif self._network_task is None: # Already cleared
            return True
        else: # pragma: no cover
            self.logger.error(f"Network task (ID: {id(self._network_task)}) still not done after stop attempts.")
            return False

    async def disconnect_gracefully(self, quit_message: Optional[str] = None) -> None:
        """Disconnect from the server gracefully."""
        self.logger.debug(f"disconnect_gracefully called. Connected: {self.connected}, Writer: {self._writer is not None}")
        if self.connected and self._writer and not self._writer.is_closing():
            try:
                if quit_message:
                    await self.send_raw(f"QUIT :{quit_message}")
                else:
                    await self.send_raw("QUIT :Client disconnected")
            except Exception as e: # pragma: no cover
                self.logger.error(f"Error sending QUIT message: {e}")

        # Ensure the network task is stopped first. This will handle reader/writer closure.
        await self.stop()

        # After stop(), _reader and _writer should ideally be None or closing.
        # Call _reset_connection_state to ensure all state is clean and disconnect event is dispatched.
        # This also handles any lingering reader/writer cleanup.
        self.logger.debug("disconnect_gracefully: Calling _reset_connection_state for final cleanup.")
        await self._reset_connection_state(dispatch_event=True)
        self.connected = False # Ensure connected flag is false after full cleanup


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
            conn_info = self.client_logic_ref.state_manager.get_connection_info()
            if conn_info and conn_info.initial_channels:
                self.channels_to_join_on_connect = conn_info.initial_channels[:]
            else:
                self.channels_to_join_on_connect = []

        self.reconnect_delay = self.config.reconnect_initial_delay

        if not self._network_task or self._network_task.done():
            logger.info("Network task not running, starting it after param update.")
        else:
            logger.debug(
                "Network task is alive. Setting connected=False to force re-evaluation in loop."
            )
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
            self.connected = False

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

    async def _reset_connection_state(self, dispatch_event: bool = True):
        async with self._reset_lock:
            self.logger.info(
                f"Resetting connection state. Dispatch disconnect event: {dispatch_event}. Called by: {inspect.stack()[1].filename}:{inspect.stack()[1].lineno} - {inspect.stack()[1].function}"
            )

        was_connected = self.connected
        self.connected = False
        self.is_handling_nick_collision = False

        if self._reader and not self._reader.at_eof():
            self.logger.debug("Calling feed_eof() on existing reader before reset.")
            self._reader.feed_eof()
        old_reader = self._reader
        self._reader = None

        writer_to_close = self._writer
        self._writer = None

        if writer_to_close:
            try:
                if not writer_to_close.is_closing():
                    self.logger.debug("Calling writer.close() in _reset_connection_state.")
                    writer_to_close.close()
                    # Await wait_closed to ensure the transport is fully shut down
                    try:
                        await asyncio.wait_for(writer_to_close.wait_closed(), timeout=5.0)
                        self.logger.debug("Writer.wait_closed() completed in _reset_connection_state.")
                    except asyncio.TimeoutError:
                        self.logger.warning("Timeout waiting for writer to close in _reset_connection_state.")
                    except Exception as e_wc: # pragma: no cover
                        self.logger.error(f"Error during writer.wait_closed() in _reset_connection_state: {e_wc}", exc_info=True)
                else:
                    self.logger.debug("Writer was already closing in _reset_connection_state.")
            except Exception as e:
                self.logger.error(f"Error handling writer in _reset_connection_state: {e}", exc_info=True)

        # Explicitly set to None after attempting closure
        self._reader = None
        self._writer = None
        # No need to 'del' explicitly, Python's GC handles it

        if self.client_logic_ref:
            current_sm_state = self.client_logic_ref.state_manager.get_connection_state()
            if current_sm_state not in [ConnectionState.DISCONNECTED, ConnectionState.ERROR, ConnectionState.CONFIG_ERROR]:
                 await self.client_logic_ref.state_manager.set_connection_state(ConnectionState.DISCONNECTED)

            if hasattr(self.client_logic_ref, "cap_negotiator") and self.client_logic_ref.cap_negotiator:
                await self.client_logic_ref.cap_negotiator.reset_negotiation_state()
            if hasattr(self.client_logic_ref, "sasl_authenticator") and self.client_logic_ref.sasl_authenticator:
                self.client_logic_ref.sasl_authenticator.reset_authentication_state()
            if hasattr(self.client_logic_ref, "registration_handler") and self.client_logic_ref.registration_handler:
                self.client_logic_ref.registration_handler.reset_registration_state()

            if (
                dispatch_event
                and was_connected
                and not self._disconnect_event_sent_for_current_session
            ):
                conn_info_snapshot_dict = self.client_logic_ref.state_manager.get("connection_info_snapshot")
                conn_info_to_use: Optional[ConnectionInfo] = None

                if isinstance(conn_info_snapshot_dict, dict):
                    try:
                        conn_info_to_use = ConnectionInfo(**conn_info_snapshot_dict)
                    except TypeError:
                        self.logger.warning("Failed to reconstruct ConnectionInfo from snapshot in _reset_connection_state.")
                        conn_info_to_use = self.client_logic_ref.state_manager.get_connection_info()
                else:
                    conn_info_to_use = self.client_logic_ref.state_manager.get_connection_info()

                if conn_info_to_use and conn_info_to_use.server and conn_info_to_use.port is not None:
                    await self.client_logic_ref.event_manager.dispatch_client_disconnected(
                        conn_info_to_use.server, conn_info_to_use.port, raw_line=""
                    )
                    self._disconnect_event_sent_for_current_session = True
                    await self.client_logic_ref.state_manager.delete("connection_info_snapshot") # await delete
                else:
                    self.logger.warning("Could not dispatch disconnect event: server/port info missing.")

        self.buffer = b""
        self.logger.debug("Connection state reset complete")

    async def _connect_socket(self) -> bool:
        self.logger.info(f"NetworkHandler._connect_socket: Entered. Current connected state: {self.connected}")
        self.is_handling_nick_collision = False
        conn_info = (
            self.client_logic_ref.state_manager.get_connection_info()
            if self.client_logic_ref
            else None
        )
        if not conn_info or not conn_info.server or conn_info.port is None:
            error_msg = "Server or port not configured"
            self.logger.error(f"NetworkHandler._connect_socket: {error_msg}")
            if self.client_logic_ref:
                await self.client_logic_ref.state_manager.set_connection_state(
                    ConnectionState.ERROR, error_msg
                )
            return False

        if self.client_logic_ref:
            await self.client_logic_ref.state_manager.set_connection_state(ConnectionState.CONNECTING)
        try:
            if not conn_info: # Should be caught above, but defensive
                error_msg = "Cannot connect - no connection info (secondary check)"
                self.logger.error(error_msg)
                if self.client_logic_ref:
                    await self.client_logic_ref.state_manager.set_connection_state(ConnectionState.ERROR, error=error_msg)
                return False

            server, port, use_ssl = conn_info.server, conn_info.port, conn_info.ssl

            self.logger.info(f"Attempting asyncio.open_connection to {server}:{port} (SSL: {use_ssl})")
            ssl_context = None
            if use_ssl:
                self.logger.debug("SSL enabled, creating SSL context.")
                ssl_context = ssl.create_default_context()
                try:
                    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                    self.logger.info(f"Set SSLContext minimum_version to TLSv1_2 for {server}")
                except AttributeError:
                    self.logger.warning("ssl.TLSVersion.TLSv1_2 not available. Default TLS settings.")

                verify_ssl = conn_info.verify_ssl_cert if conn_info.verify_ssl_cert is not None else True
                if not verify_ssl:
                    self.logger.warning("SSL certificate verification DISABLED.")
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                else:
                    ssl_context.check_hostname = True
                    ssl_context.verify_mode = ssl.CERT_REQUIRED
                    self.logger.info(f"SSL certificate verification ENABLED for {server}.")

            self._reader, self._writer = await asyncio.open_connection(server, port, ssl=ssl_context, limit=4096)
            logger.debug("Asyncio connection established.")
            self.connected = True
            self.reconnect_delay = self.config.reconnect_initial_delay
            logger.info(f"Successfully connected to {server}:{port}. SSL: {use_ssl}")
            await self.client_logic_ref.state_manager.set_connection_state(ConnectionState.CONNECTED)

            if hasattr(self.client_logic_ref, "cap_negotiator") and self.client_logic_ref.cap_negotiator:
                self.logger.debug("CapNegotiator found. RegistrationHandler will start negotiation.")
            else: # Should not happen if setup is correct
                logger.warning("CapNegotiator not found. CAP negotiation will not start.")
                await self.client_logic_ref.add_status_message("Warning: CAP negotiator not initialized.", "warning")

            if hasattr(self.client_logic_ref, "registration_handler") and self.client_logic_ref.registration_handler:
                await self.client_logic_ref.registration_handler.on_connection_established()
            else: # Should not happen
                logger.error("RegistrationHandler not found.")
                await self.client_logic_ref.add_status_message("Error: Registration handler not initialized.", "error")
                return False

            if self.client_logic_ref and hasattr(self.client_logic_ref, "event_manager"):
                await self.client_logic_ref.event_manager.dispatch_client_connected(
                    server=server, port=port, nick=conn_info.nick or "", ssl=use_ssl, raw_line=""
                )
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, socket.gaierror, ssl.SSLError) as e:
            error_msg = f"Connection error to {server}:{port}: {e}"
            logger.error(error_msg, exc_info=True)
            if self.client_logic_ref:
                await self.client_logic_ref.state_manager.set_connection_state(ConnectionState.ERROR, error_msg)
            self._reader, self._writer = None, None
            return False
        except Exception as e:
            error_msg = f"Unexpected error during connection: {e}"
            logger.critical(error_msg, exc_info=True)
            if self.client_logic_ref:
                await self.client_logic_ref.state_manager.set_connection_state(ConnectionState.ERROR, error_msg)
            self._reader, self._writer = None, None
            return False

    async def send_raw(self, data: str):
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            self.logger.error(f"send_raw: Event loop closed. Cannot send: {data.strip()}")
            return
        if not self._writer or self._writer.is_closing():
            self.logger.error(f"send_raw: StreamWriter None or closing. Cannot send: {data.strip()}")
            return
        if not self.connected and not data.upper().startswith("QUIT"):
            self.logger.warning(f"send_raw: Not connected. Attempted to send: {data.strip()}")
            if self.client_logic_ref and hasattr(self.client_logic_ref, 'add_status_message'):
                await self.client_logic_ref.add_status_message("Cannot send: Not connected.", "error")
            return

        try:
            if not data.endswith("\r\n"):
                data += "\r\n"
            self._writer.write(data.encode("utf-8", errors="replace"))
            await self._writer.drain()
            log_data = data.strip()
            if log_data.upper().startswith("PASS "): log_data = "PASS ******"
            elif log_data.upper().startswith("AUTHENTICATE ") and len(log_data) > 15: log_data = log_data.split(" ", 1)[0] + " ******"
            elif log_data.upper().startswith("PRIVMSG NICKSERV :IDENTIFY"):
                parts = log_data.split(" ", 3)
                log_data = f"{parts[0]} {parts[1]} {parts[2]} ******" if len(parts) >= 3 else "PRIVMSG NickServ :IDENTIFY ******"
            self.logger.debug(f"C >> {log_data}")
            if self.client_logic_ref and self.client_logic_ref.show_raw_log_in_ui and hasattr(self.client_logic_ref, 'add_status_message'):
                await self.client_logic_ref.add_status_message(f"C >> {log_data}", "system")
            if data.upper().startswith("NICK "): self.is_handling_nick_collision = False
        except (OSError, ConnectionError, ssl.SSLError, RuntimeError) as e:
            self.logger.error(f"Network error sending data ('{data.strip()}'): {e}", exc_info=False)
            if self.client_logic_ref and hasattr(self.client_logic_ref, 'add_status_message'):
                await self.client_logic_ref.add_status_message(f"Error sending data: {e}", "error")
                if not self.client_logic_ref.is_headless: self.client_logic_ref.ui_needs_update.set()
            if not loop.is_closed(): await self._reset_connection_state(dispatch_event=True)
            else: self.logger.warning("Loop closed, cannot reset state after send error."); self.connected = False
        except Exception as e_unhandled_send:
            self.logger.critical(f"Unhandled critical error sending data ('{data.strip()}'): {e_unhandled_send}", exc_info=True)
            if self.client_logic_ref and hasattr(self.client_logic_ref, 'add_status_message'):
                await self.client_logic_ref.add_status_message(f"Critical send error: {e_unhandled_send}", "error")
            if not loop.is_closed(): await self._reset_connection_state(dispatch_event=True)
            else: self.logger.warning("Loop closed, cannot reset state after critical send error."); self.connected = False

    async def network_loop(self) -> None:
        try:
            self.logger.info("Network loop initiated.")
            if not await self._connect_socket():
                self.logger.error("Initial connection failed. Exiting loop.")
                return
            self.logger.info(f"Network_loop: Successfully connected. self.connected: {self.connected}, State: {self.client_logic_ref.state_manager.get_connection_state().name if self.client_logic_ref else 'N/A'}")
            self._disconnect_event_sent_for_current_session = False
            await asyncio.sleep(0.1)

            while not self._stop_event.is_set():
                if not self.connected or not self._reader or not self._writer:
                    self.logger.warning("Loop: Not connected or streams lost. Exiting.")
                    break
                try:
                    data_chunk = await self._reader.read(4096)
                    self.logger.debug(f"Raw data chunk read: {data_chunk!r}")
                    if not data_chunk:
                        self.logger.info("Connection closed by server (empty read).")
                        if self.client_logic_ref and self.client_logic_ref.state_manager.get_connection_state() != ConnectionState.DISCONNECTED:
                            await self.client_logic_ref.state_manager.set_connection_state(ConnectionState.DISCONNECTED, "Connection closed by server")
                        break
                    await self._process_received_data(data_chunk)
                except asyncio.IncompleteReadError as e:
                    self.logger.info(f"Server closed connection (IncompleteReadError): {e}.")
                    break
                except ConnectionError as e:
                    self.logger.error(f"Connection error in loop: {e}.", exc_info=True)
                    break
                except ssl.SSLError as e:
                    self.logger.error(f"SSL error in loop: {e}.", exc_info=True)
                    if "APPLICATION_DATA_AFTER_CLOSE_NOTIFY" in str(e) and self.client_logic_ref:
                        await self.client_logic_ref.add_status_message("SSL Error: Server closed unexpectedly (close_notify).", "error")
                    elif self.client_logic_ref:
                        await self.client_logic_ref.add_status_message(f"SSL Error in loop: {e}", "error")
                    break
                except RuntimeError as e_runtime:
                    self.logger.error(f"RuntimeError in network loop: {e_runtime}.", exc_info=True)
                    if self.client_logic_ref:
                        await self.client_logic_ref.state_manager.set_connection_state(ConnectionState.ERROR, f"RuntimeError: {e_runtime}")
                    break
                except Exception as e:
                    self.logger.error(f"Unhandled error in loop: {e}.", exc_info=True)
                    break
        except asyncio.CancelledError:
            self.logger.info("Network loop task cancelled.")
        except Exception as e_outer:
            self.logger.critical(f"Critical error in network_loop structure: {e_outer}", exc_info=True)
        finally:
            self.logger.info("Network loop ending. Final cleanup...")
            await self._reset_connection_state(dispatch_event=True)
            self.logger.info("Network loop cleanup complete.")

    async def _process_received_data(self, data: bytes) -> None:
        try:
            self.buffer += data
            while b"\r\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\r\n", 1)
                try:
                    decoded_line = line.decode("utf-8", errors="replace")
                    self.logger.debug(f"Dispatching: {decoded_line.strip()}")
                    client_ref = self.client_logic_ref
                    if client_ref and hasattr(client_ref, 'event_manager'):
                        await client_ref.event_manager.dispatch_raw_server_message(client=client_ref, line=decoded_line)
                    elif client_ref:
                        logger.warning("Client has no event_manager.")
                    else:
                        logger.warning("client_logic_ref is None in _process_received_data.")
                except UnicodeDecodeError as e:
                    logger.error(f"Decoding error: {e}")
                except Exception as e:
                    logger.error(f"Error processing line: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error in _process_received_data: {e}", exc_info=True)
