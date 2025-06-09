import logging
import time
import os
import asyncio
from typing import Dict, Optional, Any, TYPE_CHECKING

from pyrc_core.dcc.dcc_utils import parse_dcc_address_and_port, get_safe_dcc_path
from pyrc_core.dcc.dcc_transfer import DCCSendTransfer, DCCReceiveTransfer, DCCStatus, DCCTransfer, DCCTransferType
from pyrc_core.dcc.dcc_protocol import parse_dcc_ctcp

if TYPE_CHECKING:
    from pyrc_core.dcc.dcc_manager import DCCManager

logger = logging.getLogger("pyrc.dcc.ctcphandler")


class DCCCTCPHandler:
    def __init__(self, manager: 'DCCManager'):
        self.manager = manager
        self.dcc_event_logger = manager.dcc_event_logger

    def process_ctcp(self, nick: str, userhost: str, ctcp_payload: str):
        """
        Parses a raw DCC CTCP payload and dispatches it to the appropriate handler.
        """
        parsed_dcc = parse_dcc_ctcp(ctcp_payload)
        if not parsed_dcc:
            asyncio.create_task(self.manager.client_logic.add_message(
                f"Received malformed DCC request from {nick}.",
                self.manager.client_logic.ui.colors["error"],
                context_name="Status"
            ))
            self.dcc_event_logger.warning(f"Could not parse DCC CTCP from {nick}: {ctcp_payload}")
            return

        dcc_command = parsed_dcc.get("dcc_command")
        self.dcc_event_logger.info(
            f"DCCCTCPHandler: Processing DCC Command '{dcc_command}' from {nick}. Data: {parsed_dcc}")

        if dcc_command == "SEND":
            self._handle_send_command(nick, userhost, parsed_dcc)
        elif dcc_command == "ACCEPT":
            self._handle_accept_command(nick, userhost, parsed_dcc)
        elif dcc_command == "RESUME":
            self._handle_resume_offer_command(nick, userhost, parsed_dcc)
        elif dcc_command == "DCCCHECKSUM":
            self._handle_checksum_command(nick, userhost, parsed_dcc)
        else:
            self.dcc_event_logger.warning(
                f"DCCCTCPHandler: Received unhandled DCC command '{dcc_command}' from {nick}: {parsed_dcc}")
            asyncio.create_task(self.manager.client_logic.add_message(
                f"Received unhandled DCC '{dcc_command}' from {nick}: {' '.join(parsed_dcc.get('args', []))}",
                self.manager.client_logic.ui.colors["system"],
                context_name="Status"
            ))

    def _handle_send_command(self, nick: str, userhost: str, parsed_dcc: Dict[str, Any]):
        self.dcc_event_logger.info(f"DCCCTCPHandler: Handling SEND from {nick}: {parsed_dcc}")
        filename = parsed_dcc.get("filename")
        ip_str = parsed_dcc.get("ip_str")
        port = parsed_dcc.get("port")
        filesize = parsed_dcc.get("filesize")
        is_passive_offer = parsed_dcc.get("is_passive_offer", False)
        token = parsed_dcc.get("token")

        if None in [filename, ip_str, port, filesize]:
            self.dcc_event_logger.warning(f"DCC SEND from {nick} missing critical information: {parsed_dcc}")
            return

        event_data = {
            "nick": nick, "userhost": userhost, "filename": filename, "size": filesize,
            "ip": ip_str, "port": port, "is_passive_offer": is_passive_offer
        }
        asyncio.create_task(self.manager.event_manager.dispatch_event("DCC_SEND_OFFER_INCOMING", event_data))

        if is_passive_offer:
            if token:
                assert filename is not None and ip_str is not None and filesize is not None
                self.manager.passive_offer_manager.store_offer(
                    token=token,
                    nick=nick,
                    filename=filename,
                    filesize=filesize,
                    ip_str=ip_str,
                    userhost=userhost
                )
                asyncio.create_task(self.manager.client_logic.add_message(
                    f"Passive DCC SEND offer from {nick} ({userhost}): '{filename}' ({filesize} bytes). "
                    f"Use /dcc get {nick} \"{filename}\" --token {token} to receive.",
                    self.manager.client_logic.ui.colors["system"],
                    context_name="DCC"
                ))
                self.manager._cleanup_stale_passive_offers()
            else:
                self.dcc_event_logger.warning(
                    f"Passive DCC SEND offer from {nick} for '{filename}' missing token. Ignoring.")
                asyncio.create_task(self.manager.client_logic.add_message(
                    f"Malformed passive DCC SEND offer from {nick} (missing token).",
                    self.manager.client_logic.ui.colors["error"],
                    context_name="Status"
                ))
        else:
            self.dcc_event_logger.info(
                f"Received active DCC SEND offer from {nick} for '{filename}'. IP={ip_str}, Port={port}, Size={filesize}")
            asyncio.create_task(self.manager.client_logic.add_message(
                f"DCC SEND offer from {nick} ({userhost}): '{filename}' ({filesize} bytes) from {ip_str}:{port}. "
                f"Use /dcc accept {nick} \"{filename}\" {ip_str} {port} {filesize} to receive.",
                self.manager.client_logic.ui.colors["system"],
                context_name="DCC"
            ))
            if self.manager.dcc_config.auto_accept:
                assert filename is not None and ip_str is not None and port is not None and filesize is not None
                self.dcc_event_logger.info(f"Attempting auto-accept for ACTIVE offer from {nick} for '{str(filename)}'")

                new_transfer_id = self.manager._generate_transfer_id()

                # Use get_safe_dcc_path
                local_filepath = get_safe_dcc_path(self.manager.dcc_config.download_dir, filename)
                if local_filepath is None:
                    self.dcc_event_logger.error(f"Could not create safe local filepath for '{filename}'. Aborting auto-accept.")
                    asyncio.create_task(self.manager.client_logic.add_message(
                        f"Failed to auto-accept DCC SEND from {nick} for '{filename}': Invalid filename or path.",
                        self.manager.client_logic.ui.colors["error"],
                        context_name="DCC"
                    ))
                    return

                incoming_transfer = DCCTransfer(
                    transfer_id=new_transfer_id,
                    transfer_type=DCCTransferType.RECEIVE,
                    peer_nick=nick,
                    filename=filename,
                    file_size=filesize,
                    local_filepath=local_filepath,
                    dcc_manager_ref=self.manager,
                    peer_ip=ip_str,
                    peer_port=port,
                    dcc_event_logger=self.manager.dcc_event_logger
                )
                self.manager.transfers[new_transfer_id] = incoming_transfer

                self.manager.receive_manager.add_pending_dcc_offer(incoming_transfer)

                asyncio.create_task(self.manager.receive_manager.accept_dcc_offer(new_transfer_id))
                self.dcc_event_logger.info(
                    f"Auto-accepted ACTIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {new_transfer_id[:8]}")
                asyncio.create_task(self.manager.client_logic.add_message(
                    f"Auto-accepted ACTIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {new_transfer_id[:8]}",
                    self.manager.client_logic.ui.colors["system"],
                    context_name="DCC"
                ))
                return

        if is_passive_offer and self.manager.dcc_config.auto_accept:
            if filename is not None and token is not None:
                self.dcc_event_logger.info(
                    f"Attempting auto-accept for PASSIVE offer from {nick} for '{filename}' with token {token}")

                # Await the result of accept_passive_offer_by_token as it's an async method
                # The result here is a Task, so we need to wait for it or ensure it's handled.
                # For auto-accept, we fire and forget the acceptance, but log its outcome.
                result = asyncio.create_task(self.manager.accept_passive_offer_by_token(nick, filename, token))

                async def log_auto_accept_result(task_result_coro):
                    task_result = await task_result_coro  # Await the coroutine result
                    if task_result.get("success"):
                        transfer_id_val = task_result.get('transfer_id')
                        transfer_id_short = transfer_id_val[:8] if transfer_id_val else "N/A"
                        self.dcc_event_logger.info(f"Auto-accepted PASSIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {transfer_id_short}")
                        await self.manager.client_logic.add_message(
                            f"Auto-accepted PASSIVE DCC SEND from {nick} for '{str(filename)}'. Transfer ID: {transfer_id_short}",
                            self.manager.client_logic.ui.colors["system"],
                            context_name="DCC"
                        )
                    else:
                        error_msg = task_result.get('error')
                        self.dcc_event_logger.error(f"Auto-accept for PASSIVE DCC SEND from {nick} for '{str(filename)}' failed: {error_msg}")
                        await self.manager.client_logic.add_message(
                            f"Auto-accept for PASSIVE DCC SEND from {nick} for '{str(filename)}' failed: {error_msg}",
                            self.manager.client_logic.ui.colors["error"],
                            context_name="DCC"
                        )
                asyncio.create_task(log_auto_accept_result(result)) # Pass the task directly
            else:
                self.dcc_event_logger.warning(
                    f"Skipping auto-accept for passive offer from {nick} due to missing filename or token.")

    def _handle_accept_command(self, nick: str, userhost: str, parsed_dcc: Dict[str, Any]):
        self.dcc_event_logger.info(f"DCCCTCPHandler: Handling ACCEPT from {nick}: {parsed_dcc}")
        is_passive_dcc_accept = parsed_dcc.get("is_passive_accept", False)
        is_resume_accept = parsed_dcc.get("is_resume_accept", False)
        filename = parsed_dcc.get("filename")

        if is_passive_dcc_accept:
            accepted_ip = parsed_dcc.get("ip_str")
            accepted_port = parsed_dcc.get("port")
            accepted_token = parsed_dcc.get("token")
            self.dcc_event_logger.info(
                f"Received Passive DCC ACCEPT from {nick} for '{filename}' (IP: {accepted_ip}, Port: {accepted_port}, Token: {accepted_token})")

            if not all([filename, accepted_ip, accepted_port is not None, accepted_token]):
                self.dcc_event_logger.warning(
                    f"Passive DCC ACCEPT from {nick} for '{filename}' missing critical info: {parsed_dcc}")
                return

            found_transfer: Optional[DCCSendTransfer] = None
            with self.manager._lock:
                for tid, transfer in self.manager.transfers.items():
                    if (isinstance(transfer, DCCSendTransfer) and
                            transfer.is_passive_offer and
                            transfer.passive_token == accepted_token and
                            transfer.filename == filename and
                            transfer.peer_nick == nick):
                        found_transfer = transfer
                        break

            if found_transfer:
                self.dcc_event_logger.info(
                    f"Matching passive SEND offer found (ID: {found_transfer.id}). Initiating connection to {nick} at {accepted_ip}:{accepted_port}")
                found_transfer.peer_ip = accepted_ip
                found_transfer.peer_port = accepted_port
                found_transfer.set_status(DCCStatus.CONNECTING,
                                           f"Peer accepted passive offer. Connecting to {accepted_ip}:{accepted_port}.")
                asyncio.create_task(self.manager.send_manager.start_send_transfer_from_accept(found_transfer))
            else:
                self.dcc_event_logger.warning(
                    f"Received Passive DCC ACCEPT from {nick} for '{filename}' with token '{accepted_token}', but no matching passive offer found.")
                asyncio.create_task(self.manager.client_logic.add_message(
                    f"Received unexpected Passive DCC ACCEPT from {nick} for '{filename}'.",
                    self.manager.client_logic.ui.colors["warning"],
                    context_name="Status"
                ))

        elif is_resume_accept:
            accepted_filename = parsed_dcc.get("filename")
            accepted_port = parsed_dcc.get("port")
            accepted_position = parsed_dcc.get("position")
            self.dcc_event_logger.info(
                f"Received Resume DCC ACCEPT from {nick} for '{accepted_filename}' (Port: {accepted_port}, Position: {accepted_position}).")

            found_resuming_send_transfer: Optional[DCCSendTransfer] = None
            with self.manager._lock:
                for tid, transfer_obj in self.manager.transfers.items():
                    if (isinstance(transfer_obj, DCCSendTransfer) and
                            transfer_obj.peer_nick == nick and
                            transfer_obj.filename == accepted_filename and
                            transfer_obj.resume_offset == accepted_position and
                            transfer_obj.status == DCCStatus.NEGOTIATING):
                        found_resuming_send_transfer = transfer_obj
                        break

            if found_resuming_send_transfer:
                self.dcc_event_logger.info(
                    f"DCC RESUME for '{accepted_filename}' to {nick} acknowledged by peer. Transfer {found_resuming_send_transfer.id} should proceed.")
                if accepted_port is not None:
                    asyncio.create_task(
                        self.manager.send_manager.resume_send_transfer(found_resuming_send_transfer, int(accepted_port)))
                else:
                    self.dcc_event_logger.warning(
                        f"Received unexpected/mismatched Resume DCC ACCEPT from {nick} for '{accepted_filename}' with no port provided.")
                    asyncio.create_task(self.manager.client_logic.add_message(
                        f"Received unexpected/mismatched Resume DCC ACCEPT from {nick} for '{accepted_filename}' with no port.",
                        self.manager.client_logic.ui.colors["warning"],
                        context_name="Status"
                    ))
            else:
                self.dcc_event_logger.warning(
                    f"Received unexpected/mismatched Resume DCC ACCEPT from {nick} for '{accepted_filename}'.")
                asyncio.create_task(self.manager.client_logic.add_message(
                    f"Received unexpected/mismatched Resume DCC ACCEPT from {nick} for '{accepted_filename}'.",
                    self.manager.client_logic.ui.colors["warning"],
                    context_name="Status"
                ))
            if accepted_filename is None:
                self.dcc_event_logger.error(f"Resume DCC ACCEPT from {nick} had None for filename after parsing. This should not happen.")
        else:
            self.dcc_event_logger.warning(f"Received ambiguous DCC ACCEPT from {nick}: {parsed_dcc}")

    def _handle_resume_offer_command(self, nick: str, userhost: str, parsed_dcc: Dict[str, Any]):
        self.dcc_event_logger.info(f"DCCCTCPHandler: Handling RESUME offer from {nick}: {parsed_dcc}")

        if not self.manager.dcc_config.resume_enabled:
            self.dcc_event_logger.info(f"DCC RESUME from {nick} ignored, resume disabled in config.")
            return

        resume_filename = parsed_dcc.get("filename")
        resume_peer_port = parsed_dcc.get("port")
        resume_position_offered_by_peer = parsed_dcc.get("position")

        if not (isinstance(resume_filename, str) and
                isinstance(resume_peer_port, int) and
                isinstance(resume_position_offered_by_peer, int)):
            self.dcc_event_logger.warning(
                f"DCC RESUME from {nick} has missing or malformed fields after parsing. "
                f"Filename type: {type(resume_filename)}, Port type: {type(resume_peer_port)}, Position type: {type(resume_position_offered_by_peer)}. "
                f"Parsed DCC: {parsed_dcc}"
            )
            return

        self.dcc_event_logger.info(
            f"Received DCC RESUME offer from {nick} for '{resume_filename}' to port {resume_peer_port} from offset {resume_position_offered_by_peer}.")

        existing_transfer_info: Optional[Dict[str, Any]] = None
        with self.manager._lock:
            for tid, transfer in self.manager.transfers.items():
                if (isinstance(transfer, DCCReceiveTransfer) and
                        transfer.peer_nick == nick and
                        transfer.filename == resume_filename and
                        transfer.status in [DCCStatus.FAILED, DCCStatus.CANCELLED, DCCStatus.TIMED_OUT]):
                    existing_transfer_info = {
                        "local_filepath": transfer.local_filepath,
                        "total_filesize": transfer.file_size,
                        "current_bytes": transfer.bytes_transferred,
                        "peer_ip": transfer.peer_ip
                    }
                    break

        if not existing_transfer_info:
            if resume_position_offered_by_peer == 0:
                self.dcc_event_logger.warning(
                    f"DCC RESUME from {nick} for '{resume_filename}' at offset 0, but no prior transfer record found. Total filesize is unknown. Rejecting.")
                asyncio.create_task(self.manager.client_logic.add_message(
                    f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': No prior transfer record to determine total filesize.",
                    self.manager.client_logic.ui.colors["error"],
                    context_name="DCC"
                ))
            else:
                self.dcc_event_logger.warning(
                    f"DCC RESUME from {nick} for '{resume_filename}' at offset {resume_position_offered_by_peer}, but no prior transfer record found. Rejecting.")
                asyncio.create_task(self.manager.client_logic.add_message(
                    f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': No prior transfer record.",
                    self.manager.client_logic.ui.colors["error"],
                    context_name="DCC"
                ))
            return

        local_file_path_to_check = existing_transfer_info["local_filepath"]
        total_filesize = existing_transfer_info["total_filesize"]
        peer_ip_address = existing_transfer_info.get("peer_ip")

        if not peer_ip_address:
            self.dcc_event_logger.error(
                f"DCC RESUME from {nick} for '{resume_filename}': Peer IP address not found in prior transfer record. Cannot proceed.")
            asyncio.create_task(self.manager.client_logic.add_message(
                f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': Peer IP unknown from prior record.",
                self.manager.client_logic.ui.colors["error"],
                context_name="DCC"
            ))
            return

        if total_filesize <= 0:
            self.dcc_event_logger.error(
                f"DCC RESUME from {nick} for '{resume_filename}': Prior transfer record has invalid total filesize ({total_filesize}). Rejecting.")
            asyncio.create_task(self.manager.client_logic.add_message(
                f"Cannot accept DCC RESUME from {nick} for '{resume_filename}': Invalid prior transfer data (filesize).",
                self.manager.client_logic.ui.colors["error"],
                context_name="DCC"
            ))
            return

        resume_offer_id = f"{nick}-{resume_filename}-{resume_position_offered_by_peer}-{peer_ip_address}-{resume_peer_port}"
        resume_transfer = DCCReceiveTransfer(
            transfer_id=resume_offer_id,
            transfer_type=DCCTransferType.RECEIVE,
            peer_nick=nick,
            filename=resume_filename,
            file_size=total_filesize,
            local_filepath=local_file_path_to_check,
            dcc_manager_ref=self.manager,
            peer_ip=peer_ip_address,
            peer_port=resume_peer_port,
            bytes_transferred=resume_position_offered_by_peer,
            dcc_event_logger=self.manager.dcc_event_logger
        )
        resume_transfer.set_status(DCCStatus.PENDING_RESUME, "Resume offer received")
        self.manager.receive_manager.add_pending_dcc_offer(resume_transfer)

        self.dcc_event_logger.info(f"DCC RESUME offer from {nick} for '{resume_filename}' added as pending. ID: {resume_offer_id}")
        asyncio.create_task(self.manager.client_logic.add_message(
            f"DCC RESUME offer from {nick} for '{resume_filename}' at offset {resume_position_offered_by_peer}. "
            f"Use /dcc accept {resume_offer_id} to resume.",
            self.manager.client_logic.ui.colors["info"],
            context_name="DCC"
        ))

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

        self.dcc_event_logger.info(
            f"Received DCCCHECKSUM from {nick} for transfer '{transfer_identifier}', file '{filename}', algo '{algorithm}'.")

        transfer_to_update: Optional[DCCReceiveTransfer] = None
        with self.manager._lock:
            for tid, tr_obj in self.manager.transfers.items():
                if (isinstance(tr_obj, DCCReceiveTransfer) and
                        tr_obj.peer_nick == nick and
                        tr_obj.filename == filename):
                    transfer_to_update = tr_obj
                    break

            if not transfer_to_update:
                for tid, tr_obj in self.manager.transfers.items():
                    if isinstance(tr_obj, DCCReceiveTransfer) and \
                            tr_obj.peer_nick == nick and \
                            tr_obj.filename == filename and \
                            tr_obj.status == DCCStatus.COMPLETED:
                        transfer_to_update = tr_obj
                        self.dcc_event_logger.info(f"DCCCHECKSUM matched by filename/nick for completed transfer {tid}")
                        break

        if transfer_to_update:
            if hasattr(transfer_to_update, 'set_expected_checksum'):
                transfer_to_update.set_expected_checksum(algorithm, checksum_value)
            else:
                self.dcc_event_logger.error(
                    f"Transfer object {transfer_to_update.id} does not have set_expected_checksum method.")
        else:
            self.dcc_event_logger.warning(
                f"Received DCCCHECKSUM from {nick} for '{filename}' (ID/Ref: {transfer_identifier}), but no matching active/completed RECV transfer found.")
