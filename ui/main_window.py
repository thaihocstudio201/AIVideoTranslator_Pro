import sys
import os

# ====================== FIX PYLANCE - BUỘC PYLANCE NHẬN CORE ======================
# Đường dẫn tuyệt đối đến thư mục gốc dự án
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Thêm cả thư mục core trực tiếp để Pylance chắc chắn nhận ra
core_path = os.path.join(project_root, "core")
if core_path not in sys.path:
    sys.path.insert(0, core_path)

import json
from pathlib import Path
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, InvalidArgument, PermissionDenied

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QTabWidget,
    QMessageBox, QColorDialog, QLabel, QFileDialog
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from ui.tabs.dubbing_tab import DubbingTab
from ui.tabs.visuals_tab import VisualsTab
from ui.style_sheets import MAIN_STYLE

# Import VideoPipelineEngine sau khi đã thêm đầy đủ sys.path
from core.master_pipeline import VideoPipelineEngine
from utils.custom_logger import sys_log


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Video Translator Pro 2026 - Master Dashboard")
        self.resize(1680, 980)
        self.setStyleSheet(MAIN_STYLE)

        self.current_folder = ""
        self.is_running = False
        self.sub_color_hex = "#FFFF00"
        self.valid_apis = []
        self.selected_model = None

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.root_tabs = QTabWidget()
        main_layout.addWidget(self.root_tabs)

        self.tab_dubbing = DubbingTab(self)
        self.tab_visuals = VisualsTab(self)

        self.root_tabs.addTab(self.tab_dubbing, "🚀 TAB 1: ĐIỀU KHIỂN & ĐỘNG CƠ")
        self.root_tabs.addTab(self.tab_visuals, "✂️ TAB 2: XƯỞNG LÁCH BẢN QUYỀN")

        sys_log.info("✅ MainWindow đã khởi tạo thành công.")

    # ===================================================================
    # CALLBACK TỪ DUBBING TAB (giữ nguyên như bạn có)
    # ===================================================================
    def select_input(self):
        if self.tab_dubbing.radio_single.isChecked():
            path, _ = QFileDialog.getOpenFileName(self, "Chọn Video", "", "Video Files (*.mp4 *.mkv *.avi *.mov)")
            if path:
                self.tab_dubbing.txt_input.setText(path)
                self.current_folder = os.path.dirname(path)
                self.tab_dubbing.list_videos.clear()
                self.tab_dubbing.list_videos.addItem(os.path.basename(path))
                self.tab_dubbing.media_player.setSource(QUrl.fromLocalFile(path))
                sys_log.info(f"Đã chọn file: {os.path.basename(path)}")
        else:
            path = QFileDialog.getExistingDirectory(self, "Chọn Thư mục")
            if path:
                self.tab_dubbing.txt_input.setText(path)
                self.current_folder = path
                self.tab_dubbing.list_videos.clear()
                valid_exts = ('.mp4', '.mkv', '.avi', '.mov')
                vids = [f for f in os.listdir(path) if f.lower().endswith(valid_exts)]
                self.tab_dubbing.list_videos.addItems(vids)
                sys_log.info(f"Đã chọn thư mục chứa {len(vids)} video.")

    def select_output(self):
        path = QFileDialog.getExistingDirectory(self, "Chọn Nơi Xuất")
        if path:
            self.tab_dubbing.txt_output.setText(path)
            sys_log.info(f"Đã chọn thư mục đầu ra: {path}")

    def toggle_play_video(self):
        if self.tab_dubbing.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.tab_dubbing.media_player.pause()
        else:
            self.tab_dubbing.media_player.play()

    def play_selected_video(self, item):
        if self.current_folder:
            filepath = os.path.join(self.current_folder, item.text())
            self.tab_dubbing.media_player.setSource(QUrl.fromLocalFile(filepath))
            sys_log.info(f"Đang xem trước: {item.text()}")

    def choose_sub_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.sub_color_hex = color.name()
            sys_log.info(f"Đã đổi màu phụ đề: {self.sub_color_hex}")

    def save_personal_settings(self):
        platform = "ollama" if self.tab_dubbing.radio_ollama.isChecked() else "gemini"
        self.selected_model = self.tab_dubbing.cb_models.currentText()

        config_dir = Path("config")
        config_dir.mkdir(exist_ok=True)
        config = {
            "ai_platform": platform,
            "default_model": self.selected_model,
            "target_lang": self.tab_dubbing.cb_target_lang.currentText()
        }
        with open(config_dir / "api_config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        sys_log.info(f"💾 Đã lưu cấu hình: {platform.upper()} - Model: {self.selected_model}")
        QMessageBox.information(self, "Lưu thành công", f"Đã lưu model: {self.selected_model}")

    def start_pipeline(self):
        if self.is_running:
            QMessageBox.warning(self, "Đang chạy", "Hệ thống đang xử lý, vui lòng chờ!")
            return

        out_dir = self.tab_dubbing.txt_output.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng chọn thư mục đầu ra!")
            return

        videos = []
        if self.tab_dubbing.radio_single.isChecked():
            path = self.tab_dubbing.txt_input.text().strip()
            if path and os.path.isfile(path):
                videos.append(path)
        else:
            folder = self.tab_dubbing.txt_input.text().strip()
            if folder and os.path.isdir(folder):
                valid_exts = ('.mp4', '.mkv', '.avi', '.mov')
                videos = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(valid_exts)]

        if not videos:
            QMessageBox.warning(self, "Không có video", "Không tìm thấy video nào!")
            return

        config = {
            "ai_platform": "ollama" if self.tab_dubbing.radio_ollama.isChecked() else "gemini",
            "target_lang": self.tab_dubbing.cb_target_lang.currentText(),
            "source_lang": self.tab_dubbing.cb_source_lang.currentText(),
            "default_model": self.tab_dubbing.cb_models.currentText() or "qwen2.5:14b",
            "vol_ai": self.tab_dubbing.sld_ai.value(),
            "vol_bg": self.tab_dubbing.sld_bg.value(),
            "vol_orig": self.tab_dubbing.sld_orig.value(),
        }

        if config["ai_platform"] == "gemini" and self.valid_apis:
            config["api_keys"] = [api["key"] for api in self.valid_apis]

        self.is_running = True
        self.tab_dubbing.btn_run.setEnabled(False)
        self.tab_dubbing.btn_run.setText("⏳ ĐANG XỬ LÝ...")

        try:
            self.engine = VideoPipelineEngine(videos, out_dir, config, self.on_pipeline_done)
            self.engine.start()
            sys_log.info(f"🚀 Khởi động dubbing: {len(videos)} video")
        except Exception as e:
            sys_log.error(f"Lỗi khởi động pipeline: {e}")
            self.on_pipeline_done()

    def on_pipeline_done(self):
        self.is_running = False
        if hasattr(self.tab_dubbing, 'btn_run'):
            self.tab_dubbing.btn_run.setEnabled(True)
            self.tab_dubbing.btn_run.setText("🚀 KHỞI ĐỘNG DUBBING")
        sys_log.info("🎉 HOÀN TẤT TOÀN BỘ CHIẾN DỊCH!")


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())