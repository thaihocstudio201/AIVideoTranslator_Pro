#!/usr/bin/env python3
"""
tools/admin_keygen.py
Công cụ ADMIN tạo License Key — chạy độc lập, không cần app chính.

Chạy:
    python tools/admin_keygen.py
    hoặc double-click file nếu đã cài Python
"""

import sys
import os
import hmac
import hashlib
import time
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

APP_SECRET = b"AIVideoTranslatorPro2026_S3cr3t_K3y_x7z"


# ── Logic sinh key (không phụ thuộc UI) ─────────────────────────────────────

def _generate(hwid: str, days: int) -> dict:
    hwid = hwid.strip().upper().replace("-", "").replace(" ", "")
    if not hwid:
        raise ValueError("HWID không được để trống")
    if days == 0:
        expiry_ts  = int(9999 * 365.25 * 86400)
        expiry_str = "Vĩnh viễn"
    else:
        expiry_ts  = int(time.time() + days * 86400)
        expiry_str = (datetime.now() + timedelta(days=days)).strftime("%d/%m/%Y")
    msg = f"{hwid}:{expiry_ts}".encode()
    h   = hmac.new(APP_SECRET, msg, hashlib.sha256).hexdigest()
    raw = h[:16].upper()
    key = f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"
    return {"key": key, "hwid": hwid, "days": days, "expiry_str": expiry_str, "expiry_ts": expiry_ts}


def _verify(key: str, hwid: str) -> bool:
    try:
        from security.license_client import LicenseClient
        client        = LicenseClient.__new__(LicenseClient)
        client._hwid  = hwid.strip().upper().replace("-", "").replace(" ", "")
        ok, _, _info  = client._validate_offline(key)
        return ok
    except Exception:
        return False


def _own_hwid() -> str:
    try:
        from security.hwid_generator import HardwareAuthenticator
        return HardwareAuthenticator.generate_hwid()
    except Exception:
        return ""


# ── GUI ──────────────────────────────────────────────────────────────────────

def main():
    from PySide6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QLineEdit, QPushButton, QGroupBox,
        QButtonGroup, QRadioButton, QFrame, QMessageBox,
        QSizePolicy
    )
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QClipboard

    app = QApplication(sys.argv)
    app.setApplicationName("Admin Keygen")

    # ── Window ───────────────────────────────────────────────────────
    win = QWidget()
    win.setWindowTitle("🔑  Admin Keygen  —  AI Video Translator Pro")
    win.setFixedSize(640, 530)
    win.setStyleSheet("""
        QWidget {
            background: #0d1117;
            color: #e6edf3;
            font-family: Arial, sans-serif;
            font-size: 12px;
        }
        QGroupBox {
            font-weight: bold;
            font-size: 12px;
            color: #00f2ff;
            border: 1px solid #30363d;
            border-radius: 6px;
            margin-top: 10px;
            padding: 10px 8px 8px 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }
        QLineEdit {
            background: #161b22;
            color: #c9d1d9;
            border: 1px solid #30363d;
            border-radius: 4px;
            padding: 5px 8px;
            font-size: 12px;
        }
        QLineEdit:focus { border: 1px solid #00f2ff; }
        QPushButton {
            border-radius: 5px;
            padding: 7px 14px;
            font-weight: bold;
            font-size: 12px;
        }
        QPushButton:hover { opacity: 0.88; }
        QRadioButton { color: #c9d1d9; spacing: 6px; }
        QLabel { color: #c9d1d9; }
    """)

    root = QVBoxLayout(win)
    root.setContentsMargins(18, 18, 18, 18)
    root.setSpacing(10)

    # ── Header ───────────────────────────────────────────────────────
    hdr = QLabel("🔑  ADMIN KEYGEN  —  AI Video Translator Pro")
    hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hdr.setFixedHeight(46)
    hdr.setStyleSheet(
        "background: #1a73e8; color: white; font-size: 15px;"
        "font-weight: bold; border-radius: 6px;"
    )
    root.addWidget(hdr)

    # ── Nhóm 1: HWID ─────────────────────────────────────────────────
    g1 = QGroupBox("1. Mã máy (HWID) của khách hàng")
    lo1 = QHBoxLayout(g1)
    lo1.setSpacing(8)

    hwid_edit = QLineEdit()
    hwid_edit.setPlaceholderText("Dán HWID khách vào đây  (VD: ABCD1234EFGH5678IJKL)")
    hwid_edit.setMinimumHeight(36)
    hwid_edit.setStyleSheet(
        "font-family: Consolas, monospace; font-size: 13px;"
        "color: #ffa500; background: #161b22;"
    )
    lo1.addWidget(hwid_edit, 1)

    btn_own = QPushButton("📋 HWID máy này")
    btn_own.setFixedHeight(36)
    btn_own.setFixedWidth(130)
    btn_own.setStyleSheet("background: #21262d; color: #8b949e;")
    btn_own.setToolTip("Tự điền HWID của máy tính đang chạy tool này")
    def paste_own():
        h = _own_hwid()
        if h:
            hwid_edit.setText(h)
        else:
            QMessageBox.warning(win, "Lỗi", "Không lấy được HWID máy này.")
    btn_own.clicked.connect(paste_own)
    lo1.addWidget(btn_own)
    root.addWidget(g1)

    # ── Nhóm 2: Số ngày ──────────────────────────────────────────────
    g2 = QGroupBox("2. Thời hạn hiệu lực")
    lo2 = QVBoxLayout(g2)
    lo2.setSpacing(6)

    radio_row = QHBoxLayout()
    bg = QButtonGroup(win)
    PRESETS = [("30 ngày", 30), ("90 ngày", 90), ("180 ngày", 180),
               ("1 năm",  365), ("2 năm",  730), ("Vĩnh viễn",  0)]
    for label, val in PRESETS:
        rb = QRadioButton(label)
        rb.setChecked(val == 365)
        bg.addButton(rb, val)
        radio_row.addWidget(rb)
    radio_row.addStretch()
    lo2.addLayout(radio_row)

    custom_row = QHBoxLayout()
    lbl_c = QLabel("Hoặc nhập số ngày tùy ý:")
    lbl_c.setStyleSheet("color: #8b949e; font-size: 11px;")
    custom_row.addWidget(lbl_c)
    custom_edit = QLineEdit()
    custom_edit.setPlaceholderText("VD: 45")
    custom_edit.setFixedWidth(80)
    custom_edit.setFixedHeight(26)
    custom_row.addWidget(custom_edit)
    custom_row.addStretch()
    lo2.addLayout(custom_row)
    root.addWidget(g2)

    # ── Separator ────────────────────────────────────────────────────
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet("color: #21262d;")
    root.addWidget(sep)

    # ── Kết quả ──────────────────────────────────────────────────────
    lbl_title = QLabel("License Key:")
    lbl_title.setStyleSheet("font-weight: bold; color: #00f2ff; font-size: 13px;")
    root.addWidget(lbl_title)

    key_edit = QLineEdit()
    key_edit.setReadOnly(True)
    key_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    key_edit.setPlaceholderText("Nhấn  ⚡ SINH KEY  để tạo...")
    key_edit.setMinimumHeight(50)
    key_edit.setStyleSheet(
        "font-family: Consolas, monospace; font-size: 20px; font-weight: bold;"
        "color: #3fb950; background: #0d1f0d; letter-spacing: 3px;"
        "border: 1px solid #238636; border-radius: 5px;"
    )
    root.addWidget(key_edit)

    info_lbl = QLabel("")
    info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    info_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
    root.addWidget(info_lbl)

    status_lbl = QLabel("")
    status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    status_lbl.setStyleSheet("font-size: 12px; font-weight: bold; min-height: 20px;")
    root.addWidget(status_lbl)

    # ── Buttons ──────────────────────────────────────────────────────
    btn_row = QHBoxLayout()
    btn_row.setSpacing(10)

    btn_gen = QPushButton("⚡  SINH KEY")
    btn_gen.setMinimumHeight(46)
    btn_gen.setStyleSheet(
        "background: #1f6feb; color: white; font-size: 15px; border-radius: 6px;"
    )

    btn_copy = QPushButton("📋  Copy Key")
    btn_copy.setMinimumHeight(46)
    btn_copy.setStyleSheet(
        "background: #238636; color: white; font-size: 14px; border-radius: 6px;"
    )

    btn_verify = QPushButton("🔍  Xác Minh")
    btn_verify.setMinimumHeight(46)
    btn_verify.setStyleSheet(
        "background: #3d1f6e; color: white; font-size: 14px; border-radius: 6px;"
    )

    btn_row.addWidget(btn_gen, 3)
    btn_row.addWidget(btn_copy, 2)
    btn_row.addWidget(btn_verify, 2)
    root.addLayout(btn_row)

    # ── Handlers ─────────────────────────────────────────────────────
    def get_days() -> int:
        cd = custom_edit.text().strip()
        if cd:
            return int(cd)
        checked = bg.checkedButton()
        return bg.id(checked) if checked else 365

    def do_generate():
        status_lbl.setText("")
        hwid_raw = hwid_edit.text().strip()
        if not hwid_raw:
            QMessageBox.warning(win, "Thiếu HWID", "Vui lòng nhập HWID của máy khách!")
            return
        try:
            days = get_days()
        except ValueError:
            QMessageBox.warning(win, "Lỗi", "Số ngày không hợp lệ!")
            return
        try:
            r = _generate(hwid_raw, days)
        except Exception as e:
            QMessageBox.critical(win, "Lỗi sinh key", str(e))
            return
        key_edit.setText(r["key"])
        days_txt = "Vĩnh viễn" if r["days"] == 0 else f"{r['days']} ngày"
        info_lbl.setText(
            f"HWID: {r['hwid']}    |    Hết hạn: {r['expiry_str']}    |    {days_txt}"
        )

    def do_copy():
        key = key_edit.text().strip()
        if not key:
            return
        app.clipboard().setText(key)
        status_lbl.setText("✅  Đã copy key vào clipboard!")
        status_lbl.setStyleSheet("color: #3fb950; font-size: 12px; font-weight: bold;")

    def do_verify():
        hwid_raw = hwid_edit.text().strip()
        key      = key_edit.text().strip()
        if not hwid_raw or not key:
            QMessageBox.warning(win, "Thiếu thông tin",
                                "Cần có HWID và Key để xác minh!")
            return
        ok = _verify(key, hwid_raw)
        if ok:
            status_lbl.setText("✅  Key HỢP LỆ cho HWID này")
            status_lbl.setStyleSheet("color: #3fb950; font-size: 12px; font-weight: bold;")
        else:
            status_lbl.setText("❌  Key KHÔNG hợp lệ — kiểm tra lại HWID")
            status_lbl.setStyleSheet("color: #f85149; font-size: 12px; font-weight: bold;")

    btn_gen.clicked.connect(do_generate)
    btn_copy.clicked.connect(do_copy)
    btn_verify.clicked.connect(do_verify)

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
