"""
thread_manager.py — Kept for future use.
The pipeline currently uses threading.Thread directly in master_pipeline.py.
PipelineSignals is re-exported here for convenience if needed by UI components.
"""

from PySide6.QtCore import QObject, Signal


class PipelineSignals(QObject):
    """Các signal dùng để giao tiếp thread-safe giữa worker và UI thread."""

    log_message = Signal(str, str)   # (level, message)
    progress    = Signal(int, str)   # (percent, stage_label)
    video_done  = Signal(str, bool)  # (video_path, success)
    all_done    = Signal()
    error_pause = Signal(str, str)   # (video_path, error_message)
    finished    = Signal()
