# START OF MODIFIED FILE: features/triggers/trigger_commands.py
import logging
import time
from typing import TYPE_CHECKING, List, Optional, Dict, Any

if TYPE_CHECKING:
    from pyrc_core.client.irc_client_logic import IRCClient_Logic
# Removed TriggerType, ActionType is already available via trigger_manager instance or direct import if needed by methods
# from .trigger_manager import TriggerType, ActionType # ActionType might be needed if used directly

logger = logging.getLogger("pyrc.features.triggers.commands")

class TriggerCommands:
    def __init__(self, client_logic: "IRCClient_Logic"):
        self.client = client_logic

    def _parse_on_args(self, args_str: str) -> Optional[Dict[str, Any]]:
        parts = args_str.split(maxsplit=3)
        # /on <EVENT_TYPE> <pattern> <action_type> [action_content]
        # /on <EVENT_TYPE> <pattern> PY <code>
        # /on <EVENT_TYPE> <pattern> CMD /command_to_run
        # /on list [event_type]
        # /on del <id>
        # /on enable <id>
        # /on disable <id>

        if not parts:
            return {"sub_command": "show_usage"}

        sub_command = parts[0].lower()

        if sub_command in ["list", "del", "delete", "rm", "enable", "disable", "info"]:
            if sub_command == "del" or sub_command == "delete" or sub_command == "rm":
                if len(parts) < 2: return None # Requires ID
                try:
                    return {"sub_command": "delete", "trigger_id": int(parts[1])}
                except ValueError:
                    return None # Invalid ID
            elif sub_command == "enable" or sub_command == "disable":
                if len(parts) < 2: return None # Requires ID
                try:
                    return {"sub_command": sub_command, "trigger_id": int(parts[1])}
                except ValueError:
                    return None # Invalid ID
            elif sub_command == "list":
                return {"sub_command": "list", "event_filter": parts[1].upper() if len(parts) > 1 else None}
            elif sub_command == "info":
                if len(parts) < 2: return None
                try:
                    return {"sub_command": "info", "trigger_id": int(parts[1])}
                except ValueError:
                    return None
            return None # Should not happen if sub_command is one of the above

        # Adding a new trigger
        if len(parts) < 4: # Needs at least EVENT_TYPE, pattern, ACTION_TYPE, action_content/code
            # Special case: /on EVENT PATTERN PY (code might be empty initially, or user is typing)
            if len(parts) == 3 and parts[2].upper() == "PY":
                 # Allow this form, but it's incomplete for actual addition via command
                 # For now, consider it an error for direct command parsing, but UI might build it incrementally
                return None
            return None

        event_type = parts[0].upper()
        pattern = parts[1]
        action_type_str = parts[2].upper()
        action_content = parts[3] # The rest of the string

        # Validate ActionType directly here if needed, or let TriggerManager handle it
        # from .trigger_manager import ActionType # Import locally if needed for validation
        # action_type_enum = ActionType.from_string(action_type_str)
        # if not action_type_enum:
        #     self.client.add_message(f"Invalid action type: {action_type_str}. Use CMD or PY.", "error")
        #     return None

        return {
            "sub_command": "add",
            "event_type": event_type,
            "pattern": pattern,
            "action_type": action_type_str, # Pass as string, TriggerManager will convert
            "action_content": action_content,
        }


    def handle_on_command(self, args_str: str):
        if not self.client.trigger_manager:
            self.client.add_message("Trigger system is not enabled or available.", "error")
            return

        parsed_args = self._parse_on_args(args_str)
        active_ctx = self.client.context_manager.active_context_name or "Status"

        if parsed_args is None:
            self.client.add_message("Usage: /on <LIST|ADD|DEL|ENABLE|DISABLE|INFO> [params...]", "error", context_name=active_ctx)
            self.client.add_message("  /on ADD <EVENT> <pattern> <CMD|PY> <action_content/code>", "error", context_name=active_ctx)
            self.client.add_message("  Example: /on TEXT \"hello world\" CMD /say Hello back!", "error", context_name=active_ctx)
            self.client.add_message("  Example: /on RAW \"PRIVMSG #chan :hi\" PY print(event_data['nick'] + ' said hi')", "error", context_name=active_ctx)
            return

        sub_command = parsed_args.get("sub_command")

        if sub_command == "add":
            trigger_id = self.client.trigger_manager.add_trigger(
                event_type_str=parsed_args["event_type"],
                pattern=parsed_args["pattern"],
                action_type_str=parsed_args["action_type"],
                action_content=parsed_args["action_content"]
            )
            if trigger_id is not None:
                self.client.add_message(f"Trigger added with ID: {trigger_id}", "system", context_name=active_ctx)
            else:
                self.client.add_message("Failed to add trigger. Check pattern or action type.", "error", context_name=active_ctx)

        elif sub_command == "list":
            event_filter = parsed_args.get("event_filter")
            triggers = self.client.trigger_manager.list_triggers(event_type=event_filter)
            if triggers:
                self.client.add_message(f"--- Configured Triggers ({event_filter or 'All'}) ---", "system", context_name=active_ctx)
                for t in triggers:
                    enabled_str = "Enabled" if t['is_enabled'] else "Disabled"
                    action_preview = t['action_content'][:50] + "..." if len(t['action_content']) > 50 else t['action_content']
                    self.client.add_message(
                        f"ID: {t['id']}, Event: {t['event_type']}, Pattern: '{t['pattern']}', Action: {t['action_type']} '{action_preview}', Status: {enabled_str}",
                        "system", context_name=active_ctx
                    )
            else:
                self.client.add_message(f"No triggers configured{(' for event ' + event_filter) if event_filter else ''}.", "system", context_name=active_ctx)

        elif sub_command == "delete":
            trigger_id = parsed_args["trigger_id"]
            if self.client.trigger_manager.remove_trigger(trigger_id):
                self.client.add_message(f"Trigger {trigger_id} removed.", "system", context_name=active_ctx)
            else:
                self.client.add_message(f"Failed to remove trigger {trigger_id}. Not found?", "error", context_name=active_ctx)

        elif sub_command == "enable" or sub_command == "disable":
            trigger_id = parsed_args["trigger_id"]
            should_enable = sub_command == "enable"
            if self.client.trigger_manager.set_trigger_enabled(trigger_id, should_enable):
                self.client.add_message(f"Trigger {trigger_id} {'enabled' if should_enable else 'disabled'}.", "system", context_name=active_ctx)
            else:
                self.client.add_message(f"Failed to update trigger {trigger_id}. Not found?", "error", context_name=active_ctx)

        elif sub_command == "info":
            trigger_id = parsed_args["trigger_id"]
            trigger = self.client.trigger_manager.get_trigger(trigger_id)
            if trigger:
                self.client.add_message(f"--- Trigger Info (ID: {trigger.id}) ---", "system", context_name=active_ctx)
                self.client.add_message(f"  Event Type: {trigger.event_type}", "system", context_name=active_ctx)
                self.client.add_message(f"  Pattern: '{trigger.pattern}' (Regex: {trigger.is_regex}, IgnoreCase: {trigger.ignore_case})", "system", context_name=active_ctx)
                self.client.add_message(f"  Action Type: {trigger.action_type.name}", "system", context_name=active_ctx)
                self.client.add_message(f"  Action Content: {trigger.action_content}", "system", context_name=active_ctx)
                self.client.add_message(f"  Status: {'Enabled' if trigger.is_enabled else 'Disabled'}", "system", context_name=active_ctx)
                self.client.add_message(f"  Created by: {trigger.created_by} at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(trigger.created_at)) if trigger.created_at else 'N/A'}", "system", context_name=active_ctx)
                self.client.add_message(f"  Description: {trigger.description or 'N/A'}", "system", context_name=active_ctx)
            else:
                self.client.add_message(f"Trigger ID {trigger_id} not found.", "error", context_name=active_ctx)

        elif sub_command == "show_usage":
             self.client.add_message("Usage: /on <LIST|ADD|DEL|ENABLE|DISABLE|INFO> [params...]", "error", context_name=active_ctx)
# END OF MODIFIED FILE: features/triggers/trigger_commands.py
