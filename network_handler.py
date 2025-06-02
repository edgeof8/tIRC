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

    def start(self):
        if self.network_thread and self.network_thread.is_alive():
            logger.warning("Network thread start requested, but already running.")
            return
        logger.info("Starting network thread.")
        self._should_thread_stop.clear()
        self.network_thread = threading.Thread(target=self._network_loop, daemon=True)
        self.network_thread.start()
        logger.debug("Network thread object created and started.")

    def stop(
        self, send_quit=True, quit_message: Optional[str] = "Client shutting down"
    ):
        logger.info(
            f"Stopping network thread. Send QUIT: {send_quit}, Message: '{quit_message}'"
        )
        self._should_thread_stop.set()
        if self.sock:
            if self.connected and send_quit:
                try:
                    if not quit_message or not quit_message.strip():
                        # Try to get a random quit message from scripts
                        variables = {
                            "nick": self.client.nick,
                            "server": self.client.server,
                        }
                        quit_message = self.client.script_manager.get_random_quit_message_from_scripts(
                            variables
                        )
                        if not quit_message:
                            quit_message = "Client shutting down"  # Fallback if no script provides a message
                    logger.debug(f"Sending QUIT: {quit_message}")
                    self.send_raw(f"QUIT :{quit_message}")
                except Exception as e:
                    logger.error(f"Error sending QUIT during stop: {e}")
            try:
                logger.debug("Shutting down socket RDWR.")
                self.sock.shutdown(socket.SHUT_RDWR)
            except (OSError, socket.error) as e:
                logger.debug(
                    f"Error during socket shutdown (expected if not connected): {e}"
                )
            finally:
                try:
                    logger.debug("Closing socket.")
                    self.sock.close()
                except (OSError, socket.error) as e:
                    logger.error(f"Error closing socket: {e}")
                self.sock = None
                logger.debug("Socket set to None.")
        self.connected = False
        logger.debug("Connected flag set to False.")
        logger.info("Network thread stop sequence complete.")

    def disconnect_gracefully(self, quit_message="Client disconnecting"):
        self.stop(send_quit=True, quit_message=quit_message)

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
        logger.debug("Resetting connection state.")
        if self.sock:
            try:
                self.sock.close()
            except (OSError, socket.error) as e_close:
                logger.error(f"Error closing socket during reset: {e_close}")
            self.sock = None
        self.connected = False
        if self.client:
            if hasattr(self.client, "cap_negotiator") and self.client.cap_negotiator:
                self.client.cap_negotiator.reset_negotiation_state()
            if (
                hasattr(self.client, "registration_handler")
                and self.client.registration_handler
            ):
                self.client.registration_handler.reset_registration_state()

            # Dispatch CLIENT_DISCONNECTED event
            if hasattr(self.client, "script_manager"):
                current_server = self.client.server if self.client else "unknown"
                current_port = self.client.port if self.client else 0
                self.client.script_manager.dispatch_event(
                    "CLIENT_DISCONNECTED",
                    {"server": current_server, "port": current_port},
                )

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
        buffer = b""
        while not self._should_thread_stop.is_set() and not self.client.should_quit:
            if not self.connected:
                if self._should_thread_stop.is_set() or self.client.should_quit:
                    logger.debug(
                        "Stop signal received while not connected, exiting loop."
                    )
                    break
                logger.debug("Not connected. Attempting to connect.")
                if self._connect_socket():
                    logger.info(
                        "Connection successful in loop, CAP negotiation initiated."
                    )
                else:
                    logger.warning("Connection attempt failed in loop.")
                    self.client.add_message(
                        f"Retrying in {self.reconnect_delay} seconds...",
                        self.client.ui.colors["system"],
                        context_name="Status",
                    )
                    self.client.ui_needs_update.set()
                    interrupted = self._should_thread_stop.wait(self.reconnect_delay)
                    if interrupted or self.client.should_quit:
                        logger.debug(
                            "Reconnect wait interrupted or client quitting, exiting loop."
                        )
                        break
                    self.reconnect_delay = min(
                        self.reconnect_delay * 2, RECONNECT_MAX_DELAY
                    )
                    logger.debug(
                        f"Increased reconnect delay to {self.reconnect_delay}s."
                    )
                    continue
            try:
                if not self.sock:
                    logger.error(
                        "Socket is None despite connected=True. Resetting state."
                    )
                    self._reset_connection_state()
                    self.client.ui_needs_update.set()
                    continue

                data = self.sock.recv(4096)
                if not data:
                    logger.info("Connection closed by server (recv returned empty).")
                    self.client.add_message(
                        "Connection closed by server.",
                        self.client.ui.colors["error"],
                        context_name="Status",
                    )
                    self._reset_connection_state()
                    self.client.ui_needs_update.set()
                    continue  # Will attempt to reconnect in the next iteration
                buffer += data
                while b"\r\n" in buffer:
                    line_bytes, buffer = buffer.split(b"\r\n", 1)
                    try:
                        decoded_line = line_bytes.decode("utf-8", errors="replace")
                        if self.client:
                            self.client.handle_server_message(decoded_line)
                        else:
                            logger.error("Client reference is None in _network_loop.")
                    except UnicodeDecodeError as e:
                        logger.error(
                            f"Unicode decode error: {e} on line: {line_bytes.hex()}",
                            exc_info=True,
                        )
                        if self.client:
                            self.client.add_message(
                                f"Unicode decode error: {e} on line: {line_bytes.hex()}",
                                self.client.ui.colors["error"],
                                context_name="Status",
                            )
            except socket.timeout:
                logger.debug(
                    "Socket recv timed out (should not happen with blocking recv unless timeout is set on socket)."
                )
                pass
            except ssl.SSLWantReadError:
                logger.debug("SSLWantReadError, need to select/poll. Sleeping briefly.")
                time.sleep(0.1)
                continue
            except (OSError, socket.error, ssl.SSLError) as e:
                if (
                    not self._should_thread_stop.is_set()
                    and not self.client.should_quit
                ):
                    logger.error(f"Network error in loop: {e}", exc_info=False)
                    if self.client:
                        self.client.add_message(
                            f"Network error: {e}",
                            self.client.ui.colors["error"],
                            context_name="Status",
                        )
                else:
                    logger.info(f"Network error during shutdown: {e}")
                self._reset_connection_state()
                if self.client:
                    self.client.ui_needs_update.set()
            except Exception as e:
                if (
                    not self._should_thread_stop.is_set()
                    and not self.client.should_quit
                ):
                    logger.critical(
                        f"Unexpected critical error in network loop: {e}", exc_info=True
                    )
                    if self.client:
                        self.client.add_message(
                            f"Unexpected network loop error: {e}",
                            self.client.ui.colors["error"],
                            context_name="Status",
                        )
                else:
                    logger.error(f"Unexpected error during network loop shutdown: {e}")
                self._reset_connection_state()
                if self.client:
                    self.client.ui_needs_update.set()
                logger.info("Breaking network loop due to critical error.")
                break

        logger.info("Network loop has exited.")
        if not self._should_thread_stop.is_set() and self.connected:
            logger.debug(
                "Loop exited but _should_thread_stop not set and still connected, calling stop() for cleanup."
            )
            self.stop(send_quit=False)

        if self.client and not self.client.should_quit:
            logger.info(
                "Network thread officially stopped (client not globally quitting)."
            )
        elif self.client and self.client.should_quit:
            logger.info("Network thread stopped (client is globally quitting).")
