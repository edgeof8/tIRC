# tirc_core/dcc/dcc_transfer.py
import os
import time
import logging
import asyncio
import hashlib
from enum import Enum, auto
from typing import Optional, TYPE_CHECKING, Callable, Any, Dict, Union
from pathlib import Path

if TYPE_CHECKING:
    from tirc_core.dcc.dcc_manager import DCCManager
    from tirc_core.config_defs import DccConfig # Corrected import

logger = logging.getLogger("tirc.dcc.transfer")

class DCCTransferType(Enum):
    SEND = auto()
    RECEIVE = auto()

class DCCTransferStatus(Enum):
    PENDING = auto()        # Waiting for user action (e.g., /dcc get or /dcc accept) or remote action
    QUEUED = auto()         # Queued for sending by DCCSendManager
    NEGOTIATING = auto()    # CTCP handshake in progress
    CONNECTING = auto()     # TCP connection attempt in progress
    TRANSFERRING = auto()   # Data transfer in progress
    COMPLETED = auto()      # Transfer finished successfully
    FAILED = auto()         # Transfer failed
    CANCELLED = auto()      # Transfer cancelled by user or remote
    PAUSED = auto()         # Transfer paused (for resumable sends)
    RESUMING = auto()       # Attempting to resume
    VERIFYING = auto()      # Checksum verification in progress (if enabled)

    def __str__(self):
        return self.name

class DCCTransfer:
    """Base class for DCC transfers (send and receive)."""

    def __init__(
        self,
        transfer_id: str,
        transfer_type: DCCTransferType,
        peer_nick: str,
        filename: str,
        filesize: int, # Expected total size
        local_filepath: Union[str, Path], # Full path to local file
        dcc_manager_ref: "DCCManager",
        dcc_config_ref: "DccConfig", # Pass DccConfig directly
        event_logger: Optional[logging.Logger] = None, # Optional dedicated event logger
        passive_token: Optional[str] = None, # For passive (reverse) offers
        remote_ip: Optional[str] = None, # For active offers
        remote_port: Optional[int] = None, # For active offers
        resume_offset: int = 0 # For resuming transfers
    ):
        self.id = transfer_id
        self.type = transfer_type
        self.peer_nick = peer_nick
        self.filename = filename
        self.expected_filesize = filesize
        self.local_filepath = Path(local_filepath) # Ensure it's a Path object
        self.dcc_manager = dcc_manager_ref
        self.dcc_config = dcc_config_ref # Store the DCCConfig reference

        self.status = DCCTransferStatus.PENDING
        self.bytes_transferred = resume_offset # Start from offset if resuming
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.error_message: Optional[str] = None
        self.current_rate_bps: float = 0.0 # Bits per second
        self.estimated_eta_seconds: Optional[float] = None

        self.socket: Optional[asyncio.StreamWriter] = None # For sending
        self.reader: Optional[asyncio.StreamReader] = None # For receiving
        self.writer: Optional[asyncio.StreamWriter] = None # For sending/receiving ACKs
        self.file_handle: Optional[Any] = None # Binary file handle

        self.passive_token = passive_token
        self.is_passive = bool(passive_token)
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.resume_offset = resume_offset # Initial offset for resuming

        self.checksum_local: Optional[str] = None
        self.checksum_remote: Optional[str] = None
        self.checksum_match: Optional[bool] = None

        # Logging
        self.transfer_logger = logger # Main logger for general transfer ops
        if event_logger:
            self.dcc_event_logger = event_logger
        else:
            # Fallback if no specific event logger is provided by the manager
            self.dcc_event_logger = logging.getLogger("tirc.dcc.events.transfer")
            if not self.dcc_event_logger.hasHandlers(): # Basic config if not already set up
                 # self.dcc_event_logger.addHandler(logging.NullHandler()) # Avoid "no handlers" warning
                 # Or, if you want it to log somewhere by default:
                 # console_handler = logging.StreamHandler()
                 # console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
                 # self.dcc_event_logger.addHandler(console_handler)
                 # self.dcc_event_logger.setLevel(logging.INFO)
                 pass # Assume root logger or other config handles it
            self.dcc_event_logger.warning(f"[{self.id}] DCCTransfer initialized without a dedicated event logger. Using fallback tirc.dcc.events.transfer.")


        self.transfer_task: Optional[asyncio.Task] = None
        self._last_ack_received_time: Optional[float] = None
        self._last_rate_update_time: float = 0.0
        self._bytes_at_last_rate_update: int = 0

        self.dcc_event_logger.info(f"[{self.id}] Initialized {self.type.name} for {self.filename} with {self.peer_nick}. Passive: {self.is_passive}, Resume Offset: {self.resume_offset}")


    async def _update_status(self, new_status: DCCTransferStatus, error_msg: Optional[str] = None):
        if self.status == new_status and self.error_message == error_msg:
            return # No change

        old_status = self.status
        self.status = new_status
        if error_msg:
            self.error_message = error_msg
            self.transfer_logger.error(f"[{self.id}] Status -> {new_status.name}. Error: {error_msg} (File: {self.filename})")
        else:
            self.transfer_logger.info(f"[{self.id}] Status -> {new_status.name} (File: {self.filename})")

        if new_status in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED]:
            self.end_time = time.monotonic()
            if self.file_handle:
                try:
                    self.file_handle.close()
                    self.file_handle = None
                except Exception as e_fh_close:
                    self.transfer_logger.error(f"[{self.id}] Error closing file handle for {self.filename}: {e_fh_close}")


        # Dispatch status change event via DCCManager
        await self.dcc_manager.dispatch_transfer_event(
            "DCC_TRANSFER_STATUS_CHANGE", self,
            {"old_status": old_status.name, "new_status": new_status.name, "error_message": error_msg}
        )

    def _calculate_rate_and_eta(self):
        now = time.monotonic()
        if self.start_time is None or now == self.start_time:
            self.current_rate_bps = 0.0
            self.estimated_eta_seconds = None
            return

        # Calculate overall average rate
        # elapsed_total = now - self.start_time
        # if elapsed_total > 0:
        #     avg_rate_bps = (self.bytes_transferred * 8) / elapsed_total
        # else:
        #     avg_rate_bps = 0.0

        # Calculate instantaneous rate (e.g., over the last 1-2 seconds)
        if now - self._last_rate_update_time >= 1.0: # Update rate every second
            elapsed_interval = now - self._last_rate_update_time
            bytes_in_interval = self.bytes_transferred - self._bytes_at_last_rate_update

            if elapsed_interval > 0:
                self.current_rate_bps = (bytes_in_interval * 8) / elapsed_interval
            else:
                self.current_rate_bps = 0.0 # Avoid division by zero if somehow time didn't advance

            self._last_rate_update_time = now
            self._bytes_at_last_rate_update = self.bytes_transferred

        if self.current_rate_bps > 0 and self.expected_filesize > 0:
            remaining_bytes = self.expected_filesize - self.bytes_transferred
            if remaining_bytes > 0:
                self.estimated_eta_seconds = remaining_bytes / (self.current_rate_bps / 8)
            else:
                self.estimated_eta_seconds = 0.0 # Already completed or exceeded
        else:
            self.estimated_eta_seconds = None


    async def _verify_checksum(self) -> bool:
        if not self.dcc_config.checksum_verify or not self.checksum_local or not self.checksum_remote:
            self.transfer_logger.info(f"[{self.id}] Checksum verification skipped for {self.filename}.")
            return True # Assume match if not verifying or checksums missing

        await self._update_status(DCCTransferStatus.VERIFYING)
        self.checksum_match = (self.checksum_local == self.checksum_remote)
        log_level = logging.INFO if self.checksum_match else logging.WARNING
        self.transfer_logger.log(log_level,
            f"[{self.id}] Checksum for {self.filename}: Local={self.checksum_local}, Remote={self.checksum_remote}. Match: {self.checksum_match}"
        )
        await self.dcc_manager.dispatch_transfer_event("DCC_TRANSFER_CHECKSUM_RESULT", self, {"match": self.checksum_match})
        return self.checksum_match

    def _calculate_file_hash(self) -> Optional[str]:
        if not self.dcc_config.checksum_verify or not self.local_filepath.exists():
            return None

        algo_name = self.dcc_config.checksum_algorithm.lower()
        hasher: Optional[hashlib._Hash] = None # type: ignore[name-defined]

        if algo_name == "md5":
            hasher = hashlib.md5()
        elif algo_name == "sha1":
            hasher = hashlib.sha1()
        elif algo_name == "sha256":
            hasher = hashlib.sha256()
        # Add other common algorithms if needed (sha512, etc.)
        else:
            self.transfer_logger.warning(f"[{self.id}] Unsupported checksum algorithm: {algo_name}. Skipping hash calculation.")
            return None

        try:
            with open(self.local_filepath, "rb") as f:
                while chunk := f.read(8192): # Read in chunks
                    hasher.update(chunk)
            hex_digest = hasher.hexdigest()
            self.transfer_logger.info(f"[{self.id}] Calculated local {algo_name} for {self.filename}: {hex_digest}")
            return hex_digest
        except Exception as e:
            self.transfer_logger.error(f"[{self.id}] Error calculating local hash for {self.filename}: {e}")
            return None


    async def start(self):
        """Starts the transfer process. Implemented by subclasses."""
        raise NotImplementedError

    async def cancel(self, reason: str = "Cancelled by user"):
        """Cancels the transfer."""
        self.transfer_logger.info(f"[{self.id}] Cancelling transfer for {self.filename}. Reason: {reason}")
        if self.transfer_task and not self.transfer_task.done():
            self.transfer_task.cancel()
        await self._close_socket_and_file()
        await self._update_status(DCCTransferStatus.CANCELLED, reason)

    async def _close_socket_and_file(self):
        if self.socket: # For DCCSendTransfer
            try:
                if not self.socket.is_closing():
                    self.socket.close()
                    await self.socket.wait_closed()
            except Exception as e:
                self.transfer_logger.error(f"[{self.id}] Error closing send socket: {e}")
            self.socket = None

        if self.writer: # For DCCReceiveTransfer (and potentially send ACKs)
            try:
                if not self.writer.is_closing():
                    self.writer.close()
                    await self.writer.wait_closed()
            except Exception as e:
                self.transfer_logger.error(f"[{self.id}] Error closing writer socket: {e}")
            self.writer = None

        # Reader is implicitly closed when writer is closed for asyncio.StreamReader/Writer pairs.
        self.reader = None

        if self.file_handle:
            try:
                self.file_handle.close()
            except Exception as e:
                self.transfer_logger.error(f"[{self.id}] Error closing file handle: {e}")
            self.file_handle = None
        self.transfer_logger.debug(f"[{self.id}] Sockets and file handle closed.")


    def get_progress_percentage(self) -> float:
        if self.expected_filesize > 0:
            return (self.bytes_transferred / self.expected_filesize) * 100
        return 0.0

    def get_status_dict(self) -> Dict[str, Any]:
        self._calculate_rate_and_eta() # Ensure rate/ETA are fresh
        return {
            "id": self.id,
            "type": self.type.name,
            "status": self.status.name,
            "peer_nick": self.peer_nick,
            "filename": self.filename,
            "local_filepath": str(self.local_filepath),
            "expected_filesize": self.expected_filesize,
            "bytes_transferred": self.bytes_transferred,
            "progress_percent": self.get_progress_percentage(),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "error_message": self.error_message,
            "is_passive": self.is_passive,
            "passive_token": self.passive_token,
            "remote_ip": self.remote_ip,
            "remote_port": self.remote_port,
            "current_rate_bps": self.current_rate_bps,
            "estimated_eta_seconds": self.estimated_eta_seconds,
            "checksum_local": self.checksum_local,
            "checksum_remote": self.checksum_remote,
            "checksum_match": self.checksum_match,
        }

    def __repr__(self):
        return (f"<DCCTransfer id={self.id[:8]} type={self.type.name} "
                f"file='{self.filename}' status={self.status.name} peer={self.peer_nick}>")
