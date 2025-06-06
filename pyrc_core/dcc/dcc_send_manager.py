import logging
import os
import uuid
import socket
from collections import deque
from typing import Dict, Optional, Any, List, Deque, TYPE_CHECKING

from pyrc_core.dcc.dcc_transfer import DCCSendTransfer, DCCTransferStatus # Assuming DCCTransferType is not directly used here
from pyrc_core.dcc.dcc_protocol import format_dcc_send_ctcp, format_dcc_resume_ctcp

if TYPE_CHECKING:
    from pyrc_core.dcc.dcc_manager import DCCManager

logger = logging.getLogger("pyrc.dcc.sendmanager") # Specific logger for this manager

class DCCSendManager:
    def __init__(self, manager_ref: 'DCCManager'):
        self.manager = manager_ref
        self.dcc_event_logger = manager_ref.dcc_event_logger # Use manager's event logger
        self._lock = manager_ref._lock
        self.send_queues: Dict[str, Deque[Dict[str, Any]]] = {}

    def initiate_sends(self, peer_nick: str, local_filepaths: List[str], passive: bool = False) -> Dict[str, Any]:
        self.dcc_event_logger.info(f"SendManager: Initiating sends to {peer_nick} for {len(local_filepaths)} file(s), passive={passive}")

        results: Dict[str, Any] = {
            "transfers_started": [],
            "files_queued": [],
            "errors": [],
            "overall_success": True
        }
        validated_files_to_process: List[Dict[str, Any]] = []

        for local_filepath_orig in local_filepaths:
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
            if filesize > self.manager.dcc_config["max_file_size"]:
                err_msg = f"File '{original_filename}' exceeds maximum size of {self.manager.dcc_config['max_file_size']} bytes."
                self.dcc_event_logger.warning(f"DCC SEND to {peer_nick}: {err_msg}")
                results["errors"].append({"filename": original_filename, "error": err_msg})
                continue
            validated_files_to_process.append({
                "local_filepath": abs_local_filepath,
                "original_filename": original_filename,
                "filesize": filesize,
                "passive": passive
            })

        if not validated_files_to_process:
            results["overall_success"] = False
            if not results["errors"]:
                 results["error"] = "No valid files provided for sending."
            return results

        with self._lock:
            is_active_send_to_peer = any(
                isinstance(t, DCCSendTransfer) and t.peer_nick == peer_nick and
                t.status not in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT]
                for t in self.manager.transfers.values()
            )
            queue_exists_for_peer = peer_nick in self.send_queues and self.send_queues[peer_nick]

            if is_active_send_to_peer or queue_exists_for_peer:
                if peer_nick not in self.send_queues:
                    self.send_queues[peer_nick] = deque()
                for file_info in validated_files_to_process:
                    self.send_queues[peer_nick].append(file_info)
                    results["files_queued"].append({"filename": file_info["original_filename"], "size": file_info["filesize"]})
                    self.dcc_event_logger.info(f"Queued DCC SEND of '{file_info['original_filename']}' to {peer_nick}. Queue size: {len(self.send_queues[peer_nick])}")
                    self.manager.client_logic.add_message(f"Queued DCC SEND of '{file_info['original_filename']}' to {peer_nick}.", "system", context_name="DCC")
            else:
                self.dcc_event_logger.info(f"No active send or queue for {peer_nick}. Starting first file and queuing rest.")
                first_file_info = validated_files_to_process.pop(0)
                exec_result = self._execute_send_operation(
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
                    results["overall_success"] = False
                if validated_files_to_process:
                    if peer_nick not in self.send_queues:
                        self.send_queues[peer_nick] = deque()
                    for file_info in validated_files_to_process:
                        self.send_queues[peer_nick].append(file_info)
                        results["files_queued"].append({"filename": file_info["original_filename"], "size": file_info["filesize"]})
                        self.dcc_event_logger.info(f"Queued DCC SEND of '{file_info['original_filename']}' to {peer_nick} (after starting first). Queue size: {len(self.send_queues[peer_nick])}")
                        self.manager.client_logic.add_message(f"Queued DCC SEND of '{file_info['original_filename']}' to {peer_nick} (after starting first).", "system", context_name="DCC")

        if not results["transfers_started"] and not results["files_queued"] and not results["errors"]:
            results["error"] = "No files processed."
            results["overall_success"] = False
        return results

    def _execute_send_operation(self, peer_nick: str, local_filepath: str, original_filename: str, filesize: int, passive: bool = False) -> Dict[str, Any]:
        self.dcc_event_logger.info(f"SendManager: Executing DCC SEND: Peer={peer_nick}, File='{original_filename}', Size={filesize}, Passive={passive}, Path='{local_filepath}'")
        abs_local_filepath = os.path.abspath(local_filepath)

        if self.manager.dcc_config.get("resume_enabled", True) and not passive:
            with self._lock:
                for tid, old_transfer in list(self.manager.transfers.items()):
                    if (isinstance(old_transfer, DCCSendTransfer) and
                        old_transfer.peer_nick == peer_nick and
                        old_transfer.original_filename == original_filename and
                        old_transfer.status in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.TIMED_OUT] and
                        old_transfer.bytes_transferred > 0 and
                        old_transfer.bytes_transferred < old_transfer.filesize):
                        resume_offset = old_transfer.bytes_transferred
                        self.dcc_event_logger.info(f"Found previous incomplete send of '{original_filename}' to {peer_nick} at offset {resume_offset}. Offering RESUME.")
                        socket_info_resume = self.manager._get_listening_socket()
                        if not socket_info_resume:
                            self.dcc_event_logger.error(f"Could not get listening socket for DCC RESUME of '{original_filename}' to {peer_nick}.")
                            break
                        listening_socket_resume, port_resume = socket_info_resume
                        ctcp_resume_message = format_dcc_resume_ctcp(original_filename, port_resume, resume_offset)
                        if not ctcp_resume_message:
                            listening_socket_resume.close()
                            self.dcc_event_logger.error(f"Failed to format DCC RESUME CTCP for '{original_filename}'.")
                            break
                        new_transfer_id_resume = self.manager._generate_transfer_id()
                        resume_send_args: Dict[str, Any] = {
                            "transfer_id": new_transfer_id_resume, "peer_nick": peer_nick,
                            "filename": original_filename, "filesize": filesize,
                            "local_filepath": abs_local_filepath, "dcc_manager_ref": self.manager,
                            "server_socket_for_active_send": listening_socket_resume,
                            "resume_offset": resume_offset, "dcc_event_logger": self.dcc_event_logger
                        }
                        resume_transfer = DCCSendTransfer(**resume_send_args)
                        self.manager.transfers[new_transfer_id_resume] = resume_transfer
                        self.manager.client_logic.send_ctcp_privmsg(peer_nick, ctcp_resume_message)
                        resume_transfer._report_status(DCCTransferStatus.NEGOTIATING, f"DCC RESUME offered. Waiting for {peer_nick} to connect on port {port_resume} for '{original_filename}' from offset {resume_offset}.")
                        resume_transfer.start_transfer_thread()
                        self.manager.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", {
                            "transfer_id": new_transfer_id_resume, "type": "SEND_RESUME", "nick": peer_nick,
                            "filename": original_filename, "size": filesize, "resume_offset": resume_offset
                        })
                        self.manager.client_logic.add_message(f"Offering to RESUME DCC SEND to {peer_nick} for '{original_filename}' from offset {resume_offset}. Waiting for peer on port {port_resume}.", "system", context_name="DCC")
                        return {"success": True, "transfer_id": new_transfer_id_resume, "filename": original_filename, "resumed": True}

        transfer_id = self.manager._generate_transfer_id()
        self.dcc_event_logger.debug(f"Generated Transfer ID: {transfer_id} for SEND to {peer_nick} of '{original_filename}'")
        passive_token: Optional[str] = None
        ctcp_message: Optional[str] = None
        send_transfer_args: Dict[str, Any] = {
            "transfer_id": transfer_id, "peer_nick": peer_nick,
            "filename": original_filename, "filesize": filesize,
            "local_filepath": abs_local_filepath, "dcc_manager_ref": self.manager,
        }
        status_message_suffix = ""

        if passive:
            passive_token = self.manager._generate_transfer_id()
            local_ip_for_ctcp = self.manager._get_local_ip_for_ctcp()
            ctcp_message = format_dcc_send_ctcp(original_filename, local_ip_for_ctcp, 0, filesize, passive_token)
            send_transfer_args["is_passive_offer"] = True
            send_transfer_args["passive_token"] = passive_token
            status_message_suffix = f" (Passive Offer, token: {passive_token[:8]})"
            if not ctcp_message:
                self.dcc_event_logger.error(f"Failed to format passive DCC SEND CTCP for '{original_filename}' to {peer_nick}.")
                return {"success": False, "error": "Failed to format passive DCC SEND CTCP message."}
            self.dcc_event_logger.debug(f"Passive SEND to {peer_nick} for '{original_filename}'. CTCP: {ctcp_message.strip()}")
        else: # Active DCC
            socket_info = self.manager._get_listening_socket()
            if not socket_info:
                self.dcc_event_logger.error(f"Could not get listening socket for active SEND of '{original_filename}' to {peer_nick}.")
                return {"success": False, "error": "Could not create listening socket for active DCC SEND."}
            listening_socket, port = socket_info
            local_ip_for_ctcp = self.manager._get_local_ip_for_ctcp()
            ctcp_message = format_dcc_send_ctcp(original_filename, local_ip_for_ctcp, port, filesize)
            send_transfer_args["server_socket_for_active_send"] = listening_socket
            status_message_suffix = f". Waiting for connection on port {port}."
            if not ctcp_message:
                listening_socket.close()
                self.dcc_event_logger.error(f"Failed to format active DCC SEND CTCP for '{original_filename}' to {peer_nick}.")
                return {"success": False, "error": "Failed to format active DCC SEND CTCP message."}
            self.dcc_event_logger.debug(f"Active SEND to {peer_nick} for '{original_filename}'. CTCP: {ctcp_message.strip()}")

        send_transfer_args["dcc_event_logger"] = self.dcc_event_logger
        send_transfer = DCCSendTransfer(**send_transfer_args)

        with self._lock:
            self.manager.transfers[transfer_id] = send_transfer

        self.manager.client_logic.send_ctcp_privmsg(peer_nick, ctcp_message)

        if passive:
            send_transfer._report_status(DCCTransferStatus.NEGOTIATING, f"Passive offer sent. Waiting for peer to ACCEPT with token.{status_message_suffix}")
        else: # Active
            send_transfer._report_status(DCCTransferStatus.NEGOTIATING, f"Waiting for peer to connect.{status_message_suffix}")
            send_transfer.start_transfer_thread()

        self.manager.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", {
            "transfer_id": transfer_id, "type": "SEND", "nick": peer_nick,
            "filename": original_filename, "size": filesize, "is_passive": passive
        })
        self.manager.client_logic.add_message(f"DCC SEND to {peer_nick} for '{original_filename}' ({filesize} bytes) initiated{status_message_suffix}", "system", context_name="DCC")
        return {"success": True, "transfer_id": transfer_id, "token": passive_token if passive else None, "filename": original_filename}

    def process_next_in_queue(self, peer_nick: str):
        file_to_send_info: Optional[Dict[str, Any]] = None
        with self._lock:
            if peer_nick in self.send_queues and self.send_queues[peer_nick]:
                file_to_send_info = self.send_queues[peer_nick].popleft()
                if not self.send_queues[peer_nick]:
                    del self.send_queues[peer_nick]
                self.dcc_event_logger.info(f"Dequeued '{file_to_send_info['original_filename'] if file_to_send_info else 'N/A'}' for sending to {peer_nick}. Remaining queue size: {len(self.send_queues.get(peer_nick, []))}")
            else:
                self.dcc_event_logger.debug(f"No more files in send queue for {peer_nick}.")

        if file_to_send_info:
            self.manager.client_logic.add_message(f"Starting next queued DCC SEND of '{file_to_send_info['original_filename']}' to {peer_nick}.", "system", context_name="DCC")
            self.dcc_event_logger.info(f"Processing next from queue for {peer_nick}: '{file_to_send_info['original_filename']}'")
            self._execute_send_operation(
                peer_nick,
                file_to_send_info["local_filepath"],
                file_to_send_info["original_filename"],
                file_to_send_info["filesize"],
                file_to_send_info["passive"]
            )
