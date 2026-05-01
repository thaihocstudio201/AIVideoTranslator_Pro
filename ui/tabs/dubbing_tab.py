import os
import json
import requests
import google.generativeai as genai
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton,
    QLineEdit, QPushButton, QLabel, QSlider, QTextEdit, QComboBox,
    QMessageBox, QListWidget, QFrame, QAbstractItemView
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from ui.console_widget import SystemConsole
from utils.custom_logger import sys_log


class DubbingTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.valid_apis = []
        self.media_player = QMediaPlayer()
        self.video_widget = QVideoWidget()
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(20)

        col_left = QVBoxLayout()

        # 1. Đầu vào & Đầu ra (giữ nguyên)
        grp_io = QGroupBox("1. ĐẦU VÀO & ĐẦU RA")
        lo_io = QVBoxLayout(grp_io)
        lo_io.setContentsMargins(15, 25, 15, 15)

        mode_lo = QHBoxLayout()
        self.radio_single = QRadioButton("🎬 1 Video")
        self.radio_batch = QRadioButton("📂 Hàng loạt")
        self.radio_single.setChecked(True)
        mode_lo.addWidget(self.radio_single)
        mode_lo.addWidget(self.radio_batch)
        lo_io.addLayout(mode_lo)

        h_in = QHBoxLayout()
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Đường dẫn nguồn...")
        btn_in = QPushButton("📂 CHỌN")
        btn_in.clicked.connect(self.main.select_input)
        h_in.addWidget(self.txt_input)
        h_in.addWidget(btn_in)
        lo_io.addLayout(h_in)

        h_out = QHBoxLayout()
        self.txt_output = QLineEdit()
        self.txt_output.setPlaceholderText("Nơi xuất...")
        btn_out = QPushButton("💾 XUẤT")
        btn_out.clicked.connect(self.main.select_output)
        h_out.addWidget(self.txt_output)
        h_out.addWidget(btn_out)
        lo_io.addLayout(h_out)
        col_left.addWidget(grp_io)

        # 2. Mixer (giữ nguyên)
        grp_mixer = QGroupBox("2. CHỈNH NHẠC VIDEO (MIXER)")
        lo_mix = QVBoxLayout(grp_mixer)
        lo_mix.setContentsMargins(15, 25, 15, 15)

        self.lbl_ai = QLabel("Giọng AI (120%):")
        lo_mix.addWidget(self.lbl_ai)
        self.sld_ai = QSlider(Qt.Orientation.Horizontal)
        self.sld_ai.setRange(0, 200)
        self.sld_ai.setValue(120)
        self.sld_ai.valueChanged.connect(lambda v: self.lbl_ai.setText(f"Giọng AI ({v}%):"))
        lo_mix.addWidget(self.sld_ai)

        self.lbl_bg = QLabel("Nhạc nền (30%):")
        lo_mix.addWidget(self.lbl_bg)
        self.sld_bg = QSlider(Qt.Orientation.Horizontal)
        self.sld_bg.setRange(0, 200)
        self.sld_bg.setValue(30)
        self.sld_bg.valueChanged.connect(lambda v: self.lbl_bg.setText(f"Nhạc nền ({v}%):"))
        lo_mix.addWidget(self.sld_bg)

        self.lbl_orig = QLabel("Giọng gốc (5%):")
        lo_mix.addWidget(self.lbl_orig)
        self.sld_orig = QSlider(Qt.Orientation.Horizontal)
        self.sld_orig.setRange(0, 200)
        self.sld_orig.setValue(5)
        self.sld_orig.valueChanged.connect(lambda v: self.lbl_orig.setText(f"Giọng gốc ({v}%):"))
        lo_mix.addWidget(self.sld_orig)

        col_left.addWidget(grp_mixer)

        # 3. Ngôn ngữ dịch & Voice
        group_lang = QGroupBox("🌐 NGÔN NGỮ DỊCH & VOICE")
        lang_layout = QVBoxLayout(group_lang)
        lang_layout.setContentsMargins(15, 25, 15, 15)

        h_lang = QHBoxLayout()
        self.lbl_source = QLabel("Ngôn ngữ gốc:")
        self.cb_source_lang = QComboBox()
        self.cb_source_lang.addItems(["Chinese", "English", "Japanese", "Korean"])
        self.cb_source_lang.setCurrentText("Chinese")

        self.lbl_target = QLabel("Dịch sang:")
        self.cb_target_lang = QComboBox()
        self.cb_target_lang.addItems(["Vietnamese", "English", "Japanese", "Korean", "Thai"])
        self.cb_target_lang.setCurrentText("Vietnamese")

        h_lang.addWidget(self.lbl_source)
        h_lang.addWidget(self.cb_source_lang)
        h_lang.addWidget(self.lbl_target)
        h_lang.addWidget(self.cb_target_lang)
        lang_layout.addLayout(h_lang)
        col_left.addWidget(group_lang)

        # 4. NỀN TẢNG TẠO VOICE (ĐÃ THÊM NÚT KIỂM TRA)
        grp_voice = QGroupBox("🎙️ NỀN TẢNG TẠO VOICE")
        lo_voice = QVBoxLayout(grp_voice)
        lo_voice.setContentsMargins(15, 25, 15, 15)

        h_voice_mode = QHBoxLayout()
        self.radio_voice_api = QRadioButton("Edge-TTS (API)")
        self.radio_voice_local = QRadioButton("Local TTS")
        self.radio_voice_api.setChecked(True)
        self.radio_voice_api.toggled.connect(self.toggle_voice_platform)
        h_voice_mode.addWidget(self.radio_voice_api)
        h_voice_mode.addWidget(self.radio_voice_local)
        lo_voice.addLayout(h_voice_mode)

        self.cb_voice_model = QComboBox()
        self.cb_voice_model.addItems(["vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural", "piper-vais1000-medium"])
        lo_voice.addWidget(QLabel("Model Voice:"))
        lo_voice.addWidget(self.cb_voice_model)

        # NÚT KIỂM TRA MODEL VOICE LOCAL
        btn_check_voice = QPushButton("🔍 Kiểm tra Model Voice Local")
        btn_check_voice.clicked.connect(self.check_voice_models)
        lo_voice.addWidget(btn_check_voice)

        # Nút lưu voice
        btn_save_voice = QPushButton("💾 Lưu Cấu Hình Voice")
        btn_save_voice.clicked.connect(self.main.save_personal_settings)
        btn_save_voice.setStyleSheet("background-color: #00ff88; color: black; font-weight: bold;")
        lo_voice.addWidget(btn_save_voice)

        col_left.addWidget(grp_voice)

        # 5. Nền tảng Dịch Thuật (giữ nguyên)
        self.gb_sec = QGroupBox("⚙️ NỀN TẢNG DỊCH THUẬT")
        lo_sec = QVBoxLayout(self.gb_sec)
        lo_sec.setContentsMargins(15, 25, 15, 15)

        h_platform = QHBoxLayout()
        self.radio_gemini = QRadioButton("🌐 Gemini API")
        self.radio_ollama = QRadioButton("🖥️ Ollama Local")
        self.radio_gemini.setChecked(True)
        self.radio_gemini.toggled.connect(self.toggle_ai_platform)
        h_platform.addWidget(self.radio_gemini)
        h_platform.addWidget(self.radio_ollama)
        lo_sec.addLayout(h_platform)

        self.wdg_gemini = QWidget()
        lo_g = QVBoxLayout(self.wdg_gemini)
        lo_g.addWidget(QLabel("Danh sách API Keys (mỗi dòng 1 key):"))
        self.txt_api_list = QTextEdit()
        self.txt_api_list.setFixedHeight(80)
        self.txt_api_list.setPlaceholderText("Paste API Keys tại đây...")
        lo_g.addWidget(self.txt_api_list)
        lo_sec.addWidget(self.wdg_gemini)

        h_test = QHBoxLayout()
        self.btn_test = QPushButton("🔍 KIỂM TRA & LOAD MODELS")
        self.btn_test.clicked.connect(self.check_and_load_models)
        self.cb_models = QComboBox()
        self.cb_models.setMinimumWidth(280)
        h_test.addWidget(self.btn_test)
        h_test.addWidget(self.cb_models)
        lo_sec.addLayout(h_test)

        btn_save = QPushButton("💾 LƯU CẤU HÌNH AI / OLLAMA")
        btn_save.clicked.connect(self.main.save_personal_settings)
        btn_save.setStyleSheet("background-color: #00ff88; color: black; font-weight: bold;")
        lo_sec.addWidget(btn_save)

        col_left.addWidget(self.gb_sec)
        col_left.addStretch()

        # Cột phải (giữ nguyên)
        col_right = QVBoxLayout()

        pv_box = QFrame()
        pv_box.setStyleSheet("background:#000; border:2px solid #00f2ff;")
        lo_pv = QVBoxLayout(pv_box)
        self.media_player.setVideoOutput(self.video_widget)
        lo_pv.addWidget(self.video_widget)
        col_right.addWidget(pv_box, 4)

        btn_play = QPushButton("▶ PLAY / PAUSE")
        btn_play.clicked.connect(self.main.toggle_play_video)
        col_right.addWidget(btn_play)

        self.list_videos = QListWidget()
        self.list_videos.itemClicked.connect(self.main.play_selected_video)
        col_right.addWidget(QLabel("DANH SÁCH VIDEO:"))
        col_right.addWidget(self.list_videos, 2)

        self.console = SystemConsole()
        self.console.setMinimumHeight(180)
        col_right.addWidget(self.console, 3)

        self.btn_run = QPushButton("🚀 KHỞI ĐỘNG DUBBING")
        self.btn_run.setMinimumHeight(80)
        self.btn_run.setStyleSheet("background:#ff00ff; color: white; font-size:18px; font-weight:bold;")
        self.btn_run.clicked.connect(self.main.start_pipeline)
        col_right.addWidget(self.btn_run)

        layout.addLayout(col_left, 3)
        layout.addLayout(col_right, 4)

    def toggle_voice_platform(self):
        if self.radio_voice_api.isChecked():
            self.cb_voice_model.clear()
            self.cb_voice_model.addItems(["vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"])
        else:
            self.cb_voice_model.clear()
            self.cb_voice_model.addItems(["piper-vais1000-medium"])

    def check_voice_models(self):
        """Nút kiểm tra model voice local"""
        if self.radio_voice_local.isChecked():
            self.cb_voice_model.clear()
            self.cb_voice_model.addItems(["piper-vais1000-medium", "local-xtts-v2"])
            sys_log.info("✅ Đã load model Voice Local")
            QMessageBox.information(self, "Thành công", "Đã load model Voice Local!")
        else:
            QMessageBox.information(self, "Edge-TTS", "Edge-TTS dùng model mặc định, không cần quét.")

    # Các hàm còn lại (toggle_ai_platform, check_and_load_models, start_pipeline) giữ nguyên như cũ
    def toggle_ai_platform(self):
        is_gemini = self.radio_gemini.isChecked()
        self.wdg_gemini.setVisible(is_gemini)
        self.cb_models.clear()

        if is_gemini:
            self.btn_test.setText("🔍 KIỂM TRA & LOAD GEMINI")
            self.btn_test.setStyleSheet("background-color: #1a73e8; color: white;")
        else:
            self.btn_test.setText("🔍 QUÉT MODEL OLLAMA LOCAL")
            self.btn_test.setStyleSheet("background-color: #ff5500; color: white;")

    def check_and_load_models(self):
        self.cb_models.clear()
        if self.radio_ollama.isChecked():
            self.btn_test.setText("⌛ Đang quét Ollama...")
            try:
                response = requests.get("http://localhost:11434/api/tags", timeout=5)
                if response.status_code == 200:
                    models = [m['name'] for m in response.json().get('models', [])]
                    if models:
                        self.cb_models.addItems(models)
                        sys_log.info(f"✅ Đã kết nối Ollama Local. Tìm thấy {len(models)} models.")
                        QMessageBox.information(self, "Ollama OK", f"Tìm thấy {len(models)} model offline!")
                    else:
                        QMessageBox.warning(self, "Trống", "Ollama đang chạy nhưng chưa có model nào!")
                else:
                    QMessageBox.warning(self, "Lỗi", f"Ollama trả về lỗi: {response.status_code}")
            except requests.exceptions.ConnectionError:
                sys_log.error("Không thể kết nối Ollama.")
                QMessageBox.critical(self, "Lỗi", "Không tìm thấy Ollama Local.\nBạn đã chạy 'ollama serve' chưa?")
            except Exception as e:
                sys_log.error(f"Lỗi quét Ollama: {e}")
            self.btn_test.setText("🔍 QUÉT MODEL OLLAMA LOCAL")
            return

        # Gemini logic (giữ nguyên)
        raw_text = self.txt_api_list.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Chưa có key", "Vui lòng nhập ít nhất 1 API Key Gemini!")
            return

        keys = [line.strip() for line in raw_text.split('\n') if line.strip()]
        self.valid_apis = []
        all_models = set()
        self.btn_test.setText("⌛ Checking...")

        for i, key in enumerate(keys, 1):
            try:
                genai.configure(api_key=key)
                models = [m.name.split('/')[-1] for m in genai.list_models() if 'gemini-2' in m.name.lower()]
                if models:
                    self.valid_apis.append({"key": key, "models": models})
                    for m in models:
                        all_models.add(m)
                    sys_log.info(f"✅ Key #{i} hợp lệ")
            except Exception as e:
                sys_log.error(f"Key #{i} lỗi: {e}")

        for model in sorted(all_models):
            self.cb_models.addItem(model)

        if self.valid_apis:
            QMessageBox.information(self, "Thành công", f"Đã load {len(all_models)} model Gemini 2.0+.")
        else:
            QMessageBox.critical(self, "Lỗi", "Không có API Key nào hợp lệ.")

        self.btn_test.setText("🔍 KIỂM TRA & LOAD GEMINI")

    def start_pipeline(self):
        self.main.start_pipeline()