import logging
import os
import argparse # For more robust argument parsing
from typing import TYPE_CHECKING, Dict, Any

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.commands.dcc")

def dcc_command_handler(client_logic: 'IRCClient_Logic', args_str: str):
    """Handles the main /dcc command and its subcommands."""

    # Use a simple list of args for now, consider argparse for more complex needs later
    args = args_str.split()

    if not hasattr(client_logic, 'dcc_manager') or not client_logic.dcc_manager:
        client_logic.add_message("DCC system is not initialized or available.", "error", context_name="Status")
        return

    dcc_m = client_logic.dcc_manager
    active_context_name = client_logic.context_manager.active_context_name or "Status"
    dcc_context_name = "DCC"

    if not dcc_m.dcc_config.get("enabled"):
        client_logic.add_message("DCC is currently disabled in the configuration.", "error", context_name=active_context_name)
        return

    if not args:
        client_logic.add_message(
            "Usage: /dcc <send|get|accept|list|close|browse|cancel> [options...]. Try /help dcc for more.",
            "error",
            context_name=active_context_name
        )
        return

    subcommand = args[0].lower()
    cmd_args = args[1:]

    if subcommand == "send":
        parser = argparse.ArgumentParser(prog="/dcc send", add_help=False) # Disable default help
        parser.add_argument("-p", "--passive", action="store_true", help="Initiate a passive (reverse) DCC send.")
        parser.add_argument("nick", help="The recipient's nickname.")
        parser.add_argument("filepath", nargs='+', help="The path to the file to send.") # Use nargs='+' to capture spaces

        try:
            # Filter out only known args for this subcommand before parsing
            # This is a bit manual; a more complex dispatcher could handle this better
            parsed_known_args, remaining_args = parser.parse_known_args(cmd_args)
            if remaining_args: # Should not happen if prog is set and usage is correct
                 client_logic.add_message(f"Error: Unexpected arguments for send: {remaining_args}", "error", context_name=active_context_name)
                 client_logic.add_message("Usage: /dcc send [-p] <nick> <filepath>", "error", context_name=active_context_name)
                 return

            nick = parsed_known_args.nick
            filepath = " ".join(parsed_known_args.filepath) # Join back if filepath had spaces
            passive_mode = parsed_known_args.passive

            result = dcc_m.initiate_send(nick, filepath, passive=passive_mode)

            msg = f"DCC SEND to {nick} for '{os.path.basename(filepath)}'"
            if passive_mode:
                msg += " (passive offer)"
                token = result.get('token')
                if token:
                    msg += f" with token {token[:8]}"
            msg += f" (ID: {result.get('transfer_id', 'N/A')[:8]}) initiated."

            if result.get("success"):
                client_logic.add_message(msg, "system", context_name=dcc_context_name)
            else:
                client_logic.add_message(f"DCC SEND failed: {result.get('error', 'Unknown error')}", "error", context_name=dcc_context_name)

            if client_logic.context_manager.active_context_name != dcc_context_name:
                client_logic.switch_active_context(dcc_context_name)

        except SystemExit: # Argparse calls sys.exit() on error by default
            client_logic.add_message("Usage: /dcc send [-p] <nick> <filepath>", "error", context_name=active_context_name)
            return
        except Exception as e: # Catch other parsing errors, though argparse should handle most
            logger.error(f"Error parsing /dcc send arguments: {e}", exc_info=True)
            client_logic.add_message(f"Error in /dcc send: {e}. Usage: /dcc send [-p] <nick> <filepath>", "error", context_name=active_context_name)
            return


    elif subcommand == "get": # New subcommand for accepting passive offers
        # Usage: /dcc get <nick> "<filename>" --token <token_value>
        parser_get = argparse.ArgumentParser(prog="/dcc get", add_help=False)
        parser_get.add_argument("nick", help="Sender's nickname.")
        parser_get.add_argument("filename", help="Filename offered (can be quoted).")
        parser_get.add_argument("--token", required=True, help="The token provided with the passive offer.")

        try:
            parsed_get_args = parser_get.parse_args(cmd_args)
            nick = parsed_get_args.nick
            filename = parsed_get_args.filename.strip('"') # Basic unquoting
            token = parsed_get_args.token

            # We need filesize. DCCManager should store pending passive offers.
            # Let's assume DCCManager has a method like `initiate_accept_passive_offer`
            # that looks up the offer by nick, filename, token to get filesize.
            if hasattr(dcc_m, "accept_passive_offer_by_token"): # Check if manager method exists
                result = dcc_m.accept_passive_offer_by_token(nick, filename, token)
                if result.get("success"):
                    client_logic.add_message(f"Attempting to GET '{filename}' from {nick} via passive DCC (ID: {result.get('transfer_id', 'N/A')[:8]}).", "system", context_name=dcc_context_name)
                else:
                    client_logic.add_message(f"DCC GET for '{filename}' from {nick} failed: {result.get('error', 'Unknown error')}", "error", context_name=dcc_context_name)
            else:
                client_logic.add_message(f"DCC GET command logic not fully implemented in DCCManager yet.", "error", context_name=dcc_context_name)

            if client_logic.context_manager.active_context_name != dcc_context_name:
                client_logic.switch_active_context(dcc_context_name)

        except SystemExit: # Argparse calls sys.exit()
            client_logic.add_message("Usage: /dcc get <nick> \"<filename>\" --token <token>", "error", context_name=active_context_name)
            return
        except Exception as e:
            logger.error(f"Error parsing /dcc get arguments: {e}", exc_info=True)
            client_logic.add_message(f"Error in /dcc get: {e}. Usage: /dcc get <nick> \"<filename>\" --token <token>", "error", context_name=active_context_name)
            return

    elif subcommand == "accept": # This is for ACTIVE offers received by user
        # /dcc accept <nick> "<filename>" <ip> <port> <size>
        # User provides these details after seeing the offer.
        if len(cmd_args) < 5: # nick, filename, ip, port, size
            client_logic.add_message("Usage: /dcc accept <nick> \"<filename>\" <ip> <port> <size>", "error", context_name=active_context_name)
            return
        try:
            nick = cmd_args[0]
            filename = cmd_args[1].strip('"') # Basic unquoting
            ip_str = cmd_args[2]
            port = int(cmd_args[3])
            filesize = int(cmd_args[4])

            result = dcc_m.accept_incoming_send_offer(nick, filename, ip_str, port, filesize)
            if result.get("success"):
                client_logic.add_message(f"Accepted DCC SEND from {nick} for '{filename}' (ID: {result.get('transfer_id', 'N/A')[:8]}). Receiving...", "system", context_name=dcc_context_name)
            else:
                err_msg = result.get('error', 'Unknown error')
                fn_for_err = result.get('sanitized_filename', filename)
                client_logic.add_message(f"DCC ACCEPT for '{fn_for_err}' from {nick} failed: {err_msg}", "error", context_name=dcc_context_name)
            if client_logic.context_manager.active_context_name != dcc_context_name:
                client_logic.switch_active_context(dcc_context_name)
        except (ValueError, IndexError) as e:
            client_logic.add_message(f"Invalid arguments for /dcc accept. Error: {e}. Please check format.", "error", context_name=active_context_name)

    elif subcommand == "list":
        statuses = dcc_m.get_transfer_statuses()
        client_logic.add_message("--- DCC Transfers ---", "system", context_name=dcc_context_name)
        for status_line in statuses:
            client_logic.add_message(status_line, "system", context_name=dcc_context_name)
        client_logic.add_message("---------------------", "system", context_name=dcc_context_name)
        if client_logic.context_manager.active_context_name != dcc_context_name:
            client_logic.switch_active_context(dcc_context_name)

    elif subcommand == "browse":
        target_dir = " ".join(cmd_args) if cmd_args else "."
        try:
            abs_target_dir = os.path.abspath(target_dir)
            if not os.path.isdir(abs_target_dir):
                client_logic.add_message(f"Error: '{target_dir}' (abs: {abs_target_dir}) is not a valid directory.", "error", context_name=dcc_context_name)
                return
            client_logic.add_message(f"Contents of '{abs_target_dir}':", "system", context_name=dcc_context_name)
            items = []
            for item_name in sorted(os.listdir(abs_target_dir)):
                item_path = os.path.join(abs_target_dir, item_name)
                is_dir_marker = "[D] " if os.path.isdir(item_path) else "[F] "
                items.append(f"  {is_dir_marker}{item_name}")
            if not items: client_logic.add_message("  (Directory is empty)", "system", context_name=dcc_context_name)
            else:
                for item_line in items: client_logic.add_message(item_line, "system", context_name=dcc_context_name)
        except Exception as e:
            client_logic.add_message(f"Error browsing '{target_dir}': {e}", "error", context_name=dcc_context_name)
        if client_logic.context_manager.active_context_name != dcc_context_name:
            client_logic.switch_active_context(dcc_context_name)

    elif subcommand == "close" or subcommand == "cancel":
        if not cmd_args:
            client_logic.add_message("Usage: /dcc close <transfer_id_prefix>", "error", context_name=active_context_name)
            return
        transfer_id_prefix = cmd_args[0]

        transfer_to_cancel = None
        # This lock usage assumes DCCManager's transfers dict might be modified by other threads.
        # If DCCManager provides a thread-safe method to find/cancel, that's preferred.
        with dcc_m._lock:
            for tid, transfer_obj in dcc_m.transfers.items():
                if tid.startswith(transfer_id_prefix):
                    if transfer_to_cancel is not None: # Ambiguous
                         client_logic.add_message(f"Ambiguous transfer ID prefix '{transfer_id_prefix}'. Multiple matches.", "error", context_name=dcc_context_name)
                         return
                    transfer_to_cancel = tid

        if transfer_to_cancel:
            if dcc_m.cancel_transfer(transfer_to_cancel):
                client_logic.add_message(f"DCC transfer {transfer_to_cancel[:8]} cancellation requested.", "system", context_name=dcc_context_name)
            else:
                client_logic.add_message(f"Failed to cancel DCC transfer {transfer_to_cancel[:8]}.", "error", context_name=dcc_context_name)
        else:
            client_logic.add_message(f"Transfer ID starting with '{transfer_id_prefix}' not found.", "error", context_name=dcc_context_name)

        if client_logic.context_manager.active_context_name != dcc_context_name:
            client_logic.switch_active_context(dcc_context_name)
    else:
        client_logic.add_message(f"Unknown DCC subcommand: {subcommand}. Try /help dcc.", "error", context_name=active_context_name)

COMMAND_DEFINITIONS = [
    {
        "name": "dcc",
        "handler": "dcc_command_handler", # Name of the function in this module
        "help": {
            "usage": "/dcc <subcommand> [args]",
            "description": "Manages DCC file transfers. Subcommands: send, get, accept, list, close, browse, cancel.",
            "aliases": []
        }
    },
    # Help for subcommands can be implicitly handled by the main /dcc help string
    # or CommandHandler could be extended for sub-command help topics.
]
