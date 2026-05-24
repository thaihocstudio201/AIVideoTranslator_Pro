"""
tools/license_server.py
Flask admin server for AI Video Translator Pro license management.
Run SEPARATELY from the desktop app:
    python tools/license_server.py

Admin panel: http://localhost:5000
Default password: admin2026
"""

import os
import sys
import hmac
import time
import hashlib
import sqlite3
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, jsonify, g
)

# ── Constants ──────────────────────────────────────────────────────────────────

APP_SECRET = b"AIVideoTranslatorPro2026_S3cr3t_K3y_x7z"
APP_VERSION = "2.0.0"

# SHA-256 of "admin2026"
ADMIN_PASS_HASH = "6051fc84a7a0d74c225fb18a496b09952da5642e60723ecae543298edd7d82d6"

# Database path relative to this file
_THIS_DIR = Path(__file__).parent
DB_PATH = _THIS_DIR / "licenses.db"

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# ── Database ───────────────────────────────────────────────────────────────────

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    hwid          TEXT    NOT NULL,
    license_key   TEXT    NOT NULL UNIQUE,
    plan          TEXT    DEFAULT '365 ngày',
    days          INTEGER DEFAULT 365,
    created_at    TEXT    DEFAULT (datetime('now', 'localtime')),
    expires_at    TEXT    NOT NULL,
    activated_at  TEXT,
    is_activated  INTEGER DEFAULT 0,
    client_ip     TEXT    DEFAULT '',
    notes         TEXT    DEFAULT ''
)
"""


def get_db() -> sqlite3.Connection:
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    """Create database and tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(DB_SCHEMA)
    conn.commit()
    conn.close()
    print(f"[License Server] Database ready at {DB_PATH}")


# ── Key generation ─────────────────────────────────────────────────────────────

def _make_key(hwid: str, expiry_ts: int) -> str:
    msg = f"{hwid}:{expiry_ts}".encode()
    h = hmac.new(APP_SECRET, msg, hashlib.sha256).hexdigest()
    raw = h[:16].upper()
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"


def _create_license(hwid: str, days: int, notes: str = "") -> dict:
    expiry_ts = int(time.time() + days * 86400)
    key = _make_key(hwid, expiry_ts)
    expires_at = datetime.fromtimestamp(expiry_ts).strftime("%Y-%m-%d %H:%M:%S")
    plan = f"{days} ngày" if days > 0 else "Vĩnh viễn"
    return {
        "hwid": hwid,
        "license_key": key,
        "plan": plan,
        "days": days,
        "expires_at": expires_at,
        "expiry_ts": expiry_ts,
        "notes": notes,
    }


# ── Auth helper ────────────────────────────────────────────────────────────────

def _is_auth() -> bool:
    return session.get("admin_auth") is True


# ── HTML Template ──────────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>License Server — Đăng nhập</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0d1117;color:#c9d1d9;font-family:'Segoe UI',Arial,sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh;}
  .card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:40px;
        width:360px;text-align:center;}
  h1{color:#00f2ff;font-size:20px;margin-bottom:8px;}
  p{color:#8b949e;font-size:13px;margin-bottom:24px;}
  input{width:100%;padding:10px 14px;background:#0d1117;border:1px solid #30363d;
        border-radius:6px;color:#c9d1d9;font-size:14px;margin-bottom:14px;outline:none;}
  input:focus{border-color:#00f2ff;}
  button{width:100%;padding:11px;background:#00f2ff;color:#000;font-size:15px;
         font-weight:bold;border:none;border-radius:6px;cursor:pointer;}
  button:hover{background:#00d4e0;}
  .err{color:#ff4444;font-size:13px;margin-top:10px;}
</style>
</head>
<body>
<div class="card">
  <h1>🔐 License Server</h1>
  <p>AI Video Translator Pro — Admin Panel</p>
  <form method="post">
    <input type="password" name="password" placeholder="Mật khẩu admin" autofocus>
    <button type="submit">Đăng nhập</button>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
  </form>
</div>
</body>
</html>"""

ADMIN_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>License Manager — AI Video Translator Pro</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0d1117;color:#c9d1d9;font-family:'Segoe UI',Arial,sans-serif;font-size:14px;}
  a{color:#00f2ff;text-decoration:none;}
  a:hover{text-decoration:underline;}

  /* Header */
  .header{background:#161b22;border-bottom:1px solid #30363d;padding:14px 24px;
           display:flex;align-items:center;justify-content:space-between;}
  .header h1{color:#00f2ff;font-size:18px;}
  .header .logout{color:#8b949e;font-size:13px;}

  /* Stats */
  .stats{display:flex;gap:16px;padding:20px 24px;}
  .stat-card{background:#161b22;border:1px solid #30363d;border-radius:8px;
              padding:16px 24px;flex:1;text-align:center;}
  .stat-card .num{font-size:28px;font-weight:bold;color:#00f2ff;}
  .stat-card .lbl{font-size:12px;color:#8b949e;margin-top:4px;}
  .stat-card.activated .num{color:#00ff88;}
  .stat-card.pending .num{color:#ffa500;}
  .stat-card.expired .num{color:#ff4444;}

  /* Create form */
  .create-section{padding:0 24px 20px;}
  .create-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;}
  .create-card h2{color:#00f2ff;font-size:15px;margin-bottom:14px;}
  .form-row{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;}
  .form-group{display:flex;flex-direction:column;gap:5px;}
  .form-group label{font-size:12px;color:#8b949e;}
  .form-group input{padding:8px 12px;background:#0d1117;border:1px solid #30363d;
                    border-radius:6px;color:#c9d1d9;font-size:13px;outline:none;}
  .form-group input:focus{border-color:#00f2ff;}
  .form-group input.hwid-input{width:280px;font-family:monospace;}
  .form-group input.days-input{width:80px;}
  .form-group input.notes-input{width:220px;}
  .btn{padding:8px 18px;border:none;border-radius:6px;font-size:13px;
       font-weight:bold;cursor:pointer;transition:opacity .15s;}
  .btn:hover{opacity:.85;}
  .btn-create{background:#1a73e8;color:#fff;}
  .btn-revoke{background:#7a2d2d;color:#fff;padding:5px 12px;font-size:12px;}
  .btn-copy{background:#2d5a2d;color:#fff;padding:5px 12px;font-size:12px;}
  .btn-export{background:#333;color:#ccc;}
  .btn-logout{background:#333;color:#ccc;font-size:12px;padding:6px 14px;}

  /* Search */
  .toolbar{padding:0 24px 12px;display:flex;align-items:center;gap:12px;}
  .toolbar input{padding:7px 12px;background:#161b22;border:1px solid #30363d;
                  border-radius:6px;color:#c9d1d9;font-size:13px;outline:none;width:280px;}
  .toolbar input:focus{border-color:#00f2ff;}

  /* Table */
  .table-section{padding:0 24px 24px;overflow-x:auto;}
  table{width:100%;border-collapse:collapse;background:#161b22;
        border:1px solid #30363d;border-radius:8px;overflow:hidden;}
  thead tr{background:#21262d;}
  th{padding:10px 12px;text-align:left;font-size:12px;color:#8b949e;
     font-weight:600;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;}
  td{padding:9px 12px;border-top:1px solid #21262d;vertical-align:middle;}
  tr.row-activated td{border-left:3px solid #00ff88;}
  tr.row-pending td{border-left:3px solid #ffa500;}
  tr.row-expired td{border-left:3px solid #ff4444;}
  tr:hover td{background:#1c2128;}

  .badge{padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold;white-space:nowrap;}
  .badge-activated{background:#0d2b1a;color:#00ff88;border:1px solid #00ff88;}
  .badge-pending{background:#2b1a00;color:#ffa500;border:1px solid #ffa500;}
  .badge-expired{background:#2b0d0d;color:#ff4444;border:1px solid #ff4444;}

  .key-mono{font-family:monospace;font-size:13px;color:#00f2ff;letter-spacing:1px;}
  .hwid-mono{font-family:monospace;font-size:11px;color:#aaa;}
  .actions{display:flex;gap:6px;}

  .flash{padding:10px 24px;background:#0d2b1a;border-bottom:1px solid #00ff88;
         color:#00ff88;font-size:13px;}
  .flash.error{background:#2b0d0d;border-color:#ff4444;color:#ff4444;}

  /* Modal */
  .modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);
                  z-index:100;align-items:center;justify-content:center;}
  .modal-overlay.open{display:flex;}
  .modal{background:#161b22;border:1px solid #30363d;border-radius:10px;
          padding:28px;min-width:340px;text-align:center;}
  .modal h3{color:#ff4444;margin-bottom:12px;}
  .modal p{color:#8b949e;font-size:13px;margin-bottom:20px;}
  .modal .btn-row{display:flex;gap:10px;justify-content:center;}
  .btn-cancel{background:#333;color:#ccc;padding:8px 20px;border-radius:6px;
               border:none;cursor:pointer;font-size:13px;}
</style>
</head>
<body>

<div class="header">
  <h1>🔐 License Manager — AI Video Translator Pro</h1>
  <div style="display:flex;gap:16px;align-items:center;">
    <span style="color:#8b949e;font-size:12px;">{{ now }}</span>
    <a href="/logout" class="logout btn btn-logout">Đăng xuất</a>
  </div>
</div>

{% if flash_msg %}
<div class="flash {{ 'error' if flash_err else '' }}">{{ flash_msg }}</div>
{% endif %}

<!-- Stats -->
<div class="stats">
  <div class="stat-card">
    <div class="num">{{ total }}</div>
    <div class="lbl">Tổng số</div>
  </div>
  <div class="stat-card activated">
    <div class="num">{{ activated }}</div>
    <div class="lbl">Đã kích hoạt</div>
  </div>
  <div class="stat-card pending">
    <div class="num">{{ pending }}</div>
    <div class="lbl">Chờ kích hoạt</div>
  </div>
  <div class="stat-card expired">
    <div class="num">{{ expired }}</div>
    <div class="lbl">Đã hết hạn</div>
  </div>
</div>

<!-- Create form -->
<div class="create-section">
  <div class="create-card">
    <h2>➕ Tạo License Mới</h2>
    <form method="post" action="/admin/create">
      <div class="form-row">
        <div class="form-group">
          <label>HWID máy khách *</label>
          <input class="hwid-input" type="text" name="hwid" placeholder="ABCD1234EFGH5678..." required>
        </div>
        <div class="form-group">
          <label>Số ngày</label>
          <input class="days-input" type="number" name="days" value="365" min="1" max="9999">
        </div>
        <div class="form-group">
          <label>Ghi chú</label>
          <input class="notes-input" type="text" name="notes" placeholder="Tên khách hàng...">
        </div>
        <div class="form-group">
          <label>&nbsp;</label>
          <button type="submit" class="btn btn-create">⚡ Tạo License</button>
        </div>
      </div>
    </form>
  </div>
</div>

<!-- Toolbar -->
<div class="toolbar">
  <input type="text" id="searchInput" placeholder="🔍 Tìm kiếm HWID, key, ghi chú..."
         oninput="filterTable(this.value)">
  <button class="btn btn-export" onclick="exportCSV()">📤 Export CSV</button>
  <span style="color:#8b949e;font-size:12px;margin-left:auto;">{{ licenses|length }} bản ghi</span>
</div>

<!-- Table -->
<div class="table-section">
  <table id="licenseTable">
    <thead>
      <tr>
        <th>ID</th>
        <th>HWID</th>
        <th>License Key</th>
        <th>Gói</th>
        <th>Tạo lúc</th>
        <th>Hết hạn</th>
        <th>Kích hoạt</th>
        <th>IP</th>
        <th>Ghi chú</th>
        <th>Thao tác</th>
      </tr>
    </thead>
    <tbody>
      {% for lic in licenses %}
      {% set now_str = now %}
      {% set is_exp = lic.expires_at < now_str %}
      {% set row_cls = 'row-expired' if is_exp else ('row-activated' if lic.is_activated else 'row-pending') %}
      <tr class="{{ row_cls }}" data-search="{{ lic.hwid }} {{ lic.license_key }} {{ lic.notes }}">
        <td>{{ lic.id }}</td>
        <td><span class="hwid-mono" title="{{ lic.hwid }}">{{ lic.hwid[:16] }}…</span></td>
        <td><span class="key-mono">{{ lic.license_key }}</span></td>
        <td>{{ lic.plan }}</td>
        <td style="font-size:12px;color:#8b949e;">{{ lic.created_at }}</td>
        <td style="font-size:12px;{% if is_exp %}color:#ff4444;{% endif %}">{{ lic.expires_at }}</td>
        <td>
          {% if is_exp %}
            <span class="badge badge-expired">Hết hạn</span>
          {% elif lic.is_activated %}
            <span class="badge badge-activated">✓ Đã kích hoạt</span>
            <div style="font-size:11px;color:#8b949e;margin-top:2px;">{{ lic.activated_at or '' }}</div>
          {% else %}
            <span class="badge badge-pending">Chờ</span>
          {% endif %}
        </td>
        <td style="font-size:12px;color:#8b949e;">{{ lic.client_ip or '—' }}</td>
        <td style="font-size:12px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
            title="{{ lic.notes }}">{{ lic.notes or '—' }}</td>
        <td>
          <div class="actions">
            <button class="btn btn-copy" onclick="copyKey('{{ lic.license_key }}')">📋 Copy</button>
            <button class="btn btn-revoke" onclick="confirmRevoke({{ lic.id }}, '{{ lic.license_key }}')">🗑️ Xóa</button>
          </div>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="10" style="text-align:center;color:#8b949e;padding:24px;">Chưa có license nào</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<!-- Revoke Modal -->
<div class="modal-overlay" id="revokeModal">
  <div class="modal">
    <h3>🗑️ Xác nhận xóa</h3>
    <p id="revokeMsg">Bạn có chắc muốn xóa license này?</p>
    <div class="btn-row">
      <button class="btn-cancel" onclick="closeModal()">Hủy</button>
      <form id="revokeForm" method="post">
        <button type="submit" class="btn btn-revoke" style="padding:8px 20px;">Xóa</button>
      </form>
    </div>
  </div>
</div>

<script>
function confirmRevoke(id, key) {
  document.getElementById('revokeMsg').textContent = 'Xóa license: ' + key + ' ?';
  document.getElementById('revokeForm').action = '/admin/revoke/' + id;
  document.getElementById('revokeModal').classList.add('open');
}
function closeModal() {
  document.getElementById('revokeModal').classList.remove('open');
}
function copyKey(key) {
  navigator.clipboard.writeText(key).then(() => {
    const old = event.target.textContent;
    event.target.textContent = '✓ Copied!';
    setTimeout(() => event.target.textContent = old, 1500);
  });
}
function filterTable(q) {
  q = q.toLowerCase();
  document.querySelectorAll('#licenseTable tbody tr[data-search]').forEach(row => {
    row.style.display = row.dataset.search.toLowerCase().includes(q) ? '' : 'none';
  });
}
function exportCSV() {
  const rows = [['ID','HWID','License Key','Plan','Created','Expires','Activated','IP','Notes']];
  document.querySelectorAll('#licenseTable tbody tr[data-search]').forEach(tr => {
    const cells = tr.querySelectorAll('td');
    if (cells.length >= 9) {
      rows.push([
        cells[0].textContent.trim(),
        cells[1].querySelector('span') ? cells[1].querySelector('span').title : cells[1].textContent.trim(),
        cells[2].textContent.trim(),
        cells[3].textContent.trim(),
        cells[4].textContent.trim(),
        cells[5].textContent.trim(),
        cells[6].textContent.trim().replace(/\\n/g,' '),
        cells[7].textContent.trim(),
        cells[8].textContent.trim(),
      ]);
    }
  });
  const csv = rows.map(r => r.map(c => '"' + c.replace(/"/g,'""') + '"').join(',')).join('\\n');
  const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'licenses_' + new Date().toISOString().slice(0,10) + '.csv';
  a.click();
}
</script>
</body>
</html>"""


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if not _is_auth():
        return redirect(url_for("login"))
    return redirect(url_for("admin"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pwd = request.form.get("password", "")
        pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()
        if pwd_hash == ADMIN_PASS_HASH:
            session["admin_auth"] = True
            return redirect(url_for("admin"))
        error = "Sai mật khẩu!"
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
def admin():
    if not _is_auth():
        return redirect(url_for("login"))

    db = get_db()
    licenses = db.execute(
        "SELECT * FROM licenses ORDER BY id DESC"
    ).fetchall()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(licenses)
    activated = sum(1 for r in licenses if r["is_activated"] and r["expires_at"] >= now_str)
    expired = sum(1 for r in licenses if r["expires_at"] < now_str)
    pending = total - activated - expired

    flash_msg = session.pop("flash_msg", None)
    flash_err = session.pop("flash_err", False)

    return render_template_string(
        ADMIN_HTML,
        licenses=licenses,
        total=total,
        activated=activated,
        pending=pending,
        expired=expired,
        now=now_str,
        flash_msg=flash_msg,
        flash_err=flash_err,
    )


@app.route("/admin/create", methods=["POST"])
def admin_create():
    if not _is_auth():
        return redirect(url_for("login"))

    hwid = request.form.get("hwid", "").strip()
    days_str = request.form.get("days", "365").strip()
    notes = request.form.get("notes", "").strip()

    if not hwid:
        session["flash_msg"] = "HWID không được để trống!"
        session["flash_err"] = True
        return redirect(url_for("admin"))

    try:
        days = int(days_str)
        if days <= 0:
            days = 365
    except ValueError:
        days = 365

    lic = _create_license(hwid, days, notes)

    try:
        db = get_db()
        db.execute(
            "INSERT INTO licenses (hwid, license_key, plan, days, expires_at, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (lic["hwid"], lic["license_key"], lic["plan"], lic["days"],
             lic["expires_at"], lic["notes"])
        )
        db.commit()
        session["flash_msg"] = f"Đã tạo license: {lic['license_key']}"
        session["flash_err"] = False
    except sqlite3.IntegrityError:
        session["flash_msg"] = f"License đã tồn tại cho HWID này (cùng thời điểm hết hạn)!"
        session["flash_err"] = True

    return redirect(url_for("admin"))


@app.route("/admin/revoke/<int:lic_id>", methods=["POST"])
def admin_revoke(lic_id: int):
    if not _is_auth():
        return redirect(url_for("login"))

    db = get_db()
    row = db.execute("SELECT license_key FROM licenses WHERE id = ?", (lic_id,)).fetchone()
    if row:
        db.execute("DELETE FROM licenses WHERE id = ?", (lic_id,))
        db.commit()
        session["flash_msg"] = f"Đã xóa license: {row['license_key']}"
        session["flash_err"] = False
    else:
        session["flash_msg"] = "Không tìm thấy license!"
        session["flash_err"] = True

    return redirect(url_for("admin"))


@app.route("/api/validate", methods=["POST"])
def api_validate():
    """JSON API — client calls this to validate a license key."""
    data = request.get_json(silent=True) or {}
    key = data.get("key", "").strip()
    hwid = data.get("hwid", "").strip()
    client_ip = request.remote_addr or ""

    if not key or not hwid:
        return jsonify({"valid": False, "message": "Thiếu key hoặc hwid"}), 400

    # Normalise key — strip dashes
    key_clean = key.replace("-", "").upper()

    db = get_db()
    row = db.execute(
        "SELECT * FROM licenses WHERE hwid = ?", (hwid,)
    ).fetchone()

    if not row:
        return jsonify({"valid": False, "message": "Key không hợp lệ hoặc không khớp với máy"}), 200

    # Check key matches
    stored_clean = row["license_key"].replace("-", "").upper()
    if key_clean != stored_clean:
        return jsonify({"valid": False, "message": "Key sai"}), 200

    # Check expiry
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if row["expires_at"] < now_str:
        return jsonify({"valid": False, "message": "Key đã hết hạn", "expired": True}), 200

    # Parse expiry timestamp
    try:
        exp_dt = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
        expiry_ts = int(exp_dt.timestamp())
    except Exception:
        expiry_ts = 0

    days_left = max(0, int((expiry_ts - time.time()) / 86400))

    # Mark as activated
    activated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "UPDATE licenses SET is_activated=1, activated_at=?, client_ip=? WHERE id=?",
        (activated_at, client_ip, row["id"])
    )
    db.commit()

    return jsonify({
        "valid": True,
        "message": f"Kích hoạt thành công — còn {days_left} ngày",
        "expiry_ts": expiry_ts,
        "days_left": days_left,
        "plan": row["plan"],
        "version_allowed": APP_VERSION,
    }), 200


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
