# PyRC - Python IRC Client

PyRC is a terminal-based IRC client written in Python. It allows users to connect to IRC servers, join channels, and communicate with other users.

## Features

- Connect to IRC servers
- Join and part channels
- Send and receive messages
- Basic IRC command support
- User interface managed in the terminal
- Configurable settings
- **Logging**: Application events, errors, and IRC communications are logged to files in the `logs/` directory. Log behavior (e.g., level, file size) is configurable in [`pyterm_irc_config.ini`](./pyterm_irc_config.ini:0).

### Command Shortcuts

The client supports common IRC command shortcuts:

- `/j <channel>` or `/join <channel>`: Join a channel.
- `/p <channel>` or `/part <channel>`: Leave a channel.
- `/q` or `/quit [message]`: Disconnect from the server with an optional quit message.
- `/nick <new_nickname>`: Change your nickname.
- `/me <action_message>`: Send an action message (e.g., "/me is coding").
- `/msg <nickname> <message>`: Send a private message to a user.
- `/whois <nickname>`: Get information about a user.
- `/topic <channel> [new_topic]`: View or set the channel topic.
- `/away [message]`: Set or remove an away message.
- `/invite <nickname> <channel>`: Invite a user to a channel.

## Configuration

The client can be configured using the [`pyterm_irc_config.ini`](./pyterm_irc_config.ini:0) file. This file typically includes settings such as:

- Default IRC server and port
- Default nickname
- Default channels to join on connect
- Logging settings (enabled, file name, level, rotation parameters)

## Dependencies

The project dependencies are listed in the [`requirements.txt`](./requirements.txt:0) file. You can install them using pip:

```bash
pip install -r requirements.txt
```

## How to Run

To start the IRC client, you can likely run the main script (assuming it's `pyrc.py`):

```bash
python pyrc.py
```

Or, if there's a specific entry point like `simple_irc_client.py`:

```bash
python simple_irc_client.py
```

Please verify the correct command to run the client.

## Project Structure

The project is organized into several Python modules:

- `pyrc.py`: Likely the main application script or entry point.
- `irc_client_logic.py`: Handles the core IRC client logic.
- `irc_protocol.py`: Implements the IRC protocol.
- `network_handler.py`: Manages network connections.
- `ui_manager.py`: Handles the terminal-based user interface.
- `config.py`: Manages configuration loading and access.
