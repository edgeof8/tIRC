# START OF MODIFIED FILE: features/triggers/trigger_commands.py
import logging
import time
from typing import TYPE_CHECKING, List, Optional, Dict, Any

if TYPE_CHECKING:
    from tirc_core.client.irc_client_logic import IRCClient_Logic

logger = logging.getLogger("tirc.features.triggers.commands")

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

        return {
            "sub_command": "add",
            "event_type": event_type,
            "pattern": pattern,
            "action_type": action_type_str, # Pass as string, TriggerManager will convert
            "action_content": action_content,
        }


    async def handle_on_command(self, args_str: str):
        if not self.client.trigger_manager:
            active_ctx = self.client.context_manager.active_context_name or "Status"
            await self.client.add_message("Trigger system is not enabled or available.",
                self.client.ui.colors.get("error", 0),
                context_name=active_ctx)
            return

        parsed_args = self._parse_on_args(args_str)
        active_ctx = self.client.context_manager.active_context_name or "Status"

        if parsed_args is None:
            await self.client.add_message("Usage: /on <LIST|ADD|DEL|ENABLE|DISABLE|INFO> [params...]",
                self.client.ui.colors.get("error", 0),
                context_name=active_ctx)
            await self.client.add_message("  /on ADD <EVENT> <pattern> <CMD|PY> <action_content/code>",
                self.client.ui.colors.get("error", 0),
                context_name=active_ctx)
            await self.client.add_message("  Example: /on TEXT \"hello world\" CMD /say Hello back!",
                self.client.ui.colors.get("error", 0),
                context_name=active_ctx)
            await self.client.add_message("  Example: /on RAW \"PRIVMSG #chan :hi\" PY print(event_data['nick'] + ' said hi')",
                self.client.ui.colors.get("error", 0),
                context_name=active_ctx)
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
                await self.client.add_message(
                    f"Trigger added with ID: {trigger_id}",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
            else:
                await self.client.add_message(
                    "Failed to add trigger. Check pattern or action type.",
                    self.client.ui.colors.get("error", 0),
                    context_name=active_ctx)

        elif sub_command == "list":
            event_filter = parsed_args.get("event_filter")
            triggers = self.client.trigger_manager.list_triggers(event_type=event_filter)
            if triggers:
                await self.client.add_message(
                    f"--- Configured Triggers ({event_filter or 'All'}) ---",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
                for t in triggers:
                    enabled_str = "Enabled" if t['is_enabled'] else "Disabled"
                    action_preview = t['action_content'][:50] + "..." if len(t['action_content']) > 50 else t['action_content']
                    await self.client.add_message(
                        f"ID: {t['id']}, Event: {t['event_type']}, Pattern: '{t['pattern']}', Action: {t['action_type']} '{action_preview}', Status: {enabled_str}",
                        self.client.ui.colors.get("system", 0),
                        context_name=active_ctx
                    )
            else:
                await self.client.add_message(
                    f"No triggers configured{(' for event ' + event_filter) if event_filter else ''}.",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)

        elif sub_command == "delete":
            trigger_id = parsed_args["trigger_id"]
            if self.client.trigger_manager.remove_trigger(trigger_id):
                await self.client.add_message(
                    f"Trigger {trigger_id} removed.",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
            else:
                await self.client.add_message(
                    f"Failed to remove trigger {trigger_id}. Not found?",
                    self.client.ui.colors.get("error", 0),
                    context_name=active_ctx)

        elif sub_command == "enable" or sub_command == "disable":
            trigger_id = parsed_args["trigger_id"]
            should_enable = sub_command == "enable"
            if self.client.trigger_manager.set_trigger_enabled(trigger_id, should_enable):
                await self.client.add_message(
                    f"Trigger {trigger_id} {'enabled' if should_enable else 'disabled'}.",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
            else:
                await self.client.add_message(
                    f"Failed to update trigger {trigger_id}. Not found?",
                    self.client.ui.colors.get("error", 0),
                    context_name=active_ctx)

        elif sub_command == "info":
            trigger_id = parsed_args["trigger_id"]
            trigger = self.client.trigger_manager.get_trigger(trigger_id)
            if trigger:
                await self.client.add_message(
                    f"--- Trigger Info (ID: {trigger.id}) ---",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
                await self.client.add_message(
                    f"  Event Type: {trigger.event_type}",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
                await self.client.add_message(
                    f"  Pattern: '{trigger.pattern}' (Regex: {trigger.is_regex}, IgnoreCase: {trigger.ignore_case})",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
                await self.client.add_message(
                    f"  Action Type: {trigger.action_type.name}",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
                await self.client.add_message(
                    f"  Action Content: {trigger.action_content}",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
                await self.client.add_message(
                    f"  Status: {'Enabled' if trigger.is_enabled else 'Disabled'}",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
                await self.client.add_message(
                    f"  Created by: {trigger.created_by} at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(trigger.created_at)) if trigger.created_at else 'N/A'}",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
                await self.client.add_message(
                    f"  Description: {trigger.description or 'N/A'}",
                    self.client.ui.colors.get("system", 0),
                    context_name=active_ctx)
            else:
                await self.client.add_message(
                    f"Trigger ID {trigger_id} not found.",
                    self.client.ui.colors.get("error", 0),
                    context_name=active_ctx)

        elif sub_command == "show_usage":
             await self.client.add_message(
                 "Usage: /on <LIST|ADD|DEL|ENABLE|DISABLE|INFO> [params...]",
                 self.client.ui.colors.get("error", 0),
                 context_name=active_ctx)
# END OF MODIFIED FILE: features/triggers/trigger_commands.py
