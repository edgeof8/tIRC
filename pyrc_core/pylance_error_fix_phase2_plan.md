# Pylance Error Fix Plan - Phase 2

## Error Categories

### 1. Unused Coroutine Errors

- **Files**:
  - All channel commands (cyclechannel, invite, kick, part, simple_mode, topic)
- **Solution**:
  - Add `await` to async function calls (`add_message`, `send_raw`)
  - Assign results to variables when needed

### 2. Argument Type Mismatch

- **Files**:
  - All channel commands
- **Solution**:
  - Replace string literals ('error', 'system') with:
    ```python
    client.ui.colors["error"]
    client.ui.colors["system"]
    ```

### 3. Attribute Access Issues

- **Files**:
  - dcc_auto_command.py
  - dcc_cancel_command.py
  - dcc_get_command.py
  - dcc_send_command.py
- **Solution**:
  - Replace `dcc_config.get("enabled")` with `dcc_config.enabled`
  - Replace `dcc_config["auto_accept"]` with `dcc_config.auto_accept`

### 4. Indexing and Assignment Issues

- **Files**:
  - simple_mode_commands.py
  - dcc_get_command.py
  - dcc_send_command.py
- **Solution**:

  - Await coroutines before indexing/accessing:

    ```python
    # Before
    nick = parts[0]

    # After
    resolved_parts = await parts
    nick = resolved_parts[0]
    ```

### 5. Try Block Syntax Error

- **Files**:
  - dcc_list_command.py
- **Solution**:
  - Add except/finally clause to try block

### 6. dcc_receive_manager.py Issues

- **Problems**:
  - Duplicate peer_ip parameter
  - Indentation issues
  - Incorrect async/await usage
- **Solution**:
  - Remove duplicate peer_ip
  - Correct indentation in accept_dcc_resume_offer
  - Fix async/await usage

## Implementation Plan

### Phase 1: Fix Common Patterns

- Apply await/color constant fixes to all channel command files
- Fix indexing issues in simple_mode_commands.py

### Phase 2: DCC-Specific Fixes

- Fix attribute access in all dcc\_\*\_command.py files
- Implement missing DCCManager methods
- Correct try block syntax in dcc_list_command.py
- Resolve dcc_receive_manager.py issues

### Phase 3: Testing

- Test all command workflows
- Verify DCC file transfers
- Confirm Pylance errors are resolved
