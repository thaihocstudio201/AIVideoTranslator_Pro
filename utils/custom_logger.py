import logging
import os
from datetime import datetime

class AppLogger:
    """Quản lý việc ghi Log và xuất Log ra giao diện PyQt6"""
    
    def __init__(self, log_dir="temp"):
        self.log_dir = log_dir
        # Đảm bảo thư mục temp luôn tồn tại
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.logger = logging.getLogger("AITranslatorPro")
        self.logger.setLevel(logging.DEBUG)
        
        # Định dạng dòng log: [14:30:05] [INFO] Nội dung...
        formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
        
        # Xóa các handler cũ nếu có (tránh in log bị trùng lặp)
        if self.logger.hasHandlers():
            self.logger.handlers.clear()
            
        # Cấu hình lưu Log vào file (Để chạy tính năng Resume)
        log_file = os.path.join(self.log_dir, f"session_{datetime.now().strftime('%Y%m%d')}.log")
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def info(self, msg):
        self.logger.info(msg)
        # TODO: Sau này sẽ thêm code bắn tín hiệu (Signal) chữ Xanh Lá ra giao diện tại đây

    def warning(self, msg):
        self.logger.warning(msg)
        # TODO: Bắn tín hiệu chữ Vàng ra giao diện

    def error(self, msg):
        self.logger.error(msg)
        # TODO: Bắn tín hiệu chữ Đỏ ra giao diện

# Khởi tạo sẵn một đối tượng để các module khác import và dùng ngay
sys_log = AppLogger()