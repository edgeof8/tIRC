# pyrc_core/client/client_view_manager.py
import asyncio
import logging
from typing import TYPE_CHECKING, Optional, List, Dict, Any, cast

from pyrc_core.client.ui_manager import UIManager # For runtime check

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.view_manager")

class ClientViewManager:
    def __init__(self, client: "IRCClient_Logic"):
        self.client = client

    async def switch_active_context(self, direction: str):
        logger.debug(f"ClientViewManager.switch_active_context called with direction: '{direction}'")
        context_names = self.client.context_manager.get_all_context_names()
        logger.debug(f"Available context names (raw from manager): {context_names}")
        if not context_names:
            logger.warning("ClientViewManager.switch_active_context: No context names returned from manager.")
            return

        status_context = "Status"
        dcc_context = "DCC"
        regular_contexts = [
            name for name in context_names if name not in [status_context, dcc_context]
        ]
        regular_contexts.sort(key=lambda x: x.lower())

        sorted_context_names = []
        if status_context in context_names:
            sorted_context_names.append(status_context)
        sorted_context_names.extend(regular_contexts)
        if dcc_context in context_names and dcc_context not in sorted_context_names:  # ensure DCC is added if present
            sorted_context_names.append(dcc_context)

        logger.debug(f"Sorted context names for cycling: {sorted_context_names}")

        current_active_name = self.client.context_manager.active_context_name
        logger.debug(f"Current active context name (from manager): {current_active_name}")

        if not current_active_name and sorted_context_names:
            current_active_name = sorted_context_names[0]
            logger.debug(f"Current active context was None, set to first sorted: {current_active_name}")
        elif not current_active_name:
            logger.warning("ClientViewManager.switch_active_context: Current active context is None and no sorted_context_names available. Returning.")
            return

        current_idx = -1
        if current_active_name:
            try:
                current_idx = sorted_context_names.index(current_active_name)
            except ValueError:
                logger.warning(f"ClientViewManager.switch_active_context: Current active context '{current_active_name}' not found in sorted list. Defaulting to index 0.")
                current_idx = 0
                if sorted_context_names:
                    current_active_name = sorted_context_names[0]
                else:
                    logger.error("ClientViewManager.switch_active_context: sorted_context_names is empty, cannot proceed.")
                    return

        logger.debug(f"Determined current_idx: {current_idx} for current_active_name: {current_active_name}")

        if not current_active_name:
            logger.error("ClientViewManager.switch_active_context: current_active_name is still None after attempting to default. This should not happen. Returning.")
            return

        new_active_context_name = None
        num_contexts = len(sorted_context_names)
        if num_contexts == 0:
            logger.warning("ClientViewManager.switch_active_context: num_contexts is 0. Returning.")
            return

        logger.debug(f"Cycling with num_contexts: {num_contexts}, current_idx: {current_idx}")

        if direction == "next":
            new_idx = (current_idx + 1) % num_contexts
            new_active_context_name = sorted_context_names[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + num_contexts) % num_contexts
            new_active_context_name = sorted_context_names[new_idx]
        else:
            if direction in sorted_context_names:
                new_active_context_name = direction
            else:
                try:
                    # Assuming direction might be a number string for direct indexing (1-based)
                    num_idx = int(direction) -1
                    if 0 <= num_idx < num_contexts:
                        new_active_context_name = sorted_context_names[num_idx]
                    else:
                        # Calling add_status_message on IRCClient_Logic instance
                        await self.client.add_status_message(f"Window number '{direction}' out of range.", "error")
                        return
                except ValueError: # Not a number, try partial match
                    found_ctx = [name for name in sorted_context_names if direction.lower() in name.lower()]
                    if len(found_ctx) == 1:
                        new_active_context_name = found_ctx[0]
                    elif len(found_ctx) > 1:
                        await self.client.add_status_message(
                            f"Ambiguous window name '{direction}'. Matches: {', '.join(sorted(found_ctx))}",
                            "error",
                        )
                        return
                    else: # No partial match, try case-insensitive exact match
                        exact_match_case_insensitive = [name for name in sorted_context_names if direction.lower() == name.lower()]
                        if len(exact_match_case_insensitive) == 1:
                            new_active_context_name = exact_match_case_insensitive[0]
                        else:
                            await self.client.add_status_message(
                                f"Window '{direction}' not found.",
                                "error",
                            )
                            return

        if new_active_context_name and new_active_context_name != current_active_name:
            logger.debug(f"Final attempt to set new active context to: {new_active_context_name}")
            if self.client.context_manager.set_active_context(new_active_context_name):
                logger.info(f"Successfully switched active context from '{current_active_name}' to: {new_active_context_name}")
                self.client.ui_needs_update.set()
            else:
                logger.error(f"Final attempt: Failed to set active context to {new_active_context_name} via context_manager.")
        elif new_active_context_name == current_active_name:
            logger.debug(f"New active context '{new_active_context_name}' is same as current '{current_active_name}'. No switch needed.")
        else:
            # This case implies new_active_context_name was not set, error already shown.
            logger.warning(f"ClientViewManager.switch_active_context: new_active_context_name is None after all processing for direction '{direction}'. No switch.")


    async def switch_active_channel(self, direction: str):
        all_context_names = self.client.context_manager.get_all_context_names()
        channel_names_only: List[str] = []
        for name in all_context_names:
            context_obj = self.client.context_manager.get_context(name)
            if context_obj and context_obj.type == "channel":
                channel_names_only.append(name)
        channel_names_only.sort(key=lambda x: x.lower())

        cyclable_contexts = channel_names_only[:]
        if "Status" in all_context_names:
            if "Status" not in cyclable_contexts:
                cyclable_contexts.append("Status")

        if not cyclable_contexts:
            await self.client.add_status_message(
                "No channels or Status window to switch to.",
                "system",
            )
            return

        current_active_name_str: Optional[str] = self.client.context_manager.active_context_name
        current_idx = -1
        if current_active_name_str and current_active_name_str in cyclable_contexts:
            current_idx = cyclable_contexts.index(current_active_name_str)

        new_active_channel_name_to_set: Optional[str] = None
        num_cyclable = len(cyclable_contexts)
        if num_cyclable == 0:
            return

        if current_idx == -1:
            new_active_channel_name_to_set = cyclable_contexts[0]
        elif direction == "next":
            new_idx = (current_idx + 1) % num_cyclable
            new_active_channel_name_to_set = cyclable_contexts[new_idx]
        elif direction == "prev":
            new_idx = (current_idx - 1 + num_cyclable) % num_cyclable
            new_active_channel_name_to_set = cyclable_contexts[new_idx]

        if new_active_channel_name_to_set:
            if self.client.context_manager.set_active_context(new_active_channel_name_to_set):
                logger.debug(f"Switched active channel/status to: {self.client.context_manager.active_context_name}")
                self.client.ui_needs_update.set()
            else:
                logger.error(f"Failed to set active channel/status to {new_active_channel_name_to_set}.")
                await self.client.add_status_message(
                    f"Error switching to '{new_active_channel_name_to_set}'.",
                    "error",
                )

    async def _handle_client_ready_for_ui_switch(self, event_data: Dict[str, Any]):
        nick = event_data.get("nick", "N/A")
        initial_channels_attempted = event_data.get("channels", [])
        logger.info(f"ClientViewManager: CLIENT_READY event received for nick '{nick}'. Auto-join initiated for: {initial_channels_attempted}")
        await self.client.add_status_message(f"Client ready. Nick: {nick}. Attempting to join: {', '.join(initial_channels_attempted) if initial_channels_attempted else 'None'}.")

        if not self.client._switched_to_initial_channel:
            current_active_normalized = self.client.context_manager._normalize_context_name(self.client.context_manager.active_context_name or "Status")
            normalized_initial_channels_attempted = {self.client.context_manager._normalize_context_name(ch) for ch in initial_channels_attempted if ch}

            if current_active_normalized.lower() != "status" and current_active_normalized not in normalized_initial_channels_attempted:
                logger.debug(
                    f"ClientViewManager: CLIENT_READY: Not yet switched to an initial channel. "
                    f"Active context '{self.client.context_manager.active_context_name}' is not Status or an attempted initial channel. "
                    f"Setting to 'Status'."
                )
                self.client.context_manager.set_active_context("Status")
        else:
            logger.debug(f"ClientViewManager: CLIENT_READY: Already switched to an initial channel ('{self.client.context_manager.active_context_name}'). No UI switch needed here.")

        self.client.ui_needs_update.set()

    async def _handle_auto_channel_fully_joined(self, event_data: Dict[str, Any]):
        joined_channel_name = event_data.get("channel_name")
        logger.debug(f"ClientViewManager: _handle_auto_channel_fully_joined: Called for channel '{joined_channel_name}'.")

        if not joined_channel_name:
            return

        conn_info = self.client.state_manager.get_connection_info()
        if not conn_info or not conn_info.initial_channels:
            logger.debug("ClientViewManager: _handle_auto_channel_fully_joined: No conn_info or no initial_channels configured. Returning.")
            return

        joined_channel_normalized = self.client.context_manager._normalize_context_name(joined_channel_name)
        normalized_initial_channels = [self.client.context_manager._normalize_context_name(ch) for ch in conn_info.initial_channels if ch]

        current_active_context_name_or_status = self.client.context_manager.active_context_name or "Status"
        current_active_normalized = self.client.context_manager._normalize_context_name(current_active_context_name_or_status)

        logger.debug(
            f"ClientViewManager: _handle_auto_channel_fully_joined: Joined='{joined_channel_normalized}', ConfiguredInitialChannels='{normalized_initial_channels}', "
            f"IsStatusActive={current_active_normalized.lower() == 'status'}, SwitchedAlready={self.client._switched_to_initial_channel}, CurrentActive='{current_active_normalized}'"
        )

        if (
            joined_channel_normalized in normalized_initial_channels
            and current_active_normalized.lower() == "status"
            and not self.client._switched_to_initial_channel
        ):
            logger.info(f"ClientViewManager: _handle_auto_channel_fully_joined: Auto-switching to first successfully joined initial channel: {joined_channel_name}")
            self.client.context_manager.set_active_context(joined_channel_name)
            if not self.client.is_headless and hasattr(self.client.ui, 'refresh_all_windows') and callable(self.client.ui.refresh_all_windows): # Check if it's UIManager
                # Ensure self.client.ui is UIManager before calling UIManager specific methods
                if TYPE_CHECKING: # This block is for type checkers
                     ui_manager = cast("UIManager", self.client.ui)
                     ui_manager.refresh_all_windows()
                elif isinstance(self.client.ui, UIManager): # Runtime check
                     self.client.ui.refresh_all_windows()

            self.client._switched_to_initial_channel = True
        elif joined_channel_normalized in normalized_initial_channels and self.client._switched_to_initial_channel:
            logger.debug(f"ClientViewManager: CHANNEL_FULLY_JOINED (auto-join): Initial channel '{joined_channel_normalized}' joined, but already switched to an earlier initial channel. No further auto-switch.")
        elif joined_channel_normalized in normalized_initial_channels and current_active_normalized.lower() != "status":
            logger.debug(f"ClientViewManager: CHANNEL_FULLY_JOINED (auto-join): Initial channel '{joined_channel_normalized}' joined, but UI is already on '{current_active_normalized}' (not Status). No auto-switch.")
        else:
            logger.debug(
                f"ClientViewManager: CHANNEL_FULLY_JOINED: '{joined_channel_normalized}' is not one of the configured initial channels or other conditions not met. No auto-switch action based on this event."
            )
