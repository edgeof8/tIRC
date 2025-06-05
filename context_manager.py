import logging
from collections import deque
from enum import Enum, auto
from typing import (
    Optional,
    Any,
    Deque,
    Tuple,
    Dict,
    List,
)

from config import MAX_HISTORY

logger = logging.getLogger("pyrc.context")


class ChannelJoinStatus(Enum):
    NOT_JOINED = auto()
    PENDING_INITIAL_JOIN = auto()
    JOIN_COMMAND_SENT = auto()
    SELF_JOIN_RECEIVED = auto()
    FULLY_JOINED = auto()
    PARTING = auto()
    JOIN_FAILED = auto()


class Context:
    """Represents a single context (server, channel, or query window)."""

    def __init__(
        self,
        name: str,
        context_type: str = "channel",
        topic: Optional[str] = None,
        max_history: int = MAX_HISTORY,
        initial_join_status: Optional[ChannelJoinStatus] = None,
    ):
        self.name: str = name
        self.type: str = context_type
        self.messages: Deque[Tuple[str, Any]] = deque(maxlen=max_history)
        self.users: Dict[str, str] = {}
        self.user_prefixes: Dict[str, str] = {}
        self.modes: set = set()
        self.topic: Optional[str] = topic
        self.unread_count: int = 0
        self.scrollback_offset: int = 0
        self.user_list_scroll_offset: int = 0

        self.join_status: Optional[ChannelJoinStatus]
        if context_type == "channel":
            self.join_status = (
                initial_join_status
                if initial_join_status is not None
                else ChannelJoinStatus.NOT_JOINED
            )
        else:
            self.join_status = None

    def add_message(self, text: str, color_attr: Any):
        self.messages.append((text, color_attr))

    def __repr__(self):
        user_count = len(self.users)
        join_status_repr = (
            f" join_status={self.join_status.name}" if self.join_status else ""
        )
        return f"<Context name='{self.name}' type='{self.type}' users={user_count} unread={self.unread_count}{join_status_repr} scroll_offset={self.scrollback_offset} user_scroll_offset={self.user_list_scroll_offset}>"

    def update_join_status(self, new_status: ChannelJoinStatus) -> bool:
        """
        Updates the join status for this context, if it's a channel.
        Logs the transition.
        Returns True if status was updated, False otherwise.
        """
        if self.type != "channel":
            logger.warning(
                f"Attempted to update join_status for non-channel context '{self.name}' (type: {self.type}) to {new_status.name}. Ignoring."
            )
            return False

        if self.join_status == new_status:
            return True

        old_status_name = self.join_status.name if self.join_status else "None"
        self.join_status = new_status
        logger.info(
            f"Context '{self.name}': join_status changed from {old_status_name} -> {new_status.name}"
        )
        return True


class ContextManager:
    """Manages multiple communication contexts (server, channels, queries)."""

    def __init__(self, max_history_per_context: int = MAX_HISTORY):
        self.contexts: Dict[str, Context] = {}
        self.active_context_name: Optional[str] = None
        self.max_history = max_history_per_context
        logger.info(
            f"ContextManager initialized with max_history={max_history_per_context}"
        )

    def _normalize_context_name(self, name: str) -> str:
        if not name:
            return ""
        if name.startswith(("#", "&", "!", "+")):
            return name.lower()
        return name

    def create_context(
        self,
        context_name: str,
        context_type: str = "generic",
        topic: Optional[str] = None,
        initial_join_status_for_channel: Optional[ChannelJoinStatus] = None,
    ) -> bool:
        original_passed_name = context_name
        normalized_name = self._normalize_context_name(context_name)

        if not normalized_name:
            logger.warning(
                f"Attempted to create context with an empty or invalid original name: '{original_passed_name}'"
            )
            return False

        # Special handling for DCC windows
        if context_type == "dcc":
            # Ensure DCC windows have a unique name
            if normalized_name in self.contexts:
                logger.debug(
                    f"DCC context '{normalized_name}' already exists, skipping creation."
                )
                return False

        if normalized_name not in self.contexts:
            self.contexts[normalized_name] = Context(
                name=normalized_name,
                context_type=context_type,
                topic=topic,
                max_history=self.max_history,
                initial_join_status=(
                    initial_join_status_for_channel
                    if context_type == "channel"
                    else None
                ),
            )
            created_context = self.contexts[normalized_name]
            join_status_name = (
                created_context.join_status.name
                if created_context.join_status
                else "N/A"
            )
            logger.debug(
                f"Created context: '{normalized_name}' (original: '{original_passed_name}') of type {context_type} with join_status: {join_status_name}"
            )
            return True
        logger.debug(
            f"Context '{normalized_name}' (original: '{original_passed_name}') already exists."
        )
        return False

    def remove_context(self, context_name: str) -> bool:
        original_passed_name = context_name
        normalized_name = self._normalize_context_name(context_name)
        if normalized_name in self.contexts:
            context = self.contexts[normalized_name]
            is_active = self.active_context_name == normalized_name

            # Special handling for DCC windows
            if context.type == "dcc":
                # If this is the active context, switch to Status before removing
                if is_active:
                    status_context = self.get_context("Status")
                    if status_context:
                        self.set_active_context("Status")
                    else:
                        # If no Status context, switch to any available context
                        other_contexts = [
                            name
                            for name in self.contexts.keys()
                            if name != normalized_name
                        ]
                        if other_contexts:
                            self.set_active_context(other_contexts[0])
                        else:
                            self.active_context_name = None

            del self.contexts[normalized_name]
            logger.info(
                f"Removed context: '{normalized_name}' (original: '{original_passed_name}')"
            )
            return True
        logger.warning(
            f"Context '{normalized_name}' (original: '{original_passed_name}') not found, cannot remove."
        )
        return False

    def get_context(self, context_name: str) -> Optional[Context]:
        normalized_name = self._normalize_context_name(context_name)
        return self.contexts.get(normalized_name)

    def get_active_context(self) -> Optional[Context]:
        if self.active_context_name:
            return self.contexts.get(self.active_context_name)
        return None

    def set_active_context(self, context_name: str) -> bool:
        original_passed_name = context_name
        normalized_name = self._normalize_context_name(context_name)
        if normalized_name in self.contexts:
            self.active_context_name = normalized_name
            context = self.contexts[normalized_name]
            context.unread_count = 0
            logger.debug(
                f"Switched active context to: '{normalized_name}' (original: '{original_passed_name}')"
            )
            return True
        logger.warning(
            f"Cannot switch to non-existent context: '{normalized_name}' (original: '{original_passed_name}')"
        )
        return False

    def get_all_context_names(self) -> List[str]:
        return list(self.contexts.keys())

    def add_message_to_context(
        self,
        context_name: str,
        text_line: str,
        color_attr: Any,
        num_lines_added: int = 1,
    ):
        original_passed_name = context_name
        normalized_name = self._normalize_context_name(context_name)
        context = self.contexts.get(normalized_name)

        if not context:
            logger.error(
                f"Attempted to add message to non-existent context: '{normalized_name}' (original: '{original_passed_name}')"
            )
            return

        context.add_message(text_line, color_attr)

        if self.active_context_name != normalized_name:
            context.unread_count += num_lines_added

    def update_topic(self, context_name: str, topic: str) -> bool:
        original_passed_name = context_name
        normalized_name = self._normalize_context_name(context_name)
        context = self.contexts.get(normalized_name)
        if context:
            context.topic = topic
            logger.debug(
                f"Updated topic for context: '{context.name}' (original passed: '{original_passed_name}')"
            )
            return True
        logger.warning(
            f"Failed to update topic for non-existent context: '{normalized_name}' (original: '{original_passed_name}')"
        )
        return False

    def add_user(self, context_name: str, user: str, prefix: str = "") -> bool:
        """Adds a user with an optional prefix to a context."""
        original_passed_name = context_name
        normalized_name = self._normalize_context_name(context_name)
        context = self.contexts.get(normalized_name)
        if context:
            if context.type in ["channel", "query"]:
                context.users[user] = prefix
                logger.debug(
                    f"Added/updated user '{user}' with prefix '{prefix}' in context '{context.name}' (original passed: '{original_passed_name}')"
                )
                return True
            else:
                logger.debug(
                    f"Not adding user '{user}' to context '{context.name}' (type '{context.type}') (original passed: '{original_passed_name}')"
                )
        else:
            logger.warning(
                f"Failed to add user to non-existent context: '{normalized_name}' (original: '{original_passed_name}')"
            )
        return False

    def remove_user(self, context_name: str, user: str) -> bool:
        """Removes a user from a context."""
        original_passed_name = context_name
        normalized_name = self._normalize_context_name(context_name)
        context = self.contexts.get(normalized_name)
        if context and user in context.users:
            del context.users[user]
            logger.debug(
                f"Removed user '{user}' from context '{context.name}' (original passed: '{original_passed_name}')"
            )
            return True
        if not context:
            logger.warning(
                f"Failed to remove user from non-existent context: '{normalized_name}' (original: '{original_passed_name}')"
            )
        elif context:
            logger.debug(
                f"User '{user}' not found in context '{context.name}', cannot remove (original passed: '{original_passed_name}')."
            )
        return False

    def get_users(self, context_name: str) -> Dict[str, str]:
        """Retrieves the dictionary of users and their prefixes for a context."""
        original_passed_name = context_name
        normalized_name = self._normalize_context_name(context_name)
        context = self.contexts.get(normalized_name)
        if not context:
            logger.debug(
                f"Attempted to get users from non-existent context: '{normalized_name}' (original: '{original_passed_name}')"
            )
            return {}
        return context.users

    def get_user_prefix(self, context_name: str, user: str) -> str:
        """Retrieves the prefix for a specific user in a context."""
        context = self.get_context(context_name)
        if context and user in context.users:
            return context.users[user]
        return ""

    def update_user_prefix(self, context_name: str, user: str, new_prefix: str) -> bool:
        """Updates the prefix for an existing user in a context.
        If the user doesn't exist, it adds them with the new prefix.
        """
        context = self.get_context(context_name)
        if context:
            if context.type in ["channel", "query"]:
                context.users[user] = new_prefix
                logger.debug(
                    f"Updated prefix for user '{user}' to '{new_prefix}' in context '{context_name}'"
                )
                return True
        return False

    def get_context_messages(
        self, context_name: str
    ) -> Optional[Deque[Tuple[str, Any]]]:
        context = self.get_context(context_name)
        return context.messages if context else None

    def get_context_type(self, context_name: str) -> Optional[str]:
        context = self.get_context(context_name)
        return context.type if context else None

    def get_context_topic(self, context_name: str) -> Optional[str]:
        context = self.get_context(context_name)
        return context.topic if context else None

    def get_unread_count(self, context_name: str) -> int:
        """Gets the unread message count for a context."""
        context = self.get_context(context_name)
        return context.unread_count if context else 0

    def reset_unread_count(self, context_name: str) -> bool:
        context = self.get_context(context_name)
        if context:
            context.unread_count = 0
            return True
        return False

    def set_channel_join_status(
        self, channel_name: str, new_status: ChannelJoinStatus
    ) -> bool:
        """
        Sets the join status for a specific channel context.
        Returns True if the status was successfully updated, False otherwise.
        """
        normalized_name = self._normalize_context_name(channel_name)
        context = self.contexts.get(normalized_name)

        if not context:
            logger.warning(
                f"set_channel_join_status: Context '{normalized_name}' (original: '{channel_name}') not found."
            )
            return False

        if context.type != "channel":
            logger.warning(
                f"set_channel_join_status: Context '{normalized_name}' (original: '{channel_name}') is not a channel (type: {context.type}). Cannot set join status."
            )
            return False

        return context.update_join_status(new_status)

    def get_context_messages_raw(
        self, context_name: str, count: Optional[int] = None
    ) -> Optional[List[Tuple[str, Any]]]:
        """
        Retrieves messages from a specified context's buffer.

        Args:
            context_name: The name of the context.
            count: If provided, retrieve only the last 'count' messages. Otherwise, all messages.

        Returns:
            A list of (message_text, color_attribute) tuples, or None if context not found.
            Returns an empty list if the context exists but has no messages.
        """
        context = self.get_context(context_name)
        if not context:
            logger.warning(
                f"get_context_messages_raw: Context '{context_name}' not found."
            )
            return None

        if not hasattr(context, "messages") or not isinstance(context.messages, deque):
            logger.warning(
                f"get_context_messages_raw: Context '{context_name}' has no valid 'messages' deque."
            )
            return []

        # Return a copy of the messages
        all_messages = list(context.messages)
        if count is None:
            return all_messages
        else:
            # Ensure count is positive
            if not isinstance(count, int) or count <= 0:
                logger.warning(
                    f"get_context_messages_raw: Invalid count '{count}' provided. Returning all messages."
                )
                return all_messages
            return all_messages[-count:]  # Get the last 'count' messages
