import logging
from typing import TYPE_CHECKING, Optional, Set

from pyrc_core.irc.cap_negotiator import CapNegotiator
from pyrc_core.irc.sasl_authenticator import SaslAuthenticator
from pyrc_core.irc.registration_handler import RegistrationHandler
from pyrc_core.state_manager import ConnectionInfo
from pyrc_core.context_manager import ChannelJoinStatus # Added for reset_for_new_connection

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    from pyrc_core.network_handler import NetworkHandler
    from pyrc_core.state_manager import StateManager
    from pyrc_core.app_config import AppConfig


logger = logging.getLogger("pyrc.connection_orchestrator")

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
            desired_caps=set(conn_info.desired_caps),
            registration_handler=None,  # Will be set after RegistrationHandler is created
            client_logic_ref=self.client_logic_ref,
        )

        self.client_logic_ref.sasl_authenticator = SaslAuthenticator(
            network_handler=self.network_handler,
            cap_negotiator=self.client_logic_ref.cap_negotiator,
            password=conn_info.sasl_password or conn_info.nickserv_password,
            client_logic_ref=self.client_logic_ref,
        )

        self.client_logic_ref.registration_handler = RegistrationHandler(
            network_handler=self.network_handler,
            command_handler=self.client_logic_ref.command_handler,
            state_manager=self.state_manager,
            cap_negotiator=self.client_logic_ref.cap_negotiator,
            client_logic_ref=self.client_logic_ref,
        )

        # Link handlers back
        if self.client_logic_ref.cap_negotiator:
            self.client_logic_ref.cap_negotiator.registration_handler = self.client_logic_ref.registration_handler
            if hasattr(self.client_logic_ref.cap_negotiator, "set_sasl_authenticator"):
                self.client_logic_ref.cap_negotiator.set_sasl_authenticator(self.client_logic_ref.sasl_authenticator)

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

        # --- ADDED/MODIFIED CODE START ---
        # Get the set of previously pending initial joins
        old_pending_joins_normalized = set(self.client_logic_ref.pending_initial_joins)

        # Determine the new set of pending initial joins for this connection
        new_pending_joins_normalized: Set[str] = set()
        if server_config_to_use.initial_channels:
            new_pending_joins_normalized = {
                self.client_logic_ref.context_manager._normalize_context_name(ch)
                for ch in server_config_to_use.initial_channels if ch # Ensure channel name is not empty
            }

        # Update IRCClient_Logic's tracking
        self.client_logic_ref.pending_initial_joins = new_pending_joins_normalized
        logger.info(f"ConnectionOrchestrator: Updated client_logic.pending_initial_joins to: {new_pending_joins_normalized}")

        if not self.client_logic_ref.pending_initial_joins:
            self.client_logic_ref.all_initial_joins_processed.set()
            logger.debug("ConnectionOrchestrator: No new pending initial joins, all_initial_joins_processed set.")
        else:
            self.client_logic_ref.all_initial_joins_processed.clear()
            logger.debug(f"ConnectionOrchestrator: New pending initial joins exist ({len(new_pending_joins_normalized)}), all_initial_joins_processed cleared.")

        # Update join status for channels that are no longer pending initial join
        channels_no_longer_pending = old_pending_joins_normalized - new_pending_joins_normalized
        if channels_no_longer_pending:
            logger.debug(f"ConnectionOrchestrator: Channels no longer pending initial join: {channels_no_longer_pending}")
            for channel_name_norm in channels_no_longer_pending:
                original_channel_name = self.client_logic_ref.context_manager.find_original_case_for_normalized_name(channel_name_norm)
                if original_channel_name:
                    context = self.client_logic_ref.context_manager.get_context(original_channel_name)
                    if context and context.type == "channel" and context.join_status == ChannelJoinStatus.PENDING_INITIAL_JOIN:
                        logger.info(f"ConnectionOrchestrator: Channel '{original_channel_name}' ({channel_name_norm}) is no longer a pending initial join. Setting status to NOT_JOINED.")
                        context.join_status = ChannelJoinStatus.NOT_JOINED
                        # Optionally, add a status message to the channel itself or Status window
                        # await self.client_logic_ref.add_message(f"Auto-join for {original_channel_name} cancelled (not in current server's initial channels).", self.client_logic_ref.ui.colors.get("info", 0), context_name=original_channel_name)
                        self.client_logic_ref.ui_needs_update.set()
        # --- ADDED/MODIFIED CODE END ---

        # Start network handler if it's not already running
        if not self.network_handler._network_task or self.network_handler._network_task.done():
            logger.debug(f"ConnectionOrchestrator: About to call network_handler.start() for {server_config_to_use.server}")
            await self.network_handler.start()
            logger.info("ConnectionOrchestrator: Network handler started.")
        else:
            logger.info("ConnectionOrchestrator: Network handler already running, parameters updated.")
