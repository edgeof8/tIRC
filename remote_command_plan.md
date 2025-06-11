# Plan: Implement a "Remote Command" Feature for PyRC

This document outlines the detailed plan for implementing a "Remote Command" feature in PyRC, allowing a command-line interface (CLI) to send raw IRC commands to a running PyRC instance via a local socket. This will involve creating an Inter-Process Communication (IPC) mechanism.

## Detailed Plan

The implementation will proceed in two main phases:

### Phase 1: Create the IPC Command Server

This phase focuses on modifying the main PyRC instance to act as a server, listening for incoming remote commands.

1.  **Create the `IPCManager` Class:**

    - A new file, `pyrc_core/ipc_manager.py`, will be created.
    - This file will define the `IPCManager` class responsible for managing the local command server.
    - The `IPCManager`'s `__init__` method will take a reference to the `IRCClient_Logic` instance.
    - An `async def start_server(self)` method will be implemented to:
      - Determine the socket path using `localhost` and a configurable `ipc_port` (defaulting to `61234` from `AppConfig`).
      - Use `asyncio.start_server()` to create and start the TCP server.
      - Set `_handle_ipc_client` as the callback for new client connections.
    - An `async def _handle_ipc_client(self, reader, writer)` method will be implemented to:
      - Read a single line of data (the raw command) from the connected client.
      - Decode the command string.
      - Pass the command to the `IRCClient_Logic`'s `command_handler` using `await self.client.command_handler.process_user_command(command)`.
      - Close the `writer` to terminate the client connection.
    - An `async def stop_server(self)` method will be added to gracefully close the server socket.

2.  **Integrate `IPCManager` into `IRCClient_Logic`:**
    - The file `pyrc_core/client/irc_client_logic.py` will be modified.
    - The `IPCManager` will be imported.
    - An instance of `IPCManager` will be created in the `IRCClient_Logic`'s `__init__` method, passing `self` (the `IRCClient_Logic` instance) to it.
    - A call to `await self.ipc_manager.start_server()` will be added within the `run_main_loop` method, after the main components are initialized.
    - A call to `await self.ipc_manager.stop_server()` will be added to the `ClientShutdownCoordinator` (which is responsible for graceful shutdown, as per the `README.md` architecture), ensuring the IPC server is properly closed when the client exits.

### Phase 2: Create the CLI Caller Logic

This phase focuses on adding the command-line argument and the client-side logic to send commands to the running PyRC instance.

1.  **Add the `--send-raw` Argument:**

    - The file `pyrc.py` will be modified.
    - The `parse_arguments` function will be updated to include a new command-line argument:
      ```python
      parser.add_argument(
          "--send-raw",
          metavar="\"COMMAND\"",
          help="Send a raw command to a running PyRC instance and exit."
      )
      ```

2.  **Implement the "Send and Exit" Logic:**
    - The `main()` function in `pyrc.py` will be modified.
    - At the beginning of `main()`, immediately after argument parsing, a check for `args.send_raw` will be added.
    - If `args.send_raw` is present, a new asynchronous helper function, `send_remote_command`, will be called using `asyncio.run()`.
    - Error handling will be included to catch exceptions during command sending and exit with an appropriate status code.
    - The `send_remote_command` function will be defined within `pyrc.py` as follows:
      - It will take the `command` string and `app_config` as arguments.
      - It will retrieve the `ipc_port` from the `AppConfig` (defaulting to `61234`).
      - It will use `asyncio.open_connection` to connect to `127.0.0.1` on the specified `ipc_port`.
      - The raw command string will be encoded and sent over the socket, ensuring a newline character is appended.
      - It will handle `ConnectionRefusedError` to provide a user-friendly message if no PyRC instance is running.
    - Finally, the `pyrc_core/app_config.py` file will be updated to include a default constant and loading logic for `ipc_port` under an `[IPC]` section.

## IPC Flow Diagram

```mermaid
graph TD
    subgraph Main PyRC Instance
        A[pyrc.py (Main Loop)] --> B{IRCClient_Logic.run_main_loop()}
        B --> C[IPCManager.start_server()]
        C -- Listens on --> D(Local TCP Socket: 127.0.0.1:61234)
        D -- New Connection --> E[IPCManager._handle_ipc_client(reader, writer)]
        E -- Reads Command --> F[IRCClient_Logic.command_handler.process_user_command(command)]
    end

    subgraph CLI Caller Instance
        G[pyrc.py --send-raw "COMMAND"] --> H{parse_arguments()}
        H -- args.send_raw present --> I[asyncio.run(send_remote_command(command, app_config))]
        I -- Connects to --> D
        I -- Sends Command --> D
        I -- Exits --> J(CLI Exits)
    end

    F -- Processes Command --> K[IRCClient_Logic (Internal Command Processing)]
    K -- Updates UI/State --> L[PyRC Application Behavior]
```
