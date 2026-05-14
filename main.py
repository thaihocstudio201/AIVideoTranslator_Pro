import sys
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from utils.custom_logger import sys_log
from security.hwid_generator import HardwareAuthenticator

def main():
    sys_log.info("=" * 50)
    sys_log.info("HỆ THỐNG AI VIDEO TRANSLATOR PRO 2026 ĐÃ KHỞI ĐỘNG")

    hwid = HardwareAuthenticator.generate_hwid()
    if hwid:
        sys_log.info(f"Đã xác thực mã thiết bị: {hwid}")
    else:
        sys_log.error("Không thể xác minh phần cứng. Vui lòng chạy bằng quyền Admin.")

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    sys_log.info("Cửa sổ chính đã hiển thị thành công.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()