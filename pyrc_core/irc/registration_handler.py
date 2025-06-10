# pyrc_core/irc/registration_handler.py
import logging
import asyncio # Import asyncio
from typing import List, Optional, TYPE_CHECKING
from dataclasses import asdict # Import asdict

from pyrc_core.context_manager import ChannelJoinStatus # Import ChannelJoinStatus

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
        self.logger = logging.getLogger("pyrc.registration")
        self.cap_negotiator = cap_negotiator
        self.client_logic_ref = client_logic_ref
        self.sasl_authenticator: Optional['SaslAuthenticator'] = None

        self.nick_user_sent = False
        conn_info = self.state_manager.get_connection_info()
        self.initial_nick = conn_info.nick if conn_info else "PyRCNick"
        self.post_registration_task: Optional[asyncio.Task] = None
        self.end_of_motd_received = asyncio.Event()
        self._post_motd_actions_initiated_flag = False

    def set_sasl_authenticator(self, authenticator: 'SaslAuthenticator'):
        self.sasl_authenticator = authenticator

    def set_cap_negotiator(self, negotiator: 'CapNegotiator'):
        self.cap_negotiator = negotiator

    async def _add_status_message(self, message: str, color_key: str = "system"):
        if self.client_logic_ref and hasattr(self.client_logic_ref, 'add_status_message'):
            await self.client_logic_ref.add_status_message(message, color_key)
        else:
            logger.error("client_logic_ref or add_status_message not available.")

    async def _proceed_with_nick_user_registration(self):
        if self.nick_user_sent:
            logger.debug("NICK/USER registration already sent, skipping.")
            return

        conn_info = self.state_manager.get_connection_info()
        if not conn_info:
            logger.error("Cannot proceed with registration: ConnectionInfo not found.")
            await self._add_status_message("Registration error: Missing connection details.", "error")
            return

        logger.info(f"Proceeding with NICK/USER registration. Nick: {conn_info.nick}, User: {conn_info.username}, Real: {conn_info.realname}")
        await self._add_status_message("Sending NICK/USER to server.")

        if conn_info.server_password:
            await self.network_handler.send_raw(f"PASS {conn_info.server_password}")

        self.initial_nick = conn_info.nick
        await self.network_handler.send_raw(f"NICK {conn_info.nick}")
        await self.network_handler.send_raw(f"USER {conn_info.username or conn_info.nick} 0 * :{conn_info.realname or conn_info.nick}")
        self.nick_user_sent = True
        logger.debug("NICK/USER commands sent.")

    async def _perform_post_registration_actions(self):
        self._post_motd_actions_initiated_flag = True
        logger.info("PERFORM_POST_REG_ACTIONS: Entered function.")
        await self._add_status_message("Performing post-registration actions...")
        conn_info = self.state_manager.get_connection_info()

        if not conn_info:
            logger.error("_perform_post_registration_actions: conn_info is None.")
            return

        logger.debug(f"_perform_post_registration_actions: Fetched conn_info. Server: {conn_info.server}, Nick: {conn_info.nick}, Initial Channels: {conn_info.initial_channels}")

        channels_to_join = conn_info.initial_channels
        if channels_to_join:
            logger.info(f"Auto-joining initial channels: {', '.join(channels_to_join)}")
            for channel_name in channels_to_join:
                if self.client_logic_ref:
                    self.client_logic_ref.context_manager.create_context(
                        channel_name,
                        context_type="channel",
                        initial_join_status_for_channel=ChannelJoinStatus.JOIN_COMMAND_SENT
                    )
                logger.debug(f"Sending JOIN for {channel_name}")
                await self.network_handler.send_raw(f"JOIN {channel_name}")
        else:
            logger.info("No initial channels to auto-join.")

        if self.client_logic_ref and self.client_logic_ref.pending_initial_joins:
            logger.info(f"Waiting for {len(self.client_logic_ref.pending_initial_joins)} initial channel join(s) to complete. Pending: {self.client_logic_ref.pending_initial_joins}")
            try:
                await asyncio.wait_for(self.client_logic_ref.all_initial_joins_processed.wait(), timeout=10.0)
                logger.info("All initial join attempts processed or timed out.")
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for all initial joins. Proceeding.")
                if not self.client_logic_ref.all_initial_joins_processed.is_set():
                    self.client_logic_ref.all_initial_joins_processed.set()
        elif self.client_logic_ref:
             logger.debug("No pending initial joins or all_initial_joins_processed already set.")
        else:
            logger.error("client_logic_ref is None, cannot wait for initial joins.")

        if conn_info.nickserv_password:
            sasl_completed_successfully = self.sasl_authenticator and self.sasl_authenticator.sasl_authentication_succeeded
            if not sasl_completed_successfully:
                logger.info(f"SASL not completed. Sending NickServ IDENTIFY for {conn_info.nick}.")
                if self.client_logic_ref and hasattr(self.client_logic_ref, 'command_handler'):
                    await self.client_logic_ref.command_handler.process_user_command(f"/msg NickServ IDENTIFY {conn_info.nickserv_password}")
            else:
                logger.info("SASL succeeded. Skipping NickServ IDENTIFY.")
        else:
            logger.info("No NickServ password configured.")

        if self.client_logic_ref and hasattr(self.client_logic_ref, 'event_manager'):
            logger.info("Dispatching CLIENT_READY event.")
            await self.client_logic_ref.event_manager.dispatch_event(
                "CLIENT_READY",
                {"nick": conn_info.nick, "channels": conn_info.initial_channels}
            )

    async def execute_post_motd_actions(self):
        logger.info("REG_HANDLER: execute_post_motd_actions called (triggered by MOTD end).")
        if not self.end_of_motd_received.is_set():
            logger.warning("REG_HANDLER: execute_post_motd_actions called, but MOTD event not set. Setting now.")
            self.end_of_motd_received.set()

        if self._post_motd_actions_initiated_flag:
            logger.info("REG_HANDLER: execute_post_motd_actions: Actions already initiated. Skipping duplicate run.")
            return

        if self.post_registration_task and not self.post_registration_task.done():
            logger.info("REG_HANDLER: execute_post_motd_actions cancelling existing post_registration_task (fallback).")
            self.post_registration_task.cancel()
            try:
                await self.post_registration_task
            except asyncio.CancelledError:
                logger.debug("REG_HANDLER: Successfully cancelled existing post_registration_task (fallback) in execute_post_motd_actions.")
            except Exception as e_prev:
                logger.error(f"REG_HANDLER: Error awaiting existing post_registration_task (fallback) cancellation: {e_prev}")

        logger.info("REG_HANDLER: Creating new task for _perform_post_registration_actions from execute_post_motd_actions.")
        asyncio.create_task(self._perform_post_registration_actions())


    async def on_welcome_received(self, confirmed_nick: str):
        logger.info(f"RPL_WELCOME (001) received. Confirmed nick: {confirmed_nick}")
        conn_info = self.state_manager.get_connection_info()
        if conn_info and conn_info.nick != confirmed_nick:
            logger.info(f"Server confirmed nick as '{confirmed_nick}', updating from '{conn_info.nick}'.")
            conn_info.nick = confirmed_nick
            await self.state_manager.set_connection_info(conn_info)

        await self.state_manager.set_connection_state(ConnectionState.REGISTERED)

        if self.cap_negotiator and self.cap_negotiator.cap_negotiation_pending:
            logger.info("RPL_WELCOME received while CAP negotiation was pending. Finalizing CAP.")
            await self.cap_negotiator.on_cap_end_confirmed()

        if not self.nick_user_sent:
            logger.warning("RPL_WELCOME received, but NICK/USER was not yet sent. Sending now.")
            await self._proceed_with_nick_user_registration()

        cap_timeout = 5.0

        async def post_welcome_sequence_fallback():
            current_task = asyncio.current_task()
            logger.info(f"POST_WELCOME_SEQ_FALLBACK: Task started: {current_task!r}")
            try:
                logger.info("POST_WELCOME_SEQ_FALLBACK: Waiting for CAP negotiation (if pending).")

                if self.cap_negotiator and self.cap_negotiator.cap_negotiation_pending:
                    logger.debug(f"POST_WELCOME_SEQ_FALLBACK: CAP pending, awaiting cap_negotiation_finished_event timeout {cap_timeout}s.")
                    try:
                        await asyncio.wait_for(self.cap_negotiator.cap_negotiation_finished_event.wait(), timeout=cap_timeout)
                        logger.info("POST_WELCOME_SEQ_FALLBACK: CAP negotiation confirmed finished.")
                    except asyncio.TimeoutError:
                        logger.warning(f"POST_WELCOME_SEQ_FALLBACK: Timed out ({cap_timeout}s) waiting for CAP to finish. Proceeding cautiously.")
                        if self.cap_negotiator and not self.cap_negotiator.cap_negotiation_finished_event.is_set():
                             self.cap_negotiator.cap_negotiation_finished_event.set()

                fallback_motd_delay = 25.0
                logger.info(f"POST_WELCOME_SEQ_FALLBACK: Starting {fallback_motd_delay}s fallback delay for MOTD actions.")
                await asyncio.sleep(fallback_motd_delay)

                if not self._post_motd_actions_initiated_flag:
                    logger.warning(f"POST_WELCOME_SEQ_FALLBACK: Fallback triggered. MOTD actions not yet initiated after {fallback_motd_delay}s. Attempting actions now.")
                    if not self.end_of_motd_received.is_set():
                        logger.info("POST_WELCOME_SEQ_FALLBACK: Forcing end_of_motd_received event set.")
                        self.end_of_motd_received.set()
                    await self._perform_post_registration_actions()
                else:
                    logger.info("POST_WELCOME_SEQ_FALLBACK: Post MOTD actions already initiated, fallback doing nothing further.")

            except asyncio.CancelledError:
                logger.info("POST_WELCOME_SEQ_FALLBACK: Task cancelled.")
            except Exception as e:
                logger.exception(f"CRITICAL ERROR in POST_WELCOME_SEQ_FALLBACK: {e}")

        if self.post_registration_task and not self.post_registration_task.done():
            logger.warning("Previous post_registration_task (fallback) pending. Cancelling.")
            self.post_registration_task.cancel()
            try:
                await self.post_registration_task
            except asyncio.CancelledError:
                logger.debug("Successfully cancelled previous post_registration_task (fallback).")
            except Exception as e_prev:
                logger.error(f"Error awaiting previous post_registration_task (fallback) cancellation: {e_prev}")

        logger.info("Scheduling post_welcome_sequence_fallback task.")
        self._post_motd_actions_initiated_flag = False
        self.post_registration_task = asyncio.create_task(post_welcome_sequence_fallback())
        logger.info(f"REG_HANDLER: Scheduled post_welcome_sequence_fallback task: {self.post_registration_task!r}")


    async def on_cap_negotiation_complete(self):
        logger.info("RegistrationHandler: CAP negotiation initial flow complete. Proceeding with NICK/USER if not already sent.")
        if not self.nick_user_sent:
            await self._proceed_with_nick_user_registration()
        else:
            logger.debug("RegistrationHandler: NICK/USER already sent prior to on_cap_negotiation_complete call.")

    def update_nick_for_registration(self, new_nick: str):
        self.initial_nick = new_nick
        logger.info(f"RegistrationHandler: Initial nick updated to '{new_nick}' due to nick collision handling.")

    def reset_registration_state(self):
        logger.debug("Resetting RegistrationHandler state.")
        self.nick_user_sent = False
        conn_info = self.state_manager.get_connection_info()
        self.initial_nick = conn_info.nick if conn_info else "PyRCNick"
        if self.post_registration_task and not self.post_registration_task.done():
            logger.debug("Cancelling pending post_registration_task during reset_registration_state.")
            self.post_registration_task.cancel()
        self.post_registration_task = None
        self.end_of_motd_received.clear()
        self._post_motd_actions_initiated_flag = False

    async def on_connection_established(self):
        logger.info("RegistrationHandler.on_connection_established: Entered.")
        self._post_motd_actions_initiated_flag = False
        if not self.cap_negotiator:
            logger.error("CapNegotiator not found on RegistrationHandler.")
            await self._add_status_message("Error: CAP negotiator not initialized.", "error")
            return

        await self.cap_negotiator.reset_negotiation_state()
        logger.debug("CapNegotiator state reset on connection established.")

        if not self.network_handler.connected:
            logger.warning("NetworkHandler reports not connected despite on_connection_established call")
            await self._add_status_message("Connected but network not ready for CAP negotiation", "warning")
            return

        logger.info("Starting CAP negotiation after connection established")
        await self.cap_negotiator.start_negotiation()
