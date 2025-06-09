# asyncio Migration Debug Plan v2

This document outlines the plan to address the remaining issues after migrating PyRC to an asyncio-based architecture.

## Issues

The following issues persist:

1.  **NetworkHandler**: `Network task already running`: This suggests the lock in `NetworkHandler` is not fully effective or there's another path triggering the network loop start.
2.  **CapNegotiator**: `CapNegotiator: start_negotiation called while already pending. Resetting.`: This indicates the lock in `CapNegotiator` is also not fully effective.
3.  **SSL Error**: `ssl.SSLError: [SSL: APPLICATION_DATA_AFTER_CLOSE_NOTIFY] application data after close notify`: This SSL error persists and needs to be addressed with proper error handling.
4.  **Task Cleanup**: `Task was destroyed but it is pending!`: This indicates improper task cleanup during shutdown.
5.  **Event Loop**: `Event loop is closed`: This indicates the event loop is being closed prematurely.

## Plan

The following steps will be taken to address these issues:

1.  **NetworkHandler**:

    - Double-check the lock implementation in `NetworkHandler.start`.
    - Add logging to the `NetworkHandler.start` method to track when it's called, by whom, and whether the lock is acquired.
    - Search for other places where the network loop might be started.
    - Ensure that the event loop is not closed prematurely.
    - Ensure that the `NetworkHandler` is fully disconnected before the event loop is closed.

2.  **CapNegotiator**:

    - Double-check the lock implementation in `CapNegotiator.start_negotiation`.
    - Add logging to track when `start_negotiation` is called, by whom, whether the lock is acquired, and the state of `self.cap_negotiation_pending`.
    - Add a try...except block to catch any exceptions preventing negotiation.

3.  **SSL Error**:

    - Implement proper error handling to catch and log SSL errors in the `_network_loop` in `network_handler.py`.
    - Ensure that data is not sent after the SSL connection has been closed.
    - Investigate the SSL shutdown process and ensure it's handled correctly.

4.  **Task Cleanup**:

    - Ensure that all tasks are properly cancelled and awaited during shutdown in `irc_client_logic.py`.
    - Implement proper error handling to catch and log any errors that occur during task cancellation.

5.  **Event Loop**:
    - Investigate where the event loop is being closed and prevent it from being closed prematurely.
    - Ensure that all tasks are completed before closing the event loop.

## Mermaid Diagram

```mermaid
graph TD
    A[Start] --> B{NetworkHandler: "Network task already running"};
    B --> C{Double-check lock in start()};
    B --> D{Add logging to start()};
    B --> E{Search for other network loop starts};
    B --> F{Ensure event loop is not closed prematurely};
    B --> G{Ensure NetworkHandler is fully disconnected before closing event loop};
    A --> H{CapNegotiator: "start_negotiation called while already pending"};
    H --> I{Double-check lock in start_negotiation()};
    H --> J{Add logging to start_negotiation()};
    H --> K{Add try...except block to prevent negotiation interruptions};
    A --> L{ssl.SSLError: "APPLICATION_DATA_AFTER_CLOSE_NOTIFY"};
    L --> M{Implement SSL error handling in _network_loop};
    L --> N{Ensure data is not sent after SSL connection is closed};
    L --> O{Investigate SSL shutdown process};
    A --> P{"Task was destroyed but it is pending!"};
    P --> Q{Ensure all tasks are cancelled and awaited during shutdown in irc_client_logic.py};
    P --> R{Implement error handling for task cancellation};
    A --> S{"Event loop is closed"};
    S --> T{Investigate where the event loop is being closed};
    S --> U{Prevent premature event loop closure};
    S --> V{Ensure all tasks are completed before closing the event loop};
```
