# tirc_core/dcc/dcc_receive_manager.py
import logging
import asyncio
import os
import time
from typing import TYPE_CHECKING, Optional, Dict, Any, Deque
from collections import deque
from pathlib import Path

from tirc_core.dcc.dcc_transfer import DCCTransfer, DCCTransferType, DCCTransferStatus
from tirc_core.dcc.dcc_utils import ip_str_to_int, format_dcc_ctcp, create_listening_socket
from tirc_core.dcc.dcc_security import get_safe_download_filepath, sanitize_filename
from tirc_core.config_defs import DccConfig

if TYPE_CHECKING:
    from tirc_core.dcc.dcc_manager import DCCManager

logger = logging.getLogger("tirc.dcc.receive_manager")

class DCCReceiveTransfer(DCCTransfer):
    """Represents an incoming DCC SEND transfer (we are receiving)."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.type != DCCTransferType.RECEIVE:
            raise ValueError("DCCReceiveTransfer must have type RECEIVE.")
        self.transfer_logger.info(f"[{self.id}] DCCReceiveTransfer instance created for {self.filename}.")
        self.listening_socket: Optional[asyncio.AbstractServer] = None
        self.accept_task: Optional[asyncio.Task] = None

    async def start(self):
        """Initiates the DCC RECEIVE process (active or passive)."""
        if self.status != DCCTransferStatus.PENDING and self.status != DCCTransferStatus.RESUMING:
            self.transfer_logger.warning(f"[{self.id}] Attempted to start DCC RECEIVE for {self.filename} but status is {self.status.name}. Aborting.")
            return

        self.start_time = time.monotonic()

        safe_path = get_safe_download_filepath(
            self.dcc_config.download_dir,
            self.filename,
            set(self.dcc_config.blocked_extensions),
            overwrite_existing=False
        )
        if not safe_path:
            await self._update_status(DCCTransferStatus.FAILED, f"Could not determine safe download path for {self.filename}.")
            return
        self.local_filepath = safe_path

        if self.is_passive:
            await self._initiate_passive_receive()
        else:
            await self._initiate_active_receive()

    async def _initiate_active_receive(self):
        """Handles active DCC RECEIVE (we connect to the sender)."""
        self.transfer_logger.info(f"[{self.id}] Initiating ACTIVE DCC RECEIVE for {self.filename} from {self.peer_nick} at {self.remote_ip}:{self.remote_port}.")
        await self._update_status(DCCTransferStatus.CONNECTING)

        try:
            self.reader, self.writer = await asyncio.open_connection(self.remote_ip, self.remote_port)
            self.socket = self.writer
            self.transfer_logger.info(f"[{self.id}] Active RECEIVE: Connected to {self.remote_ip}:{self.remote_port}. Starting file reception.")
            await self._receive_file_data()
        except ConnectionRefusedError:
            await self._update_status(DCCTransferStatus.FAILED, f"Connection refused by {self.remote_ip}:{self.remote_port}")
        except asyncio.TimeoutError:
            await self._update_status(DCCTransferStatus.FAILED, f"Timeout connecting to {self.remote_ip}:{self.remote_port}")
        except Exception as e:
            self.transfer_logger.error(f"[{self.id}] Active RECEIVE: Error connecting/receiving from {self.remote_ip}:{self.remote_port}: {e}", exc_info=True)
            await self._update_status(DCCTransferStatus.FAILED, f"Error in active receive: {e}")


    async def _initiate_passive_receive(self):
        """Handles passive DCC RECEIVE (we listen, sender connects using token)."""
        self.transfer_logger.info(f"[{self.id}] Initiating PASSIVE DCC RECEIVE for {self.filename} from {self.peer_nick} (token: {self.passive_token}).")

        actual_listen_port: Optional[int] = None
        try:
            host_to_listen = "0.0.0.0"
            port_range_start = self.dcc_config.port_range_start
            port_range_end = self.dcc_config.port_range_end

            for port_candidate in range(port_range_start, port_range_end + 1):
                try:
                    server = await asyncio.start_server(
                        lambda r, w: self._handle_connection_passive(r, w, self.id),
                        host_to_listen, port_candidate
                    )
                    self.listening_socket = server
                    actual_listen_port = port_candidate
                    self.transfer_logger.info(f"[{self.id}] Passive DCC RECEIVE: Listening on {host_to_listen}:{actual_listen_port} for {self.filename}.")
                    break
                except OSError: continue

            if not self.listening_socket or actual_listen_port is None:
                await self._update_status(DCCTransferStatus.FAILED, "No available port for passive DCC RECEIVE.")
                return

            ctcp_accept_msg = f"DCC ACCEPT \"{self.filename}\" {self.passive_token} {actual_listen_port}"
            await self.dcc_manager.client_logic.send_ctcp_privmsg(self.peer_nick, ctcp_accept_msg)
            await self._update_status(DCCTransferStatus.CONNECTING, f"Waiting for {self.peer_nick} to connect to our port {actual_listen_port} (token {self.passive_token}).")

            accept_timeout = self.dcc_config.passive_mode_token_timeout

            async def server_serve_forever_with_timeout(server: asyncio.AbstractServer, timeout: float):
                try:
                    await asyncio.wait_for(server.serve_forever(), timeout=timeout)
                except asyncio.TimeoutError:
                    self.transfer_logger.warning(f"[{self.id}] Timeout waiting for peer connection for passive DCC RECEIVE {self.filename}.")
                    if self.status == DCCTransferStatus.CONNECTING:
                        await self._update_status(DCCTransferStatus.FAILED, "Timeout waiting for peer connection (passive).")
                except asyncio.CancelledError:
                    self.transfer_logger.info(f"[{self.id}] Passive DCC server task for {self.filename} cancelled.")
                finally:
                    if server and server.is_serving():
                        server.close()
                        await server.wait_closed()
                        self.transfer_logger.info(f"[{self.id}] Passive DCC server for {self.filename} closed.")

            self.accept_task = asyncio.create_task(server_serve_forever_with_timeout(self.listening_socket, accept_timeout))

        except Exception as e:
            self.transfer_logger.error(f"[{self.id}] Error initiating passive DCC RECEIVE for {self.filename}: {e}", exc_info=True)
            await self._update_status(DCCTransferStatus.FAILED, f"Error setting up passive receive: {e}")
            if self.listening_socket and self.listening_socket.is_serving():
                self.listening_socket.close()
                await self.listening_socket.wait_closed()

    async def _handle_connection_passive(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, transfer_id_check: str):
        if self.id != transfer_id_check:
            self.transfer_logger.error(f"[{self.id}] Mismatched transfer ID in _handle_connection_passive. Expected {self.id}, got {transfer_id_check}.")
            writer.close(); await writer.wait_closed()
            return

        peer_addr = writer.get_extra_info('peername')
        self.transfer_logger.info(f"[{self.id}] Peer {peer_addr} connected for passive DCC RECEIVE of {self.filename}.")

        self.reader = reader
        self.writer = writer
        self.socket = writer

        if self.listening_socket and self.listening_socket.is_serving():
            self.listening_socket.close()
        if self.accept_task and not self.accept_task.done():
            self.accept_task.cancel()

        await self._receive_file_data()


    async def _receive_file_data(self):
        if not self.reader or not self.writer or self.writer.is_closing():
            await self._update_status(DCCTransferStatus.FAILED, "Socket not available or closing before receive.")
            return

        await self._update_status(DCCTransferStatus.TRANSFERRING)
        self.transfer_logger.info(f"[{self.id}] Starting data reception for {self.filename} to {self.local_filepath} (offset: {self.resume_offset}).")

        try:
            file_mode = "ab" if self.resume_offset > 0 else "wb"
            with open(self.local_filepath, file_mode) as f:
                self.file_handle = f
                if self.resume_offset > 0:
                    self.transfer_logger.info(f"[{self.id}] Resumed receive for {self.filename} from offset {self.resume_offset}.")

                self.bytes_transferred = self.resume_offset
                self._last_rate_update_time = time.monotonic()
                self._bytes_at_last_rate_update = self.bytes_transferred

                chunk_size = getattr(self.dcc_config, "chunk_size_recv", 4096)
                throttle_enabled = self.dcc_config.bandwidth_limit_recv_kbps > 0
                bytes_per_second_limit = self.dcc_config.bandwidth_limit_recv_kbps * 1024 if throttle_enabled else float('inf')

                last_throttle_check_time = time.monotonic()
                bytes_recv_in_period = 0

                while self.bytes_transferred < self.expected_filesize:
                    if self.status == DCCTransferStatus.CANCELLED:
                        self.transfer_logger.info(f"[{self.id}] Receive cancelled during data reception for {self.filename}.")
                        break
                    read_amount = chunk_size
                    try:
                        chunk = await asyncio.wait_for(self.reader.read(read_amount), timeout=self.dcc_config.timeout / 2 or 30)
                    except asyncio.TimeoutError:
                        await self._update_status(DCCTransferStatus.FAILED, "Timeout waiting for data from peer.")
                        return

                    if not chunk:
                        if self.bytes_transferred < self.expected_filesize:
                            await self._update_status(DCCTransferStatus.FAILED, "Connection closed by peer before transfer complete.")
                        else:
                            pass
                        break

                    f.write(chunk)
                    self.bytes_transferred += len(chunk)

                    ack_payload = self.bytes_transferred.to_bytes(4, 'big')
                    self.writer.write(ack_payload)
                    await self.writer.drain()

                    if throttle_enabled:
                        bytes_recv_in_period += len(chunk)
                        current_time = time.monotonic()
                        elapsed_in_period = current_time - last_throttle_check_time
                        if elapsed_in_period >= 1.0:
                            expected_bytes_this_period = bytes_per_second_limit * elapsed_in_period
                            if bytes_recv_in_period > expected_bytes_this_period:
                                excess_bytes = bytes_recv_in_period - expected_bytes_this_period
                                time_to_receive_excess_at_limit = excess_bytes / bytes_per_second_limit
                                if time_to_receive_excess_at_limit > 0:
                                    self.transfer_logger.debug(f"[{self.id}] Throttling receive for {self.filename}, sleeping for {time_to_receive_excess_at_limit:.3f}s")
                                    await asyncio.sleep(time_to_receive_excess_at_limit)
                            last_throttle_check_time = current_time
                            bytes_recv_in_period = 0

                    self._calculate_rate_and_eta()
                    await self.dcc_manager.dispatch_transfer_event("DCC_TRANSFER_PROGRESS", self)

            if self.status == DCCTransferStatus.CANCELLED:
                return

            if self.bytes_transferred == self.expected_filesize:
                self.transfer_logger.info(f"[{self.id}] Finished receiving data for {self.filename}. Total bytes: {self.bytes_transferred}.")
                if self.dcc_config.checksum_verify:
                    self.checksum_local = self._calculate_file_hash()
                await self._update_status(DCCTransferStatus.COMPLETED)
            else:
                await self._update_status(DCCTransferStatus.FAILED, f"Transfer ended with {self.bytes_transferred}/{self.expected_filesize} bytes.")

        except asyncio.CancelledError:
            self.transfer_logger.info(f"[{self.id}] Receive task for {self.filename} was cancelled.")
            if self.status not in [DCCTransferStatus.CANCELLED, DCCTransferStatus.FAILED]:
                 await self._update_status(DCCTransferStatus.CANCELLED, "Transfer task cancelled externally.")
        except ConnectionResetError:
            await self._update_status(DCCTransferStatus.FAILED, "Connection reset by peer.")
        except BrokenPipeError:
            await self._update_status(DCCTransferStatus.FAILED, "Broken pipe (connection closed by peer).")
        except Exception as e:
            self.transfer_logger.error(f"[{self.id}] Error receiving file {self.filename}: {e}", exc_info=True)
            await self._update_status(DCCTransferStatus.FAILED, f"Error during receive: {e}")
        finally:
            await self._close_socket_and_file()


class DCCReceiveManager:
    """Manages all incoming DCC SEND offers (files we receive)."""

    def __init__(self, dcc_manager: "DCCManager"):
        self.dcc_manager = dcc_manager
        self.config = dcc_manager.config.dcc
        logger.info("DCCReceiveManager initialized.")

    async def handle_incoming_send_offer(
        self,
        peer_nick: str,
        filename: str,
        ip_str: Optional[str],
        port: Optional[int],
        filesize: int,
        token: Optional[str] = None
    ) -> Optional[DCCReceiveTransfer]:
        is_passive_offer = bool(token)
        safe_filename = sanitize_filename(filename)
        if safe_filename != filename:
            logger.info(f"DCC Offer from {peer_nick}: Original filename '{filename}' sanitized to '{safe_filename}'.")

        file_ext = os.path.splitext(safe_filename)[1].lower()
        if file_ext in self.config.blocked_extensions:
            logger.warning(f"DCC Offer from {peer_nick} for '{safe_filename}' blocked due to extension '{file_ext}'.")
            await self.dcc_manager.client_logic.add_status_message(
                f"DCC offer for '{safe_filename}' from {peer_nick} blocked (extension).", "warning"
            )
            return None

        if self.config.max_file_size > 0 and filesize > self.config.max_file_size:
            logger.warning(f"DCC Offer from {peer_nick} for '{safe_filename}' ({filesize}B) exceeds max size ({self.config.max_file_size}B). Rejected.")
            await self.dcc_manager.client_logic.add_status_message(
                f"DCC offer for '{safe_filename}' from {peer_nick} rejected (too large).", "warning"
            )
            return None

        transfer_id = self.dcc_manager._generate_transfer_id()
        placeholder_local_path = Path(self.config.download_dir) / safe_filename

        transfer = DCCReceiveTransfer(
            transfer_id=transfer_id,
            transfer_type=DCCTransferType.RECEIVE,
            peer_nick=peer_nick,
            filename=safe_filename,
            filesize=filesize,
            local_filepath=placeholder_local_path,
            dcc_manager_ref=self.dcc_manager,
            dcc_config_ref=self.config,
            event_logger=self.dcc_manager.dcc_event_logger,
            passive_token=token,
            remote_ip=ip_str,
            remote_port=port
        )
        self.dcc_manager._add_transfer_to_tracking(transfer)

        offer_type_str = "passive (reverse)" if is_passive_offer else "active"
        log_msg = f"Received {offer_type_str} DCC SEND offer from {peer_nick} for '{safe_filename}' ({filesize} bytes)."
        if is_passive_offer: log_msg += f" Token: {token}"
        else: log_msg += f" Peer at: {ip_str}:{port}"
        logger.info(log_msg)

        ui_msg = f"DCC {offer_type_str.upper()} SEND offer from {peer_nick}: \"{safe_filename}\" ({filesize} bytes)."
        if is_passive_offer:
            ui_msg += f" Use /dcc_get \"{peer_nick}\" \"{safe_filename}\" --token {token}"
        else:
            ui_msg += f" Use /dcc_accept \"{peer_nick}\" \"{safe_filename}\" {ip_str} {port} {filesize}"

        # Resolve color key to integer color pair ID
        ui_colors = self.dcc_manager.client_logic.ui.colors
        dcc_offer_color_key = "dcc_offer"
        fallback_color_key = "system_highlight" # Default fallback
        default_color_pair_id = 0 # Ultimate fallback if no keys match

        color_pair_id = ui_colors.get(dcc_offer_color_key, ui_colors.get(fallback_color_key, default_color_pair_id))

        await self.dcc_manager.client_logic.add_message(
            ui_msg,
            color_pair_id, # Pass the resolved integer
            context_name=self.dcc_manager.dcc_ui_context_name
        )

        if self.config.auto_accept:
            logger.info(f"DCC auto_accept is ON. Attempting to start transfer {transfer_id} for '{safe_filename}'.")
            asyncio.create_task(transfer.start())
        else:
            logger.info(f"DCC auto_accept is OFF. Transfer {transfer_id} for '{safe_filename}' is PENDING user action.")

        return transfer

    async def shutdown(self):
        logger.info("Shutting down DCCReceiveManager. Cancelling active receive tasks.")
        all_receives = [t for t in self.dcc_manager.transfers.values() if isinstance(t, DCCReceiveTransfer)]
        for transfer in all_receives:
            if transfer.status not in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED]:
                if transfer.transfer_task and not transfer.transfer_task.done():
                    logger.info(f"Cancelling active receive task during shutdown: {transfer.filename} from {transfer.peer_nick}")
                    await transfer.cancel("Receive manager shutdown (active task)")
                elif transfer.accept_task and not transfer.accept_task.done():
                    logger.info(f"Cancelling passive receive accept task during shutdown: {transfer.filename} from {transfer.peer_nick}")
                    await transfer.cancel("Receive manager shutdown (accept task)")
        logger.info("DCCReceiveManager shutdown complete.")
