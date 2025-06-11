# Detailed Plan for Streamlining UI Refresh and Resize Logic

## Objective:

Refactor the `refresh_all_windows` method in `pyrc_core/client/ui_manager.py` to simplify its logic for handling terminal resizes and "too small" UI conditions, and to ensure explicit cleanup of `curses` window objects.

## Current State Analysis:

The `refresh_all_windows` method currently has intertwined logic for resize detection, window recreation, and "terminal too small" error display. This leads to complexity and potential issues. The `delete_windows` method in `WindowLayoutManager` is already implemented but lacks explicit debug logging for each deleted window.

## Proposed Changes:

### 1. Modify `pyrc_core/client/window_layout_manager.py`:

- **`delete_windows(self)` method:**
  - Inside the loop, after `del win` and before `setattr(self, win_name, None)`, add a `logger.debug` message indicating which window is being deleted.

### 2. Modify `pyrc_core/client/ui_manager.py`:

- **`refresh_all_windows` method:**
  - **Step 1: Initial Dimension Check and Resize Handling:**
    - Keep the initial `get_dimensions()` and `resize_occurred` check.
    - Inside the `if resize_occurred:` block (lines 212-255 in current file):
      - Keep logging the resize (line 213).
      - Keep `self.height, self.width = new_height, new_width` (line 214).
      - Keep `self.ui_is_too_small = False` (line 215).
      - Keep `SafeCursesUtils._safe_clear(self.stdscr, "UIManager.resize_clear_stdscr")` (line 219).
      - Keep `SafeCursesUtils._safe_refresh(self.stdscr, "UIManager.resize_refresh_stdscr")` (line 220).
      - **INSERT at line 221:** `self.window_layout_manager.delete_windows()`
      - Keep `self.setup_layout()` (line 222).
      - **REMOVE:** The `try-except` block that wraps `self.setup_layout()` (lines 217-255). This includes removing the `scroll_messages("end")` call (lines 225-229) and all the "Terminal too small" error display logic within this block.
  - **Step 2: Dedicated "Too Small" State Check:**
    - After the `if resize_occurred:` block (which will end around line 223 after refactoring), add a new `if self.ui_is_too_small:` block.
    - This new block will replace the existing `if self.ui_is_too_small:` block (lines 257-273).
    - Inside this new block:
      - `SafeCursesUtils._safe_erase(self.stdscr, "UIManager.too_small_repeat_erase")`
      - `msg = "Terminal too small. Please resize."`
      - `if self.height > 0 and self.width > 0:`
        - `msg_y = self.height // 2`
        - `msg_x = max(0, (self.width - len(msg)) // 2)`
        - `if msg_x + len(msg) <= self.width:`
          - `error_attr = self.curses_manager.get_color("error") | curses.A_BOLD`
          - `SafeCursesUtils._safe_addstr(self.stdscr, msg_y, msg_x, msg, error_attr, "UIManager.too_small_repeat_addstr")`
      - `SafeCursesUtils._safe_refresh(self.stdscr, "UIManager.too_small_final_refresh")`
      - `return`
  - **Step 3: Normal Drawing Routine:**
    - This block will now start after the new "Too Small" check (around line 275 in the original file, but will shift up).
    - Keep the existing `try-except` block for drawing (lines 279-308).
    - Keep `active_ctx_name_snapshot` and `active_ctx_obj_snapshot` assignments.
    - Keep `SafeCursesUtils._safe_noutrefresh(self.stdscr, "UIManager.refresh_all_windows_noutrefresh_stdscr")`.
    - Keep calls to `self.draw_messages`, `self.draw_sidebar`, `self.draw_status_bar`, `self.draw_input_line`.
    - Keep `self.curses_manager.update_screen()`.
    - Keep the error handling for `curses.error` and `Exception` within this block.

## Mermaid Diagram:

```mermaid
graph TD
    A[Start refresh_all_windows] --> B{Get new terminal dimensions};
    B --> C{Is resize_occurred?};
    C -- Yes --> D[Log resize, Update dimensions, Reset ui_is_too_small];
    D --> E[Clear & Refresh stdscr];
    E --> F[Call window_layout_manager.delete_windows()];
    F --> G[Call setup_layout()];
    G --> H{Is ui_is_too_small?};
    C -- No --> H;
    H -- Yes --> I[Display "Terminal too small" on stdscr];
    I --> J[Refresh stdscr];
    J --> K[Return];
    H -- No --> L[Prepare stdscr for batched update (noutrefresh)];
    L --> M[Draw messages, sidebar, status bar, input line];
    M --> N[Perform batched update (curses_manager.update_screen())];
    N --> O[End refresh_all_windows];
```
