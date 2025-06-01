# server_commands_handler.py
import logging
from typing import TYPE_CHECKING, Optional, Tuple

from context_manager import ChannelJoinStatus
from config import DEFAULT_PORT, DEFAULT_SSL_PORT # For _parse_connect_args

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.server_commands_handler")

class ServerCommandsHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic

    def _parse_connect_args(self, args_str: str) -> Optional[Tuple[str, int, bool]]:
        conn_args = args_str.split()
        if not conn_args:
            self.client.add_message(
                "Usage: /connect <server[:port]> [ssl|nossl]",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return None

        new_server_host, port_str_arg = conn_args[0], None
        new_port: Optional[int] = None
        new_ssl: bool = self.client.use_ssl

        if ":" in new_server_host:
            new_server_host, port_str_arg = new_server_host.split(":", 1)
            try:
                new_port = int(port_str_arg)
            except ValueError:
                self.client.add_message(
                    f"Invalid port: {port_str_arg}",
                    self.client.ui.colors["error"],
                    context_name=self.client.context_manager.active_context_name,
                )
                return None

        if len(conn_args) > 1:
            ssl_arg = conn_args[1].lower()
            if ssl_arg == "ssl":
                new_ssl = True
            elif ssl_arg == "nossl":
                new_ssl = False

        if new_port is None:
            new_port = DEFAULT_SSL_PORT if new_ssl else DEFAULT_PORT

        return new_server_host, new_port, new_ssl

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
                initial_join_status_for_channel=ChannelJoinStatus.PENDING_INITIAL_JOIN
            )
            logger.debug(f"Re-created initial channel context: {ch_name} with PENDING_INITIAL_JOIN status.")

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

    def handle_connect_command(self, args_str: str):
        parsed_args = self._parse_connect_args(args_str)
        if parsed_args is None:
            return

        new_server_host, new_port, new_ssl = parsed_args

        if self.client.network.connected:
            self.client.network.disconnect_gracefully("Changing servers")

        self.client.server = new_server_host
        self.client.port = new_port
        self.client.use_ssl = new_ssl

        self.client.add_message(
            f"Attempting to connect to: {self.client.server}:{self.client.port} (SSL: {self.client.use_ssl})",
            self.client.ui.colors["system"],
            context_name="Status",
        )
        logger.info(
            f"Attempting new connection to: {self.client.server}:{self.client.port} (SSL: {self.client.use_ssl})"
        )

        self._reset_contexts_for_new_connection()

        logger.info(
            f"ServerCommandsHandler: Before update_connection_params. Server: {self.client.server}, Port: {self.client.port}, SSL: {self.client.use_ssl}, Verify SSL: {self.client.verify_ssl_cert}"
        )
        self.client.network.update_connection_params(
            self.client.server, self.client.port, self.client.use_ssl
        )

    def handle_disconnect_command(self, args_str: str):
        """Handle the /disconnect command"""
        reason = args_str if args_str else "Disconnecting"
        self.client.network.disconnect_gracefully(reason)

    def handle_quit_command(self, args_str: str):
        """Handle the /quit command"""
        reason = args_str if args_str else "Leaving"
        self.client.network.disconnect_gracefully(reason)

    def handle_raw_command(self, args_str: str):
        """Handle the /raw command"""
        if not self.client.command_handler._ensure_args(args_str, "Usage: /raw <raw IRC command>"):
            return
        self.client.network.send_raw(args_str)
