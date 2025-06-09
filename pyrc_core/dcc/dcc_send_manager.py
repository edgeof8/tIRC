import logging
import os
import uuid
import socket
from collections import deque
from typing import Dict, Optional, Any, List, Deque, TYPE_CHECKING

from pyrc_core.dcc.dcc_transfer import DCCSendTransfer, DCCStatus # Changed DCCTransferStatus to DCCStatus
import asyncio # Added for async operations
from pyrc_core.dcc.dcc_protocol import format_dcc_send_ctcp, format_dcc_resume_ctcp
from pyrc_core.dcc.dcc_utils import get_listening_socket, get_local_ip_for_ctcp # NEW: Import utility functions

if TYPE_CHECKING:
    from pyrc_core.dcc.dcc_manager import DCCManager

logger = logging.getLogger("pyrc.dcc.sendmanager") # Specific logger for this manager

class DCCSendManager:
    def __init__(self, manager_ref: 'DCCManager'):
        self.manager = manager_ref
        self.dcc_event_logger = manager_ref.dcc_event_logger # Use manager's event logger
        self._lock = manager_ref._lock
        self.send_queues: Dict[str, Deque[Dict[str, Any]]] = {}

    async def _handle_incoming_dcc_resume_offer(self, event_data: Dict[str, Any]):
        """Handles the INCOMING_DCC_RESUME_OFFER event."""
        nick = event_data.get("nick")
        full_userhost = event_data.get("full_userhost")
        dcc_info = event_data.get("dcc_info")

        if not nick or not full_userhost or not dcc_info:
            logger.error(f"Invalid event data for INCOMING_DCC_RESUME_OFFER: {event_data}")
            return

        filename = dcc_info.get("filename")
        port = dcc_info.get("port")
        offset = dcc_info.get("position") # Standardized var name to avoid confusion
        if not filename or not port or not offset:
            logger.error(f"Missing filename, port, or offset in DCC RESUME info: {dcc_info}")
            return

        # Locate the existing transfer
        transfer: Optional[DCCSendTransfer] = None
        with self._lock:
            for t_id, t in self.manager.transfers.items():
                if (isinstance(t, DCCSendTransfer) and t.peer_nick == nick and t.filename == filename and t.status in [DCCStatus.FAILED, DCCStatus.CANCELLED, DCCStatus.TIMED_OUT]):
                    transfer = t
                    break

        if not transfer:
            logger.warning(f"No matching transfer found for DCC RESUME offer from {nick} for '{filename}'.")
            return

        # Resume the transfer
        transfer.resume_offset = offset
        if transfer and full_userhost and nick and filename and offset and port:
            transfer.peer_ip = full_userhost.split('@')[1] # Parse IP from userhost
            asyncio.create_task(self.resume_send_transfer(transfer, port)) # Resume the send
            logger.info(f"DCCSendManager: Resuming DCC SEND to {nick} for '{filename}' from offset {offset} on port {port}.")

    async def initiate_sends(self, peer_nick: str, local_filepaths: List[str], passive: bool = False) -> Dict[str, Any]:
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
            if filesize > self.manager.dcc_config.max_file_size:
                err_msg = f"File '{original_filename}' exceeds maximum size of {self.manager.dcc_config.max_file_size} bytes."
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
                t.status not in [DCCStatus.COMPLETED, DCCStatus.FAILED, DCCStatus.CANCELLED, DCCStatus.TIMED_OUT] # Changed DCCTransferStatus to DCCStatus
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
                    await self.manager.client_logic.add_message(f"Queued DCC SEND of '{file_info['original_filename']}' to {peer_nick}.", self.manager.client_logic.ui.colors["system"], context_name="DCC")
            else:
                self.dcc_event_logger.info(f"No active send or queue for {peer_nick}. Starting first file and queuing rest.")
                first_file_info = validated_files_to_process.pop(0)
                # Schedule the first send operation as an asyncio task
                exec_result = await self._execute_send_operation( # Made this awaitable
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
                        await self.manager.client_logic.add_message(f"Queued DCC SEND of '{file_info['original_filename']}' to {peer_nick} (after starting first).", self.manager.client_logic.ui.colors["system"], context_name="DCC")

        if not results["transfers_started"] and not results["files_queued"] and not results["errors"]:
            results["error"] = "No files processed."
            results["overall_success"] = False
        return results

    async def _execute_send_operation(self, peer_nick: str, local_filepath: str, original_filename: str, filesize: int, passive: bool = False) -> Dict[str, Any]: # Made async
        self.dcc_event_logger.info(f"SendManager: Executing DCC SEND: Peer={peer_nick}, File='{original_filename}', Size={filesize}, Passive={passive}, Path='{local_filepath}'")
        abs_local_filepath = os.path.abspath(local_filepath)

        if self.manager.dcc_config.resume_enabled and not passive:
            with self._lock:
                for tid, old_transfer in list(self.manager.transfers.items()):
                    if (isinstance(old_transfer, DCCSendTransfer) and
                        old_transfer.peer_nick == peer_nick and
                        old_transfer.filename == original_filename and
                        old_transfer.status in [DCCStatus.FAILED, DCCStatus.CANCELLED, DCCStatus.TIMED_OUT] and
                        old_transfer.bytes_transferred > 0 and
                        old_transfer.bytes_transferred < old_transfer.file_size):
                        resume_offset = old_transfer.bytes_transferred
                        self.dcc_event_logger.info(f"Found previous incomplete send of '{original_filename}' to {peer_nick} at offset {resume_offset}. Offering RESUME.")

                        # Initiate listening socket for resume
                        try:
                            listening_server = await asyncio.start_server(
                                lambda r, w: self._handle_outgoing_dcc_connection(r, w, old_transfer),
                                host='0.0.0.0',  # Listen on all interfaces
                                port=0,  # Let OS pick an available port
                                family=socket.AF_INET
                            )
                            port_resume = listening_server.sockets[0].getsockname()[1]
                            old_transfer.local_port = port_resume
                            local_ip = self.manager.dcc_config.advertised_ip
                            if local_ip is not None:
                                old_transfer.local_ip = get_local_ip_for_ctcp(local_ip)  # Use manager's config
                            else:
                                self.dcc_event_logger.error(f"dcc_advertised_ip is not set in config. Cannot resume DCC.")
                                break
                            if not hasattr(self.manager, "send_listening_servers"):
                                self.manager.send_listening_servers = {}
                            self.manager.send_listening_servers[old_transfer.id] = listening_server  # Store server for this transfer
                        except Exception as e:
                            self.dcc_event_logger.error(f"Could not get listening socket for DCC RESUME of '{original_filename}' to {peer_nick}: {e}", exc_info=True)
                            break  # Skip this resume attempt

                        ctcp_resume_message = format_dcc_resume_ctcp(original_filename, port_resume, resume_offset)
                        if not ctcp_resume_message:
                            listening_server.close()
                            await listening_server.wait_closed()
                            self.dcc_event_logger.error(f"Failed to format DCC RESUME CTCP for '{original_filename}'.")
                            break

                        # Update existing transfer's status
                        old_transfer.set_status(DCCStatus.NEGOTIATING, f"DCC RESUME offered. Waiting for {peer_nick} to connect on port {port_resume} for '{original_filename}' from offset {resume_offset}.")

                        # Send CTCP message
                        await self.manager.client_logic.send_ctcp_privmsg(peer_nick, ctcp_resume_message)

                        await self.manager.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", {
                            "transfer_id": old_transfer.id, "type": "SEND_RESUME", "nick": peer_nick,  # Changed transfer_id to id
                            "filename": original_filename, "size": filesize, "resume_offset": resume_offset
                        })
                        await self.manager.client_logic.add_message(f"Offering to RESUME DCC SEND to {peer_nick} for '{original_filename}' from offset {resume_offset}. Waiting for peer on port {port_resume}.", self.manager.client_logic.ui.colors["system"], context_name="DCC")
                        return {"success": True, "transfer_id": old_transfer.id, "filename": original_filename, "resumed": True}  # Changed transfer_id to id

        transfer_id = self.manager._generate_transfer_id()
        self.dcc_event_logger.debug(f"Generated Transfer ID: {transfer_id} for SEND to {peer_nick} of '{original_filename}'")
        passive_token: Optional[str] = None
        ctcp_message: Optional[str] = None
        send_transfer_args: Dict[str, Any] = {
            "transfer_id": transfer_id, "peer_nick": peer_nick,
            "filename": original_filename, "file_size": filesize, # Changed filesize to file_size
            "local_filepath": abs_local_filepath, "dcc_manager_ref": self.manager,
        }
        status_message_suffix = ""

        if passive:
            passive_token = self.manager._generate_transfer_id()
            local_ip = self.manager.dcc_config.advertised_ip
            if local_ip is not None:
                local_ip_for_ctcp = get_local_ip_for_ctcp(local_ip)  # Use manager's config
            else:
                self.dcc_event_logger.error(f"dcc_advertised_ip is not set in config. Cannot send DCC in passive mode.")
                return {"success": False, "error": f"dcc_advertised_ip is not set in config. Cannot send DCC in passive mode."}
            ctcp_message = format_dcc_send_ctcp(original_filename, local_ip_for_ctcp, 0, filesize, passive_token)
            send_transfer_args["is_passive_offer"] = True
            send_transfer_args["passive_token"] = passive_token
            status_message_suffix = f" (Passive Offer, token: {passive_token[:8]})"
            if not ctcp_message:
                self.dcc_event_logger.error(f"Failed to format passive DCC SEND CTCP for '{original_filename}' to {peer_nick}.")
                return {"success": False, "error": "Failed to format passive DCC SEND CTCP message."}
            self.dcc_event_logger.debug(f"Passive SEND to {peer_nick} for '{original_filename}'. CTCP: {ctcp_message.strip()}")
        else:  # Active DCC
            # For active DCC, we start a listening server and wait for the peer to connect
            try:
                listening_server = await asyncio.start_server(
                    lambda r, w: self._handle_outgoing_dcc_connection(r, w, send_transfer),  # Pass the transfer object
                    host='0.0.0.0',  # Listen on all interfaces
                    port=0,  # Let OS pick an available port
                    family=socket.AF_INET
                )
                port = listening_server.sockets[0].getsockname()[1]
                local_ip = self.manager.dcc_config.advertised_ip
                if local_ip is not None:
                    local_ip_for_ctcp = get_local_ip_for_ctcp(local_ip)  # Use manager's config
                else:
                    self.dcc_event_logger.error(f"dcc_advertised_ip is not set in config. Cannot send DCC in active mode.")
                    return {"success": False, "error": f"dcc_advertised_ip is not set in config. Cannot send DCC in active mode."}

                ctcp_message = format_dcc_send_ctcp(original_filename, local_ip_for_ctcp, port, filesize)
                send_transfer_args["local_port"] = port  # Store the port we are listening on
                send_transfer_args["local_ip"] = local_ip_for_ctcp  # Store the IP we are advertising
                if not hasattr(self.manager, "send_listening_servers"):
                    self.manager.send_listening_servers = {}
                self.manager.send_listening_servers[transfer_id] = listening_server  # Store the server
                status_message_suffix = f". Waiting for connection on port {port}."
            except Exception as e:
                self.dcc_event_logger.error(f"Could not start listening socket for active SEND of '{original_filename}' to {peer_nick}: {e}", exc_info=True)
                return {"success": False, "error": f"Could not create listening socket for active DCC SEND: {e}"}

            if not ctcp_message:
                listening_server.close()
                await listening_server.wait_closed()
                self.dcc_event_logger.error(f"Failed to format active DCC SEND CTCP for '{original_filename}' to {peer_nick}.")
                return {"success": False, "error": "Failed to format active DCC SEND CTCP message."}
            self.dcc_event_logger.debug(f"Active SEND to {peer_nick} for '{original_filename}'. CTCP: {ctcp_message.strip()}")

        send_transfer_args["dcc_event_logger"] = self.dcc_event_logger
        send_transfer = DCCSendTransfer(**send_transfer_args)

        with self._lock:
            self.manager.transfers[transfer_id] = send_transfer

        await self.manager.client_logic.send_ctcp_privmsg(peer_nick, ctcp_message)

        if passive:
            send_transfer.set_status(DCCStatus.NEGOTIATING, f"Passive offer sent. Waiting for peer to ACCEPT with token.{status_message_suffix}") # Changed _report_status to set_status, DCCTransferStatus to DCCStatus
        else: # Active
            send_transfer.set_status(DCCStatus.NEGOTIATING, f"Waiting for peer to connect.{status_message_suffix}") # Changed _report_status to set_status, DCCTransferStatus to DCCStatus
            # No start_transfer_thread here, connection will be handled by _handle_outgoing_dcc_connection

        await self.manager.event_manager.dispatch_event("DCC_TRANSFER_QUEUED", {
            "transfer_id": transfer_id, "type": "SEND", "nick": peer_nick,
            "filename": original_filename, "size": filesize, "is_passive": passive
        })
        await self.manager.client_logic.add_message(f"DCC SEND to {peer_nick} for '{original_filename}' ({filesize} bytes) initiated{status_message_suffix}", self.manager.client_logic.ui.colors["system"], context_name="DCC")
        return {"success": True, "transfer_id": transfer_id, "token": passive_token if passive else None, "filename": original_filename}

    async def process_next_in_queue(self, peer_nick: str): # Made async
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
            await self.manager.client_logic.add_message(f"Starting next queued DCC SEND of '{file_to_send_info['original_filename']}' to {peer_nick}.", self.manager.client_logic.ui.colors["system"], context_name="DCC")
            self.dcc_event_logger.info(f"Processing next from queue for {peer_nick}: '{file_to_send_info['original_filename']}'")
            await self._execute_send_operation( # Await the async method
                peer_nick,
                file_to_send_info["local_filepath"],
                file_to_send_info["original_filename"],
                file_to_send_info["filesize"],
                file_to_send_info["passive"]
            )

    async def _handle_outgoing_dcc_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, transfer: DCCSendTransfer):
        """Handles an outgoing DCC connection (peer connecting to our listening socket for a SEND)."""
        peername = writer.get_extra_info('peername')
        self.dcc_event_logger.info(f"Incoming connection from {peername} for outgoing transfer {transfer.id} ('{transfer.filename}')")

        # Check if this connection matches a pending active or resumed send transfer
        if transfer.status not in [DCCStatus.NEGOTIATING, DCCStatus.CONNECTING]:
            self.dcc_event_logger.warning(f"Rejecting unexpected incoming DCC connection for transfer in status {transfer.status}: {transfer.id}")
            writer.close()
            await writer.wait_closed()
            return

        transfer.reader = reader
        transfer.writer = writer
        transfer.set_status(DCCStatus.IN_PROGRESS, "Connection established")

        # Close the listening server once a connection is accepted for this transfer
        if hasattr(self.manager, "send_listening_servers") and transfer.id in self.manager.send_listening_servers:
            server = self.manager.send_listening_servers.pop(transfer.id)
            server.close()
            await server.wait_closed()
            self.dcc_event_logger.info(f"Closed listening server for transfer {transfer.id}.")

        await self.manager.event_manager.dispatch_dcc_transfer_status_change(transfer)
        await self.manager.client_logic.add_message(
            f"DCC Send: Connection established for '{transfer.filename}' to {transfer.peer_nick}.",
            self.manager.client_logic.ui.colors["info"], context_name="DCC"
        )
        asyncio.create_task(self._send_file_data(transfer))

    async def _send_file_data(self, transfer: DCCSendTransfer):
        """Sends file data for an active DCC transfer."""
        bytes_sent = transfer.resume_offset
        try:
            with open(transfer.local_filepath, 'rb') as f:
                if bytes_sent > 0:
                    f.seek(bytes_sent) # Seek to resume offset
                    self.dcc_event_logger.info(f"[{transfer.id}] Resuming send from offset {bytes_sent}.")

                while bytes_sent < transfer.file_size and transfer.status == DCCStatus.IN_PROGRESS:
                    if transfer.writer is None:
                        self.dcc_event_logger.error(f"[{transfer.id}] Writer is None during send operation.")
                        transfer.set_status(DCCStatus.FAILED, "Internal error: writer not available.")
                        break

                    chunk = f.read(4096)
                    if not chunk: # End of file
                        break

                    transfer._apply_throttle(len(chunk)) # Apply throttling before sending

                    transfer.writer.write(chunk)
                    await transfer.writer.drain()
                    bytes_sent += len(chunk)
                    transfer.bytes_transferred = bytes_sent

                    # Optionally wait for ACK, but DCC SEND typically doesn't wait for byte ACKs.
                    # If the peer sends a RESUME/ACK, it's handled by DCCCTCPHandler.

            if bytes_sent >= transfer.file_size:
                transfer.set_status(DCCStatus.COMPLETED, "File sent successfully")
                self.dcc_event_logger.info(f"DCC Send: Successfully sent '{transfer.filename}'.")
                await self.manager.client_logic.add_message(
                    f"DCC Send: Successfully sent '{transfer.filename}' to {transfer.peer_nick}.",
                    self.manager.client_logic.ui.colors["info"], context_name="DCC"
                )
            else:
                error_msg = f"DCC Send: Transfer of '{transfer.filename}' incomplete. Expected {transfer.file_size}, sent {bytes_sent}."
                self.dcc_event_logger.warning(error_msg)
                transfer.set_status(DCCStatus.FAILED, error_msg)
                await self.manager.client_logic.add_message(
                    f"DCC Send Error: {error_msg}",
                    self.manager.client_logic.ui.colors["error"], context_name="DCC"
                )

        except asyncio.CancelledError:
            self.dcc_event_logger.info(f"DCC send of '{transfer.filename}' cancelled.")
            transfer.set_status(DCCStatus.CANCELLED, "Transfer cancelled")
            await self.manager.client_logic.add_message(
                f"DCC Send: Transfer of '{transfer.filename}' cancelled.",
                self.manager.client_logic.ui.colors["warning"], context_name="DCC"
            )
        except Exception as e:
            error_msg = f"Error during DCC send of '{transfer.filename}': {e}"
            self.dcc_event_logger.error(error_msg, exc_info=True)
            transfer.set_status(DCCStatus.FAILED, error_msg)
            await self.manager.client_logic.add_message(
                f"DCC Send Error: {error_msg}",
                self.manager.client_logic.ui.colors["error"], context_name="DCC"
            )
        finally:
            if transfer.writer:
                transfer.writer.close()
                await transfer.writer.wait_closed()
            if transfer.id in self.manager.transfers:
                # This ensures the transfer is removed from active list, allowing next in queue to start
                # However, we keep it in self.manager.transfers for /dcc list and cleanup_old_transfers
                # self.manager.transfers.pop(transfer.id, None) # Don't remove here, let cleanup handle
                pass
            await self.manager.event_manager.dispatch_dcc_transfer_status_change(transfer)
            # After a send completes (or fails), try to process the next in queue for this peer
            await self.process_next_in_queue(transfer.peer_nick)

    async def start_send_transfer_from_accept(self, transfer: DCCSendTransfer):
        """
        Initiates the connection for a passive DCC SEND transfer after the peer
        has sent a DCC ACCEPT.
        """
        self.dcc_event_logger.info(f"Attempting to connect for passive send transfer {transfer.id} to {transfer.peer_ip}:{transfer.peer_port}")
        if not transfer.peer_ip or not transfer.peer_port:
            error_msg = f"Cannot connect for passive send {transfer.id}: Missing peer IP or port."
            self.dcc_event_logger.error(error_msg)
            transfer.set_status(DCCStatus.FAILED, error_msg)
            return

        try:
            reader, writer = await asyncio.open_connection(transfer.peer_ip, transfer.peer_port)
            self.dcc_event_logger.info(f"Successfully connected for passive send transfer {transfer.id} to {transfer.peer_ip}:{transfer.peer_port}")
            await self._handle_outgoing_dcc_connection(reader, writer, transfer)
        except Exception as e:
            error_msg = f"Failed to connect for passive send transfer {transfer.id} to {transfer.peer_ip}:{transfer.peer_port}: {e}"
            self.dcc_event_logger.error(error_msg, exc_info=True)
            transfer.set_status(DCCStatus.FAILED, error_msg)

    async def resume_send_transfer(self, transfer: DCCSendTransfer, accepted_port: int):
        """
        Resumes an outgoing DCC SEND transfer after the peer has sent a DCC ACCEPT for RESUME.
        """
        self.dcc_event_logger.info(f"Attempting to resume send transfer {transfer.id} to {transfer.peer_nick} on port {accepted_port} from offset {transfer.resume_offset}")
        if not transfer.peer_ip: # Peer IP should be known from original transfer
            error_msg = f"Cannot resume send {transfer.id}: Peer IP unknown."
            self.dcc_event_logger.error(error_msg)
            transfer.set_status(DCCStatus.FAILED, error_msg)
            return

        try:
            reader, writer = await asyncio.open_connection(transfer.peer_ip, accepted_port)
            self.dcc_event_logger.info(f"Successfully connected for resume send transfer {transfer.id} to {transfer.peer_ip}:{accepted_port}")
            await self._handle_outgoing_dcc_connection(reader, writer, transfer)
        except Exception as e:
            error_msg = f"Failed to connect for resume send transfer {transfer.id} to {transfer.peer_ip}:{accepted_port}: {e}"
            self.dcc_event_logger.error(error_msg, exc_info=True)
            transfer.set_status(DCCStatus.FAILED, error_msg)

    def shutdown(self):
        """
        Shuts down the DCCSendManager, stopping any pending transfers.
        """
        logger.info("Shutting down DCCSendManager...")
        self.is_shutting_down = True
        # Clear the queue to prevent new transfers from starting
        with self._lock:
            self.send_queues.clear()
        # Cancel any pending futures
        #for future in self.pending_futures: #TODO: Add pending futures
        #    if not future.done():
        #        future.cancel()
        logger.info("DCCSendManager shutdown initiated.")
