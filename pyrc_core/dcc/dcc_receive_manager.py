# pyrc_core/dcc/dcc_receive_manager.py
import asyncio
import logging
import os
import socket
import struct # Added for struct.pack
from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING, List
from pyrc_core.dcc.dcc_manager import DCCManager
from pyrc_core.dcc.dcc_transfer import DCCStatus, DCCTransfer, DCCTransferType # Moved import to top
from pyrc_core.dcc.dcc_utils import get_available_port, get_local_ip_for_connection, parse_dcc_address_and_port, get_safe_dcc_path, get_listening_socket, get_local_ip_for_ctcp
from pyrc_core.app_config import AppConfig, DccConfig

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    from pyrc_core.event_manager import EventManager

logger = logging.getLogger("pyrc.dcc.receive_manager")

class DCCReceiveManager:
    def __init__(self, client_logic: 'IRCClient_Logic', event_manager: 'EventManager', config: AppConfig):
        self.client_logic = client_logic
        self.event_manager = event_manager
        self.config = config
        self.dcc_config: DccConfig = config.dcc # Reference to the DccConfig object
        self.active_receives: Dict[str, DCCTransfer] = {}  # Key: f"{sender_nick}-{filename}"
        self.listen_sockets: Dict[int, asyncio.Server] = {} # Key: port
        self.pending_transfers: Dict[str, Any] = {} # Key: f"{sender_nick}-{filename}-{size}-{timestamp}"
        self.event_manager.script_manager.subscribe_script_to_event("INCOMING_DCC_SEND_OFFER", self._handle_incoming_dcc_send_offer, "dcc_receive_manager")

    def shutdown(self):
        """Clean up active DCC receive transfers and close listening sockets."""
        logger.info("DCCReceiveManager shutting down.")
        for transfer_id, transfer in list(self.active_receives.items()):
            if transfer.status == DCCStatus.IN_PROGRESS:
                logger.info(f"Cancelling in-progress DCC receive: {transfer.filename} from {transfer.peer_nick}")
                transfer.set_status(DCCStatus.CANCELLED, "DCC Manager shutting down")
                # TODO: Ensure associated tasks are cancelled
        self.active_receives.clear()

        for port, server in list(self.listen_sockets.items()):
            logger.info(f"Closing DCC listening socket on port {port}")
            server.close()
            # await server.wait_closed() # Cannot await in sync shutdown method
            del self.listen_sockets[port]
        self.listen_sockets.clear()
        logger.info("DCCReceiveManager shutdown complete.")

    async def _handle_incoming_dcc_send_offer(self, event_data: Dict[str, Any]):
        """Handles the INCOMING_DCC_SEND_OFFER event."""
        nick = event_data.get("nick")
        full_userhost = event_data.get("full_userhost")
        dcc_info = event_data.get("dcc_info")

        if not nick or not full_userhost or not dcc_info:
            logger.error(f"Invalid event data for INCOMING_DCC_SEND_OFFER: {event_data}")
            return

        filename = dcc_info.get("filename")
        file_size = dcc_info.get("size")
        if not filename or not file_size:
            logger.error(f"Missing filename or file_size in DCC info: {dcc_info}")
            return

        new_transfer_id = self.client_logic.dcc_manager. _generate_transfer_id()

        # Use get_safe_dcc_path instead of sanitize_filename
        local_filepath = get_safe_dcc_path(self.dcc_config.download_dir, filename)
        if local_filepath is None:
            error_msg = f"Could not create safe local filepath for '{filename}'. Aborting passive offer acceptance."
            logger.error(error_msg)
            return

        incoming_transfer = DCCTransfer(
            transfer_id=new_transfer_id,
            transfer_type=DCCTransferType.RECEIVE,
            peer_nick=nick,
            filename=filename,
            file_size=file_size,
            local_filepath=local_filepath,
            dcc_manager_ref=self.client_logic.dcc_manager,
            peer_ip=full_userhost.split('@')[1] if full_userhost else None, # Set later when the connection is established
            dcc_event_logger=logger, # Use the receive manager's logger
            peer_port=dcc_info.get("port"),
        )

        # Add to overall transfers list
        self.client_logic.dcc_manager.transfers[new_transfer_id] = incoming_transfer

        # Delegate offer acceptance to DCCReceiveManager
        self.add_pending_dcc_offer(incoming_transfer)

        logger.info(f"DCCReceiveManager: Incoming DCC SEND offer from {nick} for '{filename}'. Transfer ID: {new_transfer_id[:8]}")

    async def start_listening_socket(self, transfer: DCCTransfer) -> Optional[asyncio.Server]:
        """
        Starts a listening socket for an incoming DCC transfer.
        Returns the asyncio.Server object if successful, None otherwise.
        """
        if not self.dcc_config.enabled: # Access directly from self.dcc_config
            logger.warning("DCC is disabled in config, cannot start listening socket.")
            return None

        if transfer.transfer_type != DCCTransferType.RECEIVE:
            logger.error(f"Attempted to start listening socket for non-receive transfer type: {transfer.transfer_type}")
            return None

        # Determine the local IP to advertise. Prioritize external, then local for target.
        # Fallback to 0.0.0.0 for binding, but advertise a specific IP if possible.
        listen_ip = '0.0.0.0'
        advertised_ip = get_local_ip_for_connection(transfer.peer_ip) if transfer.peer_ip else None # Handle Optional[str]

        if not advertised_ip:
            logger.warning(f"Could not determine local IP for peer {transfer.peer_ip}, cannot establish DCC connection.")
            return None

        if self.dcc_config.advertised_ip: # Access directly from self.dcc_config
            listen_ip = self.dcc_config.advertised_ip # Use advertised IP for binding if specified
            logger.debug(f"Using configured bind_ip: {listen_ip}")
        else:
            logger.debug(f"Binding to {listen_ip} (all interfaces).")

        # Find an available port
        start_port = self.dcc_config.port_range_start # Access directly from self.dcc_config
        end_port = self.dcc_config.port_range_end # Access directly from self.dcc_config
        if start_port is None or end_port is None: # These should always have defaults set in AppConfig
            logger.error("DCC port range not configured.")
            await self.client_logic.add_message(
                "DCC Error: Port range not configured in app_config.ini. Cannot receive.",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return None

        port = get_available_port(start_port, end_port)
        if port is None:
            logger.error(f"No available ports in range {start_port}-{end_port} for DCC receive.")
            await self.client_logic.add_message(
                f"DCC Error: No available ports in {start_port}-{end_port}. Cannot receive.",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return None

        try:
            # Create a listening socket
            # For DCC, we typically listen on 0.0.0.0 (all interfaces) or a specific bind_ip
            # and then tell the sender which IP/port to connect to.
            server = await asyncio.start_server(
                lambda r, w: self._handle_incoming_dcc_connection(r, w, transfer),
                host=listen_ip,
                port=port,
                family=socket.AF_INET # DCC typically uses IPv4
            )
            self.listen_sockets[port] = server
            transfer.local_port = port
            transfer.local_ip = advertised_ip # This is the IP we tell the sender to connect to
            logger.info(f"DCC listening on {listen_ip}:{port}, advertising {advertised_ip}:{port}")
            return server
        except OSError as e:
            logger.error(f"Failed to start DCC listening socket on {listen_ip}:{port}: {e}")
            await self.client_logic.add_message(
                f"DCC Error: Failed to listen on port {port}. {e}",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return None
        except Exception as e:
            logger.critical(f"Unhandled error starting DCC listening socket: {e}", exc_info=True)
            await self.client_logic.add_message(
                f"DCC Error: Unhandled error starting listener. {e}",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return None

    async def _handle_incoming_dcc_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, transfer: DCCTransfer):
        """Handles an incoming DCC connection for a pending transfer."""
        peername = writer.get_extra_info('peername')
        logger.info(f"Incoming DCC connection from {peername} for transfer {transfer.filename}")

        if transfer.status != DCCStatus.PENDING_ACCEPT: # Changed from WAITING_FOR_ACCEPT to PENDING_ACCEPT based on DCC flow
            logger.warning(f"Rejecting unexpected DCC connection for transfer in status {transfer.status}: {transfer.filename}")
            writer.close()
            await writer.wait_closed()
            return

        transfer.set_status(DCCStatus.IN_PROGRESS, "Connection established")
        transfer.reader = reader
        transfer.writer = writer
        self.active_receives[transfer.id] = transfer # Move from pending to active

        # Close the listening socket once a connection is accepted for this transfer
        if transfer.local_port and transfer.local_port in self.listen_sockets:
            server = self.listen_sockets.pop(transfer.local_port)
            server.close()
            await server.wait_closed()
            logger.info(f"Closed listening socket on port {transfer.local_port} for {transfer.filename}")

        await self.event_manager.dispatch_dcc_transfer_status_change(transfer)
        await self.client_logic.add_message(
            f"DCC Receive: Connection established for '{transfer.filename}' from {transfer.peer_nick}.",
            self.client_logic.ui.colors["info"], context_name="DCC"
        )
        # Start the actual file transfer
        asyncio.create_task(self._receive_file_data(transfer, append=False)) # Initial receive starts fresh

    async def _receive_file_data(self, transfer: DCCTransfer, append: bool = False):
        """Receives file data for an active DCC transfer, with option to append."""
        file_path = get_safe_dcc_path(self.dcc_config.download_dir, transfer.filename)
        if not file_path:
            error_msg = f"Invalid or unsafe DCC download path for '{transfer.filename}'."
            logger.error(error_msg)
            transfer.set_status(DCCStatus.FAILED, error_msg)
            await self.client_logic.add_message(
                f"DCC Receive Error: {error_msg}",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            if transfer.writer:
                transfer.writer.close()
                await transfer.writer.wait_closed()
            return

        mode = 'ab' if append else 'wb'
        bytes_received = transfer.bytes_transferred if append else 0 # Start from current position if appending
        logger.info(f"Receiving file data for '{transfer.filename}', mode: '{mode}', initial bytes: {bytes_received}")

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        try:
            with open(file_path, mode) as f:
                # If appending, seek to the end of the file to ensure we write from the correct position
                if append:
                    f.seek(0, os.SEEK_END)
                    # Verify the file size matches the resume position
                    current_file_size = f.tell()
                    if current_file_size != transfer.bytes_transferred:
                        error_msg = f"Resume error for '{transfer.filename}': Local file size ({current_file_size}) does not match resume position ({transfer.bytes_transferred})."
                        logger.error(error_msg)
                        transfer.set_status(DCCStatus.FAILED, error_msg)
                        await self.client_logic.add_message(
                            f"DCC Receive Error: {error_msg}",
                            self.client_logic.ui.colors["error"], context_name="DCC"
                        )
                        return # Exit the function, transfer failed

                while bytes_received < transfer.file_size and transfer.status == DCCStatus.IN_PROGRESS:
                    if transfer.reader is None:
                        logger.error(f"[{transfer.id}] Reader is None during receive operation.")
                        transfer.set_status(DCCStatus.FAILED, "Internal error: reader not available.")
                        break

                    data = await transfer.reader.read(4096)
                    if not data:
                        # Sender closed connection prematurely
                        error_msg = f"Sender closed connection unexpectedly for '{transfer.filename}'."
                        logger.warning(error_msg)
                        transfer.set_status(DCCStatus.FAILED, error_msg)
                        break
                    f.write(data)
                    bytes_received += len(data)
                    transfer.bytes_transferred = bytes_received
                    # Acknowledge received bytes (important for flow control)
                    ack_data = struct.pack('!I', bytes_received)
                    if transfer.writer is None:
                        logger.warning(f"[{transfer.id}] Writer is None, cannot send ACK.")
                    else:
                        transfer.writer.write(ack_data)
                        await transfer.writer.drain()

                    # Update UI periodically (e.g., every 1MB or 10% progress)
                    if self.client_logic and not self.client_logic.is_headless:
                        # This should be a less frequent update to avoid UI thrashing
                        pass # UI updates handled by DCCManager/UIManager

            if bytes_received >= transfer.file_size:
                transfer.set_status(DCCStatus.COMPLETED, "File received successfully")
                logger.info(f"DCC Receive: Successfully received '{transfer.filename}'.")
                await self.client_logic.add_message(
                    f"DCC Receive: Successfully received '{transfer.filename}' from {transfer.peer_nick}.",
                    self.client_logic.ui.colors["info"], context_name="DCC"
                )
            else:
                error_msg = f"DCC Receive: Transfer of '{transfer.filename}' incomplete. Expected {transfer.file_size}, got {bytes_received}."
                logger.warning(error_msg)
                transfer.set_status(DCCStatus.FAILED, error_msg)
                await self.client_logic.add_message(
                    f"DCC Receive Error: {error_msg}",
                    self.client_logic.ui.colors["error"], context_name="DCC"
                )

        except asyncio.CancelledError:
            logger.info(f"DCC receive of '{transfer.filename}' cancelled.")
            transfer.set_status(DCCStatus.CANCELLED, "Transfer cancelled")
            await self.client_logic.add_message(
                f"DCC Receive: Transfer of '{transfer.filename}' cancelled.",
                self.client_logic.ui.colors["warning"], context_name="DCC"
            )
        except Exception as e:
            error_msg = f"Error during DCC receive of '{transfer.filename}': {e}"
            logger.error(error_msg, exc_info=True)
            transfer.set_status(DCCStatus.FAILED, error_msg)
            await self.client_logic.add_message(
                f"DCC Receive Error: {error_msg}",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
        finally:
            if transfer.writer:
                transfer.writer.close()
                await transfer.writer.wait_closed()
            if transfer.id in self.active_receives:
                del self.active_receives[transfer.id]
            await self.event_manager.dispatch_dcc_transfer_status_change(transfer)

    async def accept_dcc_offer(self, transfer_id: str) -> bool:
        """
        Accepts a pending DCC offer by its ID.
        """
        transfer = self.pending_transfers.pop(transfer_id, None)
        if not transfer:
            logger.warning(f"Attempted to accept unknown or expired DCC offer: {transfer_id}")
            await self.client_logic.add_message(
                f"DCC Error: No pending offer found for ID '{transfer_id}'. It might have expired or been accepted/rejected.",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return False

        if transfer.transfer_type != DCCTransferType.RECEIVE or transfer.status != DCCStatus.PENDING_ACCEPT:
            logger.warning(f"DCC offer {transfer_id} is not in a receivable state (type: {transfer.transfer_type}, status: {transfer.status}).")
            await self.client_logic.add_message(
                f"DCC Error: Offer '{transfer_id}' not in receivable state.",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return False

        logger.info(f"Accepting DCC offer for '{transfer.filename}' from {transfer.peer_nick} (ID: {transfer_id}).")
        transfer.set_status(DCCStatus.CONNECTING, "Accepted, waiting for connection") # Changed status to CONNECTING
        await self.event_manager.dispatch_dcc_transfer_status_change(transfer)

        # Start listening for the incoming connection
        listening_server = await self.start_listening_socket(transfer)
        if not listening_server:
            transfer.set_status(DCCStatus.FAILED, "Could not start listening socket")
            await self.event_manager.dispatch_dcc_transfer_status_change(transfer)
            return False

        # Send DCC ACCEPT CTCP
        # Format: DCC ACCEPT <filename> <port> <bytes_acked_so_far>
        # For a new receive, bytes_acked_so_far is 0.
        # The local_ip and local_port fields should be set by start_listening_socket
        if transfer.local_ip and transfer.local_port:
            formatted_ip = transfer.local_ip # No need to pack, just send as string
            ctcp_accept_msg = (
                f"DCC ACCEPT {transfer.filename} {transfer.local_port} 0"
            )
            logger.debug(f"Sending DCC ACCEPT: {ctcp_accept_msg}")
            await self.client_logic.send_ctcp_privmsg(transfer.peer_nick, ctcp_accept_msg)
            return True
        else:
            error_msg = "Internal Error: Local IP or Port not set after starting listening socket."
            logger.error(error_msg)
            transfer.set_status(DCCStatus.FAILED, error_msg)
            await self.event_manager.dispatch_dcc_transfer_status_change(transfer)
            await self.client_logic.add_message(
                f"DCC Error: {error_msg}",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return False

    def add_pending_dcc_offer(self, transfer: DCCTransfer):
        """Adds a DCC offer to the list of pending transfers."""
        if transfer.transfer_type != DCCTransferType.RECEIVE:
            logger.error(f"Attempted to add non-receive transfer as pending offer: {transfer.transfer_type}")
            return

        transfer.set_status(DCCStatus.PENDING_ACCEPT, "Offer received, waiting for user acceptance")
        self.pending_transfers[transfer.id] = transfer
        logger.info(f"Added pending DCC offer: {transfer.filename} from {transfer.peer_nick} (ID: {transfer.id})")
        # Notify UI/user of pending offer
        asyncio.create_task(self.client_logic.add_message(
            f"DCC Offer: '{transfer.filename}' ({transfer.file_size} bytes) from {transfer.peer_nick}. Type '/dcc accept {transfer.id}' to accept.",
            self.client_logic.ui.colors["info"], context_name="DCC"
        ))
        asyncio.create_task(self.event_manager.dispatch_dcc_transfer_status_change(transfer))

    def get_transfer_by_id(self, transfer_id: str) -> Optional[DCCTransfer]:
        """Retrieves a DCC transfer by its ID from either pending or active lists."""
        return self.pending_transfers.get(transfer_id) or self.active_receives.get(transfer_id)

    def get_all_transfers(self) -> List[DCCTransfer]:
        """Returns a list of all pending and active DCC transfers."""
        return list(self.pending_transfers.values()) + list(self.active_receives.values())
    def get_transfer_id_by_args(self, nick: str, filename: str, ip: str, port: int, filesize: int) -> Optional[str]:
        """
        Retrieves the transfer ID based on the provided arguments.
        """
        for transfer_id, transfer in self.pending_transfers.items():
            if (
                transfer.peer_nick == nick
                and transfer.filename == filename
                and transfer.peer_ip == ip
                and transfer.peer_port == port
                and transfer.file_size == filesize
            ):
                return transfer_id

        for transfer_id, transfer in self.active_receives.items():
            if (
                transfer.peer_nick == nick
                and transfer.filename == filename
                and transfer.peer_ip == ip
                and transfer.peer_port == port
                and transfer.file_size == filesize
            ):
                return transfer_id

        return None

    async def accept_dcc_resume_offer(self, transfer_id: str) -> bool:
        """
        Accepts a pending DCC RESUME offer by its ID.
        This will initiate a connection to the peer and resume the file transfer.
        """
        transfer = self.pending_transfers.pop(transfer_id, None)
        if not transfer:
            logger.warning(f"Attempted to accept unknown or expired DCC RESUME offer: {transfer_id}")
            await self.client_logic.add_message(
                f"DCC Error: No pending resume offer found for ID '{transfer_id}'. It might have expired or been accepted/rejected.",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return False

        if transfer.transfer_type != DCCTransferType.RECEIVE or transfer.status != DCCStatus.PENDING_RESUME:
            logger.warning(f"DCC resume offer {transfer_id} is not in a resumable state (type: {transfer.transfer_type}, status: {transfer.status}).")
            await self.client_logic.add_message(
                f"DCC Error: Resume offer '{transfer_id}' not in resumable state.",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return False

        logger.info(f"Accepting DCC RESUME offer for '{transfer.filename}' from {transfer.peer_nick} (ID: {transfer.id}).")
        transfer.set_status(DCCStatus.CONNECTING, "Accepted resume, connecting to peer")
        await self.event_manager.dispatch_dcc_transfer_status_change(transfer)

        # Connect to the peer's advertised IP and port
        if not transfer.peer_ip or not transfer.peer_port:
            error_msg = f"Internal Error: Peer IP or Port not set for resume transfer {transfer_id}."
            logger.error(error_msg)
            transfer.set_status(DCCStatus.FAILED, error_msg)
            await self.event_manager.dispatch_dcc_transfer_status_change(transfer)
            await self.client_logic.add_message(
                f"DCC Error: {error_msg}",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return False

        try:
            reader, writer = await asyncio.open_connection(transfer.peer_ip, transfer.peer_port)
            transfer.reader = reader
            transfer.writer = writer
            transfer.set_status(DCCStatus.IN_PROGRESS, "Connection established, resuming transfer")
            self.active_receives[transfer.id] = transfer  # Move from pending to active

            await self.event_manager.dispatch_dcc_transfer_status_change(transfer)
            await self.client_logic.add_message(
                f"DCC Receive: Connection established for resume of '{transfer.filename}' from {transfer.peer_nick}.",
                self.client_logic.ui.colors["info"], context_name="DCC"
            )
            # Start receiving file data, indicating it's a resume operation
            asyncio.create_task(self._receive_file_data(transfer, append=True))
            return True
        except OSError as e:
            error_msg = f"Failed to connect to peer for DCC RESUME on {transfer.peer_ip}:{transfer.peer_port}: {e}"
            logger.error(error_msg)
            transfer.set_status(DCCStatus.FAILED, error_msg)
            await self.client_logic.add_message(
                f"DCC Error: {error_msg}",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return False
        except Exception as e:
            error_msg = f"Unhandled error during DCC RESUME connection for {transfer.filename}: {e}"
            logger.critical(error_msg, exc_info=True)
            transfer.set_status(DCCStatus.FAILED, error_msg)
            await self.client_logic.add_message(
                f"DCC Error: {error_msg}",
                self.client_logic.ui.colors["error"], context_name="DCC"
            )
            return False
