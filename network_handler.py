import socket
import ssl
import threading
import time
import logging
from typing import List, Optional, Set
from config import (
    CONNECTION_TIMEOUT,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
)

logger = logging.getLogger("pyrc.network")


class NetworkHandler:
    def __init__(self, client_ref):
        self.client = client_ref
        logger.debug("NetworkHandler initialized.")
        self.sock = None
        self.connected = False
        self.reconnect_delay = RECONNECT_INITIAL_DELAY
        self.network_thread = None
        self._should_thread_stop = threading.Event()
        self.channels_to_join_on_connect: List[str] = []
        self.is_handling_nick_collision: bool = False
        self.running = True
        self.buffer = b""  # Initialize the buffer for message processing

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

    def disconnect_gracefully(self, quit_message="Client disconnecting"):
        """Disconnect from the server gracefully with a quit message.

        Args:
            quit_message: The message to send with the QUIT command
        """
        logger.info(
            f"NetworkHandler.disconnect_gracefully called with message: {quit_message}"
        )
        if self.client:
            self.client._final_quit_message = (
                quit_message  # Store for network loop to use
            )
            self.client.should_quit = (
                True  # This will make the network loop send QUIT and exit
            )
        self._should_thread_stop.set()  # Also signal the thread directly

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

        if channels_to_join is not None:
            self.channels_to_join_on_connect = channels_to_join
        else:
            self.channels_to_join_on_connect = self.client.initial_channels_list[:]

        self.reconnect_delay = RECONNECT_INITIAL_DELAY

        if not self.network_thread or not self.network_thread.is_alive():
            logger.info("Network thread not running, starting it after param update.")
            self.start()
        else:
            logger.debug(
                "Network thread is alive. Setting connected=False to force re-evaluation in loop."
            )
            if hasattr(self.client, "cap_negotiator") and self.client.cap_negotiator:
                self.client.cap_negotiator.reset_negotiation_state()
            if (
                hasattr(self.client, "registration_handler")
                and self.client.registration_handler
            ):
                self.client.registration_handler.reset_registration_state()

            self.connected = False

    def send_cap_ls(self, version: Optional[str] = "302"):
        # 1. Trigger: Called by `CapNegotiator.start_negotiation()` immediately after a successful socket connection
        #    (specifically, after `_connect_socket()` calls `cap_negotiator.start_negotiation()`).
        # 2. Expected State Before:
        #    - `self.connected` is True.
        #    - `self.sock` is an active, connected socket.
        #    - CAP negotiation is just beginning.
        # 3. Key Actions:
        #    - Sends the "CAP LS [version]" (e.g., "CAP LS 302") command to the IRC server.
        #      This requests the server to list the capabilities it supports.
        # 4. Expected State After:
        #    - The "CAP LS" command has been sent.
        #    - The client expects the server to respond with one or more "CAP * LS" messages detailing available capabilities,
        #      or "CAP * ACK/NAK" if the CAP LS command itself is problematic (less common for LS).
        #    - Subsequent step: `CapNegotiator` will process the server's "CAP * LS" response.
        if self.connected:
            if version:
                self.send_raw(f"CAP LS {version}")
            else:
                self.send_raw("CAP LS")
        else:
            logger.warning("send_cap_ls called but not connected.")

    def send_cap_req(self, capabilities: List[str]):
        # 1. Trigger: Called by `CapNegotiator.request_capabilities()` after it has processed the server's
        #    "CAP * LS" response and determined which capabilities to request.
        # 2. Expected State Before:
        #    - `self.connected` is True.
        #    - `self.sock` is an active, connected socket.
        #    - The client has received and parsed the server's list of supported capabilities.
        #    - `capabilities` (method argument) contains a list of capability names to request.
        # 3. Key Actions:
        #    - Sends the "CAP REQ :cap1 cap2 ..." command to the IRC server.
        #      This requests the server to enable the specified capabilities.
        # 4. Expected State After:
        #    - The "CAP REQ" command has been sent.
        #    - The client expects the server to respond with "CAP * ACK :cap1 cap2..." for successfully enabled capabilities
        #      and/or "CAP * NAK :cap3 cap4..." for rejected capabilities.
        #    - Subsequent step: `CapNegotiator` will process the server's "CAP * ACK/NAK" responses.
        if self.connected:
            if capabilities:
                self.send_raw(f"CAP REQ :{ ' '.join(capabilities)}")
        else:
            logger.warning("send_cap_req called but not connected.")

    def send_cap_end(self):
        # 1. Trigger: Called by `CapNegotiator.end_negotiation()` when:
        #    a) The client has finished requesting all desired capabilities (and received ACK/NAK responses).
        #    b) The client decides not to request any capabilities after "CAP LS" (e.g., if none are desired or supported).
        #    c) The server indicates no more capabilities will be listed (e.g. an empty LS response or specific server behavior).
        # 2. Expected State Before:
        #    - `self.connected` is True.
        #    - `self.sock` is an active, connected socket.
        #    - The client has either completed its CAP REQs or decided not to make any/further REQs.
        #    - `CapNegotiator.negotiation_in_progress` is likely True.
        # 3. Key Actions:
        #    - Sends the "CAP END" command to the IRC server.
        #      This signals to the server that the client has finished capability negotiation.
        # 4. Expected State After:
        #    - The "CAP END" command has been sent.
        #    - `CapNegotiator.negotiation_in_progress` is set to False.
        #    - The client is now ready to proceed with the next stage of registration, typically SASL authentication
        #      (if `sasl-auth.enabled` is True and the 'sasl' capability was ACKed) or traditional NICK/USER registration.
        #    - Subsequent step: `CapNegotiator` calls `self.client.sasl_authenticator.start_authentication()` or
        #      `self.client.registration_handler.start_registration()` depending on SASL configuration and success.
        logger.debug("Sending CAP END")
        self.send_raw("CAP END")

    def send_authenticate(self, payload: str):
        # 1. Trigger: Called by `SaslAuthenticator.send_initial_auth()` or `SaslAuthenticator.send_challenge_response()`
        #    during the SASL authentication process. This happens after CAP negotiation is complete (`CAP END` sent)
        #    and if SASL authentication is enabled and the 'sasl' capability was acknowledged.
        # 2. Expected State Before:
        #    - `self.connected` is True.
        #    - `self.sock` is an active, connected socket.
        #    - CAP negotiation is complete.
        #    - `SaslAuthenticator.authentication_in_progress` is True.
        #    - `payload` (method argument) contains the base64-encoded SASL mechanism data (e.g., for PLAIN or EXTERNAL)
        #      or a response to a server challenge.
        # 3. Key Actions:
        #    - Sends the "AUTHENTICATE <payload>" command to the IRC server.
        #      This transmits the client's authentication credentials or challenge response.
        # 4. Expected State After:
        #    - The "AUTHENTICATE <payload>" command has been sent.
        #    - The client expects the server to respond with:
        #      - `AUTHENTICATE +` (challenge from server, if mechanism requires multiple steps).
        #      - `903` (RPL_SASLSUCCESS): SASL authentication successful.
        #      - `904` (RPL_SASLFAIL): SASL authentication failed.
        #      - `905` (RPL_SASLTOOLONG): SASL payload was too long.
        #      - `906` (RPL_SASLABORTED): SASL authentication aborted by client (less common here, usually via `AUTHENTICATE *`).
        #      - `907` (RPL_SASLALREADY): Already authenticated (should not happen if logic is correct).
        #    - Subsequent step: `SaslAuthenticator` will process the server's response (e.g., `handle_sasl_response`, `handle_sasl_success`, `handle_sasl_failure`).
        logger.debug(f"Sending AUTHENTICATE {payload[:20]}...")
        self.send_raw(f"AUTHENTICATE {payload}")

    def _reset_connection_state(self):
        """Reset the connection state and clean up resources."""
        logger.debug("Resetting connection state...")
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error closing socket during reset: {e}")
            finally:
                self.sock = None
        self.connected = False
        self.buffer = b""
        logger.debug("Connection state reset complete")

    def _connect_socket(self):
        # 1. Trigger: Called by the `_network_loop` when `self.connected` is False.
        #    This typically happens on initial startup or after a disconnect when a reconnect attempt is made.
        # 2. Expected State Before:
        #    - `self.sock` might be None or a closed socket.
        #    - `self.connected` is False.
        #    - `self.client.server`, `self.client.port`, `self.client.use_ssl` are set with connection parameters.
        #    - `self.is_handling_nick_collision` is reset to False.
        # 3. Key Actions:
        #    - Resets `self.is_handling_nick_collision`.
        #    - Attempts to create a TCP socket connection to the configured server and port.
        #    - If `self.client.use_ssl` is True, wraps the socket with SSL/TLS.
        #    - Sets `self.sock` to the new socket object.
        #    - Sets `self.connected` to True on successful connection.
        #    - Resets `self.reconnect_delay`.
        #    - Calls `self.client.cap_negotiator.start_negotiation()` to initiate CAP negotiation.
        # 4. Expected State After (Success):
        #    - `self.sock` is an active, connected (and possibly SSL-wrapped) socket.
        #    - `self.connected` is True.
        #    - CAP negotiation process is initiated via `CapNegotiator`.
        #    - Returns True.
        # Expected State After (Failure):
        #    - `self.sock` remains None or is closed.
        #    - `self.connected` remains False.
        #    - An error message is logged and added to the UI.
        #    - `_reset_connection_state()` is called.
        #    - Returns False, leading to a retry attempt in `_network_loop`.
        self.is_handling_nick_collision = False
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
                    context.minimum_version = ssl.TLSVersion.TLSv1
                    logger.info(
                        f"Set SSLContext minimum_version to TLSv1 for {self.client.server}"
                    )
                except AttributeError:
                    logger.warning(
                        "ssl.TLSVersion.TLSv1 not available, or context does not support minimum_version (older Python?). Default TLS settings will be used."
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
                # This is the first step in the IRC handshake after TCP/IP connection.
                self.client.cap_negotiator.start_negotiation()
            else:
                logger.error(
                    "NetworkHandler: cap_negotiator not found on client object during _connect_socket."
                )
                self.client.add_message(
                    "Error: CAP negotiator not initialized.",
                    self.client.ui.colors["error"],
                    "Status",
                )

            # Dispatch CLIENT_CONNECTED event after successful connection and CAP negotiation start
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
        if self.sock and self.connected:
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
            except Exception as e:
                logger.error(f"Error sending data: {e}", exc_info=True)
                self.client.add_message(
                    f"Error sending data: {e}",
                    self.client.ui.colors["error"],
                    context_name="Status",
                )
                self._reset_connection_state()
                self.client.ui_needs_update.set()
        elif not self.connected:
            logger.warning(
                f"Attempted to send data while not connected: {data.strip()}"
            )
            self.client.add_message(
                "Cannot send: Not connected.",
                self.client.ui.colors["error"],
                context_name="Status",
            )
            self.client.ui_needs_update.set()

    def _network_loop(self):
        """Main network loop that handles reading from the socket."""
        logger.debug("Network loop starting.")
        try:
            while self.running:
                if not self.connected:
                    logger.debug("Not connected, attempting to connect...")
                    if not self._connect_socket():
                        logger.debug("Connection failed, waiting before retry...")
                        time.sleep(self.reconnect_delay)
                        self.reconnect_delay = min(
                            self.reconnect_delay * 2, RECONNECT_MAX_DELAY
                        )
                        continue

                if not self.sock:
                    logger.error("Socket is None after connection attempt")
                    self.connected = False
                    continue

                try:
                    data = self.sock.recv(4096)
                    if not data:
                        logger.info("Connection closed by server")
                        self.connected = False
                        continue
                    self._process_data(data)
                except socket.timeout:
                    continue
                except socket.error as e:
                    if self.running:  # Only log if we're still supposed to be running
                        logger.error(f"Socket error in network loop: {e}")
                    self.connected = False
                    continue
        except Exception as e:
            logger.error(f"Unexpected error in network loop: {e}", exc_info=True)
        finally:
            logger.info("Network loop is exiting its main processing (finally block).")
            if (
                self.connected and self.sock
            ):  # If we were connected when loop terminates
                # Send QUIT if client is quitting and QUIT hasn't been sent by another mechanism
                quit_msg = getattr(
                    self.client, "_final_quit_message", "Client shutting down"
                )
                logger.info(f"Network loop: Sending QUIT: {quit_msg}")
                try:
                    self.sock.sendall(
                        f"QUIT :{quit_msg}\r\n".encode("utf-8", errors="replace")
                    )
                except Exception as e:
                    logger.warning(f"Network loop: Error sending QUIT in finally: {e}")

            if self.sock:
                logger.info("Network loop performing final socket close.")
                try:
                    self.sock.close()
                except Exception as e_close:
                    logger.error(
                        f"Error closing socket in network loop finally: {e_close}"
                    )
                self.sock = None
            self.connected = False
            logger.info("Network loop has fully finished and cleaned up.")
            # Dispatch disconnect event if it wasn't a clean client-initiated quit that already dispatched it
            if (
                self.client
                and hasattr(self.client, "script_manager")
                and not getattr(self.client, "_clean_disconnect_event_sent", False)
            ):
                current_server = self.client.server if self.client else "unknown"
                current_port = self.client.port if self.client else 0
                logger.info(
                    f"Network loop dispatching CLIENT_DISCONNECTED for {current_server}:{current_port}"
                )
                self.client.script_manager.dispatch_event(
                    "CLIENT_DISCONNECTED",
                    {"server": current_server, "port": current_port},
                )

    def _process_data(self, data: bytes):
        """Process received data and handle message parsing."""
        self.buffer += data
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            line = line.decode("utf-8", errors="replace").strip()
            if line:
                self.client.handle_server_message(line)
