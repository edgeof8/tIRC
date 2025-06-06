import logging
import time
from typing import Dict, Optional, Any, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.dcc.dcc_manager import DCCManager # To avoid circular import for type hinting

logger = logging.getLogger("pyrc.dcc.passiveoffermgr")

class DCCPassiveOfferManager:
    def __init__(self, manager_ref: 'DCCManager'):
        self.manager = manager_ref
        self.dcc_event_logger = manager_ref.dcc_event_logger
        self._lock = manager_ref._lock # Use the manager's lock for consistency
        self.pending_passive_offers: Dict[str, Dict[str, Any]] = {}

    def store_offer(self, token: str, nick: str, filename: str, filesize: int, ip_str: str, userhost: str) -> None:
        """Stores a new passive DCC SEND offer."""
        with self._lock:
            self.pending_passive_offers[token] = {
                "nick": nick,
                "filename": filename,
                "filesize": filesize,
                "ip_str": ip_str,
                "userhost": userhost,
                "timestamp": time.time()
            }
        self.dcc_event_logger.info(f"Stored pending passive DCC SEND offer from {nick} for '{filename}' (IP: {ip_str}) with token {token}.")
        # Opportunistic cleanup can be called by DCCManager after this
        # self.cleanup_stale_offers(self.manager.dcc_config.get("passive_mode_token_timeout", 120))


    def get_offer(self, token: str) -> Optional[Dict[str, Any]]:
        """Retrieves a pending offer by its exact token."""
        with self._lock:
            return self.pending_passive_offers.get(token)

    def remove_offer(self, token: str) -> bool:
        """Removes an offer by its exact token. Returns True if removed, False otherwise."""
        with self._lock:
            if token in self.pending_passive_offers:
                del self.pending_passive_offers[token]
                self.dcc_event_logger.info(f"Removed pending passive offer with token {token}.")
                return True
            return False

    def cleanup_stale_offers(self) -> int:
        """Removes pending passive offers that have timed out. Returns count of removed offers."""
        now = time.time()
        stale_tokens = []
        timeout_duration = self.manager.dcc_config.get("passive_mode_token_timeout", 120)

        with self._lock:
            for token, offer_details in self.pending_passive_offers.items():
                if now - offer_details.get("timestamp", 0) > timeout_duration:
                    stale_tokens.append(token)

            for token in stale_tokens:
                if token in self.pending_passive_offers: # Double check before del
                    del self.pending_passive_offers[token]
                    self.dcc_event_logger.info(f"Removed stale passive DCC offer with token {token} due to timeout.")

        if stale_tokens:
            self.dcc_event_logger.debug(f"Cleaned up {len(stale_tokens)} stale passive DCC offer(s).")
        return len(stale_tokens)

    def cancel_offer_by_prefix(self, token_prefix: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Cancels a pending passive DCC SEND offer based on a token prefix.
        Returns (actual_token_cancelled, cancelled_offer_details) or (None, None).
        """
        if not token_prefix:
            return None, None

        actual_token_cancelled: Optional[str] = None
        cancelled_offer_details: Optional[Dict[str, Any]] = None

        with self._lock:
            for token, offer_details in list(self.pending_passive_offers.items()): # list() for safe iteration
                if token.startswith(token_prefix):
                    actual_token_cancelled = token
                    cancelled_offer_details = self.pending_passive_offers.pop(token)
                    break

        if cancelled_offer_details and actual_token_cancelled:
            self.dcc_event_logger.info(
                f"Cancelled pending passive DCC SEND offer with token {actual_token_cancelled} "
                f"(matched by prefix '{token_prefix}')."
            )
        else:
            self.dcc_event_logger.debug(f"No pending passive offer found starting with token prefix '{token_prefix}'.")

        return actual_token_cancelled, cancelled_offer_details

    def get_status_lines(self) -> List[str]:
        """Returns a list of formatted strings representing pending passive offers."""
        status_lines: List[str] = []
        with self._lock:
            if not self.pending_passive_offers:
                return []

            status_lines.append("--- Pending Passive Offers (Incoming) ---")
            sorted_passive_offers = sorted(
                self.pending_passive_offers.items(),
                key=lambda item: item[1].get("timestamp", 0),
                reverse=True
            )

            for token, offer_details in sorted_passive_offers:
                nick = offer_details.get("nick", "Unknown")
                filename = offer_details.get("filename", "UnknownFile")
                filesize_bytes = offer_details.get("filesize", 0)
                filesize_mb = filesize_bytes / (1024*1024)
                timestamp = offer_details.get("timestamp", 0)
                age_seconds = time.time() - timestamp

                line = (f"Token: {token[:8]}... From: {nick}, File: '{filename}' ({filesize_mb:.2f}MB). "
                        f"Received: {age_seconds:.0f}s ago. "
                        f"Use: /dcc get {nick} \"{filename}\" --token {token}")
                status_lines.append(line)
        return status_lines
