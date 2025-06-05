import logging
import وقت
import os
import socket
import threading
import uuid # For unique transfer IDs
from typing import Dict, Optional, Any, List, Tuple

# Assuming these will be accessible via client_logic.config or similar
# from config import (
#     DCC_ENABLED, DCC_DOWNLOAD_DIR, DCC_UPLOAD_DIR, DCC_AUTO_ACCEPT,
#     DCC_MAX_FILE_SIZE, DCC_PORT_RANGE_START, DCC_PORT_RANGE_END, DCC_TIMEOUT,
#     DCC_BLOCKED_EXTENSIONS
# )
import app_config # Use this to access config values

from dcc_transfer import DCCTransfer, DCCSendTransfer, DCCReceiveTransfer, DCCTransferStatus, DCCTransferType
from dcc_protocol import parse_dcc_ctcp, format_dcc_send_ctcp
from dcc_security import validate_download_path, sanitize_filename

logger = logging.getLogger("pyrc.dcc.manager")

class DCCManager:
    def __init__(self, client_logic_ref: Any, event_manager_ref: Any):
        self.client_logic = client_logic_ref
        self.event_manager = event_manager_ref
        self.transfers: Dict[str, DCCTransfer] = {}
        self.dcc_config = self._load_dcc_config()
        self._lock = threading.Lock() # To protect access to self.transfers

        if not self.dcc_config.get("enabled", False):
            logger.info("DCCManager initialized, but DCC is disabled in configuration.")
        else:
            logger.info("DCCManager initialized and DCC is enabled.")
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
        }

    def _ensure_dir_exists(self, dir_path: str):
        abs_dir_path = os.path.abspath(dir_path)
        if not os.path.exists(abs_dir_path):
            try:
                os.makedirs(abs_dir_path, exist_ok=True)
                logger.info(f"Created directory: {abs_dir_path}")
            except OSError as e:
                logger.error(f"Could not create directory '{abs_dir_path}': {e}")
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
            logger.info(f"Created listening socket on port {port}")
            return s, port
        except socket.error as e:
            logger.error(f"Could not create listening socket: {e}")
            return None

    def initiate_send(self, peer_nick: str, local_filepath: str) -> Dict[str, Any]:
        """Initiates a DCC SEND (Active DCC for Phase 1)."""
        if not self.dcc_config.get("enabled"):
            return {"success": False, "error": "DCC is disabled."}

        abs_local_filepath = os.path.abspath(local_filepath)
        if not os.path.isfile(abs_local_filepath):
            return {"success": False, "error": f"File not found: {local_filepath}"}

        try:
            filesize = os.path.getsize(abs_local_filepath)
        except OSError as e:
            return {"success": False, "error": f"Could not get file size for '{local_filepath}': {e}"}

        if filesize > self.dcc_config["max_file_size"]:
            return {"success": False, "error": f"File exceeds maximum size of {self.dcc_config['max_file_size']} bytes."}

        # For SEND, dcc_security.sanitize_filename isn't applied to local_filepath,
        # but the original filename sent in CTCP should be just the basename.
        original_filename = os.path.basename(local_filepath)

        socket_info = self._get_listening_socket()
        if not socket_info:
            return {"success": False, "error": "Could not create listening socket for DCC SEND."}

        listening_socket, port = socket_info

        # Get local IP to send in CTCP. This can be tricky.
        # For Phase 1, try to get an IP that's likely reachable.
        # A more robust solution would involve STUN or config.
        try:
            # This gets the IP used for default route, might not always be correct for NAT.
            temp_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            temp_s.connect(("8.8.8.8", 80)) # Connect to a known external address (doesn't send data)
            local_ip_for_ctcp = temp_s.getsockname()[0]
            temp_s.close()
        except socket.error:
            logger.warning("Could not determine local IP for DCC SEND CTCP. Using '127.0.0.1'. This might fail over network.")
            local_ip_for_ctcp = "127.0.0.1" # Fallback, likely only works locally

        ctcp_message = format_dcc_send_ctcp(original_filename, local_ip_for_ctcp, port, filesize)
        if not ctcp_message:
            listening_socket.close()
            return {"success": False, "error": "Failed to format DCC SEND CTCP message."}

        transfer_id = self._generate_transfer_id()
        send_transfer = DCCSendTransfer(
            transfer_id=transfer_id,
            peer_nick=peer_nick,
            filename=original_filename, # Filename as sent in CTCP
            filesize=filesize,
            local_filepath=abs_local_filepath, # Full path for reading
            dcc_manager_ref=self,
            server_socket_for_active_send=listening_socket # Pass the listening socket
        )

        with self._lock:
            self.transfers[transfer_id] = send_transfer

        # Inform client logic to send the CTCP message
        self.client_logic.send_ctcp_privmsg(peer_nick, ctcp_message) # Assumes send_ctcp_privmsg exists

        send_transfer._report_status(DCCTransferStatus.NEGOTIATING, "Waiting for peer to connect.")
        # The transfer thread will be started once the peer connects (handled by DCCSendTransfer.run)
        # For Phase 1, DCCSendTransfer.run() will do the accept() call.
        send_transfer.start_transfer_thread() # This thread will now block on accept()

        self.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", { # Or NEGOTIATING
            "transfer_id": transfer_id, "type": "SEND", "nick": peer_nick,
            "filename": original_filename, "size": filesize
        })
        self.client_logic.add_message(f"DCC SEND to {peer_nick} for '{original_filename}' ({filesize} bytes) initiated. Waiting for connection on port {port}.", "system", context_name="DCC")
        return {"success": True, "transfer_id": transfer_id}

    def handle_incoming_dcc_ctcp(self, nick: str, userhost: str, ctcp_payload: str):
        """Handles a parsed DCC CTCP command from a peer."""
        if not self.dcc_config.get("enabled"):
            logger.info(f"DCC disabled, ignoring incoming DCC CTCP from {nick}: {ctcp_payload}")
            return

        parsed_dcc = parse_dcc_ctcp(ctcp_payload)
        if not parsed_dcc:
            logger.warning(f"Could not parse DCC CTCP from {nick}: {ctcp_payload}")
            self.client_logic.add_message(f"Received malformed DCC request from {nick}.", "error", context_name="Status")
            return

        dcc_command = parsed_dcc.get("dcc_command")
        logger.info(f"Received DCC Command '{dcc_command}' from {nick} with data: {parsed_dcc}")

        if dcc_command == "SEND":
            # This is an offer to receive a file
            filename = parsed_dcc["filename"]
            ip_str = parsed_dcc["ip_str"]
            port = parsed_dcc["port"]
            filesize = parsed_dcc["filesize"]

            self.event_manager.dispatch_event("DCC_SEND_OFFER_INCOMING", {
                "nick": nick, "userhost": userhost, "filename": filename, "size": filesize,
                "ip": ip_str, "port": port
            })

            # Phase 1: Manual accept via /dcc accept command.
            # For now, just notify user. DCCManager won't auto-start receive yet.
            self.client_logic.add_message(
                f"DCC SEND offer from {nick} ({userhost}): '{filename}' ({filesize} bytes) from {ip_str}:{port}. "
                f"Use /dcc accept {nick} \"{filename}\" {ip_str} {port} {filesize} to receive.",
                "system", context_name="DCC"
            )
            # If auto_accept is on and conditions met, could proceed here.

        elif dcc_command == "ACCEPT":
            # This is a response to our DCC SEND, indicating peer is ready to receive at their port
            # Or an acceptance of a file we offered to send via passive DCC (Phase 2)
            # For Phase 1 Active SEND, we don't expect an ACCEPT back this way.
            # The connection to our listening socket is the "acceptance".
            logger.info(f"Received DCC ACCEPT from {nick} for '{parsed_dcc.get('filename')}'. This is typically for passive DCC or resume.")
            # Potentially find matching SEND transfer and update its status if it was passive.

        else:
            self.client_logic.add_message(f"Received unhandled DCC '{dcc_command}' from {nick}: {' '.join(parsed_dcc.get('args',[]))}", "system", context_name="Status")


    def accept_incoming_send_offer(self, peer_nick: str, original_filename: str, ip_str: str, port: int, filesize: int) -> Dict[str, Any]:
        """
        Called by command handler when user accepts a DCC SEND offer.
        Initiates a DCCReceiveTransfer (Active DCC RECV for Phase 1).
        """
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
            connect_to_port=port
        )

        with self._lock:
            self.transfers[transfer_id] = recv_transfer

        recv_transfer._report_status(DCCTransferStatus.QUEUED) # Or CONNECTING if thread starts immediately
        recv_transfer.start_transfer_thread()

        self.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", {
            "transfer_id": transfer_id, "type": "RECEIVE", "nick": peer_nick,
            "filename": original_filename, "size": filesize
        })
        self.client_logic.add_message(f"DCC RECV for '{original_filename}' from {peer_nick} accepted. Connecting to {ip_str}:{port}. Saving to '{sanitized_filename_for_log}'.", "system", context_name="DCC")
        return {"success": True, "transfer_id": transfer_id}


    def update_transfer_status(self, transfer_id: str, status: DCCTransferStatus, error_message: Optional[str]):
        with self._lock:
            transfer = self.transfers.get(transfer_id)
        if transfer:
            old_status = transfer.status
            transfer.status = status
            transfer.error_message = error_message
            logger.info(f"Transfer {transfer_id} status updated: {old_status.name} -> {status.name}. Error: {error_message}")

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
                logger.info(f"Transfer {transfer_id} reached final state: {status.name}. It will remain in list for now.")
                # Consider removing from self.transfers after a delay or if list gets too long.

            self.client_logic.add_message(
                f"DCC {transfer.transfer_type.name} {transfer.original_filename} with {transfer.peer_nick}: {status.name}"
                f"{f' ({error_message})' if error_message else ''}",
                "error" if status in [DCCTransferStatus.FAILED, DCCTransferStatus.TIMED_OUT] else "system",
                context_name="DCC"
            )
        else:
            logger.warning(f"update_transfer_status called for unknown transfer_id: {transfer_id}")

    def update_transfer_progress(self, transfer_id: str, bytes_transferred: int, total_size: int, rate_bps: float, eta_seconds: Optional[float]):
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
            logger.warning(f"update_transfer_progress called for unknown transfer_id: {transfer_id}")

    def get_transfer_statuses(self) -> List[str]:
        """Returns a list of formatted strings representing current transfer statuses."""
        status_lines = []
        with self._lock:
            if not self.transfers:
                return ["No active or queued DCC transfers."]

            # Sort by start time or add time? For now, just iterate.
            for tid, t in self.transfers.items():
                progress_percent = (t.bytes_transferred / t.filesize * 100) if t.filesize > 0 else 0
                size_str = f"{t.bytes_transferred / (1024*1024):.2f}MB / {t.filesize / (1024*1024):.2f}MB"
                rate_str = f"{t.current_rate_bps / 1024:.1f} KB/s" if t.current_rate_bps > 0 else ""
                eta_str = f"ETA: {int(t.estimated_eta_seconds // 60)}m{int(t.estimated_eta_seconds % 60)}s" if t.estimated_eta_seconds is not None else ""

                line = (f"ID: {tid[:8]} [{t.transfer_type.name}] {t.peer_nick} - '{t.original_filename}' "
                        f"({size_str}, {progress_percent:.1f}%) Status: {t.status.name} {rate_str} {eta_str}")
                if t.error_message:
                    line += f" Error: {t.error_message}"
                status_lines.append(line)
        return status_lines

    def cancel_transfer(self, transfer_id: str) -> bool:
        with self._lock:
            transfer = self.transfers.get(transfer_id)

        if transfer:
            logger.info(f"Attempting to cancel transfer {transfer_id}")
            transfer.stop_transfer(DCCTransferStatus.CANCELLED, "User cancelled.")
            # The stop_transfer method itself calls _report_status, which dispatches event
            return True
        logger.warning(f"Cannot cancel: Transfer ID {transfer_id} not found.")
        return False

    def cleanup_old_transfers(self):
        # Placeholder for future: remove very old completed/failed transfers
        pass
