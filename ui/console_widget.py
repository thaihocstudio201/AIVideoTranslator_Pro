"""
console_widget.py - SystemConsole Widget
Màn hình đen hiển thị log realtime (INFO=xanh lá, WARNING=vàng, ERROR=đỏ).
Kết nối với custom_logger qua Qt Signal để thread-safe.
"""

from PySide6.QtWidgets import QTextEdit, QWidget, QVBoxLayout
from PySide6.QtCore import Qt, QObject, Signal, Slot
from PySide6.QtGui import QColor, QTextCursor, QFont


class LogSignalBridge(QObject):
    """Bridge thread-safe giữa logger và Qt widget."""
    new_log = Signal(str, str)  # (level, message)


# Singleton bridge - dùng chung toàn app
log_bridge = LogSignalBridge()


class SystemConsole(QWidget):
    """
    Widget console kiểu terminal hacker.
    - Nền đen, chữ màu theo level
    - Thread-safe: nhận log từ bất kỳ thread nào qua Qt signal
    - Tự cuộn xuống cuối
    - Giới hạn 2000 dòng để tránh tràn RAM
    """

    MAX_LINES = 2000

    COLORS = {
        "INFO":     "#00ff88",   # Xanh lá
        "WARNING":  "#ffd700",   # Vàng
        "ERROR":    "#ff4444",   # Đỏ
        "CRITICAL": "#ff0000",   # Đỏ đậm
        "DEBUG":    "#888888",   # Xám
        "SUCCESS":  "#00f2ff",   # Cyan
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_count = 0
        self._init_ui()
        self._connect_bridge()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setStyleSheet("""
            QTextEdit {
                background-color: #0a0a0f;
                border: 1px solid #00f2ff;
                border-radius: 4px;
                padding: 6px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }
        """)
        self.text_area.document().setMaximumBlockCount(self.MAX_LINES)

        layout.addWidget(self.text_area)

    def _connect_bridge(self):
        log_bridge.new_log.connect(self._append_log)

    @Slot(str, str)
    def _append_log(self, level: str, message: str):
        color = self.COLORS.get(level.upper(), "#c9d1d9")
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Format HTML
        html = f'<span style="color:{color};">{message}</span><br>'
        cursor.insertHtml(html)

        # Auto-scroll
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self._line_count += 1

    def append_raw(self, level: str, message: str):
        """Gọi từ bất kỳ thread nào - thread safe qua signal."""
        log_bridge.new_log.emit(level, message)

    def clear_console(self):
        self.text_area.clear()
        self._line_count = 0