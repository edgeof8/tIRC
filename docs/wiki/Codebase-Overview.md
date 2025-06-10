## Codebase Overview

PyRC's codebase is organized into a logical directory structure to promote modularity, maintainability, and clear separation of concerns.

### Directory Structure

```
PyRC/
├── pyrc.py                     # Main application entry point and asyncio event loop setup
│
├── pyrc_core/                  # Core application package
│   ├── __init__.py             # Package initialization
│   ├── app_config.py           # Centralized configuration management using configparser
│   ├── context_manager.py      # Manages chat contexts (channels, queries, server)
│   ├── event_manager.py        # Asynchronous event dispatching system
│   ├── network_handler.py      # Async IRC protocol handling using asyncio.StreamReader/Writer
│   └── state_manager.py        # Thread-safe state management with persistence
│
│   ├── client/                # Client implementation
│   │   ├── __init__.py
│   │   ├── client_shutdown_coordinator.py # Handles graceful shutdown
│   │   ├── client_view_manager.py    # Manages different views/layouts
│   │   ├── connection_orchestrator.py  # Coordinates connection lifecycle and authentication
│   │   ├── dummy_ui.py               # Dummy UI for headless mode
│   │   ├── input_handler.py            # Async input processing and command dispatching
│   │   ├── irc_client_logic.py         # Main application logic and component coordination
│   │   └── state_change_ui_handler.py  # Updates UI in response to state changes
│   │
│   ├── ui/                     # Terminal UI components
│   │   ├── __init__.py
│   │   ├── curses_manager.py          # Low-level Curses initialization and teardown
│   │   ├── curses_utils.py            # Safe Curses drawing utilities
│   │   ├── input_line_renderer.py     # Input prompt and text entry
│   │   ├── message_panel_renderer.py  # Chat message display
│   │   ├── sidebar_panel_renderer.py  # Channel/user list
│   │   ├── status_bar_renderer.py     # Status information display
│   │   ├── ui_manager.py              # UI component coordination
│   │   └── window_layout_manager.py   # Window layout calculations
│   │
│   ├── commands/              # Built-in command implementations
│   │   ├── __init__.py
│   │   ├── command_handler.py   # Command registration and dispatch
│   │   │
│   │   ├── channel/           # Commands for channel operations.
│   │   │   ├── __init__.py
│   │   │   ├── ban_commands.py       # /ban, /unban, /kickban
│   │   │   ├── cyclechannel_command.py # /cycle
│   │   │   ├── invite_command.py     # /invite
│   │   │   ├── join_command.py       # /join
│   │   │   ├── kick_command.py       # /kick
│   │   │   ├── mode_command.py       # /mode (channel modes)
│   │   │   ├── part_command.py       # /part
│   │   │   ├── simple_mode_commands.py # /op, /deop, /voice, etc.
│   │   │   └── topic_command.py      # /topic
│   │   │
│   │   ├── core/            # Essential client commands.
│   │   │   ├── __init__.py
│   │   │   └── help_command.py       # /help
│   │   │
│   │   ├── dcc/             # DCC file transfer and chat commands.
│   │   │   ├── __init__.py
│   │   │   ├── dcc_accept_command.py  # /dcc accept
│   │   │   ├── dcc_auto_command.py    # /dcc auto
│   │   │   ├── dcc_browse_command.py  # /dcc browse
│   │   │   ├── dcc_cancel_command.py  # /dcc cancel
│   │   │   ├── dcc_commands.py        # Main DCC command handler
│   │   │   ├── dcc_get_command.py     # /dcc get
│   │   │   ├── dcc_list_command.py    # /dcc list
│   │   │   ├── dcc_resume_command.py  # /dcc resume
│   │   │   └── dcc_send_command.py    # /dcc send
│   │   │
│   │   ├── information/     # Information retrieval commands.
│   │   │   ├── __init__.py
│   │   │   ├── list_command.py        # /list
│   │   │   ├── names_command.py       # /names
│   │   │   ├── who_command.py         # /who
│   │   │   └── whowas_command.py      # /whowas
│   │   │
│   │   ├── server/          # Server connection and management.
│   │   │   ├── __init__.py
│   │   │   ├── connect_command.py     # /connect
│   │   │   ├── disconnect_command.py  # /disconnect
│   │   │   ├── quit_command.py        # /quit
│   │   │   ├── raw_command.py         # /raw
│   │   │   ├── reconnect_command.py   # /reconnect
│   │   │   └── server_command.py      # /server
│   │   │
│   │   ├── ui/              # User interface controls.
│   │   │   ├── __init__.py
│   │   │   ├── close_command.py       # /close
│   │   │   ├── split_screen_commands.py # /split, /unsplit
│   │   │   ├── status_command.py      # /status
│   │   │   ├── userlist_scroll_command.py # /scrollusers
│   │   │   └── window_navigation_commands.py # /window, /next, /prev
│   │   │
│   │   ├── user/            # User interaction commands.
│   │   │   ├── __init__.py
│   │   │   ├── away_command.py        # /away
│   │   │   ├── ignore_commands.py     # /ignore, /unignore, /listignores
│   │   │   ├── me_command.py          # /me
│   │   │   ├── msg_command.py         # /msg
│   │   │   ├── nick_command.py        # /nick
│   │   │   ├── notice_command.py      # /notice
│   │   │   └── query_command.py       # /query
│   │   │
│   │   └── utility/         # Utility and configuration commands.
│   │       ├── __init__.py
│   │       ├── clear_command.py       # /clear
│   │       ├── execute_command.py     # /exec
│   │       ├── rehash_command.py      # /rehash
│   │       ├── save_command.py        # /save
│   │       ├── script_command.py      # /script
│   │       ├── set_command.py         # /set
│   │       ├── show_command.py        # /show
│   │       └── trigger_command.py     # /trigger
│   │
│   ├── data/                   # Static data files for pyrc_core
│   │   └── default_help/
│   │       └── command_help.ini  # Fallback help texts for core commands
│   │
│   ├── dcc/                   # DCC (Direct Client-to-Client) feature implementation.
│   │   ├── __init__.py
│   │   ├── dcc_ctcp_handler.py # Handles incoming DCC CTCP requests.
│   │   ├── dcc_manager.py      # Main orchestrator for all DCC functionality.
│   │   ├── dcc_passive_offer_manager.py # Manages passive (reverse) DCC offers.
│   │   ├── dcc_protocol.py     # Parses and formats DCC CTCP messages.
│   │   ├── dcc_receive_manager.py # Manages all incoming file transfers.
│   │   ├── dcc_security.py     # Filename sanitization and path validation.
│   │   ├── dcc_send_manager.py # Manages all outgoing file transfers.
│   │   ├── dcc_transfer.py     # Base classes for DCC send/receive transfer logic.
│   │   └── dcc_utils.py        # Shared utility functions (e.g., socket creation).
│   │
│   ├── features/              # Self-contained, optional features.
│   │   └── triggers/          # Implementation of the /on command trigger system.
│   │       ├── __init__.py
│   │       ├── trigger_commands.py
│   │       └── trigger_manager.py
│   │
│   ├── irc/                  # IRC protocol logic and message handling.
│   │   ├── __init__.py
│   │   ├── cap_negotiator.py   # Handles IRCv3 capability negotiation.
│   │   ├── irc_message.py     # Parses raw IRC lines into structured message objects.
│   │   ├── irc_protocol.py    # Main dispatcher for incoming server messages.
│   │   ├── registration_handler.py  # Manages NICK/USER registration sequence.
│   │   ├── sasl_authenticator.py    # Handles SASL PLAIN authentication.
│   │   └── handlers/          # Specific handlers for different IRC commands/numerics.
│   │       ├── __init__.py
│   │       ├── irc_numeric_handlers.py # Handlers for server numeric replies.
│   │       ├── membership_handlers.py  # Handlers for JOIN, PART, QUIT, KICK.
│   │       ├── message_handlers.py     # Handlers for PRIVMSG, NOTICE.
│   │       ├── protocol_flow_handlers.py # Handlers for PING, CAP, etc.
│   │       └── state_change_handlers.py # Handlers for NICK, MODE, etc.
│   │
│   ├── logging/              # Logging-specific components.
│   │   └── channel_logger.py  # Manages per-channel and status window log files.
│   │
│   ├── script_manager.py  # Discovers, loads, and manages all user scripts, providing the bridge between the core client and custom extensions.
│   │
│   └── scripting/            # The Python scripting engine.
│       ├── __init__.py
│       ├── api_responder_agent.py # Example AI agent script.
│       ├── python_trigger_api.py  # API for the /on <event> PY <code> trigger action.
│       ├── script_api_handler.py  # Provides the `api` object for scripts.
│       └── script_base.py     # A base class for scripts to inherit from.
│
├── scripts/                  # Directory for user-provided Python scripts and test utilities.
│   ├── ai_api_test_script.py    # Test script for AI API integration.
│   ├── default_exit_handler.py  # Default exit handler script.
│   ├── default_fun_commands.py  # Example script with fun commands.
│   ├── default_random_messages.py  # Random message generator for testing.
│   ├── event_test_script.py     # Script for testing event handling.
│   ├── run_headless_tests.py    # Entry point for running headless tests.
│   ├── test_dcc_features.py     # Tests for DCC functionality.
│   ├── test_headless.py         # Headless test runner.
│   └── test_script.py          # General test script.
│
├── config/                   # Directory for configuration files.
│   ├── pyterm_irc_config.ini       # Main configuration file (user-edited)
│   ├── pyterm_irc_config.ini.example # Example configuration file
│   └── triggers.json         # Stores persistent user-defined triggers (auto-generated)
│
├── data/                     # Directory for static data files (e.g. script data).
│
```

### Key Components

PyRC's core functionality is distributed across several key components, each responsible for a specific aspect of the client's operation:

#### Core Application Modules (`pyrc_core/`)

- **`app_config.py`**: Centralized management of all application and server settings.
- **`context_manager.py`**: Manages various chat contexts (channels, private queries, server status window).
- **`event_manager.py`**: The central asynchronous event dispatching system, enabling loose coupling between components.
- **`network_handler.py`**: Handles asynchronous network I/O using `asyncio.StreamReader` and `StreamWriter` for sending and receiving raw IRC data.
- **`state_manager.py`**: The single, thread-safe source of truth for all connection, session, and client-specific runtime state, with automatic persistence.
- **`script_manager.py`**: Discovers, loads, and manages all user scripts, providing the bridge between the core client and custom extensions.

#### Client Implementation (`pyrc_core/client/`)

- **`irc_client_logic.py`**: The main application logic, acting as a high-level orchestrator for various manager and coordinator components. It manages the primary asyncio event loop and delegates specialized tasks.
- **`connection_orchestrator.py`**: Manages the entire lifecycle of server connections, coordinating CAP negotiation (`CapNegotiator`), SASL authentication (`SaslAuthenticator`), and NICK/USER registration (`RegistrationHandler`).
- **`client_shutdown_coordinator.py`**: Encapsulates the complex shutdown sequence, ensuring a graceful and orderly termination of all client components.
- **`client_view_manager.py`**: Manages UI-specific logic related to different views (e.g., split-screen), active context switching, and associated event handling.
- **`dummy_ui.py`**: Provides a non-operational UI interface for headless mode, allowing the core client logic to run without a terminal UI.
- **`input_handler.py`**: Processes user input, translating key presses into commands or messages.
- **`state_change_ui_handler.py`**: Responsible for updating the User Interface in response to changes in the application state.

#### Command System (`pyrc_core/commands/`)

- **`command_handler.py`**: Discovers, registers, and dispatches all built-in and script-defined commands.
- **Subdirectories (e.g., `channel/`, `server/`, `dcc/`, `ui/`, `user/`, `utility/`)**: Contain individual Python modules implementing specific command categories. Commands are dynamically loaded from these directories.

#### DCC (Direct Client-to-Client) (`pyrc_core/dcc/`)

- **`dcc_manager.py`**: Orchestrates all DCC send and receive operations.
- **`dcc_ctcp_handler.py`**: Handles incoming DCC CTCP requests.
- **`dcc_send_manager.py`** & **`dcc_receive_manager.py`**: Manage outgoing and incoming file transfers, respectively.
- **`dcc_security.py`**: Provides filename sanitization and path validation for safe transfers.

#### Scripting Engine (`pyrc_core/scripting/`)

- **`script_api_handler.py`**: Provides the API object (`self.api`) that scripts use to interact with the client.
- **`python_trigger_api.py`**: Implements the API for the `/on <event> PY <code>` trigger action.

#### IRC Protocol Logic (`pyrc_core/irc/`)

- **`irc_message.py`**: Parses raw IRC lines into structured message objects.
- **`irc_protocol.py`**: The main dispatcher for incoming server messages, directing them to appropriate handlers.
- **`cap_negotiator.py`**: Handles IRCv3 capability negotiation.
- **`sasl_authenticator.py`**: Manages SASL PLAIN authentication.
- **`registration_handler.py`**: Manages the NICK/USER registration sequence.
- **`handlers/`**: Contains specific handlers for various IRC commands and numeric replies (e.g., `PRIVMSG`, `JOIN`, `RPL_WELCOME`).

#### UI System (`pyrc_core/ui/`)

- **`ui_manager.py`**: Coordinates all UI components and refresh cycles.
- **`curses_manager.py`**: Manages low-level `curses` initialization, teardown, and basic terminal interactions.
- **`window_layout_manager.py`**: Calculates and manages the layout, sizing, and positioning of all UI windows (message panel, sidebar, input line, status bar).
- **`message_panel_renderer.py`**, **`sidebar_panel_renderer.py`**, **`status_bar_renderer.py`**, **`input_line_renderer.py`**: Dedicated components for rendering specific parts of the terminal UI.
- **`curses_utils.py`**: Provides safe, utility functions for `curses` drawing operations.

#### Logging (`pyrc_core/logging/`)

- **`channel_logger.py`**: Manages per-channel and status window log files, ensuring message history is persisted.
