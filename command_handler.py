# command_handler.py
import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from irc_client_logic import (
        IRCClient_Logic,
    )  # To avoid circular import for type hinting

# Get a logger instance
logger = logging.getLogger("pyrc.command_handler")


class CommandHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic

    def get_available_commands_for_tab_complete(self) -> List[str]:
        """
        Returns a list of commands primarily for tab-completion.
        This list is curated from the original do_tab_complete method.
        """
        return [
            "/join",
            "/j",
            "/part",
            "/p",
            "/msg",
            "/m",
            "/query",
            "/nick",
            "/n",
            "/quit",
            "/q",
            "/whois",
            "/w",
            "/me",
            "/away",
            "/invite",
            "/topic",
            "/raw",
            "/quote",
            "/connect",
            "/server",
            "/s", # Alias for /connect or /server
            "/disconnect",
            "/clear",
            "/next", "/nextwindow",
            "/prev", "/prevwindow",
            "/win", "/window",
            "/close", "/wc", "/partchannel",
            "/cyclechannel", "/cc", # Added
            "/prevchannel", "/pc",   # Added
            "/userlistscroll", # Added
            "/u",            # Alias for /userlistscroll
            "/status",         # Added
        ]

    def _handle_topic_command(self, args_str: str):
        topic_parts = args_str.split(" ", 1)
        current_active_ctx_name = self.client.context_manager.active_context_name
        target_channel_ctx_name = current_active_ctx_name  # Default to current
        new_topic = None

        if not target_channel_ctx_name:
            self.client.add_message(
                "No active window to get/set topic from.",
                self.client.ui.colors["error"],
                context_name="Status",
            )
            return

        current_context = self.client.context_manager.get_context(
            target_channel_ctx_name
        )

        if (
            not topic_parts or not topic_parts[0]
        ):  # /topic (view/set for current channel)
            if not (current_context and current_context.type == "channel"):
                self.client.add_message(
                    "Not in a channel to get/set topic. Current window is not a channel.",
                    self.client.ui.colors["error"],
                    context_name=target_channel_ctx_name,
                )
                return
            # If no args, it's a request for current topic (handled by new_topic is None below)
        elif topic_parts[0].startswith("#"):  # /topic #channel [new_topic]
            target_channel_ctx_name = topic_parts[0]
            # current_context = self.client.context_manager.get_context(target_channel_ctx_name) # Re-evaluate if needed
            if len(topic_parts) > 1:
                new_topic = topic_parts[1]
        else:  # /topic new topic for current channel
            if not (current_context and current_context.type == "channel"):
                self.client.add_message(
                    "Not in a channel to set topic. Current window is not a channel.",
                    self.client.ui.colors["error"],
                    context_name=target_channel_ctx_name,
                )
                return
            new_topic = args_str  # The whole arg string is the new topic

        if target_channel_ctx_name.startswith("#"):
             self.client.context_manager.create_context(
                target_channel_ctx_name, context_type="channel"
            )

        if new_topic is not None:
            self.client.network.send_raw(
                f"TOPIC {target_channel_ctx_name} :{new_topic}"
            )
        else:
            self.client.network.send_raw(f"TOPIC {target_channel_ctx_name}")

    def _handle_connect_command(self, args_str: str):
        from config import DEFAULT_PORT, DEFAULT_SSL_PORT

        conn_args = args_str.split()
        if not conn_args:
            self.client.add_message(
                "Usage: /connect <server[:port]> [ssl|nossl]",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name,
            )
            return
        new_server_host, new_port, new_ssl = conn_args[0], None, self.client.use_ssl
        if ":" in new_server_host:
            new_server_host, port_str = new_server_host.split(":", 1)
            try:
                new_port = int(port_str)
            except ValueError:
                self.client.add_message(
                    f"Invalid port: {port_str}",
                    self.client.ui.colors["error"],
                    context_name=self.client.context_manager.active_context_name,
                )
                return
        if len(conn_args) > 1:
            ssl_arg = conn_args[1].lower()
            if ssl_arg == "ssl":
                new_ssl = True
            elif ssl_arg == "nossl":
                new_ssl = False
        if new_port is None:
            new_port = DEFAULT_SSL_PORT if new_ssl else DEFAULT_PORT

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

        logger.debug("Clearing existing contexts for new server connection.")
        status_context = self.client.context_manager.get_context("Status")
        current_status_msgs = list(status_context.messages) if status_context else []
        status_scroll_offset = status_context.scrollback_offset if status_context and hasattr(status_context, 'scrollback_offset') else 0


        self.client.context_manager.contexts.clear()
        self.client.context_manager.create_context("Status", context_type="status")
        new_status_context = self.client.context_manager.get_context("Status")
        if new_status_context:
            for msg_tuple in current_status_msgs:
                new_status_context.add_message(msg_tuple[0], msg_tuple[1])
            if hasattr(new_status_context, 'scrollback_offset'):
                new_status_context.scrollback_offset = status_scroll_offset

        logger.debug(
            f"Restored {len(current_status_msgs)} messages to 'Status' context."
        )

        for ch_name in self.client.initial_channels_list:
            self.client.context_manager.create_context(ch_name, context_type="channel")
            logger.debug(f"Re-created initial channel context: {ch_name}")

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
        self.client.network.update_connection_params(
            self.client.server, self.client.port, self.client.use_ssl
        )

    def process_user_command(self, line: str):
        if not line:
            return
        if line.startswith("/"):
            parts = line.split(" ", 1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            logger.info(f"Processing command: {command} with args: '{args}'")
            if command in ["/quit", "/q"]:
                self.client.should_quit = True
                quit_message = args if args else "Client quitting"
                if self.client.network.connected:
                    self.client.network.send_raw(f"QUIT :{quit_message}")
                logger.info(f"QUIT command processed with message: {quit_message}")
                self.client.add_message(
                    "Quitting...",
                    self.client.ui.colors["system"],
                    context_name="Status",
                )
            elif command in ["/join", "/j"]:
                if args:
                    new_channel_target = args.split(" ")[0]
                    if not new_channel_target.startswith("#"):
                        new_channel_target = "#" + new_channel_target

                    current_active_ctx_name_for_join = (
                        self.client.context_manager.active_context_name
                    )
                    # Auto-parting logic removed for now based on previous decision
                    # if (
                    #     current_active_ctx_name_for_join
                    # ):
                    #     active_ctx = self.client.context_manager.get_context(
                    #         current_active_ctx_name_for_join
                    #     )
                    #     if (
                    #         current_active_ctx_name_for_join.startswith("#")
                    #         and current_active_ctx_name_for_join.lower()
                    #         != new_channel_target.lower()
                    #         and active_ctx
                    #         and active_ctx.type == "channel"
                    #     ):
                    #         # self.client.network.send_raw(
                    #         #     f"PART {current_active_ctx_name_for_join} :Changing channels"
                    #         # )
                    #         pass

                    if self.client.context_manager.create_context(
                        new_channel_target, context_type="channel"
                    ):
                        logger.debug(
                            f"Ensured context for {new_channel_target} exists before sending JOIN."
                        )
                    self.client.network.send_raw(f"JOIN {new_channel_target}")
                    self.client.add_message(
                        f"Attempting to join {new_channel_target}...",
                        self.client.ui.colors["system"],
                        context_name=new_channel_target, # Message to the new channel context
                    )
                    # Optionally switch to the new channel context immediately
                    self.client.switch_active_context(new_channel_target)

                else:
                    logger.warning("JOIN command issued with no arguments.")
                    self.client.add_message(
                        "Usage: /join #channel",
                        self.client.ui.colors["error"],
                        context_name=self.client.context_manager.active_context_name,
                    )
            elif command in ["/part", "/p"]:
                current_active_ctx_name = (
                    self.client.context_manager.active_context_name
                )
                target_part_channel = current_active_ctx_name
                part_message = "Leaving"
                part_args_parts = args.split(" ", 1)

                if args and args.startswith("#"):
                    target_part_channel = part_args_parts[0]
                    if len(part_args_parts) > 1:
                        part_message = part_args_parts[1]
                elif args: # /part message for current channel
                    part_message = args

                if (
                    not target_part_channel
                ):
                    self.client.add_message(
                        "No active window to part from.",
                        self.client.ui.colors["error"],
                        context_name="Status",
                    )
                    return

                part_context = self.client.context_manager.get_context(
                    target_part_channel
                )
                if part_context and part_context.type == "channel":
                    self.client.network.send_raw(
                        f"PART {target_part_channel} :{part_message}"
                    )
                    # Message about parting will be added to the channel context by protocol handler for self-part
                else:
                    self.client.add_message(
                        f"Cannot part: '{target_part_channel}' is not a channel or you are not in it.",
                        self.client.ui.colors["error"],
                        context_name=(
                            current_active_ctx_name
                            if current_active_ctx_name
                            else "Status"
                        ),
                    )
            elif command in ["/nick", "/n"]:
                if args:
                    self.client.network.send_raw(f"NICK {args.split(' ')[0]}")
                else:
                    self.client.add_message(
                        "Usage: /nick <new_nickname>",
                        self.client.ui.colors["error"],
                        context_name=self.client.context_manager.active_context_name,
                    )
            elif command in ["/msg", "/query", "/m"]:
                msg_parts = args.split(" ", 1)
                if len(msg_parts) == 2:
                    target_nick, message = msg_parts
                    self.client.network.send_raw(f"PRIVMSG {target_nick} :{message}")
                    query_context_name = f"Query:{target_nick}"
                    if self.client.context_manager.create_context(
                        query_context_name, context_type="query"
                    ):
                        logger.debug(f"Ensured query context for {target_nick} exists.")
                    self.client.add_message(
                        f"[To {target_nick}] {message}",
                        self.client.ui.colors["my_message"],
                        context_name=query_context_name,
                    )
                    if (
                        self.client.context_manager.active_context_name
                        != query_context_name
                    ):
                        self.client.switch_active_context(
                            query_context_name
                        )
                else:
                    logger.warning("MSG/QUERY command with insufficient arguments.")
                    self.client.add_message(
                        "Usage: /msg <nickname> <message>",
                        self.client.ui.colors["error"],
                        context_name=self.client.context_manager.active_context_name,
                    )
            elif command == "/me":
                current_active_ctx_name = (
                    self.client.context_manager.active_context_name
                )
                if not current_active_ctx_name:
                    self.client.add_message(
                        "No active window to use /me in.",
                        self.client.ui.colors["error"],
                        context_name="Status",
                    )
                    return

                active_ctx = self.client.context_manager.get_context(
                    current_active_ctx_name
                )
                if (
                    args
                    and active_ctx
                    and (active_ctx.type == "channel" or active_ctx.type == "query") # Allow /me in queries
                    and self.client.network.connected
                ):
                    target_for_action = current_active_ctx_name
                    if active_ctx.type == "query":
                         if ":" in current_active_ctx_name:
                            target_for_action = current_active_ctx_name.split(":", 1)[1]
                         else: # Should not happen
                            logger.warning(f"Malformed query context for /me: {current_active_ctx_name}")
                            return

                    self.client.network.send_raw(
                        f"PRIVMSG {target_for_action} :\x01ACTION {args}\x01"
                    )
                    self.client.add_message(
                        f"* {self.client.nick} {args}",
                        self.client.ui.colors["my_message"] if active_ctx.type == "query" else self.client.ui.colors["channel_message"],
                        context_name=current_active_ctx_name,
                    )
                elif not (active_ctx and (active_ctx.type == "channel" or active_ctx.type == "query")):
                    self.client.add_message(
                        "You can only use /me in a channel or query window.",
                        self.client.ui.colors["error"],
                        context_name=current_active_ctx_name,
                    )
                elif not self.client.network.connected:
                    self.client.add_message(
                        "Not connected.",
                        self.client.ui.colors["error"],
                        context_name="Status", # Or current_active_ctx_name
                    )
                else: # No args
                    self.client.add_message(
                        "Usage: /me <action>",
                        self.client.ui.colors["error"],
                        context_name=current_active_ctx_name,
                    )
            elif command == "/away":
                if args:
                    self.client.network.send_raw(f"AWAY :{args}")
                    self.client.add_message(
                        f"You are now marked as away: {args}",
                        self.client.ui.colors["system"],
                        context_name="Status",
                    )
                else:
                    self.client.network.send_raw("AWAY")
                    self.client.add_message(
                        "You are no longer marked as away.",
                        self.client.ui.colors["system"],
                        context_name="Status",
                    )
            elif command == "/invite":
                invite_parts = args.split(" ", 1)
                if len(invite_parts) == 2:
                    nick, chan = invite_parts
                    if not chan.startswith("#"):
                        chan = "#" + chan
                    self.client.network.send_raw(f"INVITE {nick} {chan}")
                    self.client.add_message(
                        f"Invited {nick} to {chan}.",
                        self.client.ui.colors["system"],
                        context_name=self.client.context_manager.active_context_name,
                    )
                else:
                    self.client.add_message(
                        "Usage: /invite <nick> <#channel>",
                        self.client.ui.colors["error"],
                        context_name=self.client.context_manager.active_context_name,
                    )
            elif command in [
                "/whois",
                "/w",
            ]:
                if args:
                    self.client.network.send_raw(f"WHOIS {args.split(' ')[0]}")
                else:
                    self.client.add_message(
                        "Usage: /whois <nick>",
                        self.client.ui.colors["error"],
                        context_name=self.client.context_manager.active_context_name,
                    )
            elif command == "/topic":
                self._handle_topic_command(args)
            elif command in ["/raw", "/quote"]:
                if args:
                    self.client.network.send_raw(args)
                    self.client.add_message(
                        f"RAW > {args}",
                        self.client.ui.colors["system"],
                        context_name="Status",
                    )
                else:
                    self.client.add_message(
                        "Usage: /raw <raw IRC command>",
                        self.client.ui.colors["error"],
                        context_name=self.client.context_manager.active_context_name,
                    )
            elif command == "/clear":
                current_active_ctx_name = (
                    self.client.context_manager.active_context_name
                )
                if not current_active_ctx_name:
                    self.client.add_message(
                        "No active window to clear.",
                        self.client.ui.colors["error"],
                        context_name="Status",
                    )
                    return

                active_ctx = self.client.context_manager.get_context(
                    current_active_ctx_name
                )
                if active_ctx:
                    active_ctx.messages.clear()
                    active_ctx.unread_count = 0
                    if hasattr(active_ctx, 'scrollback_offset'):
                        active_ctx.scrollback_offset = 0
                    self.client.add_message(
                        "Messages cleared for current context.",
                        self.client.ui.colors["system"],
                        False,
                        context_name=current_active_ctx_name,
                    )
                else:
                    logger.error(
                        f"'/clear' command: Active context '{current_active_ctx_name}' not found in manager."
                    )
                    self.client.add_message(
                        f"Error: Active context '{current_active_ctx_name}' not found to clear.",
                        self.client.ui.colors["error"],
                        context_name="Status",
                    )
            elif command in ["/connect", "/server", "/s"]: # Ensure /s is for connect/server
                self._handle_connect_command(args)
            elif command == "/disconnect":
                if self.client.network.connected:
                    self.client.network.disconnect_gracefully(
                        "Client disconnect command"
                    )
                    self.client.add_message(
                        "Disconnecting...",
                        self.client.ui.colors["system"],
                        context_name="Status",
                    )
                else:
                    self.client.add_message(
                        "Not currently connected.",
                        self.client.ui.colors["system"],
                        context_name="Status",
                    )
            elif command in ["/next", "/nextwindow"]:
                self.client.switch_active_context("next")
            elif command in ["/prev", "/prevwindow"]:
                self.client.switch_active_context("prev")
            elif command in ["/cyclechannel", "/cc"]: # New command
                self.client.switch_active_channel("next")
            elif command in ["/prevchannel", "/pc"]:   # New command
                self.client.switch_active_channel("prev")
            elif command == "/status": # Only /status, /s is for server/connect
                self.client.switch_active_context("Status")
            elif command in [
                "/win",
                "/window",
            ]:
                win_args = args.split(" ", 1)
                if win_args[0]:
                    self.client.switch_active_context(win_args[0])
                else:
                    msg_lines = ["Open contexts (use /win <number_or_name> to switch):"]
                    # Sort for consistent numbering, Status first
                    all_context_names = self.client.context_manager.get_all_context_names()
                    context_keys = ["Status"] + sorted([name for name in all_context_names if name != "Status"])

                    active_ctx_name_for_list = (
                        self.client.context_manager.active_context_name
                    )
                    for i, name in enumerate(context_keys):
                        if name not in all_context_names: continue # if Status was manually removed somehow

                        ctx_obj = self.client.context_manager.get_context(name)
                        unread_str = ""
                        if ctx_obj and ctx_obj.unread_count > 0:
                            unread_str = f" ({ctx_obj.unread_count} unread)"

                        type_indicator = ""
                        if ctx_obj:
                            if ctx_obj.type == "channel": type_indicator = "[C]"
                            elif ctx_obj.type == "query": type_indicator = "[Q]"
                            elif ctx_obj.type == "status": type_indicator = "[S]"

                        active_marker = "*" if name == active_ctx_name_for_list else " "
                        msg_lines.append(f" {i+1}: {active_marker}{name}{type_indicator}{unread_str}")

                    target_ctx_for_listing = active_ctx_name_for_list if active_ctx_name_for_list else "Status"
                    # Ensure target_ctx_for_listing exists, fallback to Status if it was closed.
                    if not self.client.context_manager.get_context(target_ctx_for_listing):
                        target_ctx_for_listing = "Status"
                        if not self.client.context_manager.get_context(target_ctx_for_listing): # If even status is gone (should not happen)
                             print("CRITICAL: No Status context for /win listing") # Last resort
                             return


                    for m_line in msg_lines:
                        self.client.add_message(
                            m_line,
                            self.client.ui.colors["system"],
                            prefix_time=False,
                            context_name=target_ctx_for_listing,
                        )
            elif command in ["/close", "/wc", "/partchannel"]:
                current_active_ctx_name = (
                    self.client.context_manager.active_context_name
                )
                context_to_close = current_active_ctx_name
                close_reason = "Closed by user"
                close_args_parts = args.split(" ", 1)

                if args and (args.startswith("#") or args.lower().startswith("query:")):
                    context_to_close = close_args_parts[0]
                    if len(close_args_parts) > 1:
                        close_reason = close_args_parts[1]
                elif args:
                    close_reason = args


                if not context_to_close:
                    self.client.add_message(
                        "No window specified or active to close.",
                        self.client.ui.colors["error"],
                        context_name="Status",
                    )
                    return

                if context_to_close == "Status":
                    self.client.add_message(
                        "Cannot close the Status window.",
                        self.client.ui.colors["error"],
                        context_name="Status",
                    )
                else:
                    ctx_to_close_obj = self.client.context_manager.get_context(
                        context_to_close
                    )
                    if ctx_to_close_obj:
                        ctx_type = ctx_to_close_obj.type
                        is_active_context = (
                            self.client.context_manager.active_context_name
                            == context_to_close
                        )

                        if ctx_type == "channel":
                            self.client.network.send_raw(
                                f"PART {context_to_close} :{close_reason}"
                            )
                            # Message will be added by protocol handler.
                            # Context removal/switch will also be handled by protocol handler for self-part.
                        elif ctx_type == "query" or ctx_type == "generic":
                            removed = self.client.context_manager.remove_context(
                                context_to_close
                            )
                            if removed:
                                self.client.add_message(
                                    f"Closed window: {context_to_close}",
                                    self.client.ui.colors["system"],
                                    context_name="Status",
                                )
                                if is_active_context:
                                    # Determine next context to switch to
                                    all_contexts = self.client.context_manager.get_all_context_names()
                                    if "Status" in all_contexts:
                                        self.client.switch_active_context("Status")
                                    elif all_contexts: # Switch to first available if Status is somehow gone
                                        self.client.switch_active_context(all_contexts[0])
                                    # If no contexts left, active_context_name will be None, handled by UI
                            else:
                                logger.error(
                                    f"Failed to remove context '{context_to_close}' though it was found."
                                )
                    else:
                        self.client.add_message(
                            f"Window '{context_to_close}' not found to close.",
                            self.client.ui.colors["error"],
                            context_name=(
                                current_active_ctx_name
                                if current_active_ctx_name
                                else "Status"
                            ),
                        )
            elif command in ["/userlistscroll", "/u"]:
                active_ctx_for_msg = self.client.context_manager.active_context_name or "Status"

                direction_arg = ""
                lines_value_arg_str = None
                lines_value_arg_int = None

                if command == "/u" and not args:
                    direction_arg = "pagedown" # Default for /u without args
                else:
                    parts = args.split(maxsplit=1)
                    direction_arg = parts[0].lower() if parts else ""
                    lines_value_arg_str = parts[1] if len(parts) > 1 else None

                valid_directions = ["up", "down", "pageup", "pagedown", "top", "bottom"]

                usage_msg = f"Usage: {command} <up|down|pageup|pagedown|top|bottom> [lines]"
                if command == "/u":
                    usage_msg = f"Usage: /u [up|down|pageup|pagedown|top|bottom] [lines] (Defaults to pagedown if no args)"


                if not direction_arg or direction_arg not in valid_directions:
                    self.client.add_message(
                        usage_msg,
                        self.client.ui.colors["error"],
                        context_name=active_ctx_for_msg,
                    )
                else:
                    if lines_value_arg_str:
                        try:
                            lines_value_arg_int = int(lines_value_arg_str)
                            if lines_value_arg_int <= 0:
                                self.client.add_message(
                                    "Scroll line count must be a positive number.",
                                    self.client.ui.colors["error"],
                                    context_name=active_ctx_for_msg,
                                )
                                lines_value_arg_int = None # Invalidate
                            elif direction_arg not in ["up", "down"]:
                                self.client.add_message(
                                    f"Line count argument is only valid for 'up' or 'down' directions.",
                                    self.client.ui.colors["error"],
                                    context_name=active_ctx_for_msg,
                                )
                                lines_value_arg_int = None # Invalidate
                        except ValueError:
                            self.client.add_message(
                                "Invalid line count for scroll.",
                                self.client.ui.colors["error"],
                                context_name=active_ctx_for_msg,
                            )
                            lines_value_arg_int = None # Invalidate

                    # Proceed if lines_value_arg_int is valid or None (for directions not requiring it)
                    if lines_value_arg_int is not None or lines_value_arg_str is None:
                        if hasattr(self.client.ui, 'scroll_user_list'):
                             self.client.ui.scroll_user_list(direction_arg, lines_value_arg_int)
                        else:
                            logger.error("scroll_user_list method not found on UIManager")
                            self.client.add_message(
                                "Error: User list scrolling feature not fully implemented (UI component missing).",
                                self.client.ui.colors["error"],
                                context_name=active_ctx_for_msg,
                             )

            else:
                self.client.add_message(
                    f"Unknown command: {command}",
                    self.client.ui.colors["error"],
                    context_name=self.client.context_manager.active_context_name,
                )
        else:
            current_active_ctx_name_msg = (
                self.client.context_manager.active_context_name
            )
            if not current_active_ctx_name_msg:
                self.client.add_message(
                    "No active window to send a message to.",
                    self.client.ui.colors["error"],
                    context_name="Status",
                )
                return

            active_ctx = self.client.context_manager.get_context(
                current_active_ctx_name_msg
            )
            if (
                active_ctx
                and (active_ctx.type == "channel" or active_ctx.type == "query")
                and self.client.network.connected
            ):
                target_for_privmsg = current_active_ctx_name_msg
                if active_ctx.type == "query":
                    if ":" in current_active_ctx_name_msg:
                        target_for_privmsg = current_active_ctx_name_msg.split(":", 1)[
                            1
                        ]
                    else:
                        logger.warning(
                            f"Query context name '{current_active_ctx_name_msg}' malformed for PRIVMSG."
                        )
                        self.client.add_message(
                            "Error: Malformed query context name.",
                            self.client.ui.colors["error"],
                            context_name="Status",
                        )
                        return

                self.client.network.send_raw(f"PRIVMSG {target_for_privmsg} :{line}")
                self.client.add_message(
                    f"<{self.client.nick}> {line}",
                    self.client.ui.colors["my_message"],
                    context_name=current_active_ctx_name_msg,
                )
            elif not self.client.network.connected:
                self.client.add_message(
                    "Not connected. Use /connect <server> to connect.",
                    self.client.ui.colors["error"],
                    context_name="Status",
                )
            else:
                self.client.add_message(
                    "Cannot send messages here. Join a channel with /join #channel or start a query with /msg <nick> <message>.",
                    self.client.ui.colors["error"],
                    context_name=(
                        current_active_ctx_name_msg
                        if current_active_ctx_name_msg
                        else "Status"
                    ),
                )
        self.client.ui_needs_update.set()
