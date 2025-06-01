# context_manager.py
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
)  # Set removed, Dict was already present

from config import MAX_HISTORY

logger = logging.getLogger("pyrc.context")


class ChannelJoinStatus(Enum):
    NOT_JOINED = auto()
    PENDING_INITIAL_JOIN = auto()  # For initial channels list before connect/join command
    JOIN_COMMAND_SENT = auto()    # /join issued, or initial join command sent
    SELF_JOIN_RECEIVED = auto()   # Own JOIN echoed by server
    FULLY_JOINED = auto()         # RPL_ENDOFNAMES received, channel is ready
    PARTING = auto()              # /part issued, awaiting confirmation
    JOIN_FAILED = auto()          # Explicit failure (e.g. banned, invite-only)


class Context:
    """Represents a single context (server, channel, or query window)."""

    def __init__(
        self,
        name: str,
        context_type: str = "generic",
        topic: Optional[str] = None,
        max_history: int = MAX_HISTORY,
        initial_join_status: Optional[ChannelJoinStatus] = None,
    ):
        self.name: str = name
        self.type: str = context_type
        self.messages: Deque[Tuple[str, Any]] = deque(maxlen=max_history)
        self.users: Dict[str, str] = (
            {}
        )  # {'nickname': '<prefix_char>'} e.g. {'ChanOp': '@', 'User': ''}
        self.topic: Optional[str] = topic
        self.unread_count: int = 0
        self.scrollback_offset: int = 0
        self.user_list_scroll_offset: int = 0

        self.join_status: Optional[ChannelJoinStatus] # Declare with the broader type
        if context_type == "channel":
            self.join_status = initial_join_status if initial_join_status is not None else ChannelJoinStatus.NOT_JOINED
        else:
            self.join_status = None # Not applicable for non-channel contexts

    def add_message(self, text: str, color_attr: Any):
        self.messages.append((text, color_attr))

    def __repr__(self):
        user_count = len(self.users)
        join_status_repr = f" join_status={self.join_status.name}" if self.join_status else ""
        return f"<Context name='{self.name}' type='{self.type}' users={user_count} unread={self.unread_count}{join_status_repr} scroll_offset={self.scrollback_offset} user_scroll_offset={self.user_list_scroll_offset}>"

    def update_join_status(self, new_status: ChannelJoinStatus) -> bool:
        """
        Updates the join status for this context, if it's a channel.
        Logs the transition.
        Returns True if status was updated, False otherwise.
        """
        if self.type != "channel":
            logger.warning(f"Attempted to update join_status for non-channel context '{self.name}' (type: {self.type}) to {new_status.name}. Ignoring.")
            return False

        if self.join_status == new_status:
            # logger.debug(f"Join status for '{self.name}' is already {new_status.name}. No change.") # Optional: log no-ops
            return True # Considered successful as state is already as desired

        old_status_name = self.join_status.name if self.join_status else "None"
        self.join_status = new_status
        logger.info(f"Context '{self.name}': join_status changed from {old_status_name} -> {new_status.name}")
        return True


class ContextManager:
    """Manages multiple communication contexts (server, channels, queries)."""

    def __init__(self, max_history_per_context: int = MAX_HISTORY):
        self.contexts: Dict[str, Context] = {}
        self.active_context_name: Optional[str] = None  # Will store normalized names
        self.max_history = max_history_per_context
        logger.info(
            f"ContextManager initialized with max_history={max_history_per_context}"
        )

    def _normalize_context_name(self, name: str) -> str:
        if not name:  # Handle empty or None names gracefully
            return ""  # Or raise an error, depending on desired behavior
        if name.startswith(("#", "&", "!", "+")):
            return name.lower()
        return name  # For "Status", server names, query nicks, preserve case.

    def create_context(
        self,
        context_name: str,
        context_type: str = "generic",
        topic: Optional[str] = None,
        initial_join_status_for_channel: Optional[ChannelJoinStatus] = None,
    ) -> bool:
        original_passed_name = context_name  # For logging/debugging
        normalized_name = self._normalize_context_name(context_name)

        if not normalized_name:  # Avoid creating context with empty normalized name
            logger.warning(
                f"Attempted to create context with an empty or invalid original name: '{original_passed_name}'"
            )
            return False

        if normalized_name not in self.contexts:
            self.contexts[normalized_name] = Context(
                name=normalized_name,  # Store normalized name in Context object
                context_type=context_type,
                topic=topic,
                max_history=self.max_history,
                initial_join_status=initial_join_status_for_channel if context_type == "channel" else None,
            )
            # Refactor logging line to potentially help Pylance with type inference
            created_context = self.contexts[normalized_name]
            join_status_name = created_context.join_status.name if created_context.join_status else 'N/A'
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
            is_active = self.active_context_name == normalized_name
            del self.contexts[normalized_name]
            logger.info(
                f"Removed context: '{normalized_name}' (original: '{original_passed_name}')"
            )
            if is_active:
                self.active_context_name = None
            return True
        logger.warning(
            f"Context '{normalized_name}' (original: '{original_passed_name}') not found, cannot remove."
        )
        return False

    def get_context(self, context_name: str) -> Optional[Context]:
        normalized_name = self._normalize_context_name(context_name)
        return self.contexts.get(normalized_name)

    def get_active_context(self) -> Optional[Context]:
        if self.active_context_name:  # active_context_name is already normalized
            return self.contexts.get(self.active_context_name)  # Use .get for safety
        return None

    def set_active_context(self, context_name: str) -> bool:
        original_passed_name = context_name
        normalized_name = self._normalize_context_name(context_name)
        if normalized_name in self.contexts:
            self.active_context_name = normalized_name  # Store normalized name
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
        context = self.contexts.get(normalized_name)  # Use .get for safety

        if not context:
            logger.error(
                f"Attempted to add message to non-existent context: '{normalized_name}' (original: '{original_passed_name}')"
            )
            return

        context.add_message(text_line, color_attr)

        # active_context_name is already stored normalized
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
            )  # context.name is normalized
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
                context.users[user] = (
                    prefix  # Usernames themselves are case-sensitive/preserving
                )
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
        elif context:  # Context exists but user not in it
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
            if context.type in ["channel", "query"]:  # Only for relevant context types
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

    def set_channel_join_status(self, channel_name: str, new_status: ChannelJoinStatus) -> bool:
        """
        Sets the join status for a specific channel context.
        Returns True if the status was successfully updated, False otherwise.
        """
        normalized_name = self._normalize_context_name(channel_name)
        context = self.contexts.get(normalized_name)

        if not context:
            logger.warning(f"set_channel_join_status: Context '{normalized_name}' (original: '{channel_name}') not found.")
            return False

        if context.type != "channel":
            logger.warning(f"set_channel_join_status: Context '{normalized_name}' (original: '{channel_name}') is not a channel (type: {context.type}). Cannot set join status.")
            return False

        return context.update_join_status(new_status)
