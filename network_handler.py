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
        self.sock: Optional[socket.socket] = None
        self.connected: bool = False
        self.reconnect_delay: int = RECONNECT_INITIAL_DELAY
        self.network_thread: Optional[threading.Thread] = None
        self._should_thread_stop: threading.Event = threading.Event()
        self.channels_to_join_on_connect: List[str] = []
        self.is_handling_nick_collision: bool = False
        self.running = True
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
        # No direct socket operations here - let the network loop handle its own socket
        logger.info("NetworkHandler.stop() has signaled network thread.")

    def disconnect_gracefully(self, quit_message="Client disconnecting"):
        """Disconnect from the server gracefully with a quit message."""
        logger.info(
            f"NetworkHandler.disconnect_gracefully called with message: {quit_message}"
        )
        if self.client:
            self.client._final_quit_message = (
                quit_message  # Store for network loop to use
            )
        self.stop()  # Signal threads to stop; network loop will send QUIT

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

    def _reset_connection_state(self, dispatch_event: bool = True):
        """Reset the connection state and clean up resources."""
        logger.debug(
            f"Resetting connection state. Dispatch disconnect event: {dispatch_event}"
        )

        # Socket closure is now primarily handled by the network loop's finally block
        # or when a socket error occurs within the loop.
        # This method focuses on resetting logical state.
        if self.sock:
            # It's possible this is called when the socket is already bad or closed by the loop.
            # Attempting a close here again is mostly for safety if called from an unexpected path.
            try:
                self.sock.close()
                logger.debug(
                    "Socket closed by _reset_connection_state (might be redundant)."
                )
            except (OSError, socket.error):
                pass  # Ignore errors if already closed
            self.sock = None

        was_connected = self.connected
        self.connected = False
        self.is_handling_nick_collision = False  # Reset this too

        if self.client:
            if hasattr(self.client, "cap_negotiator") and self.client.cap_negotiator:
                self.client.cap_negotiator.reset_negotiation_state()
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
                    self._disconnect_event_sent_for_current_session = (
                        True  # Mark as sent for this session
                    )

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
        logger.debug("Network loop starting.")
        self.buffer = b""  # Ensure buffer is reset for each connection attempt cycle

        while not self._should_thread_stop.is_set():  # Loop for reconnection attempts
            if self.client and self.client.should_quit:  # Check global quit flag
                logger.info(
                    "Network loop: client.should_quit is true. Exiting network loop."
                )
                break

            if not self.connected:
                self._disconnect_event_sent_for_current_session = (
                    False  # Reset for new connection attempt
                )
                if self.client and self.client.should_quit:
                    break  # Exit if quitting
                logger.debug("Network loop: Not connected. Attempting to connect.")
                if self._connect_socket():
                    logger.info(
                        "Network loop: Connection successful, CAP negotiation initiated."
                    )
                    self.is_handling_nick_collision = (
                        False  # Reset on successful connection
                    )
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
                    continue  # Retry connection

            # Inner loop for processing data once connected
            try:
                while (
                    self.connected
                    and not self._should_thread_stop.is_set()
                    and not (self.client and self.client.should_quit)
                ):
                    current_sock_for_loop = self.sock
                    if not current_sock_for_loop:
                        logger.error(
                            "Network loop: self.sock is None while connected. Resetting."
                        )
                        self._reset_connection_state(dispatch_event=True)
                        break  # Break inner loop to attempt reconnect

                    try:
                        data = current_sock_for_loop.recv(4096)
                        if not data:
                            logger.info(
                                "Network loop: Connection closed by server (recv returned empty)."
                            )
                            self._reset_connection_state(dispatch_event=True)
                            break  # Break inner loop

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

                    except (
                        socket.timeout
                    ):  # Should not happen with blocking sockets unless set_timeout is used
                        logger.debug("Network loop: Socket recv timed out.")
                        continue
                    except ssl.SSLWantReadError:  # For non-blocking SSL sockets
                        time.sleep(0.01)
                        continue
                    except (
                        OSError,
                        socket.error,
                        ssl.SSLError,
                    ) as e_sock:  # Includes ConnectionResetError, BrokenPipeError
                        if not self._should_thread_stop.is_set():
                            logger.error(
                                f"Network loop: Socket error: {e_sock}", exc_info=False
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
                        break  # Break inner loop to attempt reconnect
            except Exception as e_inner_loop:
                logger.critical(
                    f"Network loop: Unexpected critical error in inner loop: {e_inner_loop}",
                    exc_info=True,
                )
                self._reset_connection_state(dispatch_event=True)
                # Potentially break outer loop too if error is severe
                # For now, it will try to reconnect
            finally:
                if (
                    not self.connected and self.client and not self.client.is_headless
                ):  # If disconnected from inner loop
                    self.client.ui_needs_update.set()

        # This finally block is for the outer `while not self._should_thread_stop.is_set():`
        logger.info("Network loop's outer while loop is ending.")
        if (
            self.sock
        ):  # If a socket still exists (e.g. loop broken by should_quit while connected)
            if self.connected and self.client and self.client.should_quit:
                # Send QUIT if we are quitting and were connected
                quit_message = getattr(
                    self.client, "_final_quit_message", "Client shutting down"
                )
                logger.info(f"Network loop (finally): Sending QUIT: {quit_message}")
                try:
                    self.sock.sendall(
                        f"QUIT :{quit_message}\r\n".encode("utf-8", errors="replace")
                    )
                except Exception as e_quit:
                    logger.warning(
                        f"Network loop (finally): Error sending QUIT: {e_quit}"
                    )

            logger.info("Network loop (finally): Closing socket.")
            try:
                self.sock.close()
            except Exception as e_close:
                logger.error(f"Error closing socket in network loop finally: {e_close}")
            self.sock = None

        if self.connected:  # If we were connected when the loop ended
            self._reset_connection_state(
                dispatch_event=True
            )  # Ensure state is fully reset and event dispatched

        logger.info("Network loop has fully terminated.")
