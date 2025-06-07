# Plan for Step 3.4: SASL Configuration Error Fix

## Problem Description

The error "SASL username provided but no password" occurs because `ServerConfig.__post_init__` in `pyrc_core/app_config.py` defaults `sasl_username` to `nick` if `sasl_username` is `None`, even when no corresponding `sasl_password` or `nickserv_password` is provided. This triggers a validation error in `ConnectionStateValidator` in `pyrc_core/state_manager.py`. Additionally, the `IRCClient_Logic` was not fully halting connection attempts when `ConnectionInfo` validation failed.

## Proposed Fix

The fix involves refining the default logic for SASL credentials in `ServerConfig` and ensuring that validation failures in `ConnectionStateValidator` and `IRCClient_Logic` prevent connection attempts and provide clear error messages.

### 1. Refine `ServerConfig.__post_init__` in `pyrc_core/app_config.py`

The logic for defaulting `sasl_username` and `sasl_password` will be adjusted to be more cautious.

- `sasl_password` will try to use `nickserv_password` if `sasl_password` itself is `None`.
- `sasl_username` will default to `nick` _only if_ `sasl_password` was also just successfully defaulted (or was already explicitly set).
- This prevents `sasl_username` from being set to `nick` if there's no corresponding password, which was the primary cause of the validation error.
- It also handles the case where `sasl_password` is set but `sasl_username` isn't, defaulting `sasl_username` to `nick`.

```python
# pyrc_core/app_config.py
# ... (other imports and dataclasses) ...

@dataclass
class ServerConfig:
    # ... (existing fields) ...

    def __post_init__(self):
        """Set default values based on other fields after initialization."""
        if self.username is None:
            self.username = self.nick
        if self.realname is None:
            self.realname = self.nick

        # Refined SASL default logic:
        if self.sasl_password is None and self.nickserv_password is not None:
            self.sasl_password = self.nickserv_password
            if self.sasl_username is None:
                self.sasl_username = self.nick
        elif self.sasl_username is not None and self.sasl_password is None and self.nickserv_password is None:
            pass # Let validator handle if sasl_username is set but sasl_password is not.
        elif self.sasl_username is None and self.sasl_password is not None:
            self.sasl_username = self.nick
```

### 2. Ensure `ConnectionStateValidator.validate` returns `False` in `pyrc_core/state_manager.py`

The validator will explicitly set `is_valid = False` when the "SASL username provided but no password" condition is met, ensuring the overall validation fails. An inverse check for `sasl_password` without `sasl_username` (if `nick` is also missing) will also be added.

```python
# pyrc_core/state_manager.py
# ... (other imports and dataclasses) ...

class ConnectionStateValidator(StateValidator[ConnectionInfo]):
    """Validator for connection information."""

    def validate(self, value: ConnectionInfo) -> bool:
        """Validate connection information."""
        value.config_errors.clear()
        is_valid = True

        # ... (existing validations) ...

        # Validate SASL configuration
        if value.sasl_username and not value.sasl_password:
            value.config_errors.append("SASL username provided but no password")
            is_valid = False

        if not value.sasl_username and value.sasl_password:
            value.config_errors.append("SASL password provided but no username")
            if not value.nick:
                 is_valid = False

        return is_valid
```

### 3. Update `IRCClient_Logic` to respect validation results in `pyrc_core/client/irc_client_logic.py`

- In `_create_initial_state()`, if `self.state_manager.set_connection_info(conn_info_obj)` returns `False`, an error message will be logged and displayed, and `auto_connect` will be set to `False` to prevent connection attempts with invalid configuration.
- In `_configure_from_server_config()`, the function will return `False` if `self.state_manager.set_connection_info(conn_info_obj)` fails validation, signaling to the caller that configuration was unsuccessful.

```python
# pyrc_core/client/irc_client_logic.py
# ...
    def _create_initial_state(self):
        # ... (existing logic) ...
        if active_config:
            conn_info_obj = ConnectionInfo(...)
            if not self.state_manager.set_connection_info(conn_info_obj):
                logger.error("Initial state creation failed: ConnectionInfo validation error.")
                config_errors = self.state_manager.get_config_errors()
                error_summary = "; ".join(config_errors) if config_errors else "Unknown validation error."
                self._add_status_message(f"Initial Configuration Error: {error_summary}", "error")
                conn_info_obj.auto_connect = False
                if self.state_manager.get_connection_info():
                    updated_conn_info = self.state_manager.get_connection_info()
                    if updated_conn_info:
                        updated_conn_info.auto_connect = False
                        self.state_manager.set("connection_info", updated_conn_info)

    def _configure_from_server_config(self, config_data: ServerConfig, config_name: str) -> bool:
        # ... (existing logic) ...
        try:
            conn_info_obj = ConnectionInfo(...)
            if not self.state_manager.set_connection_info(conn_info_obj):
                logger.error(f"Configuration for server '{config_name}' failed validation.")
                return False
            logger.info(f"Successfully validated and set server config: {config_name} in StateManager.")
            return True
        except Exception as e:
            logger.error(f"Error configuring from server config {config_name}: {str(e)}", exc_info=True)
            self.state_manager.set_connection_state(ConnectionState.CONFIG_ERROR, f"Internal error processing config {config_name}")
            return False
```

### 4. Update `_proceed_with_new_server_connection` in `commands/server/server_command.py`

The `_proceed_with_new_server_connection` function will now check the return value of `client._configure_from_server_config`. If it returns `False`, it will display an error message and halt the connection attempt.

```python
# commands/server/server_command.py
# ...
def _proceed_with_new_server_connection(client: "IRCClient_Logic", config_name: str):
    # ... (existing logic) ...
    new_conf = client.config.all_server_configs[config_name]

    if not client._configure_from_server_config(new_conf, config_name):
        client.add_message(f"Failed to apply server configuration '{config_name}'. Check logs/status for details.", "error", context_name="Status")
        return

    conn_info = client.state_manager.get_connection_info()
    if not conn_info:
        client.add_message(f"Critical error: Connection info lost after configuring for '{config_name}'.", "error", context_name="Status")
        return

    client._initialize_connection_handlers()
    client._reset_state_for_new_connection()

    if conn_info.server and conn_info.port is not None:
        client.network_handler.update_connection_params(...)
        if not client.network_handler._network_thread or not client.network_handler._network_thread.is_alive():
            client.network_handler.start()

        client.add_message(
            f"Switched active server configuration to '{config_name}'. Attempting to connect...",
            "system",
            context_name="Status",
        )
    else:
        client.add_message(
            f"Error: Invalid server configuration for '{config_name}'. Missing server address or port.",
            "error",
            context_name="Status",
        )
```
