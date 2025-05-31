# context_manager.py
import logging
from collections import deque
from typing import Optional, Any, Set, Deque, Tuple, Dict, List

from config import MAX_HISTORY  # For default max_history in Context

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
        self.type: str = context_type  # "status", "channel", "query", "generic"
        self.messages: Deque[Tuple[str, Any]] = deque(
            maxlen=max_history
        )  # (text, color_attribute)
        self.users: Set[str] = set()
        self.topic: Optional[str] = topic
        self.unread_count: int = 0
        # self.last_read_line_count: int = 0 # UI specific, consider if needed here or managed by UI

    def add_message(self, text: str, color_attr: Any):
        """Adds a single pre-formatted line to the context's message deque."""
        self.messages.append((text, color_attr))

    def __repr__(self):
        return f"<Context name='{self.name}' type='{self.type}' unread={self.unread_count}>"


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
        """Creates a new context if it doesn't already exist."""
        if context_name not in self.contexts:
            self.contexts[context_name] = Context(
                name=context_name,
                context_type=context_type,
                topic=topic,
                max_history=self.max_history,
            )
            logger.debug(f"Created context: {context_name} of type {context_type}")
            return True
        logger.warning(f"Context {context_name} already exists, not creating.")
        return False

    def remove_context(self, context_name: str) -> bool:
        """Removes a context. Returns True if successful, False otherwise."""
        if context_name in self.contexts:
            is_active = self.active_context_name == context_name
            del self.contexts[context_name]
            logger.info(f"Removed context: {context_name}")
            if is_active:
                self.active_context_name = (
                    None  # Caller should handle switching to a new active context
                )
            return True
        logger.warning(f"Context {context_name} not found, cannot remove.")
        return False

    def get_context(self, context_name: str) -> Optional[Context]:
        """Retrieves a context by its name."""
        return self.contexts.get(context_name)

    def get_active_context(self) -> Optional[Context]:
        """Retrieves the currently active context object."""
        if self.active_context_name:
            return self.get_context(self.active_context_name)
        return None

    def set_active_context(self, context_name: str) -> bool:
        """Sets the active context by name. Resets unread count for the new active context."""
        if context_name in self.contexts:
            self.active_context_name = context_name
            context = self.contexts[context_name]
            context.unread_count = 0
            logger.debug(f"Switched active context to: {context_name}")
            return True
        logger.warning(f"Cannot switch to non-existent context: {context_name}")
        return False

    def get_all_context_names(self) -> List[str]:
        """Returns a list of all context names. The order might not be guaranteed unless sorted."""
        return list(self.contexts.keys())

    def add_message_to_context(
        self,
        context_name: str,
        text_line: str,
        color_attr: Any,
        num_lines_added: int = 1,
    ):
        """
        Adds a pre-formatted message line to the specified context.
        Updates unread count if the context is not active.
        """
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
        """Updates the topic for a given context."""
        context = self.get_context(context_name)
        if context:
            context.topic = topic
            logger.debug(f"Topic for {context_name} updated to: {topic[:50]}...")
            return True
        logger.warning(f"Cannot update topic for non-existent context: {context_name}")
        return False

    def add_user(self, context_name: str, user: str) -> bool:
        """Adds a user to the user list of a context (typically channel or query)."""
        context = self.get_context(context_name)
        if context:  # Could also check context.type
            context.users.add(user)
            return True
        return False

    def remove_user(self, context_name: str, user: str) -> bool:
        """Removes a user from the user list of a context."""
        context = self.get_context(context_name)
        if context and user in context.users:
            context.users.remove(user)
            return True
        return False

    def get_users(self, context_name: str) -> Set[str]:
        """Retrieves the set of users for a given context."""
        context = self.get_context(context_name)
        return context.users if context else set()

    def get_context_messages(
        self, context_name: str
    ) -> Optional[Deque[Tuple[str, Any]]]:
        """Retrieves the message deque for a given context."""
        context = self.get_context(context_name)
        return context.messages if context else None

    def get_context_type(self, context_name: str) -> Optional[str]:
        """Retrieves the type of a given context."""
        context = self.get_context(context_name)
        return context.type if context else None

    def get_context_topic(self, context_name: str) -> Optional[str]:
        """Retrieves the topic of a given context."""
        context = self.get_context(context_name)
        return context.topic if context else None

    def get_unread_count(self, context_name: str) -> int:
        """Retrieves the unread message count for a given context."""
        context = self.get_context(context_name)
        return context.unread_count if context else 0

    def reset_unread_count(self, context_name: str) -> bool:
        """Resets the unread count for a specific context."""
        context = self.get_context(context_name)
        if context:
            context.unread_count = 0
            return True
        return False
