"""
checkpoint_mgr.py - Quản lý Checkpoint để Resume pipeline sau lỗi.
Lưu trạng thái từng video vào disk, đọc lại khi nhấn Resume.
"""

import os
import json
import time
from pathlib import Path
from typing import Optional

from utils.custom_logger import sys_log

CHECKPOINT_DIR = Path("config/checkpoints")
try:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


class CheckpointManager:
    """
    Lưu và phục hồi trạng thái xử lý từng video.
    Mỗi video có 1 file checkpoint riêng theo tên + hash.
    """

    STAGES = [
        "pending",           # Chờ xử lý
        "audio_extracted",   # Đã tách audio
        "transcribed",       # Đã Whisper
        "translated",        # Đã dịch
        "tts_done",          # Đã tạo voice
        "rendered",          # Đã render xong
        "completed",         # Hoàn tất + cleanup
    ]

    def __init__(self, video_path: str, out_dir: str):
        import hashlib
        vid_hash = hashlib.md5(video_path.encode()).hexdigest()[:8]
        base = os.path.splitext(os.path.basename(video_path))[0]
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in base)
        self._ckpt_path = CHECKPOINT_DIR / f"{safe_name}_{vid_hash}.json"
        self._state: dict = self._load()
        self._state.setdefault("video_path", video_path)
        self._state.setdefault("out_dir", out_dir)
        self._state.setdefault("stage", "pending")
        self._state.setdefault("segments", [])
        self._state.setdefault("temp_files", {})
        self._state.setdefault("error_count", 0)
        self._state.setdefault("created_at", time.time())

    # =========================================================================
    # LOAD / SAVE
    # =========================================================================

    def _load(self) -> dict:
        if self._ckpt_path.exists():
            try:
                with open(self._ckpt_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sys_log.info(f"📂 Đọc checkpoint: {self._ckpt_path.name} (stage={data.get('stage')})")
                return data
            except Exception as e:
                sys_log.warning(f"⚠️ Không đọc được checkpoint: {e}. Bắt đầu lại từ đầu.")
        return {}

    def save(self):
        try:
            self._state["updated_at"] = time.time()
            with open(self._ckpt_path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            sys_log.warning(f"⚠️ Không lưu được checkpoint: {e}")

    def delete(self):
        """Xoá checkpoint khi hoàn tất thành công."""
        if self._ckpt_path.exists():
            self._ckpt_path.unlink()
            sys_log.info(f"🗑️ Đã xoá checkpoint: {self._ckpt_path.name}")

    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================

    @property
    def stage(self) -> str:
        return self._state.get("stage", "pending")

    @property
    def segments(self) -> list:
        return self._state.get("segments", [])

    @property
    def temp_files(self) -> dict:
        return self._state.get("temp_files", {})

    def is_stage_done(self, stage: str) -> bool:
        """Kiểm tra xem stage này đã hoàn tất chưa (để skip khi resume)."""
        current_idx = self.STAGES.index(self.stage) if self.stage in self.STAGES else 0
        target_idx = self.STAGES.index(stage) if stage in self.STAGES else 0
        return current_idx > target_idx

    def advance_stage(self, new_stage: str, **extra_data):
        """Tiến lên stage tiếp theo và lưu checkpoint."""
        self._state["stage"] = new_stage
        self._state.update(extra_data)
        self.save()
        sys_log.info(f"  ✅ Checkpoint [{new_stage}] đã lưu")

    def set_segments(self, segments: list):
        self._state["segments"] = segments
        self.save()

    def register_temp_file(self, key: str, path: str):
        """Lưu đường dẫn file tạm để tái sử dụng khi resume."""
        self._state["temp_files"][key] = path
        self.save()

    def get_temp_file(self, key: str) -> Optional[str]:
        path = self._state["temp_files"].get(key)
        if path and os.path.exists(path):
            return path
        return None

    def record_error(self, error_msg: str):
        self._state["error_count"] = self._state.get("error_count", 0) + 1
        self._state["last_error"] = error_msg
        self._state["last_error_time"] = time.time()
        self.save()

    @property
    def is_resumable(self) -> bool:
        """True nếu đã xử lý qua ít nhất 1 stage."""
        return self.stage not in ("pending", "completed")

    def summary(self) -> str:
        return (
            f"Stage={self.stage}, "
            f"Segments={len(self.segments)}, "
            f"Errors={self._state.get('error_count', 0)}, "
            f"TempFiles={list(self.temp_files.keys())}"
        )


def list_resumable_checkpoints() -> list[dict]:
    """Trả về danh sách các video chưa hoàn tất (có thể Resume)."""
    result = []
    for f in CHECKPOINT_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("stage") not in ("pending", "completed"):
                result.append({
                    "file": str(f),
                    "video": data.get("video_path", "?"),
                    "stage": data.get("stage", "?"),
                    "error_count": data.get("error_count", 0),
                    "last_error": data.get("last_error", ""),
                })
        except Exception:
            pass
    return result