# tirc_core/commands/dcc/dcc_command_base.py
import logging
from typing import TYPE_CHECKING, Optional, List, Dict, Any, Tuple # Added Tuple
import re # Ensure re is imported

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.commands.dcc.base")

class DCCCommandHelper:
    """
    Provides common helper methods for DCC command handlers.
    This class is not instantiated directly but its static methods are used.
    """

    @staticmethod
    async def ensure_dcc_context_active(client: "IRCClient_Logic", dcc_ui_context_name: str):
        """
        Ensures the DCC UI context is active if it's not already.
        """
        if client.context_manager.active_context_name != dcc_ui_context_name:
            logger.debug(f"Switching to DCC context: {dcc_ui_context_name} from {client.context_manager.active_context_name}")
            await client.view_manager.switch_active_context(dcc_ui_context_name)

    @staticmethod
    def get_dcc_ui_context_name(client: "IRCClient_Logic") -> str:
        """
        Returns the name of the DCC UI context, defaulting to "Status" if DCCManager isn't available.
        """
        return client.dcc_manager.dcc_ui_context_name if client.dcc_manager else "Status"

    @staticmethod
    async def show_dcc_help(client: "IRCClient_Logic", command_name: str, active_context_name: str):
        """
        Shows the help text for a specific DCC command.
        """
        cmd_help_data = client.command_handler.get_help_text_for_command(command_name)

        if cmd_help_data:
            # Check if structured help_info is available
            structured_help = cmd_help_data.get("help_info")
            if isinstance(structured_help, dict):
                usage = structured_help.get("usage", f"/{command_name} ...")
                desc = structured_help.get("description", "No description available.")
                aliases = ", ".join(structured_help.get("aliases", []))

                help_lines = [
                    f"Usage: {usage}",
                    f"Description: {desc}"
                ]
                if aliases:
                    help_lines.append(f"Aliases: {aliases}")

                for line in help_lines:
                    await client.add_message(line, client.ui.colors.get("help_text", 0), context_name=active_context_name)
            elif cmd_help_data.get("help_text"): # Fallback to simple help_text string
                 await client.add_message(cmd_help_data["help_text"], client.ui.colors.get("help_text", 0), context_name=active_context_name)
            else: # Should not happen if get_help_text_for_command returns valid data
                await client.add_message(
                    f"Help information for '/{command_name}' is incomplete.",
                    client.ui.colors.get("warning", 0),
                    context_name=active_context_name
                )
        else:
            await client.add_message(
                f"No help found for '/{command_name}'. Try '/help dcc'.",
                client.ui.colors.get("warning", 0),
                context_name=active_context_name
            )

    @staticmethod
    def parse_filename_with_quotes(args_list: List[str]) -> Tuple[Optional[str], List[str]]:
        """
        Parses a filename that might be enclosed in quotes from the beginning of an argument list.
        Returns the filename (without quotes) and the remaining arguments.
        If no quoted filename is found at the start, returns None and the original list.
        """
        if not args_list:
            return None, []

        full_args_str = " ".join(args_list)

        match = re.match(r'"([^"]*)"\s*(.*)', full_args_str)
        if match:
            filename = match.group(1)
            remaining_args_str = match.group(2).strip()
            remaining_args_list = remaining_args_str.split() if remaining_args_str else []
            return filename, remaining_args_list

        if not args_list[0].startswith('-'):
            return args_list[0], args_list[1:]

        return None, args_list
