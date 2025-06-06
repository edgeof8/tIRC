# PyRC Project Rationalization Plan

## Analysis and Rationalization Plan

The core of the rationalization focuses on centralizing configuration and runtime state, streamlining `IRCClient_Logic` initialization, improving command loading, and refining DCC command handling.

### 1. Centralize Configuration Management

- **Problem:** Configuration values are scattered across global variables in `app_config.py` and reloaded by a brittle function.
- **Solution:** Introduce a single, injectable `AppConfig` class. `IRCClient_Logic` will own this instance, and other components will receive configuration explicitly, eliminating global variables and the `reload_all_config_values` function.

### 2. Enforce `StateManager` as the Single Source of Truth

- **Problem:** Runtime state attributes (e.g., `self.nick`, `self.server`) are directly held in `IRCClient_Logic` and other modules, leading to inconsistencies.
- **Solution:** Make `StateManager` the _exclusive_ source of truth for connection and session state. All state access and modification will occur via the `StateManager` instance.

### 3. Streamline `IRCClient_Logic` Initialization

- **Problem:** The `__init__` method in `irc_client_logic.py` is overly complex, handling argument parsing and initial state determination.
- **Solution:** Simplify `__init__` to focus on manager instantiation. A new private helper method, `_create_initial_state`, will handle parsing CLI arguments and config to set the initial `ConnectionInfo` in the `StateManager`.

### 4. Refactor Dynamic Command Loading

- **Problem:** `command_handler.py` uses `os.walk` for command discovery, which is platform-dependent and fragile.
- **Solution:** Replace `os.walk` with Python's more robust `pkgutil.walk_packages` for module discovery within the `pyrc_core.commands` package.

### 5. Simplify DCC Command Handling

- **Problem:** DCC commands are handled by a separate, parallel system in `dcc_commands.py` that instantiates handler classes.
- **Solution:** Simplify the `dcc_commands.py` dispatcher to act as a router that directly calls appropriate functions, aligning it more closely with how other commands are handled.

---

## Prompt for Roo Code

Here is a detailed, structured prompt to provide to the coding assistant to execute this plan.

**ROLE**
You are an expert Python software architect specializing in refactoring and improving application architecture. Your task is to analyze the provided PyRC IRC client codebase, identify areas of architectural drift, and refactor the code to be more robust, maintainable, and consistent with its stated design goals.

**CONTEXT**
The provided project is PyRC, a terminal-based IRC client. It has a well-defined architecture described in its `README.md`, emphasizing modularity and a centralized `StateManager`. However, the implementation has drifted from these principles, particularly in configuration and state management. Your goal is to refactor the code to realign it with its excellent architectural vision.

**TASK**
Perform a comprehensive refactoring of the PyRC codebase according to the following step-by-step plan. You must modify all relevant files to implement these changes while ensuring all existing functionality remains intact.

**Step 1: Centralize Configuration Management**

1.  **Create a dedicated `AppConfig` class in `pyrc_core/app_config.py`.** This class will be responsible for loading and holding all configuration values from the `.ini` file. It should parse the config file in its `__init__` method.
2.  **Remove all module-level global configuration variables** from `app_config.py` (e.g., `IRC_SERVER`, `LOG_ENABLED`, `DCC_MAX_FILE_SIZE`, etc.). The only globals remaining should be default constants (like `DEFAULT_SERVER`, `DEFAULT_LOG_LEVEL`) and the `config` parser instance itself.
3.  **Refactor `IRCClient_Logic`** to create and hold a single instance of this new `AppConfig` class.
4.  **Update all modules** that previously imported globals from `app_config`. They should now receive the necessary configuration values from the `IRCClient_Logic` instance or its managers, which get them from the central `AppConfig` object. For example, `DCCManager`'s `__init__` should take the config object or a dictionary of DCC settings from `IRCClient_Logic`.
5.  **Eliminate the `reload_all_config_values` function.** The `/rehash` command should now simply tell `IRCClient_Logic` to create a _new_ `AppConfig` instance and re-distribute the necessary values to its components.

**Step 2: Enforce `StateManager` as the Single Source of Truth**

1.  **Eliminate direct state attributes in `IRCClient_Logic`.** Remove attributes like `self.nick`, `self.server`, `self.port`, `self.use_ssl`, `self.currently_joined_channels`, `self.last_attempted_nick_change`, etc.
2.  **Refactor all code** (in `IRCClient_Logic`, command handlers, network handlers, etc.) to access this state _exclusively_ through the `StateManager` instance (`self.client.state_manager`).
    - **Example:** A call to `client.nick` should become `client.state_manager.get_connection_info().nick`.
    - **Example:** A check `if client.network_handler.connected:` should be `if client.state_manager.get_connection_state() == ConnectionState.CONNECTED:`.
3.  **Update `StateChangeUIHandler`** to handle more state transitions (like `connection_info` changes) and update the UI accordingly, ensuring the status bar always reflects the true state from the `StateManager`.
4.  Use the `StateManager` to track all aspects of the connection lifecycle, including pending server switches for the `/server` command.

**Step 3: Streamline `IRCClient_Logic` Initialization**

1.  **Simplify the `IRCClient_Logic.__init__` method.** Its primary role should be to instantiate its manager components (`StateManager`, `AppConfig`, `ContextManager`, etc.).
2.  **Create a new private helper method, `_create_initial_state`**, within `IRCClient_Logic`. This method will be responsible for:
    - Examining the command-line `args`.
    - Consulting the `AppConfig` object for the default server configuration.
    - Merging these sources to create the definitive initial `ConnectionInfo` object.
    - Setting this initial `ConnectionInfo` object in the `StateManager`.
3.  The `__init__` method will call `_create_initial_state` as part of its setup sequence.

**Step 4: Refactor Dynamic Command Loading**

1.  **Modify `pyrc_core/commands/command_handler.py`.**
2.  Replace the `os.walk`-based module discovery with the more robust `pkgutil.walk_packages` function.
3.  The path for `walk_packages` should be the `pyrc_core.commands` package itself. This will make the loading mechanism independent of the file system's current working directory and platform path separators.

**Step 5: Final Cleanup and Consistency**

1.  Review all modified files for consistency. Ensure type hints are updated to reflect the new class structures (e.g., functions now accepting `AppConfig` or `StateManager` instances).
2.  Verify that all command handlers, event handlers, and scripts now access configuration and state through the correct, centralized channels.
3.  Ensure the `run_headless_tests.py` script and the `test_headless.py` script itself are updated to work with the refactored initialization and state management logic.

**DELIVERABLES**
Provide the complete, refactored code for all modified files. The final project should be fully functional, with the improved architecture implemented as described above. Do not add any new features; focus solely on the refactoring and rationalization tasks.
