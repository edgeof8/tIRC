# PyRC - Python Terminal IRC Client

PyRC is a modern, terminal-based IRC (Internet Relay Chat) client written in Python. It aims to provide a feature-rich, yet lightweight and user-friendly experience for IRC users who prefer the command line. It is actively developed with a focus on extreme modularity, enabling programmatic use and integration with AI agents or other automated systems.

## Key Features

- **Text-based UI:** Clean and navigable interface using the Python `curses` library (optional for headless operation).
- **Split-Screen Support:** Horizontal split-screen mode with independent scrolling and context management for each pane.
- **Multi-Server Configuration & Switching:**
  - Define multiple server connection profiles in `pyterm_irc_config.ini`.
  - Switch between configured servers using the `/server <config_name>` command.
- **Channel and Query Windows:** Separate, consistently managed contexts for channels (case-insensitive handling, e.g., `#channel` and `#Channel` are treated as the same) and private messages.
- **mIRC-like UI Flow:** Starts in the "Status" window and automatically switches to a channel upon successful join (when UI is active).
- **IRCv3 Support:**
  - Robust CAP negotiation (including `sasl`, `multi-prefix`, `server-time`, `message-tags`, `account-tag`, `echo-message`, `away-notify`, `chghost`, `userhost-in-names`, `cap-notify`, `extended-join`, `account-notify`, `invite-notify`). Server-specific desired capabilities can be configured.
  - SASL PLAIN authentication for secure login.
  - IRCv3 Message Tag parsing and inclusion in relevant script events.
- **Highly Modular Command System:** _All_ core client commands are now implemented in individual, self-contained Python modules within a structured `commands/` directory (e.g., [`commands/utility/set_command.py`](commands/utility/set_command.py:1), [`commands/ui/split_screen_commands.py`](commands/ui/split_screen_commands.py:1)). These commands are dynamically discovered and registered at startup, making the system highly extensible and maintainable. Each command module defines its own handler(s), help text (usage, description), and aliases, ensuring that adding or modifying core commands is straightforward and isolated.

- **Dynamic Help System:** The `/help` system is now fully dynamic, sourcing its information directly from the core command modules' definitions and from script registrations. This ensures help text is always up-to-date with available commands and their functionalities.
- **Comprehensive Command Set:** Supports a wide array of standard IRC commands and client-specific utility commands. (See "Basic Commands" section).
- **Dynamic Configuration:** View and modify client settings on-the-fly using the `/set` command. Changes are saved to [`pyterm_irc_config.ini`](pyterm_irc_config.ini:1). Reload configuration with `/rehash`.
- **Ignore System:** Powerful ignore list for users/hostmasks with wildcard support, managed via `/ignore`, `/unignore`, `/listignores`.
- **Extensible Scripting System (Python):**
  - Load custom Python scripts from a `scripts/` directory to add new commands, respond to IRC/client events, and modify client behavior.
  - Default features like "fun" commands (`/slap`, `/8ball`), randomized quit/part messages, and the client exit screen are implemented as default scripts.
  - Scripts have access to a rich `ScriptAPIHandler` for safe and powerful interaction with the client (see "Scripting System" section below for API details).
- **Advanced Event-Driven Trigger System (`/on` command & API):**
  - Define custom actions based on IRC events (TEXT, ACTION, JOIN, PART, QUIT, KICK, MODE, TOPIC, NICK, NOTICE, INVITE, CTCP, RAW).
  - Actions can be standard client commands or arbitrary Python code snippets (executed via a sandboxed [`PythonTriggerAPI`](python_trigger_api.py:1)). The `/on` command and its underlying Python execution API ([`PythonTriggerAPI`](python_trigger_api.py:1)) are stable and robust.
  - Utilize regex capture groups ($0, $1, etc.) and extensive event-specific variables ($nick, $channel, $$1, $1-, etc.).
  - Triggers are persistent and saved to `config/triggers.json`.
  - Fully manageable via the `/on` command or programmatically through the `ScriptAPIHandler`.
- **Modular Event Management:**
  - A dedicated `EventManager` class handles the construction and dispatching of all script-facing events, ensuring consistency in event data.
- **Headless Operation:**
  - Can be run with a `--headless` flag, disabling the `curses` UI for use as an IRC backend or for AI agents. Core logic and scripting remain fully functional.
  - All core IRC logic, event processing, and the scripting system remain fully functional.
  - Scripts can interact with the IRC server using the `ScriptAPIHandler`.
  - The `headless_message_history_lines` config option allows for different message history sizes in headless mode.
- **Logging:**
  - Comprehensive main application log (defaults to `logs/pyrc_core.log`).
  - Dedicated log for Status window messages (defaults to `logs/client_status_messages.log`).
  - Optional per-channel logging to separate files in the `logs/` directory (e.g., `logs/python.log`). The `logs/` directory will be created automatically if it doesn't exist.
  - Robust collision avoidance for log filenames.
  - Raw IRC message logging to UI toggleable with `/rawlog`.
- **Code Modularity:** Significantly improved structure throughout the core:
  - **Protocol Handling:** IRC command processing is broken down into multiple focused handler modules (e.g., [`message_handlers.py`](message_handlers.py:1), [`membership_handlers.py`](membership_handlers.py:1), [`state_change_handlers.py`](state_change_handlers.py:1), [`protocol_flow_handlers.py`](protocol_flow_handlers.py:1), [`irc_numeric_handlers.py`](irc_numeric_handlers.py:1)), making [`irc_protocol.py`](irc_protocol.py:1) a lean dispatcher.
  - **Command Handling:** Core client command logic is highly modularized into individual files within `commands/` subdirectories.
- **Centralized Color Handling:** Client feedback and messages utilize a semantic color key system, resolved centrally for consistent UI presentation.
- **Tab Completion:** For commands (core, script-added, dynamically loaded) and nicks in the current context (UI mode only).
- **SSL/TLS Encryption:** Secure connections, with an option (`verify_ssl_cert` in config) to allow connections to servers with self-signed certificates.
- **Color Themes:** Basic support, with potential for expansion.

## Prerequisites

- Python 3.8 or higher.
- `pip` (Python package installer).
- On Windows, `windows-curses` is required (`pip install windows-curses`). It's included in `requirements.txt`.
- `pyfiglet` for the `/ascii` command (optional, for `default_fun_commands.py` script). It's included in `requirements.txt`.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/edgeof8/PyRC.git
    cd PyRC
    ```
2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    ```
3.  **Activate it:**
    - Windows: `venv\Scripts\activate`
    - Linux/macOS: `source venv/bin/activate`
4.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

PyRC uses a configuration file named `pyterm_irc_config.ini` located in the root directory. An example `pyterm_irc_config.ini.example` is provided, which you can copy and customize.

Key settings from `pyterm_irc_config.ini`:

- **Server Definitions:** (e.g., `[Server.LiberaChat]`)
  - `address`, `port`, `ssl`, `nick`, `channels` (comma-separated list)
  - `username`, `realname` (optional, default to nick)
  - `server_password` (optional)
  - `nickserv_password` (optional, also used for SASL if `sasl_password` not set)
  - `sasl_username`, `sasl_password` (optional, default to nick/nickserv_password)
  - `verify_ssl_cert` (true/false)
  - `auto_connect` (true for one server to connect on startup)
  - `desired_caps` (optional, e.g., `sasl,multi-prefix,server-time`): Comma-separated list of IRCv3 capabilities to request from this specific server.
- **UI Settings:** (`[UI]`)
  - `message_history_lines`
  - `headless_message_history_lines` (for `--headless` mode)
  - `colorscheme` (currently "default")
- **Logging Settings:** (`[Logging]`)
  - `log_enabled`, `log_file` (main log, e.g., `pyrc_core.log`), `log_level`, `log_max_bytes`, `log_backup_count`
  - `channel_log_enabled` (all logs go into `logs/` subdirectory, which is created automatically if needed)
- **Features:** (`[Features]`)
  - `enable_trigger_system` (true/false)
- **Scripts:** (`[Scripts]`)
  - `disabled_scripts` (comma-separated list of script module names to disable)
- **IgnoreList:** (`[IgnoreList]`): This section is automatically managed by the `/ignore`, `/unignore`, and `/listignores` commands. Ignored patterns (e.g., `*!*@*.example.com`) are stored here.
- **DCC Settings:** (`[DCC]`)
  - `dcc_enabled` (true/false): Enables or disables DCC functionality.
  - `dcc_download_dir` (string): Default directory for downloaded files (e.g., `downloads/`).
  - `dcc_max_file_size` (integer): Maximum file size in bytes for transfers (e.g., `104857600` for 100MB).
  - `dcc_auto_accept` (true/false): Whether to automatically accept incoming file offers (use with caution).
  - `dcc_blocked_extensions` (comma-separated string): File extensions to block (e.g., `exe,bat,sh,vbs`).
  - `dcc_port_range_start`, `dcc_port_range_end` (integers): Port range for listening sockets in active DCC.
  - `dcc_timeout` (integer): Timeout in seconds for DCC connections/transfers.

You can view and modify many settings on-the-fly using the `/set` command. Changes are saved automatically. Use `/rehash` to reload the INI file.

## Usage

Run PyRC from its root directory:

```bash
python pyrc.py
```

Command-line overrides (creates a temporary "CommandLine" server configuration):

```bash
python pyrc.py [--server <server>] [--port <port>] [--nick <nick>] [--channel <#channel>] [--ssl] [--password <server_pass>] [--nickserv-password <pass>] [--headless] [--disable-script <script_name>]
```

## Basic Commands

PyRC supports a variety of commands, all dynamically loaded. Type `/help` within the client for a list of commands and their aliases, or `/help <command>` for specific command usage. The help system is dynamically built from command module definitions and script registrations, ensuring up-to-date information.

### Connection & Session Management:

- `/connect <server[:port]> [ssl|nossl]`: Connects to the specified IRC server. Uses SSL if 'ssl' is provided, or attempts to infer from port.
- `/server <config_name>` (Alias: `/s`): Switches to a pre-defined server configuration and attempts to connect.
- `/disconnect [reason]` (Alias: `/d`): Disconnects from the current server.
- `/quit [message]` (Alias: `/q`): Disconnects from the server and exits PyRC.
- `/reconnect`: Disconnects and then reconnects to the current server.
- `/nick <newnickname>` (Alias: `/n`): Changes your nickname.
- `/away [message]`: Sets your away status with an optional message. If no message is provided, marks you as no longer away.

### Channel Operations:

- `/join <channel> [#channel2 ...]` (Alias: `/j`): Joins the specified IRC channel(s).
- `/part [channel] [reason]` (Alias: `/p`): Leaves the specified channel or the current channel if none is specified.
- `/topic [<channel>] [<new_topic>]` (Alias: `/t`): Views or sets the topic for a channel. If no channel is specified, uses the current channel. If no new_topic is specified, views the current topic.
- `/invite <nick> [channel]` (Alias: `/i`): Invites a user to a channel. If no channel is specified, uses the current channel.
- `/kick <nick> [reason]` (Alias: `/k`): Kicks a user from the current channel.
- `/cyclechannel` (Alias: `/cc`): Parts and then rejoins the current channel.
- `/ban <nick|hostmask>`: Bans a user or hostmask from the current channel.
- `/unban <hostmask>`: Removes a ban (specified by hostmask) from the current channel.
- `/mode [<target>] <modes_and_params>`: Sets or views channel or user modes. If <target> is omitted for a channel mode, it defaults to the current channel.
- `/op <nick>` (Alias: `/o`): Grants operator status to <nick> in the current channel.
- `/deop <nick>` (Alias: `/do`): Removes operator status from <nick> in the current channel.
- `/voice <nick>` (Alias: `/v`): Grants voice status to <nick> in the current channel.
- `/devoice <nick>` (Alias: `/dv`): Removes voice status from <nick> in the current channel.

### Messaging & Information:

- `/msg <target> <message>` (Alias: `/m`): Sends a private message to a user or a message to a channel.
- `/query <nick> [message]`: Opens a query window with <nick> and optionally sends an initial message.
- `/notice <target> <message>` (Alias: `/no`): Sends a NOTICE to the specified target.
- `/me <action text>`: Sends an action message (CTCP ACTION) to the current channel or query.
- `/whois <nick>` (Alias: `/w`): Retrieves WHOIS information for the specified nickname.
- `/who [channel|nick]`: Shows WHO information for a channel or user.
- `/whowas <nick> [count] [server]`: Shows WHOWAS information for a user, providing historical data about a nickname.
- `/list [pattern]`: Lists channels on the server, optionally filtering by a pattern. Results appear in a new temporary window.
- `/names [channel]`: Shows the list of users in a channel. If no channel is specified, it may list users in the current channel or all visible users depending on the server.

### Client Utility & UI:

- `/clear` (Alias: `/c`): Clears the message history of the current active window.
- `/close [context_name]` (Aliases: `/wc`, `/partchannel`): Closes the specified window or the current window if none is specified. For channels, this parts the channel.
- `/help [command_name]` (Alias: `/h`): Displays general help or help for a specific command.
- PageUp/PageDown: Scroll message buffer.
- Ctrl+N (or `/nextwindow`, Alias: `/next`): Switch to the next window.
- Ctrl+P (or `/prevwindow`, Alias: `/prev`): Switch to the previous window.
- `/window <name|number>` (Alias: `/win`): Switches to the window specified by name or number.
- `/status`: Switches to the Status window.
- `/prevchannel` (Alias: `/pc`): Switches to the previously active channel or Status window.
- `/split`: Toggle split-screen mode on/off.
- `/focus <top|bottom>`: Switch focus between split panes (top or bottom).
- `/setpane <top|bottom> <context_name>`: Set a context in a specific pane.
- Ctrl+U (or `/userlistscroll [offset|direction]`, Alias: `/u`): Scrolls the user list.
- `/set [<section.key> [<value>]]` (Alias: `/se`): Views or modifies client configuration settings.
- `/rehash`: Reloads the client configuration from the INI file.
- `/save`: Saves the current client configuration to the INI file.
- `/ignore <nick|hostmask>`: Adds a user/hostmask to the ignore list. Simple nicks are converted to nick!_@_.
- `/unignore <nick|hostmask>`: Removes a user/hostmask from the ignore list. Tries to match exact pattern or derived nick!_@_.
- `/listignores` (Alias: `/ignores`): Lists all currently ignored patterns.
- `/rawlog [on|off|toggle]`: Toggles or sets the display of raw IRC messages in the Status window.
- `/lastlog <pattern>`: Searches the message history of the active window for lines containing <pattern>.
- `/raw <raw IRC command>` (Aliases: `/quote`, `/r`): Sends a raw command directly to the IRC server.
- `/on ...`: Manages event-based triggers (see `/help on`).

### Fun Commands (from default_fun_commands.py script):

- `/slap <nickname>`: Slaps a user.
- `/8ball <question>`: Asks the Magic 8-Ball.
- `/dice <NdN>` (Alias: `/roll`): Rolls dice.
- `/rainbow <text>`: Sends text in rainbow colors.
- `/reverse <text>`: Sends text reversed.
- `/wave <text>`: Sends text with a wave effect.
- `/ascii <text>`: Converts text to ASCII art (requires `pyfiglet`).

### DCC (Direct Client-to-Client) Commands:

- `/dcc send <nick> <filepath>`: Initiates a DCC SEND (file transfer) to the specified user.
- `/dcc accept <nick> <filename> <ip> <port> <size>`: Accepts an incoming DCC SEND offer from a user.
- `/dcc list`: Lists current DCC transfers and their statuses.
- `/dcc cancel <transfer_id>`: Cancels an active or queued DCC transfer.
- `/dcc browse [path]`: (Future functionality) Opens a file browser, planned for easier file selection.

## Headless Operation

Run with `--headless`. Core logic, scripting (including `ScriptAPIHandler`), event management (`EventManager`), and the trigger system (if enabled via config) remain fully functional. Ideal for bots and AI integrations.

## Scripting System

PyRC features a powerful Python scripting system located in the `scripts/` directory. Scripts can add commands, subscribe to events, and use the `ScriptAPIHandler` (passed as `self.api`) for extensive client interaction.

### Key `ScriptAPIHandler` Capabilities (Summary):

- **Sending:** `send_raw`, `send_message`, `send_action`, `send_notice`, channel operations (`join_channel`, `part_channel`), state changes (`set_nick`, `set_topic`, `set_channel_mode`), user actions (`kick_user`, `invite_user`), client control (`quit_client`).
- **UI Interaction:** `add_message_to_context` (uses semantic color keys).
- **Information Retrieval:** Client info (`get_client_nick`, `is_connected`), server info (`get_server_info`, `get_server_capabilities`), channel/context info (`get_joined_channels`, `get_channel_users`, `get_channel_topic`, `get_context_info`, `get_context_messages`).
- **Trigger Management API:** `add_trigger`, `remove_trigger`, `list_triggers`, `set_trigger_enabled`.
- **Script Functionality Registration:** `register_command`, `subscribe_to_event`, `register_help_text`.
- **Logging & Data:** `log_info/warning/error` (script-aware), `request_data_file_path`.

Refer to `script_api_handler.py` and example scripts for full details.

### Key Script Events (Dispatched via `EventManager`)

Events are dispatched with a consistent `event_data` dictionary including `timestamp`, `raw_line` (if applicable), and `client_nick`.

**Client Lifecycle Events:**

- `CLIENT_CONNECTED`: Fired when TCP/IP connection is up and CAP negotiation begins.
  - `event_data` additional keys: `server` (str), `port` (int), `nick` (str - current client nick), `ssl` (bool).
- `CLIENT_DISCONNECTED`: Fired when connection is lost/closed.
  - `event_data` additional keys: `server` (str), `port` (int).
- `CLIENT_REGISTERED`: Fired upon receiving RPL_WELCOME (001).
  - `event_data` additional keys: `nick` (str - confirmed client nick), `server_message` (str - welcome message).
- `CLIENT_READY`: Fired after `CLIENT_REGISTERED` and initial auto-join actions (like NickServ IDENTIFY and channel joins) have been initiated. This is a good event for headless scripts to start their primary operations.
  - `event_data` additional keys: `nick` (str - confirmed client nick), `client_logic_ref` (reference to `IRCClient_Logic`).
- `CLIENT_NICK_CHANGED`: Fired specifically when PyRC's own nickname successfully changes.
  - `event_data` additional keys: `old_nick` (str), `new_nick` (str).
- `CLIENT_SHUTDOWN_FINAL`: Fired just before application exit, _after_ `curses` UI is down (if UI was active).

**IRC Message & Command Events:**

- `PRIVMSG`: For channel and private messages.
  - `event_data` additional keys: `nick` (str), `userhost` (str), `target` (str), `message` (str), `is_channel_msg` (bool), `tags` (Dict[str, Any] - parsed IRCv3 message tags).
- `NOTICE`: For IRC NOTICEs.
  - `event_data` additional keys: `nick` (str), `userhost` (str), `target` (str), `message` (str), `is_channel_notice` (bool), `tags` (Dict[str, Any]).
- `JOIN`: When a user (including client) joins.
  - `event_data` additional keys: `nick` (str), `userhost` (str - if available from server, e.g. with extended-join), `channel` (str), `account` (str - if available, e.g. with extended-join), `real_name` (str - if available, e.g. with extended-join), `is_self` (bool).
- `CHANNEL_FULLY_JOINED`: Fired after a channel is successfully joined and RPL_ENDOFNAMES (or equivalent) is received.
  - `event_data` additional keys: `channel_name` (str).
- `PART`: When a user (including client) parts.
  - `event_data` additional keys: `nick` (str), `userhost` (str), `channel` (str), `reason` (str), `is_self` (bool).
- `QUIT`: When a user quits.
  - `event_data` additional keys: `nick` (str), `userhost` (str), `reason` (str).
- `NICK`: When any user changes their nickname.
  - `event_data` additional keys: `old_nick` (str), `new_nick` (str), `userhost` (str), `is_self` (bool).
- `MODE`: When a mode change occurs (raw event).
  - `event_data` additional keys: `nick` (str - setter), `userhost` (str - setter's host), `target` (str - channel/nick affected), `modes_and_params` (str - raw mode string), `parsed_modes` (List[Dict] - structured mode changes).
- `CHANNEL_MODE_APPLIED`: Fired after a channel MODE is processed and applied.
  - `event_data` additional keys: `channel` (str), `setter_nick` (str), `setter_userhost` (str), `mode_changes` (List[Dict] - structured), `current_channel_modes` (List[str]).
- `TOPIC`: When a channel topic is changed or viewed.
  - `event_data` additional keys: `nick` (str - setter), `userhost` (str), `channel` (str), `topic` (str).
- `CHGHOST`: When a user's host changes.
  - `event_data` additional keys: `nick` (str), `new_ident` (str), `new_host` (str), `userhost` (str - old userhost).

**Raw IRC Lines & Numerics:**

- `RAW_IRC_LINE`: Fired for _every_ complete raw line received from the server _before_ PyRC's internal parsing.
  - `event_data` keys: `raw_line` (str).
- `RAW_IRC_NUMERIC`: Fired for all numeric replies from the server.
  - `event_data` keys: `numeric` (int), `source` (str - server name), `params_list` (List[str] - full parameters), `display_params_list` (List[str] - parameters with client nick removed if first), `trailing` (Optional[str]), `tags` (Dict[str, Any]).

## Default Scripts & Modular Core Commands

- Default utility/fun scripts are in `scripts/`.
- Core client commands are now modularly defined in `commands/core/`, `commands/utility/`, `commands/ui/`, and `commands/user/`. Each command module specifies its own help text via a `COMMAND_DEFINITIONS` structure.

## Recent Changes (Summary)

- **Initial DCC Implementation (Phase 1 - Active DCC):** Added core functionality for DCC SEND and DCC ACCEPT (receive) using active DCC connections. This includes new `/dcc` commands, DCC-specific configuration, and underlying modules (`DCCManager`, `DCCTransfer`, `DCCProtocol`, `DCCSecurity`). CTCP handling for DCC negotiation has been integrated into `IRCClient_Logic`.
- **Complete Core Command Modularization:** All core client commands are now located in individual modules within the `commands/` directory and are dynamically loaded. This includes commands for UI navigation, user interactions (ignore, away, etc.), server management, and utilities.
- **Trigger System Stability:** Successfully resolved a trigger execution loop issue, leading to improved stability and reliability of the `/on` command and Python-based triggers.
- **Help System Accuracy:** Fixed the general `/help` command to accurately display all command groups and their respective commands, sourcing information dynamically from modules and scripts.
- **Hyper-Modular Commands:** Core client command logic has been refactored out of `CommandHandler` into individual files within a structured `commands/` directory. These are dynamically loaded.
- **Modular Help System:** The `/help` command now dynamically sources its information from these command modules as well as from scripts.
- **EventManager:** Introduced a dedicated `EventManager` to centralize the creation and dispatch of script-facing events, ensuring consistent data.
- **PythonTriggerAPI Relocation:** The API for Python-based triggers (`/on ... PY ...`) moved to [`python_trigger_api.py`](python_trigger_api.py:1).
- **Protocol Handler Refactoring:** [`irc_protocol.py`](irc_protocol.py:1) has been significantly slimmed down into a dispatcher, with specific command handling logic moved to new modules: [`message_handlers.py`](message_handlers.py:1), [`membership_handlers.py`](membership_handlers.py:1), [`state_change_handlers.py`](state_change_handlers.py:1), [`protocol_flow_handlers.py`](protocol_flow_handlers.py:1).
- **Centralized Color Handling:** Core logic components now pass semantic color keys (e.g., "system", "error") to `IRCClient_Logic.add_message`, which handles UI color resolution.
- **Initialization Order Fix:** Corrected an issue where `CommandHandler` was initialized before `ScriptManager` in `IRCClient_Logic`, affecting dynamic command loading.

## Contributing

Contributions are welcome! Please:

1.  Fork the repository.
2.  Create a new branch (`git checkout -b feature/your-feature-name`).
3.  Make your changes and commit them (`git commit -am 'Add some feature'`).
4.  Push to the branch (`git push origin feature/your-feature-name`).
5.  Create a new Pull Request.

For major changes, please open an issue first to discuss your ideas.

## License

This project is licensed under the MIT License.
