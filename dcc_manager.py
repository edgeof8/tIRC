import logging
import time
import os
import socket
import threading
import uuid # For unique transfer IDs
from typing import Dict, Optional, Any, List, Tuple, Deque
from collections import deque # Import Deque
import logging.handlers # For RotatingFileHandler

# Assuming these will be accessible via client_logic.config or similar
# from config import (
#     DCC_ENABLED, DCC_DOWNLOAD_DIR, DCC_UPLOAD_DIR, DCC_AUTO_ACCEPT,
#     DCC_MAX_FILE_SIZE, DCC_PORT_RANGE_START, DCC_PORT_RANGE_END, DCC_TIMEOUT,
#     DCC_BLOCKED_EXTENSIONS
# )
import config as app_config # Use this to access config values

from dcc_transfer import DCCTransfer, DCCSendTransfer, DCCReceiveTransfer, DCCTransferStatus, DCCTransferType
from dcc_protocol import parse_dcc_ctcp, format_dcc_send_ctcp, format_dcc_accept_ctcp, format_dcc_checksum_ctcp, format_dcc_resume_ctcp
from dcc_security import validate_download_path, sanitize_filename

logger = logging.getLogger("pyrc.dcc.manager") # For general manager operations
dcc_event_logger = logging.getLogger("pyrc.dcc.events") # For detailed DCC events

def setup_dcc_specific_logger():
    """Sets up the dedicated DCC event logger."""
    if not app_config.DCC_LOG_ENABLED:
        dcc_event_logger.disabled = True
        logger.info("Dedicated DCC event logging is disabled via config.")
        return

    # Ensure the logs directory exists (similar to irc_client_logic.py)
    log_dir = os.path.join(app_config.BASE_DIR, "logs")
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"Could not create logs directory '{log_dir}' for DCC logs: {e}")
            dcc_event_logger.disabled = True # Disable if dir can't be made
            return

    log_file_path = os.path.join(log_dir, app_config.DCC_LOG_FILE)

    # Prevent adding handlers multiple times if this function were called again (e.g., rehash)
    if dcc_event_logger.hasHandlers():
        # Attempt to remove existing file handlers to reconfigure, or just return if config is unchanged
        # For simplicity now, we'll assume it's setup once. Rehash might need more robust handler management.
        logger.debug("DCC event logger already has handlers. Skipping reconfiguration for now.")
        # To properly reconfigure on rehash, we'd need to close and remove existing handlers.
        # For now, if it's already set up, we assume it's fine.
        # If DCC_LOG_ENABLED was turned off then on, it might not re-enable without handler removal.
        # However, dcc_event_logger.disabled = True would still take effect.
        if dcc_event_logger.disabled and app_config.DCC_LOG_ENABLED: # Re-enabling
             dcc_event_logger.disabled = False
             logger.info("Re-enabled dedicated DCC event logging.")
        return


    dcc_event_logger.setLevel(app_config.DCC_LOG_LEVEL)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    try:
        handler = logging.handlers.RotatingFileHandler(
            log_file_path,
            maxBytes=app_config.DCC_LOG_MAX_BYTES,
            backupCount=app_config.DCC_LOG_BACKUP_COUNT,
            encoding="utf-8"
        )
        handler.setFormatter(formatter)
        dcc_event_logger.addHandler(handler)
        dcc_event_logger.propagate = False # Don't send to root logger if we have our own file
        logger.info(f"Dedicated DCC event logger configured: File='{log_file_path}', Level={logging.getLevelName(app_config.DCC_LOG_LEVEL)}")
    except Exception as e:
        logger.error(f"Failed to setup dedicated DCC file logger: {e}", exc_info=True)
        dcc_event_logger.disabled = True


class DCCManager:
    def __init__(self, client_logic_ref: Any, event_manager_ref: Any):
        self.client_logic = client_logic_ref
        self.event_manager = event_manager_ref
        self.transfers: Dict[str, DCCTransfer] = {}
        self.pending_passive_offers: Dict[str, Dict[str, Any]] = {} # Key: token
        self.send_queues: Dict[str, Deque[Dict[str, Any]]] = {} # Key: peer_nick, Value: Deque of file_info dicts
        self.dcc_config = self._load_dcc_config()
        self._lock = threading.Lock() # To protect access to self.transfers, pending_passive_offers, and send_queues

        # Setup the dedicated DCC logger instance
        # This logger will be used by DCCManager and passed to DCCTransfer instances
        setup_dcc_specific_logger() # Call the setup function
        self.dcc_event_logger = dcc_event_logger # Store a reference if needed, or just use the global one.

        if not self.dcc_config.get("enabled", False):
            logger.info("DCCManager initialized, but DCC is disabled in configuration.")
        else:
            logger.info("DCCManager initialized and DCC is enabled.")
            self.dcc_event_logger.info("DCCManager initialized and DCC is enabled via app_config.")
            # Ensure download/upload directories exist
            self._ensure_dir_exists(self.dcc_config["download_dir"])
            # Upload dir is less critical to pre-create as source path is absolute for send.

    def _load_dcc_config(self) -> Dict[str, Any]:
        # Load relevant DCC settings from app_config module
        return {
            "enabled": getattr(app_config, "DCC_ENABLED", False),
            "download_dir": getattr(app_config, "DCC_DOWNLOAD_DIR", "downloads"),
            "upload_dir": getattr(app_config, "DCC_UPLOAD_DIR", "uploads"), # Less used by manager directly
            "auto_accept": getattr(app_config, "DCC_AUTO_ACCEPT", False),
            "max_file_size": getattr(app_config, "DCC_MAX_FILE_SIZE", 100 * 1024 * 1024),
            "port_range_start": getattr(app_config, "DCC_PORT_RANGE_START", 1024),
            "port_range_end": getattr(app_config, "DCC_PORT_RANGE_END", 65535),
            "timeout": getattr(app_config, "DCC_TIMEOUT", 300),
            "blocked_extensions": getattr(app_config, "DCC_BLOCKED_EXTENSIONS", []),
            "passive_mode_token_timeout": getattr(app_config, "DCC_PASSIVE_MODE_TOKEN_TIMEOUT", 120),
            "checksum_verify": getattr(app_config, "DCC_CHECKSUM_VERIFY", True),
            "checksum_algorithm": getattr(app_config, "DCC_CHECKSUM_ALGORITHM", "md5").lower(),
            "resume_enabled": getattr(app_config, "DCC_RESUME_ENABLED", True), # Added for resume
        }

    def _cleanup_stale_passive_offers(self):
        """Removes pending passive offers that have timed out."""
        now = time.time()
        stale_tokens = []
        timeout_duration = self.dcc_config.get("passive_mode_token_timeout", 120)

        with self._lock: # Ensure thread-safe access
            for token, offer_details in self.pending_passive_offers.items():
                if now - offer_details.get("timestamp", 0) > timeout_duration:
                    stale_tokens.append(token)

            for token in stale_tokens:
                del self.pending_passive_offers[token]
                self.dcc_event_logger.info(f"Removed stale passive DCC offer with token {token} due to timeout.")

        if stale_tokens:
            self.client_logic.add_message(f"Cleaned up {len(stale_tokens)} stale passive DCC offer(s).", "debug", context_name="DCC")
            self.dcc_event_logger.debug(f"Cleaned up {len(stale_tokens)} stale passive DCC offer(s).")


    def _ensure_dir_exists(self, dir_path: str):
        abs_dir_path = os.path.abspath(dir_path)
        if not os.path.exists(abs_dir_path):
            try:
                os.makedirs(abs_dir_path, exist_ok=True)
                self.dcc_event_logger.info(f"Created directory: {abs_dir_path}")
            except OSError as e:
                self.dcc_event_logger.error(f"Could not create directory '{abs_dir_path}': {e}")
                # Potentially disable DCC or parts of it if essential dirs can't be made
                self.client_logic.add_message(f"Error: DCC directory '{abs_dir_path}' cannot be created. DCC may not function.", "error", context_name="Status")


    def _generate_transfer_id(self) -> str:
        return str(uuid.uuid4())

    def _get_listening_socket(self) -> Optional[Tuple[socket.socket, int]]:
        """Finds an available port in the configured range and returns a listening socket."""
        # For Phase 1, let's try a simpler approach: pick one port or let OS pick.
        # True port range iteration can be complex.
        # For now, let OS pick an ephemeral port by binding to port 0.
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("", 0)) # Bind to any interface, OS picks port
            s.listen(1) # Listen for one incoming connection for this transfer
            port = s.getsockname()[1] # Get the assigned port
            self.dcc_event_logger.info(f"Created listening socket on port {port} for a DCC transfer.")
            return s, port
        except socket.error as e:
            self.dcc_event_logger.error(f"Could not create listening socket: {e}")
            return None

    def _get_local_ip_for_ctcp(self) -> str:
        """Attempts to determine a suitable local IP address for CTCP messages."""
        try:
            # This gets the IP used for default route, might not always be correct for NAT.
            temp_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            temp_s.settimeout(0.5) # Avoid long block if 8.8.8.8 is unreachable
            temp_s.connect(("8.8.8.8", 80)) # Connect to a known external address
            local_ip = temp_s.getsockname()[0]
            temp_s.close()
            return local_ip
        except socket.error:
            logger.warning("Could not determine local IP for DCC CTCP using external connect. Trying hostname.")
            try:
                # Fallback to hostname, may resolve to 127.0.0.1 or an internal IP.
                return socket.gethostbyname(socket.gethostname())
            except socket.gaierror:
                logger.warning("Could not determine local IP via gethostname. Falling back to '127.0.0.1'.")
                return "127.0.0.1"

    def _execute_send(self, peer_nick: str, local_filepath: str, original_filename: str, filesize: int, passive: bool = False) -> Dict[str, Any]:
        """Internal method to execute a single DCC SEND operation."""
        self.dcc_event_logger.info(f"Executing DCC SEND: Peer={peer_nick}, File='{original_filename}', Size={filesize}, Passive={passive}, Path='{local_filepath}'")
        # This method assumes local_filepath is valid and filesize is known.
        # Basic enabled check is done by the public calling method.

        abs_local_filepath = os.path.abspath(local_filepath) # Should already be absolute from initiate_sends

        # Check for existing failed/cancelled transfer to offer resume
        if self.dcc_config.get("resume_enabled", True) and not passive: # Resume primarily for active sends for now
            with self._lock:
                for tid, old_transfer in list(self.transfers.items()): # list() for safe iteration if we modify
                    if (isinstance(old_transfer, DCCSendTransfer) and
                        old_transfer.peer_nick == peer_nick and
                        old_transfer.original_filename == original_filename and
                        old_transfer.status in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT] and
                        old_transfer.bytes_transferred > 0 and
                        old_transfer.bytes_transferred < old_transfer.filesize):

                        resume_offset = old_transfer.bytes_transferred
                        self.dcc_event_logger.info(f"Found previous incomplete send of '{original_filename}' to {peer_nick} at offset {resume_offset}. Offering RESUME.")

                        # Clean up the old transfer object from the main list if we're replacing it with a resume attempt
                        # Or mark it differently. For now, let's remove the old one to avoid confusion.
                        # A more robust system might keep it for history or multiple resume attempts.
                        # del self.transfers[tid]
                        # self.dcc_event_logger.debug(f"Removed old transfer object {tid} before offering resume.")


                        socket_info_resume = self._get_listening_socket()
                        if not socket_info_resume:
                            self.dcc_event_logger.error(f"Could not get listening socket for DCC RESUME of '{original_filename}' to {peer_nick}.")
                            # Fall through to normal send if socket fails for resume
                            break # Break from loop, proceed to normal send below

                        listening_socket_resume, port_resume = socket_info_resume

                        ctcp_resume_message = format_dcc_resume_ctcp(original_filename, port_resume, resume_offset)
                        if not ctcp_resume_message:
                            listening_socket_resume.close()
                            self.dcc_event_logger.error(f"Failed to format DCC RESUME CTCP for '{original_filename}'.")
                            break # Fall through

                        new_transfer_id_resume = self._generate_transfer_id()
                        resume_send_args: Dict[str, Any] = {
                            "transfer_id": new_transfer_id_resume,
                            "peer_nick": peer_nick,
                            "filename": original_filename,
                            "filesize": filesize, # Total original filesize
                            "local_filepath": abs_local_filepath,
                            "dcc_manager_ref": self,
                            "server_socket_for_active_send": listening_socket_resume,
                            "resume_offset": resume_offset, # Key part for resume
                            "dcc_event_logger": self.dcc_event_logger
                        }
                        resume_transfer = DCCSendTransfer(**resume_send_args)
                        self.transfers[new_transfer_id_resume] = resume_transfer # Add new transfer attempt

                        self.client_logic.send_ctcp_privmsg(peer_nick, ctcp_resume_message)
                        resume_transfer._report_status(DCCTransferStatus.NEGOTIATING, f"DCC RESUME offered. Waiting for {peer_nick} to connect on port {port_resume} for '{original_filename}' from offset {resume_offset}.")
                        resume_transfer.start_transfer_thread() # Starts listening

                        self.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", { # Or a new event like DCC_RESUME_OFFERED
                            "transfer_id": new_transfer_id_resume, "type": "SEND_RESUME", "nick": peer_nick,
                            "filename": original_filename, "size": filesize, "resume_offset": resume_offset
                        })
                        self.client_logic.add_message(f"Offering to RESUME DCC SEND to {peer_nick} for '{original_filename}' from offset {resume_offset}. Waiting for peer on port {port_resume}.", "system", context_name="DCC")
                        return {"success": True, "transfer_id": new_transfer_id_resume, "filename": original_filename, "resumed": True}
            # End of resume check block

        transfer_id = self._generate_transfer_id()
        self.dcc_event_logger.debug(f"Generated Transfer ID: {transfer_id} for SEND to {peer_nick} of '{original_filename}'")
        passive_token: Optional[str] = None
        ctcp_message: Optional[str] = None
        send_transfer_args: Dict[str, Any] = {
            "transfer_id": transfer_id,
            "peer_nick": peer_nick,
            "filename": original_filename,
            "filesize": filesize,
            "local_filepath": abs_local_filepath,
            "dcc_manager_ref": self,
        }
        status_message_suffix = ""

        if passive:
            passive_token = self._generate_transfer_id() # Use another UUID for token
            # For passive send, IP can be "0" or actual IP. Port is 0.
            # Sending "0" for IP might be problematic for some clients; actual IP is better if known.
            local_ip_for_ctcp = self._get_local_ip_for_ctcp() # Try to get a real IP
            ctcp_message = format_dcc_send_ctcp(original_filename, local_ip_for_ctcp, 0, filesize, passive_token)
            send_transfer_args["is_passive_offer"] = True
            send_transfer_args["passive_token"] = passive_token
            status_message_suffix = f" (Passive Offer, token: {passive_token[:8]})"
            if not ctcp_message:
                self.dcc_event_logger.error(f"Failed to format passive DCC SEND CTCP for '{original_filename}' to {peer_nick}.")
                return {"success": False, "error": "Failed to format passive DCC SEND CTCP message."}
            self.dcc_event_logger.debug(f"Passive SEND to {peer_nick} for '{original_filename}'. CTCP: {ctcp_message.strip()}")
        else: # Active DCC
            socket_info = self._get_listening_socket()
            if not socket_info:
                self.dcc_event_logger.error(f"Could not get listening socket for active SEND of '{original_filename}' to {peer_nick}.")
                return {"success": False, "error": "Could not create listening socket for active DCC SEND."}
            listening_socket, port = socket_info
            local_ip_for_ctcp = self._get_local_ip_for_ctcp()
            ctcp_message = format_dcc_send_ctcp(original_filename, local_ip_for_ctcp, port, filesize)
            send_transfer_args["server_socket_for_active_send"] = listening_socket
            status_message_suffix = f". Waiting for connection on port {port}."
            if not ctcp_message:
                listening_socket.close()
                self.dcc_event_logger.error(f"Failed to format active DCC SEND CTCP for '{original_filename}' to {peer_nick}.")
                return {"success": False, "error": "Failed to format active DCC SEND CTCP message."}
            self.dcc_event_logger.debug(f"Active SEND to {peer_nick} for '{original_filename}'. CTCP: {ctcp_message.strip()}")

        # Pass the dcc_event_logger to the transfer object
        send_transfer_args["dcc_event_logger"] = self.dcc_event_logger
        send_transfer = DCCSendTransfer(**send_transfer_args)

        with self._lock:
            self.transfers[transfer_id] = send_transfer

        self.client_logic.send_ctcp_privmsg(peer_nick, ctcp_message)

        if passive:
            send_transfer._report_status(DCCTransferStatus.NEGOTIATING, f"Passive offer sent. Waiting for peer to ACCEPT with token.{status_message_suffix}")
            # For passive, thread starts when ACCEPT is received from peer.
        else: # Active
            send_transfer._report_status(DCCTransferStatus.NEGOTIATING, f"Waiting for peer to connect.{status_message_suffix}")
            send_transfer.start_transfer_thread() # Active send starts listening immediately

        self.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", {
            "transfer_id": transfer_id, "type": "SEND", "nick": peer_nick,
            "filename": original_filename, "size": filesize, "is_passive": passive
        })
        self.client_logic.add_message(f"DCC SEND to {peer_nick} for '{original_filename}' ({filesize} bytes) initiated{status_message_suffix}", "system", context_name="DCC")
        return {"success": True, "transfer_id": transfer_id, "token": passive_token if passive else None, "filename": original_filename}


    def initiate_sends(self, peer_nick: str, local_filepaths: List[str], passive: bool = False) -> Dict[str, Any]:
        """
        Initiates DCC SEND for one or more files. Files are queued if a transfer to the same peer is active.
        """
        if not self.dcc_config.get("enabled"):
            return {"success": False, "error": "DCC is disabled.", "transfers_started": [], "files_queued": [], "errors": []}

        results: Dict[str, Any] = {
            "transfers_started": [],
            "files_queued": [],
            "errors": [],
            "overall_success": True # Becomes false if any critical error occurs
        }

        validated_files_to_process: List[Dict[str, Any]] = []

        for fp_index, local_filepath_orig in enumerate(local_filepaths):
            abs_local_filepath = os.path.abspath(local_filepath_orig)
            original_filename = os.path.basename(abs_local_filepath)

            if not os.path.isfile(abs_local_filepath):
                err_msg = f"File not found: {original_filename} (path: {local_filepath_orig})"
                self.dcc_event_logger.warning(f"DCC SEND to {peer_nick}: {err_msg}")
                results["errors"].append({"filename": original_filename, "error": err_msg})
                continue

            try:
                filesize = os.path.getsize(abs_local_filepath)
            except OSError as e:
                err_msg = f"Could not get file size for '{original_filename}': {e}"
                self.dcc_event_logger.warning(f"DCC SEND to {peer_nick}: {err_msg}")
                results["errors"].append({"filename": original_filename, "error": err_msg})
                continue

            if filesize > self.dcc_config["max_file_size"]:
                err_msg = f"File '{original_filename}' exceeds maximum size of {self.dcc_config['max_file_size']} bytes."
                self.dcc_event_logger.warning(f"DCC SEND to {peer_nick}: {err_msg}")
                results["errors"].append({"filename": original_filename, "error": err_msg})
                continue

            validated_files_to_process.append({
                "local_filepath": abs_local_filepath,
                "original_filename": original_filename,
                "filesize": filesize,
                "passive": passive # All files in a single /dcc send command share the passive flag
            })

        if not validated_files_to_process:
            results["overall_success"] = False # No valid files to process
            if not results["errors"]: # If no specific file errors, add a generic one
                 results["error"] = "No valid files provided for sending."
            return results

        with self._lock:
            # Check if there's an active DCCSendTransfer to this peer
            is_active_send_to_peer = any(
                isinstance(t, DCCSendTransfer) and t.peer_nick == peer_nick and
                t.status not in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]
                for t in self.transfers.values()
            )

            queue_exists_for_peer = peer_nick in self.send_queues and self.send_queues[peer_nick]

            if is_active_send_to_peer or queue_exists_for_peer:
                # Queue all validated files
                if peer_nick not in self.send_queues:
                    self.send_queues[peer_nick] = deque()

                for file_info in validated_files_to_process:
                    self.send_queues[peer_nick].append(file_info)
                    results["files_queued"].append({"filename": file_info["original_filename"], "size": file_info["filesize"]})
                    self.dcc_event_logger.info(f"Queued DCC SEND of '{file_info['original_filename']}' to {peer_nick}. Queue size: {len(self.send_queues[peer_nick])}")
                    self.client_logic.add_message(f"Queued DCC SEND of '{file_info['original_filename']}' to {peer_nick}.", "system", context_name="DCC")
            else:
                # No active send or queue, start the first file and queue the rest
                self.dcc_event_logger.info(f"No active send or queue for {peer_nick}. Starting first file and queuing rest.")
                first_file_info = validated_files_to_process.pop(0)
                exec_result = self._execute_send(
                    peer_nick,
                    first_file_info["local_filepath"],
                    first_file_info["original_filename"],
                    first_file_info["filesize"],
                    first_file_info["passive"]
                )
                if exec_result.get("success"):
                    results["transfers_started"].append({
                        "filename": exec_result.get("filename", first_file_info["original_filename"]),
                        "transfer_id": exec_result.get("transfer_id"),
                        "token": exec_result.get("token")
                    })
                else:
                    results["errors"].append({
                        "filename": first_file_info["original_filename"],
                        "error": exec_result.get("error", "Failed to start transfer")
                    })
                    results["overall_success"] = False # If first fails, mark overall as failed for now

                # Queue remaining validated files
                if validated_files_to_process:
                    if peer_nick not in self.send_queues:
                        self.send_queues[peer_nick] = deque()
                    for file_info in validated_files_to_process:
                        self.send_queues[peer_nick].append(file_info)
                        results["files_queued"].append({"filename": file_info["original_filename"], "size": file_info["filesize"]})
                        self.dcc_event_logger.info(f"Queued DCC SEND of '{file_info['original_filename']}' to {peer_nick} (after starting first). Queue size: {len(self.send_queues[peer_nick])}")
                        self.client_logic.add_message(f"Queued DCC SEND of '{file_info['original_filename']}' to {peer_nick} (after starting first).", "system", context_name="DCC")

        if not results["transfers_started"] and not results["files_queued"] and not results["errors"]:
            results["error"] = "No files processed." # Should be caught by empty validated_files_to_process
            results["overall_success"] = False

        return results

    def _process_next_in_send_queue(self, peer_nick: str):
        """Checks the send queue for a peer and starts the next transfer if available."""
        file_to_send_info: Optional[Dict[str, Any]] = None
        with self._lock:
            if peer_nick in self.send_queues and self.send_queues[peer_nick]:
                file_to_send_info = self.send_queues[peer_nick].popleft()
                if not self.send_queues[peer_nick]: # If queue is now empty
                    del self.send_queues[peer_nick]
                self.dcc_event_logger.info(f"Dequeued '{file_to_send_info['original_filename'] if file_to_send_info else 'N/A'}' for sending to {peer_nick}. Remaining queue size: {len(self.send_queues.get(peer_nick, []))}")
            else:
                self.dcc_event_logger.debug(f"No more files in send queue for {peer_nick}.")

        if file_to_send_info:
            self.client_logic.add_message(f"Starting next queued DCC SEND of '{file_to_send_info['original_filename']}' to {peer_nick}.", "system", context_name="DCC")
            self.dcc_event_logger.info(f"Processing next from queue for {peer_nick}: '{file_to_send_info['original_filename']}'")
            self._execute_send(
                peer_nick,
                file_to_send_info["local_filepath"],
                file_to_send_info["original_filename"],
                file_to_send_info["filesize"],
                file_to_send_info["passive"]
            )

    def handle_incoming_dcc_ctcp(self, nick: str, userhost: str, ctcp_payload: str):
        """Handles a parsed DCC CTCP command from a peer."""
        if not self.dcc_config.get("enabled"):
            self.dcc_event_logger.info(f"DCC disabled, ignoring incoming DCC CTCP from {nick}: {ctcp_payload}")
            return

        self.dcc_event_logger.debug(f"Received raw CTCP from {nick} ({userhost}): {ctcp_payload}")
        parsed_dcc = parse_dcc_ctcp(ctcp_payload)
        if not parsed_dcc:
            self.dcc_event_logger.warning(f"Could not parse DCC CTCP from {nick}: {ctcp_payload}")
            self.client_logic.add_message(f"Received malformed DCC request from {nick}.", "error", context_name="Status")
            return

        dcc_command = parsed_dcc.get("dcc_command")
        self.dcc_event_logger.info(f"Received DCC Command '{dcc_command}' from {nick} with data: {parsed_dcc}")

        if dcc_command == "SEND":
            filename = parsed_dcc.get("filename")
            ip_str = parsed_dcc.get("ip_str")
            port = parsed_dcc.get("port")
            filesize = parsed_dcc.get("filesize")
            is_passive_offer = parsed_dcc.get("is_passive_offer", False)
            token = parsed_dcc.get("token")

            if None in [filename, ip_str, port, filesize]: # filesize can be 0 for empty file
                self.dcc_event_logger.warning(f"DCC SEND from {nick} missing critical information: {parsed_dcc}")
                return

            event_data = {
                "nick": nick, "userhost": userhost, "filename": filename, "size": filesize,
                "ip": ip_str, "port": port, "is_passive_offer": is_passive_offer
            }
            if token:
                event_data["token"] = token
            self.event_manager.dispatch_event("DCC_SEND_OFFER_INCOMING", event_data)

            if is_passive_offer:
                if token: # Passive offers must have a token by our design
                    with self._lock:
                        self.pending_passive_offers[token] = {
                            "nick": nick,
                            "filename": filename,
                            "filesize": filesize,
                            "userhost": userhost,
                            "timestamp": time.time()
                        }
                    self.dcc_event_logger.info(f"Stored pending passive DCC SEND offer from {nick} for '{filename}' with token {token}.")
                    self._cleanup_stale_passive_offers() # Opportunistic cleanup
                    self.client_logic.add_message(
                        f"Passive DCC SEND offer from {nick} ({userhost}): '{filename}' ({filesize} bytes). "
                        f"Use /dcc get {nick} \"{filename}\" --token {token} to receive.",
                        "system", context_name="DCC"
                    )
                else: # Passive offer without a token - spec might allow, but our flow expects it.
                    self.dcc_event_logger.warning(f"Passive DCC SEND offer from {nick} for '{filename}' missing token. Ignoring.")
                    self.client_logic.add_message(f"Malformed passive DCC SEND offer from {nick} (missing token).", "error", context_name="Status")
            else: # Active offer
                self.dcc_event_logger.info(f"Received active DCC SEND offer from {nick} for '{filename}'. IP={ip_str}, Port={port}, Size={filesize}")
                self.client_logic.add_message(
                    f"DCC SEND offer from {nick} ({userhost}): '{filename}' ({filesize} bytes) from {ip_str}:{port}. "
                    f"Use /dcc accept {nick} \"{filename}\" {ip_str} {port} {filesize} to receive.",
                    "system", context_name="DCC"
                )
                # Auto-accept logic
                if self.dcc_config.get("auto_accept", False):
                    if is_passive_offer:
                        if filename is not None and token is not None: # Crucial check for passive auto-accept
                            self.dcc_event_logger.info(f"Attempting auto-accept for PASSIVE offer from {nick} for '{filename}' with token {token}")
                            # filename and token are confirmed non-None here
                            result = self.accept_passive_offer_by_token(nick, filename, token)
                            if result.get("success"):
                                transfer_id_val = result.get('transfer_id')
                                transfer_id_short = transfer_id_val[:8] if transfer_id_val else "N/A"
                                self.dcc_event_logger.info(f"Auto-accepted PASSIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {transfer_id_short}")
                                self.client_logic.add_message(f"Auto-accepted PASSIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {transfer_id_short}", "system", context_name="DCC")
                                return # Offer handled
                            else:
                                self.dcc_event_logger.error(f"Auto-accept for PASSIVE DCC SEND from {nick} for '{str(filename)}' failed: {result.get('error')}")
                                self.client_logic.add_message(f"Auto-accept for PASSIVE DCC SEND from {nick} for '{str(filename)}' failed: {result.get('error')}", "error", context_name="DCC")
                                return
                        else:
                            self.dcc_event_logger.warning(f"Skipping auto-accept for passive offer from {nick} due to missing filename or token.")
                            # Fall through to manual prompt logic below, as auto-accept cannot proceed.
                    else: # Active offer auto-accept
                        # The `if None in [filename, ip_str, port, filesize]:` check earlier covers this.
                        # If we reach here, all these parameters are guaranteed to be non-None.
                        self.dcc_event_logger.info(f"Attempting auto-accept for ACTIVE offer from {nick} for '{str(filename)}'")
                        # Explicitly assert types for Pylance if direct pass-through is still an issue,
                        # but the prior check should make them valid.
                        assert filename is not None
                        assert ip_str is not None
                        assert port is not None
                        assert filesize is not None
                        result = self.accept_incoming_send_offer(nick, filename, ip_str, port, filesize)
                        if result.get("success"):
                            transfer_id_val = result.get('transfer_id')
                            transfer_id_short = transfer_id_val[:8] if transfer_id_val else "N/A"
                            self.dcc_event_logger.info(f"Auto-accepted ACTIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {transfer_id_short}")
                            self.client_logic.add_message(f"Auto-accepted ACTIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {transfer_id_short}", "system", context_name="DCC")
                            return # Offer handled
                        else:
                            self.dcc_event_logger.error(f"Auto-accept for ACTIVE DCC SEND from {nick} for '{str(filename)}' failed: {result.get('error')}")
                            self.client_logic.add_message(f"Auto-accept for ACTIVE DCC SEND from {nick} for '{str(filename)}' failed: {result.get('error')}", "error", context_name="DCC")
                            return
                # If auto_accept is false, or if conditions for auto-accept weren't met (e.g. missing params for passive),
                # the code will fall through to the manual prompt logic below.
                # The return statements above prevent falling through if auto-accept was decisively processed (success or failure after attempt).

        elif dcc_command == "ACCEPT":
            is_passive_dcc_accept = parsed_dcc.get("is_passive_accept", False)
            is_resume_accept = parsed_dcc.get("is_resume_accept", False)
            filename = parsed_dcc.get("filename") # Should always be present for ACCEPT

            if is_passive_dcc_accept:
                accepted_ip = parsed_dcc.get("ip_str")
                accepted_port = parsed_dcc.get("port")
                accepted_token = parsed_dcc.get("token")
                self.dcc_event_logger.info(f"Received Passive DCC ACCEPT from {nick} for '{filename}' (IP: {accepted_ip}, Port: {accepted_port}, Token: {accepted_token})")

                if not all([filename, accepted_ip, accepted_port is not None, accepted_token]): # Port can be 0, but must exist
                    self.dcc_event_logger.warning(f"Passive DCC ACCEPT from {nick} for '{filename}' missing critical info: {parsed_dcc}")
                    return

                found_transfer = None
                with self._lock:
                    for tid, transfer in self.transfers.items():
                        if (isinstance(transfer, DCCSendTransfer) and
                            transfer.is_passive_offer and
                            transfer.passive_token == accepted_token and
                            transfer.original_filename == filename and
                            transfer.peer_nick == nick):
                            found_transfer = transfer
                            break

                if found_transfer:
                    self.dcc_event_logger.info(f"Matching passive SEND offer found (ID: {found_transfer.transfer_id}). Initiating connection to {nick} at {accepted_ip}:{accepted_port}")
                    found_transfer.connect_to_ip = accepted_ip # Store for DCCSendTransfer.run()
                    found_transfer.connect_to_port = accepted_port
                    found_transfer._report_status(DCCTransferStatus.CONNECTING, f"Peer accepted passive offer. Connecting to {accepted_ip}:{accepted_port}.")
                    found_transfer.start_transfer_thread() # Now the sender connects
                else:
                    self.dcc_event_logger.warning(f"Received Passive DCC ACCEPT from {nick} for '{filename}' with token '{accepted_token}', but no matching passive offer found.")
                    self.client_logic.add_message(f"Received unexpected Passive DCC ACCEPT from {nick} for '{filename}'.", "warning", context_name="Status")

            elif is_resume_accept:
                # This is when peer ACKs our RESUME offer.
                # Our DCCSendTransfer (created when we sent DCC RESUME) should be listening.
                # The accept() call in its run() method will handle the connection.
                # This CTCP ACCEPT is mostly an acknowledgment.
                accepted_filename = parsed_dcc.get("filename")
                accepted_port = parsed_dcc.get("port") # This should be the port we told them we're listening on for resume
                accepted_position = parsed_dcc.get("position") # This should be the offset we offered

                self.dcc_event_logger.info(f"Received Resume DCC ACCEPT from {nick} for '{accepted_filename}' (Port: {accepted_port}, Position: {accepted_position}).")

                found_resuming_send_transfer = None
                with self._lock:
                    for tid, transfer_obj in self.transfers.items():
                        if (isinstance(transfer_obj, DCCSendTransfer) and
                            transfer_obj.peer_nick == nick and
                            transfer_obj.original_filename == accepted_filename and
                            hasattr(transfer_obj, 'resume_offset') and # Check if it's a resume-capable transfer object
                            transfer_obj.resume_offset == accepted_position and
                            transfer_obj.status == DCCTransferStatus.NEGOTIATING and # It should be waiting for connection
                            transfer_obj.server_socket is not None and # It should have a listening socket
                            transfer_obj.server_socket.getsockname()[1] == accepted_port): # Port matches
                            found_resuming_send_transfer = transfer_obj
                            break

                if found_resuming_send_transfer:
                    # The actual connection is handled by the listening socket in DCCSendTransfer.run()
                    # This ACCEPT confirms the peer is proceeding with the resume.
                    # We might change status here slightly or just log.
                    self.dcc_event_logger.info(f"DCC RESUME for '{accepted_filename}' to {nick} acknowledged by peer. Transfer {found_resuming_send_transfer.transfer_id} should proceed.")
                    # The transfer status will change to CONNECTING/TRANSFERRING when the socket accepts.
                    # We don't need to call start_transfer_thread() again as it's already running and listening.
                else:
                    self.dcc_event_logger.warning(f"Received Resume DCC ACCEPT from {nick} for '{accepted_filename}', but no matching active RESUME offer found or details mismatch.")
                    self.client_logic.add_message(f"Received unexpected/mismatched Resume DCC ACCEPT from {nick} for '{accepted_filename}'.", "warning", context_name="Status")

            else: # Should not happen if parsed_dcc is valid and has is_passive_accept or is_resume_accept
                self.dcc_event_logger.warning(f"Received ambiguous DCC ACCEPT from {nick}: {parsed_dcc}")

        elif dcc_command == "RESUME": # Peer is offering to RESUME sending a file to us
            # DCC RESUME <filename> <peer_listening_port> <position_peer_will_send_from>
            # Peer's IP is implicitly known from CTCP source (nick).
            # dcc_protocol.parse_dcc_ctcp for RESUME should provide: filename, port, position

            if not self.dcc_config.get("resume_enabled", True):
                self.dcc_event_logger.info(f"DCC RESUME from {nick} ignored, resume disabled in config.")
                # Optionally send a reject CTCP? For now, just ignore.
                return

            resume_filename = parsed_dcc.get("filename")
            resume_peer_port = parsed_dcc.get("port")
            resume_position_offered_by_peer = parsed_dcc.get("position")
            # Assuming peer's IP is implicitly the source of the CTCP.
            # We need the actual IP of the sender to connect to.
            # For now, let's assume DCCManager can get the peer's IP if needed, or that the protocol implies it.
            # This part needs careful thought on how peer_ip is obtained for the connection.
            # Let's assume for now the client_logic can provide the peer's IP based on nick.
            # This is a placeholder, real IP lookup might be needed.
            # For now, we'll assume client_logic can provide it. If not, we can't proceed.
            # A more robust method would be to store peer IP from initial DCC SEND offer.
            peer_ip_address = None
            if hasattr(self.client_logic, 'get_user_ip') and callable(self.client_logic.get_user_ip):
                 peer_ip_address = self.client_logic.get_user_ip(nick)

            if not peer_ip_address:
                self.dcc_event_logger.error(f"DCC RESUME from {nick} for '{resume_filename}': Could not determine peer IP address. Cannot proceed.")
                self.client_logic.add_message(f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': Peer IP unknown.", "error", context_name="DCC")
                return

            if not all([resume_filename, resume_peer_port is not None, resume_position_offered_by_peer is not None]): # Removed peer_ip_address from here as it's checked above
                self.dcc_event_logger.warning(f"DCC RESUME from {nick} missing critical information: {parsed_dcc}")
                return

            assert isinstance(resume_filename, str), "resume_filename must be a string after the all() check"

            self.dcc_event_logger.info(f"Received DCC RESUME offer from {nick} for '{resume_filename}' to port {resume_peer_port} from offset {resume_position_offered_by_peer}.")

            # Look for an existing partial download to determine total filesize and validate resume
            existing_transfer_info: Optional[Dict[str, Any]] = None
            with self._lock:
                for tid, transfer in self.transfers.items():
                    if (isinstance(transfer, DCCReceiveTransfer) and
                        transfer.peer_nick == nick and
                        transfer.original_filename == resume_filename and
                        transfer.status in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]):
                        existing_transfer_info = {
                            "local_filepath": transfer.local_filepath,
                            "total_filesize": transfer.filesize, # Crucial: get total size from previous attempt
                            "current_bytes": transfer.bytes_transferred
                        }
                        break

            if not existing_transfer_info:
                if resume_position_offered_by_peer == 0:
                    # Peer offers to send from start, and we have no prior record. Treat as a new SEND offer essentially.
                    # However, a RESUME CTCP doesn't carry total filesize. This is problematic.
                    # For now, we cannot accept a RESUME offer for a completely new file if it doesn't start at 0
                    # and even then, we don't know the total size.
                    # A more compliant client might send DCC SEND first, then we could request RESUME.
                    self.dcc_event_logger.warning(f"DCC RESUME from {nick} for '{resume_filename}' at offset 0, but no prior transfer record found. Total filesize is unknown. Rejecting.")
                    self.client_logic.add_message(f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': No prior transfer record to determine total filesize.", "error", context_name="DCC")
                    return # Reject if no prior record and offset is 0 (filesize unknown)
                else: # resume_position_offered_by_peer > 0 but no record
                    self.dcc_event_logger.warning(f"DCC RESUME from {nick} for '{resume_filename}' at offset {resume_position_offered_by_peer}, but no prior transfer record found. Rejecting.")
                    self.client_logic.add_message(f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': No prior transfer record.", "error", context_name="DCC")
                    return

            # At this point, existing_transfer_info is guaranteed to be populated if we didn't return.
            local_file_path_to_check = existing_transfer_info["local_filepath"]
            total_filesize = existing_transfer_info["total_filesize"]

            if total_filesize <= 0: # Should not happen if we had a valid prior transfer
                self.dcc_event_logger.error(f"DCC RESUME from {nick} for '{resume_filename}': Prior transfer record has invalid total filesize ({total_filesize}). Rejecting.")
                self.client_logic.add_message(f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': Invalid prior transfer data.", "error", context_name="DCC")
                return

            actual_resume_offset = 0
            can_resume_this_offer = False

            if os.path.exists(local_file_path_to_check):
                current_local_size = os.path.getsize(local_file_path_to_check)
                if current_local_size == resume_position_offered_by_peer:
                    actual_resume_offset = current_local_size
                    can_resume_this_offer = True
                    self.dcc_event_logger.info(f"Local file '{local_file_path_to_check}' size {current_local_size} matches peer's offered RESUME offset {resume_position_offered_by_peer}. Will accept.")
                else:
                    self.dcc_event_logger.warning(f"DCC RESUME from {nick}: local file '{local_file_path_to_check}' size {current_local_size} mismatches peer's offered offset {resume_position_offered_by_peer}. Cannot accept this RESUME offer as is.")
                    # Optionally, could send DCC ACCEPT with *our* current_local_size if we want to request resume from *our* end.
                    # For now, if peer's offset doesn't match our local state exactly for an existing file, we reject their RESUME offer.
            elif resume_position_offered_by_peer == 0: # Peer offers to send from start, we had a record but local file is gone.
                 can_resume_this_offer = True # Effectively a new download, but we know the total_filesize
                 actual_resume_offset = 0
                 # local_file_path_to_check is already set from existing_transfer_info.original_filename
                 self.dcc_event_logger.info(f"DCC RESUME from {nick} for '{resume_filename}' is from offset 0. Local file missing/re-downloading to '{local_file_path_to_check}'.")

            if can_resume_this_offer:
                # Send DCC ACCEPT <filename> <our_ip_or_0_ignored> <our_connecting_port_ignored> <actual_resume_offset>
                # The port in this ACCEPT is not critical as the peer is already listening.
                # The IP is also not strictly needed by the peer for resume.
                ctcp_accept_msg = format_dcc_accept_ctcp(resume_filename, "0", 0, actual_resume_offset, token=None)
                if not ctcp_accept_msg:
                    self.dcc_event_logger.error(f"Failed to format DCC ACCEPT for RESUME from {nick}.")
                    return

                self.client_logic.send_ctcp_privmsg(nick, ctcp_accept_msg)

                new_transfer_id = self._generate_transfer_id()
                # If existing_transfer, we might reuse its ID or update it. For simplicity, new ID for new attempt.

                # Path validation for local_file_path_to_check should have happened when existing_transfer_info was created.
                # If actual_resume_offset is 0 and file was missing, local_file_path_to_check was (re)derived.
                # We trust local_file_path_to_check from existing_transfer_info or its re-derivation.

                recv_resume_args = {
                    "transfer_id": new_transfer_id,
                    "peer_nick": nick,
                    "filename": resume_filename,
                    "filesize": total_filesize, # Use the known total_filesize from prior record
                    "local_filepath": local_file_path_to_check, # This is the validated path
                    "dcc_manager_ref": self,
                    "connect_to_ip": peer_ip_address,
                    "connect_to_port": resume_peer_port,
                    "resume_offset": actual_resume_offset,
                    "dcc_event_logger": self.dcc_event_logger
                }
                # DCC RESUME typically doesn't include total filesize. This needs to be obtained from original offer or stored.
                # For now, if existing_transfer, use its filesize. Otherwise, this is problematic.
                # Let's assume filesize is known from a previous offer or needs to be requested again.
                # For this simplified step, we'll assume filesize is available if existing_transfer.
                # If not existing_transfer and offset is 0, this is like a new SEND, but RESUME protocol might not provide total size.
                # This needs clarification from DCC spec for RESUME. For now, proceed if filesize is sensible.
                # No need for the filesize check here as total_filesize is now sourced reliably.

                new_recv_transfer = DCCReceiveTransfer(**recv_resume_args)
                with self._lock:
                    self.transfers[new_transfer_id] = new_recv_transfer

                new_recv_transfer._report_status(DCCTransferStatus.CONNECTING, f"Accepted RESUME from {nick}. Connecting to resume download.")
                new_recv_transfer.start_transfer_thread()
                self.client_logic.add_message(f"Accepted DCC RESUME from {nick} for '{resume_filename}'. Resuming download from offset {actual_resume_offset}.", "system", context_name="DCC")
            else:
                self.dcc_event_logger.info(f"Cannot accept DCC RESUME from {nick} for '{resume_filename}' under current conditions (offset mismatch or file issue).")
                # Optionally send reject CTCP
                self.client_logic.add_message(f"Could not accept DCC RESUME from {nick} for '{resume_filename}' (offset/file mismatch).", "warning", context_name="DCC")


        elif dcc_command == "DCCCHECKSUM":
            self.dcc_event_logger.debug(f"Received DCCCHECKSUM CTCP from {nick}: {parsed_dcc}")
            # Parsed by dcc_protocol.py: {'dcc_command': 'DCCCHECKSUM', 'filename': ...,
            # 'algorithm': ..., 'checksum_value': ..., 'transfer_identifier': ...}

            transfer_identifier = parsed_dcc.get("transfer_identifier")
            filename = parsed_dcc.get("filename")
            algorithm = parsed_dcc.get("algorithm")
            checksum_value = parsed_dcc.get("checksum_value")

            if not all([transfer_identifier, filename, algorithm, checksum_value]):
                self.dcc_event_logger.warning(f"Malformed DCCCHECKSUM from {nick}: {parsed_dcc}")
                return

            # At this point, algorithm and checksum_value are guaranteed not to be None by the all() check.
            # We can cast them to str for Pylance if it's still an issue, or rely on the runtime check.
            # For now, let's assume the all() check is sufficient for runtime, Pylance might need explicit cast.
            # However, the .get() still returns Optional[str], so Pylance is correct to warn without a cast/check.
            # The `all()` check ensures they are truthy (not None and not empty string).

            self.dcc_event_logger.info(f"Received DCCCHECKSUM from {nick} for transfer '{transfer_identifier}', file '{filename}', algo '{algorithm}'.")

            transfer_to_update = None
            with self._lock:
                # Try to find by transfer_id first
                if transfer_identifier in self.transfers:
                    potential_transfer = self.transfers[transfer_identifier]
                    if isinstance(potential_transfer, DCCReceiveTransfer) and \
                       potential_transfer.peer_nick == nick and \
                       potential_transfer.original_filename == filename:
                        transfer_to_update = potential_transfer

                # Fallback: If not found by ID, maybe by filename and nick (less reliable if multiple transfers of same file)
                if not transfer_to_update:
                    for tid, tr_obj in self.transfers.items():
                        if isinstance(tr_obj, DCCReceiveTransfer) and \
                           tr_obj.peer_nick == nick and \
                          tr_obj.original_filename == filename and \
                          tr_obj.status == DCCTransferStatus.COMPLETED:
                           # Only apply to completed transfers if ID didn't match, to avoid ambiguity
                           transfer_to_update = tr_obj
                           self.dcc_event_logger.info(f"DCCCHECKSUM matched by filename/nick for completed transfer {tid}")
                           break
            # This block is now correctly indented (12 spaces), same level as `with self._lock`
            if transfer_to_update:
                if hasattr(transfer_to_update, 'set_expected_checksum'):
                    # The `all()` check above ensures algorithm and checksum_value are not None.
                    cast_algorithm: str = str(algorithm)
                    cast_checksum_value: str = str(checksum_value)
                    transfer_to_update.set_expected_checksum(cast_algorithm, cast_checksum_value)
                else:
                    self.dcc_event_logger.error(f"Transfer object {transfer_to_update.transfer_id} does not have set_expected_checksum method.")
            else:
                self.dcc_event_logger.warning(f"Received DCCCHECKSUM from {nick} for '{filename}' (ID/Ref: {transfer_identifier}), but no matching active/completed RECV transfer found.")
       # This 'else' is now correctly aligned with the main if/elif dcc_command checks (8 spaces)
        else:
            self.dcc_event_logger.warning(f"Received unhandled DCC command '{dcc_command}' from {nick}: {parsed_dcc}")
            self.client_logic.add_message(f"Received unhandled DCC '{dcc_command}' from {nick}: {' '.join(parsed_dcc.get('args',[]))}", "system", context_name="Status")


    def accept_incoming_send_offer(self, peer_nick: str, original_filename: str, ip_str: str, port: int, filesize: int) -> Dict[str, Any]:
        """
        Called by command handler when user accepts a DCC SEND offer.
        Initiates a DCCReceiveTransfer (Active DCC RECV for Phase 1).
        """
        self.dcc_event_logger.info(f"Attempting to accept ACTIVE DCC SEND offer from {peer_nick} for '{original_filename}' ({ip_str}:{port}, {filesize} bytes).")
        if not self.dcc_config.get("enabled"):
            return {"success": False, "error": "DCC is disabled."}

        validation_result = validate_download_path(
            original_filename,
            self.dcc_config["download_dir"],
            self.dcc_config["blocked_extensions"],
            self.dcc_config["max_file_size"],
            filesize
        )

        if not validation_result["success"]:
            return {"success": False, "error": validation_result["error"], "sanitized_filename": validation_result.get("sanitized_filename")}

        safe_local_path = validation_result["safe_path"]
        sanitized_filename_for_log = validation_result["sanitized_filename"]

        transfer_id = self._generate_transfer_id()
        recv_transfer = DCCReceiveTransfer(
            transfer_id=transfer_id,
            peer_nick=peer_nick,
            filename=original_filename, # Original filename for display/logging
            filesize=filesize,
            local_filepath=safe_local_path, # Where to save the file
            dcc_manager_ref=self,
            connect_to_ip=ip_str, # For active DCC RECV, we connect
            connect_to_port=port,
            dcc_event_logger=self.dcc_event_logger # Pass the logger
        )

        with self._lock:
            self.transfers[transfer_id] = recv_transfer
            self.dcc_event_logger.debug(f"Created DCCReceiveTransfer (active) with ID {transfer_id} for '{original_filename}' from {peer_nick}.")

        recv_transfer._report_status(DCCTransferStatus.QUEUED) # Or CONNECTING if thread starts immediately
        recv_transfer.start_transfer_thread()

        self.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", {
            "transfer_id": transfer_id, "type": "RECEIVE", "nick": peer_nick,
            "filename": original_filename, "size": filesize
        })
        self.client_logic.add_message(f"DCC RECV for '{original_filename}' from {peer_nick} accepted. Connecting to {ip_str}:{port}. Saving to '{sanitized_filename_for_log}'.", "system", context_name="DCC")
        return {"success": True, "transfer_id": transfer_id}

    def initiate_passive_receive(self, peer_nick: str, offered_filename: str, offered_filesize: int, offer_token: str) -> Dict[str, Any]:
        """
        Called when the local user wants to accept a PASSIVE DCC SEND offer they received.
        This client will listen, and send an ACCEPT CTCP to the peer, who will then connect.
        """
        self.dcc_event_logger.info(f"Attempting to initiate PASSIVE DCC RECV for '{offered_filename}' from {peer_nick} (token: {offer_token}, size: {offered_filesize}).")
        if not self.dcc_config.get("enabled"):
            return {"success": False, "error": "DCC is disabled."}

        # logger.info(f"Attempting to initiate passive receive for '{offered_filename}' from {peer_nick} (token: {offer_token}).") # Redundant with above

        validation_result = validate_download_path(
            offered_filename,
            self.dcc_config["download_dir"],
            self.dcc_config["blocked_extensions"],
            self.dcc_config["max_file_size"],
            offered_filesize
        )

        if not validation_result["success"]:
            return {"success": False, "error": validation_result["error"], "sanitized_filename": validation_result.get("sanitized_filename")}

        safe_local_path = validation_result["safe_path"]
        sanitized_filename_for_log = validation_result["sanitized_filename"]

        socket_info = self._get_listening_socket()
        if not socket_info:
            return {"success": False, "error": "Could not create listening socket for passive DCC RECV."}

        listening_socket, local_listening_port = socket_info
        local_ip_for_ctcp = self._get_local_ip_for_ctcp()

        # We send an ACCEPT with our listening IP/Port, position 0, and the token
        ctcp_accept_message = format_dcc_accept_ctcp(
            filename=offered_filename,
            ip_str=local_ip_for_ctcp,
            port=local_listening_port,
            position=0, # Position is 0 for new passive transfers
            token=offer_token
        )

        if not ctcp_accept_message:
            listening_socket.close()
            self.dcc_event_logger.error(f"Failed to format passive DCC ACCEPT CTCP for '{offered_filename}' to {peer_nick}.")
            return {"success": False, "error": "Failed to format passive DCC ACCEPT CTCP message."}
        self.dcc_event_logger.debug(f"Passive RECV for '{offered_filename}' from {peer_nick}. Sent ACCEPT CTCP: {ctcp_accept_message.strip()}")

        transfer_id = self._generate_transfer_id()
        # Ensure DCCReceiveTransfer can handle server_socket_for_passive_recv
        recv_transfer_args = {
            "transfer_id":transfer_id,
            "peer_nick":peer_nick,
            "filename":offered_filename,
            "filesize":offered_filesize,
            "local_filepath":safe_local_path,
            "dcc_manager_ref":self,
            "server_socket_for_passive_recv":listening_socket,
            "dcc_event_logger": self.dcc_event_logger # Pass the logger
        }
        recv_transfer = DCCReceiveTransfer(**recv_transfer_args)

        with self._lock:
            self.transfers[transfer_id] = recv_transfer
            self.dcc_event_logger.debug(f"Created DCCReceiveTransfer (passive setup) with ID {transfer_id} for '{offered_filename}' from {peer_nick}.")

        # Send the CTCP ACCEPT to the peer, inviting them to connect to us
        self.client_logic.send_ctcp_privmsg(peer_nick, ctcp_accept_message)

        recv_transfer._report_status(DCCTransferStatus.NEGOTIATING, f"Sent passive ACCEPT. Waiting for {peer_nick} to connect to {local_ip_for_ctcp}:{local_listening_port}.")
        recv_transfer.start_transfer_thread() # This thread will now block on listening_socket.accept()

        self.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", {
            "transfer_id": transfer_id, "type": "RECEIVE", "nick": peer_nick,
            "filename": offered_filename, "size": offered_filesize, "is_passive_setup": True
        })
        self.client_logic.add_message(
            f"Passive DCC RECV for '{offered_filename}' from {peer_nick} initiated. "
            f"Listening on {local_ip_for_ctcp}:{local_listening_port}. Waiting for peer connection.",
            "system", context_name="DCC"
        )
        return {"success": True, "transfer_id": transfer_id}

    def accept_passive_offer_by_token(self, calling_nick_for_logging: str, offered_filename_by_user: str, offer_token: str) -> Dict[str, Any]:
        """
        Accepts a stored passive DCC SEND offer based on a token.
        Called by the /dcc get command.
        """
        self.dcc_event_logger.info(f"User {calling_nick_for_logging} attempting to accept passive offer with token: {offer_token} for filename: {offered_filename_by_user}")
        pending_offer_details = None
        with self._lock:
            pending_offer_details = self.pending_passive_offers.get(offer_token)

        if not pending_offer_details:
            self.dcc_event_logger.warning(f"Passive offer with token '{offer_token}' not found or expired for user {calling_nick_for_logging}.")
            return {"success": False, "error": f"Passive offer with token '{offer_token}' not found or expired."}

        # Verify details (optional, but good for sanity)
        # The filename from user command might differ slightly (e.g. no quotes) from stored one.
        # For now, primary match is by token.
        original_sender_nick = pending_offer_details["nick"]
        original_offered_filename = pending_offer_details["filename"]
        original_filesize = pending_offer_details["filesize"]

        if offered_filename_by_user.lower() != original_offered_filename.lower():
             self.dcc_event_logger.warning(f"Filename mismatch for passive offer token {offer_token}. User: '{offered_filename_by_user}', Offer: '{original_offered_filename}'. Proceeding by token match.")

        # Remove the pending offer once we attempt to process it
        with self._lock:
            if offer_token in self.pending_passive_offers:
                del self.pending_passive_offers[offer_token]
                self.dcc_event_logger.info(f"Removed pending passive offer token {offer_token} after acceptance attempt by {calling_nick_for_logging}.")

        # Now call initiate_passive_receive with the details from the stored offer
        return self.initiate_passive_receive(
            peer_nick=original_sender_nick, # The one who made the passive offer
            offered_filename=original_offered_filename,
            offered_filesize=original_filesize,
            offer_token=offer_token # Pass the original token through
        )

    def update_transfer_status(self, transfer_id: str, status: DCCTransferStatus, error_message: Optional[str]):
        with self._lock:
            transfer = self.transfers.get(transfer_id)
        if transfer:
            old_status = transfer.status
            transfer.status = status
            transfer.error_message = error_message
            self.dcc_event_logger.info(f"Transfer {transfer_id} ('{transfer.original_filename}') status updated: {old_status.name} -> {status.name}. Error: {error_message}")

            event_name = ""
            if status == DCCTransferStatus.COMPLETED: event_name = "DCC_TRANSFER_COMPLETE"
            elif status in [DCCTransferStatus.FAILED, DCCTransferStatus.TIMED_OUT]: event_name = "DCC_TRANSFER_ERROR"
            elif status == DCCTransferStatus.CANCELLED: event_name = "DCC_TRANSFER_CANCELLED"
            elif status == DCCTransferStatus.TRANSFERRING: event_name = "DCC_TRANSFER_START" # First time it hits transferring
            # Add more specific events if needed, e.g. DCC_TRANSFER_CONNECTING

            if event_name:
                event_data = {
                    "transfer_id": transfer.transfer_id,
                    "type": transfer.transfer_type.name,
                    "nick": transfer.peer_nick,
                    "filename": transfer.original_filename,
                    "local_path": transfer.local_filepath,
                    "size": transfer.filesize # Add size to error/complete events too
                }
                if error_message:
                    event_data["error_message"] = error_message
                self.event_manager.dispatch_event(event_name, event_data)

            # Clean up completed or failed transfers from active list?
            # Or keep them for a while for /dcc list. For now, keep.
            if status in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]:
                logger.info(f"Transfer {transfer_id} ('{transfer.original_filename}') reached final state: {status.name}.")
                # If it's a send transfer, try to process the next in queue for that peer
                if isinstance(transfer, DCCSendTransfer):
                    self.dcc_event_logger.debug(f"Send transfer {transfer_id} for {transfer.peer_nick} ended. Checking send queue.")
                    self._process_next_in_send_queue(transfer.peer_nick)
                # Consider removing from self.transfers after a delay or if list gets too long.

            self.client_logic.add_message(
                f"DCC {transfer.transfer_type.name} '{transfer.original_filename}' with {transfer.peer_nick}: {status.name}"
                f"{f' ({error_message})' if error_message else ''}",
                "error" if status in [DCCTransferStatus.FAILED, DCCTransferStatus.TIMED_OUT] else "system",
                context_name="DCC"
            )
        else:
            self.dcc_event_logger.warning(f"update_transfer_status called for unknown transfer_id: {transfer_id}")

    def update_transfer_progress(self, transfer_id: str, bytes_transferred: int, total_size: int, rate_bps: float, eta_seconds: Optional[float]):
        # This can be very frequent, so logging might be too verbose for INFO/DEBUG unless specifically needed.
        # For now, no dcc_event_logger call here. Can be added if debugging specific progress issues.
        with self._lock:
            transfer = self.transfers.get(transfer_id)
        if transfer:
            transfer.bytes_transferred = bytes_transferred
            # filesize might differ from total_size if sender sends more/less than advertised
            # but for progress, use the initial filesize as total.
            transfer.current_rate_bps = rate_bps
            transfer.estimated_eta_seconds = eta_seconds

            self.event_manager.dispatch_event("DCC_TRANSFER_PROGRESS", {
                "transfer_id": transfer.transfer_id,
                "type": transfer.transfer_type.name,
                "bytes_transferred": bytes_transferred,
                "total_size": transfer.filesize, # Use original advertised filesize for consistency
                "rate_bps": rate_bps,
                "eta_seconds": eta_seconds
            })
            # UI update for progress is typically handled by the UI subscribing to DCC_TRANSFER_PROGRESS
            # No direct add_message here to avoid flooding, unless it's a very infrequent update.
        else:
            # This could also be verbose if it happens often for a short period after a transfer is removed.
            # logger.warning(f"update_transfer_progress called for unknown transfer_id: {transfer_id}")
            pass


    def get_transfer_statuses(self) -> List[str]:
        """Returns a list of formatted strings representing current transfer statuses."""
        status_lines = []
        with self._lock:
            # List active/completed/failed transfers
            if self.transfers:
                status_lines.append("--- Active/Recent Transfers ---")
                # Sort by start time or add time? For now, just iterate.
                # Consider sorting by a 'last_updated' timestamp if available on DCCTransfer objects.
                sorted_transfers = sorted(self.transfers.items(), key=lambda item: getattr(item[1], 'start_time', 0) or getattr(item[1], 'queue_time', 0), reverse=True)

                for tid, t in sorted_transfers:
                    progress_percent = (t.bytes_transferred / t.filesize * 100) if t.filesize > 0 else 0
                    size_str = f"{t.bytes_transferred / (1024*1024):.2f}MB / {t.filesize / (1024*1024):.2f}MB"
                    rate_str = f"{t.current_rate_bps / 1024:.1f} KB/s" if t.current_rate_bps is not None and t.current_rate_bps > 0 else ""
                    eta_str = f"ETA: {int(t.estimated_eta_seconds // 60)}m{int(t.estimated_eta_seconds % 60)}s" if t.estimated_eta_seconds is not None else ""

                    checksum_info = ""
                    if hasattr(t, 'checksum_status') and t.checksum_status and t.checksum_status not in ["Pending", "NotChecked", None]:
                        checksum_info = f" Checksum: {t.checksum_status}"
                        if hasattr(t, 'checksum_algorithm') and t.checksum_algorithm:
                            checksum_info += f" ({t.checksum_algorithm})"

                    line = (f"ID: {tid[:8]} [{t.transfer_type.name}] {t.peer_nick} - '{t.original_filename}' "
                            f"({size_str}, {progress_percent:.1f}%) Status: {t.status.name}{checksum_info} {rate_str} {eta_str}")
                    if t.error_message:
                        line += f" Error: {t.error_message}"
                    status_lines.append(line)

            # List pending passive offers
            if self.pending_passive_offers:
                status_lines.append("--- Pending Passive Offers (Incoming) ---")
                # Sort by timestamp, newest first
                sorted_passive_offers = sorted(self.pending_passive_offers.items(), key=lambda item: item[1].get("timestamp", 0), reverse=True)

                for token, offer_details in sorted_passive_offers:
                    nick = offer_details.get("nick", "Unknown")
                    filename = offer_details.get("filename", "UnknownFile")
                    filesize_bytes = offer_details.get("filesize", 0)
                    filesize_mb = filesize_bytes / (1024*1024)
                    timestamp = offer_details.get("timestamp", 0)
                    age_seconds = time.time() - timestamp

                    line = (f"Token: {token[:8]}... From: {nick}, File: '{filename}' ({filesize_mb:.2f}MB). "
                            f"Received: {age_seconds:.0f}s ago. "
                            f"Use: /dcc get {nick} \"{filename}\" --token {token}")
                    status_lines.append(line)

            if not status_lines: # If both lists were empty
                return ["No active DCC transfers or pending passive offers."]

            # The previously duplicated/commented out code from line 683 to 702 has been removed by this diff.
            # The loop for self.transfers is already handled correctly above.
            # The final return statement's indentation is also corrected.
        return status_lines # This line is now correctly indented.

    def cancel_transfer(self, transfer_id: str) -> bool:
        with self._lock:
            transfer = self.transfers.get(transfer_id)

        if transfer:
            self.dcc_event_logger.info(f"User requested cancellation of transfer {transfer_id} ('{transfer.original_filename}') to/from {transfer.peer_nick}.")
            transfer.stop_transfer(DCCTransferStatus.CANCELLED, "User cancelled.")
            # The stop_transfer method itself calls _report_status, which dispatches event
            return True
        self.dcc_event_logger.warning(f"Cannot cancel: Transfer ID {transfer_id} not found in active transfers.")
        return False

    def cancel_pending_passive_offer(self, token_prefix: str) -> bool:
        """Cancels a pending passive DCC SEND offer based on a token or its prefix."""
        if not token_prefix:
            return False

        cancelled_offer_details: Optional[Dict[str, Any]] = None
        actual_token_cancelled: Optional[str] = None

        with self._lock:
            # Iterate to find a match by prefix
            for token, offer_details in list(self.pending_passive_offers.items()): # list() for safe iteration while modifying
                if token.startswith(token_prefix):
                    actual_token_cancelled = token
                    cancelled_offer_details = self.pending_passive_offers.pop(token)
                    break # Cancel only the first match

        if cancelled_offer_details and actual_token_cancelled:
            peer_nick = cancelled_offer_details.get('nick', 'UnknownNick')
            filename = cancelled_offer_details.get('filename', 'UnknownFile')
            self.dcc_event_logger.info(f"Cancelled pending passive DCC SEND offer from {peer_nick} for '{filename}' with token {actual_token_cancelled} (matched by prefix '{token_prefix}').")
            self.client_logic.add_message(
                f"Cancelled pending passive DCC SEND offer from {peer_nick} for '{filename}' (token: {actual_token_cancelled[:8]}...).",
                "system", context_name="DCC"
            )
            return True
        else:
            # No message here, as the command handler will try active transfers first
            # and then report if neither was found.
            self.dcc_event_logger.debug(f"No pending passive offer found starting with token prefix '{token_prefix}'.")
            return False

    def cleanup_old_transfers(self):
        # Placeholder for future: remove very old completed/failed transfers
        pass

    def send_dcc_checksum_info(self, transfer_id: str, peer_nick: str, filename: str, algorithm: str, checksum: str):
        """Called by DCCSendTransfer to send checksum info to the peer."""
        if not self.dcc_config.get("checksum_verify", False) or self.dcc_config.get("checksum_algorithm", "none") == "none":
            return # Checksums not enabled

        self.dcc_event_logger.info(f"Sending DCCCHECKSUM for transfer {transfer_id}, file '{filename}', algo {algorithm}, checksum '{checksum[:10]}...' to {peer_nick}")

        # Using transfer_id as the identifier for the peer to match
        ctcp_checksum_msg = format_dcc_checksum_ctcp(filename, algorithm, checksum, transfer_id)

        if ctcp_checksum_msg:
            self.client_logic.send_ctcp_privmsg(peer_nick, ctcp_checksum_msg)
            self.client_logic.add_message(f"Sent checksum ({algorithm}) for '{filename}' to {peer_nick}.", "debug", context_name="DCC")
        else:
            self.dcc_event_logger.error(f"Failed to format DCCCHECKSUM message for transfer {transfer_id}.")

    def update_transfer_checksum_result(self, transfer_id: str, checksum_status: str):
        """Called by DCCTransfer when checksum comparison is done."""
        with self._lock:
            transfer = self.transfers.get(transfer_id)

        if transfer:
            self.dcc_event_logger.info(f"Checksum status for transfer {transfer_id} ('{transfer.original_filename}'): {checksum_status}. Expected: '{transfer.expected_checksum}', Calculated: '{transfer.calculated_checksum}' (Algo: {transfer.checksum_algorithm})")
            transfer.checksum_status = checksum_status # Ensure it's updated on the object if not already

            # Notify UI
            ui_message = f"DCC: Checksum for '{transfer.original_filename}' with {transfer.peer_nick}: {checksum_status}."
            color_key = "system"
            if checksum_status == "Mismatch":
                color_key = "error"
            elif checksum_status == "Match":
                color_key = "info" # Or a success color

            self.client_logic.add_message(ui_message, color_key, context_name="DCC")

            # Dispatch event
            self.event_manager.dispatch_event("DCC_TRANSFER_CHECKSUM_VALIDATED", {
                "transfer_id": transfer_id,
                "type": transfer.transfer_type.name,
                "nick": transfer.peer_nick,
                "filename": transfer.original_filename,
                "checksum_status": checksum_status,
                "expected_checksum": transfer.expected_checksum,
                "calculated_checksum": transfer.calculated_checksum,
                "algorithm_used": transfer.checksum_algorithm
            })
        else:
            self.dcc_event_logger.warning(f"update_transfer_checksum_result called for unknown transfer_id: {transfer_id}")

    def attempt_user_resume(self, identifier: str) -> Dict[str, Any]:
        """
        Attempts to resume a previously failed/cancelled outgoing DCC SEND transfer
        based on a user-provided identifier (transfer ID prefix or filename).
        """
        if not self.dcc_config.get("enabled"):
            return {"success": False, "error": "DCC is disabled."}
        if not self.dcc_config.get("resume_enabled"):
            return {"success": False, "error": "DCC resume is disabled in configuration."}

        self.dcc_event_logger.info(f"User attempt to resume transfer with identifier: '{identifier}'")

        resumable_transfer: Optional[DCCSendTransfer] = None

        with self._lock:
            # Try to find by transfer ID prefix first
            possible_matches_by_id = []
            for tid, transfer in self.transfers.items():
                if tid.startswith(identifier) and isinstance(transfer, DCCSendTransfer):
                    possible_matches_by_id.append(transfer)

            if len(possible_matches_by_id) == 1:
                resumable_transfer = possible_matches_by_id[0]
            elif len(possible_matches_by_id) > 1:
                self.dcc_event_logger.warning(f"Ambiguous identifier '{identifier}' for resume (multiple ID prefix matches).")
                return {"success": False, "error": f"Ambiguous transfer ID prefix '{identifier}'. Be more specific."}

            # If not found by ID prefix, try by filename (case-insensitive)
            if not resumable_transfer:
                possible_matches_by_filename = []
                for transfer in self.transfers.values():
                    if (isinstance(transfer, DCCSendTransfer) and
                        transfer.original_filename.lower() == identifier.lower()):
                        possible_matches_by_filename.append(transfer)

                if len(possible_matches_by_filename) == 1:
                    resumable_transfer = possible_matches_by_filename[0]
                elif len(possible_matches_by_filename) > 1:
                    self.dcc_event_logger.warning(f"Ambiguous identifier '{identifier}' for resume (multiple filename matches).")
                    # Consider listing them or asking for peer_nick if implementing more complex resume UI
                    return {"success": False, "error": f"Ambiguous filename '{identifier}'. Multiple transfers match. Try ID prefix."}

        if not resumable_transfer:
            self.dcc_event_logger.warning(f"No resumable SEND transfer found matching identifier '{identifier}'.")
            return {"success": False, "error": f"No SEND transfer found matching '{identifier}'."}

        # Check if the found transfer is in a state that allows resuming
        if resumable_transfer.status not in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]:
            self.dcc_event_logger.info(f"Transfer '{resumable_transfer.transfer_id}' ('{resumable_transfer.original_filename}') is not in a resumable state (current state: {resumable_transfer.status.name}).")
            return {"success": False, "error": f"Transfer '{resumable_transfer.original_filename}' is not in a failed/cancelled state ({resumable_transfer.status.name})."}

        if not (resumable_transfer.bytes_transferred > 0 and resumable_transfer.bytes_transferred < resumable_transfer.filesize):
            self.dcc_event_logger.info(f"Transfer '{resumable_transfer.transfer_id}' ('{resumable_transfer.original_filename}') has no partial progress ({resumable_transfer.bytes_transferred}/{resumable_transfer.filesize}). Cannot resume.")
            return {"success": False, "error": f"Transfer '{resumable_transfer.original_filename}' has no partial progress to resume from."}

        # At this point, we have a valid, resumable DCCSendTransfer.
        # Call _execute_send, which contains the logic to offer DCC RESUME CTCP.
        self.dcc_event_logger.info(f"Re-initiating send for '{resumable_transfer.original_filename}' to {resumable_transfer.peer_nick} (will offer resume from {resumable_transfer.bytes_transferred}).")

        # Note: _execute_send will create a *new* transfer object internally for the resume attempt.
        # The old 'resumable_transfer' object will remain in self.transfers unless explicitly removed by _execute_send's resume logic.
        # The current _execute_send logic for resume does not remove the old transfer object explicitly.
        # This means `self.transfers` might accumulate multiple attempts for the same logical file if resume is tried multiple times.
        # This might be desired for history, or might need cleanup later.

        return self._execute_send(
            peer_nick=resumable_transfer.peer_nick,
            local_filepath=resumable_transfer.local_filepath,
            original_filename=resumable_transfer.original_filename,
            filesize=resumable_transfer.filesize,
            passive=False # User-initiated resume is for active sends for now
        )
