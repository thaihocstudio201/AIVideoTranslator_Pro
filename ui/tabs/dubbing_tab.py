"""
ui/tabs/dubbing_tab.py
FULL CODE - ĐÃ PHỤC HỒI TOÀN BỘ + THÊM CHECKBOX DEMUCS
"""
import os
import json
import requests
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton,
    QLineEdit, QPushButton, QLabel, QSlider, QTextEdit, QComboBox,
    QMessageBox, QListWidget, QListWidgetItem, QFileDialog, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont

from ui.console_widget import SystemConsole
from utils.custom_logger import sys_log


# ── Thread load VieNeu (tránh block UI) ────────────────────────
class VoiceLoaderThread(QThread):
    done = Signal(list, dict)  # preset_list, profiles

    def run(self):
        try:
            from services.voice_service import VoiceService
            svc = VoiceService()
            presets  = svc.list_voices()
            profiles = svc.list_profiles()
            self.done.emit(presets, profiles)
        except Exception as e:
            sys_log.error(f"VoiceLoaderThread lỗi: {e}")
            self.done.emit([], {})


class _ProfileSaverThread(QThread):
    """Lưu clone profile trên background thread để không block UI."""
    done = Signal(bool, str)  # (success, name)

    def __init__(self, name: str, wav_path: str):
        super().__init__()
        self._name = name
        self._wav_path = wav_path

    def run(self):
        try:
            from services.voice_service import VoiceService
            ok = VoiceService().save_clone_profile(self._name, self._wav_path)
            self.done.emit(ok, self._name)
        except Exception as e:
            sys_log.error(f"ProfileSaverThread lỗi: {e}")
            self.done.emit(False, self._name)


class _ProfileDeleterThread(QThread):
    """Xóa clone profile trên background thread để không block UI."""
    done = Signal(bool, str)  # (success, name)

    def __init__(self, name: str):
        super().__init__()
        self._name = name

    def run(self):
        try:
            from services.voice_service import VoiceService
            VoiceService().delete_profile(self._name)
            self.done.emit(True, self._name)
        except Exception as e:
            sys_log.error(f"ProfileDeleterThread lỗi: {e}")
            self.done.emit(False, self._name)


class DubbingTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main        = main_window
        self.valid_apis  = []

        # Trạng thái voice
        self._voice_presets: list = []
        self._voice_profiles: dict = {}
        self._clone_wav_path: str = ""

        self.init_ui()
        self._load_voices_async()

    @property
    def media_player(self):
        return self.main.preview_panel.media_player

    # ═══════════════════════════════════════════════════════════
    # INIT UI
    # ═══════════════════════════════════════════════════════════
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(20)

        col_left  = QVBoxLayout()
        col_right = QVBoxLayout()

        # ── 1. Đầu vào & Đầu ra ─────────────────────────────
        grp_io = QGroupBox("1. ĐẦU VÀO & ĐẦU RA")
        lo_io  = QVBoxLayout(grp_io)
        lo_io.setContentsMargins(15, 25, 15, 15)

        mode_lo = QHBoxLayout()
        self.radio_single = QRadioButton("🎬 1 Video")
        self.radio_batch  = QRadioButton("📂 Hàng loạt")
        self.radio_single.setChecked(True)
        mode_lo.addWidget(self.radio_single)
        mode_lo.addWidget(self.radio_batch)
        lo_io.addLayout(mode_lo)

        h_in = QHBoxLayout()
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Đường dẫn nguồn...")
        btn_in = QPushButton("📂 CHỌN")
        btn_in.clicked.connect(self.main.select_input)
        h_in.addWidget(self.txt_input); h_in.addWidget(btn_in)
        lo_io.addLayout(h_in)

        h_out = QHBoxLayout()
        self.txt_output = QLineEdit()
        self.txt_output.setPlaceholderText("Nơi xuất...")
        btn_out = QPushButton("💾 XUẤT")
        btn_out.clicked.connect(self.main.select_output)
        h_out.addWidget(self.txt_output); h_out.addWidget(btn_out)
        lo_io.addLayout(h_out)
        col_left.addWidget(grp_io)

        # ── 2. Mixer + CHECKBOX DEMUCS ───────────────────────
        grp_mixer = QGroupBox("2. CHỈNH NHẠC VIDEO (MIXER)")
        lo_mix = QVBoxLayout(grp_mixer)
        lo_mix.setContentsMargins(15, 25, 15, 15)

        self.lbl_ai = QLabel("Giọng AI (120%):")
        self.sld_ai = QSlider(Qt.Orientation.Horizontal)
        self.sld_ai.setRange(0, 200); self.sld_ai.setValue(120)
        self.sld_ai.valueChanged.connect(lambda v: self.lbl_ai.setText(f"Giọng AI ({v}%):"))
        lo_mix.addWidget(self.lbl_ai); lo_mix.addWidget(self.sld_ai)

        self.lbl_bg = QLabel("Nhạc nền (30%):")
        self.sld_bg = QSlider(Qt.Orientation.Horizontal)
        self.sld_bg.setRange(0, 200); self.sld_bg.setValue(30)
        self.sld_bg.valueChanged.connect(lambda v: self.lbl_bg.setText(f"Nhạc nền ({v}%):"))
        lo_mix.addWidget(self.lbl_bg); lo_mix.addWidget(self.sld_bg)

        self.lbl_orig = QLabel("Giọng gốc (5%):")
        self.sld_orig = QSlider(Qt.Orientation.Horizontal)
        self.sld_orig.setRange(0, 200); self.sld_orig.setValue(5)
        self.sld_orig.valueChanged.connect(lambda v: self.lbl_orig.setText(f"Giọng gốc ({v}%):"))
        lo_mix.addWidget(self.lbl_orig); lo_mix.addWidget(self.sld_orig)

        # CHECKBOX ĐÃ THÊM ĐÚNG VỊ TRÍ
        self.chk_advanced_mix = QCheckBox("🎛️ Tách nhạc nền nâng cao (Demucs)")
        self.chk_advanced_mix.setChecked(True)
        self.chk_advanced_mix.setStyleSheet("color: #00f2ff; font-weight: bold;")
        lo_mix.addWidget(self.chk_advanced_mix)

        col_left.addWidget(grp_mixer)

        # ── 3. Ngôn ngữ ──────────────────────────────────────
        grp_lang = QGroupBox("🌐 NGÔN NGỮ DỊCH")
        lo_lang = QVBoxLayout(grp_lang)
        lo_lang.setContentsMargins(15, 25, 15, 15)

        h_lang = QHBoxLayout()
        self.cb_source_lang = QComboBox()
        self.cb_source_lang.addItems(["Chinese", "English", "Japanese", "Korean"])
        self.cb_target_lang = QComboBox()
        self.cb_target_lang.addItems(["Vietnamese", "English", "Japanese", "Korean", "Thai"])
        self.cb_target_lang.setCurrentText("Vietnamese")
        h_lang.addWidget(QLabel("Nguồn:")); h_lang.addWidget(self.cb_source_lang)
        h_lang.addWidget(QLabel("Dịch sang:")); h_lang.addWidget(self.cb_target_lang)
        lo_lang.addLayout(h_lang)
        col_left.addWidget(grp_lang)

        # ── 4. NỀN TẢNG TẠO VOICE (VieNeu-TTS) ─────────────
        grp_voice = QGroupBox("🎙️ NỀN TẢNG TẠO VOICE (VieNeu-TTS)")
        lo_voice = QVBoxLayout(grp_voice)
        lo_voice.setContentsMargins(15, 25, 15, 15)
        lo_voice.setSpacing(8)

        h_vmode = QHBoxLayout()
        self.radio_preset = QRadioButton("🎭 Preset Voice")
        self.radio_clone  = QRadioButton("🎤 Clone Voice (file .wav)")
        self.radio_profile = QRadioButton("📁 Profile đã lưu")
        self.radio_preset.setChecked(True)
        self.radio_preset.toggled.connect(self._on_voice_mode_changed)
        self.radio_clone.toggled.connect(self._on_voice_mode_changed)
        self.radio_profile.toggled.connect(self._on_voice_mode_changed)
        h_vmode.addWidget(self.radio_preset)
        h_vmode.addWidget(self.radio_clone)
        h_vmode.addWidget(self.radio_profile)
        lo_voice.addLayout(h_vmode)

        # Panel Preset
        self.pnl_preset = QWidget()
        lo_p = QVBoxLayout(self.pnl_preset)
        lo_p.setContentsMargins(0,0,0,0)
        lo_p.addWidget(QLabel("Chọn giọng (⭐ = nữ ưu tiên):"))
        self.cb_voice_model = QComboBox()
        self.cb_voice_model.addItem("⏳ Đang load VieNeu presets...")
        lo_p.addWidget(self.cb_voice_model)
        lo_voice.addWidget(self.pnl_preset)

        # Panel Clone
        self.pnl_clone = QWidget()
        lo_c = QVBoxLayout(self.pnl_clone)
        lo_c.setContentsMargins(0,0,0,0)
        lo_c.addWidget(QLabel("File mẫu giọng (.wav, 3–10 giây):"))
        h_wav = QHBoxLayout()
        self.txt_clone_wav = QLineEdit()
        self.txt_clone_wav.setPlaceholderText("Chưa chọn file mẫu...")
        self.txt_clone_wav.setReadOnly(True)
        btn_browse = QPushButton("📂 Chọn")
        btn_browse.setMaximumWidth(70)
        btn_browse.clicked.connect(self._browse_clone_wav)
        h_wav.addWidget(self.txt_clone_wav); h_wav.addWidget(btn_browse)
        lo_c.addLayout(h_wav)

        h_save_clone = QHBoxLayout()
        self.txt_profile_name = QLineEdit()
        self.txt_profile_name.setPlaceholderText("Đặt tên profile...")
        btn_save_clone = QPushButton("💾 Lưu Profile")
        btn_save_clone.clicked.connect(self._save_clone_profile)
        btn_save_clone.setStyleSheet("background:#1a73e8; color:white; font-weight:bold;")
        h_save_clone.addWidget(self.txt_profile_name)
        h_save_clone.addWidget(btn_save_clone)
        lo_c.addLayout(h_save_clone)
        lo_voice.addWidget(self.pnl_clone)

        # Panel Profile
        self.pnl_profile = QWidget()
        lo_pr = QVBoxLayout(self.pnl_profile)
        lo_pr.setContentsMargins(0,0,0,0)
        lo_pr.addWidget(QLabel("Voice profile đã lưu:"))
        h_prof = QHBoxLayout()
        self.cb_profiles = QComboBox()
        self.cb_profiles.addItem("(Chưa có profile)")
        btn_del_prof = QPushButton("🗑️ Xóa")
        btn_del_prof.setMaximumWidth(60)
        btn_del_prof.clicked.connect(self._delete_profile)
        h_prof.addWidget(self.cb_profiles); h_prof.addWidget(btn_del_prof)
        lo_pr.addLayout(h_prof)
        lo_voice.addWidget(self.pnl_profile)

        # Nút reload & lưu
        h_vbtn = QHBoxLayout()
        btn_reload = QPushButton("🔄 Reload VieNeu")
        btn_reload.clicked.connect(self._load_voices_async)
        btn_save_voice = QPushButton("💾 Lưu Cấu Hình Voice")
        btn_save_voice.clicked.connect(self.main.save_personal_settings)
        btn_save_voice.setStyleSheet("background:#00ff88; color:black; font-weight:bold;")
        h_vbtn.addWidget(btn_reload); h_vbtn.addWidget(btn_save_voice)
        lo_voice.addLayout(h_vbtn)

        col_left.addWidget(grp_voice)
        self._on_voice_mode_changed()

        # ── 5. Nền tảng Dịch Thuật ───────────────────────────
        self.gb_sec = QGroupBox("⚙️ NỀN TẢNG DỊCH THUẬT")
        lo_sec = QVBoxLayout(self.gb_sec)
        lo_sec.setContentsMargins(15, 25, 15, 15)

        h_platform = QHBoxLayout()
        self.radio_gemini = QRadioButton("🌐 Gemini API")
        self.radio_ollama = QRadioButton("🖥️ Ollama Local")
        self.radio_gemini.setChecked(True)
        self.radio_gemini.toggled.connect(self.toggle_ai_platform)
        h_platform.addWidget(self.radio_gemini); h_platform.addWidget(self.radio_ollama)
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
        h_test.addWidget(self.btn_test); h_test.addWidget(self.cb_models)
        lo_sec.addLayout(h_test)

        btn_save = QPushButton("💾 LƯU CẤU HÌNH AI / OLLAMA")
        btn_save.clicked.connect(self.main.save_personal_settings)
        btn_save.setStyleSheet("background:#00ff88; color:black; font-weight:bold;")
        lo_sec.addWidget(btn_save)
        self.gb_sec.hide()
        col_left.addWidget(self.gb_sec)
        col_left.addStretch()

        # ── Cột phải ─────────────────────────────────────────
        self.list_videos = QListWidget()
        self.list_videos.itemClicked.connect(self.main.play_selected_video)
        col_right.addWidget(QLabel("DANH SÁCH VIDEO:"))
        col_right.addWidget(self.list_videos, 2)

        self.console = SystemConsole()
        self.console.setMinimumHeight(180)
        col_right.addWidget(self.console, 3)

        self.btn_run = QPushButton("🚀 KHỞI ĐỘNG DUBBING")
        self.btn_run.setMinimumHeight(80)
        self.btn_run.setStyleSheet("background:#ff00ff; color:white; font-size:18px; font-weight:bold;")
        self.btn_run.clicked.connect(self.main.start_pipeline)
        col_right.addWidget(self.btn_run)

        # ── Nút Tạm dừng / Tiếp tục & Dừng hẳn ─────────────
        h_ctrl = QHBoxLayout()
        self.btn_pause = QPushButton("⏸️  TẠM DỪNG")
        self.btn_pause.setMinimumHeight(44)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet(
            "background:#f5a623; color:black; font-size:14px; font-weight:bold;"
        )
        self.btn_pause.clicked.connect(self.main.toggle_pause_pipeline)

        self.btn_stop = QPushButton("⏹️  DỪNG HẲN")
        self.btn_stop.setMinimumHeight(44)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "background:#e53935; color:white; font-size:14px; font-weight:bold;"
        )
        self.btn_stop.clicked.connect(self.main.stop_pipeline)

        h_ctrl.addWidget(self.btn_pause)
        h_ctrl.addWidget(self.btn_stop)
        col_right.addLayout(h_ctrl)

        layout.addLayout(col_left, 3)
        layout.addLayout(col_right, 4)

    # ═══════════════════════════════════════════════════════════
    # VOICE — LOAD ASYNC
    # ═══════════════════════════════════════════════════════════
    def _load_voices_async(self):
        # Ngắt kết nối signal của thread cũ nếu vẫn còn chạy,
        # tránh _on_voices_loaded bị gọi 2 lần khi user bấm Reload nhanh.
        if hasattr(self, '_voice_loader'):
            try:
                self._voice_loader.done.disconnect()
            except RuntimeError:
                pass
        self.cb_voice_model.clear()
        self.cb_voice_model.addItem("⏳ Đang khởi tạo VieNeu-TTS...")
        self._voice_loader = VoiceLoaderThread()
        self._voice_loader.done.connect(self._on_voices_loaded)
        self._voice_loader.start()

    def _on_voices_loaded(self, presets: list, profiles: dict):
        self._voice_presets  = presets
        self._voice_profiles = profiles

        self.cb_voice_model.clear()
        if presets:
            for desc, voice_id in presets:
                from services.voice_service import FEMALE_HINTS
                star = "⭐ " if any(h in desc.lower() for h in FEMALE_HINTS) else ""
                self.cb_voice_model.addItem(f"{star}{desc}", userData=voice_id)
        else:
            self.cb_voice_model.addItem("(Không tải được voices)")

        self.cb_profiles.clear()
        if profiles:
            for name in profiles.keys():
                self.cb_profiles.addItem(name)
        else:
            self.cb_profiles.addItem("(Chưa có profile)")

    def _on_voice_mode_changed(self):
        self.pnl_preset.setVisible(self.radio_preset.isChecked())
        self.pnl_clone.setVisible(self.radio_clone.isChecked())
        self.pnl_profile.setVisible(self.radio_profile.isChecked())

    def _browse_clone_wav(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file giọng mẫu", "", "Audio Files (*.wav *.mp3 *.flac)")
        if path:
            self._clone_wav_path = path
            self.txt_clone_wav.setText(os.path.basename(path))
            sys_log.info(f"🎙️ Đã chọn file mẫu: {os.path.basename(path)}")

    def _save_clone_profile(self):
        if not self._clone_wav_path:
            QMessageBox.warning(self, "Chưa chọn file", "Vui lòng chọn file .wav mẫu trước!")
            return
        name = self.txt_profile_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Thiếu tên", "Vui lòng đặt tên cho profile!")
            return
        self._saver_thread = _ProfileSaverThread(name, self._clone_wav_path)
        self._saver_thread.done.connect(self._on_profile_saved)
        self._saver_thread.start()

    def _on_profile_saved(self, ok: bool, name: str):
        if ok:
            if self.cb_profiles.itemText(0) == "(Chưa có profile)":
                self.cb_profiles.clear()
            self.cb_profiles.addItem(name)
            self.cb_profiles.setCurrentText(name)
            self._voice_profiles[name] = {"type": "clone", "value": self._clone_wav_path}
            self.txt_profile_name.clear()
            QMessageBox.information(self, "Đã lưu", f"✅ Profile '{name}' đã được lưu!")
        else:
            QMessageBox.critical(self, "Lỗi", "Không lưu được profile!")

    def _delete_profile(self):
        name = self.cb_profiles.currentText()
        if name == "(Chưa có profile)" or not name:
            return
        reply = QMessageBox.question(self, "Xác nhận", f"Xóa profile '{name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._deleter_thread = _ProfileDeleterThread(name)
            self._deleter_thread.done.connect(lambda ok, n=name: self._on_profile_deleted(ok, n))
            self._deleter_thread.start()

    def _on_profile_deleted(self, ok: bool, name: str):
        if ok:
            idx = self.cb_profiles.findText(name)
            if idx >= 0:
                self.cb_profiles.removeItem(idx)
            if self.cb_profiles.count() == 0:
                self.cb_profiles.addItem("(Chưa có profile)")
        else:
            QMessageBox.critical(self, "Lỗi", f"Không xóa được profile '{name}'!")

    def get_selected_voice(self):
        if self.radio_preset.isChecked():
            return self.cb_voice_model.currentData() or None
        elif self.radio_clone.isChecked():
            return self._clone_wav_path or None
        elif self.radio_profile.isChecked():
            name = self.cb_profiles.currentText()
            return None if name == "(Chưa có profile)" else name
        return None

    # ═══════════════════════════════════════════════════════════
    # AI PLATFORM
    # ═══════════════════════════════════════════════════════════
    def toggle_ai_platform(self):
        is_gemini = self.radio_gemini.isChecked()
        self.wdg_gemini.setVisible(is_gemini)
        self.cb_models.clear()
        if is_gemini:
            self.btn_test.setText("🔍 KIỂM TRA & LOAD GEMINI")
        else:
            self.btn_test.setText("🔍 QUÉT MODEL OLLAMA LOCAL")

    def check_and_load_models(self):
        self.cb_models.clear()
        if self.radio_ollama.isChecked():
            self.btn_test.setText("⌛ Đang quét Ollama...")
            try:
                resp = requests.get("http://localhost:11434/api/tags", timeout=5)
                if resp.status_code == 200:
                    models = [m['name'] for m in resp.json().get('models', [])]
                    if models:
                        self.cb_models.addItems(models)
                        QMessageBox.information(self, "OK", f"Tìm thấy {len(models)} model Ollama!")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không kết nối Ollama: {e}")
            self.btn_test.setText("🔍 QUÉT MODEL OLLAMA LOCAL")
            return

        QMessageBox.information(self, "Tab 3", "Vui lòng sử dụng 🔐 TAB 3: QUẢN LÝ API để quản lý Gemini/OpenAI/Groq/DeepSeek keys và models.")
        self.btn_test.setText("🔍 KIỂM TRA & LOAD GEMINI")

    def start_pipeline(self):
        self.main.start_pipeline()

    # ═══════════════════════════════════════════════════════════
    # BATCH PROGRESS — cập nhật từng item trong danh sách
    # ═══════════════════════════════════════════════════════════
    # Màu nền và icon theo trạng thái
    _STATUS_STYLE = {
        "start":   ("#1a3a5c", "▶️ ", True),   # xanh đậm, bold
        "done":    ("#0d3320", "✅ ", False),   # xanh lá đậm
        "error":   ("#3a1a1a", "❌ ", False),   # đỏ đậm
        "stopped": ("#2a2a1a", "⏸️ ", False),  # vàng đậm
        "pending": ("#1a1a2a", "",    False),   # xám mặc định
    }

    def reset_video_list_status(self):
        """Xoá toàn bộ trạng thái, đặt lại về pending trước khi bắt đầu batch."""
        for i in range(self.list_videos.count()):
            item = self.list_videos.item(i)
            if not item:
                continue
            name = item.text()
            for _, prefix, _ in self._STATUS_STYLE.values():
                if prefix and name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            item.setText(name)
            item.setBackground(QColor("#1a1a2a"))
            f = item.font()
            f.setBold(False)
            item.setFont(f)

    def update_video_item(self, one_based_idx: int, status: str):
        """
        Cập nhật item tại vị trí one_based_idx với trạng thái mới.
        Gọi từ main thread (đã được QTimer.singleShot bảo vệ).
        """
        row = one_based_idx - 1
        item = self.list_videos.item(row)
        if not item:
            return

        # Lấy tên gốc (bỏ prefix cũ nếu có)
        name = item.text()
        for _, prefix, _ in self._STATUS_STYLE.values():
            if prefix and name.startswith(prefix):
                name = name[len(prefix):]
                break

        bg_hex, prefix, bold = self._STATUS_STYLE.get(status, self._STATUS_STYLE["pending"])
        item.setText(prefix + name)
        item.setBackground(QColor(bg_hex))
        f = QFont(item.font())
        f.setBold(bold)
        item.setFont(f)

        # Cuộn đến item đang xử lý
        if status == "start":
            self.list_videos.scrollToItem(item)