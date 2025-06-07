# pyrc_core/irc/registration_handler.py
import logging
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.network_handler import NetworkHandler
    from pyrc_core.commands.command_handler import CommandHandler
    from pyrc_core.irc.cap_negotiator import CapNegotiator
    from pyrc_core.irc.sasl_authenticator import SaslAuthenticator
    from pyrc_core.state_manager import StateManager
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

from pyrc_core.state_manager import ConnectionState

logger = logging.getLogger("pyrc.registration")

class RegistrationHandler:
    def __init__(self,
                 network_handler: 'NetworkHandler',
                 command_handler: 'CommandHandler',
                 state_manager: 'StateManager',
                 cap_negotiator: Optional['CapNegotiator'] = None,
                 client_logic_ref: Optional['IRCClient_Logic'] = None):
        self.network_handler = network_handler
        self.command_handler = command_handler
        self.state_manager = state_manager
        self.cap_negotiator = cap_negotiator
        self.client_logic_ref = client_logic_ref
        self.sasl_authenticator: Optional['SaslAuthenticator'] = None
        self.registration_triggered_by_001 = False
        self.nick_user_sent = False

    def set_sasl_authenticator(self, authenticator: 'SaslAuthenticator'):
        """Set the SASL authenticator instance."""
        self.sasl_authenticator = authenticator

    def set_cap_negotiator(self, negotiator: 'CapNegotiator'):
        """Set the CAP negotiator instance."""
        self.cap_negotiator = negotiator

    def _add_status_message(self, message: str, color_key: str = "system"):
        """Helper to add status messages through client if available."""
        if self.client_logic_ref:
            self.client_logic_ref._add_status_message(message, color_key)

    def _proceed_with_nick_user_registration(self):
        if self.nick_user_sent:
            return

        conn_info = self.state_manager.get_connection_info()
        if not conn_info:
            logger.error("Cannot proceed with registration: ConnectionInfo not found.")
            return

        logger.info(f"Proceeding with NICK/USER registration. Nick: {conn_info.nick}, User: {conn_info.username}")
        self._add_status_message("Proceeding with NICK/USER registration.")

        if conn_info.server_password:
            self.network_handler.send_raw(f"PASS {conn_info.server_password}")
        self.network_handler.send_raw(f"NICK {conn_info.nick}")
        self.network_handler.send_raw(f"USER {conn_info.username} 0 * :{conn_info.realname}")
        self.nick_user_sent = True

    def _perform_post_registration_actions(self):
        logger.info("Performing post-registration actions (channel joins, NickServ IDENTIFY).")
        conn_info = self.state_manager.get_connection_info()
        if not conn_info:
            return

        if conn_info.initial_channels:
            for channel_name in conn_info.initial_channels:
                self.command_handler.process_user_command(f"/join {channel_name}")

        if conn_info.nickserv_password:
            sasl_succeeded = self.sasl_authenticator and self.sasl_authenticator.sasl_authentication_succeeded
            if not sasl_succeeded:
                 self.command_handler.process_user_command(f"/msg NickServ IDENTIFY {conn_info.nickserv_password}")

    def on_welcome_received(self, confirmed_nick: str):
        self.registration_triggered_by_001 = True
        conn_info = self.state_manager.get_connection_info()
        if conn_info:
            conn_info.nick = confirmed_nick
            self.state_manager.set("connection_info", conn_info)

        self.state_manager.set_connection_state(ConnectionState.REGISTERED)

        if not self.nick_user_sent:
            self._proceed_with_nick_user_registration()

        if self.cap_negotiator and self.cap_negotiator.cap_negotiation_pending:
            self.cap_negotiator.on_cap_end_confirmed()

        if self.cap_negotiator:
            if self.cap_negotiator.wait_for_negotiation_finish(timeout=5.0):
                self._perform_post_registration_actions()
            else:
                logger.warning("Timed out waiting for CAP negotiation after 001.")
                self._perform_post_registration_actions()
        else:
            self._perform_post_registration_actions()

    def reset_registration_state(self):
        self.registration_triggered_by_001 = False
        self.nick_user_sent = False

    def on_cap_negotiation_complete(self):
        """Called when CAP negotiation is complete and registration can proceed."""
        if not self.nick_user_sent:
            self._proceed_with_nick_user_registration()
