"""
ui/license_dialog.py
Startup license dialog — shown BEFORE main window when no valid license detected.
"""

import sys
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

LICENSE_CONFIG_PATH = Path("config/license.json")


# ── Worker thread ──────────────────────────────────────────────────────────────

class _ActivateThread(QThread):
    done = Signal(bool, str)  # (success, message)

    def __init__(self, key: str, server: str):
        super().__init__()
        self._key = key
        self._server = server

    def run(self):
        try:
            from security.license_client import LicenseClient
            ok, msg = LicenseClient.get().activate(self._key, self._server)
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


# ── Main Dialog ────────────────────────────────────────────────────────────────

class LicenseDialog(QDialog):
    """Modal dialog for license activation — shown at app startup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._licensed = False
        self._act_thread = None

        self.setWindowTitle("AI Video Translator Pro — Kích hoạt bản quyền")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedSize(520, 420)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.CustomizeWindowHint
        )
        self.setStyleSheet("""
            QDialog {
                background: #0d1117;
                color: #c9d1d9;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLabel {
                color: #c9d1d9;
                font-size: 13px;
            }
            QLineEdit {
                background: #161b22;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 5px;
                padding: 7px 10px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #00f2ff;
            }
            QPushButton {
                border-radius: 5px;
                padding: 8px 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                opacity: 0.85;
            }
            QPushButton:disabled {
                background: #333;
                color: #666;
            }
        """)

        self._init_ui()
        self._load_saved_server()
        self._load_hwid()

        # If already licensed, accept immediately
        try:
            from security.license_client import LicenseClient
            if LicenseClient.get().is_valid():
                self._licensed = True
                # Use a short delay to let the dialog fully construct before accepting
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self.accept)
        except Exception:
            pass

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)

        # 1. Header
        header = QLabel("🔒 AI Video Translator Pro — Kích hoạt bản quyền")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #00f2ff;"
            "background: #161b22; border-radius: 6px; padding: 10px;"
        )
        layout.addWidget(header)

        # 2. HWID row
        hwid_row = QHBoxLayout()
        hwid_lbl = QLabel("Mã máy:")
        hwid_lbl.setFixedWidth(80)
        hwid_row.addWidget(hwid_lbl)

        self.lbl_hwid = QLabel("Đang tải...")
        self.lbl_hwid.setStyleSheet(
            "font-family: monospace; font-size: 12px; color: #ffa500;"
            "background: #161b22; padding: 5px 10px; border-radius: 4px;"
            "border: 1px solid #30363d;"
        )
        self.lbl_hwid.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        hwid_row.addWidget(self.lbl_hwid, 1)

        btn_copy_hwid = QPushButton("📋 Copy")
        btn_copy_hwid.setFixedWidth(72)
        btn_copy_hwid.setStyleSheet(
            "background: #333; color: #ccc; font-size: 12px; padding: 5px 8px;"
        )
        btn_copy_hwid.clicked.connect(self._copy_hwid)
        hwid_row.addWidget(btn_copy_hwid)
        layout.addLayout(hwid_row)

        # 3. Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #30363d;")
        layout.addWidget(sep)

        # 4. License Key input
        lbl_key = QLabel("License Key:")
        lbl_key.setStyleSheet("font-weight: bold; color: #c9d1d9;")
        layout.addWidget(lbl_key)

        self.txt_key = QLineEdit()
        self.txt_key.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self.txt_key.setStyleSheet(
            "font-family: monospace; font-size: 14px; letter-spacing: 2px;"
            "background: #161b22; color: #00f2ff; border: 1px solid #30363d;"
            "border-radius: 5px; padding: 8px 12px;"
        )
        self.txt_key.setMaxLength(20)
        layout.addWidget(self.txt_key)

        # 5. Server URL (optional)
        lbl_server = QLabel("Server URL (tùy chọn):")
        lbl_server.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(lbl_server)

        self.txt_server = QLineEdit()
        self.txt_server.setPlaceholderText("http://your-server:5000")
        self.txt_server.setStyleSheet(
            "font-size: 12px; background: #0d1117; color: #8b949e;"
            "border: 1px solid #21262d; border-radius: 4px; padding: 5px 10px;"
        )
        layout.addWidget(self.txt_server)

        # 6. Status label
        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("font-size: 12px; color: #8b949e; min-height: 18px;")
        layout.addWidget(self.lbl_status)

        # 7. Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_activate = QPushButton("🔑 KÍCH HOẠT")
        self.btn_activate.setMinimumHeight(44)
        self.btn_activate.setStyleSheet(
            "background: #1a73e8; color: white; font-size: 14px;"
            "font-weight: bold; border-radius: 6px;"
        )
        self.btn_activate.clicked.connect(self._on_activate)
        btn_row.addWidget(self.btn_activate, 3)

        self.btn_trial = QPushButton("🎁 Dùng Thử 7 Ngày")
        self.btn_trial.setMinimumHeight(44)
        self.btn_trial.setStyleSheet(
            "background: #2d7a2d; color: white; font-size: 13px;"
            "font-weight: bold; border-radius: 6px;"
        )
        self.btn_trial.clicked.connect(self._on_trial)
        btn_row.addWidget(self.btn_trial, 2)

        btn_exit = QPushButton("❌ Thoát")
        btn_exit.setMinimumHeight(44)
        btn_exit.setStyleSheet(
            "background: #7a1a1a; color: #ffaaaa; font-size: 13px;"
            "font-weight: bold; border-radius: 6px;"
        )
        btn_exit.clicked.connect(self._on_exit)
        btn_row.addWidget(btn_exit, 1)

        layout.addLayout(btn_row)

        # 8. Bottom note
        note = QLabel("Liên hệ admin để nhận License Key")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet("color: #484f58; font-size: 11px;")
        layout.addWidget(note)

        # Hide trial button if trial already used
        try:
            from security.license_client import LicenseClient
            if LicenseClient.get().check_trial_used():
                self.btn_trial.setVisible(False)
        except Exception:
            pass

    def _load_hwid(self):
        try:
            from security.hwid_generator import HardwareAuthenticator
            hwid = HardwareAuthenticator.get_formatted_hwid()
            self.lbl_hwid.setText(hwid or "Không xác định")
        except Exception as e:
            self.lbl_hwid.setText("Không xác định")

    def _load_saved_server(self):
        """Load previously saved server URL from license.json."""
        try:
            if LICENSE_CONFIG_PATH.exists():
                with open(LICENSE_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                server = data.get("server_url", "")
                if server:
                    self.txt_server.setText(server)
        except Exception:
            pass

    def _save_server_url(self, url: str):
        """Persist server URL to config."""
        try:
            LICENSE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if LICENSE_CONFIG_PATH.exists():
                with open(LICENSE_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["server_url"] = url
            with open(LICENSE_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _copy_hwid(self):
        hwid = self.lbl_hwid.text().replace("-", "").replace(" ", "")
        QApplication.clipboard().setText(hwid)
        self._set_status("Đã copy HWID vào clipboard!", "#00f2ff")

    def _set_status(self, msg: str, color: str = "#8b949e"):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet(f"font-size: 12px; color: {color}; min-height: 18px;")

    # ── Activate ───────────────────────────────────────────────────────────────

    def _on_activate(self):
        key = self.txt_key.text().strip()
        if not key:
            self._set_status("Vui lòng nhập License Key!", "#ff4444")
            return

        server = self.txt_server.text().strip()
        if server:
            self._save_server_url(server)
            try:
                from security.license_client import LicenseClient
                LicenseClient.get().set_server(server)
            except Exception:
                pass

        self.btn_activate.setEnabled(False)
        self.btn_activate.setText("⏳ Đang kích hoạt...")
        self._set_status("Đang xác minh license...", "#8b949e")

        self._act_thread = _ActivateThread(key, server)
        self._act_thread.done.connect(self._on_activate_done)
        self._act_thread.start()

    def _on_activate_done(self, ok: bool, msg: str):
        self.btn_activate.setEnabled(True)
        self.btn_activate.setText("🔑 KÍCH HOẠT")
        if ok:
            self._set_status(f"✅ {msg}", "#00ff88")
            self._licensed = True
            from PySide6.QtCore import QTimer
            QTimer.singleShot(800, self.accept)
        else:
            self._set_status(f"❌ {msg}", "#ff4444")

    # ── Trial ──────────────────────────────────────────────────────────────────

    def _on_trial(self):
        try:
            from security.license_client import LicenseClient
            client = LicenseClient.get()
            if client.check_trial_used():
                self._set_status("Bạn đã sử dụng dùng thử trước đó.", "#ff4444")
                self.btn_trial.setVisible(False)
                return
            ok = client.start_trial()
            if ok:
                self._set_status("✅ Bắt đầu 7 ngày dùng thử!", "#00ff88")
                self._licensed = True
                from PySide6.QtCore import QTimer
                QTimer.singleShot(800, self.accept)
            else:
                self._set_status("Không thể bắt đầu dùng thử.", "#ff4444")
                self.btn_trial.setVisible(False)
        except Exception as e:
            self._set_status(f"Lỗi: {e}", "#ff4444")

    # ── Exit ───────────────────────────────────────────────────────────────────

    def _on_exit(self):
        sys.exit(0)

    # ── Prevent closing without license ───────────────────────────────────────

    def closeEvent(self, event):
        if self._licensed:
            event.accept()
        else:
            event.ignore()


# ── Module-level helper ────────────────────────────────────────────────────────

def show_license_dialog_if_needed() -> bool:
    """
    Returns True if licensed (show main window), False if exited.
    Call this after QApplication is created but before MainWindow.
    """
    from security.license_client import LicenseClient
    if LicenseClient.get().is_valid():
        return True
    dlg = LicenseDialog()
    result = dlg.exec()
    return result == QDialog.DialogCode.Accepted
