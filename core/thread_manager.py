"""
thread_manager.py - Thread-safe pipeline worker cho Qt UI
Đảm bảo mọi callback từ worker thread → UI thread đều an toàn qua Signal.
"""

import threading
from typing import Callable, Optional
from PySide6.QtCore import QObject, Signal, Qt

from utils.custom_logger import sys_log


class PipelineSignals(QObject):
    """Các signal dùng để giao tiếp thread-safe giữa worker và UI thread."""

    log_message   = Signal(str, str)      # (level, message)   level: INFO / WARNING / ERROR
    progress      = Signal(int, str)      # (percent, stage_label)
    video_done    = Signal(str, bool)     # (video_path, success)
    all_done      = Signal()              # Hoàn thành toàn bộ pipeline
    error_pause   = Signal(str, str)      # (video_path, error_message)
    finished      = Signal()              # Signal dùng cho on_finish (thay thế _noop)


class PipelineThread(threading.Thread):
    """
    Thread chạy pipeline. Tất cả callback về UI đều đi qua Qt signals.
    """

    def __init__(
        self,
        target_fn: Callable,
        signals: PipelineSignals,
        on_finish: Optional[Callable] = None,
        daemon: bool = True
    ):
        super().__init__(daemon=daemon)
        self._target_fn = target_fn
        self.signals = signals
        self._on_finish = on_finish
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()   # Bắt đầu ở trạng thái chạy

    def run(self):
        try:
            self._target_fn()
        except Exception as e:
            sys_log.error(f"[PipelineThread] Crash: {e}")
            import traceback
            sys_log.error(traceback.format_exc())
        finally:
            # Connect TRƯỚC khi emit để callback nhận được signal
            if self._on_finish:
                self.signals.finished.connect(
                    self._on_finish, Qt.ConnectionType.QueuedConnection
                )
            self.signals.finished.emit()
            # Dọn dẹp signal sau khi dùng
            try:
                self.signals.finished.disconnect()
            except Exception:
                pass

    def request_stop(self):
        self._stop_event.set()
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()
        sys_log.info("[PipelineThread] Đã tạm dừng.")

    def resume(self):
        self._pause_event.set()
        sys_log.info("[PipelineThread] Đã tiếp tục.")

    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def wait_if_paused(self):
        """Gọi trong vòng lặp pipeline để hỗ trợ pause/resume."""
        self._pause_event.wait()


class ThreadManager:
    """
    Quản lý tất cả các pipeline threads.
    """

    def __init__(self):
        self._active_threads: list[PipelineThread] = []
        self._lock = threading.Lock()

    def spawn(
        self,
        target_fn: Callable,
        signals: PipelineSignals,
        on_finish: Optional[Callable] = None
    ) -> PipelineThread:
        """Tạo và chạy một pipeline thread mới."""
        t = PipelineThread(target_fn, signals, on_finish)
        with self._lock:
            self._active_threads.append(t)
        t.start()
        sys_log.info(f"[ThreadManager] Thread mới khởi động. Đang chạy: {self.active_count}")
        return t

    def stop_all(self):
        with self._lock:
            for t in self._active_threads:
                t.request_stop()
        sys_log.info("[ThreadManager] Đã yêu cầu dừng toàn bộ threads.")

    def pause_all(self):
        with self._lock:
            for t in self._active_threads:
                t.pause()

    def resume_all(self):
        with self._lock:
            for t in self._active_threads:
                t.resume()

    def cleanup_finished(self):
        with self._lock:
            self._active_threads = [t for t in self._active_threads if t.is_alive()]

    @property
    def active_count(self) -> int:
        self.cleanup_finished()
        return len(self._active_threads)

    @property
    def is_any_running(self) -> bool:
        return self.active_count > 0