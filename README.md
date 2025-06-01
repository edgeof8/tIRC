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
- `/help [command]`: Displays general help or help for a specific command.
- `PageUp`/`PageDown`: Scroll through the message buffer in the current window.
- `Ctrl+N`/`Ctrl+P` (or `/nextwindow`, `/prevwindow`): Switch to the next/previous active context (channel/query/status window).
- `Ctrl+U` (or `/u`, `/userlistscroll [offset]`): Scroll the user list in a channel window.

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
