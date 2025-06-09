# Debugging Plan

This document outlines the plan to address the remaining issues in the PyRC client.

## Issues

- `TypeError: object NoneType can't be used in 'await' expression` in `pyrc_core/irc/handlers/message_handlers.py`
- "Received CAP LS but negotiation is not pending. Ignoring." warning

## Plan

1.  **Check client reference in `handle_notice`:**

    - Modify `pyrc_core/irc/handlers/message_handlers.py` to add a check for `client` being `None` at the beginning of the `handle_notice` function.
    - If `client` is `None`, log a warning and return.

2.  **Investigate CAP LS warning:**

    - Examine `pyrc_core/irc/cap_negotiator.py`:
      - Identify the different states of the CAP negotiation process (e.g., initial, negotiating, negotiated, failed).
      - Trace the transitions between these states based on received messages and actions taken.
      - Look for the conditions that determine whether CAP negotiation is considered "pending."
    - Examine `pyrc_core/network_handler.py`:
      - Trace the sending and handling of CAP-related messages (CAP LS, CAP REQ, CAP END).
      - Verify that CAP LS is only sent when CAP negotiation is started.
      - Analyze the conditions under which CAP LS responses are ignored, and ensure that these conditions are correct.
    - Check conditions for setting negotiation pending:
      - Identify where and how the "negotiation pending" flag is set in `cap_negotiator.py`.
      - Verify that the flag is set correctly when CAP negotiation is initiated.
    - Analyze conditions for ignoring CAP LS:
      - Examine the logic that determines whether to ignore a received CAP LS message.
      - Verify that the conditions for ignoring CAP LS are appropriate (e.g., negotiation is not pending, invalid message format).
    - Implement fix for CAP LS warning:
      - Based on the analysis, implement a fix to prevent the "Received CAP LS but negotiation is not pending. Ignoring." warning from being generated unnecessarily.
      - This might involve adjusting the conditions for ignoring CAP LS, modifying the state transitions in `cap_negotiator.py`, or ensuring that CAP negotiation is properly initiated.

3.  **Implement logging:**

    - Add logging statements in `pyrc_core/network_handler.py` to track the flow of messages and the state of the `client_logic_ref` object.
    - Add logging statements in `pyrc_core/irc/irc_protocol.py` to track the handling of different IRC messages and the values of relevant variables.

4.  **Testing:**
    - Run the PyRC client and connect to an IRC server.
    - Monitor the logs for any errors or warnings.
    - Test basic IRC functionality (e.g., joining channels, sending messages, receiving messages).
    - Specifically test CAP negotiation by connecting to a server that requires it (e.g., Libera.Chat).
