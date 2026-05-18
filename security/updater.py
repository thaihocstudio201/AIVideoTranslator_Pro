"""
security/updater.py
Kiểm tra và tải bản cập nhật từ xa.
Hỗ trợ: GitHub Releases API hoặc custom server endpoint.
"""

import os
import sys
import json
import time
import threading
import tempfile
import shutil
import zipfile
from typing import Optional, Callable
from pathlib import Path

CURRENT_VERSION = "2.0.0"
APP_DIR         = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# URL mặc định — cấu hình trong config/update_config.json hoặc qua set_update_url()
DEFAULT_UPDATE_URL = ""   # ví dụ: "https://api.github.com/repos/OWNER/REPO/releases/latest"

UPDATE_CONFIG_PATH = APP_DIR / "config" / "update_config.json"
LAST_CHECK_PATH    = APP_DIR / "config" / ".last_update_check"
CHECK_INTERVAL_H   = 24   # kiểm tra tối đa 1 lần/ngày


class UpdateInfo:
    """Thông tin bản cập nhật."""
    __slots__ = ("current_version", "latest_version", "has_update",
                 "download_url", "release_notes", "release_date", "file_size_mb")

    def __init__(self):
        self.current_version: str  = CURRENT_VERSION
        self.latest_version: str   = CURRENT_VERSION
        self.has_update: bool      = False
        self.download_url: str     = ""
        self.release_notes: str    = ""
        self.release_date: str     = ""
        self.file_size_mb: float   = 0.0


class AppUpdater:
    """Singleton — kiểm tra và tải bản cập nhật."""

    _instance: "Optional[AppUpdater]" = None

    @classmethod
    def get(cls) -> "AppUpdater":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._update_url  = self._load_update_url()
        self._last_info:  Optional[UpdateInfo] = None
        self._is_checking = False
        self._download_progress: float = 0.0  # 0.0–1.0

    # ── Public API ─────────────────────────────────────────────────

    def set_update_url(self, url: str):
        self._update_url = url.strip()
        self._save_update_url(url.strip())

    @property
    def update_url(self) -> str:
        return self._update_url

    @property
    def current_version(self) -> str:
        return CURRENT_VERSION

    def check_for_updates(self, force: bool = False) -> UpdateInfo:
        """
        Kiểm tra cập nhật (đồng bộ).
        Nếu đã kiểm tra trong 24h và force=False → trả cache.
        """
        if not force and self._last_info and not self._should_check():
            return self._last_info

        info = UpdateInfo()
        if not self._update_url:
            info.release_notes = "Chưa cấu hình URL cập nhật"
            self._last_info = info
            return info

        try:
            import requests
            headers = {"Accept": "application/vnd.github+json",
                       "User-Agent": f"AIVideoTranslatorPro/{CURRENT_VERSION}"}
            resp = requests.get(self._update_url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            info = self._parse_response(data)
            self._last_info = info
            self._mark_last_check()
            return info
        except Exception as e:
            info.release_notes = f"Lỗi kiểm tra cập nhật: {e}"
            self._last_info = info
            return info

    def check_async(self, callback: Callable[[UpdateInfo], None]):
        """Kiểm tra cập nhật trên background thread, gọi callback khi xong."""
        if self._is_checking:
            return
        self._is_checking = True
        def _run():
            try:
                result = self.check_for_updates()
                callback(result)
            except Exception:
                callback(UpdateInfo())
            finally:
                self._is_checking = False
        threading.Thread(target=_run, daemon=True).start()

    def download_update(
        self,
        url: str,
        progress_cb: Optional[Callable[[float], None]] = None
    ) -> Optional[str]:
        """
        Tải file cập nhật về thư mục tạm.
        progress_cb(0.0–1.0) được gọi định kỳ.
        Trả về đường dẫn file đã tải hoặc None nếu lỗi.
        """
        if not url:
            return None
        try:
            import requests
            tmp_dir  = tempfile.mkdtemp(prefix="aivtp_update_")
            filename = url.split("/")[-1].split("?")[0] or "update.zip"
            out_path = os.path.join(tmp_dir, filename)

            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total and progress_cb:
                                progress_cb(downloaded / total)
            if progress_cb:
                progress_cb(1.0)
            return out_path
        except Exception as e:
            return None

    def apply_update_zip(self, zip_path: str) -> tuple:
        """
        Áp dụng cập nhật từ file ZIP.
        Giải nén vào thư mục app, bỏ qua config/ và license.json.
        Trả về (success: bool, message: str).
        """
        if not os.path.isfile(zip_path):
            return False, "File cập nhật không tồn tại"
        try:
            skip_prefixes = ("config/", "config\\")
            with zipfile.ZipFile(zip_path, "r") as zf:
                members = zf.namelist()
                # Detect top-level folder (GitHub releases often wrap in repo-name/)
                top_dir = ""
                if members and "/" in members[0]:
                    top_dir = members[0].split("/")[0] + "/"

                for member in members:
                    rel = member[len(top_dir):] if top_dir and member.startswith(top_dir) else member
                    if not rel or rel.endswith("/"):
                        continue
                    # Bỏ qua config/ và file trống
                    if any(rel.startswith(p) for p in skip_prefixes):
                        continue
                    dest = APP_DIR / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)

            return True, "Cập nhật thành công! Vui lòng khởi động lại ứng dụng."
        except Exception as e:
            return False, f"Lỗi giải nén cập nhật: {e}"

    def launch_installer(self, installer_path: str) -> bool:
        """Chạy file installer (.exe) và thoát ứng dụng hiện tại."""
        try:
            import subprocess
            if sys.platform == "win32":
                subprocess.Popen([installer_path], shell=False)
            else:
                subprocess.Popen(["bash", installer_path])
            return True
        except Exception:
            return False

    # ── Internal ───────────────────────────────────────────────────

    def _parse_response(self, data: dict) -> UpdateInfo:
        """Parse GitHub releases API hoặc custom JSON response."""
        info = UpdateInfo()
        # GitHub format
        if "tag_name" in data:
            latest = data["tag_name"].lstrip("v")
            info.latest_version = latest
            info.has_update     = self._version_gt(latest, CURRENT_VERSION)
            info.release_notes  = data.get("body", "")[:500]
            info.release_date   = data.get("published_at", "")[:10]
            # Tìm file .zip hoặc .exe trong assets
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                if name.endswith((".zip", ".exe", ".tar.gz")):
                    info.download_url   = asset.get("browser_download_url", "")
                    info.file_size_mb   = asset.get("size", 0) / 1024 / 1024
                    break
            if not info.download_url:
                info.download_url = data.get("zipball_url", "")
        else:
            # Custom server format: {latest_version, download_url, release_notes, ...}
            latest = data.get("latest_version", CURRENT_VERSION)
            info.latest_version = latest
            info.has_update     = self._version_gt(latest, CURRENT_VERSION)
            info.download_url   = data.get("download_url", "")
            info.release_notes  = data.get("release_notes", "")
            info.release_date   = data.get("release_date", "")
            info.file_size_mb   = float(data.get("file_size_mb", 0))
        return info

    @staticmethod
    def _version_gt(v1: str, v2: str) -> bool:
        """True nếu v1 > v2 (so sánh semantic version)."""
        try:
            def _parse(v):
                return tuple(int(x) for x in v.strip().split(".")[:3])
            return _parse(v1) > _parse(v2)
        except Exception:
            return v1 != v2

    def _should_check(self) -> bool:
        try:
            if LAST_CHECK_PATH.exists():
                last = float(LAST_CHECK_PATH.read_text().strip())
                if time.time() - last < CHECK_INTERVAL_H * 3600:
                    return False
        except Exception:
            pass
        return True

    def _mark_last_check(self):
        try:
            LAST_CHECK_PATH.parent.mkdir(parents=True, exist_ok=True)
            LAST_CHECK_PATH.write_text(str(time.time()))
        except Exception:
            pass

    def _load_update_url(self) -> str:
        try:
            if UPDATE_CONFIG_PATH.exists():
                d = json.loads(UPDATE_CONFIG_PATH.read_text(encoding="utf-8"))
                return d.get("update_url", DEFAULT_UPDATE_URL)
        except Exception:
            pass
        return DEFAULT_UPDATE_URL

    def _save_update_url(self, url: str):
        try:
            UPDATE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            d = {}
            if UPDATE_CONFIG_PATH.exists():
                try:
                    d = json.loads(UPDATE_CONFIG_PATH.read_text(encoding="utf-8"))
                except Exception:
                    pass
            d["update_url"] = url
            UPDATE_CONFIG_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")
        except Exception:
            pass
