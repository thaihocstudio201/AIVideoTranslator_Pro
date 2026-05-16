import sys
import traceback
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from utils.custom_logger import sys_log
from security.hwid_generator import HardwareAuthenticator


def _handle_uncaught_exception(exc_type, exc_value, exc_tb):
    """Bắt mọi exception chưa xử lý trên main thread — log trước khi app thoát."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    sys_log.error(f"UNHANDLED EXCEPTION — ứng dụng sắp tắt:\n{msg}")


sys.excepthook = _handle_uncaught_exception


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