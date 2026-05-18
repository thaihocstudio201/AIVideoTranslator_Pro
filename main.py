import sys
import os
import traceback
from PySide6.QtWidgets import QApplication, QMessageBox

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


def _check_license_startup(app: QApplication) -> bool:
    """
    Kiểm tra license khi khởi động.
    Trả về True nếu được phép chạy.
    Hiển thị cảnh báo nếu sắp hết hạn hoặc grace period.
    """
    try:
        from security.license_client import LicenseClient, STATUS_VALID, STATUS_TRIAL, STATUS_GRACE
        client = LicenseClient.get()
        info   = client.get_status()

        if info.status in (STATUS_VALID, STATUS_TRIAL):
            if info.days_left <= 7:
                sys_log.warning(f"⚠️ License sắp hết hạn: còn {info.days_left} ngày")
                QMessageBox.warning(
                    None, "⚠️ License sắp hết hạn",
                    f"License của bạn còn <b>{info.days_left} ngày</b>.<br>"
                    f"Vui lòng gia hạn trong Tab 4 để tiếp tục sử dụng."
                )
            return True

        if info.status == STATUS_GRACE:
            sys_log.warning(f"⚠️ License ân hạn: {info.message}")
            QMessageBox.warning(
                None, "⚠️ License đã hết hạn (Ân hạn)",
                f"{info.message}<br><br>"
                f"Vui lòng nhập License Key mới trong Tab 4."
            )
            return True  # vẫn cho chạy trong grace period

        # Chưa kích hoạt / hết hạn hoàn toàn → hiển thị thông báo nhưng vẫn cho chạy
        # (để người dùng có thể vào Tab 4 nhập key)
        if info.status == "offline":
            sys_log.info("ℹ️ Chưa kích hoạt — vào Tab 4 để nhập License Key hoặc dùng thử")
        elif info.status == "expired":
            sys_log.warning("❌ License đã hết hạn hoàn toàn")
            QMessageBox.warning(
                None, "❌ License đã hết hạn",
                "License của bạn đã hết hạn.<br>"
                "Vui lòng gia hạn trong Tab 4 để tiếp tục sử dụng đầy đủ tính năng."
            )
        return True  # không chặn app — người dùng vào Tab 4 để activate

    except Exception as e:
        sys_log.warning(f"Không kiểm tra được license: {e}")
        return True  # không chặn app nếu có lỗi kiểm tra


def main():
    sys_log.info("=" * 50)
    sys_log.info("HỆ THỐNG AI VIDEO TRANSLATOR PRO 2026 ĐÃ KHỞI ĐỘNG")

    hwid = HardwareAuthenticator.generate_hwid()
    hwid_fmt = HardwareAuthenticator.get_formatted_hwid()
    if hwid:
        sys_log.info(f"HWID: {hwid_fmt}")
    else:
        sys_log.warning("Không xác định được HWID máy tính")

    app = QApplication(sys.argv)
    app.setApplicationName("AI Video Translator Pro")
    app.setApplicationVersion("2.0.0")

    _check_license_startup(app)

    window = MainWindow()
    window.show()

    # Kiểm tra cập nhật tự động sau 3 giây (không block UI)
    from PySide6.QtCore import QTimer

    def _auto_check_update():
        try:
            from security.updater import AppUpdater
            def _on_update(info):
                if info.has_update:
                    sys_log.info(f"🆕 Có bản cập nhật: v{info.latest_version} — vào Tab 4 để tải")
            AppUpdater.get().check_async(_on_update)
        except Exception:
            pass

    QTimer.singleShot(3000, _auto_check_update)

    sys_log.info("✅ Cửa sổ chính đã hiển thị.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
