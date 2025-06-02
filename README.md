# PyRC - Python Terminal IRC Client

PyRC is a modern, terminal-based IRC (Internet Relay Chat) client written in Python. It aims to provide a feature-rich, yet lightweight and user-friendly experience for IRC users who prefer the command line.

## Key Features

- **Text-based UI:** Clean and navigable interface using the `curses` library.
- **Channel and Query Windows:** Separate, consistently managed contexts for channels (case-insensitive handling, e.g., `#channel` and `#Channel` are treated as the same) and private messages.
- **mIRC-like UI Flow:** Starts in the "Status" window and automatically switches to a channel upon successful join.
- **IRCv3 Support:** Robust CAP negotiation and SASL PLAIN authentication for secure login.
- **Improved Command Handling:**
  - `/part` command now reliably updates UI, clears user lists, and closes the channel window.
- **Configuration File:** Easy setup via `pyterm_irc_config.ini`.
- **Logging:** Comprehensive logging for debugging and session history.
- **Tab Completion:** For commands and nicks.
- **SSL/TLS Encryption:** Secure connections to IRC servers, with an option (`verify_ssl_cert` in config) to allow connections to servers with self-signed certificates.
- **Dynamic Configuration:** View and modify client settings on-the-fly using the `/set` command. Changes are saved to `pyterm_irc_config.ini` and some may apply immediately while others might require a restart.
- **Code Modularity:** Recent refactoring has significantly improved the structure and maintainability of core components:
  - **IRC Protocol Parsing:** The `irc_protocol.py` module has been refactored. The `IRCMessage` class is now in `irc_message.py`, and all numeric reply handlers (e.g., for RPL_WELCOME, ERR_NOSUCHNICK) are in `irc_numeric_handlers.py`.
  - **Command Handling:** The `command_handler.py` module has been modularized. Specific command groups are now handled by dedicated classes:
    - `FunCommandsHandler` (`fun_commands_handler.py`) for commands like `/slap`, `/8ball`.
    - `ChannelCommandsHandler` (`channel_commands_handler.py`) for commands like `/join`, `/part`, `/topic`.
    - `ServerCommandsHandler` (`server_commands_handler.py`) for commands like `/connect`, `/quit`.
    - `InformationCommandsHandler` (`information_commands_handler.py`) for commands like `/who`, `/whowas`, `/list`, `/names`.
  - **Connection & Registration Logic:** The `irc_client_logic.py` module has been refactored to delegate core connection, capability negotiation (CAP), SASL authentication, and post-registration tasks to specialized handlers:
    - `CapNegotiator` (`cap_negotiator.py`): Manages the CAP negotiation lifecycle.
    - `SaslAuthenticator` (`sasl_authenticator.py`): Handles SASL PLAIN authentication. It has been refactored to dynamically fetch the client's current nickname from `IRCClient_Logic` at the time of authentication, ensuring the most up-to-date nick is used even if changes occurred shortly before SASL credential transmission.
    - `RegistrationHandler` (`registration_handler.py`): Orchestrates NICK/USER registration, auto-channel joins, and NickServ identification.
- **Advanced Trigger System:**
  - Define custom actions based on IRC events (TEXT, ACTION, JOIN, etc.).
  - Actions can be standard client commands or **arbitrary Python code snippets**.
  - Utilize **regex capture groups** from trigger patterns as variables (`$0`, `$1`, etc.) in both command and Python actions.
- **Multiple Server Connections:** (Planned)
- **Color Themes:** (Basic support, planned for expansion)

## Prerequisites

- Python 3.8 or higher.
- `pip` (Python package installer).

## Installation

1.  **Clone the repository (or download the source code):**

    ```bash
    git clone https://github.com/yourusername/pyrc.git  # Replace with your actual repository URL
    cd pyrc
    ```

2.  **Create a virtual environment (recommended):**

    ```bash
    python -m venv venv
    ```

    Activate it:

    - Windows: `venv\Scripts\activate`
    - Linux/macOS: `source venv/bin/activate`

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

PyRC uses a configuration file named `pyterm_irc_config.ini` located in the root directory of the application.

1.  **Copy the example configuration (if it doesn't exist or you want to start fresh):**
    If an example like `pyterm_irc_config.ini.example` is provided, copy it to `pyterm_irc_config.ini`.

    ```bash
    # On Linux/macOS:
    # cp pyterm_irc_config.ini.example pyterm_irc_config.ini
    # On Windows:
    # copy pyterm_irc_config.ini.example pyterm_irc_config.ini
    ```

    If no example exists, PyRC might create a default one on first run, or you may need to create it manually based on the structure below.
    You can also view and modify many of these settings directly within the client using the `/set` command (see Basic Commands section).

2.  **Edit `pyterm_irc_config.ini`:**
    Open the file in a text editor and customize the settings. Key settings include:

    - `[Connection]`

      - `default_server`: The IRC server address (e.g., `irc.libera.chat`).
      - `default_port`: The server port (e.g., `6697` for SSL, `6667` for non-SSL).
      - `default_ssl`: `true` or `false` to enable/disable SSL.
      - `default_nick`: Your preferred nickname.
      - `default_channels`: Comma-separated list of channels to auto-join (e.g., `#python,#testchannel`).
      - `password`: Server password, if required by the server (rarely used for user connections).
      - `nickserv_password`: Your NickServ password for services authentication. Leave blank if not used.
      - `verify_ssl_cert`: `true` or `false`. Set to `false` to allow SSL connections to servers using self-signed certificates (less secure, use with caution). Defaults to `true` if not specified.

    - `[UI]`

      - `message_history_lines`: Number of lines to keep in channel/query buffers (e.g., `500`).
      - `colorscheme`: (e.g., `default` - future support for more themes).

    - `[Logging]`
      - `log_enabled`: `true` or `false`.
      - `log_file`: Name of the log file (e.g., `pyrc.log`). Defaults to `logs/pyrc.log`.
      - `log_level`: Logging verbosity (e.g., `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
      - `log_max_bytes`: Maximum size of a log file before rotation (e.g., `5242880` for 5MB).
      - `log_backup_count`: Number of backup log files to keep (e.g., `3`).

## Usage

Once installed and configured, run PyRC from its root directory:

```bash
python pyrc.py
```

### Basic Commands

PyRC supports a variety of commands, most of which are standard IRC commands. Type `/help` within the client for a list of available commands and their aliases.

- `/join #channelname`: Joins the specified channel.
- `/part [message]`: Leaves the current channel (closing its window and optionally sending a message).
- `/msg <nickname> <message>`: Sends a private message to a user.
- `/query <nickname>`: Opens a new query window with the specified user.
- `/nick <newnickname>`: Changes your nickname.
- `/quit [message]`: Disconnects from the server and exits PyRC.
- `/connect <server>[:<port>] [ssl|nossl] [#channel1,#channel2,...]`: Connects to a new server.
- `/server <server_alias_or_host>`: Switches to a different server connection (if multiple active - planned feature).
- `/wc` or `/close`: Closes the current query window or parts the current channel.
- `/clear`: Clears the current window's messages.
- `/set`: Lists all current configuration settings.
- `/set <key>`: Displays the value of a specific setting (e.g., `/set default_nick`).
- `/set <section.key>`: Displays the value of a specific setting within a section (e.g., `/set Connection.default_nick`).
- `/set <section.key> <value>`: Modifies a setting and saves it to `pyterm_irc_config.ini` (e.g., `/set Connection.default_nick MyNewNick`).
- `/ignore <nick|hostmask>`: Ignores messages from the specified user or hostmask (e.g., `*!*@some.host`).
- `/unignore <nick|hostmask>`: Removes an ignore pattern.
- `/listignores`: Lists all current ignore patterns.
- `/who [<target>]`: Retrieves WHO information for `<target>` (nick, channel, mask). Defaults to current channel if active and no target given.
- `/whowas <nick> [count [target_server]]`: Retrieves information about a nickname that is no longer in use.
- `/list [pattern]`: Lists channels on the server, optionally matching `[pattern]`. Output is currently shown in the Status window.
- `/names [channel]`: Lists users in `[channel]` or all joined channels if `[channel]` is omitted. Updates the user list in the channel window.
- `/help [command]`: Displays general help or help for a specific command.
- `PageUp`/`PageDown`: Scroll through the message buffer in the current window.
- `Ctrl+N`/`Ctrl+P` (or `/nextwindow`, `/prevwindow`): Switch to the next/previous active context (channel/query/status window).
- `Ctrl+U` (or `/u`, `/userlistscroll [offset]`): Scroll the user list in a channel window.

#### Client Management Commands

- `/reconnect`: Disconnects from the current server and attempts to reconnect using the same server settings.
- `/rehash`: Reloads the `pyterm_irc_config.ini` configuration file. Note that some changes (especially to core logging setup or server connection details if manually edited in the INI) may require a client restart or a `/reconnect` to take full effect.
- `/rawlog [on|off|toggle]`: Toggles or sets the display of raw IRC messages (both sent `C >>` and received `S <<`) in the Status window. Useful for debugging.

#### Channel Moderation Commands

These commands are typically used by channel operators to manage users and channel settings.

- `/ban <nick|hostmask>`: Bans the specified nickname or hostmask from the current channel.
- `/unban <hostmask>`: Removes a ban for the specified hostmask from the current channel.
- `/mode [<target>] <modes_and_params>`: Sets or views modes on a target (channel or user).
- If `<target>` is omitted, it defaults to the current channel.
- Example: `/mode +o someuser` (ops `someuser` in current channel)
- Example: `/mode #channel -v anotheruser` (devoices `anotheruser` in `#channel`)
- Example: `/mode #channel +imnt` (sets modes `i`, `m`, `n`, `t` on `#channel`)
- `/op <nick>` (Alias: `/o <nick>`): Grants channel operator status to `<nick>` in the current channel.
- `/deop <nick>` (Alias: `/do <nick>`): Removes channel operator status from `<nick>` in the current channel.
- `/voice <nick>` (Alias: `/v <nick>`): Grants voice status to `<nick>` in the current channel.
- `/devoice <nick>` (Alias: `/dv <nick>`): Removes voice status from `<nick>` in the current channel.

### Triggers (`/on` command)

PyRC features a powerful trigger system that allows you to automate responses and actions based on IRC events.

- `/on add <event> <pattern> <TYPE> <action_content>`: Adds a new trigger.

  - `<event>`: The IRC event to trigger on (e.g., `TEXT`, `ACTION`, `JOIN`, `PART`, `QUIT`, `KICK`, `MODE`, `TOPIC`, `NICK`, `NOTICE`, `INVITE`, `CTCP`, `RAW`).
  - `<pattern>`: A regular expression to match against relevant data for the event (e.g., the message content for `TEXT` events).
  - `<TYPE>`:
    - `CMD`: The `action_content` is a client command (e.g., `/say Hello $nick`).
    - `PY`: The `action_content` is a Python code snippet.
  - `<action_content>`: The command to execute or the Python code to run.

- `/on list [event]`: Lists currently defined triggers, optionally filtered by event type.
- `/on remove <id>`: Removes a trigger by its ID.
- `/on enable <id>`: Enables a disabled trigger.
- `/on disable <id>`: Disables an active trigger.

**Regex Capture Groups & Variables:**

When a trigger's regex pattern matches, capture groups are made available as variables:

- `$0`: The full text matched by the regex pattern.
- `$1`, `$2`, ...: The text matched by the 1st, 2nd, ... capture group in the pattern.
- Other standard variables like `$nick`, `$channel`, `$msg`, `$me` are also available.

These variables can be used directly in `CMD` actions (e.g., `/msg $nick You said $1`) and are accessible within the `event_data` dictionary in `PY` actions (e.g., `event_data['$1']`).

**Python (`PY`) Actions:**

When using `PY` as the action type, the `<action_content>` is a Python code snippet that will be executed.

- **Security Warning:** Executing arbitrary Python code can be dangerous. Only use Python code from trusted sources or code you have written and understand yourself. PyRC provides the code execution environment, but does not sandbox it heavily beyond the provided context.
- **Execution Context:** The Python code is executed with the following available in its local scope:
  - `client`: An instance of `IRCClient_Logic`, allowing interaction with the client (e.g., `client.add_message(...)`, `client.send_raw(...)`).
  - `event_data`: A dictionary containing the standard variables and regex captures (e.g., `event_data['$nick']`, `event_data['$0']`, `event_data['$1']`).

**Examples:**

- Respond to "hello" with a greeting using a command:
  ```
  /on add TEXT "hello" CMD /say Hi there, $nick!
  ```
- Extract a number from a message and perform a calculation using Python:
  ```
  /on add TEXT "calc (\d+)\s*\+\s*(\d+)" PY client.add_message(f"Calculation: {event_data['$1']} + {event_data['$2']} = {int(event_data['$1']) + int(event_data['$2'])}", client.ui.colors['system'], context_name=event_data['$channel'])
  ```
- Announce when a specific user joins a channel:
  ```
  /on add JOIN "BadUser" PY client.send_raw(f"NOTICE {event_data['$channel']} :Watch out! {event_data['$nick']} just joined!")
  ```

## Contributing

Contributions are welcome! If you'd like to contribute, please:

1.  Fork the repository.
2.  Create a new branch for your feature or bug fix (`git checkout -b feature/your-feature-name`).
3.  Make your changes and commit them (`git commit -am 'Add some feature'`).
4.  Push to the branch (`git push origin feature/your-feature-name`).
5.  Create a new Pull Request.

For major changes, please open an issue first to discuss what you would like to change.

## License

This project is licensed under the MIT License - see the `LICENSE` file for details (if a `LICENSE` file exists, otherwise assume MIT or specify as appropriate).
