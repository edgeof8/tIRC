# irc_client_logic.py
import curses
import threading
import time
import socket
from collections import deque
from typing import Optional, Any, List, Set # Added Set
import logging

from config import (
    MAX_HISTORY,
)
from context_manager import ContextManager

from ui_manager import UIManager
from network_handler import NetworkHandler
import irc_protocol
from command_handler import CommandHandler
from input_handler import InputHandler

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
        self.server = server_addr # Will be set by /connect or initial args
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

        self.currently_joined_channels: Set[str] = set() # New attribute to track joined channels

        self.password = password
        self.nickserv_password = nickserv_password
        self.use_ssl = use_ssl

        self.context_manager = ContextManager(max_history_per_context=MAX_HISTORY)
        # ... (rest of __init__)
        self.context_manager.create_context("Status", context_type="status")
        self.context_manager.set_active_context("Status")

        for ch_name in self.initial_channels_list:
            self.context_manager.create_context(ch_name, context_type="channel")

        if self.initial_channels_list:
            self.context_manager.set_active_context(self.initial_channels_list[0])

        self.should_quit = False
        self.ui_needs_update = threading.Event()

        self.network = NetworkHandler(self)
        self.ui = UIManager(stdscr, self)
        self.command_handler = CommandHandler(self)
        self.input_handler = InputHandler(self)

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

    def add_message(
        self,
        text: str,
        color_attr: int,
        prefix_time: bool = True,
        context_name: Optional[str] = None,
    ):
        target_context_name = (
            context_name
            if context_name is not None
            else self.context_manager.active_context_name
        )
        if not target_context_name:
            logger.error(
                "add_message called with no target_context_name and no active context."
            )
            target_context_name = "Status"

        target_ctx_exists = self.context_manager.get_context(target_context_name)
        if not target_ctx_exists:
            context_type = "generic"
            if target_context_name.startswith("#"):
                context_type = "channel"
            elif target_context_name != "Status" and ":" in target_context_name :
                 context_type = "query"


            if self.context_manager.create_context(
                target_context_name, context_type=context_type
            ):
                logger.info(
                    f"Dynamically created context '{target_context_name}' of type '{context_type}' for message."
                )
            else:
                if not self.context_manager.get_context(target_context_name):
                    logger.error(
                        f"FATAL: Failed to ensure context '{target_context_name}' for message. Message lost: {text}"
                    )
                    # Attempt to add to status, but ensure status context itself exists
                    status_ctx_for_error = self.context_manager.get_context("Status")
                    if not status_ctx_for_error: # Highly unlikely, but guard
                        self.context_manager.create_context("Status", context_type="status")

                    self.context_manager.add_message_to_context(
                        "Status",
                        f"Error: Failed to create context '{target_context_name}' for message: {text}",
                        self.ui.colors["error"],
                    )
                    self.ui_needs_update.set()
                    return

        target_context_obj = self.context_manager.get_context(target_context_name)
        if not target_context_obj:
            logger.critical(f"Context {target_context_name} is unexpectedly None after creation/check.")
            return


        max_w = self.ui.msg_win_width - 1 if self.ui.msg_win_width > 1 else 80
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

        num_lines_added_for_this_message = len(lines)

        for line_part in lines:
            self.context_manager.add_message_to_context(
                target_context_name, line_part, color_attr, 1
            )

        if target_context_name == self.context_manager.active_context_name:
            if hasattr(target_context_obj, 'scrollback_offset') and target_context_obj.scrollback_offset > 0:
                target_context_obj.scrollback_offset += num_lines_added_for_this_message

        self.ui_needs_update.set()

    def on_server_message(self, line):
        logger.debug(f"S << {line.strip()}")
        irc_protocol.handle_server_message(self, line)

    def switch_active_context(self, direction: str):
        context_names = self.context_manager.get_all_context_names()
        if not context_names:
            return

        # Ensure "Status" is first for numeric indexing if present, then sort others
        if "Status" in context_names:
            sorted_context_names = ["Status"] + sorted([name for name in context_names if name != "Status"])
        else:
            sorted_context_names = sorted(context_names)


        current_active_name = self.context_manager.active_context_name
        if not current_active_name and sorted_context_names:
            current_active_name = sorted_context_names[0]
        elif not current_active_name:
            return

        try:
            current_idx = sorted_context_names.index(current_active_name)
        except ValueError: # Active context not in sorted list (e.g. just closed)
            current_idx = 0 # Default to first
            if not sorted_context_names: return # No contexts left
            current_active_name = sorted_context_names[0]


        new_active_context_name = None

        if direction == "next":
            new_idx = (current_idx + 1) % len(sorted_context_names)
            new_active_context_name = sorted_context_names[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + len(sorted_context_names)) % len(sorted_context_names)
            new_active_context_name = sorted_context_names[new_idx]
        else:
            if direction in sorted_context_names: # Direct name match
                new_active_context_name = direction
            else:
                try: # Attempt numeric match (1-based)
                    num_idx = int(direction) - 1
                    if 0 <= num_idx < len(sorted_context_names):
                        new_active_context_name = sorted_context_names[num_idx]
                    else:
                        self.add_message(
                            f"Invalid window number: {direction}. Max: {len(sorted_context_names)}",
                            self.ui.colors["error"],
                            context_name=current_active_name,
                        )
                        return
                except ValueError: # Attempt partial name match
                    found_ctx = [
                        name
                        for name in sorted_context_names
                        if direction.lower() in name.lower()
                    ]
                    if len(found_ctx) == 1:
                        new_active_context_name = found_ctx[0]
                    elif len(found_ctx) > 1:
                        self.add_message(
                            f"Ambiguous window name '{direction}'. Matches: {', '.join(sorted(found_ctx))}",
                            self.ui.colors["error"],
                            context_name=current_active_name,
                        )
                        return
                    else:
                        self.add_message(
                            f"Window '{direction}' not found.",
                            self.ui.colors["error"],
                            context_name=current_active_name,
                        )
                        return

        if new_active_context_name:
            if self.context_manager.set_active_context(new_active_context_name):
                logger.debug(
                    f"Switched active context to: {self.context_manager.active_context_name}"
                )
                self.ui_needs_update.set()
            else:
                logger.error(
                    f"Failed to set active context to {new_active_context_name} via ContextManager."
                )
                self.add_message(
                    f"Error switching to window '{new_active_context_name}'.",
                    self.ui.colors["error"],
                    context_name=current_active_name,
                )

    def switch_active_channel(self, direction: str):
        """Switches active context only among 'channel' type contexts."""
        all_context_names = self.context_manager.get_all_context_names()

        # Explicitly build the list of channel names
        channel_context_names_temp: List[str] = []
        for name in all_context_names:
            context_obj = self.context_manager.get_context(name)
            if context_obj and context_obj.type == "channel":
                channel_context_names_temp.append(name)
        channel_context_names: List[str] = sorted(channel_context_names_temp)


        if not channel_context_names:
            self.add_message(
                "No channels to switch to.",
                self.ui.colors["system"],
                context_name=self.context_manager.active_context_name or "Status"
            )
            return

        current_active_name_str: Optional[str] = self.context_manager.active_context_name
        current_idx = -1

        # Check if the current active context is a channel and is in our list
        if current_active_name_str: # Ensure current_active_name_str is not None
            current_active_context_obj = self.context_manager.get_context(current_active_name_str)
            if current_active_context_obj and current_active_context_obj.type == "channel":
                try:
                    # current_active_name_str is guaranteed to be a string here
                    current_idx = channel_context_names.index(current_active_name_str)
                except ValueError:
                    # This means the current active channel name (which is a channel type)
                    # is somehow not in our filtered & sorted list. Should be rare.
                    # Treat as if not in a known channel.
                    current_idx = -1
                    logger.warning(f"Active channel '{current_active_name_str}' not found in filtered channel list.")

        new_active_channel_name = None
        num_channels = len(channel_context_names)

        if current_idx == -1:
            # If not currently in a known channel, or if current_active_name was None,
            # default to the first channel in the list.
            new_active_channel_name = channel_context_names[0]
        elif direction == "next":
            new_idx = (current_idx + 1) % num_channels
            new_active_channel_name = channel_context_names[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + num_channels) % num_channels
            new_active_channel_name = channel_context_names[new_idx]

        if new_active_channel_name:
            if self.context_manager.set_active_context(new_active_channel_name):
                logger.debug(
                    f"Switched active channel to: {self.context_manager.active_context_name}"
                )
                self.ui_needs_update.set()
            else:
                logger.error(
                    f"Failed to set active channel to {new_active_channel_name}."
                )
                self.add_message(
                    f"Error switching to channel '{new_active_channel_name}'.",
                    self.ui.colors["error"],
                    context_name=current_active_name_str or "Status", # Use the string version or fallback
                )


    def run_main_loop(self):
        logger.info("Starting main client loop.")
        self.network.start()
        while not self.should_quit:
            try:
                key_code = self.ui.get_input_char()
                if key_code != curses.ERR:
                    self.input_handler.handle_key_press(key_code)

                if (
                    self.ui_needs_update.is_set() or key_code != curses.ERR
                ):
                    self.ui.refresh_all_windows()
                    if self.ui_needs_update.is_set():
                        self.ui_needs_update.clear()

                time.sleep(0.05)
            except curses.error as e:
                logger.error(f"Curses error in main loop: {e}", exc_info=True)
                try:
                    self.add_message(
                        f"Curses error: {e}. Quitting.",
                        self.ui.colors["error"],
                        context_name="Status",
                    )
                except: pass
                self.should_quit = True
                break
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received. Initiating quit.")
                self.add_message(
                    "Ctrl+C pressed. Quitting...",
                    self.ui.colors["system"],
                    context_name="Status",
                )
                self.should_quit = True
                if self.network.connected:
                    self.network.send_raw("QUIT :Ctrl+C pressed")
                break
            except Exception as e:
                logger.critical(
                    f"Unhandled exception in main client loop: {e}", exc_info=True
                )
                try:
                    self.add_message(
                        f"CRITICAL ERROR: {e}. Attempting to quit.",
                        self.ui.colors["error"],
                        context_name="Status",
                    )
                except: pass
                self.should_quit = True
                break

        logger.info("Main client loop ended.")
        self.should_quit = True
        self.network.stop(send_quit=self.network.connected)
        if self.network.network_thread and self.network.network_thread.is_alive():
            logger.debug("Waiting for network thread to join...")
            self.network.network_thread.join(timeout=2.0)
            if self.network.network_thread.is_alive():
                logger.warning("Network thread did not join in time.")
            else:
                logger.debug("Network thread joined successfully.")
