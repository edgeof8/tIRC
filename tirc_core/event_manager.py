# event_manager.py
import logging
import time
from typing import TYPE_CHECKING, Dict, Any, Optional, List, Set, Callable
import asyncio
from tirc_core.dcc.dcc_transfer import DCCTransfer, DCCTransferType # Keep this import

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.event_manager")

class EventManager:
    def __init__(self, client_logic_ref: "IRCClient_Logic"):
        self.client_logic = client_logic_ref
        self.subscriptions: Dict[str, List[Dict[str, Any]]] = {}
        logger.info("EventManager initialized.")

    def subscribe(
        self, event_name: str, handler_function: Callable, script_name: str
    ) -> None:
        """Subscribe a script's handler function to an event."""
        if not callable(handler_function):
            logger.error(
                f"Script '{script_name}' attempted to subscribe non-callable handler for event '{event_name}'."
            )
            return
        if event_name not in self.subscriptions:
            self.subscriptions[event_name] = []

        for sub in self.subscriptions[event_name]:
            if sub["handler"] == handler_function and sub["script_name"] == script_name:
                logger.warning(
                    f"Script '{script_name}' handler already subscribed to event '{event_name}'. Ignoring duplicate."
                )
                return

        self.subscriptions[event_name].append(
            {"handler": handler_function, "script_name": script_name, "enabled": True}
        )
        logger.info(
            f"Script '{script_name}' subscribed to event '{event_name}' with handler '{handler_function.__name__}'."
        )

    def unsubscribe(
        self, event_name: str, handler_function: Callable, script_name: str
    ):
        """Unsubscribe a script's handler function from an event."""
        if event_name in self.subscriptions:
            self.subscriptions[event_name] = [
                sub
                for sub in self.subscriptions[event_name]
                if not (
                    sub["handler"] == handler_function
                    and sub["script_name"] == script_name
                )
            ]
            if not self.subscriptions[event_name]:
                del self.subscriptions[event_name]
            logger.info(
                f"Script '{script_name}' unsubscribed handler '{handler_function.__name__}' from event '{event_name}'."
            )
        else:
            logger.debug(f"Attempted to unsubscribe from event '{event_name}' for script '{script_name}', but no subscriptions found for this event.")


    def _prepare_base_event_data(self, raw_line: str = "") -> Dict[str, Any]:
        """Prepares a base dictionary with common event data."""
        return {
            "timestamp": time.time(),
            "raw_line": raw_line,
            "client_nick": (lambda:
                (conn_info := self.client_logic.state_manager.get_connection_info() if
                    (self.client_logic and
                     self.client_logic.state_manager)
                    else None) and
                hasattr(conn_info, 'nick') and
                conn_info.nick or "UnknownNick")(),
        }

    async def dispatch_event(self, event_name: str, specific_event_data: Dict[str, Any], raw_line: str = ""):
        base_data = self._prepare_base_event_data(raw_line)
        final_event_data = {**base_data, **specific_event_data}

        if "raw_line" in specific_event_data and specific_event_data["raw_line"]:
            final_event_data["raw_line"] = specific_event_data["raw_line"]
        elif raw_line:
            final_event_data["raw_line"] = raw_line

        if "client_nick" not in final_event_data:
             final_event_data["client_nick"] = (lambda:
                (conn_info := self.client_logic.state_manager.get_connection_info() if
                    (self.client_logic and
                     self.client_logic.state_manager)
                    else None) and
                hasattr(conn_info, 'nick') and
                conn_info.nick or "UnknownNick")()

        logger.debug(f"Dispatching event '{event_name}' with data: {final_event_data}")
        if event_name in self.subscriptions:
            for subscription in list(self.subscriptions[event_name]):
                if not subscription.get("enabled", True):
                    continue
                handler = subscription["handler"]
                script_name = subscription["script_name"]
                try:
                    logger.debug(
                        f"Calling handler '{getattr(handler, '__name__', 'unknown')}' from script '{script_name}' for event '{event_name}'."
                    )
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(final_event_data))
                        logger.debug(f"Scheduled async event handler '{getattr(handler, '__name__', 'unknown')}' for event '{event_name}' from script '{script_name}'.")
                    else:
                        handler(final_event_data)
                except Exception as e:
                    logger.error(
                        f"Error in event handler '{getattr(handler, '__name__', 'unknown')}' from script '{script_name}' for event '{event_name}': {e}",
                        exc_info=True,
                    )
                    error_message = f"Error in script '{script_name}' event handler for '{event_name}': {e}"
                    await self.client_logic.add_message(
                        error_message,
                        self.client_logic.ui.colors.get("error", 0),
                        context_name="Status",
                    )
                    subscription["enabled"] = False
                    logger.warning(
                        f"Disabled event handler '{getattr(handler, '__name__', 'unknown')}' from script '{script_name}' due to error."
                    )
        else:
            logger.debug(f"No subscriptions found for event '{event_name}'.")


    async def dispatch_client_connected(self, server: str, port: int, nick: str, ssl: bool, raw_line: str = ""):
        data = {"server": server, "port": port, "nick": nick, "ssl": ssl}
        await self.dispatch_event("CLIENT_CONNECTED", data, raw_line)

    async def dispatch_client_disconnected(self, server: str, port: int, raw_line: str = ""):
        data = {"server": server, "port": port}
        await self.dispatch_event("CLIENT_DISCONNECTED", data, raw_line)

    async def dispatch_client_registered(self, nick: str, server_message: str, raw_line: str = ""):
        data = {"nick": nick, "server_message": server_message}
        await self.dispatch_event("CLIENT_REGISTERED", data, raw_line)
        await self.dispatch_client_ready(nick, raw_line)


    async def dispatch_client_ready(self, nick: str, raw_line: str = ""):
        data = {"nick": nick, "client_logic_ref": self.client_logic}
        await self.dispatch_event("CLIENT_READY", data, raw_line)

    async def dispatch_client_nick_changed(self, old_nick: str, new_nick: str, raw_line: str = ""):
        data = {"old_nick": old_nick, "new_nick": new_nick}
        await self.dispatch_event("CLIENT_NICK_CHANGED", data, raw_line)

    async def dispatch_client_shutdown_final(self, raw_line: str = ""):
        await self.dispatch_event("CLIENT_SHUTDOWN_FINAL", {}, raw_line)

    async def dispatch_privmsg(self, nick: str, userhost: str, target: str, message: str, is_channel_msg: bool, tags: Dict[str, Any], raw_line: str = ""):
        data = {
            "nick": nick, "userhost": userhost, "target": target,
            "message": message, "is_channel_msg": is_channel_msg, "tags": tags
        }
        await self.dispatch_event("PRIVMSG", data, raw_line)

    async def dispatch_notice(self, nick: Optional[str], userhost: Optional[str], target: str, message: str, is_channel_notice: bool, tags: Dict[str, Any], raw_line: str = ""):
        data = {
            "nick": nick or "", "userhost": userhost or "", "target": target,
            "message": message, "is_channel_notice": is_channel_notice, "tags": tags
        }
        await self.dispatch_event("NOTICE", data, raw_line)

    async def dispatch_join(self, nick: str, userhost: Optional[str], channel: str, account: Optional[str], real_name: Optional[str], is_self: bool, raw_line: str = ""):
        data = {
            "nick": nick, "userhost": userhost, "channel": channel,
            "account": account, "real_name": real_name, "is_self": is_self
        }
        await self.dispatch_event("JOIN", data, raw_line)

    async def dispatch_channel_fully_joined(self, channel_name: str, raw_line: str = ""):
        data = {"channel_name": channel_name}
        await self.dispatch_event("CHANNEL_FULLY_JOINED", data, raw_line)

    async def dispatch_part(self, nick: str, userhost: str, channel: str, reason: str, is_self: bool, raw_line: str = ""):
        data = {
            "nick": nick, "userhost": userhost, "channel": channel,
            "reason": reason, "is_self": is_self
        }
        await self.dispatch_event("PART", data, raw_line)

    async def dispatch_quit(self, nick: str, userhost: str, reason: str, raw_line: str = ""):
        data = {"nick": nick, "userhost": userhost, "reason": reason}
        await self.dispatch_event("QUIT", data, raw_line)

    async def dispatch_nick(self, old_nick: str, new_nick: str, userhost: str, is_self: bool, raw_line: str = ""):
        data = {
            "old_nick": old_nick, "new_nick": new_nick,
            "userhost": userhost, "is_self": is_self
        }
        await self.dispatch_event("NICK", data, raw_line)

    async def dispatch_mode(self, target_name: str, setter_nick: Optional[str], setter_userhost: Optional[str], mode_string: str, mode_params: List[str], parsed_modes: List[Dict[str, Any]], raw_line: str = ""):
        data = {
            "target": target_name, "setter": setter_nick, "setter_userhost": setter_userhost,
            "mode_string": mode_string, "mode_params": mode_params, "parsed_modes": parsed_modes
        }
        await self.dispatch_event("MODE", data, raw_line)

    async def dispatch_channel_mode_applied(self, channel: str, setter_nick: Optional[str], setter_userhost: Optional[str], mode_changes: List[Dict[str, Any]], current_channel_modes: List[str], raw_line: str = ""):
        data = {
            "channel": channel, "setter_nick": setter_nick, "setter_userhost": setter_userhost,
            "mode_changes": mode_changes, "current_channel_modes": current_channel_modes
        }
        await self.dispatch_event("CHANNEL_MODE_APPLIED", data, raw_line)


    async def dispatch_topic(self, nick: Optional[str], userhost: Optional[str], channel: str, topic: str, raw_line: str = ""):
        data = {"nick": nick, "userhost": userhost, "channel": channel, "topic": topic}
        await self.dispatch_event("TOPIC", data, raw_line)

    async def dispatch_chghost(self, nick: str, new_ident: str, new_host: str, old_userhost: str, raw_line: str = ""):
        data = {"nick": nick, "new_ident": new_ident, "new_host": new_host, "userhost": old_userhost}
        await self.dispatch_event("CHGHOST", data, raw_line)

    async def dispatch_message_added_to_context(
        self,
        context_name: str,
        text: str,
        color_key: str,
        source_full_ident: Optional[str] = None,
        is_privmsg_or_notice: bool = False,
        raw_line: str = ""
    ):
        data = {
            "context_name": context_name,
            "text": text,
            "color_key": color_key,
            "source_full_ident": source_full_ident,
            "is_privmsg_or_notice": is_privmsg_or_notice
        }
        await self.dispatch_event("CLIENT_MESSAGE_ADDED_TO_CONTEXT", data, raw_line)

    async def dispatch_raw_server_message(self, client: "IRCClient_Logic", line: str, raw_line: str = ""):
        data = {"client": client, "line": line}
        await self.dispatch_event("RAW_SERVER_MESSAGE", data, raw_line)

    async def dispatch_dcc_transfer_status_change(self, transfer: 'DCCTransfer', raw_line: str = ""):
        data = {
            "transfer_id": transfer.id,
            "transfer_type": transfer.type.name, # Corrected
            "peer_nick": transfer.peer_nick,
            "filename": transfer.filename,
            "file_size": transfer.expected_filesize, # Corrected
            "bytes_transferred": transfer.bytes_transferred,
            "status": transfer.status.name,
            "error_message": transfer.error_message,
            "local_filepath": str(transfer.local_filepath), # Ensure string
            "checksum_local": transfer.checksum_local, # Added
            "checksum_remote": transfer.checksum_remote, # Added
            "checksum_match": transfer.checksum_match, # Corrected from checksum_status
            "is_incoming": transfer.type == DCCTransferType.RECEIVE, # Corrected
        }
        await self.dispatch_event("DCC_TRANSFER_STATUS_CHANGE", data, raw_line)

    async def dispatch_dcc_transfer_progress(self, transfer: 'DCCTransfer', raw_line: str = ""):
        data = {
            "transfer_id": transfer.id,
            "transfer_type": transfer.type.name, # Corrected
            "peer_nick": transfer.peer_nick,
            "filename": transfer.filename,
            "file_size": transfer.expected_filesize, # Corrected
            "bytes_transferred": transfer.bytes_transferred,
            "current_rate_bps": transfer.current_rate_bps,
            "estimated_eta_seconds": transfer.estimated_eta_seconds,
            "is_incoming": transfer.type == DCCTransferType.RECEIVE, # Corrected
        }
        await self.dispatch_event("DCC_TRANSFER_PROGRESS", data, raw_line)

    async def dispatch_dcc_transfer_checksum_update(self, transfer: 'DCCTransfer', raw_line: str = ""):
        data = {
            "transfer_id": transfer.id,
            "transfer_type": transfer.type.name, # Corrected
            "peer_nick": transfer.peer_nick,
            "filename": transfer.filename,
            "checksum_local": transfer.checksum_local, # Added
            "checksum_remote": transfer.checksum_remote, # Added
            "checksum_match": transfer.checksum_match, # Corrected from checksum_status
            "is_incoming": transfer.type == DCCTransferType.RECEIVE, # Corrected
        }
        await self.dispatch_event("DCC_TRANSFER_CHECKSUM_UPDATE", data, raw_line)

    async def dispatch_raw_irc_numeric(self, numeric: int, source: Optional[str], params_list: List[str], display_params_list: List[str], trailing: Optional[str], tags: Dict[str, Any], raw_line: str = ""):
        data = {
            "numeric": numeric, "source": source, "params_list": params_list,
            "display_params_list": display_params_list, "trailing": trailing, "tags": tags
        }
        await self.dispatch_event("RAW_IRC_NUMERIC", data, raw_line)
