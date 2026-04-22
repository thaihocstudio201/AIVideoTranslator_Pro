import sys
# Đổi PyQt6 thành PySide6
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

from utils.custom_logger import sys_log
from security.hwid_generator import HardwareAuthenticator

def main():
    # 1. Khởi tạo UI
    app = QApplication(sys.argv)
    
    # 2. Ghi Log hệ thống khởi động
    sys_log.info("="*50)
    sys_log.info("HỆ THỐNG AI VIDEO TRANSLATOR PRO 2026 KHỞI ĐỘNG")
    
    # 3. Kiểm tra License/HWID ngầm
    hwid = HardwareAuthenticator.generate_hwid()
    if hwid:
        sys_log.info(f"Đã xác thực mã thiết bị: {hwid}")
    else:
        sys_log.error("Không thể xác minh phần cứng. Vui lòng chạy bằng quyền Admin.")

    # 4. Hiển thị cửa sổ
    window = MainWindow()
    window.show()

    # 5. Vòng lặp sự kiện chính của App
    sys.exit(app.exec())

if __name__ == "__main__":
    main()