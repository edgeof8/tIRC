# tirc_core/dcc/dcc_passive_offer_manager.py
import logging
import time
import secrets # For generating secure random tokens
from typing import Dict, Optional, TYPE_CHECKING, List, Any # Added Any
from datetime import datetime, timezone # Added datetime, timezone

if TYPE_CHECKING:
    from tirc_core.config_defs import DccConfig

logger = logging.getLogger("tirc.dcc.passiveoffermgr")

class PassiveOffer:
    """Represents a pending passive DCC offer."""
    def __init__(self, token: str, transfer_id: str, peer_nick: str, filename: str, filesize: int, creation_time: float):
        self.token = token
        self.transfer_id = transfer_id # ID of the DCCTransfer object this offer is for
        self.peer_nick = peer_nick
        self.filename = filename
        self.filesize = filesize
        self.creation_time = creation_time # time.monotonic() float

    def is_expired(self, timeout_seconds: int) -> bool:
        return (time.monotonic() - self.creation_time) > timeout_seconds

    def __repr__(self):
        return f"<PassiveOffer token={self.token} transfer_id={self.transfer_id[:8]} file='{self.filename}' peer={self.peer_nick}>"


class DCCPassiveOfferManager:
    """Manages passive (reverse) DCC offers using tokens."""

    def __init__(self, dcc_config: "DccConfig"):
        self.dcc_config = dcc_config
        self.pending_offers: Dict[str, PassiveOffer] = {} # token -> PassiveOffer
        logger.info("DCCPassiveOfferManager initialized.")

    def generate_token(self, transfer_id: str, peer_nick: str, filename: str, filesize: int) -> str:
        """Generates a unique token for a passive offer and stores the offer."""
        token = secrets.token_hex(8)
        while token in self.pending_offers: # pragma: no cover
            token = secrets.token_hex(8)

        offer = PassiveOffer(
            token=token,
            transfer_id=transfer_id,
            peer_nick=peer_nick,
            filename=filename,
            filesize=filesize,
            creation_time=time.monotonic()
        )
        self.pending_offers[token] = offer
        logger.info(f"Generated passive DCC token {token} for transfer {transfer_id} ({filename} to {peer_nick}).")
        return token

    def get_offer_by_token(self, token: str) -> Optional[PassiveOffer]:
        """Retrieves a pending passive offer by its token."""
        offer = self.pending_offers.get(token)
        if offer:
            if offer.is_expired(self.dcc_config.passive_mode_token_timeout):
                logger.warning(f"Passive DCC offer with token {token} has expired. Removing.")
                del self.pending_offers[token]
                return None
            return offer
        return None

    def consume_token(self, token: str) -> Optional[PassiveOffer]:
        """
        Retrieves and removes a pending passive offer by its token.
        """
        offer = self.pending_offers.pop(token, None)
        if offer:
            if offer.is_expired(self.dcc_config.passive_mode_token_timeout):
                logger.warning(f"Passive DCC token {token} was consumed but had already expired.")
            logger.info(f"Consumed passive DCC token {token} for transfer {offer.transfer_id}.")
        else:
            logger.warning(f"Attempted to consume non-existent or already consumed/expired passive DCC token: {token}")
        return offer

    def cleanup_expired_offers(self):
        """Removes all expired passive offers."""
        now = time.monotonic()
        expired_tokens = [
            token for token, offer in self.pending_offers.items()
            if (now - offer.creation_time) > self.dcc_config.passive_mode_token_timeout
        ]
        for token in expired_tokens:
            offer = self.pending_offers.pop(token, None)
            if offer:
                logger.info(f"Cleaned up expired passive DCC offer token {token} for transfer {offer.transfer_id} ({offer.filename}).")
        if expired_tokens:
            logger.info(f"Passive offer cleanup: Removed {len(expired_tokens)} expired offers.")

    def get_pending_offers_for_peer(self, peer_nick: str) -> List[PassiveOffer]:
        """Returns a list of non-expired pending offers for a specific peer."""
        self.cleanup_expired_offers()
        return [
            offer for offer in self.pending_offers.values()
            if offer.peer_nick.lower() == peer_nick.lower()
        ]

    def _get_all_pending_offers_objects(self) -> List[PassiveOffer]: # Renamed for clarity
        """Returns a list of all non-expired pending PassiveOffer objects."""
        self.cleanup_expired_offers()
        return list(self.pending_offers.values())

    def get_all_pending_offers_info(self) -> List[Dict[str, Any]]:
        """
        Returns a list of dictionaries, each representing a pending passive offer,
        formatted for display or API use.
        """
        offers = self._get_all_pending_offers_objects()
        offers_info: List[Dict[str, Any]] = []
        for offer in offers:
            # Convert creation_time (monotonic) to an estimated absolute time for display.
            # This is an approximation as monotonic time doesn't directly map to wall clock.
            # We'll use current wall clock time minus elapsed monotonic time.
            elapsed_seconds = time.monotonic() - offer.creation_time
            approx_offer_datetime = datetime.now(timezone.utc) - timedelta(seconds=elapsed_seconds)

            offers_info.append({
                "token": offer.token,
                "transfer_id": offer.transfer_id,
                "peer_nick": offer.peer_nick,
                "filename": offer.filename,
                "filesize": offer.filesize,
                "offer_time_iso": approx_offer_datetime.isoformat(), # Store as ISO string
                "age_seconds": int(elapsed_seconds)
            })
        return offers_info

    def shutdown(self):
        logger.info("Shutting down DCCPassiveOfferManager. Clearing all pending offers.")
        self.pending_offers.clear()
        logger.info("DCCPassiveOfferManager shutdown complete.")

from datetime import timedelta # Add timedelta import at the end or top
