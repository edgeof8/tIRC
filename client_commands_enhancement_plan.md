# Plan: Implement Client Management and Reconnection Commands

This document outlines the plan to add commands for client configuration reloading, server reconnection, and managing raw log display.

## Phase 1: Core Logic and Flags

### 1. `/rawlog` Flag and Basic Handling:

- In [`irc_client_logic.py`](irc_client_logic.py):
  - Add a boolean attribute `self.show_raw_log_in_ui = False` to the `IRCClient_Logic` class.
  - Modify `IRCClient_Logic.handle_server_message()`:
    - Before the call to `irc_protocol.handle_server_message(self, line)`, add a check:
      ```python
      if self.show_raw_log_in_ui:
          self.add_message(f"S << {line.strip()}", self.ui.colors["system"], context_name="Status") # Or a dedicated color
      ```
  - Modify `NetworkHandler.send_raw()` in [`network_handler.py`](network_handler.py):
    - After encoding the data and before sending (using the `log_data` variable that redacts sensitive info), if `self.client.show_raw_log_in_ui` is true, add a message to the "Status" window:
      ```python
      if self.client.show_raw_log_in_ui:
          self.client.add_message(f"C >> {log_data}", self.client.ui.colors["system"], context_name="Status")
      ```

### 2. `/rehash` Configuration Reload Function:

- In [`config.py`](config.py):

  - Create a new function `reload_all_config_values()`:

    - This function will re-execute all the `get_config_value(...)` calls that assign to the global configuration variables (e.g., `IRC_SERVER`, `IRC_PORT`, `LOG_ENABLED`, `LOG_LEVEL`, etc.).
    - It should re-call `load_ignore_list()`.
    - It must re-read the config file at the beginning: `config.read(CONFIG_FILE_PATH)`.
    - Example snippet:

      ```python
      global IRC_SERVER, IRC_PORT, IRC_SSL, LOG_LEVEL, LOG_ENABLED # and all others
      config.read(CONFIG_FILE_PATH) # Re-read the INI file

      IRC_SERVER = get_config_value("Connection", "default_server", DEFAULT_SERVER, str)
      IRC_SSL = get_config_value("Connection", "default_ssl", DEFAULT_SSL, bool)
      IRC_PORT = get_config_value(
          "Connection", "default_port", DEFAULT_SSL_PORT if IRC_SSL else DEFAULT_PORT, int
      )
      # ... repeat for ALL global config variables ...
      LOG_ENABLED = get_config_value("Logging", "log_enabled", DEFAULT_LOG_ENABLED, bool)
      LOG_LEVEL_STR = get_config_value("Logging", "log_level", DEFAULT_LOG_LEVEL, str).upper()
      LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

      load_ignore_list() # Reload ignore patterns
      ```

- In `IRCClient_Logic` ([`irc_client_logic.py`](irc_client_logic.py)):
  - Add a new method, e.g., `handle_rehash_config()`:
    - This method will call `config.reload_all_config_values()`.
    - It will then update internal `IRCClient_Logic` state derived from config values (e.g., `self.verify_ssl_cert`, `self.channel_log_enabled`, `self.context_manager.max_history`).
    - **Logging Changes Note**: For complex logging settings, the initial approach is to update `config.py` values and advise users that a restart might be needed for these to fully apply to the active logging handlers. `IRCClient_Logic` can update its own logging-related attributes for future actions.

## Phase 2: Command Handlers

### 1. `/reconnect` Command:

- In [`server_commands_handler.py`](server_commands_handler.py):
  - Add `handle_reconnect_command(self, args_str: str)`:
    - Check if `self.client.server` is configured.
    - Call `self.client.network.disconnect_gracefully("Reconnecting...")`.
    - Add UI message: `"Reconnecting to server..."`
    - Call `self.client.network.update_connection_params(self.client.server, self.client.port, self.client.use_ssl)`.

### 2. `/rehash` Command:

- In [`command_handler.py`](command_handler.py):
  - Add `_handle_rehash_command(self, args_str: str)`:
    - Call `self.client.handle_rehash_config()`.
    - Add UI message: `"Configuration reloaded. Some changes (like logging or server connection details if modified directly in the file) may require a /reconnect or client restart."`

### 3. `/rawlog` Command:

- In [`command_handler.py`](command_handler.py):
  - Add `_handle_rawlog_command(self, args_str: str)`:
    - Parse `args_str` for "on", "off", or "toggle".
    - Update `self.client.show_raw_log_in_ui` in `IRCClient_Logic`.
    - Add UI feedback: "Raw IRC message logging to UI enabled/disabled."

## Phase 3: Registration and Usage Strings

- In [`command_handler.py`](command_handler.py):
  - Add to `COMMAND_USAGE_STRINGS`:
    - `"reconnect": "Usage: /reconnect - Disconnects and reconnects to the current server."`
    - `"rehash": "Usage: /rehash - Reloads the pyterm_irc_config.ini configuration file. Some changes may require a reconnect or restart."`
    - `"rawlog": "Usage: /rawlog [on|off|toggle] - Toggles or sets display of raw IRC messages in the Status window."`
  - Add to `command_map`:
    - `"reconnect": self.server_commands.handle_reconnect_command,`
    - `"rehash": self._handle_rehash_command,`
    - `"rawlog": self._handle_rawlog_command,`

## Visual Plan (Mermaid Diagram)

```mermaid
graph TD
    subgraph User Input
        A[/command] --> B{CommandHandler.process_user_command}
    end

    subgraph Command Dispatch
        B -- "/reconnect" --> C[ServerCommandsHandler.handle_reconnect_command]
        B -- "/rehash" --> D[CommandHandler._handle_rehash_command]
        B -- "/rawlog" --> E[CommandHandler._handle_rawlog_command]
    end

    subgraph Reconnect Logic
        C --> F[NetworkHandler.disconnect_gracefully]
        C --> G{NetworkHandler.update_connection_params}
        G --> H[NetworkHandler._network_loop triggers _connect_socket]
    end

    subgraph Rehash Logic
        D --> I[IRCClient_Logic.handle_rehash_config]
        I --> J[config.reload_all_config_values]
        J --> K[config.config.read INI]
        J --> L[config.py globals updated]
        I --> M[IRCClient_Logic internal state updated]
        M --> N((Advise restart for some changes))
    end

    subgraph Rawlog Logic
        E --> O[IRCClient_Logic.show_raw_log_in_ui toggled]
        subgraph Message Handling
            P[Incoming Server Msg] --> Q[IRCClient_Logic.handle_server_message]
            Q -- Check flag --> R{Display S << line if true}
            Q --> S[irc_protocol.handle_server_message]

            T[Outgoing Client Msg via /raw or other] --> U[NetworkHandler.send_raw]
            U -- Check flag --> V{Display C >> line if true}
            U --> W[Socket Send]
        end
    end

    subgraph Configuration
        Z1[pyterm_irc_config.ini]
        K -.-> Z1
    end

    subgraph UI Feedback
        C --> X[UI: "Reconnecting..."]
        D --> Y[UI: "Configuration reloaded..."]
        E --> Z[UI: "Rawlog enabled/disabled"]
        R --> UI_StatusWindow["Status Window"]
        V --> UI_StatusWindow
    end
```

## Affected Files Summary:

- [`command_handler.py`](command_handler.py)
- [`server_commands_handler.py`](server_commands_handler.py)
- [`config.py`](config.py)
- [`irc_client_logic.py`](irc_client_logic.py)
- [`network_handler.py`](network_handler.py)
