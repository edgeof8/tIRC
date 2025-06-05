import logging
import time
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
import config as app_config # Use this to access config values

from dcc_transfer import DCCTransfer, DCCSendTransfer, DCCReceiveTransfer, DCCTransferStatus, DCCTransferType
from dcc_protocol import parse_dcc_ctcp, format_dcc_send_ctcp, format_dcc_accept_ctcp, format_dcc_checksum_ctcp
from dcc_security import validate_download_path, sanitize_filename

logger = logging.getLogger("pyrc.dcc.manager")

class DCCManager:
    def __init__(self, client_logic_ref: Any, event_manager_ref: Any):
        self.client_logic = client_logic_ref
        self.event_manager = event_manager_ref
        self.transfers: Dict[str, DCCTransfer] = {}
        self.pending_passive_offers: Dict[str, Dict[str, Any]] = {} # Key: token
        self.dcc_config = self._load_dcc_config()
        self._lock = threading.Lock() # To protect access to self.transfers, and pending_passive_offers

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
            "passive_mode_token_timeout": getattr(app_config, "DCC_PASSIVE_MODE_TOKEN_TIMEOUT", 120),
            "checksum_verify": getattr(app_config, "DCC_CHECKSUM_VERIFY", True),
            "checksum_algorithm": getattr(app_config, "DCC_CHECKSUM_ALGORITHM", "md5").lower(),
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
                logger.info(f"Removed stale passive DCC offer with token {token} due to timeout.")

        if stale_tokens:
            self.client_logic.add_message(f"Cleaned up {len(stale_tokens)} stale passive DCC offer(s).", "debug", context_name="DCC")


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

    def initiate_send(self, peer_nick: str, local_filepath: str, passive: bool = False) -> Dict[str, Any]:
        """Initiates a DCC SEND. Active by default, or passive if specified."""
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

        original_filename = os.path.basename(local_filepath)
        transfer_id = self._generate_transfer_id()
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
                return {"success": False, "error": "Failed to format passive DCC SEND CTCP message."}
        else: # Active DCC
            socket_info = self._get_listening_socket()
            if not socket_info:
                return {"success": False, "error": "Could not create listening socket for active DCC SEND."}
            listening_socket, port = socket_info
            local_ip_for_ctcp = self._get_local_ip_for_ctcp()
            ctcp_message = format_dcc_send_ctcp(original_filename, local_ip_for_ctcp, port, filesize)
            send_transfer_args["server_socket_for_active_send"] = listening_socket
            status_message_suffix = f". Waiting for connection on port {port}."
            if not ctcp_message:
                listening_socket.close()
                return {"success": False, "error": "Failed to format active DCC SEND CTCP message."}

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
        return {"success": True, "transfer_id": transfer_id, "token": passive_token if passive else None}

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
            filename = parsed_dcc.get("filename")
            ip_str = parsed_dcc.get("ip_str")
            port = parsed_dcc.get("port")
            filesize = parsed_dcc.get("filesize")
            is_passive_offer = parsed_dcc.get("is_passive_offer", False)
            token = parsed_dcc.get("token")

            if None in [filename, ip_str, port, filesize]:
                logger.warning(f"DCC SEND from {nick} missing critical information: {parsed_dcc}")
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
                    logger.info(f"Stored pending passive DCC SEND offer from {nick} for '{filename}' with token {token}.")
                    self._cleanup_stale_passive_offers() # Opportunistic cleanup
                    self.client_logic.add_message(
                        f"Passive DCC SEND offer from {nick} ({userhost}): '{filename}' ({filesize} bytes). "
                        f"Use /dcc get {nick} \"{filename}\" --token {token} to receive.",
                        "system", context_name="DCC"
                    )
                else:
                    logger.warning(f"Passive DCC SEND offer from {nick} for '{filename}' missing token. Ignoring.")
                    self.client_logic.add_message(f"Malformed passive DCC SEND offer from {nick} (missing token).", "error", context_name="Status")
            else: # Active offer
                self.client_logic.add_message(
                    f"DCC SEND offer from {nick} ({userhost}): '{filename}' ({filesize} bytes) from {ip_str}:{port}. "
                    f"Use /dcc accept {nick} \"{filename}\" {ip_str} {port} {filesize} to receive.",
                    "system", context_name="DCC"
                )
            # TODO: Add auto_accept logic here if configured

        elif dcc_command == "ACCEPT":
            is_passive_dcc_accept = parsed_dcc.get("is_passive_accept", False)
            is_resume_accept = parsed_dcc.get("is_resume_accept", False)
            filename = parsed_dcc.get("filename")

            if is_passive_dcc_accept:
                accepted_ip = parsed_dcc.get("ip_str")
                accepted_port = parsed_dcc.get("port")
                accepted_token = parsed_dcc.get("token")
                logger.info(f"Received Passive DCC ACCEPT from {nick} for '{filename}' (IP: {accepted_ip}, Port: {accepted_port}, Token: {accepted_token})")

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
                    logger.info(f"Matching passive SEND offer found (ID: {found_transfer.transfer_id}). Initiating connection to {nick} at {accepted_ip}:{accepted_port}")
                    found_transfer.connect_to_ip = accepted_ip # Store for DCCSendTransfer.run()
                    found_transfer.connect_to_port = accepted_port
                    found_transfer._report_status(DCCTransferStatus.CONNECTING, f"Peer accepted passive offer. Connecting to {accepted_ip}:{accepted_port}.")
                    found_transfer.start_transfer_thread() # Now the sender connects
                else:
                    logger.warning(f"Received Passive DCC ACCEPT from {nick} for '{filename}' with token '{accepted_token}', but no matching passive offer found.")
                    self.client_logic.add_message(f"Received unexpected Passive DCC ACCEPT from {nick} for '{filename}'.", "warning", context_name="Status")

            elif is_resume_accept:
                # Handle DCC RESUME ACCEPT logic (Phase 4)
                accepted_port = parsed_dcc.get("port")
                accepted_position = parsed_dcc.get("position")
                logger.info(f"Received Resume DCC ACCEPT from {nick} for '{filename}' (Port: {accepted_port}, Position: {accepted_position}). Resume not fully implemented yet.")
                # Find original transfer, set resume position, and restart.
            else:
                logger.warning(f"Received ambiguous DCC ACCEPT from {nick}: {parsed_dcc}")

        elif dcc_command == "DCCCHECKSUM":
            # Parsed by dcc_protocol.py: {'dcc_command': 'DCCCHECKSUM', 'filename': ...,
            # 'algorithm': ..., 'checksum_value': ..., 'transfer_identifier': ...}

            transfer_identifier = parsed_dcc.get("transfer_identifier")
            filename = parsed_dcc.get("filename")
            algorithm = parsed_dcc.get("algorithm")
            checksum_value = parsed_dcc.get("checksum_value")

            if not all([transfer_identifier, filename, algorithm, checksum_value]):
                logger.warning(f"Malformed DCCCHECKSUM from {nick}: {parsed_dcc}")
                return

            logger.info(f"Received DCCCHECKSUM from {nick} for transfer '{transfer_identifier}', file '{filename}', algo '{algorithm}'.")

            transfer_to_update = None
            with self._lock:
                # Try to find by transfer_id first
                if transfer_identifier in self.transfers:
                    potential_transfer = self.transfers[transfer_identifier]
                    if isinstance(potential_transfer, DCCReceiveTransfer) and potential_transfer.peer_nick == nick and potential_transfer.original_filename == filename:
                        transfer_to_update = potential_transfer

                # Fallback: If not found by ID, maybe by filename and nick (less reliable if multiple transfers of same file)
                if not transfer_to_update:
                    for tid, tr_obj in self.transfers.items():
                        if isinstance(tr_obj, DCCReceiveTransfer) and tr_obj.peer_nick == nick and tr_obj.original_filename == filename and tr_obj.status == DCCTransferStatus.COMPLETED:
                            # Only apply to completed transfers if ID didn't match, to avoid ambiguity
                            transfer_to_update = tr_obj
                            logger.info(f"DCCCHECKSUM matched by filename/nick for completed transfer {tid}")
                            break

            if transfer_to_update:
                if hasattr(transfer_to_update, 'set_expected_checksum'):
                    transfer_to_update.set_expected_checksum(algorithm, checksum_value)
                else:
                    logger.error(f"Transfer object {transfer_to_update.transfer_id} does not have set_expected_checksum method.")
            else:
                logger.warning(f"Received DCCCHECKSUM from {nick} for '{filename}' (ID/Ref: {transfer_identifier}), but no matching active/completed RECV transfer found.")

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

    def initiate_passive_receive(self, peer_nick: str, offered_filename: str, offered_filesize: int, offer_token: str) -> Dict[str, Any]:
        """
        Called when the local user wants to accept a PASSIVE DCC SEND offer they received.
        This client will listen, and send an ACCEPT CTCP to the peer, who will then connect.
        """
        if not self.dcc_config.get("enabled"):
            return {"success": False, "error": "DCC is disabled."}

        logger.info(f"Attempting to initiate passive receive for '{offered_filename}' from {peer_nick} (token: {offer_token}).")

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
            return {"success": False, "error": "Failed to format passive DCC ACCEPT CTCP message."}

        transfer_id = self._generate_transfer_id()
        # Ensure DCCReceiveTransfer can handle server_socket_for_passive_recv
        recv_transfer_args = {
            "transfer_id":transfer_id,
            "peer_nick":peer_nick,
            "filename":offered_filename,
            "filesize":offered_filesize,
            "local_filepath":safe_local_path,
            "dcc_manager_ref":self,
            "server_socket_for_passive_recv":listening_socket
        }
        recv_transfer = DCCReceiveTransfer(**recv_transfer_args)

        with self._lock:
            self.transfers[transfer_id] = recv_transfer

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
        logger.info(f"User {calling_nick_for_logging} attempting to accept passive offer with token: {offer_token} for filename: {offered_filename_by_user}")
        pending_offer_details = None
        with self._lock:
            pending_offer_details = self.pending_passive_offers.get(offer_token)

        if not pending_offer_details:
            return {"success": False, "error": f"Passive offer with token '{offer_token}' not found or expired."}

        # Verify details (optional, but good for sanity)
        # The filename from user command might differ slightly (e.g. no quotes) from stored one.
        # For now, primary match is by token.
        original_sender_nick = pending_offer_details["nick"]
        original_offered_filename = pending_offer_details["filename"]
        original_filesize = pending_offer_details["filesize"]

        if offered_filename_by_user.lower() != original_offered_filename.lower():
             logger.warning(f"Filename mismatch for passive offer token {offer_token}. User: '{offered_filename_by_user}', Offer: '{original_offered_filename}'. Proceeding by token match.")

        # Remove the pending offer once we attempt to process it
        with self._lock:
            if offer_token in self.pending_passive_offers:
                del self.pending_passive_offers[offer_token]
                logger.info(f"Removed pending passive offer token {offer_token} after acceptance attempt.")

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

    def send_dcc_checksum_info(self, transfer_id: str, peer_nick: str, filename: str, algorithm: str, checksum: str):
        """Called by DCCSendTransfer to send checksum info to the peer."""
        if not self.dcc_config.get("checksum_verify", False) or self.dcc_config.get("checksum_algorithm", "none") == "none":
            return # Checksums not enabled

        logger.info(f"Sending DCCCHECKSUM for transfer {transfer_id}, file '{filename}', algo {algorithm} to {peer_nick}")

        # Using transfer_id as the identifier for the peer to match
        ctcp_checksum_msg = format_dcc_checksum_ctcp(filename, algorithm, checksum, transfer_id)

        if ctcp_checksum_msg:
            self.client_logic.send_ctcp_privmsg(peer_nick, ctcp_checksum_msg)
            self.client_logic.add_message(f"Sent checksum ({algorithm}) for '{filename}' to {peer_nick}.", "debug", context_name="DCC")
        else:
            logger.error(f"Failed to format DCCCHECKSUM message for transfer {transfer_id}.")

    def update_transfer_checksum_result(self, transfer_id: str, checksum_status: str):
        """Called by DCCTransfer when checksum comparison is done."""
        with self._lock:
            transfer = self.transfers.get(transfer_id)

        if transfer:
            logger.info(f"Checksum status for transfer {transfer_id} ('{transfer.original_filename}'): {checksum_status}")
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
            logger.warning(f"update_transfer_checksum_result called for unknown transfer_id: {transfer_id}")
