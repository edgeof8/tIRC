import logging
import threading
import time
import os
import socket
import hashlib
from enum import Enum, auto
from typing import Optional, Callable, Any
import config # For accessing global config values like bandwidth limits

# from dcc_manager import DCCManager # Forward declaration or import later to avoid circularity if needed

logger = logging.getLogger("pyrc.dcc.transfer") # General logger for this module
# dcc_event_logger instance will be passed from DCCManager

class DCCTransferStatus(Enum):
    QUEUED = auto()
    NEGOTIATING = auto() # CTCP handshake in progress
    CONNECTING = auto()  # TCP socket connection attempt
    TRANSFERRING = auto()
    PAUSED = auto() # For resume
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()
    TIMED_OUT = auto()

class DCCTransferType(Enum):
    SEND = auto()
    RECEIVE = auto()

class DCCTransfer:
    """Base class for DCC transfers."""
    def __init__(
        self,
        transfer_id: str,
        transfer_type: DCCTransferType,
        peer_nick: str,
        filename: str, # Original filename from offer
        filesize: int, # Proposed filesize from offer
        local_filepath: str, # Sanitized, absolute local path for the file
        dcc_manager_ref: Any, # Actual type DCCManager, but Any to avoid circular import for now
        dcc_event_logger: Optional[logging.Logger] = None,
        resume_offset: int = 0 # For resuming transfers
        # progress_callback: Callable[[str, int, int, float, float], None], # id, transferred, total, rate, eta
        # status_update_callback: Callable[[str, DCCTransferStatus, Optional[str]], None] # id, status, error_msg
    ):
        self.transfer_id: str = transfer_id
        self.transfer_type: DCCTransferType = transfer_type
        self.peer_nick: str = peer_nick
        self.original_filename: str = filename
        self.filesize: int = filesize # Proposed size
        self.local_filepath: str = local_filepath # Full path to local file
        self.resume_offset: int = resume_offset if resume_offset >= 0 else 0

        self.status: DCCTransferStatus = DCCTransferStatus.QUEUED
        self.bytes_transferred: int = self.resume_offset if self.resume_offset > 0 else 0
        self.current_rate_bps: float = 0.0  # Bytes per second
        self.estimated_eta_seconds: Optional[float] = None

        self.thread: Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()
        self.error_message: Optional[str] = None

        self.dcc_manager = dcc_manager_ref # Reference to the DCCManager instance
        # self.progress_callback = progress_callback
        # self.status_update_callback = status_update_callback

        self.socket: Optional[socket.socket] = None
        self.file_object: Optional[Any] = None # For file I/O

        self.start_time: Optional[float] = None
        self.last_progress_update_time: Optional[float] = None
        self.last_bytes_at_progress_update: int = 0

        # Checksum related attributes
        self.expected_checksum: Optional[str] = None
        self.calculated_checksum: Optional[str] = None
        self.checksum_status: str = "Pending" # "Pending", "NotChecked", "Match", "Mismatch", "SenderDidNotProvide", "AlgorithmMismatch"
        self.checksum_algorithm: Optional[str] = None # Algorithm used by sender or preferred by us

        if dcc_event_logger:
            self.dcc_event_logger = dcc_event_logger
        else:
            # Fallback, though DCCManager should always pass its configured logger
            self.dcc_event_logger = logging.getLogger("pyrc.dcc.events.transfer") # Get a child of the main DCC event logger
            self.dcc_event_logger.warning(f"[{self.transfer_id}] DCCTransfer initialized without a dedicated event logger. Using fallback pyrc.dcc.events.transfer.")

        if self.resume_offset > 0:
            self.dcc_event_logger.info(f"DCCTransfer object created for RESUME: ID={self.transfer_id}, Type={self.transfer_type.name}, Peer={self.peer_nick}, File='{self.original_filename}', Size={self.filesize}, LocalPath='{self.local_filepath}', ResumeOffset={self.resume_offset}")
        else:
            self.dcc_event_logger.info(f"DCCTransfer object created: ID={self.transfer_id}, Type={self.transfer_type.name}, Peer={self.peer_nick}, File='{self.original_filename}', Size={self.filesize}, LocalPath='{self.local_filepath}'")

        # Bandwidth Throttling attributes
        self.bandwidth_limit_bps: int = 0
        if self.transfer_type == DCCTransferType.SEND:
            limit_kbps = config.DCC_BANDWIDTH_LIMIT_SEND_KBPS
        else: # RECEIVE
            limit_kbps = config.DCC_BANDWIDTH_LIMIT_RECV_KBPS

        if limit_kbps > 0:
            self.bandwidth_limit_bps = limit_kbps * 1024
            self.dcc_event_logger.info(f"[{self.transfer_id}] Bandwidth limit set to {self.bandwidth_limit_bps} Bps ({limit_kbps} KBps).")

        self.throttle_chunk_start_time: float = time.monotonic()


    def _calculate_file_checksum(self) -> Optional[str]:
        """Calculates checksum of the local file."""
        if not self.local_filepath or not os.path.exists(self.local_filepath):
            self.dcc_event_logger.error(f"[{self.transfer_id}] File not found for checksum: {self.local_filepath}")
            return None

        algo_name = self.dcc_manager.dcc_config.get("checksum_algorithm", "md5")
        if algo_name == "none":
            return None

        try:
            hasher = hashlib.new(algo_name)
        except ValueError:
            self.dcc_event_logger.error(f"[{self.transfer_id}] Unsupported checksum algorithm: {algo_name}")
            self.checksum_status = f"Error: BadAlgo ({algo_name})"
            return None

        try:
            with open(self.local_filepath, "rb") as f:
                while True:
                    chunk = f.read(8192) # Read in chunks
                    if not chunk:
                        break
                    hasher.update(chunk)
            return hasher.hexdigest()
        except IOError as e:
            self.dcc_event_logger.error(f"[{self.transfer_id}] Error reading file for checksum '{self.local_filepath}': {e}")
            self.checksum_status = "Error: FileRead"
            return None

    def set_expected_checksum(self, algorithm: str, checksum_value: str):
        """Called by DCCManager when sender provides a checksum."""
        self.dcc_event_logger.info(f"[{self.transfer_id}] Received expected checksum: Algo={algorithm}, Value={checksum_value[:10]}...")
        self.expected_checksum = checksum_value
        # Store the algorithm the sender used, for a more precise status later
        # This is important if our config prefers a different one but sender sent one we support.
        self.checksum_algorithm = algorithm.lower()

        # If we already calculated our checksum, compare now
        if self.calculated_checksum:
            self._compare_checksums()

    def _compare_checksums(self):
        """Compares calculated and expected checksums."""
        if not self.dcc_manager.dcc_config.get("checksum_verify", False) or \
           self.dcc_manager.dcc_config.get("checksum_algorithm", "none") == "none":
            self.checksum_status = "NotChecked"
            return

        if not self.expected_checksum:
            self.checksum_status = "SenderDidNotProvide"
            self.dcc_event_logger.warning(f"[{self.transfer_id}] Cannot compare checksums: Sender did not provide one.")
            return

        if not self.calculated_checksum:
            self.checksum_status = "Error: LocalCalcFailed" # Should have been calculated if transfer completed
            self.dcc_event_logger.warning(f"[{self.transfer_id}] Cannot compare checksums: Local checksum not calculated.")
            return

        # Check if algorithm used by sender matches what we might expect or support
        # For now, we assume if sender sent one, we use that algo for comparison if we support it.
        # A stricter check could be if self.checksum_algorithm (from sender) matches self.dcc_manager.dcc_config.get("checksum_algorithm")
        # but that might be too restrictive if sender uses SHA1 and we prefer MD5 but support both.
        # The key is that hashlib.new(self.checksum_algorithm) must have worked for our local calculation.

        if self.calculated_checksum == self.expected_checksum:
            self.checksum_status = "Match"
            self.dcc_event_logger.info(f"[{self.transfer_id}] Checksum MATCH for '{self.original_filename}' (Algo: {self.checksum_algorithm or 'unknown'})")
        else:
            self.checksum_status = "Mismatch"
            self.dcc_event_logger.warning(f"[{self.transfer_id}] Checksum MISMATCH for '{self.original_filename}' (Algo: {self.checksum_algorithm or 'unknown'}). Expected: {self.expected_checksum[:10]}..., Got: {self.calculated_checksum[:10]}...")

        # Notify DCCManager about the checksum status update
        if self.dcc_manager and hasattr(self.dcc_manager, 'update_transfer_checksum_result'):
             self.dcc_manager.update_transfer_checksum_result(self.transfer_id, self.checksum_status)


    def _report_status(self, new_status: DCCTransferStatus, error_msg: Optional[str] = None):
        """Helper to call the status update callback."""
        self.status = new_status
        if error_msg:
            self.error_message = error_msg
        # self.status_update_callback(self.transfer_id, self.status, self.error_message)
        if self.dcc_manager:
            self.dcc_manager.update_transfer_status(self.transfer_id, self.status, self.error_message)


    def _report_progress(self):
        """Helper to call the progress update callback."""
        now = time.monotonic()
        if self.last_progress_update_time and self.start_time:
            time_delta = now - self.last_progress_update_time
            bytes_delta = self.bytes_transferred - self.last_bytes_at_progress_update

            if time_delta > 0.1: # Update rate if enough time has passed
                self.current_rate_bps = bytes_delta / time_delta
                self.last_progress_update_time = now
                self.last_bytes_at_progress_update = self.bytes_transferred

            if self.current_rate_bps > 0 and self.filesize > 0:
                remaining_bytes = self.filesize - self.bytes_transferred
                if remaining_bytes > 0:
                    self.estimated_eta_seconds = remaining_bytes / self.current_rate_bps
                else:
                    self.estimated_eta_seconds = 0 # Already done or exceeded
            else:
                self.estimated_eta_seconds = None
        else: # First progress update
            self.last_progress_update_time = now
            self.last_bytes_at_progress_update = self.bytes_transferred

        # self.progress_callback(
        #     self.transfer_id, self.bytes_transferred, self.filesize,
        #     self.current_rate_bps, self.estimated_eta_seconds
        # )
        if self.dcc_manager:
             self.dcc_manager.update_transfer_progress(
                 self.transfer_id, self.bytes_transferred, self.filesize,
                 self.current_rate_bps, self.estimated_eta_seconds
             )


    def start_transfer_thread(self):
        """Starts the file transfer in a new thread."""
        if self.thread and self.thread.is_alive():
            self.dcc_event_logger.warning(f"Transfer {self.transfer_id} thread already running.")
            return
        self._stop_event.clear()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.start_time = time.monotonic()
        self.last_progress_update_time = self.start_time
        self.thread.start()
        self.dcc_event_logger.info(f"Started thread for transfer {self.transfer_id} ('{self.original_filename}')")

    def stop_transfer(self, reason: DCCTransferStatus = DCCTransferStatus.CANCELLED, error_msg: Optional[str] = "User cancelled"):
        """Signals the transfer thread to stop."""
        self.dcc_event_logger.info(f"Stopping transfer {self.transfer_id} ('{self.original_filename}') with reason: {reason.name}, message: '{error_msg}'")
        self._stop_event.set()
        if self.socket:
            try:
                # Shutdown can help unblock recv/send calls more gracefully
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass # Ignore if already closed or not connected
            finally:
                self.socket.close() # Ensure it's closed
        if self.file_object and not self.file_object.closed:
            self.file_object.close()

        self._report_status(reason, error_msg)

    def run(self):
        """Main logic for the transfer, to be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement the run method.")

    def _cleanup(self):
        """Closes socket and file object if they are open."""
        if self.socket:
            try:
                self.socket.close()
                self.dcc_event_logger.debug(f"[{self.transfer_id}] Socket closed in _cleanup.")
            except OSError as e:
                self.dcc_event_logger.debug(f"[{self.transfer_id}] Error closing socket in _cleanup: {e}")
            self.socket = None
        if self.file_object and not self.file_object.closed:
            try:
                self.file_object.close()
                self.dcc_event_logger.debug(f"[{self.transfer_id}] File object closed in _cleanup.")
            except IOError as e:
                self.dcc_event_logger.debug(f"[{self.transfer_id}] Error closing file object in _cleanup: {e}")
            self.file_object = None
        self.dcc_event_logger.debug(f"[{self.transfer_id}] Cleanup finished.")

    def _apply_throttle(self, chunk_size: int):
        """Applies bandwidth throttling if a limit is set."""
        if self.bandwidth_limit_bps <= 0 or chunk_size <= 0:
            return

        # Time elapsed to process/transfer the current chunk
        elapsed_for_chunk = time.monotonic() - self.throttle_chunk_start_time

        # Expected time this chunk *should* have taken based on the limit
        expected_time_for_chunk = chunk_size / self.bandwidth_limit_bps

        sleep_duration = expected_time_for_chunk - elapsed_for_chunk

        if sleep_duration > 0:
            time.sleep(sleep_duration)
            # self.dcc_event_logger.debug(f"[{self.transfer_id}] Throttling: Slept for {sleep_duration:.4f}s")

        # Reset start time for the next chunk's rate calculation (after potential sleep)
        self.throttle_chunk_start_time = time.monotonic()


class DCCSendTransfer(DCCTransfer):
    """Handles outgoing DCC SEND transfers."""
    def __init__(
        self,
        server_socket_for_active_send: Optional[socket.socket] = None,
        is_passive_offer: bool = False,
        passive_token: Optional[str] = None,
        connect_to_ip: Optional[str] = None, # For passive sender, this is peer's IP
        connect_to_port: Optional[int] = None, # For passive sender, this is peer's port
        dcc_event_logger: Optional[logging.Logger] = None, # Added
        **kwargs
    ):
        super().__init__(transfer_type=DCCTransferType.SEND, dcc_event_logger=dcc_event_logger, **kwargs)
        self.server_socket = server_socket_for_active_send # Listening socket for active DCC sender
        self.is_passive_offer = is_passive_offer
        self.passive_token = passive_token
        self.connect_to_ip = connect_to_ip     # Peer's IP if we are connecting (passive send)
        self.connect_to_port = connect_to_port # Peer's port if we are connecting (passive send)

        if self.is_passive_offer and self.server_socket:
            self.dcc_event_logger.warning(f"[{self.transfer_id}] DCCSendTransfer initialized as passive offer but also given a server_socket. Socket will be ignored initially.")
            self.server_socket = None # Passive offers don't listen initially.

    def run(self):
        try:
            self._report_status(DCCTransferStatus.CONNECTING)

            if self.connect_to_ip and self.connect_to_port: # Passive DCC SEND: We connect to receiver
                self.dcc_event_logger.info(f"[{self.transfer_id}] Passive DCC SEND: Connecting to peer {self.peer_nick} at {self.connect_to_ip}:{self.connect_to_port} for '{self.original_filename}'.")
                try:
                    self.socket = socket.create_connection((self.connect_to_ip, self.connect_to_port), timeout=15)
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Connected to peer for passive DCC SEND.")
                except socket.timeout:
                    self.dcc_event_logger.warning(f"[{self.transfer_id}] Timeout connecting to peer for passive DCC SEND.")
                    self._report_status(DCCTransferStatus.TIMED_OUT, "Connection to peer timed out.")
                    return
                except socket.error as e:
                    self.dcc_event_logger.error(f"[{self.transfer_id}] Socket error connecting for passive DCC SEND: {e}")
                    self._report_status(DCCTransferStatus.FAILED, f"Network connect error: {e}")
                    return

            elif self.server_socket: # Active DCC SEND: We are listening
                self.dcc_event_logger.info(f"[{self.transfer_id}] Active DCC SEND: Waiting for peer {self.peer_nick} to connect...")
                try:
                    self.socket, addr = self.server_socket.accept()
                    self.server_socket.close()
                    self.server_socket = None
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Accepted connection from {addr} for sending '{self.original_filename}'.")
                except socket.timeout: # Should be set on server_socket by DCCManager if desired
                    self.dcc_event_logger.warning(f"[{self.transfer_id}] Timeout waiting for {self.peer_nick} to connect for DCC SEND.")
                    self._report_status(DCCTransferStatus.TIMED_OUT, "Peer connection timed out.")
                    return
                except OSError as e:
                    self.dcc_event_logger.error(f"[{self.transfer_id}] Socket error while waiting for accept: {e}")
                    self._report_status(DCCTransferStatus.FAILED, f"Socket accept error: {e}")
                    return

            if not self.socket:
                 # This state can be reached if it's a passive offer that hasn't been accepted yet,
                 # and start_transfer_thread was called prematurely by manager.
                 # Or if active send socket setup failed.
                 if self.is_passive_offer and not (self.connect_to_ip and self.connect_to_port):
                     self.dcc_event_logger.info(f"[{self.transfer_id}] Passive offer for {self.original_filename} waiting for peer ACCEPT. Thread will exit if not connected.")
                     # This thread shouldn't have been started by DCCManager yet for a passive offer.
                     # If it is, it means the manager expects it to do something, which is an error in logic.
                     # For now, consider it a setup issue.
                     self._report_status(DCCTransferStatus.FAILED, "Passive offer not yet accepted by peer.")
                 else:
                    self.dcc_event_logger.error(f"[{self.transfer_id}] Socket not set for DCC SEND. Aborting.")
                    self._report_status(DCCTransferStatus.FAILED, "Internal error: socket not available for sending.")
                 return

            self._report_status(DCCTransferStatus.TRANSFERRING)

            try:
                if self.resume_offset > 0:
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Attempting to resume send for '{self.local_filepath}' from offset {self.resume_offset}.")
                    if not os.path.exists(self.local_filepath):
                        self.dcc_event_logger.error(f"[{self.transfer_id}] Resume failed: File '{self.local_filepath}' not found.")
                        self._report_status(DCCTransferStatus.FAILED, "Resume error: File not found.")
                        return
                    # File size check for sending resume is less critical than receiving, but good for sanity.
                    # If file is smaller than offset, it's an issue.
                    if os.path.getsize(self.local_filepath) < self.resume_offset:
                        self.dcc_event_logger.error(f"[{self.transfer_id}] Resume failed: File '{self.local_filepath}' is smaller than resume offset {self.resume_offset}.")
                        self._report_status(DCCTransferStatus.FAILED, "Resume error: File smaller than offset.")
                        return

                    self.file_object = open(self.local_filepath, "rb")
                    self.file_object.seek(self.resume_offset)
                    self.bytes_transferred = self.resume_offset # Ensure this is set for progress
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Resuming send from {self.bytes_transferred} bytes.")
                else:
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Starting to send file '{self.local_filepath}' ({self.filesize} bytes) from beginning.")
                    self.file_object = open(self.local_filepath, "rb")
                    self.bytes_transferred = 0
            except IOError as e:
                self.dcc_event_logger.error(f"[{self.transfer_id}] Could not open file '{self.local_filepath}' for sending: {e}")
                self._report_status(DCCTransferStatus.FAILED, f"File error: {e}")
                return

            self._report_progress() # Initial progress

            while self.bytes_transferred < self.filesize:
                if self._stop_event.is_set():
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Send operation cancelled.")
                    # Status already set by stop_transfer
                    break

                chunk = self.file_object.read(4096)
                if not chunk:
                    self.dcc_event_logger.warning(f"[{self.transfer_id}] Read empty chunk from file, but not EOF by size. Expected {self.filesize}, got {self.bytes_transferred}.")
                    # This might happen if file size changed after initiating transfer
                    if self.bytes_transferred < self.filesize:
                         self._report_status(DCCTransferStatus.FAILED, "File size mismatch or premature EOF.")
                    break

                try:
                    self.socket.sendall(chunk)
                    self.bytes_transferred += len(chunk)
                    self._apply_throttle(len(chunk)) # Apply throttling
                    self._report_progress()
                except socket.error as e:
                    self.dcc_event_logger.error(f"[{self.transfer_id}] Socket error during send: {e}")
                    self._report_status(DCCTransferStatus.FAILED, f"Network error: {e}")
                    break

            if not self._stop_event.is_set() and self.bytes_transferred >= self.filesize:
                self.dcc_event_logger.info(f"[{self.transfer_id}] File '{self.original_filename}' sent successfully.")
                self._report_status(DCCTransferStatus.COMPLETED)

                # After successful send, calculate and potentially send checksum
                if self.dcc_manager.dcc_config.get("checksum_verify", False) and \
                   self.dcc_manager.dcc_config.get("checksum_algorithm", "none") != "none":
                    self.calculated_checksum = self._calculate_file_checksum()
                    if self.calculated_checksum:
                        algo = self.dcc_manager.dcc_config.get("checksum_algorithm")
                        self.checksum_algorithm = algo # Store algo used for our calculation
                        self.checksum_status = "CalculatedLocal" # Waiting for peer or for peer to request
                        self.dcc_event_logger.info(f"[{self.transfer_id}] Calculated SEND checksum ({algo}): {self.calculated_checksum[:10]}...")
                        # DCCManager will be responsible for sending this via CTCP
                        if hasattr(self.dcc_manager, 'send_dcc_checksum_info'):
                            self.dcc_manager.send_dcc_checksum_info(self.transfer_id, self.peer_nick, self.original_filename, algo, self.calculated_checksum)
                    else:
                        self.checksum_status = "Error: LocalCalcFailed"
                else:
                    self.checksum_status = "NotChecked"

            elif not self._stop_event.is_set() and self.bytes_transferred < self.filesize :
                # This case might be hit if loop broke due to non-send error (e.g. file read issue not caught above)
                if self.status not in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]:
                     self._report_status(DCCTransferStatus.FAILED, "Transfer incomplete.")


        except Exception as e:
            self.dcc_event_logger.critical(f"[{self.transfer_id}] Unexpected error in DCCSendTransfer.run: {e}", exc_info=True)
            if self.status not in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]:
                 self._report_status(DCCTransferStatus.FAILED, f"Unexpected error: {e}")
        finally:
            self._cleanup()


class DCCReceiveTransfer(DCCTransfer):
    """Handles incoming DCC RECEIVE transfers."""
    def __init__(
        self,
        connect_to_ip: Optional[str] = None,       # For active receive: peer's IP
        connect_to_port: Optional[int] = None,     # For active receive: peer's port
        server_socket_for_passive_recv: Optional[socket.socket] = None, # For passive receive: our listening socket
        dcc_event_logger: Optional[logging.Logger] = None, # Added
        **kwargs
    ):
        super().__init__(transfer_type=DCCTransferType.RECEIVE, dcc_event_logger=dcc_event_logger, **kwargs)
        self.connect_ip = connect_to_ip
        self.connect_port = connect_to_port
        self.server_socket = server_socket_for_passive_recv # Our listening socket if we are passive receiver

    def run(self):
        try:
            self._report_status(DCCTransferStatus.CONNECTING)

            if self.server_socket: # Passive DCC RECV: We are listening
                self.dcc_event_logger.info(f"[{self.transfer_id}] Passive DCC RECV: Waiting for peer {self.peer_nick} to connect to us for '{self.original_filename}'.")
                try:
                    self.socket, addr = self.server_socket.accept()
                    self.server_socket.close() # Close listening socket after one connection
                    self.server_socket = None
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Accepted connection from {addr} for passive DCC RECV.")
                except socket.timeout: # Timeout should be set on server_socket by DCCManager
                    self.dcc_event_logger.warning(f"[{self.transfer_id}] Timeout waiting for peer connection for passive DCC RECV.")
                    self._report_status(DCCTransferStatus.TIMED_OUT, "Peer connection timed out.")
                    return
                except OSError as e:
                    self.dcc_event_logger.error(f"[{self.transfer_id}] Socket error during accept for passive DCC RECV: {e}")
                    self._report_status(DCCTransferStatus.FAILED, f"Socket accept error: {e}")
                    return

            elif self.connect_ip and self.connect_port: # Active DCC RECV: We connect to sender
                self.dcc_event_logger.info(f"[{self.transfer_id}] Active DCC RECV: Connecting to {self.connect_ip}:{self.connect_port} for '{self.original_filename}'.")
                try:
                    self.socket = socket.create_connection((self.connect_ip, self.connect_port), timeout=15)
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Connected to sender for active DCC RECV.")
                except socket.timeout:
                    self.dcc_event_logger.warning(f"[{self.transfer_id}] Timeout connecting to sender for active DCC RECV.")
                    self._report_status(DCCTransferStatus.TIMED_OUT, "Connection to sender timed out.")
                    return
                except socket.error as e:
                    self.dcc_event_logger.error(f"[{self.transfer_id}] Socket error connecting for active DCC RECV: {e}")
                    self._report_status(DCCTransferStatus.FAILED, f"Network connect error: {e}")
                    return

            if not self.socket:
                 self.dcc_event_logger.error(f"[{self.transfer_id}] Socket not established for DCC RECV. Aborting.")
                 self._report_status(DCCTransferStatus.FAILED, "Internal error: socket not available for receiving.")
                 return

            self._report_status(DCCTransferStatus.TRANSFERRING)

            try:
                local_dir = os.path.dirname(self.local_filepath)
                if not os.path.exists(local_dir):
                    os.makedirs(local_dir, exist_ok=True)

                if self.resume_offset > 0:
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Attempting to resume receive for '{self.local_filepath}' from offset {self.resume_offset}.")
                    if not os.path.exists(self.local_filepath):
                        self.dcc_event_logger.error(f"[{self.transfer_id}] Resume failed: Local file '{self.local_filepath}' not found for resume.")
                        self._report_status(DCCTransferStatus.FAILED, "Resume error: Local file missing.")
                        return

                    current_size = os.path.getsize(self.local_filepath)
                    if current_size != self.resume_offset:
                        self.dcc_event_logger.error(f"[{self.transfer_id}] Resume failed: Local file size {current_size} does not match resume offset {self.resume_offset}.")
                        self._report_status(DCCTransferStatus.FAILED, f"Resume error: File size mismatch (local {current_size} != offset {self.resume_offset}).")
                        return

                    self.file_object = open(self.local_filepath, "r+b") # Read/Write binary for resume
                    self.file_object.seek(self.resume_offset)
                    self.bytes_transferred = self.resume_offset # Ensure this is set
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Resuming receive to '{self.local_filepath}' from {self.bytes_transferred} bytes.")
                else:
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Starting to receive file '{self.original_filename}' to '{self.local_filepath}' from beginning.")
                    self.file_object = open(self.local_filepath, "wb") # Write binary, create/truncate
                    self.bytes_transferred = 0
            except IOError as e:
                self.dcc_event_logger.error(f"[{self.transfer_id}] Could not open file '{self.local_filepath}' for writing: {e}")
                self._report_status(DCCTransferStatus.FAILED, f"File system error: {e}")
                return

            self._report_progress() # Initial progress

            while self.bytes_transferred < self.filesize:
                if self._stop_event.is_set():
                    self.dcc_event_logger.info(f"[{self.transfer_id}] Receive operation cancelled.")
                    # Status should be set by stop_transfer
                    break

                try:
                    # For large files and slow networks, recv might block for a long time.
                    # A select-based approach or socket timeout could be useful here if blocking is an issue.
                    # Socket should have a timeout set by DCCManager or here.
                    self.socket.settimeout(30) # Timeout for individual recv operations
                    chunk = self.socket.recv(4096)
                    if not chunk:
                        self.dcc_event_logger.info(f"[{self.transfer_id}] Connection closed by peer (received empty chunk).")
                        if self.bytes_transferred < self.filesize:
                            self._report_status(DCCTransferStatus.FAILED, "Connection closed prematurely by peer.")
                        break # Connection closed

                    self.file_object.write(chunk)
                    self.bytes_transferred += len(chunk)
                    self._apply_throttle(len(chunk)) # Apply throttling
                    self._report_progress()

                except socket.timeout:
                    self.dcc_event_logger.warning(f"[{self.transfer_id}] Socket recv timed out waiting for data.")
                    self._report_status(DCCTransferStatus.TIMED_OUT, "Network timeout waiting for data.")
                    break
                except socket.error as e:
                    self.dcc_event_logger.error(f"[{self.transfer_id}] Socket error during receive: {e}")
                    self._report_status(DCCTransferStatus.FAILED, f"Network error: {e}")
                    break

            if not self._stop_event.is_set() and self.bytes_transferred >= self.filesize:
                self.dcc_event_logger.info(f"[{self.transfer_id}] File '{self.original_filename}' received successfully.")
                self._report_status(DCCTransferStatus.COMPLETED)

                # After successful receive, calculate checksum if enabled
                if self.dcc_manager.dcc_config.get("checksum_verify", False) and \
                   self.dcc_manager.dcc_config.get("checksum_algorithm", "none") != "none":
                    self.calculated_checksum = self._calculate_file_checksum()
                    if self.calculated_checksum:
                        self.dcc_event_logger.info(f"[{self.transfer_id}] Calculated RECV checksum ({self.dcc_manager.dcc_config.get('checksum_algorithm')}): {self.calculated_checksum[:10]}...")
                        if self.expected_checksum: # If sender already sent their checksum
                            self._compare_checksums()
                        else:
                            self.checksum_status = "CalculatedLocal_WaitingForPeer"
                    else:
                        self.checksum_status = "Error: LocalCalcFailed"
                else:
                    self.checksum_status = "NotChecked"

            elif not self._stop_event.is_set() and self.bytes_transferred < self.filesize:
                # This case might be hit if loop broke due to non-recv error
                if self.status not in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]:
                    self._report_status(DCCTransferStatus.FAILED, "Transfer incomplete.")

        except Exception as e:
            self.dcc_event_logger.critical(f"[{self.transfer_id}] Unexpected error in DCCReceiveTransfer.run: {e}", exc_info=True)
            if self.status not in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]:
                self._report_status(DCCTransferStatus.FAILED, f"Unexpected error: {e}")
        finally:
            self._cleanup()
            # If file was not fully received and not cancelled, it might be partial.
            # Consider deleting partial file on failure unless resume is planned.
            if self.status == DCCTransferStatus.FAILED or self.status == DCCTransferStatus.TIMED_OUT:
                if self.bytes_transferred < self.filesize and os.path.exists(self.local_filepath):
                    try:
                        # For Phase 1, let's just log. Deletion/resume is for later.
                        self.dcc_event_logger.warning(f"[{self.transfer_id}] Transfer failed, partial file '{self.local_filepath}' may exist ({self.bytes_transferred}/{self.filesize} bytes).")
                        # os.remove(self.local_filepath)
                        # self.dcc_event_logger.info(f"[{self.transfer_id}] Deleted partial file '{self.local_filepath}'.")
                    except OSError as e_del:
                        self.dcc_event_logger.error(f"[{self.transfer_id}] Error trying to delete partial file '{self.local_filepath}': {e_del}")


if __name__ == "__main__":
    # This is placeholder for direct testing of the classes if needed.
    # For actual use, DCCManager would instantiate and manage these.
    class MockDCCManager:
        def update_transfer_status(self, transfer_id, status, error_msg):
            print(f"MockMgr: Status Update: ID={transfer_id}, Status={status.name}, Error='{error_msg}'")
        def update_transfer_progress(self, transfer_id, transferred, total, rate, eta):
            print(f"MockMgr: Progress: ID={transfer_id}, {transferred}/{total}, Rate={rate:.2f} B/s, ETA={eta:.2f}s" if eta else f"MockMgr: Progress: ID={transfer_id}, {transferred}/{total}, Rate={rate:.2f} B/s, ETA=N/A")

    mock_manager = MockDCCManager()
    print("DCCTransfer module loaded. Contains base class and Send/Receive transfer logic.")
    # Example instantiation (would normally be done by DCCManager)
    # send_transfer = DCCSendTransfer(
    #     transfer_id="send123",
    #     peer_nick="TestReceiver",
    #     filename="test_file.txt",
    #     filesize=1024, # Placeholder
    #     local_filepath="./test_send_file.txt", # Placeholder
    #     dcc_manager_ref=mock_manager
    # )
    # recv_transfer = DCCReceiveTransfer(
    #     transfer_id="recv456",
    #     peer_nick="TestSender",
    #     filename="remote_test_file.dat",
    #     filesize=2048, # Placeholder
    #     local_filepath="./test_recv_file.dat", # Placeholder
    #     dcc_manager_ref=mock_manager,
    #     connect_to_ip="127.0.0.1", # Placeholder
    #     connect_to_port=1234 # Placeholder
    # )
    # print(f"Created test send transfer: {send_transfer.transfer_id}")
    # print(f"Created test receive transfer: {recv_transfer.transfer_id}")
