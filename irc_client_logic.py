# irc_client_logic.py
import curses
import threading
import time
import socket
from collections import deque
from typing import Optional, Any  # Added Optional, Any
import logging  # Added for logging

from config import (
    MAX_HISTORY,
)  # MAX_HISTORY might be used by ContextManager if not passed
from context_manager import ContextManager  # Import the new ContextManager

# from config import RECONNECT_INITIAL_DELAY as CFG_RECONNECT_INITIAL_DELAY # No longer used directly here
from ui_manager import UIManager
from network_handler import NetworkHandler
import irc_protocol
from command_handler import CommandHandler  # Import the new CommandHandler
from input_handler import InputHandler  # Import the new InputHandler

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

        self.context_manager = ContextManager(max_history_per_context=MAX_HISTORY)
        self.context_manager.create_context("Status", context_type="status")
        self.context_manager.set_active_context("Status")  # Set initial active context

        for ch_name in self.initial_channels_list:
            self.context_manager.create_context(ch_name, context_type="channel")

        if self.initial_channels_list:
            # Set the first channel as active if any exist, otherwise Status remains active
            self.context_manager.set_active_context(self.initial_channels_list[0])

        # self.message_history is deprecated
        # self.channel_users is deprecated
        # self.input_buffer, self.partial_input_history, self.partial_input_history_idx moved to InputHandler

        self.should_quit = False
        self.ui_needs_update = threading.Event()

        self.network = NetworkHandler(self)
        self.ui = UIManager(
            stdscr, self
        )  # UIManager might need adjustment to get input_buffer from input_handler
        self.command_handler = CommandHandler(self)  # Initialize CommandHandler
        self.input_handler = InputHandler(self)  # Initialize InputHandler

        self.add_message(  # This will now use the context_manager implicitly
            "Simple IRC Client starting...",
            self.ui.colors["system"],
            context_name="Status",
        )
        initial_channels_display = (
            ", ".join(self.initial_channels_list)
            if self.initial_channels_list
            else "None"
        )
        self.add_message(  # This will now use the context_manager implicitly
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
        if (
            not target_context_name
        ):  # Should not happen if active_context_name is always set
            logger.error(
                "add_message called with no target_context_name and no active context."
            )
            target_context_name = "Status"  # Fallback

        # Ensure context exists, create if it's a new PM or similar
        if not self.context_manager.get_context(target_context_name):
            context_type = (
                "query"
                if not target_context_name.startswith("#")
                and target_context_name != "Status"
                else "generic"  # Or "channel" if it starts with # but wasn't pre-created
            )
            if (
                target_context_name.startswith("#") and target_context_name != "Status"
            ):  # A bit more specific for channels
                context_type = "channel"

            if self.context_manager.create_context(
                target_context_name, context_type=context_type
            ):
                logger.info(
                    f"Dynamically created context '{target_context_name}' of type '{context_type}' for message."
                )
            else:
                # This case implies the context was created by another thread or already existed.
                logger.warning(
                    f"Context '{target_context_name}' either already existed or creation failed (should be handled by create_context)."
                )
                # If creation failed and context still doesn't exist, we have an issue.
                if not self.context_manager.get_context(target_context_name):
                    logger.error(
                        f"FATAL: Failed to ensure context '{target_context_name}' for message. Message lost: {text}"
                    )
                    # Fallback to Status to report error
                    self.context_manager.add_message_to_context(
                        "Status",
                        f"Error: Failed to create context '{target_context_name}' for message: {text}",
                        self.ui.colors["error"],
                    )
                    self.ui_needs_update.set()
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

        num_lines_added = len(lines)
        # The loop below correctly adds each line part to the context manager.
        # The ContextManager's add_message_to_context handles unread counts appropriately
        # by incrementing based on the num_lines_added (which is 1 per call here) if the context is not active.

        for line_part in lines:
            self.context_manager.add_message_to_context(
                target_context_name, line_part, color_attr, 1
            )  # Add 1 line at a time, context_manager handles unread count.

        if (
            self.ui.current_line_in_history > 0
            and target_context_name == self.context_manager.active_context_name
        ):
            self.ui.current_line_in_history += num_lines_added

        self.ui_needs_update.set()

    def on_server_message(self, line):
        logger.debug(f"S << {line.strip()}")
        irc_protocol.handle_server_message(self, line)

    # def handle_input(self, key_code):
    #     # This method's logic is now in InputHandler.handle_key_press
    #     pass

    # def do_tab_complete(self):
    #     # This method's logic is now in InputHandler.do_tab_complete
    #     pass

    def switch_active_context(self, direction: str):
        context_names = (
            self.context_manager.get_all_context_names()
        )  # Assuming this returns a consistent order or we sort it
        if not context_names:
            return

        # For consistent next/prev, it's better if get_all_context_names() returns a sorted list
        # or we sort it here. For now, let's assume the order from dict.keys() is stable enough for this session.
        # A more robust solution might involve an ordered list of context names in ContextManager.
        # For now, let's sort them to ensure consistent next/prev behavior.
        context_names.sort()

        current_active_name = self.context_manager.active_context_name
        if (
            not current_active_name and context_names
        ):  # If no active context, pick the first one
            current_active_name = context_names[0]
        elif not current_active_name:  # No contexts at all
            return

        try:
            current_idx = context_names.index(current_active_name)
        except ValueError:
            current_idx = 0  # Default to first if active not found

        new_active_context_name = None

        if direction == "next":
            new_idx = (current_idx + 1) % len(context_names)
            new_active_context_name = context_names[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + len(context_names)) % len(context_names)
            new_active_context_name = context_names[new_idx]
        else:  # Specific context name or number
            if direction in context_names:
                new_active_context_name = direction
            else:
                try:
                    num_idx = int(direction) - 1  # 1-based index for user
                    if 0 <= num_idx < len(context_names):
                        new_active_context_name = context_names[
                            num_idx
                        ]  # Use sorted list
                    else:
                        self.add_message(
                            f"Invalid window number: {direction}",
                            self.ui.colors["error"],
                            context_name=current_active_name,
                        )
                        return
                except ValueError:
                    # Partial name matching against the sorted list
                    found_ctx = [
                        name
                        for name in context_names
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
            # Save scroll position of old context (UI concern, might need UIManager method)
            # old_context = self.context_manager.get_active_context()
            # if old_context:
            #     old_context.last_read_line_count = self.ui.current_line_in_history

            if self.context_manager.set_active_context(new_active_context_name):
                # Reset/Load scroll position for new context (UI concern)
                self.ui.current_line_in_history = (
                    0  # Reset to bottom for new active window
                )
                # new_ctx_obj = self.context_manager.get_active_context()
                # if new_ctx_obj:
                #     self.ui.current_line_in_history = new_ctx_obj.get("last_read_line_count", 0) # If we store it in Context object

                logger.debug(
                    f"Switched active context to: {self.context_manager.active_context_name}"
                )
                self.ui_needs_update.set()
            else:
                # This should not happen if logic above is correct
                logger.error(
                    f"Failed to set active context to {new_active_context_name} via ContextManager."
                )
                self.add_message(
                    f"Error switching to window '{new_active_context_name}'.",
                    self.ui.colors["error"],
                    context_name=current_active_name,
                )

    # process_user_command, _handle_topic_command, and _handle_connect_command
    # have been moved to CommandHandler.

    def run_main_loop(self):
        logger.info("Starting main client loop.")
        self.network.start()
        while not self.should_quit:
            try:
                key_code = self.ui.get_input_char()  # Blocks until input or timeout
                if key_code != curses.ERR:  # curses.ERR means no input
                    self.input_handler.handle_key_press(key_code)  # Use InputHandler

                # Refresh UI if flag is set OR if there was any input (even non-command input)
                if (
                    self.ui_needs_update.is_set() or key_code != curses.ERR
                ):  # ui_needs_update is set by InputHandler
                    self.ui.refresh_all_windows()
                    if self.ui_needs_update.is_set():
                        self.ui_needs_update.clear()  # Clear the flag after refresh

                time.sleep(0.05)  # Small sleep to prevent busy-waiting if no input
            except curses.error as e:
                logger.error(f"Curses error in main loop: {e}", exc_info=True)
                self.add_message(
                    f"Curses error: {e}. Quitting.",
                    self.ui.colors["error"],
                    context_name="Status",
                )
                self.should_quit = True  # Signal quit
                break  # Exit loop
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received. Initiating quit.")
                self.add_message(
                    "Ctrl+C pressed. Quitting...",
                    self.ui.colors["system"],  # Using system color for this message
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
                # Try to add message to UI, might fail if curses is broken
                try:
                    self.add_message(
                        f"CRITICAL ERROR: {e}. Attempting to quit.",
                        self.ui.colors["error"],
                        context_name="Status",
                    )
                except Exception as ui_e:
                    logger.error(f"Failed to add critical error message to UI: {ui_e}")

                self.should_quit = True
                # Optionally send QUIT if network is still up
                # if self.network.connected:
                #     self.network.send_raw("QUIT :Client Critical Error")
                break

        logger.info("Main client loop ended.")
        # Ensure should_quit is True for network thread cleanup
        self.should_quit = True
        self.network.stop(send_quit=self.network.connected)
        if self.network.network_thread and self.network.network_thread.is_alive():
            logger.debug("Waiting for network thread to join...")
            self.network.network_thread.join(timeout=2.0)  # Wait up to 2 seconds
            if self.network.network_thread.is_alive():
                logger.warning("Network thread did not join in time.")
            else:
                logger.debug("Network thread joined successfully.")
