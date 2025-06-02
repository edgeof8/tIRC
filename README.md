# PyRC - Python Terminal IRC Client

PyRC is a modern, terminal-based IRC (Internet Relay Chat) client written in Python. It aims to provide a feature-rich, yet lightweight and user-friendly experience for IRC users who prefer the command line. It is also being actively developed with a focus on modularity, enabling programmatic use and integration with AI agents or other automated systems.

## Key Features

- **Text-based UI:** Clean and navigable interface using the Python `curses` library (optional for headless operation).
- **Split-Screen Support:** Horizontal split-screen mode with independent scrolling and context management for each pane.
- **Channel and Query Windows:** Separate, consistently managed contexts for channels (case-insensitive handling, e.g., #channel and #Channel are treated as the same) and private messages.
- **mIRC-like UI Flow:** Starts in the "Status" window and automatically switches to a channel upon successful join (when UI is active).
- **IRCv3 Support:**
  - Robust CAP negotiation (including `sasl`, `multi-prefix`, `server-time`, `message-tags`, `account-tag`, `echo-message`, `away-notify`, `chghost`, `userhost-in-names`, `cap-notify`, `extended-join`, `account-notify`, `invite-notify`).
  - SASL PLAIN authentication for secure login.
  - IRCv3 Message Tag parsing and inclusion in relevant script events.
- **Comprehensive Command Set:** Supports a wide array of standard IRC commands and client-specific utility commands, many now managed via the scripting system.
- **Dynamic Configuration:** View and modify client settings on-the-fly using the `/set` command. Changes are saved to `pyterm_irc_config.ini`. Reload configuration with `/rehash`.
- **Ignore System:** Powerful ignore list for users/hostmasks with wildcard support, managed via `/ignore`, `/unignore`, `/listignores`.
- **Extensible Scripting System (Python):**
  - Load custom Python scripts from a `scripts/` directory to add new commands, respond to IRC/client events, and modify client behavior.
  - Default features like "fun" commands (`/slap`, `/8ball`), randomized quit/part messages, and the client exit screen are implemented as default scripts.
  - Scripts have access to a rich `ScriptAPIHandler` for safe and powerful interaction with the client (see "Scripting System" section below for API details).
- **Advanced Trigger System (`/on` command & API):**
  - Define custom actions based on IRC events (TEXT, ACTION, JOIN, PART, QUIT, KICK, MODE, TOPIC, NICK, NOTICE, INVITE, CTCP, RAW).
  - Actions can be standard client commands or arbitrary Python code snippets.
  - Utilize regex capture groups ($0, $1, etc.) and extensive event-specific variables ($nick, $channel, $$1, $1-, etc.).
  - Triggers are persistent and saved to `config/triggers.json`.
  - Fully manageable via the `/on` command or programmatically through the `ScriptAPIHandler`.
- **Headless Operation:**
  - Can be run with a `--headless` flag, disabling the `curses` UI for use as an IRC backend or for AI agents. Core logic and scripting remain fully functional.
  - No UI is drawn
  - All core IRC logic, including connection, CAP/SASL, event processing, and the scripting system, remains fully functional
  - Scripts can interact with the IRC server using the ScriptAPIHandler
  - Logging continues as configured
  - The client can be shut down via SIGINT (Ctrl+C) or programmatically by a script calling a quit/disconnect API function
  - The `headless_message_history_lines` config option can be used to set a different message history size for contexts in headless mode, potentially reducing memory usage
- **Logging:**
  - Comprehensive main log file for debugging and session history.
  - Optional per-channel logging to separate files.
  - Raw IRC message logging to UI toggleable with `/rawlog`.
- **Code Modularity:** Significantly improved structure and maintainability of core components:
  - Specialized handlers for IRC protocol parsing, numeric replies, command groups (now partially script-based), connection lifecycle (CAP, SASL, registration).
- **Tab Completion:** For commands (including script-added commands) and nicks in the current context (UI mode only).
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

PyRC uses a configuration file named `pyterm_irc_config.ini` located in the root directory of the application. If it doesn't exist, one with default values may be created on first run, or you might need to create it manually.

You can also view and modify many settings directly within the client using the `/set` command. Changes are saved automatically.

**`pyterm_irc_config.ini` Example Structure (Key Sections):**

```ini
[Connection]
default_server = irc.libera.chat
default_port = 6697
default_ssl = true
default_nick = PyRCUser
default_channels = #python,#yourchannel
password =
nickserv_password =
auto_reconnect = true
verify_ssl_cert = true
# proxy_type = SOCKS5 ; (Proxy support is not yet implemented)
# proxy_host = 127.0.0.1
# proxy_port = 9050

[UI]
message_history_lines = 500
colorscheme = default
headless_message_history_lines = 50 ; For --headless mode

[Logging]
log_enabled = true
log_file = pyrc.log ; Main log file name (will be in 'logs/' subdirectory)
log_level = INFO   ; DEBUG, INFO, WARNING, ERROR, CRITICAL
log_max_bytes = 5242880 ; 5 MB
log_backup_count = 3
channel_log_enabled = true ; Per-channel logs also go into the 'logs/' directory

[Features]
enable_trigger_system = true ; Enables or disables the /on trigger system

[Scripts]
# Comma-separated list of script module names to disable (without .py)
# e.g., disabled_scripts = default_fun_commands,event_test_script
disabled_scripts =

[IgnoreList]
# Add patterns to ignore, one per line, like:
# *!*@*.somehost.com = ignored
# BadNick!*@* = ignored
```

_(Note: The `[IgnoreList]` section is now managed by `config.py`'s `load_ignore_list` and `save_ignore_list` functions, storing patterns as keys.)_

## Usage

Once installed and configured, run PyRC from its root directory:

```bash
python pyrc.py
```

Or, to specify connection parameters via command line (overriding `pyterm_irc_config.ini` defaults):

```bash
python pyrc.py [--server <server>] [-p <port>] [-n <nick>] [-c <#channel>] [--ssl | --no-ssl] [--password <server_pass>] [--headless] [--disable-script <script_name>]
```

Example: `python pyrc.py --server irc.example.com -p 6667 -n MyPyRCNick -c "#chat" --no-ssl`
Example (headless): `python pyrc.py --server irc.example.com --nick MyBot --headless --disable-script default_fun_commands`

## Basic Commands

PyRC supports a variety of commands. Type `/help` within the client for a list of commands and their aliases, or `/help <command>` for specific command usage. The help system is data-driven from `scripts/data/default_help/command_help.ini` and can be extended by scripts.

### Connection & Session Management:

- `/connect <server[:port]> [ssl|nossl]` (Alias: `/server`, `/s`): Connects to a server.
- `/disconnect [reason]` (Alias: `/d`): Disconnects from the current server.
- `/quit [message]` (Alias: `/q`): Disconnects and exits PyRC. Uses random messages if no message is provided (from default_random_messages.py script).
- `/reconnect`: Disconnects and reconnects to the current server.
- `/nick <newnickname>` (Alias: `/n`): Changes your nickname.
- `/away [message]`: Sets your away status. No message marks you as back.

### Channel Operations:

- `/join <channel>` (Alias: `/j`): Joins a channel.
- `/part [channel] [reason]` (Alias: `/p`): Leaves a channel. Uses random messages if no reason is provided (from default_random_messages.py script).
- `/topic [newtopic]` (Alias: `/t`): Shows or sets the channel topic.
- `/invite <nick> [channel]` (Alias: `/i`): Invites a user to a channel.
- `/kick <nick> [reason]` (Alias: `/k`): Kicks a user from the current channel.
- `/cyclechannel` (Alias: `/cc`): Parts and rejoins the current channel.
- `/ban <nick|hostmask>`: Bans a user/hostmask from the current channel.
- `/unban <hostmask>`: Removes a ban.
- `/mode [<target>] <modes_and_params>`: Sets or views modes.
- `/op <nick>` (Alias: `/o`): Grants operator status.
- `/deop <nick>` (Alias: `/do`): Removes operator status.
- `/voice <nick>` (Alias: `/v`): Grants voice status.
- `/devoice <nick>` (Alias: `/dv`): Removes voice status.

### Messaging & Information:

- `/msg <nickname> <message>` (Alias: `/m`): Sends a private message.
- `/query <nickname> [message]`: Opens a query window.
- `/notice <target> <message>` (Alias: `/no`): Sends a NOTICE.
- `/me <action text>`: Sends a CTCP ACTION (e.g., `/me waves`).
- `/whois <nick>` (Alias: `/w`): Retrieves WHOIS information.
- `/who [<target>]`: Retrieves WHO information.
- `/whowas <nick> [count [target_server]]`: Retrieves WHOWAS information.
- `/list [pattern]`: Lists channels on the server.
- `/names [channel]`: Lists users in a channel.

### Client Utility & UI:

- `/clear` (Alias: `/c`): Clears messages from the current window.
- `/close` (Aliases: `/wc`, `/partchannel`): Closes the current query/channel window.
- `/help [command]` (Alias: `/h`): Displays help.
- PageUp/PageDown: Scroll message buffer.
- Ctrl+N (or `/nextwindow`, `/next`): Switch to the next window.
- Ctrl+P (or `/prevwindow`, `/prev`): Switch to the previous window.
- `/window <name|number>` (Alias: `/win`): Switches to a specific window.
- `/status`: Switches to the Status window.
- `/prevchannel` (Alias: `/pc`): Switches to the previously active channel or Status.
- `/split [on|off|toggle]`: Toggles split-screen mode.
- `/focus <top|bottom>`: Switches focus between split-screen panes.
- `/setpane <top|bottom> <context_name>`: Assigns a context to a specific pane.
- Ctrl+U (or `/u [offset|direction]`, `/userlistscroll [offset|direction]`): Scrolls the user list.
- `/set [<section.key> [<value>]]` (Alias: `/se`): Views or modifies client configuration.
- `/rehash`: Reloads `pyterm_irc_config.ini`.
- `/save`: Saves current configuration changes to `pyterm_irc_config.ini`.
- `/ignore <nick|hostmask>`: Ignores a user/hostmask.
- `/unignore <nick|hostmask>`: Removes an ignore.
- `/listignores`: Lists ignored patterns.
- `/rawlog [on|off|toggle]`: Toggles display of raw IRC messages in Status window.
- `/lastlog <pattern>`: Searches message history of the active window.
- `/raw <raw_irc_command>` (Aliases: `/quote`, `/r`): Sends a raw command to the server.
- `/on ...`: Manages event-based triggers (see `/help on`).

### Fun Commands (from default_fun_commands.py script):

- `/slap <nickname>`: Slaps a user.
- `/8ball <question>`: Asks the Magic 8-Ball.
- `/dice <NdN>` (Alias: `/roll`): Rolls dice.
- `/rainbow <text>`: Sends text in rainbow colors.
- `/reverse <text>`: Sends text reversed.
- `/wave <text>`: Sends text with a wave effect.
- `/ascii <text>`: Converts text to ASCII art.

## Headless Operation

PyRC can be run in a headless mode, without the `curses` user interface. This is useful for bots, automated scripts, or AI integrations where a visual UI is not needed.

To run in headless mode, use the `--headless` command-line flag:

```bash
python pyrc.py --server irc.example.com --nick MyHeadlessBot --headless
```

In headless mode:

- No UI is drawn.
- All core IRC logic, including connection, CAP/SASL, event processing, and the scripting system, remains fully functional.
- Scripts can interact with the IRC server using the `ScriptAPIHandler`.
- Logging continues as configured.
- The client can be shut down via `SIGINT` (Ctrl+C) or programmatically by a script.
- The `headless_message_history_lines` config option in `pyterm_irc_config.ini` (under `[UI]`) can be used to set a different message history size for contexts, potentially reducing memory usage.
- The `--disable-script <script_name>` flag can be used to prevent specific scripts from loading.
- The `enable_trigger_system` config option in `pyterm_irc_config.ini` (under `[Features]`) controls whether the `/on` trigger system is active.

## Scripting System

PyRC features a powerful and flexible scripting system, allowing users to extend and customize client functionality using Python. Scripts can introduce new commands, react to IRC and client events, manage their own data, and much more. All scripts are placed in the `scripts/` directory in PyRC's root folder and are loaded automatically on startup unless disabled in the configuration (`disabled_scripts` in `pyterm_irc_config.ini` or via `--disable-script` CLI flag).

### Key Scripting Capabilities:

- **Command Registration:** Scripts can define new client commands with custom handlers, help text, and aliases.
- **Event Subscription:** Scripts can subscribe to a wide range of IRC events (e.g., `PRIVMSG`, `JOIN`, `NICK`, `MODE`, `RAW_IRC_NUMERIC`, `CLIENT_NICK_CHANGED`, `CHANNEL_MODE_APPLIED`) and client lifecycle events (e.g., `CLIENT_CONNECTED`, `CLIENT_DISCONNECTED`, `CLIENT_REGISTERED`, `CLIENT_SHUTDOWN_FINAL`). Event data is rich and structured, often including parsed IRCv3 message tags.
- **Data Files:** Scripts can manage their own data files within a dedicated subdirectory: `scripts/data/<script_module_name>/`.
- **Comprehensive API Access (`ScriptAPIHandler`):** Scripts interact with the client through a `ScriptAPIHandler` instance (passed as `self.api` to script instances), providing methods to:

  #### Sending Messages & Commands:

  - `api.send_raw(command_string: str)`
  - `api.send_message(target: str, message: str)` (for PRIVMSG)
  - `api.send_action(target: str, action_text: str)` (for CTCP ACTION /me)
  - `api.send_notice(target: str, message: str)` (_New - assuming you'll add this to ScriptAPIHandler based on `/notice` command_)
  - `api.join_channel(channel_name: str, key: Optional[str] = None)`
  - `api.part_channel(channel_name: str, reason: Optional[str] = None)`
  - `api.set_nick(new_nick: str)`
  - `api.set_topic(channel_name: str, new_topic: str)`
  - `api.set_channel_mode(channel_name: str, modes: str, *mode_params: str)`
  - `api.kick_user(channel_name: str, nick: str, reason: Optional[str] = None)`
  - `api.invite_user(nick: str, channel_name: str)`
  - `api.quit(reason: Optional[str] = None)` (_New - assuming you'll add this_)

  #### Interacting with Client UI (when UI is active):

  - `api.add_message_to_context(context_name: str, text: str, color_key: str = "system", prefix_time: bool = True)`

  #### Accessing Client & Server Information:

  - `api.get_client_nick() -> str`
  - `api.get_current_context_name() -> Optional[str]`
  - `api.get_active_context_type() -> Optional[str]`
  - `api.is_connected() -> bool`
  - `api.get_server_info() -> Dict[str, Any]` (server, port, ssl)
  - `api.get_server_capabilities() -> Set[str]` (enabled CAPs)
  - `api.get_joined_channels() -> List[str]`
  - `api.get_channel_users(channel_name: str) -> Optional[Dict[str, str]]` (nick: prefix map)
  - `api.get_channel_topic(channel_name: str) -> Optional[str]`
  - `api.get_context_info(context_name: str) -> Optional[Dict[str, Any]]` (detailed info about a context)
  - `api.get_context_messages(context_name: str, count: Optional[int] = None) -> Optional[List[Tuple[str, Any]]]` (_New - for Stage 4 testing_)

  #### Trigger Management (if `enable_trigger_system` is true):

  - `api.add_trigger(event_type: str, pattern: str, action_type: str, action_content: str) -> Optional[int]`
  - `api.remove_trigger(trigger_id: int) -> bool`
  - `api.list_triggers(event_type: Optional[str] = None) -> List[Dict[str, Any]]`
  - `api.set_trigger_enabled(trigger_id: int, enabled: bool) -> bool`

  #### Registering Script Functionality:

  - `api.register_command(command_name: str, handler_function: Callable, help_text: str = "", aliases: List[str] = [])`
  - `api.subscribe_to_event(event_name: str, handler_function: Callable)`
  - `api.register_help_text(command_name: str, usage_str: str, description_str: str = "", aliases: Optional[List[str]] = None)`

  #### Logging & Data:

  - `api.log_info(message: str)`, `api.log_warning(message: str)`, `api.log_error(message: str)` (automatically prefixed with script name).
  - `api.request_data_file_path(data_filename: str) -> str` (gets path like `scripts/data/your_script_name/data_filename`)

### Creating Scripts:

1.  Create a Python file (e.g., `my_script.py`) in the `scripts/` directory.
2.  Define a class for your script. It's recommended to inherit from `ScriptBase` (found in `script_base.py`) for helper methods like `load_list_from_data_file` and `ensure_command_args`.

```python
# In scripts/my_cool_script.py
from script_base import ScriptBase # Assuming script_base.py is in the project root or accessible
# Or adjust path if script_base.py is elsewhere, e.g., from ..script_base import ScriptBase

class MyScript(ScriptBase): # Inherit from ScriptBase
    def __init__(self, api_handler): # api_handler is an instance of ScriptAPIHandler
        super().__init__(api_handler) # Call ScriptBase constructor
        # self.api is now available
        # self.script_name is also available from ScriptBase

    def load(self):
        self.api.log_info("MyCoolScript is loading!") # Log will be prefixed with 'my_cool_script'
        self.api.register_command("mycmd", self.handle_mycmd, "A cool command from MyCoolScript")
        self.api.subscribe_to_event("PRIVMSG", self.handle_all_privmsgs)

    def handle_mycmd(self, args_str: str, event_data_command: dict):
        self.api.send_message(event_data_command['active_context_name'], f"MyCmd executed with: {args_str}")

    def handle_all_privmsgs(self, event_data_privmsg: dict):
        # Example: self.api.log_info(f"Saw message: {event_data_privmsg['message']}")
        pass

# Required factory function for the ScriptManager
def get_script_instance(api_handler):
    return MyScript(api_handler)
```

3.  PyRC will automatically discover and attempt to load your script on startup if it's not in the `disabled_scripts` list.

### Key Script Events & Event Data

Scripts can subscribe to various events. Event handler functions receive a single dictionary argument, `event_data`, containing event-specific information. All `event_data` dictionaries now consistently include:

- `timestamp`: float, from `time.time()`
- `raw_line`: str, the original raw IRC line that triggered the event (if applicable)
- `client_nick`: str, the current nick of the PyRC client

**Client Lifecycle Events:**

- `CLIENT_CONNECTED`: Fired when TCP/IP connection is up and CAP negotiation begins.
  - `event_data` additional keys: `server` (str), `port` (int), `nick` (str - current client nick), `ssl` (bool).
- `CLIENT_DISCONNECTED`: Fired when connection is lost/closed.
  - `event_data` additional keys: `server` (str), `port` (int).
- `CLIENT_REGISTERED`: Fired upon receiving RPL_WELCOME (001).
  - `event_data` additional keys: `nick` (str - confirmed client nick), `server_message` (str - welcome message).
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

### Default Scripts & Help System

PyRC ships with several default scripts in the `scripts/` directory:

- `default_fun_commands.py`: Implements `/slap`, `/8ball`, `/dice`, etc.
- `default_exit_handler.py`: Displays the exit message when `CLIENT_SHUTDOWN_FINAL` is dispatched.
- `default_random_messages.py`: Provides random quit/part messages if configured.
- `event_test_script.py`: Logs various events for debugging/development.
- `ai_api_test_script.py`: Demonstrates and tests the enhanced `ScriptAPIHandler` for programmatic use, including automated tests for various features.
- `test_script.py`: Basic command registration example.

The client's `/help` system is driven by `scripts/data/default_help/command_help.ini` for core commands. Scripts can register help for their own commands using `self.api.register_help_text()`.

## Recent Changes and Bug Fixes

### Latest Updates

- Fixed Pylance type checking errors related to network attribute access
- Improved code consistency by standardizing on `network_handler` attribute name
- Enhanced type safety in script management system
- Fixed attribute access in network-related operations
- Added support for headless operation mode
- Enhanced ScriptAPIHandler for AI integration
- Added new IRCv3 message-tags support
- Improved event data structure with consistent fields

### Known Issues

- None currently reported

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
