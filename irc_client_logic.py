# irc_client_logic.py
import curses
import threading
import time
import socket
from collections import deque
from typing import Optional, Any  # Added Optional, Any
import logging  # Added for logging

from config import MAX_HISTORY
from config import RECONNECT_INITIAL_DELAY as CFG_RECONNECT_INITIAL_DELAY
from ui_manager import UIManager
from network_handler import NetworkHandler
import irc_protocol

# Get a logger instance (child of the main pyrc logger if configured that way)
logger = logging.getLogger("pyrc.logic")


class IRCClient_Logic:
    def __init__(
        self,
        stdscr,
        server_addr,
        port,
        nick,
        initial_channels_raw: list,
        password,
        nickserv_password,
        use_ssl,
    ):
        self.stdscr = stdscr
        self.server = server_addr
        self.port = port
        self.initial_nick = nick
        self.nick = nick

        self.initial_channels_list = []
        if initial_channels_raw and isinstance(initial_channels_raw, list):
            for ch in initial_channels_raw:
                if isinstance(ch, str):
                    processed_ch = ch.lstrip()
                    if not processed_ch.startswith("#"):
                        processed_ch = "#" + processed_ch
                    self.initial_channels_list.append(processed_ch)

        # self.channel is deprecated, use self.active_context_name
        # self.channel_users is deprecated, use self.contexts[context_name]['users']

        self.password = password
        self.nickserv_password = nickserv_password
        self.use_ssl = use_ssl

        self.contexts = {}
        self.active_context_name = "Status"  # Default active context
        self._create_context("Status", context_type="status")

        for ch_name in self.initial_channels_list:
            self._create_context(ch_name, context_type="channel")

        if self.initial_channels_list:
            self.active_context_name = self.initial_channels_list[0]

        # self.message_history is deprecated
        # self.channel_users is deprecated
        self.input_buffer = ""
        self.partial_input_history = deque(maxlen=20)
        self.partial_input_history_idx = -1

        self.should_quit = False
        self.ui_needs_update = threading.Event()

        self.network = NetworkHandler(self)
        self.ui = UIManager(stdscr, self)

        self.add_message(
            "Simple IRC Client starting...",
            self.ui.colors["system"],
            context_name="Status",
        )
        initial_channels_display = (
            ", ".join(self.initial_channels_list)
            if self.initial_channels_list
            else "None"
        )
        self.add_message(
            f"Target: {self.server}:{self.port}, Nick: {self.nick}, Channels: {initial_channels_display}",
            self.ui.colors["system"],
            context_name="Status",
        )
        logger.info(
            f"IRCClient_Logic initialized for {self.server}:{self.port} as {self.nick}. Channels: {initial_channels_display}"
        )

    def _create_context(
        self,
        context_name: str,
        context_type: str = "generic",
        topic: Optional[str] = None,
    ):
        if context_name not in self.contexts:
            self.contexts[context_name] = {
                "messages": deque(maxlen=MAX_HISTORY),
                "users": set(),
                "topic": topic,
                "unread_count": 0,
                "type": context_type,  # "status", "channel", "query"
                "last_read_line_count": 0,  # For UI to track scroll position on switch
            }
            logger.debug(f"Created context: {context_name} of type {context_type}")
            return True
        logger.warning(f"Context {context_name} already exists, not creating.")
        return False

    def add_message(
        self,
        text: str,
        color_attr: int,
        prefix_time: bool = True,
        context_name: Optional[str] = None,
    ):
        target_context_name = (
            context_name if context_name is not None else self.active_context_name
        )

        if target_context_name not in self.contexts:
            # If context doesn't exist (e.g. new PM), create it.
            # For now, assume it's a query if not 'Status' or an existing channel.
            # This logic might need refinement based on where add_message is called from.
            context_type = (
                "query"
                if not target_context_name.startswith("#")
                and target_context_name != "Status"
                else "generic"
            )
            if self._create_context(target_context_name, context_type=context_type):
                logger.info(
                    f"Dynamically created context '{target_context_name}' of type '{context_type}' for message."
                )
            else:
                # This case should ideally not be hit if _create_context handles existing contexts gracefully
                logger.error(
                    f"Failed to create context '{target_context_name}' for message, or it already existed unexpectedly."
                )
                # Fallback to Status if context creation fails for some reason
                # self.add_message(f"Error: Tried to add message to non-existent context '{target_context_name}'. Msg: {text}", self.ui.colors["error"], context_name="Status")
                # return # Decided to let it proceed and add to the context if it was created by another thread in the meantime.

        max_w = (
            self.ui.msg_win_width - 1 if self.ui.msg_win_width > 1 else 80
        )  # This will need context later
        timestamp = time.strftime("%H:%M:%S ") if prefix_time else ""
        full_message = f"{timestamp}{text}"
        lines = []
        current_line = ""
        for word in full_message.split(" "):
            if len(current_line) + len(word) + 1 > max_w and current_line:
                lines.append(current_line)
                current_line = word
            else:
                if current_line:
                    current_line += " "
                current_line += word
        if current_line:
            lines.append(current_line)

        context_messages = self.contexts[target_context_name]["messages"]
        for line_part in lines:
            context_messages.append((line_part, color_attr))

        if target_context_name != self.active_context_name:
            self.contexts[target_context_name]["unread_count"] += len(lines)

        # This part needs to be context-aware when UIManager is updated
        if (
            self.ui.current_line_in_history > 0
            and target_context_name == self.active_context_name
        ):
            self.ui.current_line_in_history += len(lines)

        self.ui_needs_update.set()

    def on_server_message(self, line):
        logger.debug(f"S << {line.strip()}")
        irc_protocol.handle_server_message(self, line)

    def handle_input(self, key_code):
        # logger.debug(f"Input key_code: {key_code}") # Can be very verbose
        if key_code == curses.ERR:
            return
        if key_code == curses.KEY_RESIZE:
            self.ui.setup_layout()
        elif key_code in [curses.KEY_BACKSPACE, 127, 8]:
            self.input_buffer = self.input_buffer[:-1]
        elif key_code in [curses.KEY_ENTER, 10, 13]:
            if self.input_buffer:
                command_to_process = self.input_buffer
                self.process_user_command(command_to_process)  # process a copy
                if command_to_process:  # Use the copy for history
                    if (
                        not self.partial_input_history
                        or self.partial_input_history[-1] != command_to_process
                    ):
                        self.partial_input_history.append(command_to_process)
                self.input_buffer = ""
                self.partial_input_history_idx = -1
        elif key_code == curses.KEY_UP:
            if self.partial_input_history:
                if self.partial_input_history_idx == -1:
                    self.partial_input_history_idx = len(self.partial_input_history) - 1
                elif self.partial_input_history_idx > 0:
                    self.partial_input_history_idx -= 1
                if (
                    0
                    <= self.partial_input_history_idx
                    < len(self.partial_input_history)
                ):
                    self.input_buffer = self.partial_input_history[
                        self.partial_input_history_idx
                    ]
        elif key_code == curses.KEY_DOWN:
            if self.partial_input_history and self.partial_input_history_idx != -1:
                if self.partial_input_history_idx < len(self.partial_input_history) - 1:
                    self.partial_input_history_idx += 1
                    self.input_buffer = self.partial_input_history[
                        self.partial_input_history_idx
                    ]
                else:
                    self.partial_input_history_idx = -1
                    self.input_buffer = ""
        elif key_code == curses.KEY_PPAGE:
            self.ui.scroll_messages("up")
        elif key_code == curses.KEY_NPAGE:
            self.ui.scroll_messages("down")
        elif key_code == curses.KEY_HOME:
            self.ui.scroll_messages("home")
        elif key_code == curses.KEY_END:
            self.ui.scroll_messages("end")
        # Ctrl+N for next window, Ctrl+P for previous window
        # ASCII 14 is Ctrl+N, ASCII 16 is Ctrl+P
        elif key_code == 14:  # CTRL+N
            self.switch_active_context("next")
        elif key_code == 16:  # CTRL+P
            self.switch_active_context("prev")
        elif key_code == 9:
            self.do_tab_complete()
        elif key_code >= 0:
            try:
                if key_code <= 255:
                    self.input_buffer += chr(key_code)
            except (ValueError, Exception):
                pass
        self.ui_needs_update.set()

    def do_tab_complete(self):
        if not self.input_buffer:
            return
        parts = self.input_buffer.split(" ")
        to_complete = parts[-1]
        prefix_str = " ".join(parts[:-1]) + (" " if len(parts) > 1 else "")
        if not to_complete:
            return
        candidates = []
        if len(parts) == 1 and self.input_buffer.startswith("/"):
            commands = [
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
                "/s",
                "/disconnect",
                "/clear",
            ]
            candidates = [
                cmd for cmd in commands if cmd.lower().startswith(to_complete.lower())
            ]
        else:
            # Tab completion for nicks should use users from the active_context_name
            active_users = []
            if (
                self.active_context_name in self.contexts
                and self.contexts[self.active_context_name]["type"] == "channel"
            ):
                active_users = list(self.contexts[self.active_context_name]["users"])

            unique_nicks = list(active_users)  # Make a mutable copy
            if (
                self.nick and self.nick not in unique_nicks
            ):  # Add self if not already in list (e.g. for PMs or if WHO hasn't populated yet)
                unique_nicks.append(self.nick)
            candidates = [
                nick
                for nick in unique_nicks
                if nick.lower().startswith(to_complete.lower())
            ]
        if len(candidates) == 1:
            self.input_buffer = prefix_str + candidates[0] + " "
        elif len(candidates) > 1:
            sorted_candidates = sorted(list(set(c.lower() for c in candidates)))
            if not sorted_candidates:
                return
            common_prefix_lower = sorted_candidates[0]
            for cand_lower in sorted_candidates[1:]:
                while not cand_lower.startswith(common_prefix_lower):
                    common_prefix_lower = common_prefix_lower[:-1]
                    if not common_prefix_lower:
                        break
                if not common_prefix_lower:
                    break
            original_cased_common_prefix = ""
            if common_prefix_lower:
                for original_cand in candidates:
                    if original_cand.lower().startswith(common_prefix_lower):
                        original_cased_common_prefix = original_cand[
                            : len(common_prefix_lower)
                        ]
                        break
            if original_cased_common_prefix and len(original_cased_common_prefix) > len(
                to_complete
            ):
                self.input_buffer = prefix_str + original_cased_common_prefix
            else:
                self.add_message(
                    f"Options: {' '.join(sorted(list(set(candidates))))}",
                    self.ui.colors["system"],
                    False,
                    context_name=self.active_context_name,  # Tab completion options go to active context
                )

    def switch_active_context(self, direction: str):
        if not self.contexts:
            return

        context_names = list(self.contexts.keys())
        try:
            current_idx = context_names.index(self.active_context_name)
        except ValueError:
            current_idx = 0  # Default to first if active not found (should not happen)

        if direction == "next":
            new_idx = (current_idx + 1) % len(context_names)
        elif direction == "prev":
            new_idx = (current_idx - 1 + len(context_names)) % len(context_names)
        else:  # Specific context name
            if direction in context_names:
                new_idx = context_names.index(direction)
            else:  # Try to find partial match or number
                try:
                    num_idx = int(direction) - 1  # 1-based index for user
                    if 0 <= num_idx < len(context_names):
                        new_idx = num_idx
                    else:
                        self.add_message(
                            f"Invalid window number: {direction}",
                            self.ui.colors["error"],
                            context_name=self.active_context_name,
                        )
                        return
                except ValueError:
                    # Partial name matching
                    found_ctx = [
                        name
                        for name in context_names
                        if direction.lower() in name.lower()
                    ]
                    if len(found_ctx) == 1:
                        new_idx = context_names.index(found_ctx[0])
                    elif len(found_ctx) > 1:
                        self.add_message(
                            f"Ambiguous window name '{direction}'. Matches: {', '.join(found_ctx)}",
                            self.ui.colors["error"],
                            context_name=self.active_context_name,
                        )
                        return
                    else:
                        self.add_message(
                            f"Window '{direction}' not found.",
                            self.ui.colors["error"],
                            context_name=self.active_context_name,
                        )
                        return

        new_active_context_name = context_names[new_idx]

        # Save scroll position of old context (optional, can be complex)
        # self.contexts[self.active_context_name]["last_read_line_count"] = self.ui.current_line_in_history

        self.active_context_name = new_active_context_name

        # Reset/Load scroll position for new context
        self.ui.current_line_in_history = 0  # Reset to bottom for new active window
        # self.ui.current_line_in_history = self.contexts[self.active_context_name].get("last_read_line_count", 0)

        if self.active_context_name in self.contexts:  # Should always be true
            self.contexts[self.active_context_name]["unread_count"] = 0
        logger.debug(f"Switched active context to: {self.active_context_name}")
        self.ui_needs_update.set()

    def process_user_command(self, line):
        if not line:
            return
        if line.startswith("/"):
            parts = line.split(" ", 1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            logger.info(f"Processing command: {command} with args: '{args}'")
            if command in ["/quit", "/q"]:
                self.should_quit = True
                quit_message = args if args else "Client quitting"
                self.network.send_raw(f"QUIT :{quit_message}")
                logger.info(f"QUIT command sent with message: {quit_message}")
                self.add_message(
                    "Quitting...", self.ui.colors["system"], context_name="Status"
                )
            elif command in ["/join", "/j"]:
                if args:
                    new_channel_target = args.split(" ")[0]
                    if not new_channel_target.startswith("#"):
                        new_channel_target = "#" + new_channel_target

                    # Part current active channel if it's different and a channel type
                    if (
                        self.active_context_name.startswith("#")
                        and self.active_context_name.lower()
                        != new_channel_target.lower()
                    ):
                        if (
                            self.active_context_name in self.contexts
                            and self.contexts[self.active_context_name]["type"]
                            == "channel"
                        ):
                            self.network.send_raw(
                                f"PART {self.active_context_name} :Changing channels"
                            )

                    if self._create_context(new_channel_target, context_type="channel"):
                        logger.debug(
                            f"Ensured context for {new_channel_target} exists before sending JOIN."
                        )
                    self.network.send_raw(f"JOIN {new_channel_target}")
                    # Active context will be set by server response (JOIN message)
                    self.add_message(
                        f"Attempting to join {new_channel_target}...",
                        self.ui.colors["system"],
                        context_name=new_channel_target,  # Or "Status"? For now, new channel.
                    )
                else:
                    logger.warning("JOIN command issued with no arguments.")
                    self.add_message(
                        "Usage: /join #channel",
                        self.ui.colors["error"],
                        context_name=self.active_context_name,
                    )
            elif command in ["/part", "/p"]:
                target_part_channel = self.active_context_name
                part_args = args.split(" ", 1)
                if part_args[0].startswith("#"):  # Allow specifying channel to part
                    target_part_channel = part_args[0]
                    args = part_args[1] if len(part_args) > 1 else ""

                if (
                    target_part_channel in self.contexts
                    and self.contexts[target_part_channel]["type"] == "channel"
                ):
                    self.network.send_raw(
                        f"PART {target_part_channel} :{args if args else 'Leaving'}"
                    )
                    # Active context will be changed by server response (PART message)
                    # Or we can proactively change it here to "Status" if parting active
                else:
                    self.add_message(
                        f"You are not in channel '{target_part_channel}' or it's not a channel context.",
                        self.ui.colors["error"],
                        context_name=self.active_context_name,
                    )
            elif command in ["/nick", "/n"]:
                if args:
                    self.network.send_raw(f"NICK {args.split(' ')[0]}")
                else:
                    self.add_message(
                        "Usage: /nick <new_nickname>", self.ui.colors["error"]
                    )
            elif command in ["/msg", "/query", "/m"]:
                msg_parts = args.split(" ", 1)
                if len(msg_parts) == 2:
                    target_nick, message = msg_parts
                    self.network.send_raw(f"PRIVMSG {target_nick} :{message}")
                    query_context_name = f"Query:{target_nick}"
                    if self._create_context(query_context_name, context_type="query"):
                        logger.debug(f"Ensured query context for {target_nick} exists.")
                    self.add_message(
                        f"[To {target_nick}] {message}",
                        self.ui.colors["my_message"],
                        context_name=query_context_name,
                    )
                    self.active_context_name = (
                        query_context_name  # Switch to query context
                    )
                    logger.info(f"Switched to query context: {query_context_name}")
                else:
                    logger.warning("MSG/QUERY command with insufficient arguments.")
                    self.add_message(
                        "Usage: /msg <nickname> <message>",
                        self.ui.colors["error"],
                        context_name=self.active_context_name,
                    )
            elif command == "/me":
                if (
                    args
                    and self.active_context_name in self.contexts
                    and self.contexts[self.active_context_name]["type"] == "channel"
                    and self.network.connected
                ):
                    self.network.send_raw(
                        f"PRIVMSG {self.active_context_name} :\x01ACTION {args}\x01"
                    )
                    self.add_message(
                        f"* {self.nick} {args}",
                        self.ui.colors["channel_message"],
                        context_name=self.active_context_name,
                    )
                elif not (
                    self.active_context_name in self.contexts
                    and self.contexts[self.active_context_name]["type"] == "channel"
                ):
                    self.add_message(
                        "You are not in a channel.",
                        self.ui.colors["error"],
                        context_name=self.active_context_name,
                    )
                elif not self.network.connected:
                    self.add_message(
                        "Not connected.", self.ui.colors["error"], context_name="Status"
                    )
                else:
                    self.add_message(
                        "Usage: /me <action>",
                        self.ui.colors["error"],
                        context_name=self.active_context_name,
                    )
            elif command == "/away":
                if args:
                    self.network.send_raw(f"AWAY :{args}")
                    self.add_message(
                        f"Away: {args}", self.ui.colors["system"], context_name="Status"
                    )
                else:
                    self.network.send_raw("AWAY")
                    self.add_message(
                        "No longer away.",
                        self.ui.colors["system"],
                        context_name="Status",
                    )
            elif command == "/invite":
                invite_parts = args.split(" ", 1)
                if len(invite_parts) == 2:
                    nick, chan = invite_parts
                    if not chan.startswith("#"):
                        chan = "#" + chan
                    self.network.send_raw(f"INVITE {nick} {chan}")
                    self.add_message(
                        f"Invited {nick} to {chan}.",
                        self.ui.colors["system"],
                        context_name=self.active_context_name,  # Or "Status"?
                    )
                else:
                    self.add_message(
                        "Usage: /invite <nick> <#channel>",
                        self.ui.colors["error"],
                        context_name=self.active_context_name,
                    )
            elif command in ["/whois", "/w"]:
                if args:
                    self.network.send_raw(f"WHOIS {args.split(' ')[0]}")
                else:
                    self.add_message(
                        "Usage: /whois <nick>",
                        self.ui.colors["error"],
                        context_name=self.active_context_name,
                    )
            elif command == "/topic":
                self._handle_topic_command(args)
            elif command in ["/raw", "/quote"]:
                if args:
                    self.network.send_raw(args)
                    self.add_message(
                        f"RAW: {args}", self.ui.colors["system"], context_name="Status"
                    )
                else:
                    self.add_message(
                        "Usage: /raw <command>",
                        self.ui.colors["error"],
                        context_name=self.active_context_name,
                    )
            elif command == "/clear":
                if self.active_context_name in self.contexts:
                    self.contexts[self.active_context_name]["messages"].clear()
                    self.contexts[self.active_context_name]["unread_count"] = 0
                    # self.ui.current_line_in_history needs to be reset for this context in UIManager
                    self.add_message(
                        "History cleared for current context.",
                        self.ui.colors["system"],
                        False,
                        context_name=self.active_context_name,
                    )
                else:
                    self.add_message(
                        "No active context to clear.",
                        self.ui.colors["error"],
                        context_name="Status",
                    )
            elif command in ["/connect", "/server", "/s"]:
                self._handle_connect_command(args)
            elif command == "/disconnect":
                if self.network.connected:
                    self.network.disconnect_gracefully("Client disconnect")
                    self.add_message(
                        "Disconnecting...",
                        self.ui.colors["system"],
                        context_name="Status",
                    )
                else:
                    self.add_message(
                        "Not connected.",
                        self.ui.colors["system"],
                        context_name="Status",
                    )
            elif command in ["/next", "/n", "/nextwindow"]:
                self.switch_active_context("next")
            elif command in ["/prev", "/p", "/prevwindow"]:
                self.switch_active_context("prev")
            elif command.startswith(("/win", "/w", "/window")):
                parts = line.split(" ", 1)
                if len(parts) > 1 and parts[1]:
                    self.switch_active_context(parts[1])
                else:
                    # List windows with numbers and unread counts
                    msg_lines = ["Open contexts:"]
                    for i, name in enumerate(self.contexts.keys()):
                        unread_str = ""
                        if self.contexts[name]["unread_count"] > 0:
                            unread_str = (
                                f" ({self.contexts[name]['unread_count']} unread)"
                            )
                        active_marker = "*" if name == self.active_context_name else " "
                        msg_lines.append(f" {i+1}: {active_marker}{name}{unread_str}")
                    for m_line in msg_lines:
                        self.add_message(
                            m_line,
                            self.ui.colors["system"],
                            prefix_time=False,
                            context_name=self.active_context_name,
                        )
            elif command in [
                "/close",
                "/wc",
                "/partchannel",
            ]:  # /partchannel is more explicit
                context_to_close = self.active_context_name
                args_parts = args.split(" ", 1)
                # Allow specifying context to close: /close #channel or /close Query:User
                if args and (args.startswith("#") or args.lower().startswith("query:")):
                    context_to_close = args
                    args = (
                        args_parts[1] if len(args_parts) > 1 else ""
                    )  # Reason for part

                if context_to_close == "Status":
                    self.add_message(
                        "Cannot close the Status window.",
                        self.ui.colors["error"],
                        context_name="Status",
                    )
                elif context_to_close in self.contexts:
                    ctx_type = self.contexts[context_to_close]["type"]
                    if ctx_type == "channel":
                        self.network.send_raw(
                            f"PART {context_to_close} :{args if args else 'Closed by user'}"
                        )
                        # Context will be fully removed/handled by PART server message processing
                        # Or we can proactively switch here if it was active
                        if self.active_context_name == context_to_close:
                            self.switch_active_context(
                                "Status"
                            )  # Switch to status after parting
                    elif ctx_type == "query":
                        del self.contexts[context_to_close]
                        self.add_message(
                            f"Closed query window: {context_to_close}",
                            self.ui.colors["system"],
                            context_name="Status",
                        )
                        if self.active_context_name == context_to_close:
                            self.switch_active_context("Status")
                    else:  # Generic or other types, just remove locally
                        del self.contexts[context_to_close]
                        self.add_message(
                            f"Closed window: {context_to_close}",
                            self.ui.colors["system"],
                            context_name="Status",
                        )
                        if self.active_context_name == context_to_close:
                            self.switch_active_context("Status")
                    self.ui_needs_update.set()
                else:
                    self.add_message(
                        f"Window '{context_to_close}' not found.",
                        self.ui.colors["error"],
                        context_name=self.active_context_name,
                    )

            else:
                self.add_message(
                    f"Unknown command: {command}",
                    self.ui.colors["error"],
                    context_name=self.active_context_name,
                )
        else:  # Regular message to active context
            if (
                self.active_context_name in self.contexts
                and (
                    self.contexts[self.active_context_name]["type"] == "channel"
                    or self.contexts[self.active_context_name]["type"] == "query"
                )
                and self.network.connected
            ):

                # For queries, target is different from context name
                target_for_privmsg = self.active_context_name
                if self.contexts[self.active_context_name]["type"] == "query":
                    target_for_privmsg = self.active_context_name.split(":", 1)[
                        1
                    ]  # Get nick from "Query:Nick"

                self.network.send_raw(f"PRIVMSG {target_for_privmsg} :{line}")
                self.add_message(
                    f"<{self.nick}> {line}",
                    self.ui.colors["my_message"],
                    context_name=self.active_context_name,
                )
            elif not self.network.connected:
                self.add_message(
                    "Not connected.", self.ui.colors["error"], context_name="Status"
                )
            else:
                self.add_message(
                    "Not in a channel or query. Use /join #channel or /msg <nick>.",
                    self.ui.colors["error"],
                    context_name=self.active_context_name,
                )
        self.ui_needs_update.set()

    def _handle_topic_command(self, args_str):
        topic_parts = args_str.split(" ", 1)
        target_channel_ctx_name = self.active_context_name
        new_topic = None

        if not topic_parts or not topic_parts[0]:  # /topic (current channel)
            if not (
                target_channel_ctx_name in self.contexts
                and self.contexts[target_channel_ctx_name]["type"] == "channel"
            ):
                self.add_message(
                    "Not in a channel to get/set topic.",
                    self.ui.colors["error"],
                    context_name=self.active_context_name,
                )
                return
        elif topic_parts[0].startswith("#"):  # /topic #channel [new_topic]
            target_channel_ctx_name = topic_parts[0]
            if len(topic_parts) > 1:
                new_topic = topic_parts[1]
        else:  # /topic new topic for current channel
            if not (
                target_channel_ctx_name in self.contexts
                and self.contexts[target_channel_ctx_name]["type"] == "channel"
            ):
                self.add_message(
                    "Not in a channel to set topic.",
                    self.ui.colors["error"],
                    context_name=self.active_context_name,
                )
                return
            new_topic = args_str

        self._create_context(
            target_channel_ctx_name, context_type="channel"
        )  # Ensure context exists

        if new_topic is not None:
            self.network.send_raw(f"TOPIC {target_channel_ctx_name} :{new_topic}")
            # Server will confirm with RPL_TOPIC or error, message added there.
            # self.add_message(f"Topic set for {target_channel_ctx_name}.", self.ui.colors["system"], context_name=target_channel_ctx_name)
        else:  # Requesting topic
            self.network.send_raw(f"TOPIC {target_channel_ctx_name}")
            # Server will respond with RPL_TOPIC or RPL_NOTOPIC
            # self.add_message(f"Requesting topic for {target_channel_ctx_name}.", self.ui.colors["system"], context_name=target_channel_ctx_name)

    def _handle_connect_command(self, args_str):
        from config import DEFAULT_PORT, DEFAULT_SSL_PORT

        conn_args = args_str.split()
        if not conn_args:
            self.add_message(
                "Usage: /connect <server[:port]> [ssl|nossl]", self.ui.colors["error"]
            )
            return
        new_server_host, new_port, new_ssl = conn_args[0], None, self.use_ssl
        if ":" in new_server_host:
            new_server_host, port_str = new_server_host.split(":", 1)
            try:
                new_port = int(port_str)
            except ValueError:
                self.add_message(f"Invalid port: {port_str}", self.ui.colors["error"])
                return
        if len(conn_args) > 1:
            ssl_arg = conn_args[1].lower()
            if ssl_arg == "ssl":
                new_ssl = True
            elif ssl_arg == "nossl":
                new_ssl = False
        if new_port is None:
            new_port = DEFAULT_SSL_PORT if new_ssl else DEFAULT_PORT

        # Disconnect from current server if connected.
        if self.network.connected:
            # disconnect_gracefully will send QUIT and handle socket closure.
            self.network.disconnect_gracefully("Changing servers")
            # Brief pause to allow network thread to process disconnect if it's very quick
            # time.sleep(0.1) # Optional: may not be necessary depending on thread behavior

        # Update client's own server/port/ssl attributes, NetworkHandler reads these.
        self.server = new_server_host
        self.port = new_port
        self.use_ssl = new_ssl

        self.add_message(
            f"Attempting to connect to: {self.server}:{self.port} (SSL: {self.use_ssl})",
            self.ui.colors["system"],
            context_name="Status",
        )
        logger.info(
            f"Attempting new connection to: {self.server}:{self.port} (SSL: {self.use_ssl})"
        )

        # Reset contexts for the new connection (or decide how to handle existing ones)
        # For now, let's clear contexts other than "Status" and re-init based on initial_channels_list
        # A more advanced approach might keep logs but mark channels as disconnected.
        logger.debug("Clearing existing contexts for new server connection.")
        current_status_msgs = list(self.contexts.get("Status", {}).get("messages", []))
        self.contexts.clear()
        self._create_context("Status", context_type="status")  # Re-create Status first
        logger.debug("Re-created 'Status' context.")
        for msg_tuple in current_status_msgs:  # Restore status messages
            self.contexts["Status"]["messages"].append(msg_tuple)
        logger.debug(
            f"Restored {len(current_status_msgs)} messages to 'Status' context."
        )

        for ch_name in self.initial_channels_list:
            self._create_context(ch_name, context_type="channel")
            logger.debug(f"Re-created initial channel context: {ch_name}")

        if self.initial_channels_list:
            self.active_context_name = self.initial_channels_list[0]
        else:
            self.active_context_name = "Status"
        logger.info(
            f"Set active context to '{self.active_context_name}' after server change."
        )

        # Tell NetworkHandler to use new parameters and attempt connection.
        # The NetworkHandler's _network_loop will use the updated self.client.server etc.
        self.network.update_connection_params(self.server, self.port, self.use_ssl)
        # The network.start() call within update_connection_params (if thread wasn't running)
        # or the existing running loop in NetworkHandler will handle the new connection attempt.

    def run_main_loop(self):
        logger.info("Starting main client loop.")
        self.network.start()
        while not self.should_quit:
            try:
                key_code = self.ui.get_input_char()
                if key_code != curses.ERR:
                    self.handle_input(key_code)
                if (
                    self.ui_needs_update.is_set() or key_code != curses.ERR
                ):  # Refresh on input or if flag is set
                    self.ui.refresh_all_windows()
                    if self.ui_needs_update.is_set():
                        self.ui_needs_update.clear()
                time.sleep(0.05)  # Keep UI responsive
            except curses.error as e:
                logger.error(f"Curses error in main loop: {e}", exc_info=True)
                self.add_message(
                    f"Curses error: {e}. Quitting.",
                    self.ui.colors["error"],
                    context_name="Status",
                )
                self.should_quit = True
                break
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received. Initiating quit.")
                self.add_message(
                    "Ctrl+C. Quitting...",
                    self.ui.colors["error"],
                    context_name="Status",
                )
                self.should_quit = True
                if self.network.connected:
                    self.network.send_raw("QUIT :Ctrl+C")
                    logger.debug("Sent QUIT due to Ctrl+C.")
                break
            except Exception as e:
                logger.critical(
                    f"Unhandled exception in main client loop: {e}", exc_info=True
                )
                self.add_message(
                    f"CRITICAL ERROR: {e}. Attempting to quit.",
                    self.ui.colors["error"],
                    context_name="Status",
                )
                self.should_quit = True  # Try to quit gracefully
                # self.network.send_raw("QUIT :Client Critical Error") # Optional: send a quit message
                break  # Exit loop on unhandled exception

        logger.info("Main client loop ended.")
        self.should_quit = True  # Ensure flag is set
        self.network.stop(
            send_quit=not self.network.connected  # Avoid double QUIT if already sent by /quit or Ctrl+C
        )
        if self.network.network_thread and self.network.network_thread.is_alive():
            logger.debug("Waiting for network thread to join...")
            self.network.network_thread.join(timeout=2.0)
            if self.network.network_thread.is_alive():
                logger.warning("Network thread did not join in time.")
            else:
                logger.debug("Network thread joined successfully.")
