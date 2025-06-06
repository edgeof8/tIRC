# START OF MODIFIED FILE: network_handler.py
import socket
import ssl
import threading
import time
import logging
from typing import List, Optional, Set, TYPE_CHECKING
from pyrc_core.app_config import (
    CONNECTION_TIMEOUT,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
)
from pyrc_core.state_manager import ConnectionState

if TYPE_CHECKING:  # To avoid circular import with client_logic
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.network")


class NetworkHandler:
    def __init__(self, client_logic_ref: "IRCClient_Logic"):
        self.client_logic_ref = client_logic_ref
        self.socket = None
        self.connected = False
        self.connection_params = None
        self._network_thread = None
        self._stop_event = threading.Event()
        self._thread_shutdown_complete = threading.Event()
        self._shutdown_timeout = 3.0  # 3 seconds timeout for shutdown
        self._force_shutdown = False
        self.logger = logging.getLogger("pyrc.network")
        self.reconnect_delay: int = RECONNECT_INITIAL_DELAY
        self.channels_to_join_on_connect: List[str] = []
        self.is_handling_nick_collision: bool = False
        self.buffer: bytes = b""
        self._disconnect_event_sent_for_current_session = False

    def start(self) -> bool:
        """Start the network handler and its thread."""
        if self._network_thread is not None and self._network_thread.is_alive():
            self.logger.warning("Network thread already running")
            return False

        self._stop_event.clear()
        self._thread_shutdown_complete.clear()
        self._force_shutdown = False
        self._network_thread = threading.Thread(target=self._network_loop, daemon=True)
        self._network_thread.start()
        return True

    def stop(self) -> bool:
        """Stop the network handler and wait for thread completion."""
        if self._network_thread is None or not self._network_thread.is_alive():
            return True

        self.logger.info("Stopping network handler...")
        self._stop_event.set()

        # Wait for thread to complete with timeout
        thread_joined = self._thread_shutdown_complete.wait(
            timeout=self._shutdown_timeout
        )

        if not thread_joined:
            self.logger.warning(
                "Network thread did not complete in time, forcing shutdown..."
            )
            self._force_shutdown = True
            # Give a brief moment for forced shutdown
            time.sleep(0.5)

            if self._network_thread.is_alive():
                self.logger.error("Network thread still alive after forced shutdown!")
                return False
            else:
                self.logger.info("Network thread terminated after forced shutdown")
                return True

        self.logger.info("Network handler stopped successfully")
        return True

    def disconnect_gracefully(self, quit_message: Optional[str] = None) -> None:
        """Disconnect from the server gracefully."""
        if self.connected and self.socket:
            try:
                if quit_message:
                    self.send_raw(f"QUIT :{quit_message}")
                else:
                    self.send_raw("QUIT :Client disconnected")
            except Exception as e:
                self.logger.error(f"Error sending QUIT message: {e}")

        self.stop()
        self.connected = False
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                self.logger.error(f"Error closing socket: {e}")
            finally:
                self.socket = None

    def update_connection_params(
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
            self.disconnect_gracefully(quit_msg)
            # Give some time for the disconnect to process if the network thread is busy
            if self._network_thread and self._network_thread.is_alive():
                self._network_thread.join(timeout=1.0)

        if channels_to_join is not None:
            self.channels_to_join_on_connect = channels_to_join
        else:  # Fallback to connection info's initial channels if not provided
            conn_info = (
                self.client_logic_ref.state_manager.get_connection_info()
                if self.client_logic_ref
                else None
            )
            self.channels_to_join_on_connect = (
                conn_info.initial_channels[:]
                if conn_info and conn_info.initial_channels
                else []
            )

        self.reconnect_delay = RECONNECT_INITIAL_DELAY

        if not self._network_thread or not self._network_thread.is_alive():
            logger.info("Network thread not running, starting it after param update.")
            self.start()
        else:
            logger.debug(
                "Network thread is alive. Setting connected=False to force re-evaluation in loop."
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

    def send_cap_ls(self, version: Optional[str] = "302"):
        if self.connected and self.socket:
            if version:
                self.send_raw(f"CAP LS {version}")
            else:
                self.send_raw("CAP LS")
        else:
            logger.warning("send_cap_ls called but not connected or no socket.")

    def send_cap_req(self, capabilities: List[str]):
        if self.connected and self.socket:
            if capabilities:
                self.send_raw(f"CAP REQ :{ ' '.join(capabilities)}")
        else:
            logger.warning("send_cap_req called but not connected or no socket.")

    def send_cap_end(self):
        if self.connected and self.socket:  # Check socket as well
            logger.debug("Sending CAP END")
            self.send_raw("CAP END")
        else:
            logger.warning("send_cap_end called but not connected or no socket.")

    def send_authenticate(self, payload: str):
        if self.connected and self.socket:  # Check socket
            logger.debug(f"Sending AUTHENTICATE {payload[:20]}...")
            self.send_raw(f"AUTHENTICATE {payload}")
        else:
            logger.warning("send_authenticate called but not connected or no socket.")

# In pyrc_core/network_handler.py

    def _reset_connection_state(self, dispatch_event: bool = True):
        logger.debug(
            f"Resetting connection state. Dispatch disconnect event: {dispatch_event}"
        )

        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except (OSError, socket.error):
                pass
            try:
                self.socket.close()
                logger.debug("Socket closed by _reset_connection_state.")
            except (OSError, socket.error):
                pass
            self.socket = None

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


    def _connect_socket(self):
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

        # Update connection state to CONNECTING
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
                f"Attempting socket connection to {server}:{port} (SSL: {use_ssl})"
            )
            sock = socket.create_connection(
                (server, port),
                timeout=float(CONNECTION_TIMEOUT) if CONNECTION_TIMEOUT is not None else None,
            )
            logger.debug("Socket created.")
            if use_ssl:
                logger.debug("SSL is enabled, wrapping socket.")
                context = ssl.create_default_context()
                try:
                    context.minimum_version = (
                        ssl.TLSVersion.TLSv1_2
                    )  # More secure default
                    logger.info(
                        f"Set SSLContext minimum_version to TLSv1_2 for {self.client_logic_ref.server}"
                    )
                except AttributeError:
                    logger.warning(
                        "ssl.TLSVersion.TLSv1_2 not available, or context does not support minimum_version (older Python?). Default TLS settings will be used."
                    )

                logger.info(
                    f"VERIFY_SSL_CERT value in _connect_socket for {server}: {conn_info.verify_ssl_cert}"
                )
                verify_ssl = conn_info.verify_ssl_cert if conn_info.verify_ssl_cert is not None else True
                if not verify_ssl:
                    logger.warning(
                        "SSL certificate verification is DISABLED. This is insecure."
                    )
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                sock = context.wrap_socket(
                    sock, server_hostname=server
                )
                logger.debug("Socket wrapped with SSL.")

            self.socket = sock
            self.connected = True
            self.reconnect_delay = RECONNECT_INITIAL_DELAY
            logger.info(
                f"Successfully connected to {server}:{port}. SSL: {use_ssl}"
            )
            # Update connection state to CONNECTED
            self.client_logic_ref.state_manager.set_connection_state(ConnectionState.CONNECTED)

            # Start CAP negotiation if available
            if (
                hasattr(self.client_logic_ref, "cap_negotiator")
                and self.client_logic_ref.cap_negotiator
            ):
                self.client_logic_ref.cap_negotiator.start_negotiation()
            else:
                logger.error(
                    "NetworkHandler: cap_negotiator not found on client object during _connect_socket."
                )
                self.client_logic_ref._add_status_message(
                    "Error: CAP negotiator not initialized.", "error"
                )

            # Dispatch connection event
            if (
                self.client_logic_ref
                and hasattr(self.client_logic_ref, "event_manager")
                and self.client_logic_ref.event_manager
            ):  # Check for event_manager
                self.client_logic_ref.event_manager.dispatch_client_connected(
                    server=server,
                    port=port,
                    nick=conn_info.nick or "",
                    ssl=use_ssl,
                    raw_line="",
                )

            return True
        except socket.timeout as e:
            error_msg = f"Connection to {server}:{port} timed out"
            logger.warning(error_msg)
            self.client_logic_ref.state_manager.set_connection_state(
                ConnectionState.ERROR,
                error=error_msg
            )
        except socket.gaierror as e:
            error_msg = f"Hostname {self.client_logic_ref.server} could not be resolved: {e}"
            logger.error(error_msg)
            self.client_logic_ref.state_manager.set_connection_state(
                ConnectionState.ERROR,
                error=error_msg
            )
        except ConnectionRefusedError as e:
            error_msg = f"Connection refused by {server}:{port}: {e}"
            logger.error(error_msg)
            self.client_logic_ref.state_manager.set_connection_state(
                ConnectionState.ERROR,
                error=error_msg
            )
        except ssl.SSLError as e:
            error_msg = f"SSL Error during connection: {e}"
            logger.error(error_msg, exc_info=True)
            self.client_logic_ref.state_manager.set_connection_state(
                ConnectionState.ERROR,
                error=error_msg
            )
        except Exception as e:
            error_msg = f"Unexpected error during connection: {e}"
            logger.error(error_msg, exc_info=True)
            self.client_logic_ref.state_manager.set_connection_state(
                ConnectionState.ERROR,
                error=error_msg
            )

        self._reset_connection_state()
        return False

    def send_raw(self, data: str):
        # Re-check connection status immediately before sending
        if not self.socket or not self.connected:
            logger.warning(
                f"Attempted to send data while not truly connected or no socket: {data.strip()}"
            )
            if (
                self.client_logic_ref
            ):  # Only add message if client and thus UI/context manager exists
                self.client_logic_ref._add_status_message(
                    "Cannot send: Not connected.", "error"
                )
                if not self.client_logic_ref.is_headless:
                    self.client_logic_ref.ui_needs_update.set()
            return

        try:
            if not data.endswith("\r\n"):
                data += "\r\n"
            self.socket.sendall(data.encode("utf-8", errors="replace"))

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
                self.client_logic_ref  # Check if client exists
                and hasattr(self.client_logic_ref, "show_raw_log_in_ui")
                and self.client_logic_ref.show_raw_log_in_ui
            ):
                self.client_logic_ref.add_message(
                    f"C >> {log_data}",
                    "system",
                    context_name="Status",
                    prefix_time=True,
                )

            if data.upper().startswith("NICK "):
                self.is_handling_nick_collision = False
        except (
            OSError,
            socket.error,
            ssl.SSLError,
        ) as e:  # Catch broader socket/SSL errors
            logger.error(f"Error sending data: {e}", exc_info=True)
            if self.client_logic_ref:
                self.client_logic_ref._add_status_message(
                    f"Error sending data: {e}", "error"
                )
                if not self.client_logic_ref.is_headless:
                    self.client_logic_ref.ui_needs_update.set()
            self._reset_connection_state(
                dispatch_event=True
            )  # Dispatch disconnect on send error
        except Exception as e_unhandled_send:  # Catch any other unexpected error
            logger.critical(
                f"Unhandled error sending data: {e_unhandled_send}", exc_info=True
            )
            if self.client_logic_ref:
                self.client_logic_ref.add_message(
                    f"Critical send error: {e_unhandled_send}",
                    "error",
                    context_name="Status",
                )
            self._reset_connection_state(dispatch_event=True)

    def _network_loop(self) -> None:
        """Main network handling loop."""
        try:
            while not self._stop_event.is_set():
                if not self.connected or not self.socket:
                    # Attempt to connect if we have connection parameters
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
                        if self._connect_socket():
                            logger.info("Successfully connected to server")
                            self.connected = True
                        else:
                            logger.warning(
                                "Failed to connect, will retry in next iteration"
                            )
                            time.sleep(0.1)  # Small delay before retry
                    else:
                        logger.debug("No connection parameters available, waiting...")
                        time.sleep(0.1)
                    continue

                try:
                    # Set a timeout for socket operations
                    self.socket.settimeout(0.5)
                    data = self.socket.recv(4096)

                    if not data:
                        logger.info("Connection closed by server")
                        self._reset_connection_state()
                        continue

                    # Process received data
                    self._process_received_data(data)

                except socket.timeout:
                    continue
                except ConnectionError as e:
                    logger.error(f"Connection error: {e}")
                    self._reset_connection_state()
                    continue
                except Exception as e:
                    logger.error(f"Error in network loop: {e}")
                    self._reset_connection_state()
                    continue

        except Exception as e:
            logger.error(f"Critical error in network loop: {e}")
        finally:
            # Ensure cleanup happens even if there's an error
            if not self._force_shutdown:
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except Exception as e:
                        logger.error(f"Error closing socket in cleanup: {e}")
                    finally:
                        self.socket = None

            self._thread_shutdown_complete.set()
            logger.info("Network thread shutdown complete")

    def _process_received_data(self, data: bytes) -> None:
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
                        self.client_logic_ref.handle_server_message(decoded_line)
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
