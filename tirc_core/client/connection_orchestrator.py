# tirc_core/client/connection_orchestrator.py
import logging
from typing import TYPE_CHECKING, Optional

from tirc_core.irc.cap_negotiator import CapNegotiator
from tirc_core.irc.sasl_authenticator import SaslAuthenticator
from tirc_core.irc.registration_handler import RegistrationHandler
from tirc_core.state_manager import ConnectionInfo
from tirc_core.context_manager import ChannelJoinStatus # Added for reset_for_new_connection

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic
    from tirc_core.network_handler import NetworkHandler
    from tirc_core.state_manager import StateManager
    from tirc_core.app_config import AppConfig


logger = logging.getLogger("tirc.connection_orchestrator")

class ConnectionOrchestrator:
    def __init__(self, client_logic_ref: "IRCClient_Logic"):
        self.client_logic_ref = client_logic_ref
        # Direct references to components on client_logic_ref for convenience
        self.network_handler: "NetworkHandler" = client_logic_ref.network_handler
        self.state_manager: "StateManager" = client_logic_ref.state_manager
        self.config: "AppConfig" = client_logic_ref.config

    def initialize_handlers(self) -> None:
        """
        Initializes and sets up connection-specific handlers (CAP, SASL, Registration)
        on the client_logic_ref.
        """
        logger.debug("ConnectionOrchestrator: Initializing connection handlers (CAP, SASL, Registration)...")
        conn_info = self.state_manager.get_connection_info()
        if not conn_info:
            logger.error("ConnectionOrchestrator: Cannot initialize connection handlers - no connection info found in StateManager.")
            return

        # Create and assign handlers to the client_logic_ref instance
        self.client_logic_ref.cap_negotiator = CapNegotiator(
            network_handler=self.network_handler,
            state_manager=self.state_manager, # Pass StateManager
            client_logic_ref=self.client_logic_ref
            # desired_caps is handled internally by CapNegotiator using StateManager
            # registration_handler is set later
        )

        if self.client_logic_ref.cap_negotiator is None:
            logger.critical("ConnectionOrchestrator: cap_negotiator is None before SASLAuthenticator initialization. This should not happen.")
            # Depending on how critical SASL is, either raise an error or try to proceed without it.
            # For now, we'll let it potentially fail at SASLAuthenticator if it can't handle None.
            # Or, ensure CapNegotiator always initializes or raises.
            # Based on current typing, SaslAuthenticator expects a CapNegotiator, not Optional.
            # This indicates a logic flaw if cap_negotiator can be None here.
            # For now, we'll assert to catch this during development.
            assert self.client_logic_ref.cap_negotiator is not None, "CapNegotiator must be initialized before SaslAuthenticator"


        self.client_logic_ref.sasl_authenticator = SaslAuthenticator(
            network_handler=self.network_handler,
            state_manager=self.state_manager, # Corrected: pass state_manager
            client_logic_ref=self.client_logic_ref
            # cap_negotiator and password are not constructor arguments for SaslAuthenticator
        )

        self.client_logic_ref.registration_handler = RegistrationHandler(
            network_handler=self.network_handler,
            command_handler=self.client_logic_ref.command_handler,
            state_manager=self.state_manager,
            cap_negotiator=self.client_logic_ref.cap_negotiator,
            client_logic_ref=self.client_logic_ref,
        )

        # Link handlers back
        # CapNegotiator accesses registration_handler and sasl_authenticator via client_logic_ref directly.
        # No explicit linking back to CapNegotiator instance is needed for these.

        if self.client_logic_ref.registration_handler and self.client_logic_ref.sasl_authenticator:
            if hasattr(self.client_logic_ref.registration_handler, "set_sasl_authenticator"):
                self.client_logic_ref.registration_handler.set_sasl_authenticator(self.client_logic_ref.sasl_authenticator)

        logger.debug("ConnectionOrchestrator: Connection handlers initialized and set on client_logic_ref.")

    async def reset_for_new_connection(self) -> None:
        """
        Resets the client's state in preparation for a new server connection.
        Moved from IRCClient_Logic._reset_state_for_new_connection.
        """
        client = self.client_logic_ref # Alias for clarity
        logger.debug("ConnectionOrchestrator: Resetting client state for new server connection.")

        # Preserve Status window messages and scroll offset if possible
        status_context = client.context_manager.get_context("Status")
        current_status_msgs = []
        status_scroll_offset = 0
        if status_context:
            current_status_msgs = list(status_context.messages) # Make a copy
            if hasattr(status_context, "scrollback_offset"):
                status_scroll_offset = status_context.scrollback_offset

        # Clear all existing contexts
        client.context_manager.contexts.clear()

        # Recreate Status window and restore its messages/scroll
        client.context_manager.create_context("Status", context_type="status")
        new_status_context = client.context_manager.get_context("Status")
        if new_status_context:
            for msg_tuple in current_status_msgs:
                if isinstance(msg_tuple, tuple) and len(msg_tuple) >= 2:
                    new_status_context.add_message(msg_tuple[0], msg_tuple[1])
                else:
                    logger.warning(f"Skipping invalid message tuple during Status restore: {msg_tuple}")
            if hasattr(new_status_context, "scrollback_offset"):
                new_status_context.scrollback_offset = status_scroll_offset

        # Recreate DCC context if enabled
        if client.config.dcc.enabled:
            client.context_manager.create_context("DCC", context_type="dcc_transfers")


        # Recreate initial channels (now based on the potentially new server config)
        conn_info = self.state_manager.get_connection_info()
        if conn_info:
            for ch_name in conn_info.initial_channels:
                client.context_manager.create_context(
                    ch_name,
                    context_type="channel",
                    initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN,
                )

        # Set active context: to the first initial channel, or Status if no initial channels
        if conn_info and conn_info.initial_channels:
            first_initial_channel_normalized = client.context_manager._normalize_context_name(conn_info.initial_channels[0])
            if client.context_manager.get_context(first_initial_channel_normalized):
                client.context_manager.set_active_context(first_initial_channel_normalized)
            else:
                client.context_manager.set_active_context("Status") # Fallback
        else:
            client.context_manager.set_active_context("Status")

        # Clear other relevant client state stored in ConnectionInfo
        if conn_info:
            conn_info.currently_joined_channels.clear()
            conn_info.user_modes.clear() # Also reset user modes
            conn_info.last_attempted_nick_change = None # Reset last attempted nick
            # Do not clear last_error, connection_attempts, etc. here as they might be relevant
            # for reconnection logic or overall stats. StateManager handles their persistence.
            # Instead, ensure they are reset appropriately at the start of a *new* connection attempt if needed.
            await self.state_manager.set_connection_info(conn_info) # Save changes to ConnectionInfo

        client.last_join_command_target = None # This is specific to client logic flow

        # If a /server switch is pending and waiting for disconnect, signal it
        if client._server_switch_disconnect_event and not client._server_switch_disconnect_event.is_set():
            logger.info("ConnectionOrchestrator: Signaling /server command that disconnect is complete via _server_switch_disconnect_event.")
            client._server_switch_disconnect_event.set()

        logger.info(
            f"ConnectionOrchestrator: Client state reset. Active context set to '{client.context_manager.active_context_name}'."
        )
        client.ui_needs_update.set()

    async def establish_connection(self, server_config_to_use: ConnectionInfo) -> None:
        """
        Orchestrates the process of establishing a new connection.
        This includes updating network parameters, starting the network handler if needed,
        and ensuring handlers are initialized.
        """
        logger.info(f"ConnectionOrchestrator: Establishing connection to {server_config_to_use.server}:{server_config_to_use.port}")

        # Ensure handlers are initialized for the new connection attempt
        # This will use the server_config_to_use (via StateManager)
        self.initialize_handlers()

        # Update network handler with new parameters
        logger.debug(f"ConnectionOrchestrator: About to call update_connection_params for {server_config_to_use.server}")
        await self.network_handler.update_connection_params(
            server=server_config_to_use.server,
            port=server_config_to_use.port,
            use_ssl=server_config_to_use.ssl,
            channels_to_join=server_config_to_use.initial_channels
        )
        logger.debug(f"ConnectionOrchestrator: Returned from update_connection_params for {server_config_to_use.server}")

        # Start network handler if it's not already running
        if not self.network_handler._network_task or self.network_handler._network_task.done():
            logger.debug(f"ConnectionOrchestrator: About to call network_handler.start() for {server_config_to_use.server}")
            await self.network_handler.start()
            logger.info("ConnectionOrchestrator: Network handler started.")
        else:
            logger.info("ConnectionOrchestrator: Network handler already running, parameters updated.")

    # We will add more methods here in the following steps.
