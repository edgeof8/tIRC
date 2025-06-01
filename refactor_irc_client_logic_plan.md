# Refactoring Plan: IRCClient_Logic Modularity

## 1. Goal

Review the current responsibilities of `IRCClient_Logic` and identify areas where specific, cohesive sets of logic could be extracted into new, more specialized classes. The aim is to improve separation of concerns, reduce the size and complexity of `IRCClient_Logic`, and make the overall architecture more modular and maintainable.

## 2. Candidate Classes & Responsibilities

The following new classes are proposed:

- **`CapNegotiator`**

  - **Primary Responsibilities:**
    - Manage the entire CAP negotiation lifecycle (LS, REQ, ACK, NAK, NEW, DEL, END).
    - Maintain all CAP-related state: `supported_caps`, `requested_caps`, `enabled_caps`, `cap_negotiation_pending`, `cap_negotiation_finished_event`, `desired_caps`.
    - Interface with `NetworkHandler` to send `CAP` commands.
    - Process `CAP` responses from the server (forwarded by `irc_protocol.py`).
    - Coordinate with `SaslAuthenticator` if the `sasl` capability is negotiated.
    - Signal completion of CAP negotiation to allow NICK/USER registration or further steps.
  - **Instantiated by:** `IRCClient_Logic`.

- **`SaslAuthenticator`**

  - **Primary Responsibilities:**
    - Manage the SASL PLAIN authentication flow.
    - Maintain SASL-related state: `sasl_authentication_initiated`, `sasl_flow_active`, `sasl_authentication_succeeded`.
    - Interface with `NetworkHandler` to send `AUTHENTICATE` commands.
    - Process `AUTHENTICATE +` challenges and SASL-related numeric replies (e.g., `900`, `903`, `904`) forwarded from `irc_protocol.py` and `irc_numeric_handlers.py`.
    - Signal success or failure of SASL authentication.
  - **Instantiated by:** `IRCClient_Logic` (and likely passed to or invoked by `CapNegotiator`).

- **`RegistrationHandler`**
  - **Primary Responsibilities:**
    - Manage actions that occur after successful connection, CAP negotiation, SASL authentication (if applicable), and receiving `RPL_WELCOME (001)`.
    - Orchestrate sending initial `NICK` and `USER` commands (if not handled as part of CAP/SASL completion signaling).
    - Handle auto-joining of channels.
    - Handle automatic NickServ identification if SASL was not used or failed, and a password is configured.
  - **Instantiated by:** `IRCClient_Logic`.

## 3. Interaction Model

```mermaid
sequenceDiagram
    participant NH as NetworkHandler
    participant ICL as IRCClient_Logic
    participant CN as CapNegotiator
    participant SA as SaslAuthenticator
    participant RH as RegistrationHandler
    participant IP as irc_protocol.py
    participant INH as irc_numeric_handlers.py

    NH ->>+ ICL: on_connected() / _connect_socket() successful
    ICL ->>+ CN: start_negotiation(nick, user, realname, password)
    CN ->> NH: send_cap_ls()
    activate CN

    NH ->> ICL: handle_server_message(raw_line_cap_ls_response)
    ICL ->> IP: handle_server_message(parsed_msg_cap_ls)
    IP ->>+ CN: on_cap_ls_received(capabilities)
    CN ->> CN: Process CAP LS, determine caps_to_request
    alt SASL desired and supported
        CN ->> CN: Add "sasl" to requested_caps
    end
    CN ->> NH: send_cap_req(requested_caps)
    deactivate CN

    NH ->> ICL: handle_server_message(raw_line_cap_ack_response)
    ICL ->> IP: handle_server_message(parsed_msg_cap_ack)
    IP ->>+ CN: on_cap_ack_received(acked_caps)
    activate CN
    CN ->> CN: Update enabled_caps, requested_caps
    alt "sasl" in acked_caps AND nickserv_password exists
        CN ->>+ SA: start_authentication(nick, nickserv_password)
        SA ->> NH: send_authenticate_plain()
        activate SA

        NH ->> ICL: handle_server_message(raw_line_auth_challenge)
        ICL ->> IP: handle_server_message(parsed_msg_auth_challenge)
        IP ->>+ SA: on_authenticate_challenge_received(challenge)
        SA ->> NH: send_authenticate_payload(credentials)
        deactivate SA

        NH ->> ICL: handle_server_message(raw_line_sasl_numeric)
        ICL ->> IP: handle_server_message(parsed_msg_sasl_numeric)
        IP ->> INH: _handle_numeric_command(parsed_msg_sasl_numeric)
        INH ->>+ SA: on_sasl_result_received(success_or_failure, message)
        SA ->> SA: Update SASL state
        SA -->>- CN: sasl_flow_complete(success_status)
        deactivate SA
    end

    alt All requested caps processed (ACK/NAK) AND SASL flow (if any) complete
        CN ->> NH: send_cap_end()
    end
    deactivate CN

    NH ->> ICL: handle_server_message(raw_line_cap_end_confirm_or_001)
    ICL ->> IP: handle_server_message(parsed_msg_cap_end_confirm_or_001)
    alt CAP END confirmed (via CAP command itself)
        IP ->>+ CN: on_cap_end_confirmed()
        CN ->>+ RH: on_cap_negotiation_complete(is_sasl_successful)
        deactivate CN
    else RPL_WELCOME (001) received
        IP ->> INH: _handle_numeric_command(parsed_msg_001)
        INH ->>+ RH: on_welcome_received(confirmed_nick, is_sasl_successful_from_cap_negotiator_state)
        alt CAP negotiation was pending and not finished by explicit CAP END
             RH ->> CN: on_welcome_signals_cap_end()
             CN -->> RH: cap_negotiation_now_complete(is_sasl_successful)
        end
    end
    deactivate IP
    deactivate INH

    activate RH
    RH ->> NH: send_nick(nick)
    RH ->> NH: send_user(user, realname)
    opt Password provided and SASL not used/successful
        RH ->> NH: send_pass(password)
    end
    RH ->> ICL: Perform auto-joins (via CommandHandler)
    opt NickServ password and SASL not successful
        RH ->> ICL: Identify with NickServ (via CommandHandler)
    end
    deactivate RH
    deactivate ICL
```

**Data and Control Flow Notes:**

- `IRCClient_Logic` would instantiate `CapNegotiator`, `SaslAuthenticator`, and `RegistrationHandler`, providing them with necessary references (e.g., to `NetworkHandler` for sending messages, to itself or a `ContextManager` delegate for adding status messages).
- `irc_protocol.py` and `irc_numeric_handlers.py` would be modified:
  - Instead of calling `client.handle_cap_ls()`, etc., they would call methods on the `CapNegotiator` instance (e.g., `cap_negotiator.on_cap_ls_received()`).
  - Similarly for SASL, routing to `SaslAuthenticator` methods.
  - The `_handle_rpl_welcome` in `irc_numeric_handlers.py` would primarily delegate to the `RegistrationHandler.on_welcome_received()` method.
- The new handler classes would encapsulate the state and the step-by-step logic for their respective responsibilities.

## 4. Benefits & Trade-offs

- **Benefits:**

  - **Improved Separation of Concerns:** Each class has a well-defined responsibility (CAP, SASL, Post-Registration).
  - **Reduced Complexity in `IRCClient_Logic`:** This class becomes much leaner, focusing on overall orchestration and UI/user command interaction.
  - **Enhanced Testability:** Each new class can be tested in isolation more easily.
  - **Maintainability & Extensibility:** Changes to CAP negotiation, SASL mechanisms, or post-registration steps can be made within the specific handler without significantly impacting other parts of the system. For example, adding a new SASL mechanism would primarily affect `SaslAuthenticator`.
  - **Readability:** The connection and registration logic becomes easier to follow by looking at the dedicated classes.

- **Potential Trade-offs:**
  - **Increased Number of Classes:** More files/classes to manage.
  - **Inter-Component Communication:** Requires careful setup of interactions (passing references, callbacks, or events) between `IRCClient_Logic` and the new handlers, and between the handlers themselves (e.g., `CapNegotiator` invoking `SaslAuthenticator`).
  - **Initial Refactoring Effort:** The initial effort to extract and correctly wire up these components.

## 5. Impact on `IRCClient_Logic`

- **Size Reduction:** Significant reduction in lines of code and complexity as CAP state, SASL state, and their respective multi-step logic methods are moved out.
- **Primary Remaining Responsibilities:**
  - Initialization of core components: `UIManager`, `NetworkHandler`, `CommandHandler`, `InputHandler`, `ContextManager`, `TriggerManager`, and the new `CapNegotiator`, `SaslAuthenticator`, `RegistrationHandler`.
  - Managing the main application loop (`run_main_loop`).
  - Handling overall client shutdown (`shutdown_client`).
  - Central `add_message` utility (used by new handlers for status updates).
  - `handle_server_message` becomes a simpler pass-through to `irc_protocol.py`.
  - Providing accessors or delegates for shared resources needed by the new handlers (e.g., configuration, `NetworkHandler` instance).
  - Switching active context (`switch_active_context`).
  - Handling user text input for messages/commands not related to the connection phase.

## 6. Server Message Dispatch (Post-Parsing)

The current `irc_protocol.py` and `irc_numeric_handlers.py` already serve as dispatchers. For now, the focus is on extracting `CapNegotiator`, `SaslAuthenticator`, and `RegistrationHandler`. Handlers in `irc_protocol.py` and `irc_numeric_handlers.py` will be modified to call methods on these new classes for CAP, SASL, and registration-related events, instead of directly calling methods on `IRCClient_Logic` for these processes.
