import re
from typing import Optional, Dict, Any
import pyrc_core.app_config as app_config

IRC_MSG_RE = re.compile(
    app_config.IRC_MSG_REGEX_PATTERN if hasattr(app_config, 'IRC_MSG_REGEX_PATTERN')
    else r'^(?:@(?P<tags>[^ ]+) )?(?::(?P<prefix>[^ ]+) )?(?P<command>[^ ]+)(?: *(?P<params>[^:]*))?(?: *:(?P<trailing>.*))?$'
)


def unescape_tag_value(value: str) -> str:
    """Unescape an IRCv3 tag value according to the spec."""
    # Replace escaped characters
    value = value.replace("\\:", ";")
    value = value.replace("\\s", " ")
    value = value.replace("\\\\", "\\")
    value = value.replace("\\r", "\r")
    value = value.replace("\\n", "\n")
    return value


class IRCMessage:
    def __init__(
        self,
        prefix,
        command,
        params_str,
        trailing,
        tags: Optional[Dict[str, str]] = None,
    ):
        self.prefix = prefix
        self.command = command
        self.params_str = params_str.strip() if params_str else None
        self.trailing = trailing
        self.params = (
            [p for p in self.params_str.split(" ") if p] if self.params_str else []
        )
        self.source_nick = prefix.split("!")[0] if prefix and "!" in prefix else prefix
        self.tags = tags or {}

    @classmethod
    def parse(cls, line: str) -> Optional["IRCMessage"]:
        # First try to parse message tags if present
        tags = {}
        if line.startswith("@"):
            tag_end = line.find(" ")
            if tag_end == -1:
                return None
            tag_str = line[1:tag_end]
            line = line[tag_end + 1 :]

            # Parse tags
            for tag in tag_str.split(";"):
                if "=" in tag:
                    key, value = tag.split("=", 1)
                    tags[key] = unescape_tag_value(value)
                else:
                    tags[tag] = ""

        # Parse the rest of the message
        match = IRC_MSG_RE.match(line)
        if not match:
            return None
        return cls(*match.groups(), tags=tags)

    def get_tag(self, key: str, default: Any = None) -> Any:
        """Get a message tag value, with optional default if not present."""
        return self.tags.get(key, default)

    def has_tag(self, key: str) -> bool:
        """Check if a message tag is present."""
        return key in self.tags

    def get_all_tags(self) -> Dict[str, str]:
        """Get all message tags."""
        return self.tags.copy()
