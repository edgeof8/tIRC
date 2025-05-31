# network_handler.py
import socket
import ssl
import threading
import time
import logging
from typing import List, Optional
from config import CONNECTION_TIMEOUT, RECONNECT_INITIAL_DELAY, RECONNECT_MAX_DELAY

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
        self.is_handling_nick_collision: bool = False # Flag for NICK collision handling

    def start(self):
        if self.network_thread and self.network_thread.is_alive():
            logger.warning("Network thread start requested, but already running.")
            return
        logger.info("Starting network thread.")
        self._should_thread_stop.clear()
        self.network_thread = threading.Thread(target=self._network_loop, daemon=True)
        self.network_thread.start()
        logger.debug("Network thread object created and started.")

    def stop(self, send_quit=True, quit_message="Client shutting down"):
        logger.info(f"Stopping network thread. Send QUIT: {send_quit}")
        self._should_thread_stop.set()
        if self.sock:
            if self.connected and send_quit:
                try:
                    logger.debug(f"Sending QUIT: {quit_message}")
                    self.send_raw(f"QUIT :{quit_message}")
                except Exception as e:
                    logger.error(f"Error sending QUIT during stop: {e}")
            try:
                logger.debug("Shutting down socket RDWR.")
                self.sock.shutdown(socket.SHUT_RDWR)
            except (OSError, socket.error) as e:
                logger.debug(f"Error during socket shutdown (expected if not connected): {e}")
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
        # UI updates are handled by client logic / protocol handler for self-part/quit
        # if not self.client.should_quit:
        #     self.client.add_message(
        #         f"Disconnected: {quit_message}", self.client.ui.colors["system"], context_name="Status"
        #     )
        # self.client.ui_needs_update.set() # stop() will likely lead to UI update anyway

    def update_connection_params(self, server: str, port: int, use_ssl: bool, channels_to_join: Optional[List[str]] = None):
        logger.info(
            f"Updating connection parameters to: {server}:{port} SSL: {use_ssl}. Channels to join: {channels_to_join}"
        )
        if self.connected:
            logger.debug(
                "Currently connected, disconnecting gracefully before updating params."
            )
            current_server_lower = self.client.server.lower() if self.client.server else ""
            new_server_lower = server.lower()
            quit_msg = f"Changing to {server}" if current_server_lower != new_server_lower else "Reconnecting"
            self.disconnect_gracefully(quit_msg)

        # Client's main server/port/ssl attributes are already updated by CommandHandler before this call.

        if channels_to_join is not None:
            self.channels_to_join_on_connect = channels_to_join
        else:
            self.channels_to_join_on_connect = self.client.initial_channels_list[:] # Default to initial list

        self.reconnect_delay = RECONNECT_INITIAL_DELAY

        if not self.network_thread or not self.network_thread.is_alive():
            logger.info("Network thread not running, starting it after param update.")
            self.start()
        else:
            logger.debug(
                "Network thread is alive. Setting connected=False to force re-evaluation in loop."
            )
            self.connected = False
            # The loop will pick this up. If it's sleeping, it will eventually wake.

    def _connect_socket(self):
        self.is_handling_nick_collision = False # Reset flag on new connection attempt
        self.client.add_message(
            f"Attempting to connect to {self.client.server}:{self.client.port}...",
            self.client.ui.colors["system"],
            context_name="Status"
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
                # For self-signed certs, consider adding options in config.py:
                # if not client.config.VERIFY_SSL_CERT: # Hypothetical config option
                #    context.check_hostname = False
                #    context.verify_mode = ssl.CERT_NONE
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
                context_name="Status"
            )

            if self.client.password:
                logger.debug("Sending PASS command.")
                self.send_raw(f"PASS {self.client.password}")

            logger.debug(f"Sending NICK: {self.client.nick}")
            self.send_raw(f"NICK {self.client.nick}") # This will reset is_handling_nick_collision in send_raw

            logger.debug(f"Sending USER: {self.client.nick} 0 * :{self.client.nick}")
            self.send_raw(f"USER {self.client.nick} 0 * :{self.client.nick}")

            # Auto-join channels. This is done *after* NICK/USER and relies on server sending 001 (Welcome)
            # The actual JOIN commands are sent upon receiving RPL_WELCOME (001) or similar numeric
            # that indicates successful registration. For now, we prepare the list here.
            # The actual sending of JOINs will happen after server confirms registration.
            # Let's move the JOIN logic to be triggered by RPL_WELCOME in irc_protocol.py
            # For now, _connect_socket just establishes the connection and sends initial auth.
            # The `self.channels_to_join_on_connect` list will be used by irc_protocol.py
            # when RPL_WELCOME is received.

            # No, let's keep JOINs here for simplicity of NetworkHandler.
            # RPL_WELCOME processing in irc_protocol.py can handle NickServ IDENTIFY.
            if self.channels_to_join_on_connect:
                unique_channels_to_join = sorted(list(set(self.channels_to_join_on_connect)))
                logger.info(f"Will attempt to auto-join channels after registration: {unique_channels_to_join}")
                for channel_to_join in unique_channels_to_join:
                    if channel_to_join.strip():
                        logger.debug(f"Sending JOIN {channel_to_join}")
                        self.send_raw(f"JOIN {channel_to_join}")
            else:
                logger.info("No channels specified to auto-join on connect.")

            return True
        except socket.timeout:
            logger.warning(f"Connection to {self.client.server}:{self.client.port} timed out.")
            self.client.add_message(f"Connection to {self.client.server}:{self.client.port} timed out.", self.client.ui.colors["error"], context_name="Status")
        except socket.gaierror as e:
            logger.error(f"Hostname {self.client.server} could not be resolved: {e}")
            self.client.add_message(f"Hostname {self.client.server} could not be resolved.", self.client.ui.colors["error"], context_name="Status")
        except ConnectionRefusedError as e:
            logger.error(f"Connection refused by {self.client.server}:{self.client.port}: {e}")
            self.client.add_message(f"Connection refused by {self.client.server}:{self.client.port}.", self.client.ui.colors["error"], context_name="Status")
        except ssl.SSLError as e:
            logger.error(f"SSL Error during connection: {e}", exc_info=True)
            self.client.add_message(f"SSL Error: {e}", self.client.ui.colors["error"], context_name="Status")
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}", exc_info=True)
            self.client.add_message(f"Connection error: {e}", self.client.ui.colors["error"], context_name="Status")

        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception as e_close:
                logger.error(f"Error closing socket after failed connect: {e_close}")
            self.sock = None
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
                elif log_data.upper().startswith("PRIVMSG NICKSERV :IDENTIFY"):
                    parts = log_data.split(" ", 3)
                    if len(parts) >= 3: # PRIVMSG NickServ :IDENTIFY <nick_or_account> ******
                        log_data = f"{parts[0]} {parts[1]} {parts[2]} ******"
                    else: # Fallback if format is unexpected
                        log_data = "PRIVMSG NickServ :IDENTIFY ******"


                logger.debug(f"C >> {log_data}")

                # Reset nick collision flag if we are sending a NICK command ourselves
                if data.upper().startswith("NICK "):
                    self.is_handling_nick_collision = False
            except Exception as e:
                logger.error(f"Error sending data: {e}", exc_info=True)
                self.client.add_message(
                    f"Error sending data: {e}", self.client.ui.colors["error"], context_name="Status"
                )
                self.connected = False # Assume connection is lost on send error
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception as e_close:
                        logger.error(f"Error closing socket after send failure: {e_close}")
                    self.sock = None
                self.client.ui_needs_update.set()
        elif not self.connected:
            logger.warning(
                f"Attempted to send data while not connected: {data.strip()}"
            )
            self.client.add_message(
                "Cannot send: Not connected.", self.client.ui.colors["error"], context_name="Status"
            )

    def _network_loop(self):
        logger.debug("Network loop starting.")
        buffer = b""
        while (
            not self._should_thread_stop.is_set() and not self.client.should_quit
        ):
            if not self.connected:
                if self._should_thread_stop.is_set() or self.client.should_quit:
                    logger.debug("Stop signal received while not connected, exiting loop.")
                    break
                logger.debug("Not connected. Attempting to connect.")
                if self._connect_socket():
                    logger.info("Connection successful in loop.")
                else:
                    logger.warning("Connection attempt failed in loop.")
                    self.client.add_message(
                        f"Retrying in {self.reconnect_delay} seconds...",
                        self.client.ui.colors["system"],
                        context_name="Status"
                    )
                    interrupted = self._should_thread_stop.wait(self.reconnect_delay)
                    if interrupted or self.client.should_quit:
                        logger.debug("Reconnect wait interrupted or client quitting, exiting loop.")
                        break
                    self.reconnect_delay = min(
                        self.reconnect_delay * 2, RECONNECT_MAX_DELAY
                    )
                    logger.debug(f"Increased reconnect delay to {self.reconnect_delay}s.")
                    continue

            try:
                if not self.sock:
                    logger.error("Socket is None despite connected=True. Resetting state.")
                    self.connected = False
                    continue

                # Using blocking recv for simplicity. For highly responsive UI during network stalls,
                # non-blocking with select/poll would be better but adds complexity.
                data = self.sock.recv(4096)
                if not data:
                    logger.info("Connection closed by server (recv returned empty).")
                    self.client.add_message(
                        "Connection closed by server.", self.client.ui.colors["error"], context_name="Status"
                    )
                    self.connected = False
                    if self.sock:
                        try:
                            self.sock.close()
                        except Exception as e_close:
                            logger.error(f"Error closing socket after server closed connection: {e_close}")
                        self.sock = None
                    self.client.ui_needs_update.set()
                    continue

                buffer += data
                while b"\r\n" in buffer:
                    line_bytes, buffer = buffer.split(b"\r\n", 1)
                    try:
                        decoded_line = line_bytes.decode("utf-8", errors="replace")
                        self.client.on_server_message(decoded_line)
                    except UnicodeDecodeError as e:
                        logger.error(
                            f"Unicode decode error: {e} on line: {line_bytes.hex()}",
                            exc_info=True,
                        )
                        self.client.add_message(
                            f"Unicode decode error: {e} on line: {line_bytes.hex()}",
                            self.client.ui.colors["error"],
                            context_name="Status"
                        )

            except socket.timeout:
                # This would only happen if sock.settimeout() was used before recv.
                # Currently, create_connection sets the main timeout.
                logger.debug("Socket recv timed out.")
                pass
            except ssl.SSLWantReadError:
                logger.debug("SSLWantReadError, need to select/poll. Sleeping briefly.")
                time.sleep(0.1)
                continue
            except (OSError, socket.error, ssl.SSLError) as e:
                if not self._should_thread_stop.is_set() and not self.client.should_quit:
                    logger.error(f"Network error in loop: {e}", exc_info=False) # exc_info=False to reduce verbosity for common net errors
                    self.client.add_message(f"Network error: {e}", self.client.ui.colors["error"], context_name="Status")
                else:
                    logger.info(f"Network error during shutdown: {e}")
                self.connected = False
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception as e_close:
                        logger.error(f"Error closing socket after network error: {e_close}")
                    self.sock = None
                self.client.ui_needs_update.set()
            except Exception as e:
                if not self._should_thread_stop.is_set() and not self.client.should_quit:
                    logger.critical(f"Unexpected critical error in network loop: {e}", exc_info=True)
                    self.client.add_message(f"Unexpected network loop error: {e}", self.client.ui.colors["error"], context_name="Status")
                else:
                    logger.error(f"Unexpected error during network loop shutdown: {e}")
                self.connected = False
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception as e_close:
                        logger.error(f"Error closing socket after critical loop error: {e_close}")
                    self.sock = None
                self.client.ui_needs_update.set()
                logger.info("Breaking network loop due to critical error.")
                break

        logger.info("Network loop has exited.")
        if not self._should_thread_stop.is_set(): # If loop exited for other reasons
            logger.debug("Loop exited but _should_thread_stop not set, calling stop() for cleanup.")
            self.stop(send_quit=False)

        if not self.client.should_quit:
            logger.info("Network thread officially stopped (client not globally quitting).")
            self.client.add_message("Network thread stopped.", self.client.ui.colors["system"], context_name="Status")
        else:
            logger.info("Network thread stopped (client is globally quitting).")
