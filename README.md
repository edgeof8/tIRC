# PyRC - Python Terminal IRC Client

PyRC is a modern, terminal-based IRC (Internet Relay Chat) client written in Python. It aims to provide a feature-rich, yet lightweight and user-friendly experience for IRC users who prefer the command line, and is increasingly being adapted for programmatic use and AI integration.

## Key Features

- **Text-based UI:** Clean and navigable interface using the Python `curses` library (optional for headless operation).
- **Split-Screen Support:** Horizontal split-screen mode with independent scrolling and context management for each pane.
- **Channel and Query Windows:** Separate, consistently managed contexts for channels (case-insensitive handling, e.g., #channel and #Channel are treated as the same) and private messages.
- **mIRC-like UI Flow:** Starts in the "Status" window and automatically switches to a channel upon successful join (when UI is active).
- **IRCv3 Support:** Robust CAP negotiation (including sasl, multi-prefix, server-time, echo-message, message-tags, etc.) and SASL PLAIN authentication for secure login.
- **Comprehensive Command Set:** Supports a wide array of standard IRC commands and client-specific utility commands, many now managed via the scripting system.
- **Dynamic Configuration:** View and modify client settings on-the-fly using the `/set` command. Changes are saved to `pyterm_irc_config.ini`. Reload configuration with `/rehash`.
- **Ignore System:** Powerful ignore list for users/hostmasks with wildcard support, managed via `/ignore`, `/unignore`, `/listignores`.
- **Advanced Trigger System (`/on` command):**
  - Define custom actions based on IRC events (TEXT, ACTION, JOIN, PART, QUIT, KICK, MODE, TOPIC, NICK, NOTICE, INVITE, CTCP, RAW).
  - Actions can be standard client commands or arbitrary Python code snippets.
  - Utilize regex capture groups ($0, $1, etc.) and extensive event-specific variables ($nick, $channel, $$1, $1-, etc.) in both command and Python actions.
  - Fully manageable via the Scripting API.
- **Extensible Scripting System (Python):**
  - Load custom Python scripts from a `scripts/` directory to add new commands, respond to IRC/client events, and modify client behavior.
  - Default features like "fun" commands (`/slap`, `/8ball`), randomized quit/part messages, and the client exit screen are implemented as default scripts.
  - Scripts have access to a rich `ScriptAPIHandler` for safe and powerful interaction with the client.
- **Headless Operation:**
  - Can be run with a `--headless` flag, disabling the `curses` UI for use as an IRC backend or for AI agents. Core logic and scripting remain fully functional.
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
- `pyfiglet` for the `/ascii` command (`pip install pyfiglet`). It's included in `requirements.txt`.

## Installation

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/edgeof8/PyRC.git # Or your fork's URL
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

**`pyterm_irc_config.ini` Structure (Key Sections):**

```ini
[Connection]
default_server = irc.libera.chat
default_port = 6667
default_ssl = true
default_nick = YourNick
default_channels = #python,#testchannel
password = optional_server_password
nickserv_password = optional_nickserv_password
auto_reconnect = true
verify_ssl_cert = true

[UI]
message_history_lines = 500
colorscheme = default

[Logging]
log_enabled = true
log_file = pyrc.log
log_level = INFO
log_max_bytes = 5242880
log_backup_count = 3
channel_log_enabled = true

[Ignore]
patterns = *bot*,*spam*
```

## Usage

Once installed and configured, run PyRC from its root directory:

```bash
python pyrc.py
```

Or, to specify connection parameters via command line (overriding pyterm_irc_config.ini defaults):

```bash
python pyrc.py <server> -p <port> -n <nick> -c <#channel> [--ssl | --no-ssl]
```

Example: `python pyrc.py irc.example.com -p 6667 -n MyPyRCNick -c #chat --no-ssl`

## Basic Commands

PyRC supports a variety of commands. Type `/help` within the client for a list of commands and their aliases, or `/help <command>` for specific command usage. The help system is data-driven from scripts/data/default_help/command_help.ini and can be extended by scripts.

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
- `/rehash`: Reloads pyterm_irc_config.ini.
- `/save`: Saves current configuration changes to pyterm_irc_config.ini.
- `/ignore <nick|hostmask>`: Ignores a user/hostmask.
- `/unignore <nick|hostmask>`: Removes an ignore.
- `/listignores`: Lists ignored patterns.
- `/rawlog [on|off|toggle]`: Toggles display of raw IRC messages in Status window.
- `/lastlog <pattern>`: Searches message history of the active window.
- `/raw <raw_irc_command>` (Aliases: `/quote`, `/r`): Sends a raw command to the server.

### Fun Commands (from default_fun_commands.py script):

- `/slap <nickname>`: Slaps a user.
- `/8ball <question>`: Asks the Magic 8-Ball.
- `/dice <NdN>` (Alias: `/roll`): Rolls dice.
- `/rainbow <text>`: Sends text in rainbow colors.
- `/reverse <text>`: Sends text reversed.
- `/wave <text>`: Sends text with a wave effect.
- `/ascii <text>`: Converts text to ASCII art.

## Scripting System

PyRC features a powerful and flexible scripting system, allowing users to extend and customize client functionality using Python. Scripts can introduce new commands, react to IRC and client events, manage their own data, and much more. All scripts are placed in the `scripts/` directory in PyRC's root folder and are loaded automatically on startup.

### Key Scripting Capabilities:

- **Command Registration:** Scripts can define new client commands with custom handlers, help text, and aliases.
- **Event Subscription:** Scripts can subscribe to a wide range of IRC events (e.g., PRIVMSG, JOIN, NICK, MODE) and client lifecycle events (e.g., CLIENT_CONNECTED, CLIENT_DISCONNECTED, CLIENT_SHUTDOWN_FINAL).
- **Data Files:** Scripts can manage their own data files within a dedicated subdirectory: `scripts/data/<script_module_name>/`.
- **API Access:** Scripts interact with the client through a ScriptAPIHandler, providing methods to:
  - Send IRC messages and raw commands.
  - Add messages to client windows.
  - Access client information (nick, active context).
  - Log messages.
  - Register commands, help texts, and subscribe to events.
  - Request paths to their data files.

### Creating Scripts:

1. Create a Python file (e.g., `my_script.py`) in the `scripts/` directory.
2. Define a class for your script (optionally inheriting from `ScriptBase` in `script_base.py` for helper methods).
3. The class `__init__` should accept an `api_handler` argument.
4. Implement a `load(self)` method where you register commands, subscribe to events, etc., using `self.api.<method_name>()`.
5. Provide a top-level factory function in your script file:

```python
def get_script_instance(api_handler):
    return MyScriptClass(api_handler)
```

PyRC will automatically discover and load your script on startup.

## Triggers (/on command)

The legacy `/on` trigger system allows defining custom actions based on IRC events using regular expressions. This system coexists with the new script-based event handling.

- `/on add <event> <pattern> <TYPE> <action_content>`: Adds a new trigger.
- `/on list [event]`: Lists triggers.
- `/on remove <id>`: Removes a trigger.

And more subcommands. Type `/help on` or `/on` in the client for details.

### Script Structure Basics

A typical PyRC script is a Python file (e.g., `my_script.py`) in the `scripts/` directory. It should contain:

1.  A class that encapsulates the script's logic. This class often inherits from `ScriptBase` (found in `script_base.py` in the project root) for convenience, though it's not strictly required.
2.  An `__init__(self, api_handler)` method that receives and stores an instance of `ScriptAPIHandler`. This `api_handler` is the script's gateway to interacting with PyRC.
3.  A `load(self)` method. This method is called by PyRC when the script is loaded. It's the primary place to register commands, subscribe to events, and perform any initial setup.
4.  A top-level factory function named `get_script_instance(api_handler)` that returns an instance of your script's class.

**Example Skeleton:**

```python
# scripts/my_cool_script.py
from ..script_base import ScriptBase # If script_base.py is in parent (project root)

class MyCoolScript(ScriptBase): # Inheriting from ScriptBase is optional but recommended
    def __init__(self, api_handler):
        super().__init__(api_handler) # Call if inheriting
        # self.api = api_handler # Or store directly if not inheriting
        self.script_name = self.__class__.__module__ # Useful for logging

    def load(self):
        self.api.log_info(f"{self.script_name} is loading!")
        # Register commands:
        # self.api.register_command("mycommand", self.handle_my_command, help_text="Does something cool.")
        # Subscribe to events:
        # self.api.subscribe_to_event("PRIVMSG", self.on_privmsg)

    # def handle_my_command(self, args_str, event_data_command):
    #     # ... command logic ...
    #     self.api.add_message_to_context(event_data_command['active_context_name'], "My command ran!")

    # def on_privmsg(self, event_data_msg):
    #     # ... event handling logic ...
    #     # self.api.log_info(f"PRIVMSG from {event_data_msg['nick']}: {event_data_msg['message']}")

# Required factory function
def get_script_instance(api_handler):
    return MyCoolScript(api_handler)
```

### Script API Overview (`self.api.*`)

Scripts interact with PyRC through the `ScriptAPIHandler` instance (typically `self.api`). Key methods include:

- **Sending Messages & Commands:**
  - `send_raw(command_string: str)`: Sends any raw IRC command string directly to the server.
  - `send_privmsg(target: str, message: str)`: Sends a `PRIVMSG` to a channel or user.
  - `send_notice(target: str, message: str)`: Sends a `NOTICE` to a channel or user.
  - `send_action(target: str, action_text: str)`: Sends a CTCP ACTION (e.g., `/me waves`) to a channel or user.
- **Interacting with Client UI:**
  - `add_message_to_context(context_name: str, text: str, color_key: str = "system", prefix_time: bool = True)`: Adds a formatted message line to the specified window/context in the PyRC UI.
- **Accessing Client Information:**
  - `get_client_nick() -> str`: Returns the client's current nickname.
  - `get_current_context_name() -> Optional[str]`: Returns the name of the currently active window (e.g., "#channel", "QueryNick", "Status").
  - `get_active_context_type() -> Optional[str]`: Returns the type (`channel`, `query`, `status`, etc.) of the active window.
- **Registering Functionality:**
  - `register_command(command_name: str, handler_function: Callable, help_text: str = "", aliases: List[str] = [])`: Registers a new slash command (e.g., `/mycmd`).
    - `handler_function` should have the signature: `def my_handler(self, args_str: str, event_data: Dict[str, Any]): ...`
    - `event_data` for commands includes: `{'client_logic_ref', 'raw_line', 'command', 'args_str', 'client_nick', 'active_context_name', 'script_name'}`.
  - `subscribe_to_event(event_name: str, handler_function: Callable)`: Subscribes a script method to be called when a specific client or IRC event occurs.
    - `handler_function` should have the signature: `def my_event_handler(self, event_data: Dict[str, Any]): ...` (See "Key Script Events" below for `event_data` contents).
  - `register_help_text(command_name: str, usage_str: str, description_str: str = "", aliases: Optional[List[str]] = None)`: Registers detailed help for a command. This is useful if a script provides commands and wants to integrate with the `/help` system. `usage_str` should be a concise usage line (e.g., "Usage: /mycmd <option>"), and `description_str` a more detailed explanation.
- **Logging:**
  - `log_info(message: str)`, `log_warning(message: str)`, `log_error(message: str)`: Writes messages to PyRC's main log file, automatically prefixed with the script's module name for easy identification.
- **Data File Management:**
  - `request_data_file_path(data_filename: str) -> str`: Returns the absolute path to a file within the script's dedicated data directory. This directory is automatically created if it doesn't exist at `scripts/data/<script_module_name>/`. Scripts should use this method to reliably access their configuration or data files (e.g., `self.api.request_data_file_path("my_settings.txt")`).

### Key Script Events

Scripts can subscribe to various events. Event handler functions (see `subscribe_to_event` above) receive a single dictionary argument, `event_data`, containing event-specific information. All `event_data` dictionaries also include a `timestamp` (float, from `time.time()`).

- **Client Lifecycle Events:**
  - `CLIENT_CONNECTED`: Fired when a TCP/IP connection to the server is established and initial IRC CAP negotiation begins.
    - `event_data` keys: `server` (str), `port` (int), `nick` (str - current client nick), `ssl` (bool).
  - `CLIENT_DISCONNECTED`: Fired when the connection to the server is lost or closed.
    - `event_data` keys: `server` (str), `port` (int).
  - `CLIENT_REGISTERED`: Typically fired upon receiving RPL_WELCOME (001) from the server, indicating successful registration.
    - `event_data` keys: `nick` (str - confirmed client nick), `server_message` (str - the welcome message), `raw_line` (str).
  - `CLIENT_SHUTDOWN_FINAL`: Fired just before the application fully exits, _after_ the curses UI has been shut down. Useful for cleanup tasks that need to `print()` directly to the console (e.g., the default exit screen script).
- **IRC Message & Command Events:**
  - `PRIVMSG`: For channel messages and private messages sent by other users or the client itself (if `echo-message` CAP is active).
    - `event_data` keys: `nick` (str - sender's nick), `userhost` (str - sender's full user@host), `target` (str - channel or your nick), `message` (str - the content), `is_channel_msg` (bool), `client_nick` (str - your current nick), `raw_line` (str).
  - `NOTICE`: For IRC NOTICEs.
    - `event_data` keys: `nick` (str - sender's nick, or server name if server notice), `userhost` (str - sender's full user@host, or server name), `target` (str - channel or your nick), `message` (str - the content), `is_channel_notice` (bool), `client_nick` (str), `raw_line` (str).
  - `JOIN`: When a user (including the client) joins a channel.
    - `event_data` keys: `nick` (str), `userhost` (str), `channel` (str), `is_self` (bool - true if it's the client joining), `client_nick` (str), `raw_line` (str).
  - `PART`: When a user (including the client) parts a channel.
    - `event_data` keys: `nick` (str), `userhost` (str), `channel` (str), `reason` (str - part message, if any), `is_self` (bool), `client_nick` (str), `raw_line` (str).
  - `QUIT`: When a user quits the IRC server.
    - `event_data` keys: `nick` (str), `userhost` (str), `reason` (str - quit message, if any), `client_nick` (str), `raw_line` (str).
  - `NICK`: When a user (including the client) changes their nickname.
    - `event_data` keys: `old_nick` (str), `new_nick` (str), `userhost` (str), `is_self` (bool), `client_nick` (str - current nick after potential change if self), `raw_line` (str).
  - `MODE`: When a mode change occurs on a channel or user.
    - `event_data` keys: `nick` (str - nick of user setting the mode, or server name), `userhost` (str), `target` (str - channel or nick affected by mode), `modes_and_params` (str - the mode string and its parameters, e.g., "+o someuser"), `client_nick` (str), `raw_line` (str).
  - `TOPIC`: When a channel topic is changed or viewed (on join).
    - `event_data` keys: `nick` (str - nick of user changing topic, or server on join), `userhost` (str), `channel` (str), `topic` (str - the new topic), `client_nick` (str), `raw_line` (str).
- **Raw IRC Lines:**
  - `RAW_IRC_LINE`: Fired for _every_ complete, raw line received from the server _before_ PyRC's internal parsing. Useful for advanced or custom protocol handling.
    - `event_data` keys: `raw_line` (str - the unmodified line), `client_nick` (str).
  - _(Note: For reacting to specific IRC numeric replies (e.g., RPL_WHOISUSER 311), scripts currently should subscribe to `RAW_IRC_LINE` and parse the numeric from the `raw_line` content. Future API enhancements might provide direct events for all numerics.)_

### Default Scripts & Help System

PyRC ships with several default scripts in the `scripts/` directory to provide core and extended functionality:

- `default_fun_commands.py`: Implements "fun" commands like `/slap`, `/8ball`, `/dice`, etc. It loads its data (e.g., slap items, 8-ball answers) from files in `scripts/data/default_fun_commands/`.
- `default_exit_handler.py`: Subscribes to the `CLIENT_SHUTDOWN_FINAL` event to display the full-screen thank you message when PyRC exits.
- `default_random_messages.py`: Provides randomized quit and part messages if the user doesn't specify one. It loads message templates from `scripts/data/default_random_messages/`.
- `event_test_script.py`: A demonstration script that logs various IRC and client events. Useful for testing or as a template for new event-driven scripts.
- `test_script.py`: A very basic example primarily showing command registration.

The client's `/help` system is primarily driven by `scripts/data/default_help/command_help.ini`. This file defines help for core client commands. Scripts can also register help for their own commands using `self.api.register_help_text()`, which will then be available via `/help <script_command>`.

### Script Lifecycle

- **Loading:** All valid `.py` files in the `scripts/` directory (that are not prefixed with `_` and contain a `get_script_instance` factory function) are loaded when PyRC starts. The `load()` method of each script instance is then called.
- **Unloading:** The `ScriptBase` class defines an optional `unload(self)` method. While PyRC does not currently support dynamic unloading/reloading of scripts at runtime, this method is reserved for future use if such functionality is added (e.g., for script cleanup).

## Contributing

Contributions are welcome! Please:

1. Fork the repository.
2. Create a new branch (`git checkout -b feature/your-feature-name`).
3. Make your changes and commit them (`git commit -am 'Add some feature'`).
4. Push to the branch (`git push origin feature/your-feature-name`).
5. Create a new Pull Request.

For major changes, please open an issue first to discuss your ideas.

## License

This project is licensed under the MIT License.

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

## Headless Operation

PyRC can be run in a headless mode, without the curses user interface. This is useful for bots, automated scripts, or AI integrations where a visual UI is not needed.

To run in headless mode, use the `--headless` command-line flag:

```bash
python pyrc.py --server irc.example.com --nick MyHeadlessBot --headless
```

In headless mode:

- No UI is drawn
- All core IRC logic, including connection, CAP/SASL, event processing, and the scripting system, remains fully functional
- Scripts can interact with the IRC server using the ScriptAPIHandler
- Logging continues as configured
- The client can be shut down via SIGINT (Ctrl+C) or programmatically by a script calling a quit/disconnect API function
- The `headless_message_history_lines` config option can be used to set a different message history size for contexts in headless mode, potentially reducing memory usage
