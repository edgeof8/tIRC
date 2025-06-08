import logging
import os
import socket
import threading
from typing import Dict, Optional, Any, List, Tuple, TYPE_CHECKING

from pyrc_core.dcc.dcc_transfer import DCCReceiveTransfer, DCCTransferStatus, DCCTransferType
from pyrc_core.dcc.dcc_protocol import format_dcc_accept_ctcp
from pyrc_core.dcc.dcc_security import validate_download_path, sanitize_filename
from pyrc_core.dcc.dcc_utils import get_listening_socket, get_local_ip_for_ctcp # Import utility functions

if TYPE_CHECKING:
    from pyrc_core.dcc.dcc_manager import DCCManager # To avoid circular import for type hinting

logger = logging.getLogger("pyrc.dcc.receivemanager") # Specific logger for this manager

class DCCReceiveManager:
    def __init__(self, manager_ref: 'DCCManager'):
        self.manager = manager_ref
        self.dcc_config = manager_ref.dcc_config # Use manager's config
        self.dcc_event_logger = manager_ref.dcc_event_logger # Use manager's event logger
        self._lock = manager_ref._lock # Use the manager's lock for consistency
        self.client_logic = manager_ref.client_logic
        self.event_manager = manager_ref.event_manager

    def accept_incoming_send_offer(self, peer_nick: str, original_filename: str, ip_str: str, port: int, filesize: int) -> Dict[str, Any]:
        """
        Called by command handler or auto-accept when user accepts a DCC SEND offer.
        Initiates a DCCReceiveTransfer (Active DCC RECV for Phase 1).
        """
        self.dcc_event_logger.info(f"ReceiveManager: Attempting to accept ACTIVE DCC SEND offer from {peer_nick} for '{original_filename}' ({ip_str}:{port}, {filesize} bytes).")
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

        transfer_id = self.manager._generate_transfer_id() # Use manager's ID generator
        recv_transfer = DCCReceiveTransfer(
            transfer_id=transfer_id,
            peer_nick=peer_nick,
            filename=original_filename, # Original filename for display/logging
            filesize=filesize,
            local_filepath=safe_local_path, # Where to save the file
            dcc_manager_ref=self.manager, # Reference back to the main manager
            connect_to_ip=ip_str, # For active DCC RECV, we connect
            connect_to_port=port,
            peer_ip=ip_str, # Store sender's IP
            dcc_event_logger=self.dcc_event_logger # Pass the logger
        )

        with self._lock:
            self.manager.transfers[transfer_id] = recv_transfer
            self.dcc_event_logger.debug(f"Created DCCReceiveTransfer (active) with ID {transfer_id} for '{original_filename}' from {peer_nick}.")

        recv_transfer._report_status(DCCTransferStatus.QUEUED) # Or CONNECTING if thread starts immediately
        recv_transfer.start_transfer_thread()

        self.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", {
            "transfer_id": transfer_id, "type": "RECEIVE", "nick": peer_nick,
            "filename": original_filename, "size": filesize
        })
        self.client_logic.add_message(f"DCC RECV for '{original_filename}' from {peer_nick} accepted. Connecting to {ip_str}:{port}. Saving to '{sanitized_filename_for_log}'.", "system", context_name="DCC")
        return {"success": True, "transfer_id": transfer_id}

    def initiate_passive_receive(self, peer_nick: str, offered_filename: str, offered_filesize: int, offer_token: str, peer_ip_str_from_offer: Optional[str]) -> Dict[str, Any]:
        """
        Called when the local user wants to accept a PASSIVE DCC SEND offer they received.
        This client will listen, and send an ACCEPT CTCP to the peer, who will then connect.
        `peer_ip_str_from_offer` is retrieved from the stored passive offer.
        """
        self.dcc_event_logger.info(f"ReceiveManager: Attempting to initiate PASSIVE DCC RECV for '{offered_filename}' from {peer_nick} (token: {offer_token}, size: {offered_filesize}, peer_ip: {peer_ip_str_from_offer}).")
        if not self.dcc_config.get("enabled"):
            return {"success": False, "error": "DCC is disabled."}

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

        socket_info = get_listening_socket(self.dcc_config, self.dcc_event_logger) # Use utility function
        if not socket_info:
            self.client_logic.add_message(f"Error: No available DCC ports in range {self.dcc_config.get('port_range_start', 1024)}-{self.dcc_config.get('port_range_end', 65535)}.", "error", context_name="DCC")
            return {"success": False, "error": "Could not create listening socket for passive DCC RECV."}

        listening_socket, local_listening_port = socket_info
        local_ip_for_ctcp = get_local_ip_for_ctcp(self.dcc_config, self.dcc_event_logger) # Use utility function

        ctcp_accept_message = format_dcc_accept_ctcp(
            filename=offered_filename,
            ip_str=local_ip_for_ctcp,
            port=local_listening_port,
            position=0,
            token=offer_token
        )

        if not ctcp_accept_message:
            listening_socket.close()
            self.dcc_event_logger.error(f"Failed to format passive DCC ACCEPT CTCP for '{offered_filename}' to {peer_nick}.")
            return {"success": False, "error": "Failed to format passive DCC ACCEPT CTCP message."}
        self.dcc_event_logger.debug(f"Passive RECV for '{offered_filename}' from {peer_nick}. Sent ACCEPT CTCP: {ctcp_accept_message.strip()}")

        transfer_id = self.manager._generate_transfer_id() # Use manager's ID generator
        recv_transfer_args = {
            "transfer_id":transfer_id,
            "peer_nick":peer_nick,
            "filename":offered_filename,
            "filesize":offered_filesize,
            "local_filepath":safe_local_path,
            "dcc_manager_ref":self.manager, # Reference back to the main manager
            "server_socket_for_passive_recv":listening_socket,
            "peer_ip": peer_ip_str_from_offer, # Use the IP from the stored offer
            "dcc_event_logger": self.dcc_event_logger
        }

        recv_transfer = DCCReceiveTransfer(**recv_transfer_args)

        with self._lock:
            self.manager.transfers[transfer_id] = recv_transfer
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

    def accept_incoming_resume_offer(
        self,
        nick: str,
        resume_filename: str,
        peer_ip_address: str,
        resume_peer_port: int,
        resume_position_offered_by_peer: int,
        total_filesize: int,
        local_file_path_to_check: str
    ) -> None:
        """
        Handles the logic for accepting a DCC RESUME offer from a peer.
        This method is called by DCCCTCPHandler after initial parsing and validation.
        """
        self.dcc_event_logger.info(f"ReceiveManager: Processing acceptance of RESUME offer for '{resume_filename}' from {nick}.")

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
        elif resume_position_offered_by_peer == 0:
             can_resume_this_offer = True
             actual_resume_offset = 0
             self.dcc_event_logger.info(f"DCC RESUME from {nick} for '{resume_filename}' is from offset 0. Local file missing/re-downloading to '{local_file_path_to_check}'.")

        if can_resume_this_offer:
            ctcp_accept_msg = format_dcc_accept_ctcp(resume_filename, "0", 0, actual_resume_offset, token=None)
            if not ctcp_accept_msg:
                self.dcc_event_logger.error(f"Failed to format DCC ACCEPT for RESUME from {nick}.")
                return

            self.client_logic.send_ctcp_privmsg(nick, ctcp_accept_msg)
            new_transfer_id = self.manager._generate_transfer_id()

            recv_resume_args = {
                "transfer_id": new_transfer_id,
                "peer_nick": nick,
                "filename": resume_filename,
                "filesize": total_filesize,
                "local_filepath": local_file_path_to_check,
                "dcc_manager_ref": self.manager,
                "connect_to_ip": peer_ip_address,
                "connect_to_port": resume_peer_port,
                "resume_offset": actual_resume_offset,
                "peer_ip": peer_ip_address, # Store peer's IP for the transfer object
                "dcc_event_logger": self.dcc_event_logger
            }

            new_recv_transfer = DCCReceiveTransfer(**recv_resume_args)
            with self._lock:
                self.manager.transfers[new_transfer_id] = new_recv_transfer

            new_recv_transfer._report_status(DCCTransferStatus.CONNECTING, f"Accepted RESUME from {nick}. Connecting to resume download.")
            new_recv_transfer.start_transfer_thread()
            self.client_logic.add_message(f"Accepted DCC RESUME from {nick} for '{resume_filename}'. Resuming download from offset {actual_resume_offset}.", "system", context_name="DCC")
        else:
            self.dcc_event_logger.info(f"Cannot accept DCC RESUME from {nick} for '{resume_filename}' under current conditions (offset mismatch or file issue).")
            self.client_logic.add_message(f"Could not accept DCC RESUME from {nick} for '{resume_filename}' (offset/file mismatch).", "warning", context_name="DCC")
