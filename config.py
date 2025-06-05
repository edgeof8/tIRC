import configparser
import os
import logging
import fnmatch
from dataclasses import dataclass, field
from typing import Type, Any, List, Union, Set, Dict, Optional

logger = logging.getLogger("pyrc.config")


@dataclass # Defines server-specific connection and behavior settings
class ServerConfig:
    server_id: str
    address: str
    port: int
    ssl: bool
    nick: str
    channels: List[str] = field(default_factory=list)
    username: Optional[str] = None
    realname: Optional[str] = None
    server_password: Optional[str] = None
    nickserv_password: Optional[str] = None
    sasl_username: Optional[str] = None
    sasl_password: Optional[str] = None
    verify_ssl_cert: bool = True
    auto_connect: bool = False
    desired_caps: Optional[List[str]] = None

    def __post_init__(self):
        if self.username is None:
            self.username = self.nick
        if self.realname is None:
            self.realname = self.nick
        if self.sasl_username is None: # Default SASL username to nick
            self.sasl_username = self.nick
        if self.sasl_password is None: # Default SASL password to nickserv_password
            self.sasl_password = self.nickserv_password

# Global server configuration storage
ALL_SERVER_CONFIGS: Dict[str, ServerConfig] = {}
DEFAULT_SERVER_CONFIG_NAME: Optional[str] = None

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

# --- Feature Settings ---
DEFAULT_ENABLE_TRIGGER_SYSTEM = True
DEFAULT_DISABLED_SCRIPTS = []
DEFAULT_HEADLESS_MAX_HISTORY = 50

# --- New Ignore List Settings ---
DEFAULT_IGNORED_PATTERNS = []

# --- Default Logging Settings ---
DEFAULT_LOG_ENABLED = True
DEFAULT_LOG_FILE = "pyrc_core.log"
DEFAULT_LOG_LEVEL = "INFO"  # e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL
DEFAULT_LOG_MAX_BYTES = 1024 * 1024 * 5  # 5 MB
DEFAULT_LOG_BACKUP_COUNT = 3
DEFAULT_CHANNEL_LOG_ENABLED = True
DEFAULT_STATUS_WINDOW_LOG_FILE = "client_status_messages.log"
DEFAULT_MAX_HISTORY = 500 # Renamed from MAX_HISTORY for use as default
DEFAULT_RECONNECT_INITIAL_DELAY = 1  # seconds
DEFAULT_RECONNECT_MAX_DELAY = 60  # seconds
DEFAULT_CONNECTION_TIMEOUT = 30  # seconds

# Defaults for direct import if needed by other modules, though ServerConfig is preferred
# These are often specific to a server configuration rather than global.
# Consider fetching from active ServerConfig where possible.
WEBIRC_USERNAME: Optional[str] = None
WEBIRC_PASSWORD: Optional[str] = None
WEBIRC_HOSTNAME: Optional[str] = None
WEBIRC_IP: Optional[str] = None
SASL_MECHANISM: Optional[str] = "PLAIN" # Default to PLAIN or None
# SASL_USERNAME and SASL_PASSWORD typically come from specific server configs or NickServ password.
# Setting them to None here means they must be configured per server if SASL is used.
SASL_USERNAME_GLOBAL_DEFAULT: Optional[str] = None # Renamed to avoid conflict if a ServerConfig has sasl_username
SASL_PASSWORD_GLOBAL_DEFAULT: Optional[str] = None # Renamed
# --- DCC Configuration Defaults ---
DEFAULT_DCC_ENABLED = True
DEFAULT_DCC_DOWNLOAD_DIR = "downloads"
DEFAULT_DCC_UPLOAD_DIR = "uploads"
DEFAULT_DCC_AUTO_ACCEPT = False
DEFAULT_DCC_AUTO_ACCEPT_FROM_FRIENDS = True
DEFAULT_DCC_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
DEFAULT_DCC_PORT_RANGE_START = 1024
DEFAULT_DCC_PORT_RANGE_END = 65535
DEFAULT_DCC_TIMEOUT = 300  # 5 minutes
DEFAULT_DCC_RESUME_ENABLED = True # For enabling resume capability
DEFAULT_DCC_CHECKSUM_VERIFY = True # Phase 2
DEFAULT_DCC_CHECKSUM_ALGORITHM = "md5" # md5, sha1, sha256, etc. (Phase 2)
DEFAULT_DCC_BANDWIDTH_LIMIT = 0  # 0 = unlimited, bytes per second (Phase 4)
DEFAULT_DCC_BLOCKED_EXTENSIONS = ['.exe', '.bat', '.com', '.scr', '.vbs', '.pif']
DEFAULT_DCC_PASSIVE_MODE_TOKEN_TIMEOUT = 120 # Seconds for a passive mode token to be valid (Phase 2)
DEFAULT_DCC_VIRUS_SCAN_CMD = "" # Phase 4
DEFAULT_DCC_LOG_ENABLED = True
DEFAULT_DCC_LOG_FILE = "dcc.log"
DEFAULT_DCC_LOG_LEVEL = "INFO" # Similar to main log level
DEFAULT_DCC_LOG_MAX_BYTES = 5 * 1024 * 1024 # 5MB
DEFAULT_DCC_LOG_BACKUP_COUNT = 3

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
        logging.error(
            f"Error writing to config file '{CONFIG_FILE_PATH}' during /save: {e}"
        )
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
        logging.error(
            f"Error writing ignore list to config file '{CONFIG_FILE_PATH}': {e}"
        )


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
        if fnmatch.fnmatchcase(
            source_lower, pattern
        ):  # fnmatchcase is case-sensitive if pattern has mixed case
            # but we store patterns lowercase, so this works
            return True
    return False


# --- Connection Settings (will be populated by load_server_configurations or fallbacks) ---
# These will be populated by load_server_configurations or fall back to DEFAULT_ values if no config loaded
IRC_SERVER: str = DEFAULT_SERVER
IRC_PORT: int = DEFAULT_PORT # Default to non-SSL port initially
IRC_SSL: bool = DEFAULT_SSL
IRC_NICK: str = DEFAULT_NICK
IRC_CHANNELS: List[str] = DEFAULT_CHANNELS[:]
IRC_PASSWORD: Optional[str] = DEFAULT_PASSWORD
NICKSERV_PASSWORD: Optional[str] = DEFAULT_NICKSERV_PASSWORD
VERIFY_SSL_CERT: bool = DEFAULT_VERIFY_SSL_CERT

# Initialize other globals with their DEFAULT values first.
# They will be updated by get_config_value later if config exists.
AUTO_RECONNECT: bool = DEFAULT_AUTO_RECONNECT
MAX_HISTORY: int = DEFAULT_MAX_HISTORY
UI_COLORSCHEME: str = "default" # Assuming "default" is the string for DEFAULT_UI_COLORSCHEME if it existed
LOG_ENABLED: bool = DEFAULT_LOG_ENABLED
LOG_FILE: str = DEFAULT_LOG_FILE
LOG_LEVEL_STR: str = DEFAULT_LOG_LEVEL.upper()
LOG_MAX_BYTES: int = DEFAULT_LOG_MAX_BYTES
LOG_BACKUP_COUNT: int = DEFAULT_LOG_BACKUP_COUNT
CHANNEL_LOG_ENABLED: bool = DEFAULT_CHANNEL_LOG_ENABLED
# LOG_LEVEL will be set after LOG_LEVEL_STR is potentially updated from config
LOG_LEVEL: int = getattr(logging, LOG_LEVEL_STR, logging.INFO)
if not isinstance(LOG_LEVEL, int): LOG_LEVEL = logging.INFO # Ensure it's an int

ENABLE_TRIGGER_SYSTEM: bool = DEFAULT_ENABLE_TRIGGER_SYSTEM
DISABLED_SCRIPTS: List[str] = DEFAULT_DISABLED_SCRIPTS[:]
HEADLESS_MAX_HISTORY: int = DEFAULT_HEADLESS_MAX_HISTORY

# Color Pair IDs (curses) - These are constants, not from config
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

# --- IRC Protocol --- (This is a constant, fine as is)
# Regex for parsing IRC messages
# :prefix COMMAND params :trailing
# Example: :nick!user@host PRIVMSG #channel :Hello world!
# Breakdown:
# - Optional prefix: starts with : or @, followed by non-space, non-!, non-\r\n chars
# - Command: sequence of non-space, non-\r\n chars
# - Optional parameters: sequence of non-colon, non-\r\n chars
# - Optional trailing part: starts with a space and then a colon, followed by any non-\r\n chars
IRC_MSG_REGEX_PATTERN = r"^(?:@(?:[^ ]+) )?(?:[:]([^ ]+) )?([A-Z0-9]+|\d{3})(?: ([^:\r\n]*))?(?: ?:([^\r\n]*))?$"


def load_server_configurations():
    global ALL_SERVER_CONFIGS, DEFAULT_SERVER_CONFIG_NAME, config
    global IRC_SERVER, IRC_PORT, IRC_SSL, IRC_NICK, IRC_CHANNELS
    global IRC_PASSWORD, NICKSERV_PASSWORD, VERIFY_SSL_CERT # Add other globals to update

    logger.debug("Loading server configurations...")
    ALL_SERVER_CONFIGS.clear()
    DEFAULT_SERVER_CONFIG_NAME = None
    found_explicit_auto_connect = False

    for section_name in config.sections():
        if section_name.startswith("Server."):
            server_id = section_name[7:]
            if not server_id:
                logger.warning(f"Skipping server section with empty ID: {section_name}")
                continue

            try:
                # Use direct config.get for mandatory, config.get(fallback=...) for optional strings
                # and config.getboolean/getint for others.
                desired_caps_str = config.get(section_name, "desired_caps", fallback=None)
                desired_caps_list = [cap.strip() for cap in desired_caps_str.split(',')] if desired_caps_str and desired_caps_str.strip() else None

                s_config = ServerConfig(
                    server_id=server_id,
                    address=config.get(section_name, "address"),
                    port=config.getint(section_name, "port"),
                    ssl=config.getboolean(section_name, "ssl"),
                    nick=config.get(section_name, "nick"),
                    channels=[ch.strip() for ch in config.get(section_name, "channels", fallback="").split(',') if ch.strip()],
                    username=config.get(section_name, "username", fallback=None),
                    realname=config.get(section_name, "realname", fallback=None),
                    server_password=config.get(section_name, "server_password", fallback=None),
                    nickserv_password=config.get(section_name, "nickserv_password", fallback=None),
                    sasl_username=config.get(section_name, "sasl_username", fallback=None),
                    sasl_password=config.get(section_name, "sasl_password", fallback=None),
                    verify_ssl_cert=config.getboolean(section_name, "verify_ssl_cert", fallback=DEFAULT_VERIFY_SSL_CERT),
                    auto_connect=config.getboolean(section_name, "auto_connect", fallback=False),
                    desired_caps=desired_caps_list
                )
                ALL_SERVER_CONFIGS[server_id] = s_config
                logger.info(f"Loaded server configuration: [{s_config.server_id}] {s_config.address}")
                if s_config.auto_connect and not found_explicit_auto_connect:
                    DEFAULT_SERVER_CONFIG_NAME = server_id
                    found_explicit_auto_connect = True
                    logger.info(f"Default server set to '{server_id}' due to auto_connect=true.")
            except (configparser.NoOptionError, ValueError) as e:
                logger.error(f"Error parsing configuration for server '{server_id}' in section '[{section_name}]': {e}. Skipping this server.")
            except Exception as e:
                logger.error(f"Unexpected error loading server configuration for '{server_id}': {e}", exc_info=True)


    if not found_explicit_auto_connect and ALL_SERVER_CONFIGS:
        DEFAULT_SERVER_CONFIG_NAME = sorted(ALL_SERVER_CONFIGS.keys())[0]
        logger.warning(f"No server has auto_connect=true. Defaulting to first server found: '{DEFAULT_SERVER_CONFIG_NAME}'.")

    if not DEFAULT_SERVER_CONFIG_NAME and config.has_section("Connection") and config.has_option("Connection", "default_server"):
        logger.warning("No [Server.<Name>] sections found or no auto_connect. Attempting to use legacy [Connection] section for default.")
        try:
            # Use get_config_value for legacy section for consistency with its design (handles fallbacks well)
            default_conf = ServerConfig(
                server_id="Default_Legacy",
                address=get_config_value("Connection", "default_server", DEFAULT_SERVER, str),
                port=get_config_value("Connection", "default_port", DEFAULT_PORT, int),
                ssl=get_config_value("Connection", "default_ssl", DEFAULT_SSL, bool),
                nick=get_config_value("Connection", "default_nick", DEFAULT_NICK, str),
                channels=get_config_value("Connection", "default_channels", DEFAULT_CHANNELS, list),
                username=get_config_value("Connection", "default_nick", DEFAULT_NICK, str),
                realname=get_config_value("Connection", "default_nick", DEFAULT_NICK, str),
                server_password=get_config_value("Connection", "password", DEFAULT_PASSWORD, str), # Ensure fallback is None if appropriate
                nickserv_password=get_config_value("Connection", "nickserv_password", DEFAULT_NICKSERV_PASSWORD, str), # Ensure fallback is None
                verify_ssl_cert=get_config_value("Connection", "verify_ssl_cert", DEFAULT_VERIFY_SSL_CERT, bool),
                auto_connect=True
            )
            # Ensure optional passwords from legacy are None if empty after get_config_value
            if default_conf.server_password == "" : default_conf.server_password = None
            if default_conf.nickserv_password == "" : default_conf.nickserv_password = None

            ALL_SERVER_CONFIGS["Default_Legacy"] = default_conf
            DEFAULT_SERVER_CONFIG_NAME = "Default_Legacy"
            logger.warning("Using legacy [Connection] settings for default server. Please migrate to [Server.<Name>] format.")
        except Exception as e:
            logger.error(f"Could not create default server from legacy [Connection] settings: {e}", exc_info=True)

    if DEFAULT_SERVER_CONFIG_NAME and DEFAULT_SERVER_CONFIG_NAME in ALL_SERVER_CONFIGS:
        active_conf = ALL_SERVER_CONFIGS[DEFAULT_SERVER_CONFIG_NAME]
        IRC_SERVER = active_conf.address
        IRC_PORT = active_conf.port
        IRC_SSL = active_conf.ssl
        IRC_NICK = active_conf.nick
        IRC_CHANNELS = active_conf.channels[:]
        IRC_PASSWORD = active_conf.server_password
        NICKSERV_PASSWORD = active_conf.nickserv_password
        VERIFY_SSL_CERT = active_conf.verify_ssl_cert
        logger.info(f"Module-level globals updated from default server: {DEFAULT_SERVER_CONFIG_NAME}")
    elif not ALL_SERVER_CONFIGS:
         logger.warning("No server configurations loaded. Client will require CLI arguments or /connect to specify a server.")
         # Fallback to hardcoded defaults if no server config (legacy or new) is found
         IRC_SERVER = DEFAULT_SERVER
         IRC_PORT = DEFAULT_PORT
         IRC_SSL = DEFAULT_SSL
         IRC_NICK = DEFAULT_NICK
         IRC_CHANNELS = DEFAULT_CHANNELS[:]
         IRC_PASSWORD = DEFAULT_PASSWORD
         NICKSERV_PASSWORD = DEFAULT_NICKSERV_PASSWORD
         VERIFY_SSL_CERT = DEFAULT_VERIFY_SSL_CERT

def reload_all_config_values():
    global config, CONFIG_FILE_PATH
    global AUTO_RECONNECT
    global MAX_HISTORY, UI_COLORSCHEME
    global LOG_ENABLED, LOG_FILE, LOG_LEVEL_STR, LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT, CHANNEL_LOG_ENABLED
    global ENABLE_TRIGGER_SYSTEM, DISABLED_SCRIPTS, HEADLESS_MAX_HISTORY

    logger.info(f"Reloading configuration from {CONFIG_FILE_PATH}")
    new_config = configparser.ConfigParser() # Use a new ConfigParser instance for read
    new_config.read(CONFIG_FILE_PATH)
    config = new_config # Assign to global config after successful read

    load_server_configurations()

    AUTO_RECONNECT = get_config_value("Connection", "auto_reconnect", DEFAULT_AUTO_RECONNECT, bool)

    ENABLE_TRIGGER_SYSTEM = get_config_value("Features", "enable_trigger_system", DEFAULT_ENABLE_TRIGGER_SYSTEM, bool)
    DISABLED_SCRIPTS = get_config_value("Scripts", "disabled_scripts", DEFAULT_DISABLED_SCRIPTS, list)

    # HEADLESS_MAX_HISTORY will be updated from config if present
    temp_headless_max_hist = get_config_value("UI", "headless_message_history_lines", DEFAULT_HEADLESS_MAX_HISTORY, int)
    if isinstance(temp_headless_max_hist, int) and temp_headless_max_hist >= 0:
        HEADLESS_MAX_HISTORY = temp_headless_max_hist
    else:
        HEADLESS_MAX_HISTORY = DEFAULT_HEADLESS_MAX_HISTORY # Fallback to default constant

    MAX_HISTORY = get_config_value("UI", "message_history_lines", DEFAULT_MAX_HISTORY, int)
    UI_COLORSCHEME = get_config_value("UI", "colorscheme", "default", str) # Assuming "default" is the fallback string for UI_COLORSCHEME

    LOG_ENABLED = get_config_value("Logging", "log_enabled", DEFAULT_LOG_ENABLED, bool)
    LOG_FILE = get_config_value("Logging", "log_file", DEFAULT_LOG_FILE, str)

    LOG_LEVEL_STR = get_config_value("Logging", "log_level", DEFAULT_LOG_LEVEL, str).upper()

    _log_level_int_reload = getattr(logging, LOG_LEVEL_STR, None)
    if not isinstance(_log_level_int_reload, int):
        _log_level_int_reload = getattr(logging, DEFAULT_LOG_LEVEL.upper(), logging.INFO)
        if not isinstance(_log_level_int_reload, int):
            _log_level_int_reload = logging.INFO
    LOG_LEVEL = _log_level_int_reload

    LOG_MAX_BYTES = get_config_value("Logging", "log_max_bytes", DEFAULT_LOG_MAX_BYTES, int)
    LOG_BACKUP_COUNT = get_config_value("Logging", "log_backup_count", DEFAULT_LOG_BACKUP_COUNT, int)
    CHANNEL_LOG_ENABLED = get_config_value("Logging", "channel_log_enabled", DEFAULT_CHANNEL_LOG_ENABLED, bool)

    load_ignore_list()
    logger.info("Configuration values reloaded.")

# --- End of function definitions, start of module execution ---

# Initial configuration read (already done at the top of the module)
# if os.path.exists(CONFIG_FILE_PATH):
#     config.read(CONFIG_FILE_PATH)
# else:
#     logger.warning(f"Configuration file '{CONFIG_FILE_PATH}' not found at module load. Using hardcoded defaults initially.")

# Load server configurations (which also sets server-related globals)
load_server_configurations()

# Load ignore list
load_ignore_list()

# Initialize non-server specific globals from config or defaults
# These were previously defined scattered or hardcoded at the end.
# Now, we ensure they are loaded from 'config' object after it has been read.

AUTO_RECONNECT = get_config_value("Connection", "auto_reconnect", DEFAULT_AUTO_RECONNECT, bool)

# These are already initialized with DEFAULT_ values above.
# The get_config_value calls will update them if values are found in the config file.
MAX_HISTORY = get_config_value("UI", "message_history_lines", DEFAULT_MAX_HISTORY, int)
UI_COLORSCHEME = get_config_value("UI", "colorscheme", "default", str)

temp_headless_max_hist_init = get_config_value("UI", "headless_message_history_lines", DEFAULT_HEADLESS_MAX_HISTORY, int)
if isinstance(temp_headless_max_hist_init, int) and temp_headless_max_hist_init >= 0:
    HEADLESS_MAX_HISTORY = temp_headless_max_hist_init
else:
    HEADLESS_MAX_HISTORY = DEFAULT_HEADLESS_MAX_HISTORY


LOG_ENABLED = get_config_value("Logging", "log_enabled", DEFAULT_LOG_ENABLED, bool)
# LOG_FILE is set here:
# 1. Reads from pyterm_irc_config.ini's [Logging] section, key 'log_file'.
# 2. If not found, uses the Python variable DEFAULT_LOG_FILE (which is "pyrc_core.log") as fallback.
LOG_FILE = get_config_value("Logging", "log_file", DEFAULT_LOG_FILE, str)

LOG_LEVEL_STR = get_config_value("Logging", "log_level", DEFAULT_LOG_LEVEL, str).upper()
_log_level_int_module_init = getattr(logging, LOG_LEVEL_STR, None)
if not isinstance(_log_level_int_module_init, int):
    _log_level_int_module_init = getattr(logging, DEFAULT_LOG_LEVEL.upper(), logging.INFO)
    if not isinstance(_log_level_int_module_init, int):
        _log_level_int_module_init = logging.INFO
LOG_LEVEL = _log_level_int_module_init


LOG_MAX_BYTES = get_config_value("Logging", "log_max_bytes", DEFAULT_LOG_MAX_BYTES, int)
LOG_BACKUP_COUNT = get_config_value("Logging", "log_backup_count", DEFAULT_LOG_BACKUP_COUNT, int)
CHANNEL_LOG_ENABLED = get_config_value("Logging", "channel_log_enabled", DEFAULT_CHANNEL_LOG_ENABLED, bool)

ENABLE_TRIGGER_SYSTEM = get_config_value("Features", "enable_trigger_system", DEFAULT_ENABLE_TRIGGER_SYSTEM, bool)
DISABLED_SCRIPTS = get_config_value("Scripts", "disabled_scripts", DEFAULT_DISABLED_SCRIPTS, list)
# --- DCC Configuration Loading ---
DCC_ENABLED = get_config_value("DCC", "enabled", DEFAULT_DCC_ENABLED, bool)
DCC_DOWNLOAD_DIR = get_config_value("DCC", "download_dir", DEFAULT_DCC_DOWNLOAD_DIR, str)
DCC_UPLOAD_DIR = get_config_value("DCC", "upload_dir", DEFAULT_DCC_UPLOAD_DIR, str)
DCC_AUTO_ACCEPT = get_config_value("DCC", "auto_accept", DEFAULT_DCC_AUTO_ACCEPT, bool)
DCC_AUTO_ACCEPT_FROM_FRIENDS = get_config_value("DCC", "auto_accept_from_friends", DEFAULT_DCC_AUTO_ACCEPT_FROM_FRIENDS, bool)
DCC_MAX_FILE_SIZE = get_config_value("DCC", "max_file_size", DEFAULT_DCC_MAX_FILE_SIZE, int)
DCC_PORT_RANGE_START = get_config_value("DCC", "port_range_start", DEFAULT_DCC_PORT_RANGE_START, int)
DCC_PORT_RANGE_END = get_config_value("DCC", "port_range_end", DEFAULT_DCC_PORT_RANGE_END, int)
DCC_TIMEOUT = get_config_value("DCC", "timeout", DEFAULT_DCC_TIMEOUT, int)
DCC_RESUME_ENABLED = get_config_value("DCC", "resume_enabled", DEFAULT_DCC_RESUME_ENABLED, bool)
DCC_CHECKSUM_VERIFY = get_config_value("DCC", "checksum_verify", DEFAULT_DCC_CHECKSUM_VERIFY, bool) # Phase 2
DCC_CHECKSUM_ALGORITHM = get_config_value("DCC", "checksum_algorithm", DEFAULT_DCC_CHECKSUM_ALGORITHM, str).lower() # Phase 2
DCC_BANDWIDTH_LIMIT = get_config_value("DCC", "bandwidth_limit", DEFAULT_DCC_BANDWIDTH_LIMIT, int) # Phase 4
DCC_BLOCKED_EXTENSIONS = get_config_value("DCC", "blocked_extensions", DEFAULT_DCC_BLOCKED_EXTENSIONS, list)
DCC_PASSIVE_MODE_TOKEN_TIMEOUT = get_config_value("DCC", "passive_token_timeout", DEFAULT_DCC_PASSIVE_MODE_TOKEN_TIMEOUT, int) # Phase 2
DCC_VIRUS_SCAN_CMD = get_config_value("DCC", "virus_scan_cmd", DEFAULT_DCC_VIRUS_SCAN_CMD, str) # Phase 4
DCC_LOG_ENABLED = get_config_value("DCC", "log_enabled", DEFAULT_DCC_LOG_ENABLED, bool)
DCC_LOG_FILE = get_config_value("DCC", "log_file", DEFAULT_DCC_LOG_FILE, str)
DCC_LOG_LEVEL_STR = get_config_value("DCC", "log_level", DEFAULT_DCC_LOG_LEVEL, str).upper()
_dcc_log_level_int = getattr(logging, DCC_LOG_LEVEL_STR, None)
if not isinstance(_dcc_log_level_int, int):
    _dcc_log_level_int = getattr(logging, DEFAULT_DCC_LOG_LEVEL.upper(), logging.INFO)
    if not isinstance(_dcc_log_level_int, int): _dcc_log_level_int = logging.INFO
DCC_LOG_LEVEL = _dcc_log_level_int
DCC_LOG_MAX_BYTES = get_config_value("DCC", "log_max_bytes", DEFAULT_DCC_LOG_MAX_BYTES, int)
DCC_LOG_BACKUP_COUNT = get_config_value("DCC", "log_backup_count", DEFAULT_DCC_LOG_BACKUP_COUNT, int)


# Constants that are not typically from config file but used by logic
CONNECTION_TIMEOUT = DEFAULT_CONNECTION_TIMEOUT
RECONNECT_INITIAL_DELAY = DEFAULT_RECONNECT_INITIAL_DELAY
RECONNECT_MAX_DELAY = DEFAULT_RECONNECT_MAX_DELAY

# IRC_MSG_REGEX_PATTERN is already defined earlier and is a constant pattern.
# Color ID constants are also fine as they are.

# Remove old hardcoded/redundant globals from the very end if they existed.
# The VERIFY_SSL_CERT global will be set by load_server_configurations if a default server is found,
# otherwise it will retain its value from the top-level get_config_value("Connection", "verify_ssl_cert", ...)
# or DEFAULT_VERIFY_SSL_CERT if [Connection] section is missing.
# This is fine, as IRCClient_Logic will use ServerConfig.verify_ssl_cert.
