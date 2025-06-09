# Debugging Plan v3

## Overview

This document outlines the plan to address the remaining issues in the PyRC IRC client, including the "Never" is not awaitable Pylance errors and the "Received CAP LS but negotiation is not pending. Ignoring." warning.

## Plan

1.  **Address Potential Race Condition in `pyrc_core/irc/irc_protocol.py`:**

    - Add a check to ensure that the `client` object is not None when calling `handle_privmsg` or `handle_notice`. This will prevent potential errors if the client is somehow being accessed after it has been set to None.

2.  **Investigate "Received CAP LS but negotiation is not pending. Ignoring." Warning:**

    - This warning suggests there might be an issue with how CAP negotiation is being handled. I need to examine the CAP-related code in `pyrc_core/irc/irc_protocol.py` and `pyrc_core/cap.py` to understand the negotiation flow and identify why this warning is occurring.

3.  **Re-evaluate the "Client reference became None" Error:**
    - After implementing the above changes, I will run the application again to see if the "Client reference became None" error still occurs. If it does, I'll need to re-examine the code to determine why the `client` reference is being lost.

## Detailed Steps

1.  **Modify `pyrc_core/irc/irc_protocol.py`:**

    ```python
    if handler in [handle_privmsg, handle_membership_changes, handle_nick_message, handle_mode_message, handle_topic_command_event, handle_notice, handle_chghost_command_event]:
        if client:
            specific_handler_trigger_action = await handler(client, parsed_msg, line)
        else:
            logger.warning(f"Client is None, skipping handler {handler.__name__}")
            specific_handler_trigger_action = None
    ```

2.  **Examine CAP Negotiation Code:**

    - Read the code in `pyrc_core/irc/irc_protocol.py` and `pyrc_core/cap.py` to understand the CAP negotiation flow.
    - Look for any potential issues that might cause the "Received CAP LS but negotiation is not pending" warning.

3.  **Test the Application:**

    - Run the application and observe whether the "Client reference became None" error and the CAP warning still occur.

4.  **Re-evaluate if Necessary:**
    - If the issues persist, re-examine the code and adjust the plan accordingly.
