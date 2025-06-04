# START OF MODIFIED FILE: network_handler.py
import socket
import ssl
import threading
import time
import logging
from typing import List, Optional, Set, TYPE_CHECKING # Added TYPE_CHECKING
from config import (
    CONNECTION_TIMEOUT,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
)

if TYPE_CHECKING: # To avoid circular import with client_logic
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.network")


class NetworkHandler:
    def __init__(self, client_ref: "IRCClient_Logic"): # Type hint client_ref
        self.client = client_ref
        logger.debug("NetworkHandler initialized.")
        self.sock: Optional[socket.socket] = None
        self.connected: bool = False
        self.reconnect_delay: int = RECONNECT_INITIAL_DELAY
        self.network_thread: Optional[threading.Thread] = None
        self._should_thread_stop: threading.Event = threading.Event()
        self.channels_to_join_on_connect: List[str] = []
        self.is_handling_nick_collision: bool = False
        # self.running = True # This seems redundant with _should_thread_stop
        self.buffer: bytes = b""
        self._disconnect_event_sent_for_current_session = False

    def start(self):
        if self.network_thread and self.network_thread.is_alive():
            logger.warning("Network thread start requested, but already running.")
            return
        logger.info("Starting network thread.")
        self._should_thread_stop.clear()
        self.network_thread = threading.Thread(target=self._network_loop, daemon=True)
        self.network_thread.start()
        logger.debug("Network thread object created and started.")

    def stop(self):
        """Stop the network handler and clean up resources."""
        logger.info(
            "NetworkHandler.stop() called. Signaling network thread and client to quit."
        )
        self._should_thread_stop.set()
        if self.client:
            self.client.should_quit = True
        logger.info("NetworkHandler.stop() has signaled network thread.")

    def disconnect_gracefully(self, quit_message="Client disconnecting"):
        """Disconnect from the server gracefully with a quit message."""
        logger.info(
            f"NetworkHandler.disconnect_gracefully called with message: {quit_message}"
        )
        if self.client:
            self.client._final_quit_message = (
                quit_message
            )
        self.stop()

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
            current_server_lower = (
                self.client.server.lower() if self.client.server else ""
            )
            new_server_lower = server.lower()
            quit_msg = (
                f"Changing to {server}"
                if current_server_lower != new_server_lower
                else "Reconnecting"
            )
            self.disconnect_gracefully(quit_msg)
            # Give some time for the disconnect to process if the network thread is busy
            if self.network_thread and self.network_thread.is_alive():
                 self.network_thread.join(timeout=1.0)


        if channels_to_join is not None:
            self.channels_to_join_on_connect = channels_to_join
        else: # Fallback to client's initial list if not provided
            self.channels_to_join_on_connect = self.client.initial_channels_list[:] if self.client else []


        self.reconnect_delay = RECONNECT_INITIAL_DELAY

        if not self.network_thread or not self.network_thread.is_alive():
            logger.info("Network thread not running, starting it after param update.")
            self.start()
        else:
            logger.debug(
                "Network thread is alive. Setting connected=False to force re-evaluation in loop."
            )
            # Reset critical handshake components
            if hasattr(self.client, "cap_negotiator") and self.client.cap_negotiator:
                self.client.cap_negotiator.reset_negotiation_state()
            if (
                hasattr(self.client, "sasl_authenticator")
                and self.client.sasl_authenticator
            ):
                self.client.sasl_authenticator.reset_authentication_state()
            if (
                hasattr(self.client, "registration_handler")
                and self.client.registration_handler
            ):
                self.client.registration_handler.reset_registration_state()

            self.connected = False # This will trigger _connect_socket in the loop

    def send_cap_ls(self, version: Optional[str] = "302"):
        if self.connected and self.sock:
            if version:
                self.send_raw(f"CAP LS {version}")
            else:
                self.send_raw("CAP LS")
        else:
            logger.warning("send_cap_ls called but not connected or no socket.")

    def send_cap_req(self, capabilities: List[str]):
        if self.connected and self.sock:
            if capabilities:
                self.send_raw(f"CAP REQ :{ ' '.join(capabilities)}")
        else:
            logger.warning("send_cap_req called but not connected or no socket.")

    def send_cap_end(self):
        if self.connected and self.sock: # Check socket as well
            logger.debug("Sending CAP END")
            self.send_raw("CAP END")
        else:
            logger.warning("send_cap_end called but not connected or no socket.")


    def send_authenticate(self, payload: str):
        if self.connected and self.sock: # Check socket
            logger.debug(f"Sending AUTHENTICATE {payload[:20]}...")
            self.send_raw(f"AUTHENTICATE {payload}")
        else:
            logger.warning("send_authenticate called but not connected or no socket.")


    def _reset_connection_state(self, dispatch_event: bool = True):
        logger.debug(
            f"Resetting connection state. Dispatch disconnect event: {dispatch_event}"
        )

        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR) # Politely shutdown read/write
            except (OSError, socket.error):
                pass # Ignore if already closed or not connected
            try:
                self.sock.close()
                logger.debug(
                    "Socket closed by _reset_connection_state."
                )
            except (OSError, socket.error):
                pass
            self.sock = None

        was_connected = self.connected
        self.connected = False
        self.is_handling_nick_collision = False

        if self.client:
            if hasattr(self.client, "cap_negotiator") and self.client.cap_negotiator:
                self.client.cap_negotiator.reset_negotiation_state()
            if (
                hasattr(self.client, "sasl_authenticator")
                and self.client.sasl_authenticator
            ):
                self.client.sasl_authenticator.reset_authentication_state()
            if (
                hasattr(self.client, "registration_handler")
                and self.client.registration_handler
            ):
                self.client.registration_handler.reset_registration_state()

            if (
                dispatch_event
                and was_connected
                and not self._disconnect_event_sent_for_current_session
            ):
                if hasattr(self.client, "script_manager"):
                    current_server = self.client.server
                    current_port = self.client.port
                    logger.info(
                        f"Dispatching CLIENT_DISCONNECTED event from _reset_connection_state for {current_server}:{current_port}"
                    )
                    self.client.script_manager.dispatch_event(
                        "CLIENT_DISCONNECTED",
                        {"server": current_server, "port": current_port},
                    )
                    self._disconnect_event_sent_for_current_session = True
        self.buffer = b""
        logger.debug("Connection state reset complete")

    def _connect_socket(self):
        self.is_handling_nick_collision = False
        if not self.client or not self.client.server or self.client.port is None:
            logger.error("NetworkHandler._connect_socket: Client server/port not configured.")
            if self.client: # Add message only if client exists
                self.client.add_message(
                    "Cannot connect: Server or port not configured.",
                    self.client.ui.colors["error"],
                    context_name="Status",
                )
            return False

        self.client.add_message(
            f"Attempting to connect to {self.client.server}:{self.client.port}...",
            self.client.ui.colors["system"],
            context_name="Status",
        )
        try:
            logger.info(
                f"Attempting socket connection to {self.client.server}:{self.client.port} (SSL: {self.client.use_ssl})"
            )
            sock = socket.create_connection(
                (self.client.server, self.client.port), timeout=CONNECTION_TIMEOUT
            )
            logger.debug("Socket created.")
            if self.client.use_ssl:
                logger.debug("SSL is enabled, wrapping socket.")
                context = ssl.create_default_context()
                try:
                    context.minimum_version = ssl.TLSVersion.TLSv1_2 # More secure default
                    logger.info(
                        f"Set SSLContext minimum_version to TLSv1_2 for {self.client.server}"
                    )
                except AttributeError:
                    logger.warning(
                        "ssl.TLSVersion.TLSv1_2 not available, or context does not support minimum_version (older Python?). Default TLS settings will be used."
                    )

                logger.info(
                    f"VERIFY_SSL_CERT value in _connect_socket for {self.client.server}: {self.client.verify_ssl_cert}"
                )
                if not self.client.verify_ssl_cert:
                    logger.warning(
                        "SSL certificate verification is DISABLED. This is insecure."
                    )
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                sock = context.wrap_socket(sock, server_hostname=self.client.server)
                logger.debug("Socket wrapped with SSL.")

            self.sock = sock
            self.connected = True
            self.reconnect_delay = RECONNECT_INITIAL_DELAY
            logger.info(
                f"Successfully connected to {self.client.server}:{self.client.port}. SSL: {self.client.use_ssl}"
            )
            self.client.add_message(
                f"Connected. SSL: {'Yes' if self.client.use_ssl else 'No'}",
                self.client.ui.colors["system"],
                context_name="Status",
            )

            if hasattr(self.client, "cap_negotiator") and self.client.cap_negotiator:
                self.client.cap_negotiator.start_negotiation()
            else:
                logger.error(
                    "NetworkHandler: cap_negotiator not found on client object during _connect_socket."
                )
                self.client.add_message(
                    "Error: CAP negotiator not initialized.",
                    self.client.ui.colors["error"],
                    context_name="Status",
                )

            if self.client and hasattr(self.client, "script_manager"):
                self.client.script_manager.dispatch_event(
                    "CLIENT_CONNECTED",
                    {
                        "server": self.client.server,
                        "port": self.client.port,
                        "nick": self.client.nick,
                        "ssl": self.client.use_ssl,
                    },
                )

            return True
        except socket.timeout:
            logger.warning(
                f"Connection to {self.client.server}:{self.client.port} timed out."
            )
            self.client.add_message(
                f"Connection to {self.client.server}:{self.client.port} timed out.",
                self.client.ui.colors["error"],
                context_name="Status",
            )
        except socket.gaierror as e:
            logger.error(f"Hostname {self.client.server} could not be resolved: {e}")
            self.client.add_message(
                f"Hostname {self.client.server} could not be resolved.",
                self.client.ui.colors["error"],
                context_name="Status",
            )
        except ConnectionRefusedError as e:
            logger.error(
                f"Connection refused by {self.client.server}:{self.client.port}: {e}"
            )
            self.client.add_message(
                f"Connection refused by {self.client.server}:{self.client.port}.",
                self.client.ui.colors["error"],
                context_name="Status",
            )
        except ssl.SSLError as e:
            logger.error(f"SSL Error during connection: {e}", exc_info=True)
            self.client.add_message(
                f"SSL Error: {e}", self.client.ui.colors["error"], context_name="Status"
            )
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}", exc_info=True)
            self.client.add_message(
                f"Connection error: {e}",
                self.client.ui.colors["error"],
                context_name="Status",
            )

        self._reset_connection_state()
        return False

    def send_raw(self, data: str):
        # Re-check connection status immediately before sending
        if not self.sock or not self.connected:
            logger.warning(
                f"Attempted to send data while not truly connected or no socket: {data.strip()}"
            )
            if self.client: # Only add message if client and thus UI/context manager exists
                self.client.add_message(
                    "Cannot send: Not connected.",
                    self.client.ui.colors["error"],
                    context_name="Status",
                )
                if not self.client.is_headless:
                    self.client.ui_needs_update.set()
            return

        try:
            if not data.endswith("\r\n"):
                data += "\r\n"
            self.sock.sendall(data.encode("utf-8", errors="replace"))

            log_data = data.strip()
            if log_data.upper().startswith("PASS "):
                log_data = "PASS ******"
            elif (
                log_data.upper().startswith("AUTHENTICATE ") and len(log_data) > 15
            ):
                log_data = log_data.split(" ", 1)[0] + " ******"
            elif log_data.upper().startswith("PRIVMSG NICKSERV :IDENTIFY"):
                parts = log_data.split(" ", 3)
                if len(parts) >= 3:
                    log_data = f"{parts[0]} {parts[1]} {parts[2]} ******"
                else:
                    log_data = "PRIVMSG NickServ :IDENTIFY ******"

            logger.debug(f"C >> {log_data}")

            if (
                self.client and # Check if client exists
                hasattr(self.client, "show_raw_log_in_ui")
                and self.client.show_raw_log_in_ui
            ):
                self.client.add_message(
                    f"C >> {log_data}",
                    self.client.ui.colors.get("system", 0),
                    context_name="Status",
                    prefix_time=True,
                )

            if data.upper().startswith("NICK "):
                self.is_handling_nick_collision = False
        except (OSError, socket.error, ssl.SSLError) as e: # Catch broader socket/SSL errors
            logger.error(f"Error sending data: {e}", exc_info=True)
            if self.client:
                self.client.add_message(
                    f"Error sending data: {e}",
                    self.client.ui.colors["error"],
                    context_name="Status",
                )
                if not self.client.is_headless:
                     self.client.ui_needs_update.set()
            self._reset_connection_state(dispatch_event=True) # Dispatch disconnect on send error
        except Exception as e_unhandled_send: # Catch any other unexpected error
            logger.critical(f"Unhandled error sending data: {e_unhandled_send}", exc_info=True)
            if self.client:
                self.client.add_message(
                    f"Critical send error: {e_unhandled_send}",
                    self.client.ui.colors["error"],
                    context_name="Status",
                )
            self._reset_connection_state(dispatch_event=True)


    def _network_loop(self):
        logger.debug("Network loop starting.")
        self.buffer = b""

        while not self._should_thread_stop.is_set():
            if self.client and self.client.should_quit:
                logger.info(
                    "Network loop: client.should_quit is true. Exiting network loop."
                )
                break

            if not self.connected:
                self._disconnect_event_sent_for_current_session = False
                if self.client and self.client.should_quit:
                    break

                # Before attempting to connect, check if server/port are configured
                if not self.client or not self.client.server or self.client.port is None:
                    logger.warning("Network loop: Server/port not configured. Waiting before retry.")
                    interrupted = self._should_thread_stop.wait(self.reconnect_delay) # Still use delay
                    if interrupted or (self.client and self.client.should_quit): break
                    self.reconnect_delay = min(self.reconnect_delay * 2, RECONNECT_MAX_DELAY)
                    continue

                logger.debug("Network loop: Not connected. Attempting to connect.")
                if self._connect_socket():
                    logger.info(
                        "Network loop: Connection successful, CAP negotiation initiated."
                    )
                    self.is_handling_nick_collision = False
                else:
                    logger.warning("Network loop: Connection attempt failed.")
                    if self.client:
                        self.client.add_message(
                            f"Retrying in {self.reconnect_delay} seconds...",
                            self.client.ui.colors["system"],
                            context_name="Status",
                        )
                        if not self.client.is_headless:
                            self.client.ui_needs_update.set()

                    interrupted = self._should_thread_stop.wait(self.reconnect_delay)
                    if interrupted or (self.client and self.client.should_quit):
                        logger.debug(
                            "Network loop: Reconnect wait interrupted or client quitting. Exiting loop."
                        )
                        break
                    self.reconnect_delay = min(
                        self.reconnect_delay * 2, RECONNECT_MAX_DELAY
                    )
                    logger.debug(
                        f"Network loop: Increased reconnect delay to {self.reconnect_delay}s."
                    )
                    continue

            try:
                while (
                    self.connected
                    and self.sock # Ensure socket exists
                    and not self._should_thread_stop.is_set()
                    and not (self.client and self.client.should_quit)
                ):
                    current_sock_for_loop = self.sock # Use a local var for the loop iteration

                    try:
                        data = current_sock_for_loop.recv(4096)
                        if not data:
                            logger.info(
                                "Network loop: Connection closed by server (recv returned empty)."
                            )
                            self._reset_connection_state(dispatch_event=True)
                            break

                        self.buffer += data
                        while b"\r\n" in self.buffer:
                            line_bytes, self.buffer = self.buffer.split(b"\r\n", 1)
                            try:
                                decoded_line = line_bytes.decode(
                                    "utf-8", errors="replace"
                                )
                                if self.client:
                                    self.client.handle_server_message(decoded_line)
                            except UnicodeDecodeError as e_decode:
                                logger.error(
                                    f"Unicode decode error: {e_decode} on line: {line_bytes.hex()}",
                                    exc_info=True,
                                )
                                if self.client:
                                    self.client.add_message(
                                        f"Unicode decode error: {e_decode}",
                                        self.client.ui.colors["error"],
                                        context_name="Status",
                                    )

                    except socket.timeout:
                        logger.debug("Network loop: Socket recv timed out.")
                        continue
                    except ssl.SSLWantReadError:
                        time.sleep(0.01)
                        continue
                    except (
                        OSError,
                        socket.error,
                        ssl.SSLError,
                    ) as e_sock:
                        if not self._should_thread_stop.is_set(): # Only log as error if not planned shutdown
                            logger.error(
                                f"Network loop: Socket error: {e_sock}", exc_info=False # Keep exc_info=False for brevity unless debugging
                            )
                            if self.client:
                                self.client.add_message(
                                    f"Network error: {e_sock}",
                                    self.client.ui.colors["error"],
                                    context_name="Status",
                                )
                        else:
                            logger.info(
                                f"Network loop: Socket error during planned shutdown: {e_sock}"
                            )
                        self._reset_connection_state(dispatch_event=True)
                        break # Break inner loop to attempt reconnect
            except Exception as e_inner_loop:
                logger.critical(
                    f"Network loop: Unexpected critical error in inner loop: {e_inner_loop}",
                    exc_info=True,
                )
                self._reset_connection_state(dispatch_event=True)
            finally:
                if (
                    not self.connected and self.client and not self.client.is_headless
                ):
                    self.client.ui_needs_update.set()

        logger.info("Network loop's outer while loop is ending.")
        if self.sock:
            if self.connected and self.client and self.client.should_quit:
                quit_message = getattr(
                    self.client, "_final_quit_message", "Client shutting down"
                )
                logger.info(f"Network loop (finally): Sending QUIT: {quit_message}")
                try:
                    # Ensure socket is still valid before sending QUIT
                    if self.sock.fileno() != -1: # Check if socket is not closed
                        self.sock.sendall(
                            f"QUIT :{quit_message}\r\n".encode("utf-8", errors="replace")
                        )
                    else:
                        logger.warning("Network loop (finally): Socket already closed, cannot send QUIT.")
                except Exception as e_quit:
                    logger.warning(
                        f"Network loop (finally): Error sending QUIT: {e_quit}"
                    )

            logger.info("Network loop (finally): Closing socket (if not already closed).")
            try:
                if self.sock.fileno() != -1:
                    self.sock.shutdown(socket.SHUT_RDWR)
            except (OSError, socket.error):
                pass
            try:
                self.sock.close()
            except Exception as e_close:
                logger.error(f"Error closing socket in network loop finally: {e_close}")
            self.sock = None

        if self.connected:
            self._reset_connection_state(dispatch_event=True)

        logger.info("Network loop has fully terminated.")
# END OF MODIFIED FILE: network_handler.py
