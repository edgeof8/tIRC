import logging
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pyrc_core.network_handler import NetworkHandler
    from pyrc_core.commands.command_handler import CommandHandler
    from pyrc_core.irc.cap_negotiator import CapNegotiator
    from pyrc_core.irc.sasl_authenticator import SaslAuthenticator
    from pyrc_core.state_manager import StateManager
    # To add status messages, it might need a reference to IRCClient_Logic or a delegate
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

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

        conn_info = state_manager.get_connection_info()
        if not conn_info:
            raise ValueError("Cannot initialize RegistrationHandler - no connection info")

        self.initial_nick = conn_info.nick
        self.current_nick_to_register = conn_info.nick
        self.username = conn_info.username or conn_info.nick
        self.realname = conn_info.realname or conn_info.nick
        self.server_password = conn_info.server_password
        self.nickserv_password = conn_info.nickserv_password
        self.initial_channels_to_join = conn_info.initial_channels[:]

        self.registration_triggered_by_001 = False
        self.nick_user_sent = False


    def set_sasl_authenticator(self, sasl_authenticator: 'SaslAuthenticator'):
        self.sasl_authenticator = sasl_authenticator

    def set_cap_negotiator(self, cap_negotiator: 'CapNegotiator'):
        """Sets the CapNegotiator instance after initialization."""
        self.cap_negotiator = cap_negotiator

    def _add_status_message(self, message: str, color_key: str = "system"):
        logger.info(f"[RegistrationHandler Status via Client] {message}") # Keep local log
        if self.client_logic_ref:
            # Directly use add_message as _add_status_message is an internal helper in client_logic itself
            # and might not be directly exposed or recognized by linter in TYPE_CHECKING context.
            color_attr = self.client_logic_ref.ui.colors.get(
                color_key, self.client_logic_ref.ui.colors["system"]
            )
            self.client_logic_ref.add_message(
                message, color_attr, context_name="Status"
            )
        else:
            logger.warning("RegistrationHandler: client_logic_ref is None, cannot add status message directly.")

    def update_nick_for_registration(self, new_nick: str):
        """Called if a NICK collision (433) occurs before 001, new nick should be used for USER."""
        self.current_nick_to_register = new_nick
        logger.info(f"RegistrationHandler: Nick for NICK/USER registration updated to {new_nick} due to collision.")


    def on_cap_negotiation_complete(self):
        # 1. Trigger: Called by `CapNegotiator`'s methods (`on_cap_ls_received`, `on_cap_ack_received`,
        #    `on_cap_nak_received`, `on_sasl_flow_completed`) when the initial client-side CAP negotiation
        #    (including sending CAP END, or after SASL completion which then triggers CAP END) is considered finished.
        #    Specifically, it's called when `CapNegotiator.initial_cap_flow_complete_event` is set.
        # 2. Expected State Before:
        #    - CAP negotiation (LS, REQ, ACK/NAK) has concluded from the client's perspective.
        #    - "CAP END" has been sent by the client (or is about to be sent immediately after SASL completion).
        #    - SASL authentication, if attempted, has completed (successfully or unsuccessfully).
        #    - `self.nick_user_sent` is typically False (unless 001 arrived unusually early).
        #    - `self.registration_triggered_by_001` is typically False.
        # 3. Key Actions:
        #    - Logs that CAP negotiation is complete.
        #    - If NICK/USER commands have not yet been sent (`self.nick_user_sent` is False) AND
        #      registration wasn't already triggered by an early RPL_WELCOME (001) (`self.registration_triggered_by_001` is False):
        #        - Calls `self._proceed_with_nick_user_registration()` to send PASS (if any), NICK, and USER commands.
        #    - Otherwise, logs that NICK/USER was already sent or 001 arrived first.
        # 4. Expected State After:
        #    - If conditions were met:
        #        - `self._proceed_with_nick_user_registration()` is called.
        #        - PASS (if configured), NICK, and USER commands are sent to the server.
        #        - `self.nick_user_sent` becomes True.
        #    - The client is now waiting for the server to respond to NICK/USER, primarily expecting RPL_WELCOME (001)
        #      to confirm successful registration.
        #    - Subsequent step: Server responses to NICK/USER, especially RPL_WELCOME (001) handled by `self.on_welcome_received()`,
        #      or error numerics like ERR_NICKNAMEINUSE (433).
        """
        Called by CapNegotiator when its initial flow (LS, REQ, ACK/NAK, END) is complete.
        This is the primary trigger for sending NICK/USER if 001 hasn't arrived yet.
        """
        logger.info("RegistrationHandler: CapNegotiator reports initial CAP flow complete.")
        if not self.registration_triggered_by_001 and not self.nick_user_sent:
            self._proceed_with_nick_user_registration()
        else:
            logger.info("RegistrationHandler: NICK/USER already sent or 001 already triggered registration.")


    def on_welcome_received(self, confirmed_nick: str):
        # 1. Trigger: Called by `irc_protocol.handle_rpl_welcome()` when the server sends RPL_WELCOME (001).
        #    This numeric signifies that the client is now successfully registered with the server.
        # 2. Expected State Before:
        #    - PASS (if any), NICK, and USER commands have been sent (or are about to be, if 001 arrived very quickly).
        #    - CAP negotiation and SASL (if used) should ideally be complete or nearing completion.
        #    - `confirmed_nick` (method argument) is the nickname the server has acknowledged for the client.
        # 3. Key Actions:
        #    - Sets `self.registration_triggered_by_001 = True`.
        #    - Updates `self.current_nick_to_register` with `confirmed_nick`.
        #    - If `self.nick_user_sent` is False (i.e., 001 arrived before NICK/USER was flagged as sent):
        #        - Logs a warning.
        #        - Calls `self._proceed_with_nick_user_registration()` to ensure NICK/USER are sent if they weren't.
        #    - If `self.cap_negotiator` exists and `is_cap_negotiation_pending()` is True:
        #        - Calls `self.cap_negotiator.on_cap_end_confirmed()`. This is crucial because RPL_WELCOME
        #          implicitly confirms that CAP negotiation (from the server's perspective) is over.
        #    - Waits for `self.cap_negotiator.wait_for_negotiation_finish()` (if `cap_negotiator` exists) to ensure
        #      any final CAP/SASL cleanup or event setting in CapNegotiator has occurred.
        #    - Calls `self._perform_post_registration_actions()` to handle auto-channel joins and NickServ identification.
        # 4. Expected State After:
        #    - `self.registration_triggered_by_001` is True.
        #    - `self.current_nick_to_register` reflects the server-confirmed nickname.
        #    - `self.nick_user_sent` is True.
        #    - If CAP was pending, `CapNegotiator` is notified that CAP END is confirmed.
        #    - Post-registration actions (channel joins, NickServ IDENTIFY) are initiated via `_perform_post_registration_actions()`.
        #    - The client is now fully registered and ready for general IRC interaction.
        #    - Subsequent step: Client joins channels, sends/receives messages, etc. The connection handshake is complete.
        """
        Called when RPL_WELCOME (001) is received.
        This confirms server registration and triggers post-registration actions.
        """
        logger.info(f"RegistrationHandler: RPL_WELCOME (001) received. Confirmed nick: {confirmed_nick}.")
        self.registration_triggered_by_001 = True
        self.current_nick_to_register = confirmed_nick # Server confirms the nick

        if not self.nick_user_sent:
            # This implies 001 arrived before CAP END was fully processed or if CAP was skipped.
            # Ensure NICK/USER was conceptually sent.
            logger.warning("RPL_WELCOME received, but NICK/USER flag not set. Assuming they were implicitly accepted or will be sent now.")
            # If NICK/USER wasn't sent due to CapNegotiator not calling on_cap_negotiation_complete yet,
            # 001 is a definitive signal to proceed.
            if not self.nick_user_sent: # Double check, as on_cap_negotiation_complete might have just run
                self._proceed_with_nick_user_registration() # Send NICK/USER if not already done.

        # Ensure CapNegotiator knows that 001 implies CAP END confirmation
        if self.cap_negotiator and self.cap_negotiator.is_cap_negotiation_pending():
            logger.info("RPL_WELCOME received while CAP was pending. Signaling CAP END confirmation to CapNegotiator.")
            self.cap_negotiator.on_cap_end_confirmed()
        elif not self.cap_negotiator:
            logger.error("RPL_WELCOME: cap_negotiator is None, cannot signal CAP END confirmation.")

        # This block should execute once 001 is received, after ensuring NICK/USER has been sent
        # and CAP flow is considered complete from the server's perspective (signaled by 001).
        logger.debug("RegistrationHandler: Processing post-001 actions. Checking cap_negotiator state.")
        if self.cap_negotiator:
            logger.debug(f"RegistrationHandler: CapNegotiator exists. cap_negotiation_finished_event is set: {self.cap_negotiator.cap_negotiation_finished_event.is_set()}")
            logger.debug(f"RegistrationHandler: Calling wait_for_negotiation_finish...")
            cap_negotiation_finished = self.cap_negotiator.wait_for_negotiation_finish(timeout=5.0)
            logger.debug(f"RegistrationHandler: wait_for_negotiation_finish result: {cap_negotiation_finished}")

            if cap_negotiation_finished:
                logger.info("RegistrationHandler: Overall CAP negotiation (including SASL) reported as finished by CapNegotiator. Proceeding with post-001 actions.")
                self._perform_post_registration_actions()
            else: # Cap negotiator exists but timed out or event not set
                logger.warning("RegistrationHandler: Timed out waiting for overall CAP negotiation after 001 (or event not set). Post-registration actions might be premature or fail.")
                self._add_status_message("Warning: CAP/SASL negotiation timed out or event not set after 001. Auto-actions may be affected.", "warning")
                logger.info("RegistrationHandler: Fallback - performing post-registration actions despite timeout/event state because 001 was received.")
                self._perform_post_registration_actions()
        else: # No cap_negotiator
            logger.error("RPL_WELCOME: cap_negotiator is None, cannot wait for negotiation finish. Performing post-reg actions directly.")
            self._perform_post_registration_actions() # Proceed with caution


    def _proceed_with_nick_user_registration(self):
        # 1. Trigger: Called by `self.on_cap_negotiation_complete()` if NICK/USER hasn't been sent and 001 hasn't arrived,
        #    OR by `self.on_welcome_received()` if 001 arrives before NICK/USER was flagged as sent (e.g., CAP skipped or very fast server).
        # 2. Expected State Before:
        #    - `self.nick_user_sent` is False.
        #    - CAP negotiation and SASL (if applicable) are considered complete from the client's perspective, allowing registration.
        #    - `self.current_nick_to_register` holds the nick to use (initial or modified by 433).
        #    - `self.username`, `self.realname`, `self.server_password` are configured.
        # 3. Key Actions:
        #    - If `self.nick_user_sent` is already True, returns early.
        #    - Logs intent to send NICK/USER and adds a status message.
        #    - If `self.server_password` is set, sends "PASS <password>" via `NetworkHandler`.
        #    - Sends "NICK <current_nick_to_register>" via `NetworkHandler`.
        #    - Sends "USER <username> 0 * :<realname>" via `NetworkHandler`.
        #    - Sets `self.nick_user_sent = True`.
        # 4. Expected State After:
        #    - `self.nick_user_sent` is True.
        #    - PASS (if applicable), NICK, and USER commands have been sent to the server.
        #    - The client is now awaiting server responses, primarily RPL_WELCOME (001) to confirm successful registration,
        #      or error numerics like ERR_NICKNAMEINUSE (433), ERR_ALREADYREGISTRED (462), etc.
        #    - Subsequent step: Server responses to these commands, leading to `self.on_welcome_received()` or error handlers.
        """Sends NICK and USER commands to the server."""
        if self.nick_user_sent:
            logger.info("NICK/USER registration already sent for this connection attempt.")
            return

        logger.info(f"Proceeding with NICK/USER registration. Nick: {self.current_nick_to_register}, User: {self.username}")
        self._add_status_message("Proceeding with NICK/USER registration.")

        if self.server_password:
            self.network_handler.send_raw(f"PASS {self.server_password}")
        self.network_handler.send_raw(f"NICK {self.current_nick_to_register}")
        self.network_handler.send_raw(f"USER {self.username} 0 * :{self.realname}")
        self.nick_user_sent = True


    def _perform_post_registration_actions(self):
        """Handles auto-channel joins and NickServ identification."""
        logger.info("Performing post-registration actions (channel joins, NickServ IDENTIFY).")

        # Auto-join channels
        if self.initial_channels_to_join:
            channels_to_join_now = self.initial_channels_to_join[:] # Operate on a copy
            logger.info(f"Post-001: Processing auto-join for channels: {', '.join(channels_to_join_now)}")
            self._add_status_message(f"Auto-joining channels: {', '.join(channels_to_join_now)}", "system")
            for channel_name in channels_to_join_now:
                self.command_handler.process_user_command(f"/join {channel_name}")
        else:
            logger.info("No channels queued for auto-join post-001.")

        # NickServ IDENTIFY
        sasl_succeeded = self.sasl_authenticator and self.sasl_authenticator.sasl_authentication_succeeded is True
        sasl_cap_enabled = self.cap_negotiator.is_cap_enabled("sasl") if self.cap_negotiator else False

        if self.nickserv_password:
            if sasl_cap_enabled and sasl_succeeded:
                logger.info("SASL authentication successful. NickServ IDENTIFY not needed.")
                self._add_status_message("SASL auth successful, NickServ IDENTIFY skipped.", "system")
            elif sasl_cap_enabled and self.sasl_authenticator and self.sasl_authenticator.is_completed() and not sasl_succeeded:
                logger.info("SASL authentication failed or not attempted, but NickServ password exists. Sending IDENTIFY.")
                self._add_status_message("SASL failed/skipped. Identifying with NickServ...", "system")
                self.command_handler.process_user_command(f"/msg NickServ IDENTIFY {self.nickserv_password}")
            elif not sasl_cap_enabled: # SASL not even a supported/enabled CAP
                logger.info("SASL CAP not enabled. NickServ password exists. Sending IDENTIFY.")
                self._add_status_message("SASL not available. Identifying with NickServ...", "system")
                self.command_handler.process_user_command(f"/msg NickServ IDENTIFY {self.nickserv_password}")
            else:
                # This case implies SASL CAP is enabled, but SASL flow hasn't completed yet or its state is unknown.
                # This shouldn't happen if we waited for cap_negotiator.wait_for_negotiation_finish()
                logger.warning("NickServ IDENTIFY check: SASL CAP enabled, password exists, but SASL state indeterminate. Holding off IDENTIFY.")
                self._add_status_message("SASL state unclear. NickServ IDENTIFY deferred.", "warning")
        else:
            logger.info("No NickServ password configured. Skipping IDENTIFY.")


    def reset_registration_state(self):
        """Resets state for a new connection attempt."""
        logger.debug("Resetting RegistrationHandler state.")
        self.registration_triggered_by_001 = False
        self.nick_user_sent = False
        self.current_nick_to_register = self.initial_nick # Reset to initial for next attempt
