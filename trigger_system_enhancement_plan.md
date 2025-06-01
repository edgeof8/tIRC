# Trigger System Enhancement Plan: Python Execution and Regex Captures

This document outlines the plan to enhance the pyRC trigger system by adding Python code execution capabilities and allowing the use of regex capture groups as variables within trigger actions.

## Affected Files (Likely)

- [`features/triggers/trigger_manager.py`](features/triggers/trigger_manager.py:1)
- [`features/triggers/trigger_commands.py`](features/triggers/trigger_commands.py:1)
- [`irc_client_logic.py`](irc_client_logic.py:1)
- [`README.md`](README.md:1)

## Phase 1: Core Trigger Logic Enhancements (in `features/triggers/trigger_manager.py`)

1.  **Introduce `ActionType` Enum:**
    - Define an enum `ActionType` with values `COMMAND` (for existing behavior) and `PYTHON` (for the new Python code execution).
2.  **Update `Trigger` Dataclass:**
    - Add an `action_type: ActionType` field to store whether the trigger action is a client command or Python code.
    - The existing `action: str` field will store either the command string or the Python code snippet.
3.  **Modify `TriggerManager.add_trigger()`:**
    - Update the method to accept an `action_type` (e.g., "CMD" or "PY") and the `action_content`.
    - Store these appropriately in the new `Trigger` object.
4.  **Update Persistence (`save_triggers`, `load_triggers`):**
    - Modify these methods to save and load the new `action_type` field for each trigger. This will likely involve serializing the enum as a string (e.g., "PYTHON") in `triggers.json`.
    - Ensure backward compatibility for older `triggers.json` files that don't have this field (defaulting them to `COMMAND`).
5.  **Enhance `TriggerManager.process_trigger()`:**
    - When a regex pattern matches, capture the `re.match` object.
    - This method will now determine if the action is `COMMAND` or `PYTHON`.
    - It will return a dictionary specifying the `type` (COMMAND/PYTHON), the `content` (command string or Python code), and a new `event_data` dictionary.
6.  **Create `_prepare_event_data()` Helper Method:**
    - This new private method will be responsible for creating the `event_data` dictionary.
    - It will populate this dictionary with standard variables (`$nick`, `$channel`, `$msg`, etc.) and the new regex capture group variables (`$0` for the full match, `$1` for the first group, `$2` for the second, and so on, derived from the `re.match` object).
7.  **Create `_perform_string_substitutions()` Helper Method:**
    - This method will take an action string (for `COMMAND` type triggers) and the `event_data` dictionary, and perform the variable substitutions (e.g., replacing `$nick` with the actual nickname).
8.  **Revised `TriggerManager.process_trigger()` Logic:**
    - If `trigger.action_type` is `COMMAND`:
      - Call `_prepare_event_data()` to get all variables.
      - Call `_perform_string_substitutions()` to get the final command string.
      - Return `{"type": ActionType.COMMAND, "content": final_command_string}`.
    - If `trigger.action_type` is `PYTHON`:
      - Call `_prepare_event_data()` to get all variables (including regex captures).
      - Return `{"type": ActionType.PYTHON, "code": trigger.action, "event_data": prepared_event_data_dict}`. The raw Python code is returned, as substitutions will occur via the `event_data` dictionary in the execution scope.

## Phase 2: User Command Interface (in `features/triggers/trigger_commands.py`)

1.  **Update `/on add` Command (`_handle_add`):**
    - Modify the syntax to: `/on add <event> <pattern> <TYPE> <action_content>`
      - `<TYPE>` will be either `CMD` or `PY`.
    - Parse these arguments and pass them to the updated `trigger_manager.add_trigger()`.
2.  **Update Help Message (`_show_usage`):**
    - Reflect the new `/on add` syntax and explain the `CMD` and `PY` action types.
3.  **Update Trigger Listing (`_handle_list`):**
    - Display the `action_type` (CMD/PY) for each trigger in the list.

## Phase 3: Python Code Execution (in `irc_client_logic.py`)

1.  **Adapt `IRCClient_Logic.process_trigger_event()`:**
    - This method calls `trigger_manager.process_trigger()`. It will now receive the dictionary structure described in Phase 1.5.
    - If the result type is `COMMAND`, it should proceed as it (presumably) currently does with the command string.
    - If the result type is `PYTHON`, it should call a new method, `execute_python_trigger()`, passing the Python code and the `event_data` dictionary.
2.  **Implement `IRCClient_Logic.execute_python_trigger(code: str, event_data: Dict[str, Any])`:**
    - **Execution Context:**
      - Prepare a limited execution scope for `exec()`.
      - `globals_for_exec = {}`
      - `locals_for_exec = { "client": self, "event_data": event_data }`
        - `client`: Provides access to client functionalities like `self.add_message()`, `self.send_raw()`. (Initially `self`, but a safer proxy object could be a future refinement).
        - `event_data`: The dictionary prepared by `TriggerManager`, containing `$nick`, `$channel`, `$msg`, and regex captures like `$0`, `$1`, etc. Python code will access these like `event_data['$1']`.
    - **Execution:**
      - Use `exec(code, globals_for_exec, locals_for_exec)` to run the Python snippet.
    - **Error Handling:**
      - Wrap the `exec()` call in a `try...except Exception as e:` block.
      - Log any exceptions.
      - Display a user-friendly error message in the IRC client (e.g., via `self.add_message()`) indicating that the Python trigger failed and why.

## Phase 4: Documentation and Safety

1.  **Update `README.md`:**
    - Document the new `/on add ... PY ...` syntax.
    - Detail the structure of the `event_data` dictionary available to Python scripts, including the regex capture variables.
    - Provide clear examples of `PY` triggers.
    - **Crucially, include a prominent security warning about the risks of executing arbitrary Python code via triggers.** Advise users to only use code from trusted sources or written by themselves.
2.  **Update In-Client Help:**
    - Ensure the `/on help` output (managed by `TriggerCommands._show_usage`) is comprehensive.

## Visual Flow Diagram

```mermaid
graph TD
    subgraph UserInput
        A[/on add TEXT "pattern" PY "code"] --> B{TriggerCommands};
    end

    B -- Parses & calls add_trigger --> C{TriggerManager};
    C -- Stores Trigger (type=PY, pattern, code) --> D[triggers.json];

    subgraph EventProcessing
        E[IRC Event (e.g., PRIVMSG)] --> F{IRCClient_Logic};
        F -- Calls process_trigger_event --> F_sub[process_trigger_event];
        F_sub -- Gets matching triggers --> C;
        C -- Finds PY trigger, prepares event_data (with $0, $1...) --> C_sub[process_trigger method];
        C_sub -- Returns {type: PY, code, event_data} --> F_sub;
        F_sub -- Identifies PY trigger --> F_exe[execute_python_trigger];
        F_exe -- exec(code, {client, event_data}) --> I[Python Code Execution];
        I -- Interacts (e.g., client.add_message via 'client' object) --> F;
        I -- Errors --> J[Error Displayed to User via client.add_message];
    end

    K[README.md / Help] -- Updated --> L[User];

    classDef user fill:#E6E6FA,stroke:#333,stroke-width:2px;
    classDef systemcomponent fill:#D5F5E3,stroke:#333,stroke-width:2px;
    classDef datastore fill:#FDEBD0,stroke:#333,stroke-width:2px;
    classDef process fill:#EBF5FB,stroke:#333,stroke-width:2px;

    class A,L user;
    class B,C,C_sub,F,F_sub,F_exe systemcomponent;
    class D datastore;
    class E,I,J,K process;
```
