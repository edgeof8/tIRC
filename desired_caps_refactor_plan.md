# Refactoring Plan: Per-Server Desired Capabilities

## Objective:

Refactor PyRC to allow `desired_caps` to be specified on a per-server basis in `pyterm_irc_config.ini`. The `CapNegotiator` should use these server-specific capabilities if defined, otherwise falling back to a global default set.

## Phase 1: Modify `config.py`

1.  **Update `ServerConfig` Dataclass:**
    *   Uncomment the `desired_caps` field.
    *   Change from: `# desired_caps: Optional[List[str]] = None # Defer this for now`
    *   To: `desired_caps: Optional[List[str]] = None`

2.  **Update `load_server_configurations` Function:**
    *   Inside the `try` block where `ServerConfig` instances are created (around line 345):
        *   Add logic to parse the `desired_caps` key from the server's INI section. This key should contain a comma-separated string of capability names.
        *   If the key is not present or its value is empty, `desired_caps` in `ServerConfig` should be `None`.
        *   The parsing should strip whitespace from each capability name.
    *   **Example Parsing Logic:**
        ```python
        # Inside ServerConfig(...) instantiation arguments:
        desired_caps_str = config.get(section_name, "desired_caps", fallback=None)
        desired_caps_list = [cap.strip() for cap in desired_caps_str.split(',')] if desired_caps_str and desired_caps_str.strip() else None
        # ...
        s_config = ServerConfig(
            # ... other existing parameters ...
            desired_caps=desired_caps_list, # Add this
            # ... other existing parameters ...
        )
        ```

## Phase 2: Modify `irc_client_logic.py`

1.  **Update `__init__` Method:**
    *   **Define Default Capabilities:** Establish a default set of desired capabilities. This can be a local variable within `__init__` or a global constant imported from `config.py` (preferred for consistency, e.g., `app_config.DEFAULT_GLOBAL_DESIRED_CAPS`).
        ```python
        # Example if keeping default locally, or import from config.py
        DEFAULT_GLOBAL_DESIRED_CAPS: Set[str] = {
            "sasl", "multi-prefix", "server-time", "message-tags", "account-tag",
            "echo-message", "away-notify", "chghost", "userhost-in-names",
            "cap-notify", "extended-join", "account-notify", "invite-notify",
        }
        ```
    *   **Initialize `self.desired_caps_config`:**
        *   Replace the current hardcoded initialization of `self.desired_caps_config` (around line 244).
        *   The new logic should check if `self.active_server_config` exists and if `self.active_server_config.desired_caps` (which is `Optional[List[str]]`) is not `None` and is a list.
        *   If server-specific capabilities are defined, convert the list to a `Set[str]` and assign it to `self.desired_caps_config`.
        *   Otherwise, assign the `DEFAULT_GLOBAL_DESIRED_CAPS` to `self.desired_caps_config`.
        *   Log which set of capabilities (server-specific or default) is being used.
    *   **Proposed Code Snippet:**
        ```python
        # In IRCClient_Logic.__init__
        # (Assuming DEFAULT_GLOBAL_DESIRED_CAPS is defined or imported)

        if self.active_server_config and \
           self.active_server_config.desired_caps is not None and \
           isinstance(self.active_server_config.desired_caps, list):
            self.desired_caps_config = set(self.active_server_config.desired_caps)
            logger.info(f"Using server-specific desired capabilities for '{self.active_server_config_name}': {self.desired_caps_config}")
        else:
            self.desired_caps_config = DEFAULT_GLOBAL_DESIRED_CAPS # Use the defined default set
            logger.info(f"Using default desired capabilities. Server-specific not set or invalid for '{self.active_server_config_name}'.")
        ```

2.  **Handle Server Switching (Integration with `ServerCommandsHandler.handle_server_command`):**
    *   The `handle_server_command` in `server_commands_handler.py` is responsible for reconfiguring the client when switching servers.
    *   **Crucial Step:** After `self.client.active_server_config` is updated with the new server's configuration in `handle_server_command`:
        *   The logic to determine `self.client.desired_caps_config` (as described above for `__init__`) must be re-executed based on the *new* `self.client.active_server_config`.
        *   **Re-instantiate `CapNegotiator`:** The existing `self.client.cap_negotiator` instance must be replaced with a new one, initialized with the (potentially new) `self.client.desired_caps_config`.
            ```python
            # In ServerCommandsHandler.handle_server_command, after updating self.client.active_server_config
            # and related client attributes (nick, port, etc.)

            # Re-determine desired_caps_config for the new server
            if self.client.active_server_config and \
               self.client.active_server_config.desired_caps is not None and \
               isinstance(self.client.active_server_config.desired_caps, list):
                self.client.desired_caps_config = set(self.client.active_server_config.desired_caps)
                # Log this change
            else:
                self.client.desired_caps_config = DEFAULT_GLOBAL_DESIRED_CAPS # Or imported default
                # Log this choice

            # Re-instantiate CapNegotiator
            self.client.cap_negotiator = CapNegotiator(
                network_handler=self.client.network_handler,
                desired_caps=self.client.desired_caps_config, # Pass the newly determined set
                registration_handler=None, # Will be set by linking logic
                client_logic_ref=self.client,
            )
            ```
        *   **Re-link Handlers:** Ensure that `SaslAuthenticator` and `RegistrationHandler` are updated to use the *new* `CapNegotiator` instance and any other server-specific settings. The existing code in `handle_server_command` already resets and reconfigures parts of these handlers; ensure the `cap_negotiator` reference they hold or use is the new one.
            *   `self.client.sasl_authenticator.cap_negotiator = self.client.cap_negotiator`
            *   `self.client.registration_handler.cap_negotiator = self.client.cap_negotiator` (or similar update mechanism if not direct attribute assignment).
            *   Also ensure they are re-linked after `CapNegotiator` is linked to them:
                *   `self.client.cap_negotiator.registration_handler = self.client.registration_handler`
                *   `self.client.cap_negotiator.set_sasl_authenticator(self.client.sasl_authenticator)`
    *   Consider encapsulating the initialization of `desired_caps_config` and the re-instantiation/re-linking of `CapNegotiator`, `SaslAuthenticator`, and `RegistrationHandler` into a helper method within `IRCClient_Logic` (e.g., `_initialize_connection_handlers()`). This method would be called from `__init__` and also by `ServerCommandsHandler.handle_server_command` after `active_server_config` is switched.

## Phase 3: Modify `cap_negotiator.py`

*   No direct code changes are required in `cap_negotiator.py` itself. It already accepts `desired_caps: Set[str]` in its constructor and uses `self.desired_caps.copy()`. The responsibility lies with `irc_client_logic.py` to pass the correct, potentially server-specific, set.

## Phase 4: Update `pyterm_irc_config.ini` (Example)

*   Users can add a `desired_caps` key to their server sections.
    ```ini
    [Server.MyServer]
    address = irc.myserver.net
    port = 6697
    ssl = true
    nick = MyNick
    channels = #channel1,#channel2
    auto_connect = true
    desired_caps = sasl,multi-prefix,server-time,echo-message,cap-notify
    ```
    If `desired_caps` is omitted or empty for a server, the global default set will be used.

## Summary of Key Changes:

1.  **`config.py`:** `ServerConfig` updated to include `Optional[List[str]] desired_caps`, and `load_server_configurations` updated to parse this from INI.
2.  **`irc_client_logic.py`:**
    *   `self.desired_caps_config: Set[str]` initialized in `__init__` based on `active_server_config.desired_caps` or a global default.
    *   This logic, along with re-instantiation of `CapNegotiator` (and re-linking of `SaslAuthenticator`, `RegistrationHandler`), must be integrated into the server switching mechanism (e.g., in `ServerCommandsHandler.handle_server_command` potentially via a helper method in `IRCClient_Logic`).
3.  **`cap_negotiator.py`:** No code changes.
4.  **`pyterm_irc_config.ini`:** New optional `desired_caps` key for server sections.

This plan ensures that desired capabilities can be tailored per server, enhancing flexibility while maintaining a fallback for configurations without this specific setting.