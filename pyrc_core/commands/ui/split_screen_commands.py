# commands/ui/split_screen_commands.py
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.ui.split_screen")
COMMAND_DEFINITIONS = [
    {
        "name": "split",
        "handler": "handle_split_command",
        "help": {
            "usage": "/split",
            "description": "Toggle split-screen mode on/off. When enabled, the message window is split into two panes. Use /focus to switch panes and /setpane to assign contexts.",
            "aliases": []
        }
    },
    {
        "name": "focus",
        "handler": "handle_focus_command",
        "help": {
            "usage": "/focus <top|bottom>",
            "description": "Switch focus between split panes (top or bottom) when in split-screen mode. The focused pane receives scroll commands.",
            "aliases": []
        }
    },
    {
        "name": "setpane",
        "handler": "handle_setpane_command",
        "help": {
            "usage": "/setpane <top|bottom> <context_name>",
            "description": "Set a context in a specific pane (top or bottom) when in split-screen mode. The context must exist.",
            "aliases": []
        }
    }
]

def handle_split_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /split command to toggle split-screen mode"""
    ui = client.ui
    active_context_name_or_empty = client.context_manager.active_context_name or ""
    system_color_key = "system"

    if not ui.split_mode_active:
        ui.split_mode_active = True
        ui.active_split_pane = "top" # Default focus to top pane
        ui.top_pane_context_name = active_context_name_or_empty
        ui.bottom_pane_context_name = "Status"
        ui.setup_layout()
        client.add_message(
            "Split-screen mode enabled. Use /focus to switch between panes.",
            system_color_key,
            context_name=active_context_name_or_empty, # Use current or empty string if none
        )
    else:
        ui.split_mode_active = False
        # Determine which context was active in the focused pane before disabling
        active_pane_context_before_disable = (
            ui.top_pane_context_name
            if ui.active_split_pane == "top"
            else ui.bottom_pane_context_name
        )
        ui.active_split_pane = "top" # Reset active pane for next activation
        ui.top_pane_context_name = ""
        ui.bottom_pane_context_name = ""
        ui.setup_layout()

        # Restore the previously focused context as the main active context
        if active_pane_context_before_disable:
             client.context_manager.set_active_context(active_pane_context_before_disable)

        client.add_message(
            "Split-screen mode disabled.",
            system_color_key,
            context_name=client.context_manager.active_context_name or "Status", # Get current active after potential switch
        )
    client.ui_needs_update.set()


def handle_focus_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /focus command to switch between split panes"""
    ui = client.ui
    active_context_name = client.context_manager.active_context_name or "Status"
    error_color_key = "error"
    system_color_key = "system"

    if not ui.split_mode_active:
        client.add_message(
            "Split-screen mode is not active. Use /split to enable it.",
            error_color_key,
            context_name=active_context_name,
        )
        return

    parts = client.command_handler._ensure_args(
        args_str, "Usage: /focus <top|bottom>", num_expected_parts=1
    )
    if not parts:
        return

    pane = parts[0].lower()
    if pane not in ["top", "bottom"]:
        client.add_message(
            "Invalid pane. Use 'top' or 'bottom'.",
            error_color_key,
            context_name=active_context_name,
        )
        return

    ui.active_split_pane = pane
    # Update the main active context to reflect the newly focused pane's context
    newly_focused_context = ui.top_pane_context_name if pane == "top" else ui.bottom_pane_context_name
    if newly_focused_context : # Ensure there's a context to switch to
        client.context_manager.set_active_context(newly_focused_context)

    client.add_message(
        f"Focus set to {pane} pane ('{newly_focused_context}').", # Provide context name in feedback
        system_color_key,
        context_name=active_context_name, # Message in the *previously* active context
    )
    client.ui_needs_update.set()


def handle_setpane_command(client: "IRCClient_Logic", args_str: str):
    """Handle the /setpane command to set a context in a specific pane"""
    ui = client.ui
    active_context_name = client.context_manager.active_context_name or "Status"
    error_color_key = "error"
    system_color_key = "system"

    if not ui.split_mode_active:
        client.add_message(
            "Split-screen mode is not active. Use /split to enable it.",
            error_color_key,
            context_name=active_context_name,
        )
        return

    parts = client.command_handler._ensure_args(
        args_str,
        "Usage: /setpane <top|bottom> <context_name>",
        num_expected_parts=2,
    )
    if not parts:
        return

    pane, context_to_set_name = parts[0].lower(), parts[1]
    if pane not in ["top", "bottom"]:
        client.add_message(
            "Invalid pane. Use 'top' or 'bottom'.",
            error_color_key,
            context_name=active_context_name,
        )
        return

    if not client.context_manager.get_context(context_to_set_name):
        client.add_message(
            f"Context '{context_to_set_name}' not found.",
            error_color_key,
            context_name=active_context_name,
        )
        return

    if pane == "top":
        ui.top_pane_context_name = context_to_set_name
    else: # bottom
        ui.bottom_pane_context_name = context_to_set_name

    # If the currently focused pane is the one we just changed,
    # update the main active context to match.
    if ui.active_split_pane == pane:
        client.context_manager.set_active_context(context_to_set_name)

    client.add_message(
        f"Set {pane} pane to context '{context_to_set_name}'.",
        system_color_key,
        context_name=active_context_name, # Message in the *previously* active context
    )
    client.ui_needs_update.set()
