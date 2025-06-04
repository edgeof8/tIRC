# event_manager.py
import logging
import time
from typing import TYPE_CHECKING, Dict, Any, Optional, List, Set # Added List, Set

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic
    from script_manager import ScriptManager

logger = logging.getLogger("pyrc.event_manager")

class EventManager:
    def __init__(self, client_logic_ref: "IRCClient_Logic", script_manager_ref: "ScriptManager"):
        self.client_logic = client_logic_ref
        self.script_manager = script_manager_ref
        logger.info("EventManager initialized.")

    def _prepare_base_event_data(self, raw_line: str = "") -> Dict[str, Any]:
        """Prepares a base dictionary with common event data."""
        return {
            "timestamp": time.time(),
            "raw_line": raw_line,
            "client_nick": self.client_logic.nick if self.client_logic else "UnknownNick",
        }

    def dispatch_event(self, event_name: str, specific_event_data: Dict[str, Any], raw_line: str = ""):
        """
        Dispatches an event by merging base event data with specific event data
        and then calling the script_manager.
        """
        base_data = self._prepare_base_event_data(raw_line)
        final_event_data = {**base_data, **specific_event_data} # Specific data overwrites base if keys clash

        # Ensure specific raw_line for the event takes precedence if provided in specific_event_data
        if "raw_line" in specific_event_data and specific_event_data["raw_line"]:
            final_event_data["raw_line"] = specific_event_data["raw_line"]
        elif raw_line: # Use raw_line passed to dispatch_event if specific_event_data didn't have one
            final_event_data["raw_line"] = raw_line

        self.script_manager.dispatch_event(event_name, final_event_data)
        logger.debug(f"Dispatched event '{event_name}' via EventManager with data: {final_event_data}")

    # --- Client Lifecycle Event Dispatchers ---
    def dispatch_client_connected(self, server: str, port: int, nick: str, ssl: bool, raw_line: str = ""):
        data = {"server": server, "port": port, "nick": nick, "ssl": ssl}
        self.dispatch_event("CLIENT_CONNECTED", data, raw_line)

    def dispatch_client_disconnected(self, server: str, port: int, raw_line: str = ""):
        data = {"server": server, "port": port}
        self.dispatch_event("CLIENT_DISCONNECTED", data, raw_line)

    def dispatch_client_registered(self, nick: str, server_message: str, raw_line: str = ""):
        data = {"nick": nick, "server_message": server_message}
        self.dispatch_event("CLIENT_REGISTERED", data, raw_line)
        # Dispatch CLIENT_READY immediately after CLIENT_REGISTERED for now
        # In future, CLIENT_READY might have more conditions (e.g., initial channels joined)
        self.dispatch_client_ready(nick, raw_line)


    def dispatch_client_ready(self, nick: str, raw_line: str = ""):
        # client_logic_ref is passed so scripts can interact further if needed
        data = {"nick": nick, "client_logic_ref": self.client_logic}
        self.dispatch_event("CLIENT_READY", data, raw_line)

    def dispatch_client_nick_changed(self, old_nick: str, new_nick: str, raw_line: str = ""):
        data = {"old_nick": old_nick, "new_nick": new_nick}
        self.dispatch_event("CLIENT_NICK_CHANGED", data, raw_line)

    def dispatch_client_shutdown_final(self, raw_line: str = ""):
        self.dispatch_event("CLIENT_SHUTDOWN_FINAL", {}, raw_line)

    # --- IRC Message & Command Event Dispatchers ---
    def dispatch_privmsg(self, nick: str, userhost: str, target: str, message: str, is_channel_msg: bool, tags: Dict[str, Any], raw_line: str = ""):
        data = {
            "nick": nick, "userhost": userhost, "target": target,
            "message": message, "is_channel_msg": is_channel_msg, "tags": tags
        }
        self.dispatch_event("PRIVMSG", data, raw_line)

    def dispatch_notice(self, nick: Optional[str], userhost: Optional[str], target: str, message: str, is_channel_notice: bool, tags: Dict[str, Any], raw_line: str = ""):
        data = {
            "nick": nick or "", "userhost": userhost or "", "target": target,
            "message": message, "is_channel_notice": is_channel_notice, "tags": tags
        }
        self.dispatch_event("NOTICE", data, raw_line)

    def dispatch_join(self, nick: str, userhost: Optional[str], channel: str, account: Optional[str], real_name: Optional[str], is_self: bool, raw_line: str = ""):
        data = {
            "nick": nick, "userhost": userhost, "channel": channel,
            "account": account, "real_name": real_name, "is_self": is_self
        }
        self.dispatch_event("JOIN", data, raw_line)

    def dispatch_channel_fully_joined(self, channel_name: str, raw_line: str = ""):
        data = {"channel_name": channel_name}
        self.dispatch_event("CHANNEL_FULLY_JOINED", data, raw_line)

    def dispatch_part(self, nick: str, userhost: str, channel: str, reason: str, is_self: bool, raw_line: str = ""):
        data = {
            "nick": nick, "userhost": userhost, "channel": channel,
            "reason": reason, "is_self": is_self
        }
        self.dispatch_event("PART", data, raw_line)

    def dispatch_quit(self, nick: str, userhost: str, reason: str, raw_line: str = ""):
        data = {"nick": nick, "userhost": userhost, "reason": reason}
        self.dispatch_event("QUIT", data, raw_line)

    def dispatch_nick(self, old_nick: str, new_nick: str, userhost: str, is_self: bool, raw_line: str = ""):
        data = {
            "old_nick": old_nick, "new_nick": new_nick,
            "userhost": userhost, "is_self": is_self # Corrected from source_userhost
        }
        self.dispatch_event("NICK", data, raw_line)

    def dispatch_mode(self, target_name: str, setter_nick: Optional[str], setter_userhost: Optional[str], mode_string: str, mode_params: List[str], parsed_modes: List[Dict[str, Any]], raw_line: str = ""):
        data = {
            "target": target_name, "setter": setter_nick, "setter_userhost": setter_userhost,
            "mode_string": mode_string, "mode_params": mode_params, "parsed_modes": parsed_modes
        }
        self.dispatch_event("MODE", data, raw_line)

    def dispatch_channel_mode_applied(self, channel: str, setter_nick: Optional[str], setter_userhost: Optional[str], mode_changes: List[Dict[str, Any]], current_channel_modes: List[str], raw_line: str = ""):
        data = {
            "channel": channel, "setter_nick": setter_nick, "setter_userhost": setter_userhost, # Changed 'setter' to 'setter_nick' for consistency
            "mode_changes": mode_changes, "current_channel_modes": current_channel_modes
        }
        self.dispatch_event("CHANNEL_MODE_APPLIED", data, raw_line)


    def dispatch_topic(self, nick: Optional[str], userhost: Optional[str], channel: str, topic: str, raw_line: str = ""):
        data = {"nick": nick, "userhost": userhost, "channel": channel, "topic": topic}
        self.dispatch_event("TOPIC", data, raw_line)

    def dispatch_chghost(self, nick: str, new_ident: str, new_host: str, old_userhost: str, raw_line: str = ""): # Changed userhost to old_userhost
        data = {"nick": nick, "new_ident": new_ident, "new_host": new_host, "userhost": old_userhost}
        self.dispatch_event("CHGHOST", data, raw_line)

    # --- Raw IRC Line & Numeric Event Dispatchers ---
    # RAW_IRC_LINE is special: typically dispatched directly by ScriptManager before IRCMessage parsing if needed.
    # If EventManager were to handle it, it would need the raw line before parsing.
    # For now, let's assume ScriptManager handles RAW_IRC_LINE dispatch if it's a pre-parsing hook.
    # If it's a post-parsing raw line event, it can be added here.

    def dispatch_raw_irc_numeric(self, numeric: int, source: Optional[str], params_list: List[str], display_params_list: List[str], trailing: Optional[str], tags: Dict[str, Any], raw_line: str = ""):
        data = {
            "numeric": numeric, "source": source, "params_list": params_list,
            "display_params_list": display_params_list, "trailing": trailing, "tags": tags
        }
        self.dispatch_event("RAW_IRC_NUMERIC", data, raw_line)
