# commands/dcc/dcc_list_command.py
import logging
from typing import TYPE_CHECKING, List, Dict, Any, Optional
from datetime import datetime, timezone # Import timezone
import time # For time.monotonic()

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.dcc.dcc_transfer import DCCTransferStatus # For type hint

logger = logging.getLogger("tirc.commands.dcc.list")

COMMAND_DEFINITIONS = [
    {
        "name": "dcc_list",
        "handler": "handle_dcc_list_command",
        "help": {
            "usage": "/dcc_list [active|completed|failed|pending|queued|all]",
            "description": "Lists DCC transfers. Default is 'active'. 'pending' shows passive offers you've received.",
            "aliases": ["dccstatus", "dccs"]
        }
    }
]

def format_filesize(size_bytes: int) -> str:
    """Formats a filesize in bytes to a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def format_duration(seconds: float) -> str:
    """Formats a duration in seconds to H:M:S or M:S string."""
    if seconds < 0: return "N/A"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

async def handle_dcc_list_command(client: "IRCClient_Logic", args_str: str):
    """Handles the /dcc_list command."""
    status_filter_str = args_str.strip().lower() if args_str else "active"
    active_context_name = client.context_manager.active_context_name or "Status"
    dcc_ui_context = client.dcc_manager.dcc_ui_context_name if client.dcc_manager else "Status"

    if not client.dcc_manager or not client.config.dcc.enabled:
        await client.add_message("DCC system is not enabled.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    transfers_data: List[Dict[str, Any]] = []
    if status_filter_str == "pending": # Special case for passive offers
        if client.dcc_manager.passive_offer_manager:
            pending_offers = client.dcc_manager.passive_offer_manager.get_all_pending_offers_info()
            for offer in pending_offers:
                # Adapt offer structure to look like a transfer for display
                transfers_data.append({
                    "id": offer.get("token", "N/A")[:8], # Show token prefix as ID
                    "type": "PASSIVE_OFFER",
                    "status": "PENDING_ACCEPT",
                    "peer_nick": offer.get("peer_nick", "Unknown"),
                    "filename": offer.get("filename", "Unknown"),
                    "filesize_total": offer.get("filesize", 0),
                    "start_time": offer.get("offer_time_iso"), # Assuming offer_time is stored as iso
                    "eta_seconds": None,
                    "rate_bps": 0,
                    "progress_percent": 0,
                    "is_passive_offer": True # Flag for display
                })
        else:
            await client.add_message("Passive offer manager not available.", client.ui.colors.get("warning", 0), context_name=dcc_ui_context)
    else:
        # Map user-friendly filter to DCCTransferStatus enum names if needed
        # For now, assume status_filter_str matches enum names or "all"
        filter_to_pass = status_filter_str if status_filter_str != "all" else None
        transfers_data = client.dcc_manager.list_transfers_as_dicts(filter_to_pass)


    if not transfers_data:
        await client.add_message(f"No DCC transfers or offers matching filter '{status_filter_str}'.", client.ui.colors.get("system", 0), context_name=dcc_ui_context)
        if client.context_manager.active_context_name != dcc_ui_context:
            await client.view_manager.switch_active_context(dcc_ui_context) # Corrected call
        return

    await client.add_message(f"--- DCC Transfers ({status_filter_str.capitalize()}) ---", client.ui.colors.get("info_header", 0), context_name=dcc_ui_context)

    for td in transfers_data:
        transfer_id_short = str(td.get("id", "N/A"))[:8]
        ttype = str(td.get("type", "N/A")).replace("DCCTransferType.", "")
        status = str(td.get("status", "N/A")).replace("DCCTransferStatus.", "")
        peer = td.get("peer_nick", "N/A")
        fname = td.get("filename", "N/A")
        fsize_total = td.get("filesize_total", 0)
        fsize_transferred = td.get("filesize_transferred", 0)

        start_time_iso = td.get("start_time")
        start_time_str = "Not started"
        if start_time_iso:
            try:
                dt_obj = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00"))
                start_time_str = dt_obj.strftime("%H:%M:%S")
            except: # Catch all for parsing, as format might vary
                start_time_str = start_time_iso[:19] # Fallback

        eta_sec = td.get("eta_seconds")
        eta_str = format_duration(eta_sec) if eta_sec is not None else "N/A"

        rate_bps = td.get("rate_bps", 0)
        rate_str = f"{format_filesize(int(rate_bps))}/s" if rate_bps > 0 else "0 B/s"

        progress = td.get("progress_percent", 0)

        if td.get("is_passive_offer"):
            line = f"Offer ID: {transfer_id_short} | From: {peer} | File: {fname} ({format_filesize(fsize_total)}) | Offered: {start_time_str}"
        else:
            line = f"ID: {transfer_id_short} | {ttype} | {status} | Peer: {peer} | File: {fname}"
            line += f" | {format_filesize(fsize_transferred)}/{format_filesize(fsize_total)} ({progress:.1f}%)"
            if status not in ["COMPLETED", "FAILED", "CANCELLED"]:
                 line += f" | Rate: {rate_str} | ETA: {eta_str}"
            if td.get("error_message"):
                line += f" | Error: {td['error_message']}"

        await client.add_message(line, client.ui.colors.get("system", 0), context_name=dcc_ui_context)

    if client.context_manager.active_context_name != dcc_ui_context:
        await client.view_manager.switch_active_context(dcc_ui_context) # Corrected call
