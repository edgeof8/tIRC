import logging
from typing import TYPE_CHECKING, Optional, List

from context_manager import ChannelJoinStatus, Context

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.channel_commands_handler")

class ChannelCommandsHandler:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic

    def handle_join_command(self, args_str: str):
        """Handle the /join command"""
        parts = self.client.command_handler._ensure_args(args_str, "Usage: /join <channel>")
        if not parts:
            return
        channel_name_arg = parts[0]
        target_channel_name = channel_name_arg if channel_name_arg.startswith("#") else f"#{channel_name_arg}"

        self.client.last_join_command_target = target_channel_name

        ctx = self.client.context_manager.get_context(target_channel_name)
        if not ctx:
            self.client.context_manager.create_context(
                target_channel_name,
                context_type="channel",
                initial_join_status_for_channel=ChannelJoinStatus.JOIN_COMMAND_SENT
            )
            logger.info(f"/join: Created context for {target_channel_name} with status JOIN_COMMAND_SENT.")
        elif ctx.type == "channel":
            if hasattr(ctx, 'join_status'):
                ctx.join_status = ChannelJoinStatus.JOIN_COMMAND_SENT
            logger.info(f"/join: Updated context for {target_channel_name} to status JOIN_COMMAND_SENT.")
        else:
            self.client.add_message(
                f"Cannot join '{target_channel_name}': A non-channel window with this name already exists.",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name
            )
            return

        self.client.network.send_raw(f"JOIN {target_channel_name}")

    def handle_part_command(self, args_str: str):
        """Handle the /part command"""
        if not self.client.command_handler._ensure_args(args_str, "Usage: /part [channel] [reason]"):
            return

        parts = args_str.split(" ", 1)
        channel_to_part = parts[0]
        reason = parts[1] if len(parts) > 1 else None

        if not channel_to_part.startswith("#"):
            channel_to_part = f"#{channel_to_part}"

        part_ctx = self.client.context_manager.get_context(channel_to_part)
        if part_ctx and part_ctx.type == "channel":
            part_ctx.join_status = ChannelJoinStatus.PARTING
            logger.info(f"/part: Set context for {channel_to_part} to status PARTING.")
        else:
            logger.debug(f"/part: No local channel context for {channel_to_part} or not a channel type. Sending PART anyway.")

        if reason:
            self.client.network.send_raw(f"PART {channel_to_part} :{reason}")
        else:
            self.client.network.send_raw(f"PART {channel_to_part}")

    def handle_topic_command(self, args_str: str):
        topic_parts = args_str.split(" ", 1)
        current_active_ctx_name = self.client.context_manager.active_context_name
        target_channel_ctx_name = current_active_ctx_name
        new_topic = None

        if not target_channel_ctx_name:
            self.client.add_message(
                "No active window to get/set topic from.",
                self.client.ui.colors["error"],
                context_name="Status",
            )
            return

        current_context = self.client.context_manager.get_context(target_channel_ctx_name)

        if not topic_parts or not topic_parts[0]:
            if not (current_context and current_context.type == "channel"):
                self.client.add_message(
                    "Not in a channel to get/set topic. Current window is not a channel.",
                    self.client.ui.colors["error"],
                    context_name=target_channel_ctx_name,
                )
                return
        elif topic_parts[0].startswith("#"):
            target_channel_ctx_name = topic_parts[0]
            if len(topic_parts) > 1:
                new_topic = topic_parts[1]
        else:
            if not (current_context and current_context.type == "channel"):
                self.client.add_message(
                    "Not in a channel to set topic. Current window is not a channel.",
                    self.client.ui.colors["error"],
                    context_name=target_channel_ctx_name,
                )
                return
            new_topic = args_str

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

    def handle_invite_command(self, args_str: str):
        """Handle the /invite command"""
        parts = self.client.command_handler._ensure_args(args_str, "Usage: /invite <nick> [channel]", num_expected_parts=1)
        if not parts:
            return

        invite_args = args_str.split(" ", 1)
        nick = invite_args[0]
        channel_arg = invite_args[1] if len(invite_args) > 1 else None

        channel_to_invite_to = channel_arg or (self.client.context_manager.active_context_name or "Status")

        if channel_to_invite_to and not channel_to_invite_to.startswith("#"):
            active_ctx = self.client.context_manager.get_context(self.client.context_manager.active_context_name or "")
            if not channel_arg and active_ctx and active_ctx.type == "channel":
                 channel_to_invite_to = f"#{channel_to_invite_to}"
            elif channel_arg :
                 channel_to_invite_to = f"#{channel_to_invite_to}"

        if not channel_to_invite_to.startswith("#"):
             self.client.add_message(f"Cannot invite to '{channel_to_invite_to}'. Not a valid channel.", self.client.ui.colors["error"], context_name="Status")
             return

        self.client.network.send_raw(f"INVITE {nick} {channel_to_invite_to}")

    def handle_kick_command(self, args_str: str):
        """Handle the /kick command"""
        parts = self.client.command_handler._ensure_args(args_str, "Usage: /kick <nick> [reason]", num_expected_parts=1)
        if not parts:
            return

        kick_args = args_str.split(" ", 1)
        target = kick_args[0]
        reason = kick_args[1] if len(kick_args) > 1 else None

        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if not current_context or current_context.type != "channel":
            self.client.add_message(
                "Not in a channel to kick from",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return
        if reason:
            self.client.network.send_raw(
                f"KICK {current_context.name} {target} :{reason}"
            )
        else:
            self.client.network.send_raw(f"KICK {current_context.name} {target}")

    def handle_cycle_channel_command(self, args_str: str):
        """Handle the /cycle command"""
        current_context = self.client.context_manager.get_context(
            self.client.context_manager.active_context_name or "Status"
        )
        if not current_context or current_context.type != "channel":
            self.client.add_message(
                "Not in a channel to cycle",
                self.client.ui.colors["error"],
                context_name=self.client.context_manager.active_context_name or "Status",
            )
            return
        channel = current_context.name
        self.client.network.send_raw(f"PART {channel}")
        self.client.network.send_raw(f"JOIN {channel}")

    def handle_ban_command(self, args_str: str):
        """Handle the /ban command"""
        active_ctx = self.client.context_manager.get_active_context()
        if not active_ctx or active_ctx.type != "channel":
            self.client.add_message("This command can only be used in a channel.", self.client.ui.colors["error"], context_name="Status")
            return
        channel_name = active_ctx.name

        parts = self.client.command_handler._ensure_args(args_str, self.client.command_handler.COMMAND_USAGE_STRINGS["ban"])
        if not parts:
            return
        target_spec = parts[0]

        self.client.network.send_raw(f"MODE {channel_name} +b {target_spec}")
        self.client.add_message(f"Banning {target_spec} from {channel_name}...", self.client.ui.colors["system"], context_name=channel_name)

    def handle_unban_command(self, args_str: str):
        """Handle the /unban command"""
        active_ctx = self.client.context_manager.get_active_context()
        if not active_ctx or active_ctx.type != "channel":
            self.client.add_message("This command can only be used in a channel.", self.client.ui.colors["error"], context_name="Status")
            return
        channel_name = active_ctx.name

        parts = self.client.command_handler._ensure_args(args_str, self.client.command_handler.COMMAND_USAGE_STRINGS["unban"])
        if not parts:
            return
        target_spec = parts[0]

        self.client.network.send_raw(f"MODE {channel_name} -b {target_spec}")
        self.client.add_message(f"Unbanning {target_spec} from {channel_name}...", self.client.ui.colors["system"], context_name=channel_name)

    def handle_mode_command(self, args_str: str):
        """Handle the /mode command"""
        # Usage: /mode [<target>] <modes_and_params>
        parts = args_str.split(" ", 1)
        target = ""
        modes_and_params = ""
        target_context_for_feedback = "Status" # Default feedback to status window

        active_ctx = self.client.context_manager.get_active_context()

        if not parts or not parts[0]:
            self.client.add_message(self.client.command_handler.COMMAND_USAGE_STRINGS["mode"], self.client.ui.colors["error"], context_name="Status")
            return

        # Try to determine if the first part is a target or modes
        first_part = parts[0]
        if first_part.startswith(("#", "&", "!", "+")) or (not first_part.startswith(("+", "-")) and len(parts) > 1):
            # Assume first_part is a target (channel or nick)
            target = first_part
            if len(parts) > 1:
                modes_and_params = parts[1]
            else: # /mode #channel (to view modes - server usually sends numeric for this) or /mode nick (user modes)
                 modes_and_params = "" # Let server handle if it's a request for current modes
        else:
            # First part is likely modes, target is current channel if applicable
            if active_ctx and active_ctx.type == "channel":
                target = active_ctx.name
                modes_and_params = args_str
            else:
                self.client.add_message("Cannot set mode: No active channel context and target not specified.", self.client.ui.colors["error"], context_name="Status")
                self.client.add_message(self.client.command_handler.COMMAND_USAGE_STRINGS["mode"], self.client.ui.colors["error"], context_name="Status")
                return

        if not modes_and_params and not target.startswith("#"): # /mode nick (without modes) is usually not a thing client sends
            if not target: # /mode (with no args and no active channel)
                self.client.add_message(self.client.command_handler.COMMAND_USAGE_STRINGS["mode"], self.client.ui.colors["error"], context_name="Status")
                return


        if target.startswith(("#", "&", "!", "+")):
            target_context_for_feedback = target
        elif active_ctx: # if target is a nick, feedback might go to active window or status
            target_context_for_feedback = active_ctx.name


        self.client.network.send_raw(f"MODE {target} {modes_and_params}".strip())
        self.client.add_message(f"Setting mode '{modes_and_params}' on {target}...", self.client.ui.colors["system"], context_name=target_context_for_feedback)

    def _handle_simple_mode_change_command(self, args_str: str, mode_char: str, action: str, usage_key: str, feedback_verb: str):
        """Helper for /op, /deop, /voice, /devoice"""
        active_ctx = self.client.context_manager.get_active_context()
        if not active_ctx or active_ctx.type != "channel":
            self.client.add_message("This command can only be used in a channel.", self.client.ui.colors["error"], context_name="Status")
            return
        channel_name = active_ctx.name

        parts = self.client.command_handler._ensure_args(args_str, self.client.command_handler.COMMAND_USAGE_STRINGS[usage_key])
        if not parts:
            return
        nick = parts[0]

        self.client.network.send_raw(f"MODE {channel_name} {action}{mode_char} {nick}")
        self.client.add_message(f"{feedback_verb} {nick} in {channel_name}...", self.client.ui.colors["system"], context_name=channel_name)

    def handle_op_command(self, args_str: str):
        """Handle the /op command"""
        self._handle_simple_mode_change_command(args_str, "o", "+", "op", "Opping")

    def handle_deop_command(self, args_str: str):
        """Handle the /deop command"""
        self._handle_simple_mode_change_command(args_str, "o", "-", "deop", "De-opping")

    def handle_voice_command(self, args_str: str):
        """Handle the /voice command"""
        self._handle_simple_mode_change_command(args_str, "v", "+", "voice", "Voicing")

    def handle_devoice_command(self, args_str: str):
        """Handle the /devoice command"""
        self._handle_simple_mode_change_command(args_str, "v", "-", "devoice", "De-voicing")
