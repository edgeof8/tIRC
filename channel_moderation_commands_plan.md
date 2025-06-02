# Plan: Implement Core Channel Moderation Commands

**Source:** User feedback comparing PyRC to irssi, WeeChat, etc.
**Goal:** Add essential channel moderation commands to allow users (with appropriate channel privileges) to manage bans, channel modes, and user statuses (op/voice).

## I. Project Setup & Goals

- **Goal:** Add `/ban`, `/unban`, `/mode`, `/op`, `/deop`, `/voice`, and `/devoice` commands.
- **Key Files to Modify:**
  - `command_handler.py`: For command registration and usage strings.
  - `channel_commands_handler.py`: For implementing the logic of these new commands.
- **Supporting Files (for understanding interactions, likely no direct changes for core command logic unless bugs are found):**
  - `network_handler.py`: Handles `send_raw()`.
  - `irc_protocol.py`: Handles incoming `MODE` messages and updates user prefixes via `ContextManager`.
  - `context_manager.py`: Manages channel/user state, including user prefixes.
  - `ui_manager.py`: Displays user lists with prefixes from `ContextManager`.

## II. Detailed Plan Diagram

```mermaid
graph TD
    A[Start: Implement Moderation Commands] --> B{Modify command_handler.py};
    B --> B1[Add new commands/aliases to command_map];
    B --> B2[Add usage strings to COMMAND_USAGE_STRINGS];
    B --> C{Modify channel_commands_handler.py};
    C --> C1[Implement handle_ban_command];
    C --> C2[Implement handle_unban_command];
    C --> C3[Implement handle_mode_command];
    C3 --> C3a[Parse <target> and <modes_and_params>];
    C3 --> C3b[Handle active channel context if target is omitted];
    C3 --> C3c[Construct MODE <target> <modes_and_params>];
    C --> C4[Implement handle_op_command (alias /o)];
    C --> C5[Implement handle_deop_command (alias /do)];
    C --> C6[Implement handle_voice_command (alias /v)];
    C --> C7[Implement handle_devoice_command (alias /dv)];
    C1 --> D{Common Handler Logic};
    C2 --> D;
    C3b --> D;
    C4 --> D;
    C5 --> D;
    C6 --> D;
    C7 --> D;
    D --> D1[Get active channel from ContextManager];
    D --> D2[Error handling for incorrect context];
    D --> D3[Construct raw IRC MODE command];
    D --> D4[Send command via NetworkHandler.send_raw()];
    D --> D5[Provide user feedback via Client.add_message()];
    D4 --> E[NetworkHandler sends to IRC Server];
    E --> F[IRC Server processes MODE];
    F --> G{IRC Server sends MODE back (if applicable)};
    G --> H{irc_protocol.py _handle_mode_message};
    H --> H1[Parse incoming MODE];
    H1 --> H2[Update ContextManager.users prefixes (for @, +)];
    H2 --> I{ui_manager.py draw_sidebar};
    I --> I1[Read user prefixes from ContextManager];
    I1 --> J[User list in UI reflects new op/voice status];
    D5 --> K[User sees command feedback in message window];
    J --> L[End: Moderation Commands Implemented];
    K --> L;

    subgraph Command Registration
        B1
        B2
    end

    subgraph Command Logic Implementation
        C1
        C2
        C3
        C4
        C5
        C6
        C7
        C3a
        C3c
    end

    subgraph Common Command Steps
        D1
        D2
        D3
        D4
        D5
    end

    subgraph IRC Communication & Response
        E
        F
        G
    end

    subgraph UI Update Path (for prefixes)
        H
        H1
        H2
        I
        I1
        J
    end
```

## III. Step-by-Step Implementation Details

1.  **Modify `command_handler.py`:**

    - **`COMMAND_USAGE_STRINGS`:** Add entries for:
      - `ban`: "Usage: /ban <nick|hostmask> - Bans the user/hostmask from the current channel."
      - `unban`: "Usage: /unban <hostmask> - Unbans the hostmask from the current channel."
      - `mode`: "Usage: /mode [<target>] <modes_and_params> - Sets modes. Target is current channel if omitted."
      - `op`: "Usage: /op <nick> (alias: /o) - Ops <nick> in the current channel."
      - `deop`: "Usage: /deop <nick> (alias: /do) - De-ops <nick> in the current channel."
      - `voice`: "Usage: /voice <nick> (alias: /v) - Voices <nick> in the current channel."
      - `devoice`: "Usage: /devoice <nick> (alias: /dv) - De-voices <nick> in the current channel."
    - **`command_map`:** Add entries pointing to new methods in `ChannelCommandsHandler`:
      - `"ban": self.channel_commands.handle_ban_command`
      - `"unban": self.channel_commands.handle_unban_command`
      - `"mode": self.channel_commands.handle_mode_command`
      - `"op": self.channel_commands.handle_op_command`
      - `"o": self.channel_commands.handle_op_command`
      - `"deop": self.channel_commands.handle_deop_command`
      - `"do": self.channel_commands.handle_deop_command`
      - `"voice": self.channel_commands.handle_voice_command`
      - `"v": self.channel_commands.handle_voice_command`
      - `"devoice": self.channel_commands.handle_devoice_command`
      - `"dv": self.channel_commands.handle_devoice_command`

2.  **Modify `channel_commands_handler.py`:**

    - Create the new handler methods (e.g., `handle_ban_command(self, args_str: str)`).
    - **Common Logic for most handlers (ban, unban, op, deop, voice, devoice):**

      - Get active channel:
        ```python
        active_ctx = self.client.context_manager.get_active_context()
        if not active_ctx or active_ctx.type != "channel":
            self.client.add_message("This command can only be used in a channel.", self.client.ui.colors["error"], context_name="Status")
            return
        channel_name = active_ctx.name
        ```
      - Parse arguments (e.g., for `/ban <nick_or_hostmask>`):
        ```python
        parts = self.client.command_handler._ensure_args(args_str, self.client.command_handler.COMMAND_USAGE_STRINGS["ban"])
        if not parts:
            return
        target_spec = parts[0]
        ```
      - Construct and send IRC command:
        - `/ban`: `self.client.network.send_raw(f"MODE {channel_name} +b {target_spec}")`
        - `/unban`: `self.client.network.send_raw(f"MODE {channel_name} -b {target_spec}")`
        - `/op`: `self.client.network.send_raw(f"MODE {channel_name} +o {nick}")`
        - `/deop`: `self.client.network.send_raw(f"MODE {channel_name} -o {nick}")`
        - `/voice`: `self.client.network.send_raw(f"MODE {channel_name} +v {nick}")`
        - `/devoice`: `self.client.network.send_raw(f"MODE {channel_name} -v {nick}")`
      - Provide feedback:
        - e.g., `self.client.add_message(f"Banning {target_spec} from {channel_name}...", self.client.ui.colors["system"], context_name=channel_name)`

    - **Specific Logic for `handle_mode_command(self, args_str: str)`:**
      - Parse arguments: `args_str` will contain `[<target>] <modes_and_params>`.
      - Determine target:
        - If the first part of `args_str` is a channel name (starts with `#`, `&`, etc.) or a nick (and not a mode string like `+o`), use that as the target.
        - Otherwise, if the active context is a channel, use `active_ctx.name` as the target.
        - If no target can be determined and the active context isn't a channel, show usage from `COMMAND_USAGE_STRINGS["mode"]`.
      - Extract `modes_and_params` string.
      - Send: `self.client.network.send_raw(f"MODE {target} {modes_and_params}")`
      - Feedback: `self.client.add_message(f"Setting mode {modes_and_params} on {target}...", self.client.ui.colors["system"], context_name=target_context_for_feedback)`
      - The client sends the raw mode string as entered by the user; server-side parsing is assumed for the mode string's details.

3.  **UI Updates & Context Management:**
    - Incoming `MODE` messages affecting user prefixes (`+o`, `+v`, etc.) are handled by `_handle_mode_message` in `irc_protocol.py`, which updates `ContextManager`.
    - `ui_manager.py` reads these prefixes from `ContextManager` when drawing the sidebar.
    - No direct changes to `irc_protocol.py` or `ui_manager.py` are anticipated for the _display_ of user prefixes due to these new commands, as the existing infrastructure should handle it.
    - Feedback messages sent via `self.client.add_message()` will appear in the relevant message window.

## IV. Testing Considerations

- Test each command individually in various scenarios:
  - Correct usage.
  - Insufficient arguments.
  - Using channel-specific commands outside a channel.
  - Targeting self vs. others.
  - Using aliases.
- Verify user feedback messages are displayed correctly.
- Verify user list prefixes update correctly for `/op`, `/deop`, `/voice`, `/devoice`.
- Test the `/mode` command with various mode strings and parameters (e.g., `+o nick`, `-v nick`, `+imnt`, `+b hostmask`, `-k key`).
