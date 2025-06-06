# pyrc_core/logging/channel_logger.py
import logging
import logging.handlers
import os
from typing import Optional, Dict

import pyrc_core.app_config as app_config

class ChannelLoggerManager:
    """Manages the creation and retrieval of per-channel loggers."""

    def __init__(self):
        self.channel_log_enabled = app_config.CHANNEL_LOG_ENABLED
        self.main_log_dir_path = os.path.join(app_config.BASE_DIR, "logs")
        self.channel_log_level = app_config.LOG_LEVEL
        self.channel_log_max_bytes = app_config.LOG_MAX_BYTES
        self.channel_log_backup_count = app_config.LOG_BACKUP_COUNT
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
            if os.path.normpath(channel_log_file_path) == os.path.normpath(os.path.join(self.main_log_dir_path, app_config.LOG_FILE)) or \
               os.path.normpath(channel_log_file_path) == os.path.normpath(os.path.join(self.main_log_dir_path, app_config.DEFAULT_STATUS_WINDOW_LOG_FILE)):
                log_file_name = f"channel_{safe_filename_part}.log"
                channel_log_file_path = os.path.join(self.main_log_dir_path, log_file_name)

            channel_logger_instance = logging.getLogger(f"pyrc.channel.{safe_filename_part}")
            channel_logger_instance.setLevel(self.channel_log_level)

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
            log_file_name = app_config.DEFAULT_STATUS_WINDOW_LOG_FILE
            status_log_file_path = os.path.join(self.main_log_dir_path, log_file_name)

            status_logger = logging.getLogger("pyrc.client_status")
            status_logger.setLevel(self.channel_log_level)

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
