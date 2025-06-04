# PyRC Refactoring Plan: Switchable Single Active Server

## Objective:

Refactor PyRC to load multiple server definitions from `pyterm_irc_config.ini` and enable switching the client's single active connection between these configurations using a new `/server <config_name>` command.

## Phase 1: Configuration System (`config.py`)

- **Goal:** Ensure `config.py` fully aligns with Part I of the requirements.
- **Status:** Verified as complete. The existing `config.py` meets all specified requirements for `ServerConfig` dataclass, global configuration variables, `load_server_configurations()` function, and its integrations.

## Phase 2: Core Logic Adaptation (`irc_client_logic.py`)

- **Goal:** Adapt `IRCClient_Logic` as per Part II of the requirements.
- **Steps:**
  1.  **Modify `IRCClient_Logic.__init__` Signature:**
      - Remove parameters: `server_addr`, `port`, `nick`, `initial_channels_raw`, `password`, `nickserv_password`, `use_ssl`.
      - The constructor will primarily take `stdscr` and `args`.
  2.  **Initialize New Attributes:**
      - `self.all_server_configs = app_config.ALL_SERVER_CONFIGS`
      - `self.active_server_config_name: Optional[str] = None`
      - `self.active_server_config: Optional[ServerConfig] = None`
  3.  **Determine and Apply Initial Active Configuration:**
      - If `args.server` (CLI override) is provided: Create a temporary `ServerConfig` instance named "CommandLine" using values from `args`. Set this as `self.active_server_config` and `self.active_server_config_name`.
      - Else, if `app_config.DEFAULT_SERVER_CONFIG_NAME` is valid: Set `self.active_server_config_name` and retrieve the corresponding `ServerConfig` from `self.all_server_configs`.
      - Else (client starts disconnected): `self.active_server_config` remains `None`. Add a status message indicating no default server configuration.
  4.  **Populate Client's Connection Attributes:**
      - If `self.active_server_config` is set, populate `self.server`, `self.port`, `self.nick`, `self.initial_nick`, `self.initial_channels_list`, `self.password`, `self.nickserv_password`, `self.use_ssl`, and `self.verify_ssl_cert` from it.
      - Otherwise, set these to `None` or appropriate defaults for a disconnected state.
  5.  **Initialize Core Handlers:**
      - Ensure `NetworkHandler`, `CapNegotiator`, `SaslAuthenticator`, and `RegistrationHandler` are always instantiated in `__init__`.
      - Their initial parameters (nick, passwords, etc.) will be derived from `self.active_server_config` if available, with fallbacks to `app_config` defaults or `None` if no configuration is active.
      - Confirm `self.command_handler` is initialized before being passed to `RegistrationHandler`.

## Phase 3: Server Switching Command (`server_commands_handler.py` & `command_handler.py`)

- **Goal:** Implement and verify the `/server <config_name>` command logic as per Part III.
- **`ServerCommandsHandler.handle_server_command(self, args_str: str)`:**
  1.  Parse `config_name`.
  2.  If switching to a different server and currently connected, disconnect gracefully.
  3.  Update `self.client.active_server_config_name` and `self.client.active_server_config`.
  4.  Update all client connection attributes (`self.client.server`, `port`, `nick`, etc.) from the new `active_server_config`.
  5.  Reconfigure/reset handlers:
      - `NetworkHandler`: Update `channels_to_join_on_connect`.
      - `RegistrationHandler`: Update all relevant parameters.
      - `SaslAuthenticator`: Update SASL password.
      - Reset state for `CapNegotiator`, `SaslAuthenticator`, `RegistrationHandler`.
  6.  Call `self._reset_contexts_for_new_connection()`.
  7.  Call `self.client.network_handler.update_connection_params(...)`.
- **`ServerCommandsHandler._reset_contexts_for_new_connection()`:**
  1.  Clear existing contexts.
  2.  Create a "Status" context.
  3.  Create contexts for `self.client.initial_channels_list` from the new server config.
  4.  Set the active context.
- **`CommandHandler.command_map`:**
  1.  Verify `"/server": self.server_commands.handle_server_command` mapping.

## Phase 4: NetworkHandler Adjustments (`network_handler.py`)

- **Goal:** Ensure `NetworkHandler` aligns with Part IV.
- **Actions:**
  1.  Verify `__init__` takes `client_ref`.
  2.  Verify `_connect_socket()` uses `self.client.server`, `self.client.port`, etc.
  3.  Review `update_connection_params` to ensure it correctly updates its internal state for the next connection attempt based on the client's active config and handles reconnection signals.

## Phase 5: Main Entry Point (`pyrc.py`)

- **Goal:** Modify argument parsing and `IRCClient_Logic` instantiation as per Part V.
- **Actions:**
  1.  In `parse_arguments`: Change `default=` values for `server`, `port`, `nick`, `channel`, `ssl`, `password`, and `nickserv_password` to `None`.
  2.  Verify that `args` is passed to `IRCClient_Logic` during instantiation.

## Phase 6: Context Management (Initial Adaptation - `context_manager.py`)

- **Goal:** No core structural changes to `ContextManager` or `Context` regarding `server_id` are required for this phase, as per Part VI.
- **Action:** Rely on `_reset_contexts_for_new_connection` in `ServerCommandsHandler` for context clearing during server switches.

## Phase 7: Remove `server_connection.py`

- **Goal:** Delete the unused `server_connection.py` file as per Part VII.
- **Action:** Delete the file from the project.

## Visual Plan (Mermaid Diagram):

```mermaid
graph TD
    A[Start: User Request] --> B{Analyze Request & Files};

    B --> C[Phase 1: config.py Review];
    C --> C_OK{All Good?};
    C_OK -- Yes --> D;
    C_OK -- No --> C_FIX[Make Minor Fixes in config.py];
    C_FIX --> D;

    D[Phase 2: irc_client_logic.py Adaptation];
    D --> D1[Modify __init__ Signature];
    D1 --> D2[Init New Config Attributes];
    D2 --> D3[Implement Initial Active Config Logic (CLI vs Default)];
    D3 --> D4[Populate Client Connection Attributes];
    D4 --> D5[Initialize Core Handlers with Fallbacks];
    D5 --> E;

    E[Phase 3: Server Switching Command];
    E --> E1[Review/Refine server_commands_handler.py: handle_server_command];
    E1 --> E2[Review/Refine server_commands_handler.py: _reset_contexts_for_new_connection];
    E2 --> E3[Verify command_handler.py: /server Mapping];
    E3 --> F;

    F[Phase 4: network_handler.py Adjustments];
    F --> F1[Verify __init__ & _connect_socket Usage];
    F1 --> F2[Review update_connection_params];
    F2 --> G;

    G[Phase 5: pyrc.py Main Entry Point];
    G --> G1[Modify parse_arguments (defaults to None)];
    G1 --> G2[Verify IRCClient_Logic Instantiation];
    G2 --> H;

    H[Phase 6: context_manager.py Review];
    H --> H_OK{No core changes needed?};
    H_OK -- Yes --> I;

    I[Phase 7: Remove server_connection.py];
    I --> J[Present Plan to User];

    J --> K{User Approves Plan?};
    K -- Yes --> L[Request Switch to 'code' Mode];
    K -- No --> B;
    L --> M[End of Architect Mode Task];
```
