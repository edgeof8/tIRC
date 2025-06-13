# tirc_core/dcc/dcc_protocol.py
import logging
import re
from typing import Optional, Dict, Any, Tuple # Added Tuple

logger = logging.getLogger("tirc.dcc.protocol")

# This file would contain more detailed parsing and formatting logic for various
# DCC sub-protocols if they become more complex than what dcc_utils.py handles.
# For now, dcc_utils.py contains format_dcc_ctcp and parse_dcc_ctcp.

# Example: If we needed to handle DCC CHAT specific messages or more complex SEND variations.

class DCCProtocolError(Exception):
    """Custom exception for DCC protocol errors."""
    pass

def parse_dcc_filename(argument_str: str) -> Tuple[str, str]:
    """
    Parses a DCC filename argument, which might be quoted.
    Returns the filename and the rest of the argument string.
    """
    if not argument_str:
        raise DCCProtocolError("Empty argument string for filename parsing.")

    if argument_str.startswith('"'):
        match = re.match(r'"([^"]*)"(.*)', argument_str)
        if match:
            filename = match.group(1)
            rest = match.group(2).lstrip()
            return filename, rest
        else:
            # Unmatched quote, treat as non-quoted or raise error
            # For simplicity, let's assume if it starts with quote, it must end with one correctly for this parser.
            raise DCCProtocolError(f"Unmatched quote in DCC filename argument: {argument_str}")
    else:
        # Not quoted, filename is the first word
        parts = argument_str.split(maxsplit=1)
        filename = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        return filename, rest


# Any other DCC protocol-specific constants or helper functions could go here.
# For example, defining known DCC commands or sub-types if needed for validation.
KNOWN_DCC_COMMANDS = {"SEND", "GET", "ACCEPT", "RESUME", "CHAT"} # etc.
