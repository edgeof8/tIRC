import logging
from dataclasses import dataclass, field
from typing import List, Set, Optional

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

# IPC
DEFAULT_IPC_PORT = 61234

# Features
DEFAULT_ENABLE_TRIGGER_SYSTEM = True
DEFAULT_DISABLED_SCRIPTS: Set[str] = {"run_headless_tests", "test_dcc_features"} # Stored without .py
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
DEFAULT_LOG_MAX_BYTES = 1024 * 1024 * 5
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

# --- Color Constants ---
# Using standard curses color numbers (0-7) for visibility on dark backgrounds
# 0: Black, 1: Red, 2: Green, 3: Yellow, 4: Blue, 5: Magenta, 6: Cyan, 7: White

DEFAULT_COLOR_SYSTEM = 7 # White
DEFAULT_COLOR_JOIN_PART = 2 # Green
DEFAULT_COLOR_NICK_CHANGE = 5 # Magenta
DEFAULT_COLOR_MY_MESSAGE = 3 # Yellow
DEFAULT_COLOR_OTHER_MESSAGE = 7 # White
DEFAULT_COLOR_HIGHLIGHT = 6 # Cyan
DEFAULT_COLOR_ERROR = 1 # Red
DEFAULT_COLOR_STATUS_BAR = 7 # White
DEFAULT_COLOR_SIDEBAR_HEADER = 7 # White
DEFAULT_COLOR_SIDEBAR_ITEM = 7 # White
DEFAULT_COLOR_SIDEBAR_USER = 7 # White
DEFAULT_COLOR_INPUT = 7 # White
DEFAULT_COLOR_PM = 7 # White
DEFAULT_COLOR_USER_PREFIX = 7 # White
DEFAULT_COLOR_WARNING = 3 # Yellow
DEFAULT_COLOR_INFO = 6 # Cyan
DEFAULT_COLOR_DEBUG = 5 # Magenta
DEFAULT_COLOR_TIMESTAMP = 7 # White
DEFAULT_COLOR_NICK = 7 # White
DEFAULT_COLOR_CHANNEL = 7 # White
DEFAULT_COLOR_QUERY = 7 # White
DEFAULT_COLOR_STATUS = 7 # White
DEFAULT_COLOR_LIST = 7 # White
DEFAULT_COLOR_LIST_SELECTED = 7 # White
DEFAULT_COLOR_LIST_HEADER = 7 # White
DEFAULT_COLOR_LIST_FOOTER = 7 # White
DEFAULT_COLOR_LIST_HIGHLIGHT = 7 # White
DEFAULT_COLOR_LIST_SELECTED_HIGHLIGHT = 7 # White
DEFAULT_COLOR_LIST_SELECTED_HEADER = 7 # White
DEFAULT_COLOR_LIST_SELECTED_HIGHLIGHT_FOOTER = 7 # White

# --- Data Classes ---

@dataclass
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
    desired_caps: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.username is None:
            self.username = self.nick
        if self.realname is None:
            self.realname = self.nick
        if self.sasl_password is None and self.nickserv_password is not None:
            self.sasl_password = self.nickserv_password
            if self.sasl_username is None:
                self.sasl_username = self.nick
        elif self.sasl_username is None and self.sasl_password is not None:
            self.sasl_username = self.nick

@dataclass
class DccConfig:
    enabled: bool = DEFAULT_DCC_ENABLED
    download_dir: str = DEFAULT_DCC_DOWNLOAD_DIR
    upload_dir: str = DEFAULT_DCC_UPLOAD_DIR
    auto_accept: bool = DEFAULT_DCC_AUTO_ACCEPT
    max_file_size: int = DEFAULT_DCC_MAX_FILE_SIZE
    port_range_start: int = DEFAULT_DCC_PORT_RANGE_START
    port_range_end: int = DEFAULT_DCC_PORT_RANGE_END
    timeout: int = DEFAULT_DCC_TIMEOUT
    resume_enabled: bool = DEFAULT_DCC_RESUME_ENABLED
    checksum_verify: bool = DEFAULT_DCC_CHECKSUM_VERIFY
    checksum_algorithm: str = DEFAULT_DCC_CHECKSUM_ALGORITHM
    bandwidth_limit_send_kbps: int = DEFAULT_DCC_BANDWIDTH_LIMIT_SEND_KBPS
    bandwidth_limit_recv_kbps: int = DEFAULT_DCC_BANDWIDTH_LIMIT_RECV_KBPS
    blocked_extensions: List[str] = field(default_factory=lambda: list(DEFAULT_DCC_BLOCKED_EXTENSIONS))
    passive_mode_token_timeout: int = DEFAULT_DCC_PASSIVE_MODE_TOKEN_TIMEOUT
    advertised_ip: Optional[str] = DEFAULT_DCC_ADVERTISED_IP
    cleanup_enabled: bool = DEFAULT_DCC_CLEANUP_ENABLED
    cleanup_interval_seconds: int = DEFAULT_DCC_CLEANUP_INTERVAL_SECONDS
    transfer_max_age_seconds: int = DEFAULT_DCC_TRANSFER_MAX_AGE_SECONDS
    log_enabled: bool = DEFAULT_DCC_LOG_ENABLED
    log_file: str = DEFAULT_DCC_LOG_FILE
    log_level: str = DEFAULT_DCC_LOG_LEVEL
    log_max_bytes: int = DEFAULT_DCC_LOG_MAX_BYTES
    log_backup_count: int = DEFAULT_DCC_LOG_BACKUP_COUNT

    def get_log_level_int(self) -> int:
        return getattr(logging, self.log_level.upper(), logging.INFO)
