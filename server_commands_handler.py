import logging
from typing import TYPE_CHECKING, Optional, Tuple
import time

from context_manager import ChannelJoinStatus
from config import DEFAULT_PORT, DEFAULT_SSL_PORT  # For _parse_connect_args

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.server_commands_handler")


class ServerCommandsHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic

    def _reset_contexts_for_new_connection(self):
        logger.debug("Clearing existing contexts for new server connection.")
        status_context = self.client.context_manager.get_context("Status")
        current_status_msgs = list(status_context.messages) if status_context else []
        status_scroll_offset = (
            status_context.scrollback_offset
            if status_context and hasattr(status_context, "scrollback_offset")
            else 0
        )

        self.client.context_manager.contexts.clear()
        self.client.context_manager.create_context("Status", context_type="status")
        new_status_context = self.client.context_manager.get_context("Status")
        if new_status_context:
            for msg_tuple in current_status_msgs:
                new_status_context.add_message(msg_tuple[0], msg_tuple[1])
            if hasattr(new_status_context, "scrollback_offset"):
                new_status_context.scrollback_offset = status_scroll_offset
        logger.debug(
            f"Restored {len(current_status_msgs)} messages to 'Status' context."
        )

        for ch_name in self.client.initial_channels_list:
            self.client.context_manager.create_context(
                ch_name,
                context_type="channel",
                initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN,
            )
            logger.debug(
                f"Re-created initial channel context: {ch_name} with PENDING_INITIAL_JOIN status."
            )

        if self.client.initial_channels_list:
            self.client.context_manager.set_active_context(
                self.client.initial_channels_list[0]
            )
        else:
            self.client.context_manager.set_active_context("Status")
        logger.info(
            f"Set active context to '{self.client.context_manager.active_context_name}' after server change."
        )
        self.client.ui_needs_update.set()

    def handle_disconnect_command(self, args_str: str):
        """Handle the /disconnect command"""
        reason = args_str if args_str else "Disconnecting"
        self.client.network_handler.disconnect_gracefully(reason)

    def handle_quit_command(self, args_str: str):
        """Handle the /quit command"""
        if args_str:
            reason = args_str
        else:
            # Try to get a random quit message from scripts
            variables = {"nick": self.client.nick, "server": self.client.server}
            reason = self.client.script_manager.get_random_quit_message_from_scripts(
                variables
            )
            if not reason:
                reason = "Leaving"  # Fallback if no script provides a message
        self.client.network_handler.disconnect_gracefully(reason)

    def handle_raw_command(self, args_str: str):
        """Handle the /raw command"""
        help_data = self.client.script_manager.get_help_text_for_command("raw")
        usage_msg = (
            help_data["help_text"] if help_data else "Usage: /raw <raw IRC command>"
        )
        if not self.client.command_handler._ensure_args(args_str, usage_msg):
            return
        self.client.network_handler.send_raw(args_str)

    def handle_reconnect_command(self, args_str: str):
        """Handles the /reconnect command."""
        if not self.client.server or self.client.port is None: # Check both server and port
            help_data = self.client.script_manager.get_help_text_for_command(
                "reconnect"
            )
            usage_msg = (
                help_data["help_text"]
                if help_data
                else "Cannot reconnect: No server configured or port missing. Use /server or /connect first."
            )
            self.client.add_message(
                usage_msg,
                self.client.ui.colors["error"],
                context_name="Status",
            )
            return

        # At this point, self.client.server and self.client.port are guaranteed to be non-None
        # due to the check above.
        current_server: str = self.client.server
        current_port: int = self.client.port

        self.client.add_message(
            f"Reconnecting to {current_server}:{current_port}...",
            self.client.ui.colors["system"],
            context_name="Status",
        )
        logger.info(
            f"User initiated /reconnect to {current_server}:{current_port}"
        )

        # Disconnect if currently connected
        if self.client.network_handler.connected:
            self.client.network_handler.disconnect_gracefully("Reconnecting")

        # The network loop will attempt to reconnect using existing parameters.
        # We can ensure it does so by calling update_connection_params,
        # which also resets the reconnect delay and ensures the network thread is running.
        # If the network thread is already running and was connected,
        # disconnect_gracefully would have set connected = False,
        # and the loop would naturally try to reconnect.
        # Calling update_connection_params makes this more explicit and handles
        # the case where the network thread might not be running.
        self.client.network_handler.update_connection_params(
            server=current_server, # Pass the non-None server
            port=current_port,       # Pass the non-None port
            use_ssl=self.client.use_ssl,
            channels_to_join=self.client.network_handler.channels_to_join_on_connect,  # Use current list
        )
        # No need to call _reset_contexts_for_new_connection here,
        # as update_connection_params (if it disconnects) or the natural
        # reconnect cycle in NetworkHandler._network_loop -> _connect_socket
        # should lead to CapNegotiator and RegistrationHandler resetting state
        # and re-joining channels, which implicitly resets contexts or prepares them.
        # If a full context reset like in /connect is desired, _reset_contexts_for_new_connection()
        # could be called before update_connection_params. For now, a simpler reconnect is implemented.

    def handle_server_command(self, args_str: str):
        """Handle the /server command for switching between configured servers."""
        if not args_str:
            help_data = self.client.script_manager.get_help_text_for_command("server")
            usage_msg = (
                help_data["help_text"] if help_data else "Usage: /server <config_name>"
            )
            self.client.add_message(
                usage_msg,
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return

        config_name = args_str.strip()
        if config_name not in self.client.all_server_configs:
            self.client.add_message(
                f"Server configuration '{config_name}' not found. Available configurations: {', '.join(sorted(self.client.all_server_configs.keys()))}",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return

        # If already connected and switching to a different server
        if (
            self.client.network_handler.connected
            and config_name != self.client.active_server_config_name
        ):
            self.client.network_handler.disconnect_gracefully(
                "Switching server configurations..."
            )
            # Wait for network thread to stop and connection to reset
            # TODO: Replace with proper event-based approach
            time.sleep(3)

        # Update active server configuration
        self.client.active_server_config_name = config_name
        self.client.active_server_config = self.client.all_server_configs[config_name]

        # Update client's connection attributes
        self.client.server = self.client.active_server_config.address
        self.client.port = self.client.active_server_config.port
        self.client.nick = self.client.active_server_config.nick
        self.client.initial_channels_list = self.client.active_server_config.channels[:]
        self.client.password = self.client.active_server_config.server_password
        self.client.nickserv_password = (
            self.client.active_server_config.nickserv_password
        )
        self.client.use_ssl = self.client.active_server_config.ssl
        self.client.verify_ssl_cert = self.client.active_server_config.verify_ssl_cert

        # Reconfigure handlers
        self.client.network_handler.channels_to_join_on_connect = (
            self.client.active_server_config.channels[:]
        )

        # Call the new helper method in IRCClient_Logic to re-initialize
        # desired_caps_config, CapNegotiator, SaslAuthenticator, and RegistrationHandler
        self.client._initialize_connection_handlers()

        # Reset contexts for new connection
        self._reset_contexts_for_new_connection()

        # Update network handler connection parameters
        if (
            self.client.server and self.client.port
        ):  # Ensure we have valid connection parameters
            self.client.network_handler.update_connection_params(
                server=self.client.server,
                port=self.client.port,
                use_ssl=self.client.use_ssl,
                channels_to_join=self.client.initial_channels_list,
            )

            self.client.add_message(
                f"Switched active server configuration to '{config_name}'. Attempting to connect...",
                self.client.ui.colors["system"],
                context_name="Status",
            )
        else:
            self.client.add_message(
                f"Error: Invalid server configuration for '{config_name}'. Missing server address or port.",
                self.client.ui.colors["error"],
                context_name="Status",
            )
