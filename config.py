import configparser
import os
import logging
import fnmatch

logger = logging.getLogger("pyrc.config")
from typing import Type, Any, List, Union, Set

# --- Default Fallback Settings (if not in INI or INI is missing) ---
DEFAULT_SERVER = "irc.libera.chat"
DEFAULT_PORT = 6667
DEFAULT_SSL_PORT = 6697
DEFAULT_NICK = "PyTermUser"
DEFAULT_CHANNELS = ["#python", "#testchannel"]
DEFAULT_SSL = False
DEFAULT_PASSWORD = None
DEFAULT_NICKSERV_PASSWORD = None
DEFAULT_AUTO_RECONNECT = True
DEFAULT_VERIFY_SSL_CERT = True

# --- New Ignore List Settings ---
DEFAULT_IGNORED_PATTERNS = []

# --- Default Logging Settings ---
DEFAULT_LOG_ENABLED = True
DEFAULT_LOG_FILE = "pyrc.log"
DEFAULT_LOG_LEVEL = "INFO"  # e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL
DEFAULT_LOG_MAX_BYTES = 1024 * 1024 * 5  # 5 MB
DEFAULT_LOG_BACKUP_COUNT = 3
DEFAULT_CHANNEL_LOG_ENABLED = True

MAX_HISTORY = 500
RECONNECT_INITIAL_DELAY = 5  # seconds
RECONNECT_MAX_DELAY = 300  # seconds
CONNECTION_TIMEOUT = 30  # seconds
DEFAULT_LEAVE_MESSAGE = "PyRC - https://github.com/edgeof8/PyRC"

# Global variable to hold current ignore patterns
IGNORED_PATTERNS: Set[str] = set()

# --- Load Configuration from INI file ---
CONFIG_FILE_NAME = "pyterm_irc_config.ini"
config = configparser.ConfigParser()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, CONFIG_FILE_NAME)

# Read the config file if it exists
if os.path.exists(CONFIG_FILE_PATH):
    config.read(CONFIG_FILE_PATH)
else:
    print(
        f"Warning: Configuration file '{CONFIG_FILE_PATH}' not found. Using default values."
    )


# Helper function to get config values with fallbacks
def get_config_value(
    section: str, key: str, fallback: Any, value_type: Type = str
) -> Any:
    if config.has_section(section) and config.has_option(section, key):
        try:
            if value_type == bool:
                return config.getboolean(section, key)
            elif value_type == int:
                return config.getint(section, key)
            elif value_type == list:
                val = config.get(section, key)
                return (
                    [item.strip() for item in val.split(",") if item.strip()]
                    if val and val.strip()
                    else []
                )
            return config.get(section, key)
        except ValueError:
            return fallback
    return fallback


# Helper function to set config values and save to INI
def set_config_value(section: str, key: str, value: str) -> bool:
    """
    Sets a configuration value in the specified section and key,
    then writes the entire configuration back to the INI file.

    Args:
        section: The section name.
        key: The key name.
        value: The value to set (will be stored as a string).

    Returns:
        True if the value was set and saved successfully, False otherwise.
    """
    global config, CONFIG_FILE_PATH
    try:
        if not config.has_section(section):
            config.add_section(section)
        config.set(section, key, value)
        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)
        logging.info(f"Configuration updated: [{section}] {key} = {value}")
        return True
    except Exception as e:
        logging.error(f"Error writing to config file '{CONFIG_FILE_PATH}': {e}")
        return False


# Helper function to get all settings
def get_all_settings() -> dict:
    """
    Retrieves all settings from the configuration.

    Returns:
        A dictionary where keys are section names and values are
        dictionaries of key-value pairs within that section.
    """
    global config
    all_settings = {}
    for section in config.sections():
        all_settings[section] = {}
        for key in config.options(section):
            all_settings[section][key] = config.get(section, key)
    return all_settings


def save_current_config():
    global config, CONFIG_FILE_PATH
    try:
        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)
        logging.info("Configuration explicitly saved by /save command.")
        return True
    except Exception as e:
        logging.error(f"Error writing to config file '{CONFIG_FILE_PATH}' during /save: {e}")
        return False
# --- Functions to manage the ignore list in the config file ---
def load_ignore_list():
    """Loads ignore patterns from the config file into the global IGNORED_PATTERNS set."""
    global IGNORED_PATTERNS, config
    IGNORED_PATTERNS.clear()
    if config.has_section("IgnoreList"):
        for key, pattern in config.items("IgnoreList"):
            IGNORED_PATTERNS.add(pattern.strip())
    logging.info(f"Loaded {len(IGNORED_PATTERNS)} ignore patterns: {IGNORED_PATTERNS}")

def save_ignore_list():
    """Saves the global IGNORED_PATTERNS set to the config file."""
    global IGNORED_PATTERNS, config, CONFIG_FILE_PATH
    try:
        if config.has_section("IgnoreList"):
            config.remove_section("IgnoreList")
        if IGNORED_PATTERNS:
            config.add_section("IgnoreList")
            for i, pattern in enumerate(sorted(list(IGNORED_PATTERNS))):
                # Simpler: store "pattern = true" (or some dummy value, key is what matters)
                config.set("IgnoreList", pattern, "ignored")

        with open(CONFIG_FILE_PATH, "w") as configfile:
            config.write(configfile)
        logging.info(f"Saved {len(IGNORED_PATTERNS)} ignore patterns to config.")
    except Exception as e:
        logging.error(f"Error writing ignore list to config file '{CONFIG_FILE_PATH}': {e}")

def add_ignore_pattern(pattern: str) -> bool:
    """Adds a pattern to the ignore list and saves it."""
    global IGNORED_PATTERNS
    normalized_pattern = pattern.strip().lower()
    if not normalized_pattern:
        return False
    if normalized_pattern not in IGNORED_PATTERNS:
        IGNORED_PATTERNS.add(normalized_pattern)
        save_ignore_list()
        return True
    return False

def remove_ignore_pattern(pattern: str) -> bool:
    """Removes a pattern from the ignore list and saves it."""
    global IGNORED_PATTERNS
    normalized_pattern = pattern.strip().lower()
    if normalized_pattern in IGNORED_PATTERNS:
        IGNORED_PATTERNS.remove(normalized_pattern)
        save_ignore_list()
        return True
    return False

def is_source_ignored(source_full_ident: str) -> bool:
    """
    Checks if a source (nick!user@host) matches any of the stored ignore patterns.
    Uses fnmatch for wildcard matching. Patterns are matched case-insensitively.
    """
    global IGNORED_PATTERNS
    if not source_full_ident:
        return False

    source_lower = source_full_ident.lower()

    for pattern in IGNORED_PATTERNS:
        # Patterns are already stored lowercase
        if fnmatch.fnmatchcase(source_lower, pattern): # fnmatchcase is case-sensitive if pattern has mixed case
                                                       # but we store patterns lowercase, so this works
            return True
    return False

# --- Connection Settings (from INI or defaults) ---
IRC_SERVER = get_config_value("Connection", "default_server", DEFAULT_SERVER, str)
IRC_SSL = get_config_value("Connection", "default_ssl", DEFAULT_SSL, bool)
IRC_PORT = get_config_value(
    "Connection", "default_port", DEFAULT_SSL_PORT if IRC_SSL else DEFAULT_PORT, int
)
IRC_NICK = get_config_value("Connection", "default_nick", DEFAULT_NICK, str)
IRC_CHANNELS = get_config_value(
    "Connection", "default_channels", DEFAULT_CHANNELS, list
)
_raw_password = get_config_value("Connection", "password", DEFAULT_PASSWORD, str)
IRC_PASSWORD = _raw_password if _raw_password and _raw_password.strip() else None

_raw_nickserv_password = get_config_value(
    "Connection", "nickserv_password", DEFAULT_NICKSERV_PASSWORD, str
)
NICKSERV_PASSWORD = (
    _raw_nickserv_password
    if _raw_nickserv_password and _raw_nickserv_password.strip()
    else None
)

AUTO_RECONNECT = get_config_value(
    "Connection", "auto_reconnect", DEFAULT_AUTO_RECONNECT, bool
)
VERIFY_SSL_CERT = get_config_value(
    "Connection", "verify_ssl_cert", DEFAULT_VERIFY_SSL_CERT, bool
)


# --- UI Settings ---
_max_history_val = get_config_value("UI", "message_history_lines", MAX_HISTORY, int)
MAX_HISTORY = (
    int(_max_history_val) if isinstance(_max_history_val, int) else int(MAX_HISTORY)
)
UI_COLORSCHEME = get_config_value("UI", "colorscheme", "default", str)

# Color Pair IDs (curses)
# (ID, foreground, background (-1 for default terminal background))
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
COLOR_ID_SIDEBAR_USER = 11
COLOR_ID_INPUT = 12
COLOR_ID_PM = 13

# --- Logging Settings (from INI or defaults) ---
LOG_ENABLED = get_config_value("Logging", "log_enabled", DEFAULT_LOG_ENABLED, bool)
LOG_FILE = get_config_value("Logging", "log_file", DEFAULT_LOG_FILE, str)
LOG_LEVEL_STR = get_config_value("Logging", "log_level", DEFAULT_LOG_LEVEL, str).upper()
LOG_MAX_BYTES = get_config_value("Logging", "log_max_bytes", DEFAULT_LOG_MAX_BYTES, int)
LOG_BACKUP_COUNT = get_config_value(
    "Logging", "log_backup_count", DEFAULT_LOG_BACKUP_COUNT, int
)
CHANNEL_LOG_ENABLED = get_config_value(
    "Logging", "channel_log_enabled", DEFAULT_CHANNEL_LOG_ENABLED, bool
)

LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# --- General Settings ---
LEAVE_MESSAGE = get_config_value(
    "General", "leave_message", DEFAULT_LEAVE_MESSAGE, str
)


# --- IRC Protocol ---
# Regex for parsing IRC messages
# :prefix COMMAND params :trailing
# Example: :nick!user@host PRIVMSG #channel :Hello world!
# Breakdown:
# - Optional prefix: starts with : or @, followed by non-space, non-!, non-\r\n chars
# - Command: sequence of non-space, non-\r\n chars
# - Optional parameters: sequence of non-colon, non-\r\n chars
# - Optional trailing part: starts with a space and then a colon, followed by any non-\r\n chars
IRC_MSG_REGEX_PATTERN = r"^(?:@(?:[^ ]+) )?(?:[:]([^ ]+) )?([A-Z0-9]+|\d{3})(?: ([^:\r\n]*))?(?: ?:([^\r\n]*))?$"


def reload_all_config_values():
    """
    Reloads all configuration values from the INI file and updates
    the global variables in this module.
    """
    global config, CONFIG_FILE_PATH
    global IRC_SERVER, IRC_PORT, IRC_SSL, IRC_NICK, IRC_CHANNELS, IRC_PASSWORD, NICKSERV_PASSWORD
    global AUTO_RECONNECT, VERIFY_SSL_CERT
    global MAX_HISTORY, UI_COLORSCHEME
    global LOG_ENABLED, LOG_FILE, LOG_LEVEL_STR, LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT, CHANNEL_LOG_ENABLED
    global LEAVE_MESSAGE
    global IGNORED_PATTERNS # Though load_ignore_list handles this

    logger.info(f"Reloading configuration from {CONFIG_FILE_PATH}")
    config.read(CONFIG_FILE_PATH)

    # --- Connection Settings ---
    IRC_SERVER = get_config_value("Connection", "default_server", DEFAULT_SERVER, str)
    IRC_SSL = get_config_value("Connection", "default_ssl", DEFAULT_SSL, bool)
    IRC_PORT = get_config_value(
        "Connection", "default_port", DEFAULT_SSL_PORT if IRC_SSL else DEFAULT_PORT, int
    )
    IRC_NICK = get_config_value("Connection", "default_nick", DEFAULT_NICK, str)
    IRC_CHANNELS = get_config_value(
        "Connection", "default_channels", DEFAULT_CHANNELS, list
    )
    _raw_password_reload = get_config_value("Connection", "password", DEFAULT_PASSWORD, str)
    IRC_PASSWORD = _raw_password_reload if _raw_password_reload and _raw_password_reload.strip() else None

    _raw_nickserv_password_reload = get_config_value(
        "Connection", "nickserv_password", DEFAULT_NICKSERV_PASSWORD, str
    )
    NICKSERV_PASSWORD = (
        _raw_nickserv_password_reload
        if _raw_nickserv_password_reload and _raw_nickserv_password_reload.strip()
        else None
    )
    AUTO_RECONNECT = get_config_value(
        "Connection", "auto_reconnect", DEFAULT_AUTO_RECONNECT, bool
    )
    VERIFY_SSL_CERT = get_config_value(
        "Connection", "verify_ssl_cert", DEFAULT_VERIFY_SSL_CERT, bool
    )

    # --- UI Settings ---
    _max_history_val_reload = get_config_value("UI", "message_history_lines", MAX_HISTORY, int)
    MAX_HISTORY = (
        int(_max_history_val_reload) if isinstance(_max_history_val_reload, int) else int(MAX_HISTORY)
    )
    UI_COLORSCHEME = get_config_value("UI", "colorscheme", "default", str)

    # --- Logging Settings ---
    LOG_ENABLED = get_config_value("Logging", "log_enabled", DEFAULT_LOG_ENABLED, bool)
    LOG_FILE = get_config_value("Logging", "log_file", DEFAULT_LOG_FILE, str)
    LOG_LEVEL_STR = get_config_value("Logging", "log_level", DEFAULT_LOG_LEVEL, str).upper()
    LOG_MAX_BYTES = get_config_value("Logging", "log_max_bytes", DEFAULT_LOG_MAX_BYTES, int)
    LOG_BACKUP_COUNT = get_config_value(
        "Logging", "log_backup_count", DEFAULT_LOG_BACKUP_COUNT, int
    )
    CHANNEL_LOG_ENABLED = get_config_value(
        "Logging", "channel_log_enabled", DEFAULT_CHANNEL_LOG_ENABLED, bool
    )
    LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO) # Update log level based on new string

    # --- General Settings ---
    LEAVE_MESSAGE = get_config_value(
        "General", "leave_message", DEFAULT_LEAVE_MESSAGE, str
    )

    # --- Reload Ignore List ---
    load_ignore_list()
    logger.info("Configuration values reloaded.")


# --- Load initial ignore list at startup ---
load_ignore_list()
