# PyRC Project Refactoring Plan

**Objective:** Reorganize the PyRC project structure for improved modularity and scalability by moving core logic into a main `pyrc_core` package.

## Phase 1: Initial Structure and Configuration File

1.  **Create Directories & Packages:**

    - Create the directory `pyrc_core/`.
    - Create `pyrc_core/__init__.py` with content: `# Makes pyrc_core a package`
    - Create the directory `pyrc_core/client/`.
    - Create `pyrc_core/client/__init__.py` with content: `# Client package`
    - Create the directory `pyrc_core/irc/`.
    - Create `pyrc_core/irc/__init__.py` with content: `# IRC protocol package`
    - Create the directory `pyrc_core/irc/handlers/`.
    - Create `pyrc_core/irc/handlers/__init__.py` with content: `# IRC message handlers`
    - Create the directory `pyrc_core/commands/`.
    - Create `pyrc_core/commands/__init__.py` with content: `# Commands package`
    - Create the directory `pyrc_core/dcc/`.
    - Create `pyrc_core/dcc/__init__.py` with content: `# DCC package`
    - Create the directory `pyrc_core/scripting/`.
    - Create `pyrc_core/scripting/__init__.py` with content: `# Scripting package`
    - Create the directory `pyrc_core/features/`.
    - Create `pyrc_core/features/__init__.py` with content: `# Features package`
    - Create the directory `pyrc_core/features/triggers/`. (This involves moving the existing `features/triggers/` directory here).
    - Create/ensure `pyrc_core/features/triggers/__init__.py` exists with content: `# Triggers feature package`
    - Create the directory `pyrc_core/utils/`.
    - Create `pyrc_core/utils/__init__.py` with content: `# Utilities package`

2.  **Relocate and Modify `config.py`:**

    - Move the existing `config.py` from the project root to `pyrc_core/app_config.py`.
    - In the new `pyrc_core/app_config.py`, modify the line that defines `BASE_DIR`.
      - **Current line (approx. line 126 in original `config.py`):**
        `BASE_DIR = os.path.dirname(os.path.abspath(__file__))`
      - **Change to:**
        `BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

3.  **Delete Original `config.py`:**
    - After confirming `pyrc_core/app_config.py` is correctly in place and modified, delete the original `config.py` file from the project root.

## Phase 2: Move Remaining Files

Relocate the following files from their current locations (mostly project root) to the new paths within `pyrc_core/`:

- `irc_client_logic.py` &rarr; `pyrc_core/client/irc_client_logic.py`
- `input_handler.py` &rarr; `pyrc_core/client/input_handler.py`
- `ui_manager.py` &rarr; `pyrc_core/client/ui_manager.py`
- `irc_message.py` &rarr; `pyrc_core/irc/irc_message.py`
- `irc_protocol.py` &rarr; `pyrc_core/irc/irc_protocol.py`
- `cap_negotiator.py` &rarr; `pyrc_core/irc/cap_negotiator.py`
- `sasl_authenticator.py` &rarr; `pyrc_core/irc/sasl_authenticator.py`
- `registration_handler.py` &rarr; `pyrc_core/irc/registration_handler.py`
- `irc_numeric_handlers.py` &rarr; `pyrc_core/irc/handlers/irc_numeric_handlers.py`
- `message_handlers.py` &rarr; `pyrc_core/irc/handlers/message_handlers.py`
- `membership_handlers.py` &rarr; `pyrc_core/irc/handlers/membership_handlers.py`
- `state_change_handlers.py` &rarr; `pyrc_core/irc/handlers/state_change_handlers.py`
- `protocol_flow_handlers.py` &rarr; `pyrc_core/irc/handlers/protocol_flow_handlers.py`
- The entire `commands/` directory &rarr; `pyrc_core/commands/` (The `__init__.py` for this new location is covered in Phase 1).
- `command_handler.py` &rarr; `pyrc_core/commands/command_handler.py`
- `dcc_manager.py` &rarr; `pyrc_core/dcc/dcc_manager.py`
- `dcc_transfer.py` &rarr; `pyrc_core/dcc/dcc_transfer.py`
- `dcc_protocol.py` &rarr; `pyrc_core/dcc/dcc_protocol.py`
- `dcc_security.py` &rarr; `pyrc_core/dcc/dcc_security.py`
- `dcc_ctcp_handler.py` &rarr; `pyrc_core/dcc/dcc_ctcp_handler.py`
- `dcc_send_manager.py` &rarr; `pyrc_core/dcc/dcc_send_manager.py`
- `dcc_passive_offer_manager.py` &rarr; `pyrc_core/dcc/dcc_passive_offer_manager.py`
- `script_manager.py` &rarr; `pyrc_core/scripting/script_manager.py`
- `script_api_handler.py` &rarr; `pyrc_core/scripting/script_api_handler.py`
- `script_base.py` &rarr; `pyrc_core/scripting/script_base.py`
- `python_trigger_api.py` &rarr; `pyrc_core/scripting/python_trigger_api.py`
- The entire existing `features/triggers/` directory &rarr; `pyrc_core/features/triggers/` (The `__init__.py` files for `pyrc_core/features/` and `pyrc_core/features/triggers/` are covered in Phase 1).
  - This includes `trigger_manager.py` and `trigger_commands.py` moving to `pyrc_core/features/triggers/`.
- `context_manager.py` &rarr; `pyrc_core/context_manager.py`
- `event_manager.py` &rarr; `pyrc_core/event_manager.py`
- `network_handler.py` &rarr; `pyrc_core/network_handler.py`
- `state_manager.py` &rarr; `pyrc_core/state_manager.py`

## Phase 3: Update Import Statements

This is the most extensive part of the refactor.

- Systematically go through **ALL** Python files in the project (including all files moved into `pyrc_core/`, `scripts/*.py`, `tests/*.py`, and the main `pyrc.py`).
- Update all `import` statements to reflect the new module paths.
  - Example: `from irc_message import IRCMessage` will become `from pyrc_core.irc.irc_message import IRCMessage`.
  - Example: `from commands.core.help_command import ...` will become `from pyrc_core.commands.core.help_command import ...`.
  - Relative imports within `pyrc_core` sub-packages might also be appropriate (e.g., `from .irc_message import IRCMessage` if importing from another file within `pyrc_core/irc/`).

## Phase 4: Adjust Entry Points and Test Scripts

1.  **Update `pyrc.py` (Main Entry Point):**

    - Modify `pyrc.py` to correctly import `IRCClient_Logic` from its new location (e.g., `from pyrc_core.client.irc_client_logic import IRCClient_Logic`).
    - Ensure `pyrc.py` correctly sets up `sys.path` if needed when running from source. If `pyrc.py` is in the project root and `pyrc_core` is a direct subdirectory, Python should find `pyrc_core` automatically for direct imports.

2.  **Update `scripts/run_headless_tests.py`:**
    - Update its import statements to reflect the new locations of modules within `pyrc_core`.
    - Adjust any `sys.path` manipulation if it was previously adding the project root. It should still ensure the project root (parent of `pyrc_core`) is in `sys.path` so that `import pyrc_core` works.

## Phase 5: Testing

- Thoroughly test all aspects of the PyRC client:
  - Connection to servers (SSL and non-SSL).
  - Channel joins, parts, messages.
  - All implemented commands.
  - DCC functionality.
  - Scripting system and triggers.
  - Logging.
  - Configuration loading and saving.
  - Headless mode tests.

This detailed plan should guide the implementation in "Code" mode.
