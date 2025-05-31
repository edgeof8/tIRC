# context_manager.py
import logging
from collections import deque
from typing import Optional, Any, Set, Deque, Tuple, Dict, List # Dict added

from config import MAX_HISTORY

logger = logging.getLogger("pyrc.context")


class Context:
    """Represents a single context (server, channel, or query window)."""

    def __init__(
        self,
        name: str,
        context_type: str = "generic",
        topic: Optional[str] = None,
        max_history: int = MAX_HISTORY,
    ):
        self.name: str = name
        self.type: str = context_type
        self.messages: Deque[Tuple[str, Any]] = deque(maxlen=max_history)
        # Changed users from Set[str] to Dict[str, str] to store prefixes
        self.users: Dict[str, str] = {}  # {'nickname': '<prefix_chars>'} e.g. {'ChanOp': '@'}
        self.topic: Optional[str] = topic
        self.unread_count: int = 0
        self.scrollback_offset: int = 0

    def add_message(self, text: str, color_attr: Any):
        self.messages.append((text, color_attr))

    def __repr__(self):
        user_count = len(self.users)
        return f"<Context name='{self.name}' type='{self.type}' users={user_count} unread={self.unread_count} scroll_offset={self.scrollback_offset}>"


class ContextManager:
    """Manages multiple communication contexts (server, channels, queries)."""

    def __init__(self, max_history_per_context: int = MAX_HISTORY):
        self.contexts: Dict[str, Context] = {}
        self.active_context_name: Optional[str] = None
        self.max_history = max_history_per_context
        logger.info(
            f"ContextManager initialized with max_history={max_history_per_context}"
        )

    def create_context(
        self,
        context_name: str,
        context_type: str = "generic",
        topic: Optional[str] = None,
    ) -> bool:
        if context_name not in self.contexts:
            self.contexts[context_name] = Context(
                name=context_name,
                context_type=context_type,
                topic=topic,
                max_history=self.max_history,
            )
            logger.debug(f"Created context: {context_name} of type {context_type}")
            return True
        return False

    def remove_context(self, context_name: str) -> bool:
        if context_name in self.contexts:
            is_active = self.active_context_name == context_name
            del self.contexts[context_name]
            logger.info(f"Removed context: {context_name}")
            if is_active:
                self.active_context_name = None
            return True
        logger.warning(f"Context {context_name} not found, cannot remove.")
        return False

    def get_context(self, context_name: str) -> Optional[Context]:
        return self.contexts.get(context_name)

    def get_active_context(self) -> Optional[Context]:
        if self.active_context_name:
            return self.get_context(self.active_context_name)
        return None

    def set_active_context(self, context_name: str) -> bool:
        if context_name in self.contexts:
            self.active_context_name = context_name
            context = self.contexts[context_name]
            context.unread_count = 0
            logger.debug(f"Switched active context to: {context_name}")
            return True
        logger.warning(f"Cannot switch to non-existent context: {context_name}")
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
        context = self.get_context(context_name)
        if not context:
            logger.error(
                f"Attempted to add message to non-existent context: {context_name}"
            )
            return

        context.add_message(text_line, color_attr)

        if self.active_context_name != context_name:
            context.unread_count += num_lines_added

    def update_topic(self, context_name: str, topic: str) -> bool:
        context = self.get_context(context_name)
        if context:
            context.topic = topic
            return True
        return False

    def add_user(self, context_name: str, user: str, prefix: str = "") -> bool:
        """Adds a user with an optional prefix to a context."""
        context = self.get_context(context_name)
        if context:
            # For now, only store users in channel or query contexts.
            # Status context doesn't typically have a user list in this sense.
            if context.type in ["channel", "query"]:
                context.users[user] = prefix
                logger.debug(f"Added/updated user '{user}' with prefix '{prefix}' in context '{context_name}'")
                return True
            else:
                logger.debug(f"Not adding user '{user}' to context '{context_name}' of type '{context.type}'")
        return False

    def remove_user(self, context_name: str, user: str) -> bool:
        """Removes a user from a context."""
        context = self.get_context(context_name)
        if context and user in context.users:
            del context.users[user]
            logger.debug(f"Removed user '{user}' from context '{context_name}'")
            return True
        return False

    def get_users(self, context_name: str) -> Dict[str, str]:
        """Retrieves the dictionary of users and their prefixes for a context."""
        context = self.get_context(context_name)
        return context.users if context else {}

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
            if context.type in ["channel", "query"]: # Only for relevant context types
                context.users[user] = new_prefix
                logger.debug(f"Updated prefix for user '{user}' to '{new_prefix}' in context '{context_name}'")
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
        context = self.get_context(context_name)
        return context.unread_count if context else 0

    def reset_unread_count(self, context_name: str) -> bool:
        context = self.get_context(context_name)
        if context:
            context.unread_count = 0
            return True
        return False
