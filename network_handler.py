# network_handler.py
import socket
import ssl
import threading
import time
import logging
from typing import List, Optional, Set # Added Set for type hint
from config import (
    CONNECTION_TIMEOUT,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    # VERIFY_SSL_CERT, # No longer imported directly
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
        self.channels_to_join_on_connect: List[str] = [] # This list will be read by IRCClient_Logic
        self.is_handling_nick_collision: bool = (
            False  # Flag for NICK collision handling
        )
        # self.initial_registration_sent: bool = ( # This flag might not be strictly needed anymore here
        #     False  # Track if NICK/USER sent for this connection
        # )

    def start(self):
        if self.network_thread and self.network_thread.is_alive():
            logger.warning("Network thread start requested, but already running.")
            return
        logger.info("Starting network thread.")
        self._should_thread_stop.clear()
        self.network_thread = threading.Thread(target=self._network_loop, daemon=True)
        self.network_thread.start()
        logger.debug("Network thread object created and started.")

    def stop(self, send_quit=True, quit_message: Optional[str] = "Client shutting down"): # Added type hint and default
        logger.info(f"Stopping network thread. Send QUIT: {send_quit}, Message: '{quit_message}'")
        self._should_thread_stop.set()
        if self.sock:
            if self.connected and send_quit:
                try:
                    # Use the provided quit_message, or a default if None/empty
                    effective_quit_message = quit_message if quit_message and quit_message.strip() else "Client shutting down"
                    logger.debug(f"Sending QUIT: {effective_quit_message}")
                    self.send_raw(f"QUIT :{effective_quit_message}")
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

        # Client's main server/port/ssl attributes are already updated by CommandHandler before this call.

        if channels_to_join is not None:
            self.channels_to_join_on_connect = channels_to_join
        else:
            # If called from /connect without channels, it might default to initial_channels_list
            # If called during startup, initial_channels_list is used.
            # This ensures channels_to_join_on_connect is correctly set based on context.
            self.channels_to_join_on_connect = self.client.initial_channels_list[:]


        self.reconnect_delay = RECONNECT_INITIAL_DELAY

        if not self.network_thread or not self.network_thread.is_alive():
            logger.info("Network thread not running, starting it after param update.")
            self.start()
        else:
            logger.debug(
                "Network thread is alive. Setting connected=False to force re-evaluation in loop."
            )
            # Ensure CAP/SASL/Registration negotiation state is reset for the new connection attempt
            if hasattr(self.client, 'cap_negotiator') and self.client.cap_negotiator:
                self.client.cap_negotiator.reset_negotiation_state() # This also resets SASL
            if hasattr(self.client, 'registration_handler') and self.client.registration_handler:
                self.client.registration_handler.reset_registration_state()

            self.connected = False # This will trigger _connect_socket in the loop
            # The loop will pick this up. If it's sleeping, it will eventually wake.


    def send_cap_ls(self, version: Optional[str] = "302"):
        if self.connected:
            if version:
                self.send_raw(f"CAP LS {version}")
            else:
                self.send_raw("CAP LS")
        else:
            logger.warning("send_cap_ls called but not connected.")

    def send_cap_req(self, capabilities: List[str]):
        if self.connected:
            if capabilities:
                self.send_raw(f"CAP REQ :{ ' '.join(capabilities)}")
        else:
            logger.warning("send_cap_req called but not connected.")

    def send_cap_end(self):
        logger.debug("Sending CAP END")
        self.send_raw("CAP END")

    def send_authenticate(self, payload: str):
        logger.debug(
            f"Sending AUTHENTICATE {payload[:20]}..."
        )
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
        # Reset CAP/SASL/Registration state for the client logic as well, as connection is lost
        if self.client: # Guard against client being None during shutdown
            if hasattr(self.client, 'cap_negotiator') and self.client.cap_negotiator:
                self.client.cap_negotiator.reset_negotiation_state() # Also resets SASL
            if hasattr(self.client, 'registration_handler') and self.client.registration_handler:
                self.client.registration_handler.reset_registration_state()
            # The old direct attribute resets are removed as they are handled by the new classes.


    def _connect_socket(self):
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
                    logger.info(f"Set SSLContext minimum_version to TLSv1 for {self.client.server}")
                except AttributeError:
                    logger.warning("ssl.TLSVersion.TLSv1 not available, or context does not support minimum_version (older Python?). Default TLS settings will be used.")

                logger.info(f"VERIFY_SSL_CERT value in _connect_socket for {self.client.server}: {self.client.verify_ssl_cert}")
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

            # Initiate CAP negotiation via the CapNegotiator
            if hasattr(self.client, 'cap_negotiator') and self.client.cap_negotiator:
                self.client.cap_negotiator.start_negotiation()
            else:
                logger.error("NetworkHandler: cap_negotiator not found on client object during _connect_socket.")
                self.client.add_message("Error: CAP negotiator not initialized.", self.client.ui.colors["error"], "Status")
                # Potentially treat as connection failure or proceed without CAP if design allows

            # Note: NICK/USER are no longer sent here directly.
            # They are handled by RegistrationHandler, triggered by CapNegotiator events or RPL_WELCOME (001).

            # --- REMOVED CHANNEL JOIN LOGIC FROM HERE ---
            # if self.channels_to_join_on_connect:
            #    # ... loop to send JOIN commands ...
            #    logger.info(f"Will attempt to auto-join channels after registration: {unique_channels_to_join}")
            # else:
            #    logger.info("No channels specified to auto-join on connect.")
            # --- END OF REMOVED LOGIC ---

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

        self._reset_connection_state() # This also resets client's CAP/SASL state
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
                elif log_data.upper().startswith("AUTHENTICATE ") and len(log_data) > 15: # SASL PLAIN creds
                    log_data = log_data.split(" ", 1)[0] + " ******"
                elif log_data.upper().startswith("PRIVMSG NICKSERV :IDENTIFY"):
                    parts = log_data.split(" ", 3)
                    if (
                        len(parts) >= 3
                    ):
                        log_data = f"{parts[0]} {parts[1]} {parts[2]} ******"
                    else:
                        log_data = "PRIVMSG NickServ :IDENTIFY ******"

                logger.debug(f"C >> {log_data}")

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
                context_name="Status", # Or active context
            )
            # Forcing a UI update might be good here if the user tried to type something
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
                # _connect_socket now initiates CAP negotiation.
                # NICK/USER are sent after CAP negotiation (or 001).
                # Channel JOINs are sent after 001 and CAP negotiation is fully finished.
                if self._connect_socket():
                    logger.info("Connection successful in loop, CAP negotiation initiated.")
                else:
                    logger.warning("Connection attempt failed in loop.")
                    self.client.add_message(
                        f"Retrying in {self.reconnect_delay} seconds...",
                        self.client.ui.colors["system"],
                        context_name="Status",
                    )
                    self.client.ui_needs_update.set() # Show retry message
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
                    continue # Try to connect again

            # If connected, proceed to read data
            try:
                if not self.sock: # Should not happen if self.connected is True
                    logger.error(
                        "Socket is None despite connected=True. Resetting state."
                    )
                    self._reset_connection_state() # This will set connected=False
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
                    continue # Will attempt to reconnect in the next iteration

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
                logger.debug("Socket recv timed out (should not happen with blocking recv unless timeout is set on socket).")
                pass # Continue loop
            except ssl.SSLWantReadError: # Non-blocking SSL socket might raise this
                logger.debug("SSLWantReadError, need to select/poll. Sleeping briefly.")
                time.sleep(0.1) # Basic way to handle, select/poll is better for responsiveness
                continue
            except (OSError, socket.error, ssl.SSLError) as e:
                if not self._should_thread_stop.is_set() and not self.client.should_quit :
                    logger.error(f"Network error in loop: {e}", exc_info=False)
                    if self.client:
                        self.client.add_message(
                            f"Network error: {e}",
                            self.client.ui.colors["error"],
                            context_name="Status",
                        )
                else: # Error during shutdown
                    logger.info(f"Network error during shutdown: {e}")
                self._reset_connection_state()
                if self.client: self.client.ui_needs_update.set()
                # Loop will continue and attempt reconnect if appropriate
            except Exception as e: # Catch-all for truly unexpected issues
                if not self._should_thread_stop.is_set() and not self.client.should_quit:
                    logger.critical(f"Unexpected critical error in network loop: {e}", exc_info=True)
                    if self.client:
                        self.client.add_message(
                            f"Unexpected network loop error: {e}",
                            self.client.ui.colors["error"],
                            context_name="Status",
                        )
                else:
                    logger.error(f"Unexpected error during network loop shutdown: {e}")
                self._reset_connection_state()
                if self.client: self.client.ui_needs_update.set()
                logger.info("Breaking network loop due to critical error.")
                break # Exit loop on critical unknown error

        logger.info("Network loop has exited.")
        # Ensure cleanup if loop exited for reasons other than explicit stop
        if not self._should_thread_stop.is_set() and self.connected:
            logger.debug("Loop exited but _should_thread_stop not set and still connected, calling stop() for cleanup.")
            self.stop(send_quit=False) # Don't try to send QUIT if connection might be bad

        if self.client and not self.client.should_quit:
            logger.info("Network thread officially stopped (client not globally quitting).")
            # self.client.add_message( # Avoid adding message if client might be shutting down
            #     "Network thread stopped.", self.client.ui.colors["system"], context_name="Status"
            # )
        elif self.client and self.client.should_quit:
            logger.info("Network thread stopped (client is globally quitting).")
