import logging
# Đổi PyQt6 thành PySide6
from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget
from PySide6.QtCore import Signal, QObject
from PySide6.QtGui import QFont

# 1. Tạo một Signal Emitter để chuyển Log từ Thread của Python sang Thread của UI (PyQt6)
class LogEmitter(QObject):
    # PySide6 dùng Signal thay vì pyqtSignal
    log_signal = Signal(str, str)

# 2. Tạo một Handler tùy chỉnh cho thư viện logging
class UIConsoleHandler(logging.Handler):
    def __init__(self, emitter):
        super().__init__()
        self.emitter = emitter

    def emit(self, record):
        msg = self.format(record)
        self.emitter.log_signal.emit(record.levelname, msg)

# 3. Widget Console Chính
class SystemConsole(QWidget):
    def __init__(self):
        super().__init__()
        
        # SỬA Ở ĐÂY: Đổi tên biến thành self.main_layout để không trùng với hàm hệ thống
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Tạo màn hình hiển thị text
        self.text_browser = QTextBrowser()
        self.text_browser.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; padding: 10px;")
        
        # Cài đặt font chữ giống Hacker (Consolas hoặc Courier)
        font = QFont("Consolas", 10)
        self.text_browser.setFont(font)
        
        # SỬA Ở ĐÂY: Gọi addWidget từ self.main_layout
        self.main_layout.addWidget(self.text_browser)

        # Khởi tạo bộ lắng nghe Log
        self.emitter = LogEmitter()
        self.emitter.log_signal.connect(self.append_log)
        
        # Kết nối với custom_logger đã tạo trước đó
        self.attach_to_system_logger()

    def attach_to_system_logger(self):
        logger = logging.getLogger("AITranslatorPro")
        console_handler = UIConsoleHandler(self.emitter)
        formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    def append_log(self, level, message):
        """Định dạng màu sắc dựa trên cấp độ Log"""
        if level == "INFO":
            color = "#4AF626"  # Xanh lá Hacker
        elif level == "WARNING":
            color = "#F39C12"  # Vàng cảnh báo
        elif level in ["ERROR", "CRITICAL"]:
            color = "#E74C3C"  # Đỏ lỗi
        else:
            color = "#FFFFFF"  # Trắng mặc định

        html_msg = f'<span style="color: {color};">{message}</span>'
        self.text_browser.append(html_msg)