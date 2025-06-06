import logging
import time
from typing import Dict, Optional, Any, TYPE_CHECKING

# Runtime imports needed for type checks or direct use if any
from pyrc_core.dcc.dcc_transfer import DCCSendTransfer, DCCReceiveTransfer, DCCTransferStatus

if TYPE_CHECKING:
    from pyrc_core.dcc.dcc_manager import DCCManager # To avoid circular import for type hinting
    # dcc_transfer types already imported above for runtime, but good for explicitness in TYPE_CHECKING
    # from dcc_core.dcc_transfer import DCCTransfer, DCCSendTransfer, DCCReceiveTransfer, DCCTransferStatus

logger = logging.getLogger("pyrc.dcc.ctcphandler")

class DCCCTCPHandler:
    def __init__(self, manager: 'DCCManager'):
        self.manager = manager
        self.dcc_event_logger = manager.dcc_event_logger

    def process_ctcp(self, nick: str, userhost: str, parsed_dcc: Dict[str, Any]):
        """
        Processes a parsed DCC CTCP command.
        """
        dcc_command = parsed_dcc.get("dcc_command")
        # self.dcc_event_logger.info(f"DCCCTCPHandler: Received DCC Command '{dcc_command}' from {nick} with data: {parsed_dcc}")
        # This log is already done in DCCManager before calling this, and a more detailed one below.

        if dcc_command == "SEND":
            self._handle_send_command(nick, userhost, parsed_dcc)
        elif dcc_command == "ACCEPT":
            self._handle_accept_command(nick, userhost, parsed_dcc)
        elif dcc_command == "RESUME":
            self._handle_resume_offer_command(nick, userhost, parsed_dcc)
        elif dcc_command == "DCCCHECKSUM":
            self._handle_checksum_command(nick, userhost, parsed_dcc)
        else:
            self.dcc_event_logger.warning(f"DCCCTCPHandler: Received unhandled DCC command '{dcc_command}' from {nick}: {parsed_dcc}")
            self.manager.client_logic.add_message(
                f"Received unhandled DCC '{dcc_command}' from {nick}: {' '.join(parsed_dcc.get('args',[]))}",
                "system",
                context_name="Status"
            )

    def _handle_send_command(self, nick: str, userhost: str, parsed_dcc: Dict[str, Any]):
        self.dcc_event_logger.info(f"DCCCTCPHandler: Handling SEND from {nick}: {parsed_dcc}")
        filename = parsed_dcc.get("filename")
        ip_str = parsed_dcc.get("ip_str")
        port = parsed_dcc.get("port")
        filesize = parsed_dcc.get("filesize")
        is_passive_offer = parsed_dcc.get("is_passive_offer", False)
        token = parsed_dcc.get("token")

        if None in [filename, ip_str, port, filesize]: # filesize can be 0
            self.dcc_event_logger.warning(f"DCC SEND from {nick} missing critical information: {parsed_dcc}")
            return

        event_data = {
            "nick": nick, "userhost": userhost, "filename": filename, "size": filesize,
            "ip": ip_str, "port": port, "is_passive_offer": is_passive_offer
        }
        if token:
            event_data["token"] = token
        self.manager.event_manager.dispatch_event("DCC_SEND_OFFER_INCOMING", event_data)

        if is_passive_offer:
            if token:
                # Use the new DCCPassiveOfferManager to store the offer
                # The lock is handled within the DCCPassiveOfferManager's methods
                assert filename is not None and ip_str is not None and filesize is not None # Ensure type safety for store_offer
                self.manager.passive_offer_manager.store_offer(
                    token=token,
                    nick=nick,
                    filename=filename,
                    filesize=filesize,
                    ip_str=ip_str,
                    userhost=userhost
                )
                # self.dcc_event_logger.info(f"Stored pending passive DCC SEND offer from {nick} for '{filename}' (IP: {ip_str}) with token {token}.") # Logged by store_offer
                self.manager._cleanup_stale_passive_offers() # Manager can still trigger cleanup
                self.manager.client_logic.add_message(
                    f"Passive DCC SEND offer from {nick} ({userhost}): '{filename}' ({filesize} bytes). "
                    f"Use /dcc get {nick} \"{filename}\" --token {token} to receive.",
                    "system", context_name="DCC"
                )
            else:
                self.dcc_event_logger.warning(f"Passive DCC SEND offer from {nick} for '{filename}' missing token. Ignoring.")
                self.manager.client_logic.add_message(f"Malformed passive DCC SEND offer from {nick} (missing token).", "error", context_name="Status")
        else: # Active offer
            self.dcc_event_logger.info(f"Received active DCC SEND offer from {nick} for '{filename}'. IP={ip_str}, Port={port}, Size={filesize}")
            self.manager.client_logic.add_message(
                f"DCC SEND offer from {nick} ({userhost}): '{filename}' ({filesize} bytes) from {ip_str}:{port}. "
                f"Use /dcc accept {nick} \"{filename}\" {ip_str} {port} {filesize} to receive.",
                "system", context_name="DCC"
            )
            if self.manager.dcc_config.get("auto_accept", False):
                # Active offer auto-accept
                assert filename is not None and ip_str is not None and port is not None and filesize is not None
                self.dcc_event_logger.info(f"Attempting auto-accept for ACTIVE offer from {nick} for '{str(filename)}'")
                result = self.manager.accept_incoming_send_offer(nick, filename, ip_str, port, filesize)
                if result.get("success"):
                    transfer_id_val = result.get('transfer_id')
                    transfer_id_short = transfer_id_val[:8] if transfer_id_val else "N/A"
                    self.dcc_event_logger.info(f"Auto-accepted ACTIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {transfer_id_short}")
                    self.manager.client_logic.add_message(f"Auto-accepted ACTIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {transfer_id_short}", "system", context_name="DCC")
                else:
                    self.dcc_event_logger.error(f"Auto-accept for ACTIVE DCC SEND from {nick} for '{str(filename)}' failed: {result.get('error')}")
                    self.manager.client_logic.add_message(f"Auto-accept for ACTIVE DCC SEND from {nick} for '{str(filename)}' failed: {result.get('error')}", "error", context_name="DCC")
                return # Offer handled (successfully or not by auto-accept)

        # Auto-accept for PASSIVE offers (if not active and auto-accept is on)
        if is_passive_offer and self.manager.dcc_config.get("auto_accept", False):
            if filename is not None and token is not None:
                self.dcc_event_logger.info(f"Attempting auto-accept for PASSIVE offer from {nick} for '{filename}' with token {token}")
                result = self.manager.accept_passive_offer_by_token(nick, filename, token)
                if result.get("success"):
                    transfer_id_val = result.get('transfer_id')
                    transfer_id_short = transfer_id_val[:8] if transfer_id_val else "N/A"
                    self.dcc_event_logger.info(f"Auto-accepted PASSIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {transfer_id_short}")
                    self.manager.client_logic.add_message(f"Auto-accepted PASSIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {transfer_id_short}", "system", context_name="DCC")
                else:
                    self.dcc_event_logger.error(f"Auto-accept for PASSIVE DCC SEND from {nick} for '{str(filename)}' failed: {result.get('error')}")
                    self.manager.client_logic.add_message(f"Auto-accept for PASSIVE DCC SEND from {nick} for '{str(filename)}' failed: {result.get('error')}", "error", context_name="DCC")
            else:
                 self.dcc_event_logger.warning(f"Skipping auto-accept for passive offer from {nick} due to missing filename or token.")


    def _handle_accept_command(self, nick: str, userhost: str, parsed_dcc: Dict[str, Any]):
        self.dcc_event_logger.info(f"DCCCTCPHandler: Handling ACCEPT from {nick}: {parsed_dcc}")
        is_passive_dcc_accept = parsed_dcc.get("is_passive_accept", False)
        is_resume_accept = parsed_dcc.get("is_resume_accept", False)
        filename = parsed_dcc.get("filename")

        if is_passive_dcc_accept:
            accepted_ip = parsed_dcc.get("ip_str")
            accepted_port = parsed_dcc.get("port")
            accepted_token = parsed_dcc.get("token")
            self.dcc_event_logger.info(f"Received Passive DCC ACCEPT from {nick} for '{filename}' (IP: {accepted_ip}, Port: {accepted_port}, Token: {accepted_token})")

            if not all([filename, accepted_ip, accepted_port is not None, accepted_token]):
                self.dcc_event_logger.warning(f"Passive DCC ACCEPT from {nick} for '{filename}' missing critical info: {parsed_dcc}")
                return

            found_transfer: Optional[DCCSendTransfer] = None
            with self.manager._lock:
                for tid, transfer in self.manager.transfers.items():
                    if (isinstance(transfer, DCCSendTransfer) and
                        transfer.is_passive_offer and
                        transfer.passive_token == accepted_token and
                        transfer.original_filename == filename and
                        transfer.peer_nick == nick):
                        found_transfer = transfer
                        break

            if found_transfer:
                self.dcc_event_logger.info(f"Matching passive SEND offer found (ID: {found_transfer.transfer_id}). Initiating connection to {nick} at {accepted_ip}:{accepted_port}")
                found_transfer.connect_to_ip = accepted_ip
                found_transfer.connect_to_port = accepted_port
                found_transfer._report_status(DCCTransferStatus.CONNECTING, f"Peer accepted passive offer. Connecting to {accepted_ip}:{accepted_port}.")
                found_transfer.start_transfer_thread()
            else:
                self.dcc_event_logger.warning(f"Received Passive DCC ACCEPT from {nick} for '{filename}' with token '{accepted_token}', but no matching passive offer found.")
                self.manager.client_logic.add_message(f"Received unexpected Passive DCC ACCEPT from {nick} for '{filename}'.", "warning", context_name="Status")

        elif is_resume_accept:
            accepted_filename = parsed_dcc.get("filename")
            accepted_port = parsed_dcc.get("port")
            accepted_position = parsed_dcc.get("position")
            self.dcc_event_logger.info(f"Received Resume DCC ACCEPT from {nick} for '{accepted_filename}' (Port: {accepted_port}, Position: {accepted_position}).")

            found_resuming_send_transfer: Optional[DCCSendTransfer] = None
            with self.manager._lock:
                for tid, transfer_obj in self.manager.transfers.items():
                    if (isinstance(transfer_obj, DCCSendTransfer) and
                        transfer_obj.peer_nick == nick and
                        transfer_obj.original_filename == accepted_filename and
                        hasattr(transfer_obj, 'resume_offset') and
                        transfer_obj.resume_offset == accepted_position and
                        transfer_obj.status == DCCTransferStatus.NEGOTIATING and
                        transfer_obj.server_socket is not None and
                        transfer_obj.server_socket.getsockname()[1] == accepted_port):
                        found_resuming_send_transfer = transfer_obj
                        break

            if found_resuming_send_transfer:
                self.dcc_event_logger.info(f"DCC RESUME for '{accepted_filename}' to {nick} acknowledged by peer. Transfer {found_resuming_send_transfer.transfer_id} should proceed.")
            else:
                self.dcc_event_logger.warning(f"Received Resume DCC ACCEPT from {nick} for '{accepted_filename}', but no matching active RESUME offer found or details mismatch.")
                self.manager.client_logic.add_message(f"Received unexpected/mismatched Resume DCC ACCEPT from {nick} for '{accepted_filename}'.", "warning", context_name="Status")
            if accepted_filename is None: # Should ideally not happen if parsing was correct
                 self.dcc_event_logger.error(f"Resume DCC ACCEPT from {nick} had None for filename after parsing. This should not happen.")
        else:
            self.dcc_event_logger.warning(f"Received ambiguous DCC ACCEPT from {nick}: {parsed_dcc}")


    def _handle_resume_offer_command(self, nick: str, userhost: str, parsed_dcc: Dict[str, Any]):
        # This is when a peer offers to RESUME sending a file to us
        self.dcc_event_logger.info(f"DCCCTCPHandler: Handling RESUME offer from {nick}: {parsed_dcc}")

        if not self.manager.dcc_config.get("resume_enabled", True):
            self.dcc_event_logger.info(f"DCC RESUME from {nick} ignored, resume disabled in config.")
            return

        resume_filename = parsed_dcc.get("filename")
        resume_peer_port = parsed_dcc.get("port")
        resume_position_offered_by_peer = parsed_dcc.get("position")

        # Validate presence and correct types as per parse_dcc_ctcp contract
        if not (isinstance(resume_filename, str) and
                isinstance(resume_peer_port, int) and
                isinstance(resume_position_offered_by_peer, int)):
            self.dcc_event_logger.warning(
                f"DCC RESUME from {nick} has missing or malformed fields after parsing. "
                f"Filename type: {type(resume_filename)}, Port type: {type(resume_peer_port)}, Position type: {type(resume_position_offered_by_peer)}. "
                f"Parsed DCC: {parsed_dcc}"
            )
            return

        # Now resume_filename, resume_peer_port, resume_position_offered_by_peer are known to be str, int, int respectively.
        self.dcc_event_logger.info(f"Received DCC RESUME offer from {nick} for '{resume_filename}' to port {resume_peer_port} from offset {resume_position_offered_by_peer}.")

        existing_transfer_info: Optional[Dict[str, Any]] = None
        with self.manager._lock:
            for tid, transfer in self.manager.transfers.items():
                if (isinstance(transfer, DCCReceiveTransfer) and
                    transfer.peer_nick == nick and
                    transfer.original_filename == resume_filename and
                    transfer.status in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]):
                    existing_transfer_info = {
                        "local_filepath": transfer.local_filepath,
                        "total_filesize": transfer.filesize,
                        "current_bytes": transfer.bytes_transferred,
                        "peer_ip": transfer.peer_ip
                    }
                    break

        if not existing_transfer_info:
            if resume_position_offered_by_peer == 0:
                self.dcc_event_logger.warning(f"DCC RESUME from {nick} for '{resume_filename}' at offset 0, but no prior transfer record found. Total filesize is unknown. Rejecting.")
                self.manager.client_logic.add_message(f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': No prior transfer record to determine total filesize.", "error", context_name="DCC")
            else:
                self.dcc_event_logger.warning(f"DCC RESUME from {nick} for '{resume_filename}' at offset {resume_position_offered_by_peer}, but no prior transfer record found. Rejecting.")
                self.manager.client_logic.add_message(f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': No prior transfer record.", "error", context_name="DCC")
            return

        local_file_path_to_check = existing_transfer_info["local_filepath"]
        total_filesize = existing_transfer_info["total_filesize"]
        peer_ip_address = existing_transfer_info.get("peer_ip")

        if not peer_ip_address:
            self.dcc_event_logger.error(f"DCC RESUME from {nick} for '{resume_filename}': Peer IP address not found in prior transfer record. Cannot proceed.")
            self.manager.client_logic.add_message(f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': Peer IP unknown from prior record.", "error", context_name="DCC")
            return

        if total_filesize <= 0:
            self.dcc_event_logger.error(f"DCC RESUME from {nick} for '{resume_filename}': Prior transfer record has invalid total filesize ({total_filesize}). Rejecting.")
            self.manager.client_logic.add_message(f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': Invalid prior transfer data (filesize).", "error", context_name="DCC")
            return

        # Delegate the actual acceptance logic to a DCCManager method
        # This keeps DCCCTCPHandler focused on parsing and initial dispatch.
        self.manager.accept_incoming_resume_offer(
            nick, resume_filename, peer_ip_address, resume_peer_port,
            resume_position_offered_by_peer, total_filesize, local_file_path_to_check
        )


    def _handle_checksum_command(self, nick: str, userhost: str, parsed_dcc: Dict[str, Any]):
        self.dcc_event_logger.info(f"DCCCTCPHandler: Handling DCCCHECKSUM from {nick}: {parsed_dcc}")
        transfer_identifier = parsed_dcc.get("transfer_identifier")
        filename = parsed_dcc.get("filename")
        algorithm = parsed_dcc.get("algorithm")
        checksum_value = parsed_dcc.get("checksum_value")

        if not all([transfer_identifier, filename, algorithm, checksum_value]):
            self.dcc_event_logger.warning(f"Malformed DCCCHECKSUM from {nick}: {parsed_dcc}")
            return

        assert isinstance(algorithm, str) and isinstance(checksum_value, str)

        self.dcc_event_logger.info(f"Received DCCCHECKSUM from {nick} for transfer '{transfer_identifier}', file '{filename}', algo '{algorithm}'.")

        transfer_to_update: Optional[DCCReceiveTransfer] = None
        with self.manager._lock:
            if transfer_identifier in self.manager.transfers:
                potential_transfer = self.manager.transfers[transfer_identifier]
                if isinstance(potential_transfer, DCCReceiveTransfer) and \
                   potential_transfer.peer_nick == nick and \
                   potential_transfer.original_filename == filename:
                    transfer_to_update = potential_transfer

            if not transfer_to_update:
                for tid, tr_obj in self.manager.transfers.items():
                    if isinstance(tr_obj, DCCReceiveTransfer) and \
                       tr_obj.peer_nick == nick and \
                       tr_obj.original_filename == filename and \
                       tr_obj.status == DCCTransferStatus.COMPLETED:
                       transfer_to_update = tr_obj
                       self.dcc_event_logger.info(f"DCCCHECKSUM matched by filename/nick for completed transfer {tid}")
                       break

        if transfer_to_update:
            if hasattr(transfer_to_update, 'set_expected_checksum'):
                transfer_to_update.set_expected_checksum(algorithm, checksum_value)
            else:
                self.dcc_event_logger.error(f"Transfer object {transfer_to_update.transfer_id} does not have set_expected_checksum method.")
        else:
            self.dcc_event_logger.warning(f"Received DCCCHECKSUM from {nick} for '{filename}' (ID/Ref: {transfer_identifier}), but no matching active/completed RECV transfer found.")
