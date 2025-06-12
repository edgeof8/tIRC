import logging
import time
import os
import hashlib
import asyncio # For StreamReader/StreamWriter
from typing import Optional, Callable, Any, TYPE_CHECKING
from enum import Enum, auto # Import Enum and auto at the top level

if TYPE_CHECKING:
    from pyrc_core.dcc.dcc_manager import DCCManager
    from pyrc_core.app_config import AppConfig as DCCConfigType # Renamed for clarity

logger = logging.getLogger("pyrc.dcc.transfer")

class DCCStatus(Enum):
    QUEUED = "QUEUED"
    PENDING_ACCEPT = "PENDING_ACCEPT" # For incoming offers waiting for user to /dcc accept
    NEGOTIATING = "NEGOTIATING" # CTCP handshake in progress (e.g., for active SEND, or active RECV)
    CONNECTING = "CONNECTING"  # TCP socket connection attempt
    IN_PROGRESS = "IN_PROGRESS" # Transfer actively sending/receiving data
    PAUSED = "PAUSED" # For resume
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    PENDING_RESUME = "PENDING_RESUME"

class DCCTransferType(Enum):
    SEND = "SEND"
    RECEIVE = "RECEIVE"

class DCCTransfer:
    """Base class for DCC transfers."""
    def __init__(
        self,
        transfer_id: str,
        transfer_type: DCCTransferType,
        peer_nick: str,
        filename: str, # Original filename from offer
        file_size: int, # Proposed file_size from offer
        local_filepath: str, # Sanitized, absolute local path for the file
        dcc_manager_ref: 'DCCManager', # Reference to the DCCManager instance
        peer_ip: Optional[str] = None, # Store peer's IP, useful for resume
        peer_port: Optional[int] = None, # Store peer's port, useful for resume
        resume_offset: int = 0, # For resuming transfers
        dcc_event_logger: Optional[logging.Logger] = None,
    ):
        self.id: str = transfer_id
        self.transfer_type: DCCTransferType = transfer_type
        self.peer_nick: str = peer_nick
        self.filename: str = filename
        self.file_size: int = file_size
        self.local_filepath: str = local_filepath
        self.peer_ip: Optional[str] = peer_ip
        self.peer_port: Optional[int] = peer_port
        self.resume_offset: int = resume_offset if resume_offset >= 0 else 0

        self.status: DCCStatus = DCCStatus.QUEUED
        self.bytes_transferred: int = self.resume_offset if self.resume_offset > 0 else 0
        self.current_rate_bps: float = 0.0
        self.estimated_eta_seconds: Optional[float] = None
        self.error_message: Optional[str] = None

        self.dcc_manager: 'DCCManager' = dcc_manager_ref

        self.local_ip: Optional[str] = None # Our IP for this transfer
        self.local_port: Optional[int] = None # Our port for this transfer

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

        self.file_object: Optional[Any] = None # For file I/O

        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
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
            self.dcc_event_logger = logging.getLogger("pyrc.dcc.events.transfer")
            self.dcc_event_logger.warning(f"[{self.id}] DCCTransfer initialized without a dedicated event logger. Using fallback pyrc.dcc.events.transfer.")

        if self.resume_offset > 0:
            self.dcc_event_logger.info(f"DCCTransfer object created for RESUME: ID={self.id}, Type={self.transfer_type.name}, Peer={self.peer_nick}, File='{self.filename}', Size={self.file_size}, LocalPath='{self.local_filepath}', ResumeOffset={self.resume_offset}")
        else:
            self.dcc_event_logger.info(f"DCCTransfer object created: ID={self.id}, Type={self.transfer_type.name}, Peer={self.peer_nick}, File='{self.filename}', Size={self.file_size}, LocalPath='{self.local_filepath}'")

        # Bandwidth Throttling attributes
        self.bandwidth_limit_bps: int = 0
        if self.dcc_manager and hasattr(self.dcc_manager, 'config'): # Check for 'config' attribute
            # Access DCC related configs directly from the AppConfig instance
            dcc_config_access = self.dcc_manager.config
            if self.transfer_type == DCCTransferType.SEND:
                limit_kbps = self.dcc_manager.config.dcc.bandwidth_limit_send_kbps
            else: # RECEIVE
                limit_kbps = self.dcc_manager.config.dcc.bandwidth_limit_recv_kbps

            if limit_kbps > 0:
                self.bandwidth_limit_bps = limit_kbps * 1024
                self.dcc_event_logger.info(f"[{self.id}] Bandwidth limit set to {self.bandwidth_limit_bps} Bps ({limit_kbps} KBps).")

        self.throttle_chunk_start_time: float = time.monotonic()

    def _calculate_file_checksum(self) -> Optional[str]:
        """Calculates checksum of the local file."""
        if not self.local_filepath or not os.path.exists(self.local_filepath):
            self.dcc_event_logger.error(f"[{self.id}] File not found for checksum: {self.local_filepath}")
            return None

        # Access checksum algorithm directly from AppConfig
        algo_name = self.dcc_manager.config.dcc.checksum_algorithm
        if algo_name.lower() == "none": # Ensure comparison is case-insensitive
            return None

        try:
            hasher = hashlib.new(algo_name)
        except ValueError:
            self.dcc_event_logger.error(f"[{self.id}] Unsupported checksum algorithm: {algo_name}")
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
            self.dcc_event_logger.error(f"[{self.id}] Error reading file for checksum '{self.local_filepath}': {e}")
            self.checksum_status = "Error: FileRead"
            return None

    def set_expected_checksum(self, algorithm: str, checksum_value: str):
        """Called by DCCManager when sender provides a checksum."""
        self.dcc_event_logger.info(f"[{self.id}] Received expected checksum: Algo={algorithm}, Value={checksum_value[:10]}...")
        self.expected_checksum = checksum_value
        # Store the algorithm the sender used, for a more precise status later
        # This is important if our config prefers a different one but sender sent one we support.
        self.checksum_algorithm = algorithm.lower()

        # If we already calculated our checksum, compare now
        if self.calculated_checksum:
            self._compare_checksums()

    def _compare_checksums(self):
        """Compares calculated and expected checksums."""
        # Access checksum_verify and checksum_algorithm directly from AppConfig
        if not self.dcc_manager.config.dcc.checksum_verify or \
           self.dcc_manager.config.dcc.checksum_algorithm.lower() == "none":
            self.checksum_status = "NotChecked"
            return

        if not self.expected_checksum:
            self.checksum_status = "SenderDidNotProvide"
            self.dcc_event_logger.warning(f"[{self.id}] Cannot compare checksums: Sender did not provide one.")
            return

        if not self.calculated_checksum:
            self.checksum_status = "Error: LocalCalcFailed" # Should have been calculated if transfer completed
            self.dcc_event_logger.warning(f"[{self.id}] Cannot compare checksums: Local checksum not calculated.")
            return

        if self.calculated_checksum == self.expected_checksum:
            self.checksum_status = "Match"
            self.dcc_event_logger.info(f"[{self.id}] Checksum MATCH for '{self.filename}' (Algo: {self.checksum_algorithm or 'unknown'})")
        else:
            self.checksum_status = "Mismatch"
            self.dcc_event_logger.warning(f"[{self.id}] Checksum MISMATCH for '{self.filename}' (Algo: {self.checksum_algorithm or 'unknown'}). Expected: {self.expected_checksum[:10]}..., Got: {self.calculated_checksum[:10]}...")

        # Notify DCCManager about the checksum status update
        if self.dcc_manager and hasattr(self.dcc_manager, 'update_transfer_checksum_result'):
            self.dcc_manager.update_transfer_checksum_result(self.id, self.checksum_status)

    def set_status(self, new_status: DCCStatus, error_msg: Optional[str] = None):
        """Updates the transfer status and notifies the DCCManager."""
        if self.status == new_status:
            return # No change

        self.status = new_status
        self.error_message = error_msg
        logger.debug(f"[{self.id}] Status changed to {new_status.name}. Error: {error_msg or 'None'}")

        # Set end_time when transfer reaches a final state
        if new_status in [DCCStatus.COMPLETED, DCCStatus.FAILED,
                         DCCStatus.CANCELLED, DCCStatus.TIMED_OUT]:
            if self.end_time is None:  # Set only once
                self.end_time = time.monotonic()
                self.dcc_event_logger.info(f"[{self.id}] Transfer reached final state {new_status.name}. End time set to {self.end_time:.2f}")

        # Notify the DCCManager of the status change
        if self.dcc_manager:
            self.dcc_manager.update_transfer_status(self.id, new_status, error_msg)

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

            if self.current_rate_bps > 0 and self.file_size > 0:
                remaining_bytes = self.file_size - self.bytes_transferred
                if remaining_bytes > 0:
                    self.estimated_eta_seconds = remaining_bytes / self.current_rate_bps
                else:
                    self.estimated_eta_seconds = 0 # Already done or exceeded
            else:
                self.estimated_eta_seconds = None
        else: # First progress update
            self.last_progress_update_time = now
            self.last_bytes_at_progress_update = self.bytes_transferred

        if self.dcc_manager:
             self.dcc_manager.update_transfer_progress(
                 self.id, self.bytes_transferred, self.file_size,
                 self.current_rate_bps, self.estimated_eta_seconds
             )

    async def stop_transfer(self, reason: DCCStatus = DCCStatus.CANCELLED, error_msg: Optional[str] = "User cancelled"):
        """Signals the transfer to stop, gracefully closing streams/sockets."""
        logger.info(f"[{self.id}] Stopping transfer ('{self.filename}') with reason: {reason.name}, message: '{error_msg}'")
        self.set_status(reason, error_msg)

        if self.reader:
            try:
                # Attempt to drain and close writer first if it exists
                if self.writer:
                    self.writer.close()
                    try:
                        await self.writer.wait_closed()
                    except Exception as e:
                        logger.debug(f"[{self.id}] Error waiting for writer to close: {e}")
                self.reader = None
                self.writer = None
                logger.debug(f"[{self.id}] Reader/Writer references cleared.")
            except Exception as e:
                logger.warning(f"[{self.id}] Error during reader/writer cleanup: {e}")

        if self.file_object and not self.file_object.closed:
            try:
                self.file_object.close()
                logger.debug(f"[{self.id}] File object closed.")
            except IOError as e:
                logger.debug(f"[{self.id}] Error closing file object: {e}")
            self.file_object = None

    def _cleanup(self):
        """Closes file object if it is open. Socket/streams are handled by async stop_transfer."""
        if self.file_object and not self.file_object.closed:
            try:
                self.file_object.close()
                self.dcc_event_logger.debug(f"[{self.id}] File object closed in _cleanup.")
            except IOError as e:
                self.dcc_event_logger.debug(f"[{self.id}] Error closing file object in _cleanup: {e}")
            self.file_object = None
        self.dcc_event_logger.debug(f"[{self.id}] Cleanup finished.")

    async def _apply_throttle(self, chunk_size: int):
        """Applies bandwidth throttling if a limit is set."""
        if self.bandwidth_limit_bps <= 0 or chunk_size <= 0:
            return

        # Time elapsed to process/transfer the current chunk
        elapsed_for_chunk = time.monotonic() - self.throttle_chunk_start_time

        # Expected time this chunk *should* have taken based on the limit
        expected_time_for_chunk = chunk_size / self.bandwidth_limit_bps

        sleep_duration = expected_time_for_chunk - elapsed_for_chunk

        if sleep_duration > 0:
            await asyncio.sleep(sleep_duration)
        self.throttle_chunk_start_time = time.monotonic()


class DCCSendTransfer(DCCTransfer):
    """Handles outgoing DCC SEND transfers."""
    def __init__(
        self,
        is_passive_offer: bool = False,
        passive_token: Optional[str] = None,
        **kwargs # Includes transfer_id, peer_nick, filename, file_size, local_filepath, peer_ip, peer_port, resume_offset, dcc_manager_ref, dcc_event_logger
    ):
        super().__init__(transfer_type=DCCTransferType.SEND, **kwargs)
        self.is_passive_offer = is_passive_offer
        self.passive_token = passive_token

class DCCReceiveTransfer(DCCTransfer):
    """Handles incoming DCC RECEIVE transfers."""
    def __init__(
        self,
        **kwargs # Includes transfer_id, peer_nick, filename, file_size, local_filepath, peer_ip, peer_port, resume_offset, dcc_manager_ref, dcc_event_logger
    ):
        super().__init__(transfer_type=DCCTransferType.RECEIVE, **kwargs)
