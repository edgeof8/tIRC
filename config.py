# config.py
import configparser
import os
import logging  # Added for logging
from typing import Type, Any, List, Union

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
DEFAULT_VERIFY_SSL_CERT = True # Added for SSL certificate verification

# --- Default Logging Settings ---
DEFAULT_LOG_ENABLED = True
DEFAULT_LOG_FILE = "pyrc.log"
DEFAULT_LOG_LEVEL = "INFO"  # e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL
DEFAULT_LOG_MAX_BYTES = 1024 * 1024 * 5  # 5 MB
DEFAULT_LOG_BACKUP_COUNT = 3

MAX_HISTORY = 500  # Will be overridden by INI if present
RECONNECT_INITIAL_DELAY = 5  # seconds
RECONNECT_MAX_DELAY = 300  # seconds
CONNECTION_TIMEOUT = 30  # seconds

# --- Load Configuration from INI file ---
CONFIG_FILE_NAME = "pyterm_irc_config.ini"
config = configparser.ConfigParser()

# Determine the path to the config file (assuming it's in the same directory as this script)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, CONFIG_FILE_NAME)

# Read the config file if it exists
if os.path.exists(CONFIG_FILE_PATH):
    config.read(CONFIG_FILE_PATH)
else:
    # In a real application, you might want to create a default config or log a warning
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
                # Return empty list if val is empty or only whitespace, otherwise split
                return (
                    [item.strip() for item in val.split(",") if item.strip()]
                    if val and val.strip()
                    else []
                )
            return config.get(section, key)  # Defaults to string
        except ValueError:  # Handles cases where conversion might fail for int/bool
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
        # Optionally, re-read global variables that depend on this setting
        # or notify parts of the application. For now, just save.
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
# Ensure password is treated as string, None is acceptable if not set.
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
# Update MAX_HISTORY from INI if available
# Ensure MAX_HISTORY is an int, as deque expects int or None for maxlen.
_max_history_val = get_config_value("UI", "message_history_lines", MAX_HISTORY, int)
# If _max_history_val is not an int (e.g. due to conversion error in get_config_value returning fallback),
# use the original MAX_HISTORY.
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

# Convert log level string to logging module's level integer
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)


# --- IRC Protocol ---
# Regex for parsing IRC messages
# :prefix COMMAND params :trailing
# Example: :nick!user@host PRIVMSG #channel :Hello world!
# Breakdown:
# - Optional prefix: starts with : or @, followed by non-space, non-!, non-\r\n chars
# - Command: sequence of non-space, non-\r\n chars
# - Optional parameters: sequence of non-colon, non-\r\n chars
# - Optional trailing part: starts with a space and then a colon, followed by any non-\r\n chars
# Original:
# IRC_MSG_REGEX_PATTERN = r"^(?:[:@]([^ !\r\n]+) )?([^ \r\n]+)(?: ([^:\r\n]*))?(?: ?:([^\r\n]*))?$"
# Corrected:
IRC_MSG_REGEX_PATTERN = r"^(?:@(?:[^ ]+) )?(?:[:]([^ ]+) )?([A-Z0-9]+|\d{3})(?: ([^:\r\n]*))?(?: ?:([^\r\n]*))?$"
