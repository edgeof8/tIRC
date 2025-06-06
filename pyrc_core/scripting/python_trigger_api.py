import logging
from typing import TYPE_CHECKING, Dict, Any

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    # If ScriptManager methods were called directly on a ScriptManager instance,
    # 'from pyrc_core.scripting.script_manager import ScriptManager' would be needed here.
    # However, it appears script_manager attributes (like logger) are accessed
    # via the client_logic instance (e.g., self._client_logic.script_manager.logger)

class PythonTriggerAPI:
    def __init__(self, client_logic: "IRCClient_Logic", script_name: str = "python_trigger"):
        self._client_logic = client_logic
        self._script_name = script_name

    def log_info(self, msg: str):
        self._client_logic.script_manager.logger.info(f"[{self._script_name}] {msg}")

    def log_error(self, msg: str):
        self._client_logic.script_manager.logger.error(f"[{self._script_name}] {msg}")

    def send_raw(self, cmd_str: str):
        self._client_logic.network_handler.send_raw(cmd_str)

    def send_message(self, target: str, message: str):
        self._client_logic.network_handler.send_raw(f"PRIVMSG {target} :{message}")

    def add_message_to_context(self, ctx_name: str, text: str, color_key: str = "system"):
        self._client_logic.add_message(text, color_key, context_name=ctx_name)

    def get_client_nick(self) -> str:
        return self._client_logic.nick
    # Add other commonly used API methods as needed by Python triggers
