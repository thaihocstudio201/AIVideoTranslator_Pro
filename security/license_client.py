"""
security/license_client.py
Hệ thống license: kích hoạt online/offline, lưu cache local, grace period 7 ngày.

Key format: XXXX-XXXX-XXXX-XXXX  (16 hex chars, dashes for readability)
Validation:  HMAC-SHA256(APP_SECRET, hwid + ":" + expiry_epoch)[:16].upper()
"""

import os
import sys
import json
import time
import hmac
import hashlib
from typing import Optional
from pathlib import Path

APP_VERSION    = "2.0.0"
APP_SECRET     = b"AIVideoTranslatorPro2026_S3cr3t_K3y_x7z"
LICENSE_PATH   = Path("config/license.json")
GRACE_DAYS     = 7
TRIAL_DAYS     = 7
DEFAULT_SERVER = ""

STATUS_VALID   = "valid"
STATUS_TRIAL   = "trial"
STATUS_EXPIRED = "expired"
STATUS_INVALID = "invalid"
STATUS_GRACE   = "grace"
STATUS_OFFLINE = "offline"


class LicenseInfo:
    __slots__ = ("status", "expiry_ts", "key", "hwid", "activated_at",
                 "message", "days_left", "version_allowed")

    def __init__(self):
        self.status: str          = STATUS_OFFLINE
        self.expiry_ts: float     = 0.0
        self.key: str             = ""
        self.hwid: str            = ""
        self.activated_at: float  = 0.0
        self.message: str         = "Chưa kích hoạt"
        self.days_left: int       = 0
        self.version_allowed: str = ""

    @property
    def is_valid(self) -> bool:
        return self.status in (STATUS_VALID, STATUS_TRIAL, STATUS_GRACE)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, d: dict) -> "LicenseInfo":
        obj = cls()
        for k in cls.__slots__:
            if k in d:
                setattr(obj, k, d[k])
        return obj


class LicenseClient:
    """Singleton — quản lý license của ứng dụng."""

    _instance: "Optional[LicenseClient]" = None

    @classmethod
    def get(cls) -> "LicenseClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        from security.hwid_generator import HardwareAuthenticator
        self._hwid   = HardwareAuthenticator.generate_hwid()
        self._info   = LicenseInfo()
        self._server = DEFAULT_SERVER
        self._load_cache()

    # ── Public API ─────────────────────────────────────────────────

    @property
    def hwid(self) -> str:
        return self._hwid

    @property
    def info(self) -> LicenseInfo:
        return self._info

    def is_valid(self) -> bool:
        self._refresh_status()
        return self._info.is_valid

    def get_status(self) -> LicenseInfo:
        self._refresh_status()
        return self._info

    def activate(self, key: str, server_url: str = "") -> tuple:
        """Kích hoạt license. Trả về (success: bool, message: str)."""
        key = self._normalize_key(key)
        if not key:
            return False, "Key không hợp lệ (định dạng: XXXX-XXXX-XXXX-XXXX)"

        url = server_url or self._server

        if url:
            ok, msg, info = self._validate_online(key, url)
            if ok:
                self._info = info
                self._save_cache()
                return True, msg
            if any(w in msg.lower() for w in ("key sai", "invalid", "hết hạn", "expired")):
                return False, msg

        ok, msg, info = self._validate_offline(key)
        if ok:
            self._info = info
            self._save_cache()
            return True, msg
        return False, msg

    def set_server(self, url: str):
        self._server = url.strip().rstrip("/")

    def deactivate(self):
        self._info = LicenseInfo()
        try:
            if LICENSE_PATH.exists():
                LICENSE_PATH.unlink()
        except OSError:
            pass

    def start_trial(self) -> bool:
        """Bắt đầu dùng thử (chỉ 1 lần)."""
        cache = self._read_raw_cache()
        if cache.get("trial_used"):
            return False
        now = time.time()
        self._info.status       = STATUS_TRIAL
        self._info.expiry_ts    = now + TRIAL_DAYS * 86400
        self._info.activated_at = now
        self._info.days_left    = TRIAL_DAYS
        self._info.message      = f"Dùng thử {TRIAL_DAYS} ngày"
        self._info.key          = "TRIAL"
        self._info.hwid         = self._hwid
        d = self._info.to_dict()
        d["trial_used"] = True
        self._save_cache(d)
        return True

    def check_trial_used(self) -> bool:
        return bool(self._read_raw_cache().get("trial_used", False))

    # ── Internal ───────────────────────────────────────────────────

    def _refresh_status(self):
        now = time.time()
        exp = self._info.expiry_ts
        if not exp:
            return
        remaining = exp - now
        self._info.days_left = max(0, int(remaining / 86400))
        if remaining > 0:
            if self._info.status not in (STATUS_TRIAL, STATUS_GRACE):
                self._info.status = STATUS_VALID
            self._info.message = f"Còn {self._info.days_left} ngày"
        elif remaining > -GRACE_DAYS * 86400:
            self._info.status = STATUS_GRACE
            grace_left = int((exp + GRACE_DAYS * 86400 - now) / 86400)
            self._info.message = f"Hết hạn — ân hạn {grace_left} ngày"
        else:
            self._info.status  = STATUS_EXPIRED
            self._info.message = "License đã hết hạn"

    def _validate_offline(self, key: str) -> tuple:
        raw = key.replace("-", "").upper()
        now = time.time()
        expiry_candidates = [
            int(now + 365 * 86400),
            int(now + 2 * 365 * 86400),
            int(now + 5 * 365 * 86400),
            int(9999 * 365.25 * 86400),
        ]
        for base_exp in expiry_candidates:
            for drift in range(-30, 31):
                exp_ts = base_exp + drift * 86400
                if hmac.compare_digest(raw, self._make_key(self._hwid, exp_ts)):
                    info = LicenseInfo()
                    info.status       = STATUS_VALID
                    info.key          = key
                    info.hwid         = self._hwid
                    info.expiry_ts    = float(exp_ts)
                    info.activated_at = now
                    info.days_left    = max(0, int((exp_ts - now) / 86400))
                    info.message      = f"Kích hoạt thành công — còn {info.days_left} ngày"
                    return True, info.message, info
        return False, "Key không hợp lệ hoặc không khớp với máy này", LicenseInfo()

    def _validate_online(self, key: str, url: str) -> tuple:
        try:
            import requests
            resp = requests.post(
                f"{url}/api/license/validate",
                json={"key": key, "hwid": self._hwid, "app_version": APP_VERSION},
                timeout=(5, 15),
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("valid"):
                info = LicenseInfo()
                info.status          = STATUS_VALID
                info.key             = key
                info.hwid            = self._hwid
                info.expiry_ts       = float(data.get("expiry_ts", 0))
                info.activated_at    = time.time()
                info.version_allowed = data.get("version_allowed", "")
                info.message         = data.get("message", "Kích hoạt thành công")
                self._refresh_status_for(info)
                return True, info.message, info
            return False, data.get("message", "Key không hợp lệ"), LicenseInfo()
        except Exception as e:
            return False, f"Lỗi kết nối server: {e}", LicenseInfo()

    @staticmethod
    def _refresh_status_for(info: LicenseInfo):
        now = time.time()
        exp = info.expiry_ts
        if exp <= 0:
            info.days_left = 9999
            info.message   = "Vĩnh viễn"
            return
        info.days_left = max(0, int((exp - now) / 86400))
        if exp > now:
            info.message = f"Còn {info.days_left} ngày"
        else:
            info.status  = STATUS_GRACE
            info.message = "Đã hết hạn"

    def _make_key(self, hwid: str, expiry_ts: int) -> str:
        msg = f"{hwid}:{expiry_ts}".encode()
        h   = hmac.new(APP_SECRET, msg, hashlib.sha256).hexdigest()
        return h[:16].upper()

    @staticmethod
    def _normalize_key(key: str) -> str:
        cleaned = key.strip().replace("-", "").replace(" ", "").upper()
        return cleaned if len(cleaned) >= 8 else ""

    def _load_cache(self):
        d = self._read_raw_cache()
        if not d:
            return
        try:
            self._info = LicenseInfo.from_dict(d)
            self._refresh_status()
        except Exception:
            self._info = LicenseInfo()

    def _read_raw_cache(self) -> dict:
        try:
            if LICENSE_PATH.exists():
                with open(LICENSE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_cache(self, extra: Optional[dict] = None):
        try:
            LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = self._info.to_dict()
            if extra:
                data.update(extra)
            with open(LICENSE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def generate_license_key(hwid: str, days: int = 365) -> str:
    """Tạo license key hợp lệ cho HWID (dùng cho admin cấp key)."""
    expiry_ts = int(time.time() + days * 86400)
    msg = f"{hwid}:{expiry_ts}".encode()
    h   = hmac.new(APP_SECRET, msg, hashlib.sha256).hexdigest()
    raw = h[:16].upper()
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"


if __name__ == "__main__":
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from security.hwid_generator import HardwareAuthenticator
    hwid = HardwareAuthenticator.generate_hwid()
    print(f"HWID: {hwid}")
    key  = generate_license_key(hwid, days=365)
    print(f"Key 1 năm: {key}")
    client = LicenseClient()
    ok, msg = client.activate(key)
    print(f"Activate: {ok} — {msg}")
