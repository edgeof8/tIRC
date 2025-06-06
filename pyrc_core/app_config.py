# pyrc_core/app_config.py
import configparser
import os
import logging
import fnmatch
from dataclasses import dataclass, field
from typing import Type, Any, List, Set, Dict, Optional

logger = logging.getLogger("pyrc.config")

# --- Default Fallback Constants ---
# These are used as fallbacks if values are not found in the INI file.

# Connection
DEFAULT_SERVER = "irc.libera.chat"
DEFAULT_PORT = 6667
DEFAULT_SSL_PORT = 6697
DEFAULT_NICK = "PyTermUser"
DEFAULT_CHANNELS = ["#python"]
DEFAULT_SSL = False
DEFAULT_PASSWORD = None
DEFAULT_NICKSERV_PASSWORD = None
DEFAULT_AUTO_RECONNECT = True
DEFAULT_VERIFY_SSL_CERT = True
DEFAULT_RECONNECT_INITIAL_DELAY = 1
DEFAULT_RECONNECT_MAX_DELAY = 60
DEFAULT_CONNECTION_TIMEOUT = 30

# Features
DEFAULT_ENABLE_TRIGGER_SYSTEM = True
DEFAULT_DISABLED_SCRIPTS: Set[str] = {"run_headless_tests", "test_dcc_features"}
DEFAULT_IGNORED_PATTERNS = []

# UI
DEFAULT_MAX_HISTORY = 500
DEFAULT_HEADLESS_MAX_HISTORY = 50

# Logging
DEFAULT_LOG_ENABLED = True
DEFAULT_LOG_FILE = "pyrc_core.log"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_ERROR_FILE = "pyrc_error.log"
DEFAULT_LOG_ERROR_LEVEL = "WARNING"
DEFAULT_LOG_MAX_BYTES = 1024 * 1024 * 5  # 5 MB
DEFAULT_LOG_BACKUP_COUNT = 3
DEFAULT_CHANNEL_LOG_ENABLED = True
DEFAULT_STATUS_WINDOW_LOG_FILE = "client_status_messages.log"

# DCC
DEFAULT_DCC_ENABLED = True
DEFAULT_DCC_DOWNLOAD_DIR = "downloads"
DEFAULT_DCC_UPLOAD_DIR = "uploads"
DEFAULT_DCC_AUTO_ACCEPT = False
DEFAULT_DCC_MAX_FILE_SIZE = 100 * 1024 * 1024
DEFAULT_DCC_PORT_RANGE_START = 1024
DEFAULT_DCC_PORT_RANGE_END = 65535
DEFAULT_DCC_TIMEOUT = 300
DEFAULT_DCC_RESUME_ENABLED = True
DEFAULT_DCC_CHECKSUM_VERIFY = True
DEFAULT_DCC_CHECKSUM_ALGORITHM = "md5"
DEFAULT_DCC_BANDWIDTH_LIMIT_SEND_KBPS = 0
DEFAULT_DCC_BANDWIDTH_LIMIT_RECV_KBPS = 0
DEFAULT_DCC_BLOCKED_EXTENSIONS = ['.exe', '.bat', '.com', '.scr', '.vbs', '.pif']
DEFAULT_DCC_PASSIVE_MODE_TOKEN_TIMEOUT = 120
DEFAULT_DCC_ADVERTISED_IP: Optional[str] = None
DEFAULT_DCC_CLEANUP_ENABLED = True
DEFAULT_DCC_CLEANUP_INTERVAL_SECONDS = 3600
DEFAULT_DCC_TRANSFER_MAX_AGE_SECONDS = 86400 * 3
DEFAULT_DCC_LOG_ENABLED = True
DEFAULT_DCC_LOG_FILE = "dcc.log"
DEFAULT_DCC_LOG_LEVEL = "INFO"
DEFAULT_DCC_LOG_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_DCC_LOG_BACKUP_COUNT = 3

# --- Data Classes ---

@dataclass
class ServerConfig:
    """A simple data container for a single server's configuration."""
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
    desired_caps: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Set default values based on other fields after initialization."""
        if self.username is None:
            self.username = self.nick
        if self.realname is None:
            self.realname = self.nick
        if self.sasl_username is None:
            self.sasl_username = self.nick
        if self.sasl_password is None:
            self.sasl_password = self.nickserv_password

# --- Main Configuration Class ---

class AppConfig:
    """
    Centralized class for loading, holding, and managing all application configuration.
    This class is the single source of truth for configuration values.
    """
    def __init__(self, config_file_path: Optional[str] = None):
        self.BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.CONFIG_FILE_NAME = "pyterm_irc_config.ini"
        self.CONFIG_FILE_PATH = config_file_path or os.path.join(self.BASE_DIR, self.CONFIG_FILE_NAME)

        self._config_parser = configparser.ConfigParser()
        self.all_server_configs: Dict[str, ServerConfig] = {}
        self.default_server_config_name: Optional[str] = None
        self.ignored_patterns: Set[str] = set()

        self._load_config_file()
        self._load_all_settings()
        self._load_server_configurations()
        self._load_ignore_list()

    def _load_config_file(self):
        """Reads the INI config file into the internal parser."""
        if os.path.exists(self.CONFIG_FILE_PATH):
            self._config_parser.read(self.CONFIG_FILE_PATH)
            logger.info(f"Configuration file '{self.CONFIG_FILE_PATH}' loaded.")
        else:
            logger.warning(
                f"Configuration file '{self.CONFIG_FILE_PATH}' not found. Using default values."
            )

    def _get_config_value(
        self, section: str, key: str, fallback: Any, value_type: Type = str
    ) -> Any:
        """Helper to get config values with fallbacks from the internal parser."""
        if self._config_parser.has_section(section) and self._config_parser.has_option(section, key):
            try:
                if value_type == bool:
                    return self._config_parser.getboolean(section, key)
                elif value_type == int:
                    return self._config_parser.getint(section, key)
                elif value_type == list:
                    val = self._config_parser.get(section, key)
                    return (
                        [item.strip() for item in val.split(",") if item.strip()]
                        if val and val.strip()
                        else []
                    )
                return self._config_parser.get(section, key)
            except (ValueError, configparser.Error):
                return fallback
        return fallback

    def set_config_value(self, section: str, key: str, value: Any) -> bool:
        """
        Sets a configuration value in the specified section and key,
        then writes the entire configuration back to the INI file.
        """
        try:
            if not self._config_parser.has_section(section):
                self._config_parser.add_section(section)
            self._config_parser.set(section, key, str(value))
            self.save_current_config()
            logger.info(f"Configuration updated: [{section}] {key} = {value}")
            return True
        except Exception as e:
            logger.error(f"Error setting config value for '{section}.{key}': {e}")
            return False

    def get_all_settings(self) -> dict:
        """Retrieves all settings from the configuration for display."""
        all_settings = {}
        for section in self._config_parser.sections():
            all_settings[section] = {}
            for key in self._config_parser.options(section):
                all_settings[section][key] = self._config_parser.get(section, key)
        return all_settings

    def save_current_config(self) -> bool:
        """Saves the current configuration state to the INI file."""
        try:
            with open(self.CONFIG_FILE_PATH, "w") as configfile:
                self._config_parser.write(configfile)
            logger.info(f"Configuration saved to {self.CONFIG_FILE_PATH}")
            return True
        except Exception as e:
            logger.error(f"Error writing to config file '{self.CONFIG_FILE_PATH}': {e}")
            return False

    def _load_all_settings(self):
        """Loads all non-server specific settings into instance attributes."""
        # General Connection Settings
        self.auto_reconnect = self._get_config_value("Connection", "auto_reconnect", DEFAULT_AUTO_RECONNECT, bool)
        self.reconnect_initial_delay = self._get_config_value("Connection", "reconnect_initial_delay", DEFAULT_RECONNECT_INITIAL_DELAY, int)
        self.reconnect_max_delay = self._get_config_value("Connection", "reconnect_max_delay", DEFAULT_RECONNECT_MAX_DELAY, int)
        self.connection_timeout = self._get_config_value("Connection", "connection_timeout", DEFAULT_CONNECTION_TIMEOUT, int)

        # UI Settings
        self.max_history = self._get_config_value("UI", "message_history_lines", DEFAULT_MAX_HISTORY, int)
        self.headless_max_history = self._get_config_value("UI", "headless_message_history_lines", DEFAULT_HEADLESS_MAX_HISTORY, int)

        # Logging Settings
        self.log_enabled = self._get_config_value("Logging", "log_enabled", DEFAULT_LOG_ENABLED, bool)
        self.log_file = self._get_config_value("Logging", "log_file", DEFAULT_LOG_FILE, str)
        self.log_error_file = self._get_config_value("Logging", "log_error_file", DEFAULT_LOG_ERROR_FILE, str)
        self.log_level_str = self._get_config_value("Logging", "log_level", DEFAULT_LOG_LEVEL, str).upper()
        self.log_error_level_str = self._get_config_value("Logging", "log_error_level", DEFAULT_LOG_ERROR_LEVEL, str).upper()
        self.log_max_bytes = self._get_config_value("Logging", "log_max_bytes", DEFAULT_LOG_MAX_BYTES, int)
        self.log_backup_count = self._get_config_value("Logging", "log_backup_count", DEFAULT_LOG_BACKUP_COUNT, int)
        self.channel_log_enabled = self._get_config_value("Logging", "channel_log_enabled", DEFAULT_CHANNEL_LOG_ENABLED, bool)
        self.status_window_log_file = self._get_config_value("Logging", "status_window_log_file", DEFAULT_STATUS_WINDOW_LOG_FILE, str)

        # Feature Settings
        self.enable_trigger_system = self._get_config_value("Features", "enable_trigger_system", DEFAULT_ENABLE_TRIGGER_SYSTEM, bool)
        self.disabled_scripts = set(self._get_config_value("Scripts", "disabled_scripts", list(DEFAULT_DISABLED_SCRIPTS), list))

        # DCC Configuration
        self.dcc_enabled = self._get_config_value("DCC", "enabled", DEFAULT_DCC_ENABLED, bool)
        self.dcc_download_dir = self._get_config_value("DCC", "download_dir", DEFAULT_DCC_DOWNLOAD_DIR, str)
        self.dcc_upload_dir = self._get_config_value("DCC", "upload_dir", DEFAULT_DCC_UPLOAD_DIR, str)
        self.dcc_auto_accept = self._get_config_value("DCC", "auto_accept", DEFAULT_DCC_AUTO_ACCEPT, bool)
        self.dcc_max_file_size = self._get_config_value("DCC", "max_file_size", DEFAULT_DCC_MAX_FILE_SIZE, int)
        self.dcc_port_range_start = self._get_config_value("DCC", "port_range_start", DEFAULT_DCC_PORT_RANGE_START, int)
        self.dcc_port_range_end = self._get_config_value("DCC", "port_range_end", DEFAULT_DCC_PORT_RANGE_END, int)
        self.dcc_timeout = self._get_config_value("DCC", "timeout", DEFAULT_DCC_TIMEOUT, int)
        self.dcc_resume_enabled = self._get_config_value("DCC", "resume_enabled", DEFAULT_DCC_RESUME_ENABLED, bool)
        self.dcc_checksum_verify = self._get_config_value("DCC", "checksum_verify", DEFAULT_DCC_CHECKSUM_VERIFY, bool)
        self.dcc_checksum_algorithm = self._get_config_value("DCC", "checksum_algorithm", DEFAULT_DCC_CHECKSUM_ALGORITHM, str).lower()
        self.dcc_bandwidth_limit_send_kbps = self._get_config_value("DCC", "bandwidth_limit_send_kbps", DEFAULT_DCC_BANDWIDTH_LIMIT_SEND_KBPS, int)
        self.dcc_bandwidth_limit_recv_kbps = self._get_config_value("DCC", "bandwidth_limit_recv_kbps", DEFAULT_DCC_BANDWIDTH_LIMIT_RECV_KBPS, int)
        self.dcc_blocked_extensions = self._get_config_value("DCC", "blocked_extensions", DEFAULT_DCC_BLOCKED_EXTENSIONS, list)
        self.dcc_passive_mode_token_timeout = self._get_config_value("DCC", "passive_token_timeout", DEFAULT_DCC_PASSIVE_MODE_TOKEN_TIMEOUT, int)
        self.dcc_advertised_ip = self._get_config_value("DCC", "dcc_advertised_ip", DEFAULT_DCC_ADVERTISED_IP, str)
        if self.dcc_advertised_ip == "": self.dcc_advertised_ip = None
        self.dcc_cleanup_enabled = self._get_config_value("DCC", "cleanup_enabled", DEFAULT_DCC_CLEANUP_ENABLED, bool)
        self.dcc_cleanup_interval_seconds = self._get_config_value("DCC", "cleanup_interval_seconds", DEFAULT_DCC_CLEANUP_INTERVAL_SECONDS, int)
        self.dcc_transfer_max_age_seconds = self._get_config_value("DCC", "transfer_max_age_seconds", DEFAULT_DCC_TRANSFER_MAX_AGE_SECONDS, int)
        self.dcc_log_enabled = self._get_config_value("DCC", "log_enabled", DEFAULT_DCC_LOG_ENABLED, bool)
        self.dcc_log_file = self._get_config_value("DCC", "log_file", DEFAULT_DCC_LOG_FILE, str)
        self.dcc_log_level_str = self._get_config_value("DCC", "log_level", DEFAULT_DCC_LOG_LEVEL, str).upper()
        self.dcc_log_max_bytes = self._get_config_value("DCC", "log_max_bytes", DEFAULT_DCC_LOG_MAX_BYTES, int)
        self.dcc_log_backup_count = self._get_config_value("DCC", "log_backup_count", DEFAULT_DCC_LOG_BACKUP_COUNT, int)

    def _load_server_configurations(self):
        """Loads all server-specific configurations."""
        self.all_server_configs.clear()
        self.default_server_config_name = None
        found_explicit_auto_connect = False

        for section_name in self._config_parser.sections():
            if section_name.startswith("Server."):
                server_id = section_name[7:]
                if not server_id:
                    logger.warning(f"Skipping server section with empty ID: {section_name}")
                    continue

                try:
                    desired_caps_str = self._get_config_value(section_name, "desired_caps", None, str)
                    desired_caps_list = [cap.strip() for cap in desired_caps_str.split(',')] if desired_caps_str else []

                    s_config = ServerConfig(
                        server_id=server_id,
                        address=self._get_config_value(section_name, "address", "", str),
                        port=self._get_config_value(section_name, "port", 0, int),
                        ssl=self._get_config_value(section_name, "ssl", False, bool),
                        nick=self._get_config_value(section_name, "nick", "", str),
                        channels=self._get_config_value(section_name, "channels", [], list),
                        username=self._get_config_value(section_name, "username", None, str),
                        realname=self._get_config_value(section_name, "realname", None, str),
                        server_password=self._get_config_value(section_name, "server_password", None, str),
                        nickserv_password=self._get_config_value(section_name, "nickserv_password", None, str),
                        sasl_username=self._get_config_value(section_name, "sasl_username", None, str),
                        sasl_password=self._get_config_value(section_name, "sasl_password", None, str),
                        verify_ssl_cert=self._get_config_value(section_name, "verify_ssl_cert", DEFAULT_VERIFY_SSL_CERT, bool),
                        auto_connect=self._get_config_value(section_name, "auto_connect", False, bool),
                        desired_caps=desired_caps_list
                    )
                    self.all_server_configs[server_id] = s_config
                    logger.info(f"Loaded server configuration: [{s_config.server_id}] {s_config.address}")
                    if s_config.auto_connect and not found_explicit_auto_connect:
                        self.default_server_config_name = server_id
                        found_explicit_auto_connect = True
                except (configparser.NoOptionError, ValueError) as e:
                    logger.error(f"Error parsing configuration for server '{server_id}': {e}. Skipping.")

        if not found_explicit_auto_connect and self.all_server_configs:
            self.default_server_config_name = sorted(self.all_server_configs.keys())[0]
            logger.warning(f"No server has auto_connect=true. Defaulting to first server: '{self.default_server_config_name}'.")

    def _load_ignore_list(self):
        """Loads ignore patterns from the config file into the `ignored_patterns` set."""
        self.ignored_patterns.clear()
        if self._config_parser.has_section("IgnoreList"):
            for key, _ in self._config_parser.items("IgnoreList"):
                self.ignored_patterns.add(key.strip().lower())
        logger.info(f"Loaded {len(self.ignored_patterns)} ignore patterns.")

    def add_ignore_pattern(self, pattern: str) -> bool:
        """Adds a pattern to the ignore list and saves it."""
        normalized_pattern = pattern.strip().lower()
        if not normalized_pattern:
            return False
        if normalized_pattern not in self.ignored_patterns:
            self.ignored_patterns.add(normalized_pattern)
            return self._save_ignore_list()
        return False

    def remove_ignore_pattern(self, pattern: str) -> bool:
        """Removes a pattern from the ignore list and saves it."""
        normalized_pattern = pattern.strip().lower()
        if normalized_pattern in self.ignored_patterns:
            self.ignored_patterns.remove(normalized_pattern)
            return self._save_ignore_list()
        return False

    def _save_ignore_list(self) -> bool:
        """Saves the `ignored_patterns` set to the config file."""
        try:
            if self._config_parser.has_section("IgnoreList"):
                self._config_parser.remove_section("IgnoreList")
            if self.ignored_patterns:
                self._config_parser.add_section("IgnoreList")
                for pattern in sorted(list(self.ignored_patterns)):
                    self._config_parser.set("IgnoreList", pattern, "true")
            return self.save_current_config()
        except Exception as e:
            logger.error(f"Error saving ignore list to config file: {e}")
            return False

    def is_source_ignored(self, source_full_ident: str) -> bool:
        """Checks if a source (nick!user@host) matches any of the stored ignore patterns."""
        if not source_full_ident:
            return False
        source_lower = source_full_ident.lower()
        for pattern in self.ignored_patterns:
            if fnmatch.fnmatchcase(source_lower, pattern):
                return True
        return False

    def get_log_level_int_from_str(self, level_str: str, default_level: int) -> int:
        """Converts a log level string to a logging integer constant."""
        level = getattr(logging, level_str.upper(), None)
        return level if isinstance(level, int) else default_level

    @property
    def log_level_int(self) -> int:
        return self.get_log_level_int_from_str(self.log_level_str, logging.INFO)

    @property
    def log_error_level_int(self) -> int:
        return self.get_log_level_int_from_str(self.log_error_level_str, logging.WARNING)

    @property
    def dcc_log_level_int(self) -> int:
        return self.get_log_level_int_from_str(self.dcc_log_level_str, logging.INFO)
