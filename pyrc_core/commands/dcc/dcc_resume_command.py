# pyrc_core/commands/dcc/dcc_resume_command.py
import logging
import argparse
from typing import TYPE_CHECKING, List, Dict, Any, cast
from .dcc_command_base import DCCCommandHandlerBase

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
    # It's good practice to import specific types if they are used for casting or type hints
    # even if the full module is already imported under TYPE_CHECKING.
    from pyrc_core.dcc.dcc_transfer import DCCSendTransfer, DCCStatus
    # from pyrc_core.dcc.dcc_defs import DCCStatus as DCCConcreteStatus # This line caused the import error

logger = logging.getLogger("pyrc.commands.dcc.resume")

COMMAND_NAME = "resume"
COMMAND_ALIASES: List[str] = []
COMMAND_HELP: Dict[str, str] = {
    "usage": "/dcc resume <transfer_id_prefix_or_filename>",
    "description": "Attempts to resume a previously failed or cancelled DCC file transfer.",
    "aliases": "None" # Explicitly stating no aliases
}

class DCCResumeCommandHandler(DCCCommandHandlerBase):
    """Handles the /dcc resume command."""

    async def execute(self, cmd_args: List[str], active_context_name: str, dcc_context_name: str):
        """
        Handles the /dcc resume command.
        Attempts to resume a previously failed/cancelled outgoing DCC SEND transfer.
        """
        dcc_m = self.client_logic.dcc_manager
        if not dcc_m:
            await self._handle_dcc_error(f"DCC system not available for /dcc {COMMAND_NAME}.", active_context_name)
            return
        if not dcc_m.dcc_config.enabled:
            await self._handle_dcc_error(f"DCC is currently disabled. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
            return
        if not dcc_m.dcc_config.resume_enabled: # Assuming dcc_config is an attribute of dcc_m
            await self._handle_dcc_error(f"DCC resume is disabled in configuration. Cannot use /dcc {COMMAND_NAME}.", active_context_name)
            return

        parser_resume = argparse.ArgumentParser(prog=f"/dcc {COMMAND_NAME}", add_help=False)
        parser_resume.add_argument("identifier", help="The transfer ID prefix or filename to resume.")

        try:
            parsed_resume_args = parser_resume.parse_args(cmd_args)
            identifier = parsed_resume_args.identifier

            # Ensure DCCStatus is available for comparison. If it's from dcc_defs, use that.
            # This assumes DCCStatus is accessible, e.g., from pyrc_core.dcc.dcc_transfer or pyrc_core.dcc.dcc_defs
            # For this example, let's assume it's imported as DCCConcreteStatus if it's a direct enum/class.
            # If DCCStatus is an attribute of the transfer object (e.g. transfer_to_resume.status.FAILED),
            # then direct comparison is fine. The original code implies DCCStatus is an enum/class.
            # We need to ensure it's correctly referenced. For now, assuming it's available as DCCStatus from dcc_transfer.
            from pyrc_core.dcc.dcc_transfer import DCCStatus


            if hasattr(dcc_m, "send_manager") and dcc_m.send_manager:
                transfer_to_resume = None
                # Assuming dcc_m._lock is an asyncio.Lock if used in async context.
                # If it's a threading.Lock, it needs careful handling.
                # For now, proceeding as if access to dcc_m.transfers is safe or handled by dcc_m internally.
                # If dcc_m._lock is an asyncio.Lock:
                # async with dcc_m._lock:
                #     # ... find transfer ...
                # else direct access:

                # Try exact ID match first
                if identifier in dcc_m.transfers and isinstance(dcc_m.transfers[identifier], DCCSendTransfer): # DCCSendTransfer needs to be imported
                    transfer_to_resume = dcc_m.transfers[identifier]
                else:
                    # Try by prefix or filename match
                    matches = [
                        t for t in dcc_m.transfers.values()
                        if isinstance(t, DCCSendTransfer) and # DCCSendTransfer
                        (t.id.startswith(identifier) or t.filename.lower() == identifier.lower())
                    ]
                    if len(matches) == 1:
                        transfer_to_resume = matches[0]
                    elif len(matches) > 1:
                        await self._handle_dcc_error(
                            f"Ambiguous identifier '{identifier}'. Multiple transfers match. Please use a more specific ID prefix.",
                            dcc_context_name,
                        )
                        return

                if not transfer_to_resume:
                    await self._handle_dcc_error(
                        f"No resumable DCC SEND transfer found matching '{identifier}'.",
                        dcc_context_name,
                    )
                    return

                transfer_to_resume = cast("DCCSendTransfer", transfer_to_resume) # Ensure type for IDE/mypy

                if transfer_to_resume.status not in [DCCStatus.FAILED, DCCStatus.CANCELLED, DCCStatus.TIMED_OUT]:
                    await self._handle_dcc_error(
                        f"Transfer '{transfer_to_resume.filename}' (ID: {transfer_to_resume.id[:8]}) is not in a resumable state (current status: {transfer_to_resume.status.name}).",
                        dcc_context_name,
                    )
                    return

                # The method resume_send_transfer might need to be async if it performs async operations
                await dcc_m.send_manager.resume_send_transfer(transfer_to_resume, 0) # Added missing accepted_port argument

                resumed_filename = transfer_to_resume.filename
                resumed_tid = transfer_to_resume.id[:8]
                await self.client_logic.add_message(
                    f"Attempting to resume DCC SEND for '{resumed_filename}' (ID: {resumed_tid}).",
                    self.client_logic.ui.colors["system"],
                    context_name=dcc_context_name,
                )
            else:
                await self._handle_dcc_error(
                    "DCC Send Manager not initialized. Cannot use /dcc resume.",
                    dcc_context_name,
                )
            await self._ensure_dcc_context(dcc_context_name)

        except SystemExit: # argparse raises SystemExit on --help or error
            await self.client_logic.add_message(f"Usage: {COMMAND_HELP['usage']}", self.client_logic.ui.colors["error"], context_name=active_context_name)
        except Exception as e:
            logger.error(f"Error in /dcc {COMMAND_NAME}: {e}", exc_info=True)
            await self._handle_dcc_error(f"Error in /dcc {COMMAND_NAME}: {e}. Usage: {COMMAND_HELP['usage']}", active_context_name)

# This function will be called by the main dcc_commands.py dispatcher
def get_dcc_command_handler() -> Dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": COMMAND_ALIASES,
        "help": COMMAND_HELP,
        "handler_class": DCCResumeCommandHandler
    }
