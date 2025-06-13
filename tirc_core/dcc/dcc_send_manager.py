# tirc_core/dcc/dcc_send_manager.py
import logging
import asyncio
import os
import time
from typing import TYPE_CHECKING, List, Dict, Optional, Tuple, Deque, Union # Added Union
from pathlib import Path # Added Path
from collections import deque # For managing send queue per peer

from tirc_core.dcc.dcc_transfer import DCCTransfer, DCCTransferType, DCCTransferStatus
from tirc_core.dcc.dcc_utils import ip_str_to_int, format_dcc_ctcp, create_listening_socket

if TYPE_CHECKING:
    from tirc_core.dcc.dcc_manager import DCCManager
    from tirc_core.config_defs import DccConfig # Corrected import

logger = logging.getLogger("tirc.dcc.sendmanager") # Specific logger for this manager

class DCCSendTransfer(DCCTransfer):
    """Represents an outgoing DCC SEND transfer."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.type != DCCTransferType.SEND:
            raise ValueError("DCCSendTransfer must have type SEND.")
        self.transfer_logger.info(f"[{self.id}] DCCSendTransfer instance created for {self.filename}.")

    async def start(self):
        """Initiates the DCC SEND process (active or passive)."""
        if self.status != DCCTransferStatus.QUEUED and self.status != DCCTransferStatus.PENDING and self.status != DCCTransferStatus.RESUMING:
            self.transfer_logger.warning(f"[{self.id}] Attempted to start DCC SEND for {self.filename} but status is {self.status.name}. Aborting.")
            return

        await self._update_status(DCCTransferStatus.NEGOTIATING)
        self.start_time = time.monotonic()

        if self.is_passive:
            await self._initiate_passive_send()
        else:
            await self._initiate_active_send()

    async def _initiate_active_send(self):
        """Handles active DCC SEND (sender listens, receiver connects)."""
        self.transfer_logger.info(f"[{self.id}] Initiating ACTIVE DCC SEND for {self.filename} to {self.peer_nick}.")

        listening_socket: Optional[asyncio.AbstractServer] = None
        actual_listen_port: Optional[int] = None

        try:
            # Find an available port in the configured range
            host_to_listen = "0.0.0.0" # Listen on all interfaces
            port_range_start = self.dcc_config.port_range_start
            port_range_end = self.dcc_config.port_range_end

            for port_candidate in range(port_range_start, port_range_end + 1):
                try:
                    # Create a server that calls handle_connection_active when a client connects
                    server = await asyncio.start_server(
                        lambda r, w: self._handle_connection_active(r, w, self.id), # Pass self.id to correlate
                        host_to_listen,
                        port_candidate
                    )
                    listening_socket = server
                    actual_listen_port = port_candidate
                    self.transfer_logger.info(f"[{self.id}] Active DCC SEND: Listening on {host_to_listen}:{actual_listen_port} for {self.filename}.")
                    break
                except OSError as e: # Port likely in use
                    self.transfer_logger.debug(f"[{self.id}] Port {port_candidate} in use for active DCC SEND: {e}")
                    continue

            if not listening_socket or actual_listen_port is None:
                await self._update_status(DCCTransferStatus.FAILED, "No available port for active DCC SEND.")
                return

            # Get local IP to advertise
            local_ip_str = self.dcc_manager.get_local_ip_for_ctcp()
            ip_int = ip_str_to_int(local_ip_str)

            # Send CTCP DCC SEND offer to peer
            ctcp_offer = format_dcc_ctcp(
                "SEND", self.filename, ip_int, actual_listen_port, self.expected_filesize
            )
            await self.dcc_manager.client_logic.send_ctcp_privmsg(self.peer_nick, ctcp_offer)
            await self._update_status(DCCTransferStatus.CONNECTING, f"Waiting for {self.peer_nick} to connect to {local_ip_str}:{actual_listen_port}")

            # Set a timeout for the peer to connect
            connect_timeout = self.dcc_config.timeout # General DCC timeout

            async def server_serve_forever_with_timeout(server: asyncio.AbstractServer, timeout: float):
                try:
                    await asyncio.wait_for(server.serve_forever(), timeout=timeout)
                except asyncio.TimeoutError:
                    self.transfer_logger.warning(f"[{self.id}] Timeout waiting for peer connection for active DCC SEND {self.filename}.")
                    if self.status == DCCTransferStatus.CONNECTING: # Check if still waiting
                        await self._update_status(DCCTransferStatus.FAILED, "Timeout waiting for peer connection.")
                except asyncio.CancelledError:
                     self.transfer_logger.info(f"[{self.id}] Active DCC server task for {self.filename} cancelled.")
                finally:
                    if server and server.is_serving():
                        server.close()
                        await server.wait_closed()
                        self.transfer_logger.info(f"[{self.id}] Active DCC server for {self.filename} closed.")

            # Store the server task so it can be cancelled if the transfer is cancelled
            self.transfer_task = asyncio.create_task(server_serve_forever_with_timeout(listening_socket, connect_timeout))

        except Exception as e:
            self.transfer_logger.error(f"[{self.id}] Error initiating active DCC SEND for {self.filename}: {e}", exc_info=True)
            await self._update_status(DCCTransferStatus.FAILED, f"Error setting up active send: {e}")
            if listening_socket and listening_socket.is_serving():
                listening_socket.close()
                await listening_socket.wait_closed()


    async def _handle_connection_active(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, transfer_id_check: str):
        """Called when a peer connects to our listening socket for an active send."""
        if self.id != transfer_id_check: # Should not happen if lambda captures self.id correctly
            self.transfer_logger.error(f"[{self.id}] Mismatched transfer ID in _handle_connection_active. Expected {self.id}, got {transfer_id_check}.")
            writer.close()
            await writer.wait_closed()
            return

        peer_addr = writer.get_extra_info('peername')
        self.transfer_logger.info(f"[{self.id}] Peer {peer_addr} connected for active DCC SEND of {self.filename}.")

        self.reader = reader # Not typically used for sending, but good to have
        self.writer = writer
        self.socket = writer # For compatibility with _close_socket_and_file and generic send logic

        # Now that connection is established, proceed to send data
        await self._send_file_data()


    async def _initiate_passive_send(self):
        """Handles passive DCC SEND (sender connects to receiver after token exchange)."""
        self.transfer_logger.info(f"[{self.id}] Initiating PASSIVE DCC SEND for {self.filename} to {self.peer_nick} with token {self.passive_token}.")
        if not self.passive_token:
            await self._update_status(DCCTransferStatus.FAILED, "Passive SEND attempted without a token.")
            return

        # Send CTCP DCC SEND offer with token to peer
        # For passive, IP is 0, port is 0. Size is actual size.
        ctcp_offer = format_dcc_ctcp(
            "SEND", self.filename, 0, 0, self.expected_filesize, token=self.passive_token
        )
        await self.dcc_manager.client_logic.send_ctcp_privmsg(self.peer_nick, ctcp_offer)
        await self._update_status(DCCTransferStatus.NEGOTIATING, f"Waiting for {self.peer_nick} to respond with /dcc get {self.passive_token}")

        # DCCManager will handle the incoming GET/ACCEPT from the peer,
        # which will then call connect_and_send_passive on this transfer instance.

    async def connect_and_send_passive(self, remote_ip: str, remote_port: int):
        """Called by DCCManager when a passive offer is accepted by the peer."""
        if not self.is_passive or self.status != DCCTransferStatus.NEGOTIATING:
            self.transfer_logger.warning(f"[{self.id}] connect_and_send_passive called inappropriately for {self.filename} (status: {self.status.name}, passive: {self.is_passive})")
            return

        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.transfer_logger.info(f"[{self.id}] Passive SEND: Peer {self.peer_nick} accepted. Connecting to {remote_ip}:{remote_port} for {self.filename}.")
        await self._update_status(DCCTransferStatus.CONNECTING)

        try:
            self.reader, self.writer = await asyncio.open_connection(remote_ip, remote_port)
            self.socket = self.writer # For compatibility
            self.transfer_logger.info(f"[{self.id}] Passive SEND: Connected to {remote_ip}:{remote_port}. Starting file transfer.")
            await self._send_file_data()
        except ConnectionRefusedError:
            await self._update_status(DCCTransferStatus.FAILED, f"Connection refused by {remote_ip}:{remote_port}")
        except asyncio.TimeoutError:
            await self._update_status(DCCTransferStatus.FAILED, f"Timeout connecting to {remote_ip}:{remote_port}")
        except Exception as e:
            self.transfer_logger.error(f"[{self.id}] Passive SEND: Error connecting/sending to {remote_ip}:{remote_port}: {e}", exc_info=True)
            await self._update_status(DCCTransferStatus.FAILED, f"Error connecting for passive send: {e}")


    async def _send_file_data(self):
        """Common logic to send file data once connection is established."""
        if not self.writer or self.writer.is_closing():
            await self._update_status(DCCTransferStatus.FAILED, "Socket not available or closing before send.")
            return

        await self._update_status(DCCTransferStatus.TRANSFERRING)
        self.transfer_logger.info(f"[{self.id}] Starting data transmission for {self.filename} (offset: {self.resume_offset}).")

        try:
            with open(self.local_filepath, "rb") as f:
                if self.resume_offset > 0:
                    f.seek(self.resume_offset)
                    self.transfer_logger.info(f"[{self.id}] Resumed send for {self.filename} from offset {self.resume_offset}.")

                self.bytes_transferred = self.resume_offset # Ensure this is set correctly for resumed transfers
                self._last_rate_update_time = time.monotonic()
                self._bytes_at_last_rate_update = self.bytes_transferred

                # TODO: Define chunk_size_send in DccConfig in config_defs.py and AppConfig
                chunk_size = getattr(self.dcc_config, "chunk_size_send", 4096)
                throttle_enabled = self.dcc_config.bandwidth_limit_send_kbps > 0
                bytes_per_second_limit = self.dcc_config.bandwidth_limit_send_kbps * 1024 if throttle_enabled else float('inf')

                last_throttle_check_time = time.monotonic()
                bytes_sent_in_period = 0

                while True:
                    if self.status == DCCTransferStatus.CANCELLED: # Check for cancellation
                        self.transfer_logger.info(f"[{self.id}] Send cancelled during data transmission for {self.filename}.")
                        break

                    chunk = f.read(chunk_size)
                    if not chunk:
                        break # End of file

                    self.writer.write(chunk)
                    await self.writer.drain()
                    self.bytes_transferred += len(chunk)

                    # Bandwidth Throttling
                    if throttle_enabled:
                        bytes_sent_in_period += len(chunk)
                        current_time = time.monotonic()
                        elapsed_in_period = current_time - last_throttle_check_time
                        if elapsed_in_period >= 1.0: # Check/adjust every second
                            # Expected bytes in this period based on limit
                            expected_bytes_this_period = bytes_per_second_limit * elapsed_in_period
                            if bytes_sent_in_period > expected_bytes_this_period:
                                # We sent too fast, calculate sleep time
                                excess_bytes = bytes_sent_in_period - expected_bytes_this_period
                                time_to_send_excess_at_limit = excess_bytes / bytes_per_second_limit
                                if time_to_send_excess_at_limit > 0:
                                    self.transfer_logger.debug(f"[{self.id}] Throttling send for {self.filename}, sleeping for {time_to_send_excess_at_limit:.3f}s")
                                    await asyncio.sleep(time_to_send_excess_at_limit)

                            # Reset for next period
                            last_throttle_check_time = current_time
                            bytes_sent_in_period = 0
                        elif bytes_sent_in_period * 8 / elapsed_in_period > bytes_per_second_limit * 8 and elapsed_in_period < 1.0 : # Proactive small sleep if rate is too high within the second
                            # This is a more aggressive throttle for very fast sends within the 1s window
                            # It might lead to slightly bursty but overall compliant sending.
                            # Calculate how much faster we are and sleep proportionally.
                            # This part is tricky to get perfect without complex token bucket.
                            # For simplicity, a small fixed sleep if current rate exceeds limit significantly.
                            # if self.current_rate_bps > bytes_per_second_limit * 8 * 1.2: # If 20% over limit
                            #    await asyncio.sleep(0.01) # Small sleep
                            pass


                    # Wait for ACK from receiver (every 4KB or so, or as per protocol)
                    # DCC protocol requires receiver to send back number of bytes received as 32-bit network-order int.
                    # This example doesn't implement waiting for ACKs for simplicity of send loop.
                    # A robust implementation would wait for these ACKs to confirm data receipt and handle potential stalls.
                    # For now, we assume TCP handles reliable delivery.

                    self._calculate_rate_and_eta() # Update progress
                    await self.dcc_manager.dispatch_transfer_event("DCC_TRANSFER_PROGRESS", self)


            if self.status == DCCTransferStatus.CANCELLED: # Re-check after loop
                 return # Already handled by cancel method

            self.transfer_logger.info(f"[{self.id}] Finished sending data for {self.filename}. Total bytes: {self.bytes_transferred}.")

            if self.dcc_config.checksum_verify:
                self.checksum_local = self._calculate_file_hash()
                # TODO: Need a way to get checksum_remote from peer (e.g. custom CTCP or post-transfer message)
                # For now, we'll assume it's not available for SEND unless peer sends it back.
                # If checksum_remote is obtained, call _verify_checksum()
                # await self._verify_checksum()
                # If not, we just complete.
                if self.checksum_local and not self.checksum_remote:
                     self.transfer_logger.info(f"[{self.id}] Local checksum calculated for {self.filename}. Waiting for remote checksum if protocol supports it.")


            await self._update_status(DCCTransferStatus.COMPLETED)

        except asyncio.CancelledError:
            self.transfer_logger.info(f"[{self.id}] Send task for {self.filename} was cancelled.")
            # Status should be set by the cancel() method
            if self.status not in [DCCTransferStatus.CANCELLED, DCCTransferStatus.FAILED]:
                 await self._update_status(DCCTransferStatus.CANCELLED, "Transfer task cancelled externally.")
        except ConnectionResetError:
            await self._update_status(DCCTransferStatus.FAILED, "Connection reset by peer.")
        except BrokenPipeError: # Often happens if receiver closes connection abruptly
            await self._update_status(DCCTransferStatus.FAILED, "Broken pipe (connection closed by peer).")
        except Exception as e:
            self.transfer_logger.error(f"[{self.id}] Error sending file {self.filename}: {e}", exc_info=True)
            await self._update_status(DCCTransferStatus.FAILED, f"Error during send: {e}")
        finally:
            await self._close_socket_and_file()


class DCCSendManager:
    """Manages all outgoing DCC SEND transfers."""

    def __init__(self, dcc_manager: "DCCManager"):
        self.dcc_manager = dcc_manager
        self.config = dcc_manager.dcc_config # Corrected: dcc_manager has dcc_config directly
        self.send_queues: Dict[str, Deque[DCCSendTransfer]] = {} # peer_nick -> deque of transfers
        self.active_sends_for_peer: Dict[str, int] = {} # peer_nick -> count of active sends
        # TODO: Define max_concurrent_sends_per_peer in DccConfig in config_defs.py and AppConfig
        self.max_concurrent_sends_per_peer = getattr(self.config, "max_concurrent_sends_per_peer", 2)
        self._lock = asyncio.Lock() # To protect access to queues and active counts
        logger.info("DCCSendManager initialized.")

    async def queue_send_request(
        self, peer_nick: str, local_filepath: Union[str, Path], passive: bool = False, resume_from_id: Optional[str] = None
    ) -> Optional[DCCSendTransfer]:
        """
        Queues a file to be sent to a peer.
        If resume_from_id is provided, it attempts to find and resume that transfer.
        Returns the DCCTransfer object if successfully queued/resumed, else None.
        """
        local_path = Path(local_filepath)
        if not local_path.exists() or not local_path.is_file():
            logger.error(f"DCC SEND: File not found or is not a file: {local_path}")
            await self.dcc_manager.client_logic.add_status_message(f"DCC Error: File not found {local_path}", "error")
            return None

        filesize = local_path.stat().st_size
        if self.config.max_file_size > 0 and filesize > self.config.max_file_size:
            logger.warning(f"DCC SEND: File {local_path.name} ({filesize}B) exceeds max size ({self.config.max_file_size}B).")
            await self.dcc_manager.client_logic.add_status_message(f"DCC Error: File {local_path.name} too large.", "error")
            return None

        # Sanitize filename for sending over DCC (remove paths, potentially harmful chars)
        # dcc_security.py should have a function for this.
        # For now, just use the basename.
        safe_filename = os.path.basename(local_path)

        if passive and not self.dcc_manager.passive_offer_manager:
            logger.error(f"Cannot initiate passive DCC SEND to {peer_nick} for {local_path}: PassiveOfferManager not available.")
            await self.dcc_manager.client_logic.add_status_message(
                f"Error: Passive DCC sends not available (manager missing).", "error"
            )
            return None

        transfer_id: Optional[str] = None
        transfer_to_process: Optional[DCCSendTransfer] = None
        resume_offset = 0

        async with self._lock:
            if resume_from_id:
                existing_transfer = self.dcc_manager.get_transfer_by_id(resume_from_id)
                if existing_transfer and isinstance(existing_transfer, DCCSendTransfer) and \
                   existing_transfer.status in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.PAUSED]:
                    logger.info(f"Attempting to resume DCC SEND for {safe_filename} (ID: {resume_from_id})")
                    transfer_to_process = existing_transfer
                    transfer_id = resume_from_id
                    # Ensure resume_offset is correctly set from the existing transfer's bytes_transferred
                    resume_offset = transfer_to_process.bytes_transferred
                    transfer_to_process.status = DCCTransferStatus.RESUMING # Mark as resuming
                    transfer_to_process.error_message = None # Clear previous error
                    transfer_to_process.start_time = None # Will be reset on actual start
                    transfer_to_process.end_time = None
                    # Passive flag should be retained from original transfer for resume
                    passive = transfer_to_process.is_passive
                    if transfer_to_process.passive_token and not passive: # Should not happen if state is consistent
                        logger.warning(f"Resuming transfer {transfer_id} had a passive token but passive flag was False. Correcting.")
                        passive = True

                else:
                    logger.warning(f"DCC RESUME: Transfer ID {resume_from_id} not found or not in a resumable state.")
                    await self.dcc_manager.client_logic.add_status_message(f"DCC Error: Cannot resume transfer {resume_from_id}.", "error")
                    return None

            if not transfer_to_process: # New transfer
                transfer_id = self.dcc_manager._generate_transfer_id()
                passive_token = None
                if passive:
                    # The earlier check (outside the lock) should ensure passive_offer_manager is not None.
                    # This assert reinforces that expectation for static analysis and runtime.
                    assert self.dcc_manager.passive_offer_manager is not None, \
                        "DCCPassiveOfferManager not initialized for a passive send attempt."
                    passive_token = self.dcc_manager.passive_offer_manager.generate_token(
                        transfer_id, peer_nick, safe_filename, filesize
                    )

                transfer_to_process = DCCSendTransfer(
                    transfer_id=transfer_id,
                    transfer_type=DCCTransferType.SEND,
                    peer_nick=peer_nick,
                    filename=safe_filename,
                    filesize=filesize,
                    local_filepath=local_path,
                    dcc_manager_ref=self.dcc_manager,
                    dcc_config_ref=self.config,
                    event_logger=self.dcc_manager.dcc_event_logger,
                    passive_token=passive_token,
                    resume_offset=0 # New transfers start at 0
                )
                self.dcc_manager._add_transfer_to_tracking(transfer_to_process)

            # Add to peer's queue
            if peer_nick not in self.send_queues:
                self.send_queues[peer_nick] = deque()
            self.send_queues[peer_nick].append(transfer_to_process)
            logger.info(f"Queued DCC SEND for {safe_filename} to {peer_nick}. Queue size: {len(self.send_queues[peer_nick])}. ID: {transfer_id}")
            await transfer_to_process._update_status(DCCTransferStatus.QUEUED)

        # Process queue for this peer
        asyncio.create_task(self._process_send_queue(peer_nick))
        return transfer_to_process


    async def _process_send_queue(self, peer_nick: str):
        async with self._lock:
            if peer_nick not in self.send_queues or not self.send_queues[peer_nick]:
                logger.debug(f"Send queue for {peer_nick} is empty. Nothing to process.")
                return

            current_active_sends = self.active_sends_for_peer.get(peer_nick, 0)
            if current_active_sends >= self.max_concurrent_sends_per_peer:
                logger.info(f"Max concurrent sends ({self.max_concurrent_sends_per_peer}) reached for {peer_nick}. Waiting.")
                return

            transfer = self.send_queues[peer_nick].popleft()
            self.active_sends_for_peer[peer_nick] = current_active_sends + 1
            logger.info(f"Processing next send for {peer_nick}: {transfer.filename} (ID: {transfer.id}). Active sends: {self.active_sends_for_peer[peer_nick]}")

        try:
            # Start the transfer (this will handle active/passive logic internally)
            # The transfer.start() method is responsible for its own lifecycle now.
            # It will eventually call _update_status which dispatches events.
            # DCCManager's main loop will monitor these events.
            await transfer.start()
            # When transfer.start() completes (either successfully, failed, or cancelled),
            # its status will be updated. We need to decrement active_sends_for_peer
            # and potentially process the next item in the queue.
            # This is better handled by the DCCManager observing the DCC_TRANSFER_STATUS_CHANGE event.
        except Exception as e:
            logger.error(f"Error starting DCC SEND for {transfer.filename} to {peer_nick}: {e}", exc_info=True)
            await transfer._update_status(DCCTransferStatus.FAILED, f"Error starting send: {e}")
            # Ensure active count is decremented even on error starting
            async with self._lock:
                self.active_sends_for_peer[peer_nick] = self.active_sends_for_peer.get(peer_nick, 1) -1
            # Try to process next if any
            asyncio.create_task(self._process_send_queue(peer_nick))


    async def handle_transfer_completion(self, transfer: DCCSendTransfer):
        """Called by DCCManager when a send transfer completes (success, fail, cancel)."""
        async with self._lock:
            peer_nick = transfer.peer_nick
            self.active_sends_for_peer[peer_nick] = self.active_sends_for_peer.get(peer_nick, 1) - 1
            if self.active_sends_for_peer[peer_nick] < 0: self.active_sends_for_peer[peer_nick] = 0 # Sanity check
            logger.info(f"DCC SEND for {transfer.filename} to {peer_nick} completed with status {transfer.status.name}. Active sends for peer: {self.active_sends_for_peer[peer_nick]}")

        # Process next in queue for this peer
        asyncio.create_task(self._process_send_queue(peer_nick))

    async def shutdown(self):
        logger.info("Shutting down DCCSendManager. Cancelling active send tasks.")
        async with self._lock:
            for peer_nick, queue in self.send_queues.items():
                for transfer in queue:
                    if transfer.status not in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED]:
                        logger.info(f"Cancelling queued send: {transfer.filename} to {peer_nick}")
                        await transfer.cancel("Send manager shutdown")
            self.send_queues.clear()

            # Also cancel transfers that might be in active_sends_for_peer but not in queue (i.e., currently processing)
            # This requires iterating through all tracked transfers in DCCManager
            all_sends = [t for t in self.dcc_manager.transfers.values() if isinstance(t, DCCSendTransfer)]
            for transfer in all_sends:
                 if transfer.status not in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED]:
                    if transfer.transfer_task and not transfer.transfer_task.done():
                        logger.info(f"Cancelling active send task during shutdown: {transfer.filename} to {transfer.peer_nick}")
                        await transfer.cancel("Send manager shutdown (active task)")
            self.active_sends_for_peer.clear()
        logger.info("DCCSendManager shutdown complete.")
