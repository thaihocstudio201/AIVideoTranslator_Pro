"""
custom_logger.py - Logger tích hợp với SystemConsole.
Mọi log đều: (1) in ra terminal, (2) gửi tới Console widget qua Qt signal.
"""

import logging
import sys
from datetime import datetime


class QtConsoleHandler(logging.Handler):
    """Handler gửi log tới SystemConsole widget qua Qt signal (thread-safe)."""

    def emit(self, record: logging.LogRecord):
        try:
            # Import lazy để tránh circular import
            from ui.console_widget import log_bridge
            level = record.levelname
            msg = self.format(record)
            log_bridge.new_log.emit(level, msg)
        except Exception:
            pass  # Không làm crash app nếu UI chưa init


class SysLogger:
    """Logger singleton cho toàn bộ ứng dụng."""

    def __init__(self, name: str = "AIVideoTranslator"):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG)

        if not self._logger.handlers:
            # Handler 1: Terminal — open fd directly as UTF-8 so Vietnamese/emoji
            # don't crash on Windows cp125x consoles
            import io
            try:
                safe_out = io.open(sys.stdout.fileno(), mode='w',
                                   encoding='utf-8', errors='replace',
                                   closefd=False)
            except Exception:
                safe_out = sys.stdout  # type: ignore[assignment]
            stream_handler = logging.StreamHandler(safe_out)
            stream_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(message)s",
                datefmt="%H:%M:%S"
            )
            stream_handler.setFormatter(formatter)
            self._logger.addHandler(stream_handler)

            # Handler 2: Qt Console widget
            qt_handler = QtConsoleHandler()
            qt_handler.setLevel(logging.DEBUG)
            qt_handler.setFormatter(formatter)
            self._logger.addHandler(qt_handler)

    def info(self, msg: str):
        self._logger.info(msg)

    def warning(self, msg: str):
        self._logger.warning(msg)

    def error(self, msg: str):
        self._logger.error(msg)

    def critical(self, msg: str):
        self._logger.critical(msg)

    def debug(self, msg: str):
        self._logger.debug(msg)

    def success(self, msg: str):
        """Alias cho info với prefix ✅ để hiển thị màu cyan trong console."""
        self._logger.info(f"✅ {msg}")


# Singleton instance dùng toàn app
sys_log = SysLogger()