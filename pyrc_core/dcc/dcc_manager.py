import logging
import os
import time
import asyncio
import secrets
import threading
from typing import Dict, Optional, Any, Tuple, List, Callable, TYPE_CHECKING, Union
from pyrc_core.dcc.dcc_protocol import parse_dcc_ctcp
from pyrc_core.dcc.dcc_transfer import DCCSendTransfer, DCCReceiveTransfer, DCCStatus, DCCTransfer, DCCTransferType
from pyrc_core.dcc.dcc_utils import get_available_port, get_local_ip_for_connection, get_listening_socket, get_local_ip_for_ctcp, get_safe_dcc_path
from pyrc_core.dcc.dcc_passive_offer_manager import DCCPassiveOfferManager
from pyrc_core.app_config import AppConfig

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    from pyrc_core.event_manager import EventManager
    from pyrc_core.dcc.dcc_send_manager import DCCSendManager
    from pyrc_core.dcc.dcc_receive_manager import DCCReceiveManager

logger = logging.getLogger("pyrc.dcc.manager")

class DCCManager:
    def __init__(self, client_logic: 'IRCClient_Logic', event_manager: 'EventManager', config: AppConfig):
        self.client_logic = client_logic
        self.event_manager = event_manager
        self.config = config
        self.dcc_config = config.dcc  # shortcut
        self.transfers: Dict[str, DCCTransfer] = {}  # Key: transfer_id
        self._lock = threading.Lock()  # Protects the transfers dict
        self.dcc_event_logger = logging.getLogger("pyrc.dcc.events")
        self.send_manager: 'DCCSendManager' = None  # type: ignore
        self.receive_manager: 'DCCReceiveManager' = None  # type: ignore
        self.passive_offer_manager = DCCPassiveOfferManager(self._lock, self.dcc_event_logger, self.dcc_config)
        self.send_listening_servers: Dict[str, asyncio.Server] = {}  # Track servers for send

    def init_dcc_managers(self, send_manager: 'DCCSendManager', receive_manager: 'DCCReceiveManager'):
        """Initializes the send and receive managers after they are created."""
        self.send_manager = send_manager
        self.receive_manager = receive_manager

    def shutdown(self):
        """Shuts down the DCC manager and associated components."""
        logger.info("DCCManager shutting down.")
        # Shut down send and receive managers
        if self.send_manager and hasattr(self.send_manager, "shutdown"):
            self.send_manager.shutdown()  # Call shutdown method
        if self.receive_manager:
            self.receive_manager.shutdown()

        # Close any remaining listening sockets
        for transfer_id, server in list(self.send_listening_servers.items()):
            logger.info(f"Closing send listening server for {transfer_id}")
            server.close()
            asyncio.create_task(server.wait_closed())  # Ensure it's closed in event loop
            del self.send_listening_servers[transfer_id]
        self.send_listening_servers.clear()

        logger.info("DCCManager shutdown complete.")

    def _generate_transfer_id(self) -> str:
        """Generates a unique transfer ID."""
        return secrets.token_hex(16)

    async def accept_passive_offer_by_token(self, nick: str, filename: str, token: str) -> Dict[str, Any]:
        """Accepts a passive DCC offer by token."""
        # This method delegates offer acceptance to the DCCReceiveManager.
        # The DCCManager's role is to validate the offer and then pass it on.
        # The DCCReceiveManager handles the actual connection and data transfer.
        logger.info(f"DCCManager: Accepting passive offer from {nick} for '{filename}' with token {token}")
        offer_data = self.passive_offer_manager.retrieve_offer(token)  # No lock needed, handled internally

        if not offer_data:
            error_msg = f"DCCManager: No passive offer found from {nick} for '{filename}' with token {token}."
            logger.warning(error_msg)
            return {"success": False, "error": error_msg}

        peer_ip = offer_data.get("ip_str")
        file_size = offer_data.get("filesize")
        if not peer_ip or not file_size:
            error_msg = f"DCCManager: Passive offer missing ip or filesize. Cannot accept."
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        # Create a DCCTransfer object to represent the incoming transfer
        new_transfer_id = self._generate_transfer_id()

        # Use get_safe_dcc_path instead of sanitize_filename
        local_filepath = get_safe_dcc_path(self.dcc_config.download_dir, filename)
        if local_filepath is None:
            error_msg = f"Could not create safe local filepath for '{filename}'. Aborting passive offer acceptance."
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        incoming_transfer = DCCReceiveTransfer(
            transfer_id=new_transfer_id,
            transfer_type=DCCTransferType.RECEIVE,
            peer_nick=nick,
            filename=filename,
            file_size=file_size,
            local_filepath=local_filepath,
            dcc_manager_ref=self,
            peer_ip=peer_ip,
            dcc_event_logger=self.dcc_event_logger
        )

        # Add to overall transfers list
        self.transfers[new_transfer_id] = incoming_transfer

        # Delegate offer acceptance to DCCReceiveManager
        self.receive_manager.add_pending_dcc_offer(incoming_transfer)

        # Now tell the receive manager to accept the offer
        asyncio.create_task(self.receive_manager.accept_dcc_offer(new_transfer_id))

        self.passive_offer_manager.remove_offer(token)  # Clean up the offer, no lock needed, handled internally

        logger.info(f"DCCManager: Passive offer accepted. Delegated to DCCReceiveManager. Transfer ID: {new_transfer_id[:8]}")
        return {"success": True, "transfer_id": new_transfer_id}

    async def initiate_sends(self, peer_nick: str, local_filepaths: List[str], passive: bool = False) -> Dict[str, Any]:
        """Initiates DCC sends to a peer. Delegates send operations to DCCSendManager."""
        return await self.send_manager.initiate_sends(peer_nick, local_filepaths, passive)

    def update_transfer_status(self, transfer_id: str, new_status: DCCStatus, error_message: Optional[str] = None):
        """Updates the status of a DCC transfer."""
        with self._lock:
            if transfer_id in self.transfers:
                transfer = self.transfers[transfer_id]
                transfer.status = new_status  # Update status directly
                if error_message:
                    transfer.error_message = error_message
                logger.info(f"[{transfer_id}] Status updated to {new_status.name}. {error_message or ''}")
                asyncio.create_task(self.event_manager.dispatch_dcc_transfer_status_change(transfer))
            else:
                logger.warning(f"Attempted to update status for unknown transfer ID: {transfer_id}")

    def update_transfer_progress(self, transfer_id: str, bytes_transferred: int, file_size: int, current_rate_bps: float, estimated_eta_seconds: Optional[float]):
        """Updates the progress of a DCC transfer."""
        with self._lock:
            if transfer_id in self.transfers:
                transfer = self.transfers[transfer_id]
                # transfer.bytes_transferred = bytes_transferred # Already updated by the transfer object itself
                # transfer.file_size = file_size
                # transfer.current_rate_bps = current_rate_bps
                # transfer.estimated_eta_seconds = estimated_eta_seconds
                pass  # No dispatch, handled by transfer object itself
            else:
                logger.warning(f"Attempted to update progress for unknown transfer ID: {transfer_id}")

    def update_transfer_checksum_result(self, transfer_id: str, checksum_status: str):
        """Updates the checksum result of a DCC transfer."""
        with self._lock:
            if transfer_id in self.transfers:
                transfer = self.transfers[transfer_id]
                transfer.checksum_status = checksum_status
                pass  # No dispatch, handled by transfer object itself
            else:
                logger.warning(f"Attempted to update checksum for unknown transfer ID: {transfer_id}")

    async def cancel_transfer(self, transfer_id: str, reason: DCCStatus = DCCStatus.CANCELLED, error_msg: str = "Transfer cancelled by user") -> bool:
        """Cancels a DCC transfer."""
        with self._lock:
            if transfer_id in self.transfers:
                transfer = self.transfers[transfer_id]
                if transfer.status not in [DCCStatus.COMPLETED, DCCStatus.FAILED, DCCStatus.CANCELLED, DCCStatus.TIMED_OUT]:
                    logger.info(f"[{transfer_id}] Cancelling transfer. Current status: {transfer.status.name}")
                    await transfer.stop_transfer(reason, error_msg)
                    return True
                else:
                    logger.warning(f"[{transfer_id}] Attempted to cancel transfer in final state: {transfer.status.name}")
                    return False
            else:
                logger.warning(f"Attempted to cancel unknown transfer ID: {transfer_id}")
                return False

    def _process_next_in_send_queue(self, peer_nick: str):
        """Processes the next send operation in the queue for a given peer."""
        asyncio.create_task(self.send_manager.process_next_in_queue(peer_nick))

    def get_transfer_by_id(self, transfer_id: str) -> Optional[DCCTransfer]:
        """Retrieves a DCC transfer by its ID."""
        with self._lock:
            return self.transfers.get(transfer_id)

    def get_all_transfers(self) -> List[DCCTransfer]:
        """Returns a list of all DCC transfers."""
        with self._lock:
            return list(self.transfers.values())

    def _cleanup_stale_passive_offers(self):
        """Clean up stale passive DCC offers."""
        logger.debug("Cleaning up stale passive DCC offers.")
        self.passive_offer_manager.remove_stale_offers()

    async def handle_incoming_dcc_ctcp(self, nick: str, full_userhost: str, ctcp_payload: str):
        """Handles incoming DCC CTCP messages."""
        parsed_dcc_info = parse_dcc_ctcp(ctcp_payload)
        if not parsed_dcc_info:
            logger.warning(f"Failed to parse DCC CTCP payload: {ctcp_payload}")
            return

        dcc_command = parsed_dcc_info["command"]
        event_data = {
            "nick": nick,
            "full_userhost": full_userhost,
            "dcc_info": parsed_dcc_info
        }
        if dcc_command in ("SEND", "ACCEPT"):
            await self.event_manager.dispatch_event("INCOMING_DCC_SEND_OFFER", event_data)
        elif dcc_command == "RESUME":
            await self.event_manager.dispatch_event("INCOMING_DCC_RESUME_OFFER", event_data)
        else:
            logger.warning(f"Unknown DCC command: {dcc_command}")
