import logging
from typing import TYPE_CHECKING, Optional, List

# from context_manager import ChannelJoinStatus, Context # No longer needed

if TYPE_CHECKING:
    from irc_client_logic import IRCClient_Logic

logger = logging.getLogger("pyrc.channel_commands_handler")

# The ChannelCommandsHandler class is now empty of active command handlers
# and can be removed. All its functionality has been moved to
# individual command modules under commands/channel/
