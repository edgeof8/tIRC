# commands/dcc/dcc_get_command.py
import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.dcc.get")

COMMAND_DEFINITIONS = [
    {
        "name": "dcc_get",
        "handler": "handle_dcc_get_command",
        "help": {
            "usage": "/dcc_get <nick> \"<filename>\" --token <token>",
            "description": "Accepts a passive (reverse) DCC SEND offer using a token provided by the sender. Use quotes for filenames with spaces.",
            "aliases": ["dccget"]
        }
    }
]

async def handle_dcc_get_command(client: "IRCClient_Logic", args_str: str):
    """
    Handles the /dcc_get <nick> "<filename>" --token <token> command.
    This is for PASSIVE (reverse) DCC offers where the sender has provided a token.
    """
    parts: List[str] = []
    temp_args_str = args_str
    status_context_for_early_errors = "Status"

    token_value: Optional[str] = None
    token_keyword = "--token"
    if token_keyword in temp_args_str:
        token_parts = temp_args_str.split(token_keyword, 1)
        temp_args_str = token_parts[0].strip()
        if len(token_parts) > 1 and token_parts[1].strip():
            token_value = token_parts[1].strip().split(" ", 1)[0]
        else:
            await client.add_message("Usage: /dcc_get <nick> \"<filename>\" --token <token_value>", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
            return

    if not token_value:
        await client.add_message("Missing --token <token_value> for /dcc_get.", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
        return

    # Parse the remaining part: <nick> "<filename>"
    # Find nick first
    temp_args_str = temp_args_str.strip() # Ensure leading/trailing spaces removed
    if not temp_args_str:
        await client.add_message("Usage: /dcc_get <nick> \"<filename>\" --token <token>", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
        return

    first_space_idx = temp_args_str.find(" ")
    if first_space_idx == -1: # Only nick provided before filename part
        await client.add_message("Usage: /dcc_get <nick> \"<filename>\" --token <token>", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
        return

    parts.append(temp_args_str[:first_space_idx]) # Nick
    remaining_after_nick = temp_args_str[first_space_idx:].strip()

    # Find quoted filename
    if not remaining_after_nick.startswith('"'):
        await client.add_message("Filename must be enclosed in quotes for /dcc_get.", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
        return

    end_quote_idx = -1
    try:
        end_quote_idx = remaining_after_nick.index('"', 1)
    except ValueError:
        await client.add_message("Malformed filename in quotes for /dcc_get.", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
        return

    parts.append(remaining_after_nick[1:end_quote_idx]) # Filename without quotes

    # There should be no further arguments after filename for /dcc_get before --token
    remaining_after_filename = remaining_after_nick[end_quote_idx+1:].strip()
    if remaining_after_filename:
        await client.add_message("Too many arguments before --token for /dcc_get.", client.ui.colors.get("error", 0), context_name=status_context_for_early_errors)
        return


    active_context_name = client.context_manager.active_context_name or "Status"
    dcc_ui_context = client.dcc_manager.dcc_ui_context_name if client.dcc_manager else "Status"

    if len(parts) != 2: # Should be nick and filename
        await client.add_message("Usage: /dcc_get <nick> \"<filename>\" --token <token>", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    peer_nick, filename = parts[0], parts[1]

    if not client.dcc_manager or not client.config.dcc.enabled:
        await client.add_message("DCC system is not enabled.", client.ui.colors.get("error", 0), context_name=active_context_name)
        return

    transfer = await client.dcc_manager.accept_passive_offer_by_token(peer_nick, filename, token_value)

    if transfer:
        await client.add_message(
            f"Attempting to accept passive DCC SEND for '{filename}' from {peer_nick} (token: {token_value}). Transfer ID: {transfer.id}",
            client.ui.colors.get("success", 0),
            context_name=dcc_ui_context
        )
        if client.context_manager.active_context_name != dcc_ui_context:
            await client.view_manager.switch_active_context(dcc_ui_context) # Corrected call
    else:
        # Error message already sent by accept_passive_offer_by_token if offer not found
        # Or, if it returns None for other reasons, provide a generic failure.
        # Check if a specific error was already displayed by looking for the transfer by token (it would have been removed if processed)
        if not client.dcc_manager.passive_offer_manager or not client.dcc_manager.passive_offer_manager.get_offer_by_token(token_value):
             # If offer is gone, assume it was processed or an error was given.
             # If it's still there, then accept_passive_offer_by_token might have failed silently.
             pass # Avoid double error messages if accept_passive_offer_by_token already sent one.
        # else: # This case might be redundant if accept_passive_offer_by_token is robust in its error messaging
        #      await client.add_message(
        #         f"Failed to process /dcc_get for '{filename}' from {peer_nick} with token {token_value}. Offer might be invalid or expired.",
        #         client.ui.colors.get("error", 0),
        #         context_name=active_context_name
        #     )
