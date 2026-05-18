#!/usr/bin/env python3
"""
tools/gen_license.py
Công cụ ADMIN sinh License Key cho AI Video Translator Pro.

Chạy CLI:
    python tools/gen_license.py --hwid ABCD1234EFGH5678IJKL --days 365
    python tools/gen_license.py --hwid ABCD... --days 30 --plan trial
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
        sys.path.insert(0, _ROOT)
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


# ─── GUI mode ─────────────────────────────────────────────────────────────────

def gui_main():
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = tk.Tk()
    root.title("🔑 Admin Keygen — AI Video Translator Pro")
    root.geometry("560x480")
    root.configure(bg="#0b0e14")
    root.resizable(False, False)

    CYAN   = "#00f2ff"
    DARK   = "#0b0e14"
    CARD   = "#161b22"
    BORDER = "#30363d"
    WHITE  = "#e6edf3"
    RED    = "#ff4444"
    GREEN  = "#00cc66"

    style = ttk.Style()
    style.theme_use("clam")

    def lbl(parent, text, color=WHITE, size=11, bold=False):
        f = ("Consolas" if ":" in text else "Arial", size, "bold" if bold else "normal")
        return tk.Label(parent, text=text, bg=DARK, fg=color, font=f)

    def entry(parent, show=None, width=44):
        e = tk.Entry(parent, bg=CARD, fg=CYAN, insertbackground=CYAN,
                     relief="flat", bd=1, width=width,
                     font=("Consolas", 12), show=show or "")
        e.configure(highlightthickness=1, highlightbackground=BORDER,
                    highlightcolor=CYAN)
        return e

    def btn(parent, text, cmd, color="#1a73e8", w=14):
        return tk.Button(parent, text=text, command=cmd, bg=color, fg="white",
                         relief="flat", cursor="hand2", width=w,
                         font=("Arial", 11, "bold"), activebackground=color,
                         activeforeground="white")

    # ── Header ──
    hdr = tk.Frame(root, bg="#1a73e8", height=50)
    hdr.pack(fill="x")
    tk.Label(hdr, text="🔑  ADMIN KEYGEN  —  AI Video Translator Pro",
             bg="#1a73e8", fg="white", font=("Arial", 14, "bold")).pack(pady=12)

    body = tk.Frame(root, bg=DARK, padx=20, pady=12)
    body.pack(fill="both", expand=True)

    # HWID input
    lbl(body, "Mã máy (HWID) của khách hàng:", CYAN, 11, True).pack(anchor="w", pady=(8,2))
    hwid_var = tk.StringVar()
    ent_hwid = entry(body)
    ent_hwid.pack(fill="x", pady=(0,8))

    # Days
    days_frm = tk.Frame(body, bg=DARK)
    days_frm.pack(fill="x", pady=4)
    lbl(days_frm, "Số ngày hiệu lực:", WHITE, 11, True).pack(side="left")

    days_var = tk.IntVar(value=365)
    for d, label in [(30,"30 ngày"), (90,"90 ngày"), (180,"6 tháng"),
                     (365,"1 năm"), (730,"2 năm"), (0,"Vĩnh viễn")]:
        tk.Radiobutton(days_frm, text=label, variable=days_var, value=d,
                       bg=DARK, fg=WHITE, selectcolor="#1a73e8",
                       font=("Arial", 10), activebackground=DARK).pack(side="left", padx=6)

    # Custom days
    custom_frm = tk.Frame(body, bg=DARK)
    custom_frm.pack(fill="x", pady=(0,8))
    lbl(custom_frm, "  Hoặc nhập số ngày tùy ý:", WHITE, 10).pack(side="left")
    custom_days = tk.Entry(custom_frm, width=8, bg=CARD, fg=CYAN,
                           insertbackground=CYAN, font=("Consolas", 11),
                           relief="flat", highlightthickness=1,
                           highlightbackground=BORDER, highlightcolor=CYAN)
    custom_days.pack(side="left", padx=6)

    # Result
    sep = tk.Frame(body, bg=BORDER, height=1)
    sep.pack(fill="x", pady=10)

    lbl(body, "License Key sinh ra:", CYAN, 11, True).pack(anchor="w", pady=(0,4))
    result_frm = tk.Frame(body, bg=CARD, bd=1, relief="flat",
                          highlightthickness=1, highlightbackground=BORDER)
    result_frm.pack(fill="x")
    result_var = tk.StringVar(value="—")
    result_lbl = tk.Label(result_frm, textvariable=result_var, bg=CARD, fg=GREEN,
                          font=("Consolas", 16, "bold"), pady=12)
    result_lbl.pack()

    info_var = tk.StringVar(value="")
    tk.Label(body, textvariable=info_var, bg=DARK, fg="#aaaaaa",
             font=("Arial", 10)).pack(pady=4)

    status_var = tk.StringVar(value="")
    status_lbl = tk.Label(body, textvariable=status_var, bg=DARK, fg=WHITE,
                          font=("Arial", 11))
    status_lbl.pack(pady=4)

    # ── Actions ──
    def do_generate():
        hwid_raw = ent_hwid.get().strip()
        if not hwid_raw:
            messagebox.showwarning("Thiếu HWID", "Vui lòng nhập HWID của máy khách!")
            return
        try:
            # Custom days override
            cd = custom_days.get().strip()
            days = int(cd) if cd else days_var.get()
            result = generate_key(hwid_raw, days)
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
            return

        result_var.set(result["key"])
        info_var.set(
            f"HWID: {result['hwid']}   |   "
            f"Hết hạn: {result['expiry_date']}   |   "
            f"Số ngày: {result['days']}"
        )
        status_var.set("")
        result_lbl.configure(fg=GREEN)

    def do_copy():
        key = result_var.get()
        if key == "—":
            return
        root.clipboard_clear()
        root.clipboard_append(key)
        status_var.set("✅ Đã copy key vào clipboard!")

    def do_verify():
        hwid_raw = ent_hwid.get().strip()
        key_val  = result_var.get()
        if key_val == "—" or not hwid_raw:
            return
        ok = verify_key(key_val, hwid_raw)
        if ok:
            status_var.set("✅ Key xác minh HỢP LỆ cho HWID này")
            status_lbl.configure(fg=GREEN)
        else:
            status_var.set("❌ Key KHÔNG hợp lệ — kiểm tra lại HWID")
            status_lbl.configure(fg=RED)

    btn_row = tk.Frame(body, bg=DARK)
    btn_row.pack(pady=10)
    btn(btn_row, "⚡ SINH KEY", do_generate, "#1a73e8").pack(side="left", padx=6)
    btn(btn_row, "📋 Copy Key", do_copy,     "#2d7a2d").pack(side="left", padx=6)
    btn(btn_row, "🔍 Xác Minh", do_verify,   "#5a3a7a").pack(side="left", padx=6)

    root.mainloop()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cli_main()
    else:
        gui_main()
