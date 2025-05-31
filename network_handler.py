# network_handler.py
import socket
import ssl
import threading
import time
import logging  # Added for logging
from config import CONNECTION_TIMEOUT, RECONNECT_INITIAL_DELAY, RECONNECT_MAX_DELAY

# Get a logger instance (child of the main pyrc logger if configured that way)
logger = logging.getLogger("pyrc.network")


class NetworkHandler:
    def __init__(self, client_ref):
        self.client = client_ref  # Reference to IRCClient_Logic
        logger.debug("NetworkHandler initialized.")
        self.sock = None
        self.connected = False
        self.reconnect_delay = RECONNECT_INITIAL_DELAY
        self.network_thread = None
        self._should_thread_stop = (
            threading.Event()
        )  # Used to signal the network loop to stop

    def start(self):
        if self.network_thread and self.network_thread.is_alive():
            # Avoid starting multiple threads if one is already running
            logger.warning("Network thread start requested, but already running.")
            return
        logger.info("Starting network thread.")
        self._should_thread_stop.clear()  # Clear stop signal before starting
        self.network_thread = threading.Thread(target=self._network_loop, daemon=True)
        self.network_thread.start()
        logger.debug("Network thread object created and started.")

    def stop(self, send_quit=True, quit_message="Client shutting down"):
        """Signals the network thread to stop and cleans up the socket."""
        logger.info(f"Stopping network thread. Send QUIT: {send_quit}")
        self._should_thread_stop.set()  # Signal the loop to exit
        if self.sock:
            if self.connected and send_quit:
                try:
                    logger.debug(f"Sending QUIT: {quit_message}")
                    self.send_raw(f"QUIT :{quit_message}")
                except Exception as e:
                    logger.error(f"Error sending QUIT during stop: {e}")
                    pass  # Ignore errors during shutdown QUIT
            try:
                logger.debug("Shutting down socket RDWR.")
                self.sock.shutdown(socket.SHUT_RDWR)
            except (OSError, socket.error) as e:
                # Common if socket is already closed or not connected
                logger.debug(
                    f"Error during socket shutdown (expected if not connected): {e}"
                )
                pass
            finally:
                try:
                    logger.debug("Closing socket.")
                    self.sock.close()
                except (OSError, socket.error) as e:
                    logger.error(f"Error closing socket: {e}")
                    pass
                self.sock = None
                logger.debug("Socket set to None.")
        self.connected = False
        logger.debug("Connected flag set to False.")
        # The thread should join itself or be joined by the main client logic
        logger.info("Network thread stop sequence complete.")

    def disconnect_gracefully(self, quit_message="Client disconnecting"):
        """Gracefully disconnects from the server by sending QUIT, then closing socket."""
        self.stop(send_quit=True, quit_message=quit_message)  # Use the stop method
        # Additional UI updates if needed
        if hasattr(self.client, "channel_users"):
            self.client.channel_users.clear()
        if (
            not self.client.should_quit
        ):  # Avoid double "Disconnected" if client is quitting globally
            self.client.add_message(
                f"Disconnected: {quit_message}", self.client.ui.colors["system"]
            )
        self.client.ui_needs_update.set()

    def update_connection_params(self, server, port, use_ssl):
        """Updates connection parameters. The network loop will use these for the next connection attempt."""
        # This method is called by IRCClient_Logic when /connect is used.
        # The actual reconnection will be handled by the _network_loop.
        # We need to ensure that if we are connected, we disconnect first.
        logger.info(
            f"Updating connection parameters to: {server}:{port} SSL: {use_ssl}"
        )
        if self.connected:
            logger.debug(
                "Currently connected, disconnecting gracefully before updating params."
            )
            self.disconnect_gracefully("Changing servers")  # Send QUIT and close socket

        # Update client's view of server, port, ssl, as NetworkHandler reads from client_ref
        logger.debug(
            f"Setting client internal server to {server}, port to {port}, SSL to {use_ssl}"
        )
        self.client.server = server
        self.client.port = port
        self.client.use_ssl = use_ssl

        self.reconnect_delay = (
            RECONNECT_INITIAL_DELAY  # Reset reconnect delay for new server
        )
        # Signal the network loop to attempt a new connection if it's in a wait state
        # This can be done by simply letting the loop iterate, or by interrupting its sleep if any.
        # For now, the loop will pick up new self.client.server etc. on its next iteration.
        # If the thread is not running, start it.
        if not self.network_thread or not self.network_thread.is_alive():
            logger.info("Network thread not running, starting it after param update.")
            self.start()
        else:
            # If the thread is alive but potentially sleeping in reconnect delay,
            # we might want to interrupt it. However, changing client params and letting
            # the loop naturally retry is simpler and often sufficient.
            # For an immediate attempt, we could set self.connected = False and clear _should_thread_stop
            # and ensure the loop re-evaluates connection.
            logger.debug(
                "Network thread is alive. Setting connected=False to force re-evaluation in loop."
            )
            self.connected = False  # Force re-evaluation in the loop.
            # No need to restart the thread if it's already running and will pick up changes.
            # If the thread is in _should_thread_stop.wait(), changing self.connected
            # will make it try to connect on the next iteration after the wait.

    def _connect_socket(self):
        self.client.add_message(
            f"Attempting to connect to {self.client.server}:{self.client.port}...",
            self.client.ui.colors["system"],
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
                # For self-signed certs, you might need:
                # context.check_hostname = False
                # context.verify_mode = ssl.CERT_NONE
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
            )

            if self.client.password:
                logger.debug("Sending PASS command.")
                self.send_raw(f"PASS {self.client.password}")
            logger.debug(f"Sending NICK: {self.client.nick}")
            self.send_raw(f"NICK {self.client.nick}")
            logger.debug(f"Sending USER: {self.client.nick} 0 * :{self.client.nick}")
            self.send_raw(f"USER {self.client.nick} 0 * :{self.client.nick}")
            # Auto-join initial channels after successful connection and authentication
            if (
                hasattr(self.client, "initial_channels_list")
                and self.client.initial_channels_list
            ):
                for channel_to_join in self.client.initial_channels_list:
                    logger.debug(f"Auto-joining channel: {channel_to_join}")
                    self.send_raw(f"JOIN {channel_to_join}")
            return True
        except socket.timeout:
            logger.warning(
                f"Connection to {self.client.server}:{self.client.port} timed out."
            )
            self.client.add_message(
                f"Connection to {self.client.server}:{self.client.port} timed out.",
                self.client.ui.colors["error"],
            )
        except socket.gaierror as e:
            logger.error(f"Hostname {self.client.server} could not be resolved: {e}")
            self.client.add_message(
                f"Hostname {self.client.server} could not be resolved.",
                self.client.ui.colors["error"],
            )
        except ConnectionRefusedError as e:
            logger.error(
                f"Connection refused by {self.client.server}:{self.client.port}: {e}"
            )
            self.client.add_message(
                f"Connection refused by {self.client.server}:{self.client.port}.",
                self.client.ui.colors["error"],
            )
        except ssl.SSLError as e:
            logger.error(f"SSL Error during connection: {e}", exc_info=True)
            self.client.add_message(f"SSL Error: {e}", self.client.ui.colors["error"])
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}", exc_info=True)
            self.client.add_message(
                f"Connection error: {e}", self.client.ui.colors["error"]
            )

        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception as e_close:
                logger.error(f"Error closing socket after failed connect: {e_close}")
            self.sock = None
        return False

    def send_raw(self, data):
        if self.sock and self.connected:
            try:
                if not data.endswith("\r\n"):
                    data += "\r\n"
                self.sock.sendall(data.encode("utf-8", errors="replace"))
                # Log sent data, but be careful with sensitive info like passwords if PASS is logged.
                # Mask PASS command data for logging.
                log_data = data.strip()
                if log_data.upper().startswith("PASS "):
                    log_data = "PASS ******"
                logger.debug(f"C >> {log_data}")
            except Exception as e:
                logger.error(f"Error sending data: {e}", exc_info=True)
                self.client.add_message(
                    f"Error sending data: {e}", self.client.ui.colors["error"]
                )
                self.connected = False
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception as e_close:
                        logger.error(
                            f"Error closing socket after send failure: {e_close}"
                        )
                    self.sock = None
                self.client.ui_needs_update.set()
        elif not self.connected:
            logger.warning(
                f"Attempted to send data while not connected: {data.strip()}"
            )
            self.client.add_message(
                "Cannot send: Not connected.", self.client.ui.colors["error"]
            )

    def _network_loop(self):
        logger.debug("Network loop starting.")
        buffer = b""
        while (
            not self._should_thread_stop.is_set() and not self.client.should_quit
        ):  # Check both stop signals
            if not self.connected:
                if self._should_thread_stop.is_set() or self.client.should_quit:
                    logger.debug(
                        "Stop signal received while not connected, exiting loop."
                    )
                    break

                # Before attempting to connect, ensure client's server/port/ssl are up-to-date
                # This is important if /connect command was used.
                # self.client object holds the authoritative server/port/ssl values.
                logger.debug("Not connected. Attempting to connect.")
                if self._connect_socket():
                    logger.info("Connection successful in loop.")
                    pass  # Successfully connected, loop will now try to recv
                else:
                    logger.warning("Connection attempt failed in loop.")
                    self.client.add_message(
                        f"Retrying in {self.reconnect_delay} seconds...",
                        self.client.ui.colors["system"],
                    )
                    logger.debug(f"Waiting {self.reconnect_delay}s for reconnect.")
                    # Use event for sleeping to allow interruption
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
                    continue  # Try to connect again

            # If we reach here, self.connected should be True
            try:
                if not self.sock:  # Should not happen if self.connected is True
                    logger.error(
                        "Socket is None despite connected=True. Resetting state."
                    )
                    self.connected = False
                    continue

                # Set a timeout for recv so the loop can periodically check stop signals
                # self.sock.settimeout(1.0) # Timeout for recv
                # It seems create_connection already sets a timeout, but this can be explicit for recv
                # However, for SSL, non-blocking with select might be better.
                # For simplicity, relying on the initial timeout and potential blocking recv.
                # If using blocking recv, SSLWantReadError needs to be handled.

                data = self.sock.recv(4096)
                if not data:  # Orderly shutdown by server
                    logger.info("Connection closed by server (recv returned empty).")
                    self.client.add_message(
                        "Connection closed by server.", self.client.ui.colors["error"]
                    )
                    self.connected = False
                    if hasattr(
                        self.client, "channel_users"
                    ):  # TODO: Review if this is still needed with context system
                        self.client.channel_users.clear()
                    if self.sock:
                        try:
                            self.sock.close()
                        except Exception as e_close:
                            logger.error(
                                f"Error closing socket after server closed connection: {e_close}"
                            )
                        self.sock = None
                    self.client.ui_needs_update.set()
                    continue  # Will attempt to reconnect if auto_reconnect is on

                buffer += data
                while b"\r\n" in buffer:
                    line_bytes, buffer = buffer.split(b"\r\n", 1)
                    try:
                        decoded_line = line_bytes.decode("utf-8", errors="replace")
                        # self.client.on_server_message will log the received line
                        self.client.on_server_message(decoded_line)
                    except UnicodeDecodeError as e:
                        logger.error(
                            f"Unicode decode error: {e} on line: {line_bytes.hex()}",
                            exc_info=True,
                        )
                        self.client.add_message(
                            f"Unicode decode error: {e} on line: {line_bytes.hex()}",
                            self.client.ui.colors["error"],
                        )

            except socket.timeout:
                # This is fine if we set a timeout on sock.recv() to check stop flags
                logger.debug("Socket recv timed out (expected if using recv timeout).")
                pass
            except ssl.SSLWantReadError:
                # For non-blocking SSL sockets, this means try again later
                logger.debug("SSLWantReadError, need to select/poll. Sleeping briefly.")
                time.sleep(0.1)  # Brief pause before retrying recv
                continue
            except (
                OSError,
                socket.error,
                ssl.SSLError,
            ) as e:  # Includes ConnectionResetError etc.
                if (
                    not self._should_thread_stop.is_set()
                    and not self.client.should_quit
                ):
                    logger.error(f"Network error in loop: {e}", exc_info=True)
                    self.client.add_message(
                        f"Network error: {e}", self.client.ui.colors["error"]
                    )
                else:
                    logger.info(f"Network error during shutdown: {e}")
                self.connected = False
                if hasattr(self.client, "channel_users"):  # TODO: Review
                    self.client.channel_users.clear()
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception as e_close:
                        logger.error(
                            f"Error closing socket after network error: {e_close}"
                        )
                    self.sock = None
                self.client.ui_needs_update.set()
                # Loop will attempt to reconnect on next iteration if applicable
            except Exception as e:  # Catch-all for unexpected errors in the loop
                if (
                    not self._should_thread_stop.is_set()
                    and not self.client.should_quit
                ):
                    logger.critical(
                        f"Unexpected critical error in network loop: {e}", exc_info=True
                    )
                    self.client.add_message(
                        f"Unexpected network loop error: {e}",
                        self.client.ui.colors["error"],
                    )
                else:
                    logger.error(f"Unexpected error during network loop shutdown: {e}")
                self.connected = False  # Ensure we don't think we're connected
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception as e_close:
                        logger.error(
                            f"Error closing socket after critical loop error: {e_close}"
                        )
                    self.sock = None
                self.client.ui_needs_update.set()
                logger.info("Breaking network loop due to critical error.")
                break  # Exit loop on critical unexpected error

        logger.info("Network loop has exited.")
        # Loop exited, ensure final cleanup via stop() if not already called elsewhere
        # This handles cases where the loop might exit due to client.should_quit directly
        if not self._should_thread_stop.is_set():
            logger.debug(
                "Loop exited but _should_thread_stop not set, calling stop() for cleanup."
            )
            self.stop(
                send_quit=False
            )  # Don't send QUIT again if client.should_quit was the reason

        # Only log "Network thread stopped" if the client isn't globally quitting,
        # to avoid redundant messages if main_curses_wrapper also logs an exit message.
        if not self.client.should_quit:
            logger.info(
                "Network thread officially stopped (client not globally quitting)."
            )
            self.client.add_message(
                "Network thread stopped.", self.client.ui.colors["system"]
            )
        else:
            logger.info("Network thread stopped (client is globally quitting).")
