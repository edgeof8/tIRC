# Refactoring Plan: Abstract Color Handling in Core Logic

**Objective:** Modify `IRCClient_Logic.add_message` and `IRCClient_Logic._add_status_message` to accept semantic color keys, and update their callers in core logic files to use these keys instead of direct `ui.colors` lookups. This centralizes color resolution and decouples core logic from UI specifics.

---

## **Phase 1: Modify `IRCClient_Logic` methods in `irc_client_logic.py`**

1.  **Modify `_add_status_message` (around line 336 in `irc_client_logic.py`)**

    - **Current Implementation:**
      ```python
      # 336 | def _add_status_message(self, text: str, color_key: str = "system"):
      # 337 |     color_attr = self.ui.colors.get(color_key, self.ui.colors["system"])
      # 338 |     self.add_message(text, color_attr, context_name="Status")
      ```
    - **Proposed Changes:**
      - Update the color resolution to ensure a robust fallback to `0` (curses default color pair) if the "system" key itself is missing from `self.ui.colors`.
      - Add logging for clarity on the intended color key.
    - **Revised Code:**
      ```python
      # In IRCClient_Logic
      def _add_status_message(self, text: str, color_key: str = "system"):
          # Resolve color_key to actual curses color attribute here
          color_attr = self.ui.colors.get(color_key, self.ui.colors.get("system", 0)) # Fallback to raw 0 if "system" also missing
          # Log the intended key for clarity, the actual adding is done by add_message
          logger.info(f"[StatusUpdate via Helper] ColorKey: '{color_key}', Text: {text}")
          self.add_message(text, color_attr, context_name="Status") # Pass resolved color_attr
      ```

2.  **Modify `add_message` (around line 407 in `irc_client_logic.py`)**
    - **Current Signature:**
      ```python
      # 407 | def add_message(
      # 408 |     self,
      # 409 |     text: str,
      # 410 |     color_attr: int,
      # 411 |     prefix_time: bool = True,
      # 412 |     context_name: Optional[str] = None,
      # 413 |     source_full_ident: Optional[str] = None,
      # 414 |     is_privmsg_or_notice: bool = False,
      # 415 | ):
      ```
    - **Proposed Changes:**
      - Change the `color_attr: int` parameter to `color_attr_or_key: Any`.
      - Implement logic to check if `color_attr_or_key` is a string (key) or an integer (pre-resolved attribute).
      - If it's a string key, resolve it using `self.ui.colors.get(color_attr_or_key, self.ui.colors.get("default", 0))`.
      - If it's an integer, use it directly.
      - Add a fallback for unexpected types, logging a warning and using the "default" color.
      - Ensure all internal calls to `self.context_manager.add_message_to_context` use the newly `resolved_color_attr`.
    - **Revised Signature and Start of Method:**
      ```python
      # In IRCClient_Logic
      def add_message(
          self,
          text: str,
          color_attr_or_key: Any, # Changed from color_attr: int
          prefix_time: bool = True,
          context_name: Optional[str] = None,
          source_full_ident: Optional[str] = None,
          is_privmsg_or_notice: bool = False,
      ):
          resolved_color_attr: int
          if isinstance(color_attr_or_key, str):
              # It's a color key, resolve it
              resolved_color_attr = self.ui.colors.get(color_attr_or_key, self.ui.colors.get("default", 0)) # Fallback to raw 0 if "default" also missing
          elif isinstance(color_attr_or_key, int):
              # It's already a resolved color attribute
              resolved_color_attr = color_attr_or_key
          else:
              # Fallback for unexpected type
              logger.warning(f"add_message: Unexpected type for color_attr_or_key: {type(color_attr_or_key)}. Using default color.")
              resolved_color_attr = self.ui.colors.get("default", 0)
          # ... rest of the method uses resolved_color_attr ...
      ```
    - **Internal Call Updates within `add_message`:**
      - Change:
        ```python
        # 467 | self.context_manager.add_message_to_context(
        # 468 |     "Status",
        # 469 |     f"[CtxErr for {target_context_name}] {text}",
        # 470 |     color_attr,
        # 471 | )
        ```
        to:
        ```python
        self.context_manager.add_message_to_context(
            "Status",
            f"[CtxErr for {target_context_name}] {text}",
            resolved_color_attr, # Use resolved_color_attr
        )
        ```
      - Change:
        ```python
        # 509 | self.context_manager.add_message_to_context(
        # 510 |     target_context_name, line_part, color_attr, 1
        # 511 | )
        ```
        to:
        ```python
        self.context_manager.add_message_to_context(
            target_context_name, line_part, resolved_color_attr, 1 # Use resolved_color_attr
        )
        ```

---

## **Phase 2: Update Callers in Core Logic Files**

For each file, find calls to `self.client.add_message(...)` or `self.client_logic_ref.add_message(...)` and change the color argument from a direct `ui.colors` lookup to the semantic string key. Calls to `_add_status_message` are generally fine as it will handle its own key resolution internally.

1.  **`features/triggers/trigger_commands.py` (`features/triggers/trigger_commands.py`)**

    - `_show_usage` (line 58):
      - Change `self.client.ui.colors["system"]` to `"system"`.
    - `_handle_add` (lines 74, 87, 100, 107):
      - Change `self.client.ui.colors["error"]` to `"error"`.
      - Change `self.client.ui.colors["system"]` to `"system"`.
    - `_handle_list` (lines 123, 149):
      - Change `self.client.ui.colors["system"]` to `"system"`.
    - `_handle_remove` (lines 160, 172, 179, 186):
      - Change `self.client.ui.colors["error"]` to `"error"`.
      - Change `self.client.ui.colors["system"]` to `"system"`.
    - `_handle_enable` (lines 197, 209, 216, 223):
      - Change `self.client.ui.colors["error"]` to `"error"`.
      - Change `self.client.ui.colors["system"]` to `"system"`.
    - `_handle_disable` (lines 234, 246, 253, 260):
      - Change `self.client.ui.colors["error"]` to `"error"`.
      - Change `self.client.ui.colors["system"]` to `"system"`.

2.  **`network_handler.py` (`network_handler.py`)**

    - `_connect_socket`:
      - Line 221: `self.client.ui.colors["error"]` to `"error"`.
      - Line 228: `self.client.ui.colors["system"]` to `"system"`.
      - Line 272: `self.client.ui.colors["system"]` to `"system"`.
      - Line 302: `self.client.ui.colors["error"]` to `"error"`.
      - Line 309: `self.client.ui.colors["error"]` to `"error"`.
      - Line 318: `self.client.ui.colors["error"]` to `"error"`.
      - Line 324: `self.client.ui.colors["error"]` to `"error"`.
      - Line 330: `self.client.ui.colors["error"]` to `"error"`.
    - `send_raw`:
      - Line 377: `self.client.ui.colors.get("system", 0)` to `"system"`.
      - Line 396: `self.client.ui.colors["error"]` to `"error"`.
    - `_network_loop` (specifically `_handle_server_message`'s `UnicodeDecodeError` handling):
      - Line 488: `self.client.ui.colors["error"]` to `"error"`.
    - Calls to `self.client._add_status_message` (e.g., lines 282, 344, 387, 435, 508) are fine as `_add_status_message` will handle the key.

3.  **`irc_client_logic.py` (`irc_client_logic.py`) (Internal Calls)**
    - `switch_active_context`:
      - Line 723: `self.ui.colors["error"]` to `"error"`.
      - Line 738: `self.ui.colors["error"]` to `"error"`.
      - Line 753: `self.ui.colors["error"]` to `"error"`.
      - Line 771: `self.ui.colors["system"]` to `"system"`.
      - Line 786: `self.ui.colors["error"]` to `"error"`.
    - `switch_active_channel`:
      - Line 810: `self.ui.colors["system"]` to `"system"`.
      - Line 858: `self.ui.colors["error"]` to `"error"`.
    - `PythonTriggerAPI.add_message_to_context` (around line 946):
      - **Current:**
        ```python
        # 946 | def add_message_to_context(self, ctx_name, text, color_key="system"):
        # 947 |     color = self._client_logic.ui.colors.get(color_key, 0)
        # 948 |     self._client_logic.add_message(text, color, context_name=ctx_name)
        ```
      - **Proposed:**
        ```python
        def add_message_to_context(self, ctx_name, text, color_key="system"):
            # Pass the color_key string directly to the refactored add_message
            self._client_logic.add_message(text, color_key, context_name=ctx_name)
        ```
    - `handle_text_input`:
      - Line 1013: `self.ui.colors["my_message"]` to `"my_message"`.
      - Line 1015: `self.ui.colors["my_message"]` to `"my_message"`.
      - Line 1019: `self.ui.colors["error"]` to `"error"`.
      - Line 1024: `self.ui.colors["my_message"]` to `"my_message"`.
      - Line 1026: `self.ui.colors["my_message"]` to `"my_message"`.
    - Calls to `self._add_status_message` within `IRCClient_Logic` (e.g., lines 316, 321, 323, 661, 974, 1001, 1006, 1028, 1046, 1054, 1073, 1103, 1111) are fine as they pass string keys or use the default "system".

---

## **Mermaid Diagram: `add_message` Color Resolution Flow**

```mermaid
graph TD
    A[Call add_message(text, color_attr_or_key, ...)] --> B{isinstance(color_attr_or_key, str)?};
    B -- Yes (Key) --> C[resolved_color_attr = ui.colors.get(color_attr_or_key, ui.colors.get("default", 0))];
    B -- No --> D{isinstance(color_attr_or_key, int)?};
    D -- Yes (Attribute) --> E[resolved_color_attr = color_attr_or_key];
    D -- No (Unexpected Type) --> F[Log Warning];
    F --> G[resolved_color_attr = ui.colors.get("default", 0)];
    C --> H[Use resolved_color_attr in context_manager.add_message_to_context];
    E --> H;
    G --> H;
```

---
