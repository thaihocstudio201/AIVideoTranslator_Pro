import sys
import os
import subprocess 
import threading  
import time       
import re
from core.master_pipeline import VideoPipelineEngine # Import động cơ lõi
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QTabWidget, QLineEdit, 
                             QFileDialog, QGroupBox, QRadioButton, QSlider, 
                             QComboBox, QCheckBox, QListWidget, QAbstractItemView, QMessageBox)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from ui.console_widget import SystemConsole
from utils.custom_logger import sys_log

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Video Translator Pro 2026 - Master Dashboard")
        self.resize(1650, 980) 
        
        # Biến điều khiển hệ thống
        self.current_folder = "" 
        self.is_running = False 
        self.api_visible = False 
        self.sub_color_hex = "#FFFF00"

        # Stylesheet chuyên nghiệp (Neon Dark Mode)
        self.setStyleSheet("""
            QMainWindow { background-color: #0b0e14; }
            QWidget { color: #c9d1d9; font-family: Arial; }
            QGroupBox { 
                border: 1px solid #30363d; 
                border-radius: 8px;
                margin-top: 3ex; 
                font-weight: bold; 
                color: #00f2ff; 
            }
            QGroupBox::title { 
                subcontrol-origin: margin; 
                subcontrol-position: top left;
                left: 15px; 
                padding: 0 5px; 
                background-color: #0b0e14;
            }
            QLineEdit, QComboBox, QListWidget { 
                background-color: #161b22; 
                border: 1px solid #30363d; 
                padding: 5px; 
                border-radius: 4px;
            }
            QPushButton { 
                background-color: #21262d; 
                border: 1px solid #30363d; 
                padding: 8px; 
                border-radius: 5px; 
                font-weight: bold;
            }
            QPushButton:hover { background-color: #30363d; border-color: #ff00ff; }
            QTabWidget::pane { border: 1px solid #30363d; background-color: #0b0e14; }
            QTabBar::tab { background-color: #161b22; color: gray; padding: 12px 25px; font-weight: bold; }
            QTabBar::tab:selected { background-color: #ff00ff; color: white; border-bottom: 2px solid white; }
            
            QListWidget::item { padding: 8px; border-bottom: 1px solid #21262d; }
            QListWidget::item:selected { background-color: #1a73e8; color: white; }
            
            QSlider::handle:horizontal { background: #00f2ff; border: 1px solid #fff; width: 14px; margin: -5px 0; border-radius: 7px; }
        """)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.root_tabs = QTabWidget()
        main_layout.addWidget(self.root_tabs)

        self.tab1 = QWidget()
        self.tab2 = QWidget()

        self.root_tabs.addTab(self.tab1, "🚀 TAB 1: ĐIỀU KHIỂN & ĐỘNG CƠ")
        self.root_tabs.addTab(self.tab2, "✂️ TAB 2: XƯỞNG LÁCH BẢN QUYỀN (VISUALS)")

        self.build_tab_1()
        self.build_tab_2()

    # ==========================================
    # XÂY DỰNG TAB 1: ĐIỀU KHIỂN & ĐỘNG CƠ
    # ==========================================
    def build_tab_1(self):
        layout = QHBoxLayout(self.tab1)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(20)

        # --- CỘT TRÁI (30%) ---
        col_left = QVBoxLayout()
        col_left.setSpacing(15)
        
        # 1. Quản lý File I/O
        grp_io = QGroupBox("1. ĐẦU VÀO & ĐẦU RA")
        lo_io = QVBoxLayout(grp_io)
        lo_io.setContentsMargins(15, 25, 15, 15) 
        lo_io.setSpacing(12)
        
        mode_layout = QHBoxLayout()
        self.radio_single = QRadioButton("🎬 1 Video")
        self.radio_batch = QRadioButton("📂 Chạy Hàng loạt")
        self.radio_single.setChecked(True)
        self.radio_single.toggled.connect(self.toggle_input_mode)
        mode_layout.addWidget(self.radio_single)
        mode_layout.addWidget(self.radio_batch)
        lo_io.addLayout(mode_layout)

        in_lo = QHBoxLayout()
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Đường dẫn file hoặc thư mục...")
        btn_input = QPushButton("📂 CHỌN NGUỒN")
        btn_input.setFixedWidth(120)
        btn_input.clicked.connect(self.select_input)
        in_lo.addWidget(self.txt_input)
        in_lo.addWidget(btn_input)
        lo_io.addLayout(in_lo)

        out_lo = QHBoxLayout()
        self.txt_output = QLineEdit()
        self.txt_output.setPlaceholderText("Nơi lưu video hoàn thành...")
        btn_output = QPushButton("💾 NƠI XUẤT")
        btn_output.setFixedWidth(120)
        btn_output.clicked.connect(self.select_output)
        out_lo.addWidget(self.txt_output)
        out_lo.addWidget(btn_output)
        lo_io.addLayout(out_lo)
        col_left.addWidget(grp_io)

        # 2. Mixer
        grp_mixer = QGroupBox("2. CHỈNH NHẠC VIDEO (MIXER)")
        lo_mixer = QVBoxLayout(grp_mixer)
        lo_mixer.setContentsMargins(15, 25, 15, 15)
        lo_mixer.setSpacing(10)
        
        self.sld_ai = QSlider(Qt.Orientation.Horizontal)
        self.sld_ai.setRange(0, 200); self.sld_ai.setValue(120)
        self.sld_bg = QSlider(Qt.Orientation.Horizontal)
        self.sld_bg.setRange(0, 200); self.sld_bg.setValue(30)
        self.sld_orig = QSlider(Qt.Orientation.Horizontal)
        self.sld_orig.setRange(0, 200); self.sld_orig.setValue(5)
        
        lo_mixer.addWidget(QLabel("Giọng AI lồng tiếng (120%):"))
        lo_mixer.addWidget(self.sld_ai)
        lo_mixer.addWidget(QLabel("Nhạc nền & Hiệu ứng (30%):"))
        lo_mixer.addWidget(self.sld_bg)
        lo_mixer.addWidget(QLabel("Giọng nói gốc (5%):"))
        lo_mixer.addWidget(self.sld_orig)
        col_left.addWidget(grp_mixer)

        # 3. [MỚI] Khu vực SETTING bảo mật (Bottom Left)
        self.gb_sec = QGroupBox("⚙️ QUẢN LÝ TÀI NGUYÊN API (MỚI)")
        self.gb_sec.setVisible(False)
        lo_sec = QVBoxLayout(self.gb_sec)
        
        lo_sec.addWidget(QLabel("Danh sách Gemini API Keys (Mỗi dòng 1 Key):"))
        self.txt_api_list = QTextEdit() # Dùng QTextEdit để nhập nhiều dòng
        self.txt_api_list.setPlaceholderText("Paste danh sách API Keys tại đây...")
        self.txt_api_list.setFixedHeight(80)
        self.txt_api_list.setStyleSheet("background-color: #161b22; color: #00f2ff;")
        lo_sec.addWidget(self.txt_api_list)
        
        h_test = QHBoxLayout()
        self.btn_test_api = QPushButton("🔍 KIỂM TRA & LOAD MODELS")
        self.btn_test_api.clicked.connect(self.check_and_load_models)
        
        self.cb_models = QComboBox() # Dropbox chọn Model
        self.cb_models.setPlaceholderText("Đang đợi check...")
        self.cb_models.setMinimumWidth(200)
        
        h_test.addWidget(self.btn_test_api)
        h_test.addWidget(self.cb_models)
        lo_sec.addLayout(h_test)
        
        btn_save = QPushButton("💾 LƯU & KÍCH HOẠT HỆ THỐNG XOAY VÒNG")
        btn_save.clicked.connect(self.save_personal_settings)
        btn_save.setStyleSheet("background-color: #1a73e8; font-weight: bold;")
        lo_sec.addWidget(btn_save)
        
        col1.addWidget(self.gb_sec)

        # --- CỘT GIỮA (30%) ---
        col_mid = QVBoxLayout()
        col_mid.setSpacing(15)
        
        grp_ai = QGroupBox("3. CẤU HÌNH TRÍ TUỆ NHÂN TẠO (AI)")
        lo_ai = QVBoxLayout(grp_ai)
        lo_ai.setContentsMargins(15, 25, 15, 15)
        
        ai_tabs = QTabWidget()
        tab_edge = QWidget()
        lo_edge = QVBoxLayout(tab_edge)
        self.cb_edge_voice = QComboBox()
        self.cb_edge_voice.addItems(["vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural", "en-US-AriaNeural", "en-US-GuyNeural"])
        lo_edge.addWidget(QLabel("Giọng đọc Miễn phí (Edge-TTS):"))
        lo_edge.addWidget(self.cb_edge_voice)
        lo_edge.addStretch()
        
        tab_vip = QWidget()
        lo_vip = QVBoxLayout(tab_vip)
        self.cb_api_type = QComboBox()
        self.cb_api_type.addItems(["Gemini 1.5 Flash (Dịch thuật)", "ElevenLabs (Giọng xịn)"])
        lo_vip.addWidget(QLabel("Nền tảng API VIP:"))
        lo_vip.addWidget(self.cb_api_type)
        lo_vip.addStretch()

        ai_tabs.addTab(tab_edge, "☁️ Cloud TTS (Free)")
        ai_tabs.addTab(tab_vip, "👑 VIP API (Pro)")
        lo_ai.addWidget(ai_tabs)
        col_mid.addWidget(grp_ai)

        self.btn_run = QPushButton("🚀 KHỞI ĐỘNG DUBBING")
        self.btn_run.setStyleSheet("background-color: #ff00ff; color: white; font-weight: bold; font-size: 20px; padding: 20px;")
        self.btn_run.setMinimumHeight(100)
        self.btn_run.clicked.connect(self.test_run_pipeline)
        col_mid.addWidget(self.btn_run)
        col_mid.addStretch()

        # --- CỘT PHẢI (40%) ---
        col_right = QVBoxLayout()
        col_right.setSpacing(10)
        
        preview_container = QWidget()
        preview_container.setStyleSheet("background-color: #000; border: 2px solid #00f2ff;")
        preview_vbox = QVBoxLayout(preview_container)
        preview_vbox.setContentsMargins(2, 2, 2, 2)
        
        self.video_widget = QVideoWidget()
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)
        
        btn_play = QPushButton("▶ PLAY / PAUSE")
        btn_play.clicked.connect(self.toggle_play_video)
        preview_vbox.addWidget(self.video_widget, stretch=1)
        preview_vbox.addWidget(btn_play)
        col_right.addWidget(preview_container, stretch=4)

        col_right.addWidget(QLabel("DANH SÁCH VIDEO TRONG THƯ MỤC:"), stretch=0)
        self.list_videos = QListWidget()
        self.list_videos.itemClicked.connect(self.play_selected_video)
        col_right.addWidget(self.list_videos, stretch=2)

        col_right.addWidget(QLabel("TÁC VỤ LOG CHẠY BÁO CÔNG VIỆC:"), stretch=0)
        self.console = SystemConsole()
        self.console.setMinimumHeight(220)
        col_right.addWidget(self.console, stretch=3)

        layout.addLayout(col_left, stretch=3)
        layout.addLayout(col_mid, stretch=3)
        layout.addLayout(col_right, stretch=4)

    # ==========================================
    # XÂY DỰNG TAB 2: VISUALS (XƯỞNG LÁCH)
    # ==========================================
    def build_tab_2(self):
        layout = QHBoxLayout(self.tab2)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(20)
        
        # Cột 1: Hình ảnh & Phụ đề
        col1 = QVBoxLayout()
        gb_text = QGroupBox("🖼️ HÌNH ẢNH & TIÊU ĐỀ")
        lo_text = QVBoxLayout(gb_text)
        lo_text.setContentsMargins(15, 25, 15, 15)
        lo_text.setSpacing(12)
        
        lo_text.addWidget(QPushButton("CHỌN MÀU SUB"))
        self.cb_font = QComboBox()
        self.cb_font.addItems(["Arial", "Impact", "Tahoma", "Verdana"])
        lo_text.addWidget(QLabel("Font chữ Phụ đề:"))
        lo_text.addWidget(self.cb_font)
        lo_text.addWidget(QLabel("Cỡ chữ Sub:"))
        lo_text.addWidget(QSlider(Qt.Orientation.Horizontal))
        lo_text.addWidget(QCheckBox("Bật Hộp Mờ Che Sub Cũ"))
        lo_text.addWidget(QLineEdit(placeholderText="Tiêu đề Viền Trên..."))
        lo_text.addWidget(QLineEdit(placeholderText="Tiêu đề Viền Dưới..."))
        col1.addWidget(gb_text)
        col1.addStretch()

        # Cột 2: Lách bản quyền
        col2 = QVBoxLayout()
        gb_fx = QGroupBox("⚙️ LÁCH BẢN QUYỀN CHUYÊN SÂU")
        lo_fx = QVBoxLayout(gb_fx)
        lo_fx.setContentsMargins(15, 25, 15, 15)
        lo_fx.setSpacing(12)
        
        lo_fx.addWidget(QCheckBox("Tẩy trắng thông tin EXIF (Metadata)"))
        lo_fx.addWidget(QCheckBox("Băm lại mã hiệu MD5 chống quét"))
        self.cb_fps = QComboBox()
        self.cb_fps.addItems(["Gốc", "24 fps", "30 fps", "60 fps"])
        lo_fx.addWidget(QLabel("Ép khung hình FPS:"))
        lo_fx.addWidget(self.cb_fps)
        self.cb_pan = QComboBox()
        self.cb_pan.addItems(["Tắt", "Lia máy (Pan x1)", "Lia máy (Pan x2)"])
        lo_fx.addWidget(QLabel("Lia máy (Bản quyền nặng):"))
        lo_fx.addWidget(self.cb_pan)
        self.cb_color = QComboBox()
        self.cb_color.addItems(["Gốc", "Rạp phim", "Đậm đà", "Trắng đen"])
        lo_fx.addWidget(QLabel("Bộ lọc màu (Filter):"))
        lo_fx.addWidget(self.cb_color)
        col2.addWidget(gb_fx)
        col2.addStretch()

        # Cột 3: Extra & Render
        col3 = QVBoxLayout()
        gb_extra = QGroupBox("🔊 ÂM THANH & RENDER")
        lo_extra = QVBoxLayout(gb_extra)
        lo_extra.setContentsMargins(15, 25, 15, 15)
        lo_extra.setSpacing(12)
        
        lo_extra.addWidget(QPushButton("📂 Chọn Video Intro"))
        lo_extra.addWidget(QPushButton("📂 Chọn Video Outro"))
        lo_extra.addWidget(QPushButton("📂 CHÈN LOGO KÉO THẢ"))
        lo_extra.addWidget(QLabel("Tone Nhạc Nền (Pitch):"))
        lo_extra.addWidget(QSlider(Qt.Orientation.Horizontal))
        self.cb_res = QComboBox()
        self.cb_res.addItems(["Gốc", "1080p", "720p", "360p"])
        lo_extra.addWidget(QLabel("Chất lượng Render:"))
        lo_extra.addWidget(self.cb_res)
        
        btn_save_fx = QPushButton("💾 LƯU CẤU HÌNH LÁCH")
        btn_save_fx.setStyleSheet("background-color: #1a73e8; padding: 15px;")
        lo_extra.addWidget(btn_save_fx)
        col3.addWidget(gb_extra)
        col3.addStretch()

        layout.addLayout(col1)
        layout.addLayout(col2)
        layout.addLayout(col3)

    # ==========================================
    # LOGIC CÀI ĐẶT & BẢO MẬT
    # ==========================================
    def toggle_settings_panel(self):
        """Bật/Hiện bảng cài đặt API"""
        self.grp_security.setVisible(not self.grp_security.isVisible())

    def toggle_api_visibility(self):
        """Ẩn/Hiện text API Key"""
        if self.api_visible:
            self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_toggle_api.setText("👁️")
        else:
            self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_toggle_api.setText("🕶️")
        self.api_visible = not self.api_visible

    def save_personal_settings(self):
        """Lưu API Key (Mô phỏng)"""
        sys_log.info("🔐 Đã mã hóa và lưu trữ API Key cá nhân thành công!")
        self.grp_security.setVisible(False)

    # ==========================================
    # LOGIC ĐIỀU KHIỂN VIDEO & FILE
    # ==========================================
    def toggle_input_mode(self):
        self.list_videos.clear()
        if self.radio_single.isChecked():
            self.txt_input.setPlaceholderText("Đường dẫn 1 file video gốc...")
        else:
            self.txt_input.setPlaceholderText("Đường dẫn thư mục chứa nhiều video...")

    def toggle_play_video(self):
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def select_input(self):
        if self.radio_single.isChecked():
            path, _ = QFileDialog.getOpenFileName(self, "Chọn Video", "", "Video Files (*.mp4 *.mkv *.avi)")
            if path:
                self.txt_input.setText(path)
                self.current_folder = os.path.dirname(path)
                self.list_videos.clear()
                self.list_videos.addItem(os.path.basename(path))
                self.media_player.setSource(QUrl.fromLocalFile(path))
                sys_log.info(f"Đã nạp file: {os.path.basename(path)}")
        else:
            path = QFileDialog.getExistingDirectory(self, "Chọn Thư mục")
            if path:
                self.txt_input.setText(path)
                self.current_folder = path
                self.list_videos.clear()
                valid_exts = ('.mp4', '.mkv', '.avi', '.mov')
                vids = [f for f in os.listdir(path) if f.lower().endswith(valid_exts)]
                self.list_videos.addItems(vids)
                sys_log.info(f"Đã nạp thư mục Batch chứa {len(vids)} video.")

    def select_output(self):
        path = QFileDialog.getExistingDirectory(self, "Chọn Nơi xuất")
        if path:
            self.txt_output.setText(path)
            sys_log.info(f"Đã đặt thư mục đầu ra: {path}")

    def play_selected_video(self, item):
        if self.current_folder:
            filepath = os.path.join(self.current_folder, item.text())
            self.media_player.setSource(QUrl.fromLocalFile(filepath))
            sys_log.info(f"Đang xem trước: {item.text()}")

    # ==========================================
    # QUY TRÌNH RENDER (MASTER PIPELINE)
    # ==========================================
    def test_run_pipeline(self):
        """Khởi động Động cơ Lồng tiếng"""
        if self.is_running:
            QMessageBox.warning(self, "Hệ thống bận", "Đại ca ơi, máy đang bận Render! Đợi xíu nhé.")
            return

        out_dir = self.txt_output.text().strip()
        if not out_dir:
            sys_log.warning("Chưa chọn Nơi xuất Video!")
            return

        videos = []
        if self.radio_single.isChecked():
            if self.txt_input.text(): videos.append(self.txt_input.text())
        else:
            if self.txt_input.text():
                path = self.txt_input.text()
                videos = [os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(('.mp4', '.mkv', '.avi'))]

        if not videos:
            sys_log.error("Không tìm thấy video nào để xử lý!")
            return

        # Gom cấu hình
        config = {
            "ai_voice": self.cb_edge_voice.currentText(),
            "api_key": self.txt_api_key.text().strip(),
            "vol_ai": self.sld_ai.value(),
            "vol_bg": self.sld_bg.value(),
            "vol_orig": self.sld_orig.value()
        }

        # Khóa nút và khởi động Core
        self.is_running = True
        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ ĐANG XỬ LÝ (DUBBING...)")

        self.engine = VideoPipelineEngine(videos, out_dir, config, self.on_pipeline_done)
        self.engine.start()

    def on_pipeline_done(self):
        """Khi Core báo xong"""
        self.is_running = False
        self.btn_run.setEnabled(True)
        self.btn_run.setText("🚀 KHỞI ĐỘNG DUBBING")
        sys_log.info("🎉 CHIẾN DỊCH HOÀN TẤT!")
    
    def check_and_load_models(self):
        """Hàm test API và lấy danh sách Model khả dụng"""
        raw_keys = self.txt_api_list.toPlainText().strip().split('\n')
        first_key = raw_keys[0].strip() if raw_keys else ""
        
        if not first_key:
            sys_log.warning("Đại ca chưa nhập Key nào để test!")
            return

        self.btn_test_api.setText("⌛ Đang check...")
        self.cb_models.clear()
        
        # Gọi AIService để lấy danh sách model
        available_models = self.ai.get_available_models(first_key)
        
        if available_models:
            self.cb_models.addItems(available_models)
            sys_log.info(f"✅ Test thành công! Tìm thấy {len(available_models)} models khả dụng.")
            self.btn_test_api.setText("🔍 KIỂM TRA LẠI")
        else:
            sys_log.error("❌ Key không hợp lệ hoặc không có quyền truy cập model nào.")
            self.btn_test_api.setText("🔍 THỬ LẠI")