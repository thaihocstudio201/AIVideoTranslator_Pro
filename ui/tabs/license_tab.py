"""
ui/tabs/license_tab.py
Tab 4: Quản lý License & Cập nhật từ xa.
"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QProgressBar,
    QTextEdit, QMessageBox, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor

from utils.custom_logger import sys_log


# ── Worker threads ─────────────────────────────────────────────────────────────

class _ActivateThread(QThread):
    done = Signal(bool, str)   # (success, message)

    def __init__(self, key: str, server: str):
        super().__init__()
        self._key    = key
        self._server = server

    def run(self):
        try:
            from security.license_client import LicenseClient
            ok, msg = LicenseClient.get().activate(self._key, self._server)
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


class _CheckUpdateThread(QThread):
    done = Signal(object)   # UpdateInfo

    def run(self):
        try:
            from security.updater import AppUpdater
            info = AppUpdater.get().check_for_updates(force=True)
            self.done.emit(info)
        except Exception as e:
            from security.updater import UpdateInfo
            ui = UpdateInfo()
            ui.release_notes = str(e)
            self.done.emit(ui)


class _DownloadThread(QThread):
    progress = Signal(float)    # 0.0–1.0
    done     = Signal(str)      # file path or ""

    def __init__(self, url: str):
        super().__init__()
        self._url = url

    def run(self):
        try:
            from security.updater import AppUpdater
            path = AppUpdater.get().download_update(
                self._url,
                progress_cb=lambda p: self.progress.emit(p)
            )
            self.done.emit(path or "")
        except Exception as e:
            self.done.emit("")


# ── Main Tab ──────────────────────────────────────────────────────────────────

class LicenseTab(QWidget):
    license_changed = Signal()   # phát khi trạng thái license thay đổi

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._update_info  = None
        self._download_path = ""
        self._act_thread   = None
        self._chk_thread   = None
        self._dl_thread    = None
        self._init_ui()
        QTimer.singleShot(500, self._refresh_license_display)

    # ── UI Builder ─────────────────────────────────────────────────

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(14)

        outer.addWidget(self._build_license_group())
        outer.addWidget(self._build_update_group())
        outer.addStretch()

    def _build_license_group(self) -> QGroupBox:
        g = QGroupBox("🔐 BẢN QUYỀN & KÍCH HOẠT")
        g.setStyleSheet("QGroupBox{font-weight:bold;font-size:14px;color:#00f2ff;"
                        "border:1px solid #00f2ff;border-radius:6px;margin-top:8px;}"
                        "QGroupBox::title{subcontrol-origin:margin;left:12px;}")
        lo = QVBoxLayout(g)
        lo.setSpacing(8)

        # HWID display
        hwid_row = QHBoxLayout()
        hwid_row.addWidget(QLabel("Mã máy (HWID):"))
        self.lbl_hwid = QLabel("...")
        self.lbl_hwid.setStyleSheet("font-family:monospace;font-size:12px;color:#ffa500;"
                                    "background:#1a1a1a;padding:4px 8px;border-radius:4px;")
        self.lbl_hwid.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        hwid_row.addWidget(self.lbl_hwid, 1)
        btn_copy = QPushButton("📋 Copy")
        btn_copy.setFixedWidth(72)
        btn_copy.clicked.connect(self._copy_hwid)
        hwid_row.addWidget(btn_copy)
        lo.addLayout(hwid_row)

        # Status
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Trạng thái:"))
        self.lbl_status = QLabel("Đang kiểm tra...")
        self.lbl_status.setStyleSheet("font-weight:bold;font-size:13px;")
        status_row.addWidget(self.lbl_status, 1)
        lo.addLayout(status_row)

        # Expiry
        exp_row = QHBoxLayout()
        exp_row.addWidget(QLabel("Hết hạn:"))
        self.lbl_expiry = QLabel("—")
        exp_row.addWidget(self.lbl_expiry, 1)
        lo.addLayout(exp_row)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setStyleSheet("color:#333;")
        lo.addWidget(sep)

        # Key input
        lo.addWidget(QLabel("Nhập License Key:"))
        key_row = QHBoxLayout()
        self.txt_key = QLineEdit()
        self.txt_key.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self.txt_key.setStyleSheet("font-family:monospace;font-size:13px;letter-spacing:2px;")
        self.txt_key.setMaxLength(20)
        key_row.addWidget(self.txt_key, 1)
        lo.addLayout(key_row)

        # Server URL (optional)
        lo.addWidget(QLabel("URL Server kích hoạt (tùy chọn):"))
        self.txt_server = QLineEdit()
        self.txt_server.setPlaceholderText("https://your-server.com  (để trống = dùng offline)")
        lo.addWidget(self.txt_server)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_activate = QPushButton("🔑 KÍCH HOẠT")
        self.btn_activate.setMinimumHeight(44)
        self.btn_activate.setStyleSheet(
            "background:#1a73e8;color:white;font-size:14px;font-weight:bold;border-radius:5px;")
        self.btn_activate.clicked.connect(self._on_activate)
        btn_row.addWidget(self.btn_activate, 2)

        self.btn_trial = QPushButton("🎁 Dùng Thử 7 Ngày")
        self.btn_trial.setMinimumHeight(44)
        self.btn_trial.setStyleSheet(
            "background:#2d7a2d;color:white;font-size:13px;font-weight:bold;border-radius:5px;")
        self.btn_trial.clicked.connect(self._on_trial)
        btn_row.addWidget(self.btn_trial, 1)

        btn_deact = QPushButton("🗑️ Hủy Kích Hoạt")
        btn_deact.setMinimumHeight(44)
        btn_deact.setStyleSheet(
            "background:#7a2d2d;color:white;font-size:13px;font-weight:bold;border-radius:5px;")
        btn_deact.clicked.connect(self._on_deactivate)
        btn_row.addWidget(btn_deact, 1)
        lo.addLayout(btn_row)

        return g

    def _build_update_group(self) -> QGroupBox:
        g = QGroupBox("🔄 CẬP NHẬT TỪ XA")
        g.setStyleSheet("QGroupBox{font-weight:bold;font-size:14px;color:#00f2ff;"
                        "border:1px solid #00f2ff;border-radius:6px;margin-top:8px;}"
                        "QGroupBox::title{subcontrol-origin:margin;left:12px;}")
        lo = QVBoxLayout(g)
        lo.setSpacing(8)

        # Version info
        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("Phiên bản hiện tại:"))
        from security.updater import CURRENT_VERSION
        self.lbl_cur_ver = QLabel(f"<b>v{CURRENT_VERSION}</b>")
        ver_row.addWidget(self.lbl_cur_ver)
        ver_row.addStretch()
        ver_row.addWidget(QLabel("Phiên bản mới nhất:"))
        self.lbl_new_ver = QLabel("—")
        self.lbl_new_ver.setStyleSheet("font-weight:bold;color:#00f2ff;")
        ver_row.addWidget(self.lbl_new_ver)
        lo.addLayout(ver_row)

        # Update URL
        lo.addWidget(QLabel("URL kiểm tra cập nhật (GitHub releases API hoặc server):"))
        url_row = QHBoxLayout()
        self.txt_update_url = QLineEdit()
        self.txt_update_url.setPlaceholderText(
            "https://api.github.com/repos/OWNER/REPO/releases/latest")
        url_row.addWidget(self.txt_update_url, 1)
        btn_save_url = QPushButton("💾 Lưu")
        btn_save_url.setFixedWidth(64)
        btn_save_url.clicked.connect(self._save_update_url)
        url_row.addWidget(btn_save_url)
        lo.addLayout(url_row)
        self._load_update_url()

        # Release notes
        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        self.txt_notes.setMaximumHeight(100)
        self.txt_notes.setPlaceholderText("Nhấn 'Kiểm tra' để xem thông tin phiên bản mới...")
        self.txt_notes.setStyleSheet("background:#0d1117;color:#ccc;font-size:12px;")
        lo.addWidget(self.txt_notes)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(
            "QProgressBar{border:1px solid #444;border-radius:4px;text-align:center;}"
            "QProgressBar::chunk{background:#1a73e8;border-radius:3px;}")
        lo.addWidget(self.progress_bar)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_check = QPushButton("🔍 Kiểm Tra Cập Nhật")
        self.btn_check.setMinimumHeight(40)
        self.btn_check.setStyleSheet(
            "background:#333;color:white;font-size:13px;font-weight:bold;border-radius:5px;")
        self.btn_check.clicked.connect(self._on_check_update)
        btn_row.addWidget(self.btn_check)

        self.btn_download = QPushButton("⬇️ Tải & Cài Đặt")
        self.btn_download.setMinimumHeight(40)
        self.btn_download.setStyleSheet(
            "background:#2d7a2d;color:white;font-size:13px;font-weight:bold;border-radius:5px;")
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._on_download_update)
        btn_row.addWidget(self.btn_download)
        lo.addLayout(btn_row)

        return g

    # ── License Actions ────────────────────────────────────────────

    def _refresh_license_display(self):
        try:
            from security.license_client import LicenseClient
            from security.hwid_generator import HardwareAuthenticator
            client = LicenseClient.get()
            info   = client.get_status()

            hwid_fmt = HardwareAuthenticator.get_formatted_hwid()
            self.lbl_hwid.setText(hwid_fmt)

            status_styles = {
                "valid":   "color:#00ff88;",
                "trial":   "color:#ffa500;",
                "grace":   "color:#ff8c00;",
                "expired": "color:#ff4444;",
                "invalid": "color:#ff4444;",
                "offline": "color:#aaaaaa;",
            }
            status_labels = {
                "valid":   "✅ ĐÃ KÍCH HOẠT",
                "trial":   "🎁 DÙNG THỬ",
                "grace":   "⚠️ ÂN HẠN",
                "expired": "❌ HẾT HẠN",
                "invalid": "❌ KHÔNG HỢP LỆ",
                "offline": "🔒 CHƯA KÍCH HOẠT",
            }
            self.lbl_status.setStyleSheet(status_styles.get(info.status, ""))
            self.lbl_status.setText(
                f"{status_labels.get(info.status, info.status)} — {info.message}"
            )

            import time
            if info.expiry_ts > 0:
                from datetime import datetime
                exp_str = datetime.fromtimestamp(info.expiry_ts).strftime("%d/%m/%Y")
                self.lbl_expiry.setText(f"{exp_str}  ({info.days_left} ngày nữa)")
            else:
                self.lbl_expiry.setText("—")

            # Hide trial button if already used or already valid
            trial_used = client.check_trial_used()
            self.btn_trial.setVisible(not trial_used and info.status == "offline")

        except Exception as e:
            self.lbl_status.setText(f"Lỗi: {e}")

    def _copy_hwid(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.lbl_hwid.text().replace("-", ""))
        QMessageBox.information(self, "Đã copy", "Mã máy đã được copy vào clipboard!")

    def _on_activate(self):
        key = self.txt_key.text().strip()
        if not key:
            QMessageBox.warning(self, "Thiếu key", "Vui lòng nhập License Key!")
            return
        server = self.txt_server.text().strip()
        self.btn_activate.setEnabled(False)
        self.btn_activate.setText("⏳ Đang kích hoạt...")
        self._act_thread = _ActivateThread(key, server)
        self._act_thread.done.connect(self._on_activate_done)
        self._act_thread.start()

    def _on_activate_done(self, ok: bool, msg: str):
        self.btn_activate.setEnabled(True)
        self.btn_activate.setText("🔑 KÍCH HOẠT")
        if ok:
            QMessageBox.information(self, "✅ Kích hoạt thành công", msg)
            sys_log.info(f"✅ License kích hoạt: {msg}")
        else:
            QMessageBox.warning(self, "❌ Kích hoạt thất bại", msg)
            sys_log.warning(f"❌ License lỗi: {msg}")
        self._refresh_license_display()
        self.license_changed.emit()

    def _on_trial(self):
        reply = QMessageBox.question(
            self, "Dùng thử",
            f"Bắt đầu 7 ngày dùng thử? Sau khi hết thời gian cần nhập License Key.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from security.license_client import LicenseClient
            ok = LicenseClient.get().start_trial()
            if ok:
                QMessageBox.information(self, "✅ Bắt đầu dùng thử",
                                        "Bạn có 7 ngày dùng thử toàn bộ tính năng!")
            else:
                QMessageBox.warning(self, "Không thể dùng thử",
                                    "Bạn đã sử dụng dùng thử trước đó.")
            self._refresh_license_display()
            self.license_changed.emit()

    def _on_deactivate(self):
        reply = QMessageBox.question(
            self, "Xác nhận",
            "Hủy kích hoạt sẽ xóa license khỏi máy này. Tiếp tục?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from security.license_client import LicenseClient
            LicenseClient.get().deactivate()
            QMessageBox.information(self, "OK", "Đã hủy kích hoạt.")
            self._refresh_license_display()
            self.license_changed.emit()

    # ── Update Actions ─────────────────────────────────────────────

    def _load_update_url(self):
        try:
            from security.updater import AppUpdater
            self.txt_update_url.setText(AppUpdater.get().update_url)
        except Exception:
            pass

    def _save_update_url(self):
        try:
            from security.updater import AppUpdater
            AppUpdater.get().set_update_url(self.txt_update_url.text().strip())
            QMessageBox.information(self, "OK", "Đã lưu URL cập nhật!")
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", str(e))

    def _on_check_update(self):
        self.btn_check.setEnabled(False)
        self.btn_check.setText("⏳ Đang kiểm tra...")
        self.txt_notes.setPlaceholderText("Đang kiểm tra...")
        self._chk_thread = _CheckUpdateThread()
        self._chk_thread.done.connect(self._on_check_done)
        self._chk_thread.start()

    def _on_check_done(self, info):
        self._update_info = info
        self.btn_check.setEnabled(True)
        self.btn_check.setText("🔍 Kiểm Tra Cập Nhật")
        self.lbl_new_ver.setText(f"<b>v{info.latest_version}</b>")

        if info.has_update:
            self.lbl_new_ver.setStyleSheet("font-weight:bold;color:#00ff88;")
            self.btn_download.setEnabled(bool(info.download_url))
            notes = f"🆕 Phiên bản mới: v{info.latest_version}"
            if info.release_date:
                notes += f"  ({info.release_date})"
            if info.file_size_mb > 0:
                notes += f"  [{info.file_size_mb:.1f} MB]"
            if info.release_notes:
                notes += f"\n\n{info.release_notes}"
            self.txt_notes.setPlainText(notes)
            sys_log.info(f"🆕 Có bản cập nhật: v{info.latest_version}")
        else:
            self.lbl_new_ver.setStyleSheet("font-weight:bold;color:#aaa;")
            self.btn_download.setEnabled(False)
            msg = f"✅ Bạn đang dùng phiên bản mới nhất (v{info.latest_version})"
            if info.release_notes and "Lỗi" in info.release_notes:
                msg = info.release_notes
            self.txt_notes.setPlainText(msg)

    def _on_download_update(self):
        if not self._update_info or not self._update_info.download_url:
            return
        self.btn_download.setEnabled(False)
        self.btn_download.setText("⏳ Đang tải...")
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self._dl_thread = _DownloadThread(self._update_info.download_url)
        self._dl_thread.progress.connect(
            lambda p: self.progress_bar.setValue(int(p * 100))
        )
        self._dl_thread.done.connect(self._on_download_done)
        self._dl_thread.start()

    def _on_download_done(self, path: str):
        self.progress_bar.setVisible(False)
        self.btn_download.setText("⬇️ Tải & Cài Đặt")
        if not path:
            QMessageBox.warning(self, "Lỗi", "Tải cập nhật thất bại!")
            self.btn_download.setEnabled(True)
            return

        self._download_path = path
        ext = os.path.splitext(path)[1].lower()
        if ext == ".zip":
            reply = QMessageBox.question(
                self, "Áp dụng cập nhật",
                f"Đã tải xong. Áp dụng cập nhật ngay?\n"
                f"(Ứng dụng cần khởi động lại sau khi cập nhật)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                from security.updater import AppUpdater
                ok, msg = AppUpdater.get().apply_update_zip(path)
                if ok:
                    QMessageBox.information(self, "✅ Cập nhật thành công",
                                            "Vui lòng khởi động lại ứng dụng để áp dụng!")
                    sys_log.info(f"✅ Cập nhật áp dụng thành công từ: {path}")
                else:
                    QMessageBox.warning(self, "❌ Lỗi", msg)
        elif ext in (".exe", ".sh", ".run"):
            reply = QMessageBox.question(
                self, "Chạy installer",
                "Chạy installer và thoát ứng dụng hiện tại?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                from security.updater import AppUpdater
                if AppUpdater.get().launch_installer(path):
                    import sys
                    sys.exit(0)
        else:
            QMessageBox.information(self, "Tải xong",
                                    f"File đã tải về: {path}\nVui lòng cài đặt thủ công.")
