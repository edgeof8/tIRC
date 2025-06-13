# commands/ui/split_screen_commands.py
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.ui.split")

COMMAND_DEFINITIONS = [
    {
        "name": "split",
        "handler": "handle_split_command",
        "help": {
            "usage": "/split",
            "description": "Toggles split screen mode. Active context moves to top, Status or next to bottom.",
            "aliases": []
        }
    },
    {
        "name": "unsplit",
        "handler": "handle_unsplit_command",
        "help": {
            "usage": "/unsplit",
            "description": "Turns off split screen mode. Active pane's context becomes the main view.",
            "aliases": []
        }
    },
    {
        "name": "focus",
        "handler": "handle_focus_command",
        "help": {
            "usage": "/focus [top|bottom]",
            "description": "Switches focus between split panes or to a specific pane.",
            "aliases": ["f"]
        }
    },
    {
        "name": "setpane",
        "handler": "handle_setpane_command",
        "help": {
            "usage": "/setpane <top|bottom> <context_name>",
            "description": "Sets the specified context in the top or bottom pane.",
            "aliases": []
        }
    }
]

async def handle_split_command(client: "IRCClient_Logic", args_str: str):
    """Toggles split screen mode."""
    if client.is_headless or not hasattr(client, 'ui') or not hasattr(client.ui, 'split_mode_active'):
        await client.add_status_message("Split screen commands are not available in headless mode or with this UI.", "error")
        return

    client.ui.split_mode_active = not client.ui.split_mode_active

    if client.ui.split_mode_active:
        # When splitting, current active context goes to top (or focused pane if already split)
        # Bottom pane gets "Status" or next available context.
        current_active_ctx = client.context_manager.active_context_name or "Status"

        if client.ui.active_split_pane == "top":
            client.ui.top_pane_context_name = current_active_ctx
            # Find a different context for bottom pane
            all_contexts = client.context_manager.get_all_context_names()
            bottom_candidate = "Status"
            if current_active_ctx.lower() == "status" and len(all_contexts) > 1:
                bottom_candidate = next((name for name in all_contexts if name.lower() != "status"), "Status")
            elif current_active_ctx.lower() != "status" and "Status" not in all_contexts: # Create Status if missing
                client.context_manager.create_context("Status", "status")
                bottom_candidate = "Status"
            elif current_active_ctx.lower() != "status" and "Status" in all_contexts:
                bottom_candidate = "Status"

            client.ui.bottom_pane_context_name = bottom_candidate
        else: # active_split_pane is bottom
            client.ui.bottom_pane_context_name = current_active_ctx
            all_contexts = client.context_manager.get_all_context_names()
            top_candidate = "Status"
            if current_active_ctx.lower() == "status" and len(all_contexts) > 1:
                top_candidate = next((name for name in all_contexts if name.lower() != "status"), "Status")
            elif current_active_ctx.lower() != "status" and "Status" not in all_contexts:
                client.context_manager.create_context("Status", "status")
                top_candidate = "Status"
            elif current_active_ctx.lower() != "status" and "Status" in all_contexts:
                top_candidate = "Status"
            client.ui.top_pane_context_name = top_candidate

        # Ensure both panes have a valid context assigned if possible
        if not client.ui.top_pane_context_name: client.ui.top_pane_context_name = "Status"
        if not client.ui.bottom_pane_context_name: client.ui.bottom_pane_context_name = "Status"
        if not client.context_manager.get_context(client.ui.top_pane_context_name): client.context_manager.create_context(client.ui.top_pane_context_name, "status")
        if not client.context_manager.get_context(client.ui.bottom_pane_context_name): client.context_manager.create_context(client.ui.bottom_pane_context_name, "status")

        await client.add_status_message(f"Split mode ON. Top: {client.ui.top_pane_context_name}, Bottom: {client.ui.bottom_pane_context_name}. Focus: {client.ui.active_split_pane}", "system")
    else:
        # When unsplitting, the context of the previously active pane becomes the main active context
        if client.ui.active_split_pane == "top" and client.ui.top_pane_context_name:
            client.context_manager.set_active_context(client.ui.top_pane_context_name)
        elif client.ui.bottom_pane_context_name: # Default to bottom if top was not set or active_split_pane was bottom
            client.context_manager.set_active_context(client.ui.bottom_pane_context_name)
        else: # Fallback
            client.context_manager.set_active_context("Status")
        await client.add_status_message("Split mode OFF.", "system")

    client.ui.setup_layout()
    client.ui_needs_update.set()

async def handle_unsplit_command(client: "IRCClient_Logic", args_str: str):
    """Turns off split screen mode."""
    if client.is_headless or not hasattr(client, 'ui') or not hasattr(client.ui, 'split_mode_active'):
        await client.add_status_message("Split screen commands are not available.", "error")
        return

    if client.ui.split_mode_active:
        client.ui.split_mode_active = False
        # Context of the previously active pane becomes the main active context
        if client.ui.active_split_pane == "top" and client.ui.top_pane_context_name:
            client.context_manager.set_active_context(client.ui.top_pane_context_name)
        elif client.ui.bottom_pane_context_name:
            client.context_manager.set_active_context(client.ui.bottom_pane_context_name)
        else:
            client.context_manager.set_active_context("Status") # Fallback

        client.ui.setup_layout()
        client.ui_needs_update.set()
        await client.add_status_message("Split mode OFF.", "system")
    else:
        await client.add_status_message("Split mode is already OFF.", "info")

async def handle_focus_command(client: "IRCClient_Logic", args_str: str):
    """Switches focus between split panes."""
    if client.is_headless or not hasattr(client, 'ui') or not hasattr(client.ui, 'split_mode_active'):
        await client.add_status_message("Split screen commands are not available.", "error")
        return

    if not client.ui.split_mode_active:
        await client.add_status_message("Split mode is not active. Use /split to enable.", "info")
        return

    target_pane = args_str.strip().lower()
    if target_pane == "top":
        client.ui.active_split_pane = "top"
    elif target_pane == "bottom":
        client.ui.active_split_pane = "bottom"
    else: # Toggle if no specific pane or invalid arg
        client.ui.active_split_pane = "bottom" if client.ui.active_split_pane == "top" else "top"

    # Update the main active context to the context of the newly focused pane
    if client.ui.active_split_pane == "top" and client.ui.top_pane_context_name:
        client.context_manager.set_active_context(client.ui.top_pane_context_name)
    elif client.ui.active_split_pane == "bottom" and client.ui.bottom_pane_context_name:
        client.context_manager.set_active_context(client.ui.bottom_pane_context_name)

    # client.ui.setup_layout() # May not be needed if only focus changes, but status bar might update
    client.ui_needs_update.set()
    await client.add_status_message(f"Focus switched to {client.ui.active_split_pane} pane ({client.context_manager.active_context_name}).", "system")

async def handle_setpane_command(client: "IRCClient_Logic", args_str: str):
    """Sets a context in a specific pane."""
    if client.is_headless or not hasattr(client, 'ui') or not hasattr(client.ui, 'split_mode_active'):
        await client.add_status_message("Split screen commands are not available.", "error")
        return

    if not client.ui.split_mode_active:
        await client.add_status_message("Split mode is not active. Use /split to enable first.", "info")
        return

    parts = args_str.split(" ", 1)
    if len(parts) < 2:
        await client.add_status_message("Usage: /setpane <top|bottom> <context_name>", "error")
        return

    pane_target = parts[0].lower()
    context_name_to_set = parts[1].strip()
    normalized_context_name = client.context_manager._normalize_context_name(context_name_to_set)

    if not client.context_manager.get_context(normalized_context_name):
        # Optionally create if it doesn't exist, or error out
        # For now, let's assume it must exist or be "Status"
        if normalized_context_name.lower() == "status":
            client.context_manager.create_context("Status", "status") # Ensure Status exists
        else:
            # A command like /query or /join should be used to create new contexts first
            await client.add_status_message(f"Context '{context_name_to_set}' not found. Create it first (e.g. /join, /query).", "error")
            return

    if pane_target == "top":
        client.ui.top_pane_context_name = normalized_context_name
        await client.add_status_message(f"Top pane set to: {normalized_context_name}", "system")
    elif pane_target == "bottom":
        client.ui.bottom_pane_context_name = normalized_context_name
        await client.add_status_message(f"Bottom pane set to: {normalized_context_name}", "system")
    else:
        await client.add_status_message("Invalid pane target. Use 'top' or 'bottom'.", "error")
        return

    # If the currently focused pane's context was changed, update the main active context
    if client.ui.active_split_pane == "top" and pane_target == "top":
        client.context_manager.set_active_context(client.ui.top_pane_context_name)
    elif client.ui.active_split_pane == "bottom" and pane_target == "bottom":
        client.context_manager.set_active_context(client.ui.bottom_pane_context_name)

    client.ui_needs_update.set()
