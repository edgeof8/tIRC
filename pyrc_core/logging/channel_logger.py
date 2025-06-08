# pyrc_core/logging/channel_logger.py
import logging
import logging.handlers
import os
from typing import Optional, Dict

from pyrc_core.app_config import AppConfig

class ChannelLoggerManager:
    """Manages the creation and retrieval of per-channel loggers."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.channel_log_enabled = config.channel_log_enabled
        self.main_log_dir_path = os.path.join(config.BASE_DIR, "logs")
        self.channel_log_level = config.log_level_str
        self.channel_log_max_bytes = config.log_max_bytes
        self.channel_log_backup_count = config.log_backup_count
        self.log_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self.channel_loggers: Dict[str, logging.Logger] = {}
        self.status_logger_instance: Optional[logging.Logger] = None

        if self.channel_log_enabled:
            self._ensure_log_dir_exists()

    def _ensure_log_dir_exists(self):
        if not os.path.exists(self.main_log_dir_path):
            try:
                os.makedirs(self.main_log_dir_path, exist_ok=True)
                logging.info(f"Created main log directory: {self.main_log_dir_path}")
            except OSError as e:
                logging.error(f"Error creating main log directory {self.main_log_dir_path}: {e}")
                self.channel_log_enabled = False

    def get_channel_logger(self, channel_name: str) -> Optional[logging.Logger]:
        if not self.channel_log_enabled:
            return None

        sanitized_name_part = channel_name.lstrip("#&+!").lower()
        safe_filename_part = "".join(c if c.isalnum() else "_" for c in sanitized_name_part)
        logger_key = safe_filename_part

        if logger_key in self.channel_loggers:
            return self.channel_loggers[logger_key]

        try:
            log_file_name = f"{safe_filename_part}.log"
            channel_log_file_path = os.path.join(self.main_log_dir_path, log_file_name)

            # Avoid collision with main/status log files
            if os.path.normpath(channel_log_file_path) == os.path.normpath(os.path.join(self.main_log_dir_path, self.config.log_file)) or \
               os.path.normpath(channel_log_file_path) == os.path.normpath(os.path.join(self.main_log_dir_path, self.config.status_window_log_file)):
                log_file_name = f"channel_{safe_filename_part}.log"
                channel_log_file_path = os.path.join(self.main_log_dir_path, log_file_name)

            channel_logger_instance = logging.getLogger(f"pyrc.channel.{safe_filename_part}")
            channel_logger_instance.setLevel(self.config.get_log_level_int_from_str(self.channel_log_level, logging.INFO))

            file_handler = logging.handlers.RotatingFileHandler(
                channel_log_file_path,
                maxBytes=self.channel_log_max_bytes,
                backupCount=self.channel_log_backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(self.log_formatter)
            channel_logger_instance.addHandler(file_handler)
            channel_logger_instance.propagate = False
            self.channel_loggers[logger_key] = channel_logger_instance
            logging.info(f"Initialized logger for channel {channel_name} at {channel_log_file_path}")
            return channel_logger_instance
        except Exception as e:
            logging.error(f"Failed to create logger for channel {channel_name}: {e}", exc_info=True)
            return None

    def get_status_logger(self) -> Optional[logging.Logger]:
        if not self.channel_log_enabled:
            return None
        if self.status_logger_instance:
            return self.status_logger_instance
        try:
            log_file_name = self.config.status_window_log_file
            status_log_file_path = os.path.join(self.main_log_dir_path, log_file_name)

            status_logger = logging.getLogger("pyrc.client_status")
            status_logger.setLevel(self.config.get_log_level_int_from_str(self.channel_log_level, logging.INFO))

            file_handler = logging.handlers.RotatingFileHandler(
                status_log_file_path,
                maxBytes=self.channel_log_max_bytes,
                backupCount=self.channel_log_backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(self.log_formatter)
            status_logger.addHandler(file_handler)
            status_logger.propagate = False
            self.status_logger_instance = status_logger
            logging.info(f"Initialized logger for Status messages at {status_log_file_path}")
            return status_logger
        except Exception as e:
            logging.error(f"Failed to create logger for Status messages: {e}", exc_info=True)
            return None

    def log_message(self, context_name: str, message: str, level: int = logging.INFO):
        """Logs a message to the appropriate channel or status logger."""
        logger_to_use: Optional[logging.Logger] = None

        if context_name == "Status":
            logger_to_use = self.get_status_logger()
        elif context_name in self.channel_loggers:
            logger_to_use = self.channel_loggers[context_name]
        else:
            # Try to get or create a channel logger if it's a channel context
            logger_to_use = self.get_channel_logger(context_name)

        if logger_to_use:
            if level == logging.DEBUG:
                logger_to_use.debug(message)
            elif level == logging.INFO:
                logger_to_use.info(message)
            elif level == logging.WARNING:
                logger_to_use.warning(message)
            elif level == logging.ERROR:
                logger_to_use.error(message)
            elif level == logging.CRITICAL:
                logger_to_use.critical(message)
            else:
                logger_to_use.info(message) # Default to info
        else:
            # Fallback to main logger if no specific logger could be found/created
            logging.getLogger("pyrc.fallback_logger").log(level, f"[Fallback Log - {context_name}] {message}")
