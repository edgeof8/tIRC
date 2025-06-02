# PyRC - Python Terminal IRC Client

PyRC is a modern, terminal-based IRC (Internet Relay Chat) client written in Python. It aims to provide a feature-rich, yet lightweight and user-friendly experience for IRC users who prefer the command line.

## Key Features

- **Text-based UI:** Clean and navigable interface using the Python `curses` library.
- **Channel and Query Windows:** Separate, consistently managed contexts for channels (case-insensitive handling, e.g., #channel and #Channel are treated as the same) and private messages.
- **mIRC-like UI Flow:** Starts in the "Status" window and automatically switches to a channel upon successful join.
- **IRCv3 Support:** Robust CAP negotiation (including sasl, multi-prefix, server-time, echo-message, etc.) and SASL PLAIN authentication for secure login.
- **Comprehensive Command Set:** Supports a wide array of standard IRC commands and client-specific utility commands, many now managed via the scripting system.
- **Dynamic Configuration:** View and modify client settings on-the-fly using the `/set` command. Changes are saved to `pyterm_irc_config.ini`. Reload configuration with `/rehash`.
- **Ignore System:** Powerful ignore list for users/hostmasks with wildcard support, managed via `/ignore`, `/unignore`, `/listignores`.
- **Advanced Trigger System (`/on` command):**
  - Define custom actions based on IRC events (TEXT, ACTION, JOIN, PART, QUIT, KICK, MODE, TOPIC, NICK, NOTICE, INVITE, CTCP, RAW).
  - Actions can be standard client commands or arbitrary Python code snippets.
  - Utilize regex capture groups ($0, $1, etc.) and extensive event-specific variables ($nick, $channel, $$1, $1-, etc.) in both command and Python actions.
  - _(Note: This system coexists with the new script-based event handling.)_
- **Extensible Scripting System:**
  - Load custom Python scripts from a `scripts/` directory to add new commands, respond to IRC/client events, and modify client behavior.
  - Default features like "fun" commands (`/slap`, `/8ball`), randomized quit/part messages, and the client exit screen are implemented as default scripts.
  - Scripts have access to a controlled API (`ScriptAPIHandler`) for safe interaction with the client.
- **Logging:**
  - Comprehensive main log file for debugging and session history.
  - Optional per-channel logging to separate files.
  - Raw IRC message logging to UI toggleable with `/rawlog`.
- **Code Modularity:** Significantly improved structure and maintainability of core components:
  - Specialized handlers for IRC protocol parsing, numeric replies, command groups (now partially script-based), connection lifecycle (CAP, SASL, registration).
- **Tab Completion:** For commands (including script-added commands) and nicks in the current context.
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
default_port = 6697
default_ssl = true
default_nick = PyTermUser
default_channels = #python,#testchannel
password =
nickserv_password =
verify_ssl_cert = true
auto_reconnect = true

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

[General]
# leave_message setting is now superseded by the default_random_messages.py script
# but can serve as a fallback if the script is disabled or fails to load messages.

[IgnoreList]
# Managed by /ignore commands, usually not edited manually.
# Stores ignore patterns, e.g., someuser!*@* = ignored
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

PyRC features a powerful scripting system allowing users to extend its functionality. Scripts are Python files placed in the `scripts/` directory.

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

### Default Scripts:

- `default_fun_commands.py`: Implements commands like `/slap`, `/8ball`, etc. Uses data files from `scripts/data/default_fun_commands/`.
- `default_exit_handler.py`: Displays the full-screen exit message when the client shuts down.
- `default_random_messages.py`: Provides randomized quit and part messages. Loads messages from `scripts/data/default_random_messages/`.
- `default_help_handler.py` (Conceptual - help is currently loaded by ScriptManager directly): The primary help texts are loaded from `scripts/data/default_help/command_help.ini` by the ScriptManager.
- `event_test_script.py`: A sample script demonstrating various event subscriptions.
- `test_script.py`: A basic example of command registration.

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
