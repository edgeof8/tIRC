Of course. `IRCClient_Logic` has become a "God Object," a common anti-pattern where one class knows too much and does too much. It's currently responsible for initialization, the main application loop, state management facades, UI update signaling, trigger processing, and high-level responses to protocol events. This makes it difficult to test and maintain.

Here is a detailed prompt for Roo Code Architect to refactor `IRCClient_Logic` by separating its concerns into more focused, single-responsibility components.

---

**To:** Roo Code Architect
**From:** Lead Architect
**Subject:** Architectural Refactor: Decompose `IRCClient_Logic` God Object

**Context:**
The `IRCClient_Logic` class has grown to be the central monolith of the application. It currently handles application lifecycle, state access, trigger processing, and high-level reactions to IRC events. This violates the Single Responsibility Principle and makes the class unwieldy. Our goal is to refactor `IRCClient_Logic` into a lean orchestrator by extracting its distinct responsibilities into new, specialized classes.

**Objective:**
Decompose `IRCClient_Logic` by extracting its core responsibilities into three new, focused classes:

1.  `TriggerProcessor`: To handle the matching and execution of all user-defined triggers.
2.  `MessageFormatter`: To encapsulate the logic for formatting messages before they are added to a context (line wrapping, timestamping, etc.).
3.  `ClientStateUpdater`: To listen for events and update the client's high-level state in `StateManager` (e.g., tracking the last joined channel, managing auto-switching logic).

This will leave `IRCClient_Logic` with its primary responsibilities: initializing all manager components, holding references to them, and running the main application loop.

**Instructions:**

**Step 1: Create the `TriggerProcessor`**

1.  Create a new file: `pyrc_core/features/triggers/trigger_processor.py`.
2.  Inside this file, define a new class `TriggerProcessor`. It should be initialized with a reference to `IRCClient_Logic`.
3.  Move the methods `process_trigger_event` and `_execute_python_trigger` from `irc_client_logic.py` into the new `TriggerProcessor` class.
4.  In `IRCClient_Logic`, remove the original methods and instantiate `self.trigger_processor = TriggerProcessor(self)` in the `__init__` method.
5.  Update `irc_protocol.py` where `client.process_trigger_event(...)` is called. It should now call `client.trigger_processor.process_trigger_event(...)`.

**Step 2: Create the `MessageFormatter`**

1.  Create a new file: `pyrc_core/client/message_formatter.py`.
2.  Inside this file, define a new class `MessageFormatter`. It should be initialized with a reference to the `AppConfig` and `UIManager` (or `DummyUI`) to get `max_history` and `msg_win_width`.
3.  In `IRCClient_Logic`, find the message formatting logic inside the `add_message` method (timestamp prefixing, line wrapping).
4.  Move this logic into a new public method in `MessageFormatter` called `format(self, text: str, prefix_time: bool) -> List[str]`. This method will take the raw text and return a list of formatted, wrapped lines.
5.  In `IRCClient_Logic`, instantiate `self.message_formatter = MessageFormatter(self.config, self.ui)` in the `__init__` method.
6.  Refactor `IRCClient_Logic.add_message` to use this new component. It should now:
    a. Check for ignored sources.
    b. Call `self.message_formatter.format(...)` to get the prepared lines.
    c. Loop through the returned lines and call `self.context_manager.add_message_to_context(...)` for each one.
    d. Handle logging and unread counts as before.

**Step 3: Create the `ClientStateUpdater`**

This is the most critical step for decoupling. This class will handle how the client's state reacts to events.

1.  Create a new file: `pyrc_core/client/client_state_updater.py`.
2.  Define a new class `ClientStateUpdater`. It should be initialized with references to `IRCClient_Logic`, `StateManager`, and `ContextManager`.
3.  In `IRCClient_Logic`, instantiate `self.client_state_updater = ClientStateUpdater(self, self.state_manager, self.context_manager)` in the `__init__` method.
4.  Identify logic in `IRCClient_Logic` that reacts to events and move it into the `ClientStateUpdater`. Create public methods in `ClientStateUpdater` for each event it handles.
    - **Target 1:** The `handle_channel_fully_joined` method. Move its entire logic into a new method in `ClientStateUpdater` called `on_channel_fully_joined(self, channel_name: str)`. This new method will access `self.client_logic_ref` when it needs to call `set_active_context` or access `last_join_command_target`.
    - **Target 2:** The `last_join_command_target` attribute. Move this attribute from `IRCClient_Logic` to `ClientStateUpdater`. The `/join` command handler (`join_command.py`) will now need to set this attribute via `client.client_state_updater.last_join_command_target`.
5.  Update the call sites:
    - In `irc_numeric_handlers.py`, the `_handle_rpl_endofnames` function calls `client.handle_channel_fully_joined(channel_ended)`. Change this to `client.client_state_updater.on_channel_fully_joined(channel_ended)`.
    - In `join_command.py`, change `client.last_join_command_target = ...` to `client.client_state_updater.last_join_command_target = ...`.

**Step 4: Final Cleanup of `IRCClient_Logic`**

1.  After the extractions above, review `irc_client_logic.py`.
2.  Its responsibilities should now be strictly limited to:
    - Initializing all manager/handler components.
    - Holding references to these components.
    - Running the main `async` application loop (`run_main_loop`).
    - Providing high-level state properties (`nick`, `server`, etc.) that read from `StateManager`.
    - Providing the core `add_message` method (which now delegates formatting).
    - Handling basic text input by delegating to `CommandHandler` or `handle_text_input`.
3.  Ensure no business logic remains that could be housed in a more appropriate, specialized class.

**Desired Outcome:**
`IRCClient_Logic` will be significantly leaner and act as a true orchestrator. The application's logic will be more cleanly separated: `TriggerProcessor` handles triggers, `MessageFormatter` handles text presentation, and `ClientStateUpdater` handles high-level state changes in response to IRC events. This will make the system more modular, testable, and easier to understand.

**File Paths to Modify:**

- `pyrc_core/client/irc_client_logic.py` (major reduction)
- `pyrc_core/irc/irc_protocol.py` (update calls)
- `pyrc_core/irc/handlers/irc_numeric_handlers.py` (update calls)
- `pyrc_core/commands/channel/join_command.py` (update attribute access)
- **New File:** `pyrc_core/features/triggers/trigger_processor.py`
- **New File:** `pyrc_core/client/message_formatter.py`
- **New File:** `pyrc_core/client/client_state_updater.py`
