# Implementation Plan: Core User Information and Server Listing Commands

This document outlines the plan to implement the `/who`, `/whowas`, `/list`, and `/names` commands in pyRC.

## Phase 1: Setup and Command Registration

1.  **Create `information_commands_handler.py`:**

    - Create a new file named `information_commands_handler.py`.
    - Define a class `InformationCommandsHandler` within this file.
    - The constructor `__init__(self, client_logic: "IRCClient_Logic")` will store `client_logic`.

2.  **Integrate `InformationCommandsHandler` into `command_handler.py`:**
    - In `command_handler.py`:
      - Import `InformationCommandsHandler`: `from information_commands_handler import InformationCommandsHandler`
      - In `CommandHandler.__init__`, instantiate it: `self.info_commands = InformationCommandsHandler(client_logic)`
      - Add usage strings to `COMMAND_USAGE_STRINGS`:
        ```python
        "who": "Usage: /who <target> - Retrieves WHO information for <target> (nick, channel, mask). Defaults to current channel if active and no target given.",
        "whowas": "Usage: /whowas <nick> [count [target_server]] - Retrieves information about a nickname that is no longer in use.",
        "list": "Usage: /list [pattern] - Lists channels, optionally matching [pattern].",
        "names": "Usage: /names [channel] - Lists users in [channel] or all joined channels if omitted.",
        ```
      - Add command mappings to `command_map`:
        ```python
        "who": self.info_commands.handle_who_command,
        "whowas": self.info_commands.handle_whowas_command,
        "list": self.info_commands.handle_list_command,
        "names": self.info_commands.handle_names_command,
        ```

## Phase 2: Implement Command Logic in `InformationCommandsHandler`

1.  **Implement `handle_who_command(self, args_str: str)`:**

    - Parse `args_str` for `<target>`.
    - If `args_str` is empty:
      - Get current active context using `self.client.context_manager.get_active_context()`.
      - If the active context is a channel (`context.type == "channel"`), use `context.name` as the target.
      - Otherwise, display usage string: `self.client.add_message(self.client.command_handler.COMMAND_USAGE_STRINGS["who"], self.client.ui.colors["error"], context_name="Status")`.
    - If a target is determined, send: `self.client.network.send_raw(f"WHO {target}")`.

2.  **Implement `handle_whowas_command(self, args_str: str)`:**

    - Use `self.client.command_handler._ensure_args(args_str, self.client.command_handler.COMMAND_USAGE_STRINGS["whowas"], num_expected_parts=1)` to ensure `<nick>` is provided.
    - If valid, parse `args_str` for `<nick>`, `[count]`, and `[target_server]`.
    - Construct and send the `WHOWAS` command: `self.client.network.send_raw(f"WHOWAS {nick_arg} {count_arg if count_arg else ''} {target_server_arg if target_server_arg else ''}".strip())`.

3.  **Implement `handle_list_command(self, args_str: str)`:**

    - Parse `args_str` for `[pattern]`.
    - **Temporary Context Creation (Preferred):**
      - Generate a unique context name, e.g., `"Channel List (timestamp)"`.
      - `self.client.context_manager.create_context(list_context_name, context_type="generic", temporary=True)`
      - Store `list_context_name` (e.g., `self.client.active_list_context = list_context_name`) so numeric handlers can target it.
    - Send: `self.client.network.send_raw(f"LIST {args_str if args_str else ''}".strip())`.
    - If temporary context isn't feasible initially, messages will go to "Status".

4.  **Implement `handle_names_command(self, args_str: str)`:**
    - Parse `args_str` for `[channel]`.
    - If `args_str` (channel) is provided:
      - Send: `self.client.network.send_raw(f"NAMES {args_str}")`.
      - Add feedback: `self.client.add_message(f"Refreshing names for {args_str}...", self.client.ui.colors["system"], context_name=args_str if self.client.context_manager.get_context(args_str) else "Status")`.
    - If `args_str` is empty:
      - Send: `self.client.network.send_raw("NAMES")`.

## Phase 3: Implement Numeric Handlers in `irc_numeric_handlers.py`

1.  **General Approach for New Numeric Handlers:**

    - Each handler will take `(client, parsed_msg: IRCMessage, raw_line: str, display_params: list, trailing: Optional[str])`.
    - Messages should generally be added to the "Status" window using `client.add_message(message_string, client.ui.colors["system"], context_name="Status")`, unless specified otherwise (like for `/list`).

2.  **Implement `_handle_rpl_whoreply(client, ...)` (352):**

    - Format and display information from `RPL_WHOREPLY`.
    - Display in "Status".

3.  **Implement `_handle_rpl_endofwho(client, ...)` (315):**

    - Display "End of WHO list" message.
    - Display in "Status".

4.  **Implement `_handle_rpl_whowasuser(client, ...)` (314):**

    - Format and display information from `RPL_WHOWASUSER`.
    - Display in "Status".

5.  **Implement `_handle_rpl_endofwhowas(client, ...)` (369):**

    - Display "End of WHOWAS list" message.
    - Display in "Status".

6.  **Implement `_handle_rpl_liststart(client, ...)` (321):**

    - Target context: `list_context_name` if active, otherwise "Status".
    - Display "Channel List Start" message.

7.  **Implement `_handle_rpl_list(client, ...)` (322):**

    - Target context: `list_context_name` or "Status".
    - Format and display channel, user count, and topic from `RPL_LIST`.

8.  **Implement `_handle_rpl_listend(client, ...)` (323):**

    - Target context: `list_context_name` or "Status".
    - Display "End of channel list" message.
    - If using temporary context, clear `client.active_list_context = None`.

9.  **Update `NUMERIC_HANDLERS` Dictionary:**

    - Add entries for the new handlers:
      ```python
      314: _handle_rpl_whowasuser,
      315: _handle_rpl_endofwho,
      321: _handle_rpl_liststart,
      322: _handle_rpl_list,
      323: _handle_rpl_listend,
      352: _handle_rpl_whoreply,
      369: _handle_rpl_endofwhowas,
      ```

10. **Review Existing `_handle_rpl_namreply` and `_handle_rpl_endofnames`:**
    - Ensure primary logic of updating `Context.users` remains.
    - `_handle_rpl_endofnames` should continue to display user count in the channel context.

## Phase 4: Context Management for `/list` (If Temporary Context is Implemented)

1.  **Modify `context_manager.py` (if full temporary context support is added):**
    - Consider adding a `temporary: bool = False` parameter to `Context.__init__` and `ContextManager.create_context`.
    - Alternatively, manage `client.active_list_context_name: Optional[str]` on `IRCClient_Logic`.

## Visual Plan (Mermaid)

```mermaid
graph TD
    subgraph User Input
        A[User types /who, /whowas, /list, /names] --> B{CommandHandler.process_user_command};
    end

    subgraph Command Handling
        B --> C{command_map};
        C -- /who --> D1[InfoHandler.handle_who_command];
        C -- /whowas --> D2[InfoHandler.handle_whowas_command];
        C -- /list --> D3[InfoHandler.handle_list_command];
        C -- /names --> D4[InfoHandler.handle_names_command];
    end

    subgraph InformationCommandsHandler (information_commands_handler.py)
        D1 --> E1{Parse args, determine target};
        E1 --> F1[client.network.send_raw("WHO ...")];
        D2 --> E2{Parse args};
        E2 --> F2[client.network.send_raw("WHOWAS ...")];
        D3 --> E3{Parse args, create/target ListContext};
        E3 --> F3[client.network.send_raw("LIST ...")];
        D4 --> E4{Parse args};
        E4 --> F4[client.network.send_raw("NAMES ...")];
    end

    subgraph Network Communication
        F1 --> G[IRC Server];
        F2 --> G;
        F3 --> G;
        F4 --> G;
        G -- Numeric Replies --> H{IRCClient_Logic.handle_line};
    end

    subgraph Numeric Reply Handling (irc_numeric_handlers.py)
        H --> I{_handle_numeric_command};
        I -- RPL_WHOREPLY (352) --> J1[_handle_rpl_whoreply];
        I -- RPL_ENDOFWHO (315) --> J2[_handle_rpl_endofwho];
        I -- RPL_WHOWASUSER (314) --> J3[_handle_rpl_whowasuser];
        I -- RPL_ENDOFWHOWAS (369) --> J4[_handle_rpl_endofwhowas];
        I -- RPL_LISTSTART (321) --> J5[_handle_rpl_liststart];
        I -- RPL_LIST (322) --> J6[_handle_rpl_list];
        I -- RPL_LISTEND (323) --> J7[_handle_rpl_listend];
        I -- RPL_NAMREPLY (353) --> J8[_handle_rpl_namreply (existing)];
        I -- RPL_ENDOFNAMES (366) --> J9[_handle_rpl_endofnames (existing)];
    end

    subgraph Output/Display
        J1 --> K[Display in Status Window];
        J2 --> K;
        J3 --> K;
        J4 --> K;
        J5 --> L{Display in ListContext / Status Window};
        J6 --> L;
        J7 --> L;
        J8 --> M[Update Channel User List (UI)];
        J9 --> M;
        J9 -- Also displays user count --> N[Display in Channel Window];
    end

    subgraph Context Management (context_manager.py)
        D3 --> CM1[Create 'List' Context (optional)];
        J5 --> CM2[Target 'List' Context];
        J6 --> CM2;
        J7 --> CM3[Clear/Close 'List' Context (optional)];
    end
```
