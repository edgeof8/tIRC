# tirc_core/dcc/dcc_manager.py
import logging
import asyncio
import threading # For self._lock
import time # For generating unique transfer IDs
from typing import TYPE_CHECKING, Dict, Optional, List, Any, Union
from pathlib import Path

from tirc_core.dcc.dcc_transfer import DCCTransfer, DCCTransferStatus, DCCTransferType
from tirc_core.dcc.dcc_send_manager import DCCSendManager, DCCSendTransfer
from tirc_core.dcc.dcc_receive_manager import DCCReceiveManager, DCCReceiveTransfer
from tirc_core.dcc.dcc_passive_offer_manager import DCCPassiveOfferManager
from tirc_core.dcc.dcc_utils import get_local_ip_for_ctcp, parse_dcc_ctcp
from tirc_core.dcc.dcc_security import sanitize_filename
from tirc_core.config_defs import DccConfig

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.event_manager import EventManager

logger = logging.getLogger("tirc.dcc.manager")

class DCCManager:
    def __init__(self, client_logic_ref: "IRCClient_Logic", event_manager_ref: "EventManager"):
        self.client_logic = client_logic_ref
        self.event_manager = event_manager_ref
        self.config = client_logic_ref.config
        self.dcc_config: DccConfig = self._load_dcc_config()

        self.transfers: Dict[str, DCCTransfer] = {}
        self._lock = threading.Lock()

        self.dcc_event_logger = logging.getLogger("tirc.dcc.events")
        self.send_manager: Optional['DCCSendManager'] = None
        self.receive_manager: Optional['DCCReceiveManager'] = None
        self.passive_offer_manager: Optional['DCCPassiveOfferManager'] = None

        self.dcc_ui_context_name = "DCC"
        self._cleanup_task_handle: Optional[asyncio.Task] = None # Initialize here

        if self.dcc_config.enabled:
            self.initialize_sub_managers()
            self.client_logic.context_manager.create_context(self.dcc_ui_context_name, context_type="dcc_transfers")
            logger.info("DCC system enabled and initialized with sub-managers.")
            # Task creation moved to start_periodic_task
            # Logging for disabled/zero interval is now implicitly handled by start_periodic_task's own logging
            if not (self.dcc_config.cleanup_enabled and self.dcc_config.cleanup_interval_seconds > 0):
                 logger.info("DCC cleanup configuration: task will not be auto-started by __init__ (disabled or interval is zero).")
        else:
            logger.info("DCC system is disabled in configuration.")
            # self._cleanup_task_handle = None # Already initialized to None

    def _load_dcc_config(self) -> DccConfig:
        if hasattr(self.config, 'dcc') and isinstance(self.config.dcc, DccConfig):
            return self.config.dcc
        else:
            logger.error("DCCConfig not found or incorrect type in AppConfig. Using default DccConfig.")
            return DccConfig()

    def initialize_sub_managers(self):
        if not self.dcc_config.enabled: return

        if not self.send_manager:
            self.send_manager = DCCSendManager(self)
        if not self.receive_manager:
            self.receive_manager = DCCReceiveManager(self)
        if not self.passive_offer_manager:
            self.passive_offer_manager = DCCPassiveOfferManager(self.dcc_config)

    def _generate_transfer_id(self) -> str:
        return f"dcc_{int(time.time() * 1000)}_{len(self.transfers)}"

    def _add_transfer_to_tracking(self, transfer: DCCTransfer):
        with self._lock:
            self.transfers[transfer.id] = transfer
        logger.info(f"Tracking new DCC transfer: {transfer.id} ({transfer.filename})")
        asyncio.create_task(self.dispatch_transfer_event("DCC_TRANSFER_INITIATED", transfer))

    async def dispatch_transfer_event(self, event_name: str, transfer: DCCTransfer, additional_data: Optional[Dict[str, Any]] = None):
        event_payload = transfer.get_status_dict()
        if additional_data:
            event_payload.update(additional_data)
        await self.event_manager.dispatch_event(event_name, event_payload)
        self.dcc_event_logger.info(f"Dispatched event {event_name} for transfer {transfer.id} ({transfer.filename}). Status: {transfer.status.name}")
        if event_name == "DCC_TRANSFER_STATUS_CHANGE" and \
           transfer.status in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED]:
            if isinstance(transfer, DCCSendTransfer) and self.send_manager:
                await self.send_manager.handle_transfer_completion(transfer)

    async def handle_incoming_ctcp_dcc(self, peer_nick: str, message: str):
        if not self.dcc_config.enabled:
            logger.debug("DCC is disabled, ignoring incoming CTCP DCC message.")
            return
        parsed_dcc = parse_dcc_ctcp(message)
        if not parsed_dcc:
            logger.warning(f"Failed to parse incoming CTCP DCC message from {peer_nick}: {message}")
            return
        command = parsed_dcc["command"]
        filename = parsed_dcc["filename"]
        logger.info(f"Handling incoming DCC {command} from {peer_nick} for file '{filename}'. Parsed: {parsed_dcc}")
        if command == "SEND":
            ip_str = parsed_dcc.get("ip_str")
            port = parsed_dcc.get("port")
            filesize = parsed_dcc.get("filesize", 0)
            token = parsed_dcc.get("token")
            if self.receive_manager:
                await self.receive_manager.handle_incoming_send_offer(
                    peer_nick, filename, ip_str, port, filesize, token
                )
            else: logger.error("ReceiveManager not initialized, cannot handle incoming SEND offer.")
        elif command == "GET":
            token = parsed_dcc.get("token")
            if not token or not self.passive_offer_manager:
                logger.warning(f"DCC GET from {peer_nick} for '{filename}' missing token or PassiveOfferManager not init. Message: {message}")
                return
            offer = self.passive_offer_manager.get_offer_by_token(token)
            if offer and offer.filename == filename and offer.peer_nick.lower() == peer_nick.lower():
                send_transfer = self.get_transfer_by_id(offer.transfer_id)
                if isinstance(send_transfer, DCCSendTransfer) and send_transfer.is_passive:
                    logger.warning(f"Received unexpected DCC GET for passive offer token {token}. Expecting DCC ACCEPT with port from peer.")
                else:
                    logger.warning(f"DCC GET for token {token} but no matching passive SEND transfer found or not a DCCSendTransfer: {offer.transfer_id}")
            else:
                logger.warning(f"Invalid or expired DCC GET token {token} from {peer_nick} for '{filename}'.")
        elif command == "ACCEPT":
            token = parsed_dcc.get("token")
            port_they_listen_on = parsed_dcc.get("port")
            if not token or port_they_listen_on is None or not self.passive_offer_manager:
                logger.warning(f"DCC ACCEPT from {peer_nick} for '{filename}' missing token/port or PassiveOfferManager not init. Message: {message}")
                return
            offer = self.passive_offer_manager.consume_token(token)
            if offer and offer.filename == filename and offer.peer_nick.lower() == peer_nick.lower():
                send_transfer = self.get_transfer_by_id(offer.transfer_id)
                if isinstance(send_transfer, DCCSendTransfer) and send_transfer.is_passive:
                    peer_actual_ip = None
                    if not peer_actual_ip:
                        user_state = self.client_logic.state_manager.get(f"user_info_{peer_nick.lower()}")
                        if isinstance(user_state, dict) and "host" in user_state:
                            pass
                        logger.error(f"Cannot determine IP for {peer_nick} to complete passive DCC SEND {send_transfer.id}. User host info not available directly in ContextManager.")
                        await send_transfer._update_status(DCCTransferStatus.FAILED, "Could not determine peer IP for passive send (host info unavailable).")
                        return
                    logger.info(f"Passive DCC SEND {send_transfer.id} accepted by {peer_nick}. They are listening on port {port_they_listen_on}. Connecting to {peer_actual_ip}:{port_they_listen_on}.")
                    asyncio.create_task(send_transfer.connect_and_send_passive(peer_actual_ip, port_they_listen_on))
                else:
                    logger.warning(f"DCC ACCEPT for token {token} but no matching passive SEND transfer found: {offer.transfer_id}")
            else:
                logger.warning(f"Invalid, expired, or mismatched DCC ACCEPT token {token} from {peer_nick} for '{filename}'.")
        else:
            logger.info(f"Received unhandled DCC command '{command}' from {peer_nick} for '{filename}'.")

    async def initiate_sends(self, peer_nick: str, local_filepaths: List[Union[str, Path]], passive: bool = False) -> List[Optional[str]]:
        if not self.dcc_config.enabled or not self.send_manager:
            logger.error("DCC system or SendManager not enabled/initialized. Cannot initiate send.")
            return [None] * len(local_filepaths)
        transfer_ids: List[Optional[str]] = []
        for filepath in local_filepaths:
            transfer = await self.send_manager.queue_send_request(peer_nick, filepath, passive)
            transfer_ids.append(transfer.id if transfer else None)
        return transfer_ids

    async def accept_passive_offer_by_token(self, peer_nick: str, filename: str, token: str) -> Optional[DCCReceiveTransfer]:
        if not self.dcc_config.enabled or not self.receive_manager or not self.passive_offer_manager:
            logger.error("DCC system or relevant managers not enabled/initialized. Cannot accept passive offer.")
            return None
        pending_receive_transfer: Optional[DCCReceiveTransfer] = None
        with self._lock:
            for t_id, t_obj in self.transfers.items():
                if isinstance(t_obj, DCCReceiveTransfer) and \
                   t_obj.peer_nick.lower() == peer_nick.lower() and \
                   t_obj.filename == filename and \
                   t_obj.passive_token == token and \
                   t_obj.status == DCCTransferStatus.PENDING and \
                   t_obj.is_passive:
                    pending_receive_transfer = t_obj
                    break
        if not pending_receive_transfer:
            logger.warning(f"No PENDING passive DCC receive offer found for {peer_nick}, file '{filename}', token {token} to accept.")
            await self.client_logic.add_status_message(f"No pending passive offer found for token {token}.", "error")
            return None
        logger.info(f"User accepted passive DCC SEND offer (token {token}) for {filename} from {peer_nick}. ID: {pending_receive_transfer.id}. Initiating passive receive setup.")
        asyncio.create_task(pending_receive_transfer.start())
        return pending_receive_transfer

    async def accept_active_offer(self, peer_nick: str, filename: str, ip_str: str, port: int, file_size: int) -> Optional[DCCReceiveTransfer]:
        if not self.dcc_config.enabled or not self.receive_manager:
            logger.error("DCC system or ReceiveManager not enabled/initialized. Cannot accept active offer.")
            return None
        transfer_id = self._generate_transfer_id()
        sanitized_filename = sanitize_filename(filename)
        placeholder_local_path = Path(self.dcc_config.download_dir) / sanitized_filename

        transfer = DCCReceiveTransfer(
            transfer_id=transfer_id,
            transfer_type=DCCTransferType.RECEIVE,
            peer_nick=peer_nick,
            filename=sanitized_filename,
            filesize=file_size,
            local_filepath=placeholder_local_path,
            dcc_manager_ref=self,
            dcc_config_ref=self.dcc_config,
            event_logger=self.dcc_event_logger,
            is_passive=False,
            remote_ip=ip_str,
            remote_port=port
        )
        self._add_transfer_to_tracking(transfer)
        logger.info(f"User accepted active DCC SEND offer for {filename} from {peer_nick}. ID: {transfer.id}. Initiating active receive.")
        asyncio.create_task(transfer.start())
        return transfer

    def get_transfer_by_id(self, transfer_id: str) -> Optional[DCCTransfer]:
        with self._lock:
            return self.transfers.get(transfer_id)

    def find_resumable_send_transfer(self, identifier: str) -> Optional[DCCSendTransfer]:
        with self._lock:
            for t_id, transfer_obj in self.transfers.items():
                if isinstance(transfer_obj, DCCSendTransfer) and t_id.startswith(identifier):
                    if transfer_obj.status in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.PAUSED]:
                        return transfer_obj
            for transfer_obj in self.transfers.values():
                if isinstance(transfer_obj, DCCSendTransfer) and transfer_obj.filename == identifier:
                    if transfer_obj.status in [DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED, DCCTransferStatus.PAUSED]:
                        return transfer_obj
        return None

    async def cancel_transfer_by_id_or_token(self, id_or_token_prefix: str, reason: str = "Cancelled by user command") -> bool:
        with self._lock:
            for transfer_id, transfer_obj in list(self.transfers.items()):
                if transfer_id.startswith(id_or_token_prefix):
                    if transfer_obj.status not in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED]:
                        logger.info(f"Cancelling transfer {transfer_id} ('{transfer_obj.filename}') by ID prefix '{id_or_token_prefix}'.")
                        asyncio.create_task(transfer_obj.cancel(reason))
                        return True
                    else:
                        logger.info(f"Transfer {transfer_id} already {transfer_obj.status.name}, cannot cancel.")
                        return False
            if self.passive_offer_manager:
                for token, offer in list(self.passive_offer_manager.pending_offers.items()):
                    if token.startswith(id_or_token_prefix):
                        transfer_obj = self.transfers.get(offer.transfer_id)
                        if transfer_obj and transfer_obj.status not in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED]:
                            logger.info(f"Cancelling transfer {offer.transfer_id} ('{offer.filename}') associated with passive token prefix '{id_or_token_prefix}'.")
                            self.passive_offer_manager.consume_token(token)
                            asyncio.create_task(transfer_obj.cancel(reason + " (passive offer cancelled)"))
                            return True
                        elif transfer_obj:
                             logger.info(f"Transfer {offer.transfer_id} for token {token} already {transfer_obj.status.name}, cannot cancel offer.")
                             return False
                        else:
                            logger.warning(f"Passive offer token {token} found, but no matching transfer object {offer.transfer_id}. Removing offer.")
                            self.passive_offer_manager.consume_token(token)
                            return True
        logger.warning(f"No active transfer or pending passive offer found matching prefix '{id_or_token_prefix}' to cancel.")
        return False

    def get_transfer_status_dict(self, transfer_id: str) -> Optional[Dict[str, Any]]:
        transfer = self.get_transfer_by_id(transfer_id)
        return transfer.get_status_dict() if transfer else None

    def list_transfers_as_dicts(self, status_filter_str: Optional[str] = None) -> List[Dict[str, Any]]:
        self._cleanup_transfers()
        results = []
        status_enum_filter: Optional[DCCTransferStatus] = None
        if status_filter_str:
            try:
                status_enum_filter = DCCTransferStatus[status_filter_str.upper()]
            except KeyError:
                logger.warning(f"Invalid status filter for list_transfers: '{status_filter_str}'")
        with self._lock:
            for transfer in self.transfers.values():
                if status_enum_filter is None or transfer.status == status_enum_filter:
                    results.append(transfer.get_status_dict())
        return sorted(results, key=lambda x: x.get("start_time") or float('-inf'), reverse=True)

    def get_local_ip_for_ctcp(self) -> str:
        return get_local_ip_for_ctcp(self.dcc_config, self.dcc_event_logger)

    def _cleanup_transfers(self):
        if not self.dcc_config.cleanup_enabled:
            return
        now = time.monotonic()
        max_age = self.dcc_config.transfer_max_age_seconds
        transfers_to_remove = []
        with self._lock:
            for transfer_id, transfer in self.transfers.items():
                if transfer.status in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED]:
                    if transfer.end_time and (now - transfer.end_time) > max_age:
                        transfers_to_remove.append(transfer_id)
            for transfer_id in transfers_to_remove:
                removed_transfer = self.transfers.pop(transfer_id, None)
                if removed_transfer:
                    logger.info(f"Cleaned up old DCC transfer: {transfer_id} ('{removed_transfer.filename}', status: {removed_transfer.status.name})")
        if transfers_to_remove:
             logger.info(f"DCC transfer cleanup: Removed {len(transfers_to_remove)} old transfers.")
        if self.passive_offer_manager:
            self.passive_offer_manager.cleanup_expired_offers()

    async def start_periodic_task(self):
        """Starts the periodic cleanup task if configured."""
        if self.dcc_config.enabled and self.dcc_config.cleanup_enabled and self.dcc_config.cleanup_interval_seconds > 0:
            if not self._cleanup_task_handle or self._cleanup_task_handle.done():
                self._cleanup_task_handle = asyncio.create_task(self._periodic_cleanup_task())
                logger.info(f"DCC cleanup task (re)started, runs every {self.dcc_config.cleanup_interval_seconds} seconds.")
            else:
                logger.info("DCC cleanup task already running.")
        else:
            logger.info("DCC cleanup task not started (disabled or interval is zero).")

    async def _periodic_cleanup_task(self):
        try:
            while True:
                await asyncio.sleep(self.dcc_config.cleanup_interval_seconds)
                if not self.dcc_config.enabled or not self.dcc_config.cleanup_enabled:
                    logger.info("Periodic DCC cleanup task stopping as DCC or cleanup is disabled.")
                    break
                logger.debug("Running periodic DCC transfer cleanup...")
                self._cleanup_transfers()
        except asyncio.CancelledError:
            logger.info("DCC periodic cleanup task was cancelled.")
            raise # Re-raise to allow awaiter to see it

    async def shutdown(self):
        logger.info("Shutting down DCCManager.")
        if self._cleanup_task_handle and not self._cleanup_task_handle.done():
            self._cleanup_task_handle.cancel()
            try:
                await self._cleanup_task_handle
            except asyncio.CancelledError:
                logger.info("DCC periodic cleanup task successfully cancelled and awaited.")
            except Exception as e:
                logger.error(f"DCC periodic cleanup task raised an exception during cancellation: {e}", exc_info=True)
            finally:
                # Additional check to log if task completed with an error not caught by CancelledError
                if self._cleanup_task_handle.done() and not self._cleanup_task_handle.cancelled():
                    exc = self._cleanup_task_handle.exception()
                    if exc:
                        logger.error(f"DCC cleanup task finished with an unhandled exception: {exc}", exc_info=exc)

        with self._lock:
            transfers_to_cancel = list(self.transfers.values())
        for transfer in transfers_to_cancel:
            if transfer.status not in [DCCTransferStatus.COMPLETED, DCCTransferStatus.FAILED, DCCTransferStatus.CANCELLED]:
                logger.info(f"Cancelling transfer {transfer.id} ('{transfer.filename}') due to DCCManager shutdown.")
                await transfer.cancel("DCC Manager shutting down")

        if self.send_manager:
            await self.send_manager.shutdown()
        if self.receive_manager:
            await self.receive_manager.shutdown()
        if self.passive_offer_manager:
            self.passive_offer_manager.shutdown()

        # Short sleep to allow any final async operations from sub-managers to settle
        await asyncio.sleep(0.1)
        with self._lock:
            self.transfers.clear()
        logger.info("DCCManager shutdown complete. All transfers cleared.")
