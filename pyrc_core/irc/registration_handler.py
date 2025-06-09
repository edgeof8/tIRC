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
    def __init__(
        self,
        network_handler: 'NetworkHandler',
        command_handler: 'CommandHandler',
        state_manager: 'StateManager',
        cap_negotiator: Optional['CapNegotiator'] = None,
        client_logic_ref: Optional['IRCClient_Logic'] = None
    ):
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

    async def _add_status_message(self, message: str, color_key: str = "system"):
        """Helper method to safely send status messages through client logic."""
        if self.client_logic_ref:
            if hasattr(self.client_logic_ref, 'add_status_message'):
                await self.client_logic_ref.add_status_message(message, color_key)
            else:
                logger.error("add_status_message method not found on client_logic_ref")
        else:
            logger.error("client_logic_ref is None - cannot send status message")

    async def _proceed_with_nick_user_registration(self):
        if self.nick_user_sent:
            logger.debug("NICK/USER registration already sent, skipping.")
            return

        conn_info = self.state_manager.get_connection_info()
        if not conn_info:
            logger.error("Cannot proceed with registration: ConnectionInfo not found.")
            await self._add_status_message("Registration error: Missing connection details.", "error")
            # Potentially set client to an error state or attempt disconnect/reconnect logic here
            return

        logger.info(f"Proceeding with NICK/USER registration. Nick: {conn_info.nick}, User: {conn_info.username}, Real: {conn_info.realname}")
        await self._add_status_message("Sending NICK/USER to server.") # Corrected: Added await

        if conn_info.server_password:
            await self.network_handler.send_raw(f"PASS {conn_info.server_password}")

        # Update initial_nick if it changed due to earlier collision before this point
        self.initial_nick = conn_info.nick

        await self.network_handler.send_raw(f"NICK {conn_info.nick}")
        await self.network_handler.send_raw(f"USER {conn_info.username or conn_info.nick} 0 * :{conn_info.realname or conn_info.nick}")
        self.nick_user_sent = True
        logger.debug("NICK/USER commands sent.")

    async def _perform_post_registration_actions(self):
        logger.info("Performing post-registration actions (channel joins, NickServ IDENTIFY).")
        await self._add_status_message("Performing post-registration actions...")
        conn_info = self.state_manager.get_connection_info()
        if not conn_info:
            logger.error("Cannot perform post-registration actions: ConnectionInfo not found.")
            return

        if conn_info.initial_channels:
            logger.info(f"Auto-joining initial channels: {', '.join(conn_info.initial_channels)}")
            for channel_name in conn_info.initial_channels:
                if self.client_logic_ref and hasattr(self.client_logic_ref, 'command_handler') and self.client_logic_ref.command_handler:
                    await self.client_logic_ref.command_handler.process_user_command(f"/join {channel_name}")
                else:
                    logger.error(f"Cannot auto-join {channel_name}: client_logic_ref or command_handler missing.")
        else:
            logger.info("No initial channels to auto-join.")

        if conn_info.nickserv_password:
            sasl_completed_successfully = self.sasl_authenticator and self.sasl_authenticator.sasl_authentication_succeeded
            if not sasl_completed_successfully:
                logger.info(f"SASL did not complete successfully (or not used). Sending NickServ IDENTIFY for {conn_info.nick}.")
                if self.client_logic_ref and hasattr(self.client_logic_ref, 'command_handler') and self.client_logic_ref.command_handler:
                    await self.client_logic_ref.command_handler.process_user_command(f"/msg NickServ IDENTIFY {conn_info.nickserv_password}")
                else:
                    logger.error("Cannot send NickServ IDENTIFY: client_logic_ref or command_handler missing.")
            else:
                logger.info("SASL authentication succeeded. Skipping NickServ IDENTIFY.")
        else:
            logger.info("No NickServ password configured.")

    async def on_welcome_received(self, confirmed_nick: str):
        """Handles RPL_WELCOME (001) - server confirms registration."""
        logger.info(f"RPL_WELCOME (001) received. Confirmed nick: {confirmed_nick}")
        conn_info = self.state_manager.get_connection_info()
        if conn_info:
            if conn_info.nick != confirmed_nick:
                logger.info(f"Server confirmed nick as '{confirmed_nick}', updating from '{conn_info.nick}'.")
                conn_info.nick = confirmed_nick
                self.state_manager.set_connection_info(conn_info)
        else:
            logger.error("Cannot update nick on RPL_WELCOME: ConnectionInfo not found.")

        self.state_manager.set_connection_state(ConnectionState.REGISTERED)

        if self.cap_negotiator and self.cap_negotiator.cap_negotiation_pending:
            logger.info("RPL_WELCOME received while CAP negotiation was pending. Finalizing CAP.")
            # on_cap_end_confirmed is now async.
            await self.cap_negotiator.on_cap_end_confirmed() # This sets cap_negotiation_finished_event

        if not self.nick_user_sent:
            logger.warning("RPL_WELCOME received, but NICK/USER was not yet sent. Sending now.")
            await self._proceed_with_nick_user_registration()

        cap_timeout = 5.0
        if self.cap_negotiator and await self.cap_negotiator.wait_for_negotiation_finish(timeout=cap_timeout):
            logger.info("CAP negotiation confirmed finished after RPL_WELCOME. Proceeding with post-registration.")
            await self._perform_post_registration_actions()
        elif self.cap_negotiator:
            logger.warning(f"Timed out ({cap_timeout}s) waiting for CAP negotiation to fully finish after RPL_WELCOME. Proceeding with post-registration actions anyway.")
            await self._perform_post_registration_actions()
        else:
            logger.info("No CAP negotiator. Proceeding with post-registration actions immediately after RPL_WELCOME.")
            await self._perform_post_registration_actions()

    async def on_cap_negotiation_complete(self):
        """Called by CapNegotiator when its initial flow is complete (client can send NICK/USER)."""
        logger.info("RegistrationHandler: CAP negotiation initial flow complete. Proceeding with NICK/USER if not already sent.")
        if not self.nick_user_sent:
            await self._proceed_with_nick_user_registration()
        else:
            logger.debug("RegistrationHandler: NICK/USER already sent prior to on_cap_negotiation_complete call.")

    def update_nick_for_registration(self, new_nick: str):
        """Called by NetworkHandler during nick collision resolution."""
        self.initial_nick = new_nick
        logger.info(f"RegistrationHandler: Initial nick updated to '{new_nick}' due to nick collision handling.")

    def reset_registration_state(self):
        logger.debug("Resetting RegistrationHandler state.")
        self.nick_user_sent = False
        conn_info = self.state_manager.get_connection_info()
        self.initial_nick = conn_info.nick if conn_info else "PyRCNick"

    async def on_connection_established(self):
        """Called when the connection to the server is established."""
        if not hasattr(self, 'cap_negotiator') or not self.cap_negotiator:
            logger.error("CapNegotiator not found on RegistrationHandler during on_connection_established.")
            if self.client_logic_ref:
                if hasattr(self.client_logic_ref, 'add_status_message'):
                    await self.client_logic_ref.add_status_message("Error: CAP negotiator not initialized.", "error")
            return

        # Ensure network is actually connected before starting CAP
        if not self.network_handler.connected:
            logger.warning("NetworkHandler reports not connected despite on_connection_established call")
            await self._add_status_message("Connected but network not ready for CAP negotiation", "warning")
            return

        logger.info("Starting CAP negotiation after connection established")
        await self.cap_negotiator.start_negotiation()
