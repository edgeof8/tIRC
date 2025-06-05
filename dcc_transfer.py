import logging
import threading
import time
import os
import socket
from enum import Enum, auto
from typing import Optional, Callable, Any

# from dcc_manager import DCCManager # Forward declaration or import later to avoid circularity if needed

logger = logging.getLogger("pyrc.dcc.transfer")

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
        # progress_callback: Callable[[str, int, int, float, float], None], # id, transferred, total, rate, eta
        # status_update_callback: Callable[[str, DCCTransferStatus, Optional[str]], None] # id, status, error_msg
    ):
        self.transfer_id: str = transfer_id
        self.transfer_type: DCCTransferType = transfer_type
        self.peer_nick: str = peer_nick
        self.original_filename: str = filename
        self.filesize: int = filesize # Proposed size
        self.local_filepath: str = local_filepath # Full path to local file

        self.status: DCCTransferStatus = DCCTransferStatus.QUEUED
        self.bytes_transferred: int = 0
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

        logger.info(f"DCCTransfer object created: ID={self.transfer_id}, Type={self.transfer_type.name}, Peer={self.peer_nick}, File='{self.original_filename}', Size={self.filesize}, LocalPath='{self.local_filepath}'")

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
            logger.warning(f"Transfer {self.transfer_id} thread already running.")
            return
        self._stop_event.clear()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.start_time = time.monotonic()
        self.last_progress_update_time = self.start_time
        self.thread.start()
        logger.info(f"Started thread for transfer {self.transfer_id}")

    def stop_transfer(self, reason: DCCTransferStatus = DCCTransferStatus.CANCELLED, error_msg: Optional[str] = "User cancelled"):
        """Signals the transfer thread to stop."""
        logger.info(f"Stopping transfer {self.transfer_id} with reason: {reason.name}")
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
                logger.debug(f"[{self.transfer_id}] Socket closed in _cleanup.")
            except OSError as e:
                logger.debug(f"[{self.transfer_id}] Error closing socket in _cleanup: {e}")
            self.socket = None
        if self.file_object and not self.file_object.closed:
            try:
                self.file_object.close()
                logger.debug(f"[{self.transfer_id}] File object closed in _cleanup.")
            except IOError as e:
                logger.debug(f"[{self.transfer_id}] Error closing file object in _cleanup: {e}")
            self.file_object = None
        logger.debug(f"[{self.transfer_id}] Cleanup finished.")


class DCCSendTransfer(DCCTransfer):
    """Handles outgoing DCC SEND transfers."""
    def __init__(self, server_socket_for_active_send: Optional[socket.socket] = None, **kwargs):
        super().__init__(transfer_type=DCCTransferType.SEND, **kwargs)
        self.server_socket = server_socket_for_active_send # Listening socket for active DCC
        # For passive DCC SEND, self.socket will be set after connecting to receiver.

    def run(self):
        try:
            self._report_status(DCCTransferStatus.CONNECTING)

            if self.server_socket: # Active DCC SEND: We are listening
                logger.info(f"[{self.transfer_id}] Active DCC SEND: Waiting for peer {self.peer_nick} to connect...")
                try:
                    # Timeout for accept should be handled by DCCManager before starting thread,
                    # or by setting a timeout on the server_socket itself.
                    # For now, assume DCCManager handles timeout for accept.
                    self.socket, addr = self.server_socket.accept()
                    self.server_socket.close() # Close listening socket after one connection
                    self.server_socket = None
                    logger.info(f"[{self.transfer_id}] Accepted connection from {addr} for sending '{self.original_filename}'.")
                except socket.timeout:
                    logger.warning(f"[{self.transfer_id}] Timeout waiting for {self.peer_nick} to connect for DCC SEND.")
                    self._report_status(DCCTransferStatus.TIMED_OUT, "Peer connection timed out.")
                    return
                except OSError as e: # Catch other socket errors like [Errno 9] Bad file descriptor if socket closed
                    logger.error(f"[{self.transfer_id}] Socket error while waiting for accept: {e}")
                    self._report_status(DCCTransferStatus.FAILED, f"Socket accept error: {e}")
                    return

            # else: Passive DCC SEND: We need to connect (logic to be added in DCCManager to set self.socket)
            if not self.socket:
                 logger.error(f"[{self.transfer_id}] Socket not set for DCC SEND. Aborting.")
                 self._report_status(DCCTransferStatus.FAILED, "Internal error: socket not available for sending.")
                 return

            self._report_status(DCCTransferStatus.TRANSFERRING)
            logger.info(f"[{self.transfer_id}] Starting to send file '{self.local_filepath}' ({self.filesize} bytes).")

            try:
                self.file_object = open(self.local_filepath, "rb")
            except IOError as e:
                logger.error(f"[{self.transfer_id}] Could not open file '{self.local_filepath}' for sending: {e}")
                self._report_status(DCCTransferStatus.FAILED, f"File error: {e}")
                return

            self.bytes_transferred = 0 # Or resume position if implemented
            self._report_progress() # Initial progress

            while self.bytes_transferred < self.filesize:
                if self._stop_event.is_set():
                    logger.info(f"[{self.transfer_id}] Send operation cancelled.")
                    # Status already set by stop_transfer
                    break

                chunk = self.file_object.read(4096)
                if not chunk:
                    logger.warning(f"[{self.transfer_id}] Read empty chunk from file, but not EOF by size. Expected {self.filesize}, got {self.bytes_transferred}.")
                    # This might happen if file size changed after initiating transfer
                    if self.bytes_transferred < self.filesize:
                         self._report_status(DCCTransferStatus.FAILED, "File size mismatch or premature EOF.")
                    break

                try:
                    self.socket.sendall(chunk)
                    self.bytes_transferred += len(chunk)
                    self._report_progress()
                except socket.error as e:
                    logger.error(f"[{self.transfer_id}] Socket error during send: {e}")
                    self._report_status(DCCTransferStatus.FAILED, f"Network error: {e}")
                    break

            if not self._stop_event.is_set() and self.bytes_transferred >= self.filesize:
                logger.info(f"[{self.transfer_id}] File '{self.original_filename}' sent successfully.")
                self._report_status(DCCTransferStatus.COMPLETED)
            elif not self._stop_event.is_set() and self.bytes_transferred < self.filesize :
                # This case might be hit if loop broke due to non-send error (e.g. file read issue not caught above)
                if self.status not in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]:
                     self._report_status(DCCTransferStatus.FAILED, "Transfer incomplete.")


        except Exception as e:
            logger.critical(f"[{self.transfer_id}] Unexpected error in DCCSendTransfer.run: {e}", exc_info=True)
            if self.status not in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]:
                 self._report_status(DCCTransferStatus.FAILED, f"Unexpected error: {e}")
        finally:
            self._cleanup()


class DCCReceiveTransfer(DCCTransfer):
    """Handles incoming DCC RECEIVE transfers."""
    def __init__(self, connect_to_ip: Optional[str] = None, connect_to_port: Optional[int] = None, **kwargs):
        super().__init__(transfer_type=DCCTransferType.RECEIVE, **kwargs)
        self.connect_ip = connect_to_ip
        self.connect_port = connect_to_port
        # For passive DCC RECV, self.socket will be set after accepting connection on a listening socket.

    def run(self):
        try:
            self._report_status(DCCTransferStatus.CONNECTING)

            if self.connect_ip and self.connect_port: # Active DCC RECV: We connect to sender
                logger.info(f"[{self.transfer_id}] Active DCC RECV: Connecting to {self.connect_ip}:{self.connect_port} for '{self.original_filename}'.")
                try:
                    self.socket = socket.create_connection((self.connect_ip, self.connect_port), timeout=15) # Shorter timeout for connect
                    logger.info(f"[{self.transfer_id}] Connected to sender for DCC RECV.")
                except socket.timeout:
                    logger.warning(f"[{self.transfer_id}] Timeout connecting to sender for DCC RECV.")
                    self._report_status(DCCTransferStatus.TIMED_OUT, "Connection to sender timed out.")
                    return
                except socket.error as e:
                    logger.error(f"[{self.transfer_id}] Socket error connecting to sender: {e}")
                    self._report_status(DCCTransferStatus.FAILED, f"Network connect error: {e}")
                    return

            # else: Passive DCC RECV: We accept connection (logic to be added in DCCManager to set self.socket)
            if not self.socket:
                 logger.error(f"[{self.transfer_id}] Socket not set for DCC RECV. Aborting.")
                 self._report_status(DCCTransferStatus.FAILED, "Internal error: socket not available for receiving.")
                 return

            self._report_status(DCCTransferStatus.TRANSFERRING)
            logger.info(f"[{self.transfer_id}] Starting to receive file '{self.original_filename}' to '{self.local_filepath}'.")

            try:
                # Ensure directory exists
                local_dir = os.path.dirname(self.local_filepath)
                if not os.path.exists(local_dir):
                    os.makedirs(local_dir, exist_ok=True)
                self.file_object = open(self.local_filepath, "wb") # Open in binary write mode
            except IOError as e:
                logger.error(f"[{self.transfer_id}] Could not open file '{self.local_filepath}' for writing: {e}")
                self._report_status(DCCTransferStatus.FAILED, f"File system error: {e}")
                return

            self.bytes_transferred = 0
            self._report_progress() # Initial progress

            while self.bytes_transferred < self.filesize:
                if self._stop_event.is_set():
                    logger.info(f"[{self.transfer_id}] Receive operation cancelled.")
                    # Status should be set by stop_transfer
                    break

                try:
                    # For large files and slow networks, recv might block for a long time.
                    # A select-based approach or socket timeout could be useful here if blocking is an issue.
                    # Socket should have a timeout set by DCCManager or here.
                    self.socket.settimeout(30) # Timeout for individual recv operations
                    chunk = self.socket.recv(4096)
                    if not chunk:
                        logger.info(f"[{self.transfer_id}] Connection closed by peer (received empty chunk).")
                        if self.bytes_transferred < self.filesize:
                            self._report_status(DCCTransferStatus.FAILED, "Connection closed prematurely by peer.")
                        break # Connection closed

                    self.file_object.write(chunk)
                    self.bytes_transferred += len(chunk)
                    self._report_progress()

                except socket.timeout:
                    logger.warning(f"[{self.transfer_id}] Socket recv timed out waiting for data.")
                    self._report_status(DCCTransferStatus.TIMED_OUT, "Network timeout waiting for data.")
                    break
                except socket.error as e:
                    logger.error(f"[{self.transfer_id}] Socket error during receive: {e}")
                    self._report_status(DCCTransferStatus.FAILED, f"Network error: {e}")
                    break

            if not self._stop_event.is_set() and self.bytes_transferred >= self.filesize:
                logger.info(f"[{self.transfer_id}] File '{self.original_filename}' received successfully.")
                self._report_status(DCCTransferStatus.COMPLETED)
            elif not self._stop_event.is_set() and self.bytes_transferred < self.filesize:
                # This case might be hit if loop broke due to non-recv error
                if self.status not in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]:
                    self._report_status(DCCTransferStatus.FAILED, "Transfer incomplete.")

        except Exception as e:
            logger.critical(f"[{self.transfer_id}] Unexpected error in DCCReceiveTransfer.run: {e}", exc_info=True)
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
                        logger.warning(f"[{self.transfer_id}] Transfer failed, partial file '{self.local_filepath}' may exist ({self.bytes_transferred}/{self.filesize} bytes).")
                        # os.remove(self.local_filepath)
                        # logger.info(f"[{self.transfer_id}] Deleted partial file '{self.local_filepath}'.")
                    except OSError as e_del:
                        logger.error(f"[{self.transfer_id}] Error trying to delete partial file '{self.local_filepath}': {e_del}")


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
