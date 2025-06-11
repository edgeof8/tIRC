import curses
import sys
import os

def main(stdscr):
    # Clear and refresh the screen for a clean start
    stdscr.clear()
    stdscr.refresh()

    # Initialize colors
    curses.start_color()
    curses.use_default_colors()

    # Define a color pair: White foreground on Blue background
    # Pair ID 1: fg=curses.COLOR_WHITE, bg=curses.COLOR_BLUE
    try:
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
        WHITE_ON_BLUE = curses.color_pair(1)
    except curses.error as e:
        stdscr.addstr(0, 0, f"Error initializing color pair: {e}")
        stdscr.refresh()
        stdscr.getch()
        return

    # Get screen dimensions
    max_y, max_x = stdscr.getmaxyx()

    # --- Test 1: Fill entire screen with white on blue using addstr ---
    stdscr.addstr(0, 0, "Test 1: Filling screen with white on blue using addstr", curses.A_BOLD)
    stdscr.addstr(1, 0, "Press any key to continue...", curses.A_NORMAL)
    stdscr.refresh()
    stdscr.getch()

    stdscr.clear()
    for y in range(max_y):
        try:
            # Fill each line with spaces using the defined color pair
            stdscr.addstr(y, 0, ' ' * max_x, WHITE_ON_BLUE)
        except curses.error as e:
            stdscr.addstr(max_y - 1, 0, f"Error addstr at {y},0: {e}")
            break
    stdscr.refresh()
    stdscr.getch()

    # --- Test 2: Fill entire screen with white on blue using chgat ---
    stdscr.clear()
    stdscr.addstr(0, 0, "Test 2: Filling screen with white on blue using chgat", curses.A_BOLD)
    stdscr.addstr(1, 0, "Press any key to continue...", curses.A_NORMAL)
    stdscr.refresh()
    stdscr.getch()

    stdscr.clear()
    for y in range(max_y):
        try:
            # Change attributes of existing characters (after clear, they are default)
            stdscr.chgat(y, 0, max_x, WHITE_ON_BLUE)
        except curses.error as e:
            stdscr.addstr(max_y - 1, 0, f"Error chgat at {y},0: {e}")
            break
    stdscr.refresh()
    stdscr.getch()

    # --- Test 3: Draw "Hello World" with white on blue ---
    stdscr.clear()
    stdscr.addstr(0, 0, "Test 3: Drawing 'Hello World' with white on blue", curses.A_BOLD)
    stdscr.addstr(1, 0, "Press any key to continue...", curses.A_NORMAL)
    stdscr.refresh()
    stdscr.getch()

    stdscr.clear()
    test_string = "Hello World!"
    try:
        stdscr.addstr(max_y // 2, (max_x - len(test_string)) // 2, test_string, WHITE_ON_BLUE)
    except curses.error as e:
        stdscr.addstr(max_y - 1, 0, f"Error addstr 'Hello World': {e}")
    stdscr.refresh()
    stdscr.getch()

    # --- Test 4: Draw "Hello World" with white on blue, truncated ---
    stdscr.clear()
    stdscr.addstr(0, 0, "Test 4: Drawing 'Hello World' truncated", curses.A_BOLD)
    stdscr.addstr(1, 0, "Press any key to continue...", curses.A_NORMAL)
    stdscr.refresh()
    stdscr.getch()

    stdscr.clear()
    test_string_long = "This is a very long string that should be truncated by addnstr."
    try:
        # Use addnstr to explicitly truncate
        stdscr.addnstr(max_y // 2, 0, test_string_long, max_x // 2, WHITE_ON_BLUE)
    except curses.error as e:
        stdscr.addstr(max_y - 1, 0, f"Error addnstr truncated: {e}")
    stdscr.refresh()
    stdscr.getch()


    stdscr.addstr(max_y - 1, 0, "Tests complete. Press any key to exit.")
    stdscr.refresh()
    stdscr.getch()

if __name__ == '__main__':
    # Attempt to set locale for curses
    try:
        os.environ['NCURSES_NO_UTF8_ACS'] = '1' # Try disabling UTF-8 ACS if issues
        # os.environ['TERM'] = 'xterm-256color' # Can try forcing a terminal type
        # locale.setlocale(locale.LC_ALL, 'en_US.UTF-8') # Requires locale to be installed on system
    except Exception as e:
        print(f"Warning: Could not set locale or environment variables: {e}", file=sys.stderr)

    try:
        curses.wrapper(main)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        print("Please ensure your terminal supports curses and try again.", file=sys.stderr)
        print("On Windows, you might need 'pip install windows-curses'.", file=sys.stderr)
        sys.exit(1)
