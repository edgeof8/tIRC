# irc_message.py
import re
from typing import Optional
from config import IRC_MSG_REGEX_PATTERN

IRC_MSG_RE = re.compile(IRC_MSG_REGEX_PATTERN)

class IRCMessage:
    def __init__(self, prefix, command, params_str, trailing):
        self.prefix = prefix
        self.command = command
        self.params_str = params_str.strip() if params_str else None
        self.trailing = trailing
        self.params = (
            [p for p in self.params_str.split(" ") if p] if self.params_str else []
        )
        self.source_nick = prefix.split("!")[0] if prefix and "!" in prefix else prefix

    @classmethod
    def parse(cls, line):
        match = IRC_MSG_RE.match(line)
        if not match:
            return None
        return cls(*match.groups())
