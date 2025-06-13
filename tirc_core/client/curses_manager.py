import curses
import logging
from typing import Any, Dict, Tuple
from tirc_core.client.curses_utils import SafeCursesUtils
from tirc_core.app_config import AppConfig
from tirc_core.client.ui_colors import UI_COLOR_PALETTE, FALLBACK_8_COLOR_MAP # Import new color palette
import colorsys # For hex to RGB conversion

logger = logging.getLogger("tirc.curses_manager")

class CursesManager:
    def __init__(self, stdscr: Any, config: AppConfig):
        self.stdscr = stdscr
        self.config = config # Store the AppConfig instance
        self.colors: Dict[str, int] = {}
        self.height: int = 0
        self.width: int = 0
        self._setup_curses_settings()

    def _setup_curses_settings(self):
        SafeCursesUtils._safe_curs_set(1, "CursesManager._setup_curses_settings_curs_set") # Make cursor visible
        SafeCursesUtils._safe_noecho("CursesManager._setup_curses_settings_noecho")    # Don't echo characters typed by user
        SafeCursesUtils._safe_cbreak("CursesManager._setup_curses_settings_cbreak")    # React to keys instantly, without waiting for Enter
        SafeCursesUtils._safe_keypad(self.stdscr, True, "CursesManager._setup_curses_settings_keypad") # Enable special keys (like arrow keys)
        SafeCursesUtils._safe_start_color("CursesManager._setup_curses_settings_start_color")
        # Removed SafeCursesUtils._safe_use_default_colors as it can conflict with explicit background setting.

        self.can_use_256_colors = False
        if curses.COLORS >= 256 and curses.can_change_color():
            self.can_use_256_colors = True
            logger.info("Terminal supports 256 colors and can change colors.")
        else:
            logger.info("Terminal does NOT support 256 colors or cannot change colors. Falling back to 8-color palette.")

        # Define color pair IDs locally
        # Assign IDs dynamically or ensure they are unique and within curses limits (typically 1 to 255)
        # We'll use a counter for color IDs
        color_id_counter = 1

        # Store a mapping from semantic name to curses color ID
        self.color_name_to_id: Dict[str, int] = {}

        # Function to convert hex to curses RGB (0-1000 scale)
        def hex_to_curses_rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            return (r * 1000 // 255, g * 1000 // 255, b * 1000 // 255)

        # Initialize custom colors if 256-color support is available
        if self.can_use_256_colors:
            # We need to map each unique hex color to a curses color number
            # Curses only has 256 color slots (0-255), so we'll use a subset
            # We'll assign color numbers starting from 16 (0-15 are standard ANSI)
            curses_color_num_counter = 16
            hex_to_curses_color_num: Dict[str, int] = {}

            for color_name, hex_value in UI_COLOR_PALETTE.items():
                if hex_value not in hex_to_curses_color_num:
                    if curses_color_num_counter < curses.COLORS:
                        r, g, b = hex_to_curses_rgb(hex_value)
                        try:
                            curses.init_color(curses_color_num_counter, r, g, b)
                            hex_to_curses_color_num[hex_value] = curses_color_num_counter
                            curses_color_num_counter += 1
                        except curses.error as e:
                            logger.warning(f"Curses error initializing color {hex_value} to ID {curses_color_num_counter}: {e}. Falling back.")
                            # Fallback to 8-color if init_color fails for some reason
                            hex_to_curses_color_num[hex_value] = FALLBACK_8_COLOR_MAP.get(hex_value, curses.COLOR_WHITE)
                    else:
                        logger.warning(f"Ran out of 256-color slots. Mapping {hex_value} to 8-color fallback.")
                        hex_to_curses_color_num[hex_value] = FALLBACK_8_COLOR_MAP.get(hex_value, curses.COLOR_WHITE)

                # Now initialize color pairs using these mapped color numbers
                # We need to handle foreground and background pairs separately
                # For simplicity, we'll create pairs for each semantic usage
                # This means some hex colors might be initialized multiple times if used as both FG and BG
                # But curses.init_color is idempotent for the same color number.

            # Helper to get curses color number for a hex value
            def get_curses_color(hex_val):
                return hex_to_curses_color_num.get(hex_val, curses.COLOR_WHITE) # Default to white if not found

            # Main Backgrounds
            self._init_color_pair("message_panel_bg", color_id_counter, get_curses_color(UI_COLOR_PALETTE["other_message"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["message_panel_bg"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("list_panel_bg", color_id_counter, get_curses_color(UI_COLOR_PALETTE["other_message"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["list_panel_bg"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("status_bar", color_id_counter, get_curses_color(UI_COLOR_PALETTE["status_bar_fg"]), get_curses_color(UI_COLOR_PALETTE["status_background"]))
            self.color_name_to_id["status_bar"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("input", color_id_counter, get_curses_color(UI_COLOR_PALETTE["other_message"]), get_curses_color(UI_COLOR_PALETTE["input_background"]))
            self.color_name_to_id["input"] = color_id_counter
            color_id_counter += 1

            # Highlighting System Colors (Foreground on main_background)
            self._init_color_pair("channel", color_id_counter, get_curses_color(UI_COLOR_PALETTE["channel"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["channel"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("nick", color_id_counter, get_curses_color(UI_COLOR_PALETTE["nick"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["nick"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("mode", color_id_counter, get_curses_color(UI_COLOR_PALETTE["mode"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["mode"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("my_message", color_id_counter, get_curses_color(UI_COLOR_PALETTE["my_message"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["my_message"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("other_message", color_id_counter, get_curses_color(UI_COLOR_PALETTE["other_message"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["other_message"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("system_message", color_id_counter, get_curses_color(UI_COLOR_PALETTE["system_message"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["system_message"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("error_message", color_id_counter, get_curses_color(UI_COLOR_PALETTE["error_message"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["error_message"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("highlight_mention", color_id_counter, get_curses_color(UI_COLOR_PALETTE["highlight_mention"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["highlight_mention"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("timestamp", color_id_counter, get_curses_color(UI_COLOR_PALETTE["timestamp"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["timestamp"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("server_name", color_id_counter, get_curses_color(UI_COLOR_PALETTE["server_name"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["server_name"] = color_id_counter
            color_id_counter += 1

            # Sidebar Specifics
            self._init_color_pair("sidebar_active", color_id_counter, get_curses_color(UI_COLOR_PALETTE["sidebar_active_fg"]), get_curses_color(UI_COLOR_PALETTE["sidebar_active_bg"]))
            self.color_name_to_id["sidebar_active"] = color_id_counter
            color_id_counter += 1

            self._init_color_pair("sidebar_unread", color_id_counter, get_curses_color(UI_COLOR_PALETTE["sidebar_unread_fg"]), get_curses_color(UI_COLOR_PALETTE["sidebar_unread_bg"]))
            self.color_name_to_id["sidebar_unread"] = color_id_counter
            color_id_counter += 1

            # Default color pair (white on main background)
            self._init_color_pair("default", color_id_counter, get_curses_color(UI_COLOR_PALETTE["other_message"]), get_curses_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["default"] = color_id_counter
            color_id_counter += 1

        else: # Fallback to 8-color palette
            # Define color pair IDs locally (re-using old IDs for consistency if possible)
            COLOR_ID_DEFAULT = 1
            COLOR_ID_SYSTEM = 2
            COLOR_ID_JOIN_PART = 3
            COLOR_ID_NICK_CHANGE = 4
            COLOR_ID_MY_MESSAGE = 5
            COLOR_ID_OTHER_MESSAGE = 6
            COLOR_ID_HIGHLIGHT = 7
            COLOR_ID_ERROR = 8
            COLOR_ID_STATUS_BAR = 9
            COLOR_ID_SIDEBAR_HEADER = 10
            COLOR_ID_SIDEBAR_ITEM = 11
            COLOR_ID_INPUT = 12
            COLOR_ID_PM = 13
            COLOR_ID_USER_PREFIX = 14
            COLOR_ID_LIST_PANEL_BG = 15
            COLOR_ID_USER_LIST_PANEL_BG = 16
            COLOR_ID_MESSAGE_PANEL_BG = 17
            COLOR_ID_SIDEBAR_ACTIVE = 18 # New for active window highlight
            COLOR_ID_SIDEBAR_UNREAD = 19 # New for unread window highlight
            COLOR_ID_TIMESTAMP = 20
            COLOR_ID_SERVER_NAME = 21
            COLOR_ID_CHANNEL = 22
            COLOR_ID_NICK = 23
            COLOR_ID_MODE = 24

            # Helper to get 8-color curses constant from hex (via FALLBACK_8_COLOR_MAP)
            def get_8_color(hex_val):
                return FALLBACK_8_COLOR_MAP.get(hex_val, curses.COLOR_WHITE)

            # Initialize color pairs using 8-color fallback
            self._init_color_pair("default", COLOR_ID_DEFAULT, get_8_color(UI_COLOR_PALETTE["other_message"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["default"] = COLOR_ID_DEFAULT

            self._init_color_pair("message_panel_bg", COLOR_ID_MESSAGE_PANEL_BG, get_8_color(UI_COLOR_PALETTE["other_message"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["message_panel_bg"] = COLOR_ID_MESSAGE_PANEL_BG

            self._init_color_pair("list_panel_bg", COLOR_ID_LIST_PANEL_BG, get_8_color(UI_COLOR_PALETTE["other_message"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["list_panel_bg"] = COLOR_ID_LIST_PANEL_BG

            self._init_color_pair("status_bar", COLOR_ID_STATUS_BAR, get_8_color(UI_COLOR_PALETTE["status_bar_fg"]), get_8_color(UI_COLOR_PALETTE["status_background"]))
            self.color_name_to_id["status_bar"] = COLOR_ID_STATUS_BAR

            self._init_color_pair("input", COLOR_ID_INPUT, get_8_color(UI_COLOR_PALETTE["other_message"]), get_8_color(UI_COLOR_PALETTE["input_background"]))
            self.color_name_to_id["input"] = COLOR_ID_INPUT

            self._init_color_pair("channel", COLOR_ID_CHANNEL, get_8_color(UI_COLOR_PALETTE["channel"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["channel"] = COLOR_ID_CHANNEL

            self._init_color_pair("nick", COLOR_ID_NICK, get_8_color(UI_COLOR_PALETTE["nick"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["nick"] = COLOR_ID_NICK

            self._init_color_pair("mode", COLOR_ID_MODE, get_8_color(UI_COLOR_PALETTE["mode"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["mode"] = COLOR_ID_MODE

            self._init_color_pair("my_message", COLOR_ID_MY_MESSAGE, get_8_color(UI_COLOR_PALETTE["my_message"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["my_message"] = COLOR_ID_MY_MESSAGE

            self._init_color_pair("other_message", COLOR_ID_OTHER_MESSAGE, get_8_color(UI_COLOR_PALETTE["other_message"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["other_message"] = COLOR_ID_OTHER_MESSAGE

            self._init_color_pair("system_message", COLOR_ID_SYSTEM, get_8_color(UI_COLOR_PALETTE["system_message"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["system_message"] = COLOR_ID_SYSTEM

            self._init_color_pair("error_message", COLOR_ID_ERROR, get_8_color(UI_COLOR_PALETTE["error_message"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["error_message"] = COLOR_ID_ERROR

            self._init_color_pair("highlight_mention", COLOR_ID_HIGHLIGHT, get_8_color(UI_COLOR_PALETTE["highlight_mention"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["highlight_mention"] = COLOR_ID_HIGHLIGHT

            self._init_color_pair("timestamp", COLOR_ID_TIMESTAMP, get_8_color(UI_COLOR_PALETTE["timestamp"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["timestamp"] = COLOR_ID_TIMESTAMP

            self._init_color_pair("server_name", COLOR_ID_SERVER_NAME, get_8_color(UI_COLOR_PALETTE["server_name"]), get_8_color(UI_COLOR_PALETTE["main_background"]))
            self.color_name_to_id["server_name"] = COLOR_ID_SERVER_NAME

            self._init_color_pair("sidebar_active", COLOR_ID_SIDEBAR_ACTIVE, get_8_color(UI_COLOR_PALETTE["sidebar_active_fg"]), get_8_color(UI_COLOR_PALETTE["sidebar_active_bg"]))
            self.color_name_to_id["sidebar_active"] = COLOR_ID_SIDEBAR_ACTIVE

            self._init_color_pair("sidebar_unread", COLOR_ID_SIDEBAR_UNREAD, get_8_color(UI_COLOR_PALETTE["sidebar_unread_fg"]), get_8_color(UI_COLOR_PALETTE["sidebar_unread_bg"]))
            self.color_name_to_id["sidebar_unread"] = COLOR_ID_SIDEBAR_UNREAD

        # Assign the final color dictionary to self.colors
        # Store the raw pair_id in self.colors
        self.colors = self.color_name_to_id
        logger.debug(f"Final self.colors dictionary (raw IDs): {self.colors}")

    def _init_color_pair(self, name: str, pair_id: int, fg: int, bg: int):
        logger.debug(f"Initializing color pair '{name}' (ID: {pair_id}) with FG: {fg}, BG: {bg}")
        SafeCursesUtils._safe_init_pair(pair_id, fg, bg, f"CursesManager._init_color_pair_{name}")
        try:
            # Verify the color pair content immediately after initialization
            retrieved_fg, retrieved_bg = curses.pair_content(pair_id)
            logger.debug(f"Verified color pair '{name}' (ID: {pair_id}): Retrieved FG: {retrieved_fg}, Retrieved BG: {retrieved_bg}")
            if retrieved_fg != fg or retrieved_bg != bg:
                logger.warning(f"Color pair '{name}' (ID: {pair_id}) initialized with FG:{fg}, BG:{bg} but retrieved FG:{retrieved_fg}, BG:{retrieved_bg}. Mismatch detected!")

            self.colors[name] = pair_id # Store the raw pair_id, not the attribute
        except curses.error as e:
            logger.warning(f"Curses error verifying color pair {pair_id} for '{name}': {e}")
            self.colors[name] = pair_id # Still store the ID even if verification fails
        except Exception as ex:
            logger.error(f"Unexpected error storing or verifying color pair ID {pair_id} for '{name}': {ex}", exc_info=True)
            self.colors[name] = pair_id # Still store the ID

    def get_dimensions(self) -> Tuple[int, int]:
        try:
            self.height, self.width = self.stdscr.getmaxyx()
            return self.height, self.width
        except curses.error as e:
            logger.error(f"Curses error getting stdscr dimensions: {e}")
            return 0, 0

    def handle_terminal_resize(self, new_lines: int, new_cols: int):
        """Handles actual terminal resize by calling curses.resize_term and refreshing stdscr."""
        try:
            curses.resize_term(new_lines, new_cols) # Corrected typo: resizeterm -> resize_term
            self.height, self.width = self.stdscr.getmaxyx() # Update internal dims
            SafeCursesUtils._safe_clear(self.stdscr, "CursesManager.handle_terminal_resize_clear")
            SafeCursesUtils._safe_refresh(self.stdscr, "CursesManager.handle_terminal_resize_refresh")
            logger.info(f"CursesManager: Terminal resized to {new_lines}x{new_cols} and stdscr refreshed.")
        except curses.error as e:
            logger.error(f"Curses error in handle_terminal_resize: {e}")
        except Exception as ex:
            logger.error(f"Unexpected error in handle_terminal_resize: {ex}", exc_info=True)


    def resize_term(self, height: int, width: int):
        # curses.resizeterm is not consistently available on all platforms (e.g., Windows)
        # We rely on getmaxyx in UIManager to get updated dimensions and subsequent redraws.
        # This method can be a no-op or perform other necessary internal adjustments if needed.
        # For now, we'll just log if it's called.
        logger.debug(f"resize_term called to {height}x{width}. Relying on UIManager for redraw.")

    def update_screen(self):
        SafeCursesUtils._safe_doupdate("CursesManager.update_screen")

    def cleanup(self):
        SafeCursesUtils._safe_endwin("CursesManager.cleanup")
        logger.debug("Curses cleanup complete.")

    def get_color(self, name: str) -> int:
        # Return the curses attribute (color pair) for the given name
        pair_id = self.colors.get(name, 0)
        return curses.color_pair(pair_id)

    def noutrefresh_stdscr(self):
        SafeCursesUtils._safe_noutrefresh(self.stdscr, "CursesManager.noutrefresh_stdscr")

    def erase_stdscr(self):
        SafeCursesUtils._safe_erase(self.stdscr, "CursesManager.erase_stdscr")

    def clear_stdscr(self):
        SafeCursesUtils._safe_clear(self.stdscr, "CursesManager.clear_stdscr")

    def refresh_stdscr(self):
        SafeCursesUtils._safe_refresh(self.stdscr, "CursesManager.refresh_stdscr")

    def addstr_stdscr(self, y: int, x: int, text: str, attr: int):
        SafeCursesUtils._safe_addstr(self.stdscr, y, x, text, attr, "CursesManager.addstr_stdscr")

    def touchwin(self, window: Any):
        if window:
            SafeCursesUtils._safe_touchwin(window, f"CursesManager.touchwin_{window!r}")
    def clearok(self, window: Any, flag: bool):
        if window:
            SafeCursesUtils._safe_clearok(window, flag, f"CursesManager.clearok_{window!r}")
