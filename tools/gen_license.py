#!/usr/bin/env python3
"""
tools/gen_license.py
Công cụ ADMIN sinh License Key cho AI Video Translator Pro.

Chạy CLI:
    python tools/gen_license.py --hwid ABCD1234EFGH5678IJKL --days 365
    python tools/gen_license.py --hwid ABCD... --days 0          (vĩnh viễn)

Chạy GUI (không cần tham số):
    python tools/gen_license.py
"""

import sys
import os
import hmac
import hashlib
import time
import argparse
from datetime import datetime, timedelta

# Đường dẫn gốc project
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Phải khớp với APP_SECRET trong license_client.py
APP_SECRET = b"AIVideoTranslatorPro2026_S3cr3t_K3y_x7z"


# ─── Core keygen ──────────────────────────────────────────────────────────────

def generate_key(hwid: str, days: int) -> dict:
    """
    Sinh license key cho HWID.
    days=0 → key vĩnh viễn (expiry_ts rất lớn).
    Trả về dict {key, hwid, days, expiry_date, expiry_ts}.
    """
    hwid = hwid.strip().upper().replace("-", "")
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

    return {
        "key":         key,
        "hwid":        hwid,
        "days":        days if days > 0 else "∞",
        "expiry_date": expiry_str,
        "expiry_ts":   expiry_ts,
    }


def verify_key(key: str, hwid: str) -> bool:
    """Xác minh key có hợp lệ cho HWID không (kiểm tra offline)."""
    try:
        from security.license_client import LicenseClient
        client = LicenseClient.__new__(LicenseClient)
        client._hwid = hwid.strip().upper().replace("-", "")
        ok, msg, _ = client._validate_offline(key)
        return ok
    except Exception:
        return False


# ─── CLI mode ─────────────────────────────────────────────────────────────────

def cli_main():
    parser = argparse.ArgumentParser(
        description="Admin keygen — AI Video Translator Pro"
    )
    parser.add_argument("--hwid",  required=True, help="HWID của máy khách")
    parser.add_argument("--days",  type=int, default=365,
                        help="Số ngày (0 = vĩnh viễn, mặc định 365)")
    parser.add_argument("--verify", action="store_true",
                        help="Kiểm tra key vừa sinh có hợp lệ không")
    args = parser.parse_args()

    try:
        result = generate_key(args.hwid, args.days)
    except ValueError as e:
        print(f"❌ Lỗi: {e}")
        sys.exit(1)

    print("=" * 55)
    print("    LICENSE KEY ĐÃ SINH")
    print("=" * 55)
    print(f"  HWID        : {result['hwid']}")
    print(f"  Key         : {result['key']}")
    print(f"  Số ngày     : {result['days']}")
    print(f"  Hết hạn     : {result['expiry_date']}")
    print("=" * 55)

    if args.verify:
        ok = verify_key(result["key"], result["hwid"])
        print(f"  Xác minh   : {'✅ HỢP LỆ' if ok else '❌ KHÔNG HỢP LỆ'}")


# ─── GUI mode (PySide6) ───────────────────────────────────────────────────────

def gui_main():
    from PySide6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QLineEdit, QPushButton, QGroupBox,
        QRadioButton, QButtonGroup, QMessageBox, QFrame
    )
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QColor

    app = QApplication.instance() or QApplication(sys.argv)

    win = QWidget()
    win.setWindowTitle("🔑 Admin Keygen — AI Video Translator Pro")
    win.setFixedSize(600, 500)
    win.setStyleSheet("""
        QWidget        { background:#0b0e14; color:#e6edf3; font-family:Arial; font-size:12px; }
        QGroupBox      { font-weight:bold; font-size:13px; color:#00f2ff;
                         border:1px solid #30363d; border-radius:6px; margin-top:8px;
                         padding-top:6px; }
        QGroupBox::title { subcontrol-origin:margin; left:12px; }
        QLineEdit      { background:#161b22; color:#00f2ff; border:1px solid #30363d;
                         border-radius:4px; padding:5px 8px; font-family:Consolas;
                         font-size:12px; }
        QLineEdit:focus { border:1px solid #00f2ff; }
        QPushButton    { border-radius:5px; padding:6px 12px; font-weight:bold; }
        QPushButton:hover { opacity:0.85; }
        QRadioButton   { color:#cccccc; spacing:6px; }
        QRadioButton::indicator { width:14px; height:14px; }
        QLabel         { color:#cccccc; }
    """)

    outer = QVBoxLayout(win)
    outer.setContentsMargins(16, 16, 16, 16)
    outer.setSpacing(12)

    # ── Header ──────────────────────────────────────────────────────
    hdr = QLabel("🔑  ADMIN KEYGEN  —  AI Video Translator Pro")
    hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hdr.setStyleSheet(
        "background:#1a73e8;color:white;font-size:15px;font-weight:bold;"
        "border-radius:6px;padding:10px;"
    )
    outer.addWidget(hdr)

    # ── HWID Input ───────────────────────────────────────────────────
    g_hwid = QGroupBox("1. HWID máy khách")
    lo_hwid = QHBoxLayout(g_hwid)
    hwid_edit = QLineEdit()
    hwid_edit.setPlaceholderText("Dán HWID của khách vào đây  (VD: ABCD1234EFGH5678IJKL)")
    hwid_edit.setMinimumHeight(36)
    lo_hwid.addWidget(hwid_edit, 1)

    btn_own = QPushButton("📋 HWID máy này")
    btn_own.setFixedHeight(36)
    btn_own.setStyleSheet("background:#333;color:#ccc;")
    def paste_own_hwid():
        try:
            from security.hwid_generator import HardwareAuthenticator
            hwid_edit.setText(HardwareAuthenticator.generate_hwid())
        except Exception as e:
            QMessageBox.warning(win, "Lỗi", str(e))
    btn_own.clicked.connect(paste_own_hwid)
    lo_hwid.addWidget(btn_own)
    outer.addWidget(g_hwid)

    # ── Days Selector ────────────────────────────────────────────────
    g_days = QGroupBox("2. Thời hạn hiệu lực")
    lo_days = QVBoxLayout(g_days)

    radio_row = QHBoxLayout()
    days_group = QButtonGroup(win)
    days_map = [("30 ngày", 30), ("90 ngày", 90), ("180 ngày", 180),
                ("1 năm", 365), ("2 năm", 730), ("Vĩnh viễn", 0)]
    selected_days = [365]

    for label, val in days_map:
        rb = QRadioButton(label)
        rb.setChecked(val == 365)
        days_group.addButton(rb, val)
        radio_row.addWidget(rb)
    lo_days.addLayout(radio_row)

    custom_row = QHBoxLayout()
    lbl_custom = QLabel("  Hoặc nhập số ngày tùy ý:")
    lbl_custom.setStyleSheet("color:#888;font-size:11px;")
    custom_row.addWidget(lbl_custom)
    custom_edit = QLineEdit()
    custom_edit.setPlaceholderText("VD: 60")
    custom_edit.setFixedWidth(90)
    custom_edit.setFixedHeight(28)
    custom_row.addWidget(custom_edit)
    custom_row.addStretch()
    lo_days.addLayout(custom_row)
    outer.addWidget(g_days)

    # ── Result ───────────────────────────────────────────────────────
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet("color:#30363d;")
    outer.addWidget(sep)

    lbl_key_title = QLabel("License Key:")
    lbl_key_title.setStyleSheet("font-weight:bold;color:#00f2ff;font-size:13px;")
    outer.addWidget(lbl_key_title)

    key_edit = QLineEdit()
    key_edit.setReadOnly(True)
    key_edit.setPlaceholderText("Nhấn SINH KEY bên dưới...")
    key_edit.setMinimumHeight(44)
    key_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    key_edit.setStyleSheet(
        "font-family:Consolas;font-size:18px;font-weight:bold;"
        "color:#00ff88;background:#0a1a0a;letter-spacing:3px;"
        "border:1px solid #00ff88;border-radius:5px;"
    )
    outer.addWidget(key_edit)

    info_lbl = QLabel("")
    info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    info_lbl.setStyleSheet("color:#888;font-size:11px;")
    outer.addWidget(info_lbl)

    status_lbl = QLabel("")
    status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    status_lbl.setStyleSheet("font-size:12px;font-weight:bold;")
    outer.addWidget(status_lbl)

    # ── Buttons ──────────────────────────────────────────────────────
    btn_row = QHBoxLayout()

    btn_gen = QPushButton("⚡  SINH KEY")
    btn_gen.setMinimumHeight(44)
    btn_gen.setStyleSheet(
        "background:#1a73e8;color:white;font-size:15px;border-radius:5px;"
    )

    btn_copy = QPushButton("📋  Copy Key")
    btn_copy.setMinimumHeight(44)
    btn_copy.setStyleSheet(
        "background:#2d7a2d;color:white;font-size:14px;border-radius:5px;"
    )

    btn_verify = QPushButton("🔍  Xác Minh")
    btn_verify.setMinimumHeight(44)
    btn_verify.setStyleSheet(
        "background:#5a3a7a;color:white;font-size:14px;border-radius:5px;"
    )

    btn_row.addWidget(btn_gen, 3)
    btn_row.addWidget(btn_copy, 2)
    btn_row.addWidget(btn_verify, 2)
    outer.addLayout(btn_row)

    # ── Logic ────────────────────────────────────────────────────────
    def do_generate():
        hwid_raw = hwid_edit.text().strip()
        if not hwid_raw:
            QMessageBox.warning(win, "Thiếu HWID", "Vui lòng nhập HWID của máy khách!")
            return
        try:
            cd = custom_edit.text().strip()
            if cd:
                days = int(cd)
            else:
                checked = days_group.checkedButton()
                days = days_group.id(checked) if checked else 365
        except ValueError:
            QMessageBox.warning(win, "Lỗi", "Số ngày không hợp lệ!")
            return
        try:
            result = generate_key(hwid_raw, days)
        except Exception as e:
            QMessageBox.critical(win, "Lỗi sinh key", str(e))
            return

        key_edit.setText(result["key"])
        info_lbl.setText(
            f"HWID: {result['hwid']}   |   Hết hạn: {result['expiry_date']}   |   Số ngày: {result['days']}"
        )
        status_lbl.setText("")
        key_edit.setStyleSheet(
            "font-family:Consolas;font-size:18px;font-weight:bold;"
            "color:#00ff88;background:#0a1a0a;letter-spacing:3px;"
            "border:1px solid #00ff88;border-radius:5px;"
        )

    def do_copy():
        key = key_edit.text().strip()
        if not key:
            return
        QApplication.clipboard().setText(key)
        status_lbl.setText("✅  Đã copy key vào clipboard!")
        status_lbl.setStyleSheet("color:#00ff88;font-size:12px;font-weight:bold;")

    def do_verify():
        hwid_raw = hwid_edit.text().strip()
        key      = key_edit.text().strip()
        if not hwid_raw or not key:
            QMessageBox.warning(win, "Thiếu thông tin", "Cần có HWID và Key để xác minh!")
            return
        ok = verify_key(key, hwid_raw)
        if ok:
            status_lbl.setText("✅  Key HỢP LỆ cho HWID này")
            status_lbl.setStyleSheet("color:#00ff88;font-size:12px;font-weight:bold;")
        else:
            status_lbl.setText("❌  Key KHÔNG hợp lệ — kiểm tra lại HWID")
            status_lbl.setStyleSheet("color:#ff4444;font-size:12px;font-weight:bold;")

    btn_gen.clicked.connect(do_generate)
    btn_copy.clicked.connect(do_copy)
    btn_verify.clicked.connect(do_verify)

    win.show()
    sys.exit(app.exec())


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cli_main()
    else:
        gui_main()
