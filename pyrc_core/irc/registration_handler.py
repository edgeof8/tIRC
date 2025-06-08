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

        self.nick_user_sent = False
        # self.registration_triggered_by_001 = False # This flag seems less critical now with event-driven flow

        # Store initial nick from config for collision handling logic
        conn_info = self.state_manager.get_connection_info()
        self.initial_nick = conn_info.nick if conn_info else "PyRCNick" # Fallback if no conn_info at init


    def set_sasl_authenticator(self, authenticator: 'SaslAuthenticator'):
        self.sasl_authenticator = authenticator

    def set_cap_negotiator(self, negotiator: 'CapNegotiator'):
        self.cap_negotiator = negotiator

    def _add_status_message(self, message: str, color_key: str = "system"):
        if self.client_logic_ref:
            self.client_logic_ref._add_status_message(message, color_key)

    def _proceed_with_nick_user_registration(self):
        if self.nick_user_sent:
            logger.debug("NICK/USER registration already sent, skipping.")
            return

        conn_info = self.state_manager.get_connection_info()
        if not conn_info:
            logger.error("Cannot proceed with registration: ConnectionInfo not found.")
            self._add_status_message("Registration error: Missing connection details.", "error")
            # Potentially set client to an error state or attempt disconnect/reconnect logic here
            return

        logger.info(f"Proceeding with NICK/USER registration. Nick: {conn_info.nick}, User: {conn_info.username}, Real: {conn_info.realname}")
        self._add_status_message("Sending NICK/USER to server.")

        if conn_info.server_password:
            self.network_handler.send_raw(f"PASS {conn_info.server_password}")

        # Update initial_nick if it changed due to earlier collision before this point
        self.initial_nick = conn_info.nick

        self.network_handler.send_raw(f"NICK {conn_info.nick}")
        self.network_handler.send_raw(f"USER {conn_info.username or conn_info.nick} 0 * :{conn_info.realname or conn_info.nick}")
        self.nick_user_sent = True
        logger.debug("NICK/USER commands sent.")


    def _perform_post_registration_actions(self):
        logger.info("Performing post-registration actions (channel joins, NickServ IDENTIFY).")
        self._add_status_message("Performing post-registration actions...")
        conn_info = self.state_manager.get_connection_info()
        if not conn_info:
            logger.error("Cannot perform post-registration actions: ConnectionInfo not found.")
            return

        if conn_info.initial_channels:
            logger.info(f"Auto-joining initial channels: {', '.join(conn_info.initial_channels)}")
            for channel_name in conn_info.initial_channels:
                # Ensure client_logic_ref and command_handler exist
                if self.client_logic_ref and hasattr(self.client_logic_ref, 'command_handler') and self.client_logic_ref.command_handler:
                    self.client_logic_ref.command_handler.process_user_command(f"/join {channel_name}")
                else:
                    logger.error(f"Cannot auto-join {channel_name}: client_logic_ref or command_handler missing.")
        else:
            logger.info("No initial channels to auto-join.")


        if conn_info.nickserv_password:
            sasl_completed_successfully = self.sasl_authenticator and self.sasl_authenticator.sasl_authentication_succeeded
            if not sasl_completed_successfully:
                logger.info(f"SASL did not complete successfully (or not used). Sending NickServ IDENTIFY for {conn_info.nick}.")
                if self.client_logic_ref and hasattr(self.client_logic_ref, 'command_handler') and self.client_logic_ref.command_handler:
                    self.client_logic_ref.command_handler.process_user_command(f"/msg NickServ IDENTIFY {conn_info.nickserv_password}")
                else:
                     logger.error("Cannot send NickServ IDENTIFY: client_logic_ref or command_handler missing.")
            else:
                logger.info("SASL authentication succeeded. Skipping NickServ IDENTIFY.")
        else:
            logger.info("No NickServ password configured.")


    def on_welcome_received(self, confirmed_nick: str):
        """Handles RPL_WELCOME (001) - server confirms registration."""
        logger.info(f"RPL_WELCOME (001) received. Confirmed nick: {confirmed_nick}")
        conn_info = self.state_manager.get_connection_info()
        if conn_info:
            if conn_info.nick != confirmed_nick:
                logger.info(f"Server confirmed nick as '{confirmed_nick}', updating from '{conn_info.nick}'.")
                conn_info.nick = confirmed_nick
                self.state_manager.set_connection_info(conn_info) # Persist the confirmed nick
        else:
            logger.error("Cannot update nick on RPL_WELCOME: ConnectionInfo not found.")
            # This is a problematic state.

        self.state_manager.set_connection_state(ConnectionState.REGISTERED)

        # If CAP negotiation was still somehow pending, 001 implies it's over from server's perspective.
        if self.cap_negotiator and self.cap_negotiator.cap_negotiation_pending:
            logger.info("RPL_WELCOME received while CAP negotiation was pending. Finalizing CAP.")
            self.cap_negotiator.on_cap_end_confirmed() # This sets cap_negotiation_finished_event

        # Ensure NICK/USER was sent if it hadn't been by CAP END.
        if not self.nick_user_sent:
            logger.warning("RPL_WELCOME received, but NICK/USER was not yet sent. Sending now.")
            self._proceed_with_nick_user_registration()

        # Now, wait for the overall CAP negotiation to be truly finished before post-reg actions.
        # This handles cases where SASL might still be ongoing even after 001 (though less common).
        cap_timeout = 5.0
        if self.cap_negotiator and self.cap_negotiator.wait_for_negotiation_finish(timeout=cap_timeout):
            logger.info("CAP negotiation confirmed finished after RPL_WELCOME. Proceeding with post-registration.")
            self._perform_post_registration_actions()
        elif self.cap_negotiator:
            logger.warning(f"Timed out ({cap_timeout}s) waiting for CAP negotiation to fully finish after RPL_WELCOME. Proceeding with post-registration actions anyway.")
            self._perform_post_registration_actions() # Proceed even on timeout
        else: # No CAP negotiator
            logger.info("No CAP negotiator. Proceeding with post-registration actions immediately after RPL_WELCOME.")
            self._perform_post_registration_actions()


    def on_cap_negotiation_complete(self):
        """Called by CapNegotiator when its initial flow is complete (client can send NICK/USER)."""
        logger.info("RegistrationHandler: CAP negotiation initial flow complete. Proceeding with NICK/USER if not already sent.")
        if not self.nick_user_sent:
            self._proceed_with_nick_user_registration()
        else:
            logger.debug("RegistrationHandler: NICK/USER already sent prior to on_cap_negotiation_complete call.")

    def update_nick_for_registration(self, new_nick: str):
        """Called by NetworkHandler during nick collision resolution."""
        # Always update initial_nick, as this is the base for future collision retries
        self.initial_nick = new_nick
        logger.info(f"RegistrationHandler: Initial nick updated to '{new_nick}' due to nick collision handling.")

    def reset_registration_state(self):
        logger.debug("Resetting RegistrationHandler state.")
        self.nick_user_sent = False
        # self.registration_triggered_by_001 = False # Removed
        conn_info = self.state_manager.get_connection_info()
        self.initial_nick = conn_info.nick if conn_info else "PyRCNick" # Reset initial_nick
