## Command System

PyRC features a powerful and extensible command system that handles both built-in client commands and custom commands defined by scripts.

**Dynamic & Modular:** The command system allows new commands to be added easily without modifying core client logic.

### Command Structure

```
/command_name [arguments] [--option=value]
```

Commands are discovered dynamically from the `pyrc_core/commands/` directory.

### Core Command Categories

- **Channel Ops:** `/join`, `/part`, `/topic`
- **Server:** `/connect`, `/server`, `/quit`
- **User:** `/msg`, `/query`, `/nick`
- **UI:** `/window`, `/next`, `/clear`
- **DCC:** `/dcc send`, `/dcc get`
- **Scripting:** `/script`, `/trigger`

### Command Features

- Tab completion for commands and arguments
- Multiple command aliases
- Context-aware execution
- Async command handlers
- Built-in help system
- Scriptable command registration

### Command Execution Flow

1.  **Input Capture**: User types command in input line
2.  **Parsing**: CommandHandler splits command and arguments
3.  **Resolution**: Finds matching command handler (Checks both core commands and script-registered commands)
4.  **Execution**: Runs handler in appropriate context:
    - Async handlers run directly in event loop
    - Sync handlers run in thread pool
5.  **Response**: Updates UI or sends IRC messages (All UI updates are thread-safe)

**Note:** PyRC's command system is fully async-capable. Commands can be implemented as either synchronous or asynchronous functions.

### Command Module Structure

```python
# Example command module (pyrc_core/commands/channel/join_command.py)
from typing import Optional
from pyrc_core.commands.command_handler import CommandDefinition

COMMAND_DEFINITIONS = [
    CommandDefinition(
        name="join",
        handler="handle_join_command",
        help={
            "usage": "/join <channel> [key]",
            "description": "Joins an IRC channel",
            "examples": [
                "/join #python",
                "/join #secret secretpass"
            ]
        },
        aliases=["j"]
    )
]

async def handle_join_command(client, args_str: str):
    args = args_str.split()
    if not args:
        await client.add_message("Error: Channel name required")
        return

    channel = args[0]
    key = args[1] if len(args) > 1 else None
    await client.network_handler.send(f"JOIN {channel} {key or ''}")
```

### Help System Examples

```
/help         # List all commands
/help join    # Show help for /join
/help script  # Show scripting commands
/help dcc     # Show DCC commands
```

### Scripting Integration

Scripts can register new commands using the ScriptAPI:

```python
# In a script's on_load() method:
self.api.register_command(
    name="greet",
    handler=self.handle_greet,
    help={
        "usage": "/greet [name]",
        "description": "Sends a greeting message",
        "examples": ["/greet Alice", "/greet"]
    }
)

async def handle_greet(self, args_str: str):
    name = args_str.strip() or "everyone"
    await self.api.send_message(
        self.api.get_active_context(),
        f"Hello, {name}!"
    )
```

#### Command Registration Best Practices

- Always provide complete help text with examples
- Use async handlers for I/O operations
- Validate arguments before processing
- Handle errors gracefully with user feedback

#### Error Handling Example

```python
async def handle_complex_command(self, args_str: str):
    try:
        # Parse and validate arguments
        args = self._parse_args(args_str)
        if not args.valid:
            await self.show_usage_error()
            return

        # Perform operation
        result = await self._perform_operation(args)
        await self.show_success(result)

    except ValueError as e:
        await self.show_error(f"Invalid input: {e}")
    except ConnectionError as e:
        await self.show_error(f"Network error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in command: {e}")
        await self.show_error("An unexpected error occurred")
```

#### Performance Considerations

- Use async for network/disk operations
- Keep sync handlers fast and non-blocking
- Cache expensive operations where possible
- Limit UI updates during batch operations

### Advanced Usage

#### Command Chaining

```python
# Example of chaining commands in a script
async def handle_chain(self, args_str: str):
    await self.api.execute_command("/connect irc.example.net")
    await asyncio.sleep(1)  # Brief delay
    await self.api.execute_command("/join #test")
    await self.api.execute_command("/msg #test Hello from script!")
```

#### Complex Command Example

```python
import os # Added import for os.path.exists
import asyncio # Added import for asyncio.sleep

async def handle_file_upload(self, args_str: str):
    """Example complex command with multiple steps"""
    # Parse arguments
    parts = args_str.split(maxsplit=1)
    if len(parts) < 2:
        await self.show_usage_error()
        return

    nick, filepath = parts

    # Validate file
    if not os.path.exists(filepath):
        await self.show_error(f"File not found: {filepath}")
        return

    # Initiate DCC transfer
    transfer_id = await self.api.dcc_send_file(nick, filepath)

    # Monitor progress
    while True:
        status = await self.api.get_dcc_status(transfer_id)
        if status in ['COMPLETED', 'FAILED', 'CANCELLED']:
            break
        await asyncio.sleep(0.5)

    # Report final status
    if status == 'COMPLETED':
        await self.show_success(f"File sent to {nick}")
    else:
        await self.show_error(f"Transfer failed: {status}")
```
