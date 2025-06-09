# Plan for PyRC CAP Negotiator Logging and State Management

This plan outlines the modifications to `pyrc_core/irc/cap_negotiator.py` to add more targeted logging and ensure proper state cleanup within the `start_negotiation` method. These changes aim to help pinpoint the root cause of the `APPLICATION_DATA_AFTER_CLOSE_NOTIFY` SSL error by providing clearer insights into the CAP negotiation flow.

## Objective

To enhance the diagnostic capabilities of the `CapNegotiator` by adding explicit logging statements and ensuring robust state management, especially when the network is not in an expected state during negotiation initiation.

## Targeted File

- [`pyrc_core/irc/cap_negotiator.py`](pyrc_core/irc/cap_negotiator.py)

## Detailed Changes

The primary focus is on the `start_negotiation` method within the `CapNegotiator` class.

### 1. Add Pre- and Post-`send_cap_ls` Logging

To confirm whether `CAP LS` is being sent and processed as expected, explicit log messages will be added around the `network_handler.send_cap_ls()` call.

**Location:** Inside the `start_negotiation` method, specifically within the `if self.network_handler and self.network_handler.connected:` block.

**Proposed Code Snippet (Conceptual):**

```python
# In pyrc_core/irc/cap_negotiator.py, within start_negotiation method

                # ... (after lock acquisition and initial checks) ...
                try:
                    if not self.loop:
                        # ... (loop acquisition logic) ...

                    if self.network_handler and self.network_handler.connected:
                        await self.add_status_message("Negotiating capabilities with server (CAP)...", "system")
                        self.logger.info("CapNegotiator: ABOUT TO SEND CAP LS.") # <<< ADD THIS
                        await self.network_handler.send_cap_ls()
                        self.logger.info("CapNegotiator: CAP LS SENT SUCCESSFULLY.") # <<< ADD THIS
                        self._start_negotiation_timeout_timer()
                    else:
                        # ... (existing else block) ...
```

### 2. Enhance `else` Block State Cleanup

The `else` block, which handles scenarios where the network is not connected when `start_negotiation` is called, needs to explicitly set negotiation flags to `False` and signal the completion events. This ensures that the state is consistently reset even if CAP negotiation cannot begin.

**Location:** Inside the `start_negotiation` method, specifically within the `else` block of `if self.network_handler and self.network_handler.connected:`.

**Proposed Code Snippet (Conceptual):**

```python
# In pyrc_core/irc/cap_negotiator.py, within start_negotiation method

                    if self.network_handler and self.network_handler.connected:
                        # ... (existing logic) ...
                    else:
                        self.logger.warning("CapNegotiator.start_negotiation: Network not connected when expected. Cannot send CAP LS.")
                        await self.add_status_message("Cannot initiate CAP: Network not connected as expected.", "error")
                        self.cap_negotiation_pending = False # <<< ENSURE THIS
                        self.initial_cap_flow_complete_event.set() # <<< ENSURE THIS
                        self.cap_negotiation_finished_event.set() # <<< ENSURE THIS
                        self._cancel_negotiation_timeout_timer() # Ensure timer is cancelled if we exit early

                except Exception as e:
                    # ... (existing error handling) ...
```

## Flow Diagram

```mermaid
graph TD
    A[CapNegotiator.start_negotiation] --> B{Acquire Lock};
    B --> C{Is cap_negotiation_pending?};
    C -- Yes --> D[Exit (redundant call)];
    C -- No --> E[Set cap_negotiation_pending = True];
    E --> F[Clear Events & Caps];
    F --> G{Is Network Connected?};
    G -- Yes --> H[Log: "ABOUT TO SEND CAP LS."];
    H --> I[Call network_handler.send_cap_ls()];
    I --> J[Log: "CAP LS SENT SUCCESSFULLY."];
    J --> K[Start Negotiation Timeout Timer];
    G -- No --> L[Log: "Network not connected when expected."];
    L --> M[Set cap_negotiation_pending = False];
    M --> N[Set initial_cap_flow_complete_event];
    N --> O[Set cap_negotiation_finished_event];
    O --> P[Cancel Negotiation Timeout Timer];
    P --> Q[Add Status Message (Error)];
    Q --> R[Exit];
    K --> S[Handle Exceptions];
    S --> T[Cleanup on Error];
```

## Implementation Steps (for Code Mode)

1.  Read `pyrc_core/irc/cap_negotiator.py`.
2.  Apply the proposed diffs to the `start_negotiation` method.
3.  Confirm successful application.
4.  Attempt completion and await further instructions/testing.

This plan aims to provide the necessary diagnostic information to further debug the SSL `APPLICATION_DATA_AFTER_CLOSE_NOTIFY` error and ensure the CAP negotiation state is always consistent.
