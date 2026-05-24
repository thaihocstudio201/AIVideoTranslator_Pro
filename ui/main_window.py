import sys
import os

# ====================== FIX PYLANCE - ĐƯỜNG DẪN CORE ======================
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

core_path = os.path.join(project_root, "core")
if core_path not in sys.path:
    sys.path.insert(0, core_path)

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QMessageBox, QColorDialog, QLabel, QFileDialog, QSplitter, QPushButton
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

from ui.preview_panel import PreviewPanel
from ui.tabs.dubbing_tab import DubbingTab
from ui.tabs.visuals_tab import VisualsTab
from ui.tabs.api_tab import ApiManagementTab
from ui.tabs.license_tab import LicenseTab
from ui.style_sheets import MAIN_STYLE
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
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(4)

        # ── Banner cảnh báo license (ẩn khi đã kích hoạt) ──────────
        self._license_banner = QWidget()
        self._license_banner.setStyleSheet(
            "background:#3a0a0a;border:1px solid #cc2222;border-radius:5px;"
        )
        _banner_row = QHBoxLayout(self._license_banner)
        _banner_row.setContentsMargins(10, 6, 10, 6)
        _banner_lbl = QLabel(
            "🔒  CHƯA KÍCH HOẠT — Ứng dụng đang bị giới hạn. "
            "Vào <b>Tab 4: BẢN QUYỀN</b> để nhập License Key hoặc bắt đầu dùng thử 7 ngày."
        )
        _banner_lbl.setStyleSheet("color:#ff6b6b;font-size:13px;")
        _banner_row.addWidget(_banner_lbl, 1)
        _btn_go_license = QPushButton("🔑 Đến Tab 4")
        _btn_go_license.setFixedWidth(110)
        _btn_go_license.setStyleSheet(
            "background:#cc2222;color:white;font-weight:bold;border-radius:4px;padding:4px;"
        )
        _btn_go_license.clicked.connect(
            lambda: self.root_tabs.setCurrentIndex(3)
        )
        _banner_row.addWidget(_btn_go_license)
        self._license_banner.setVisible(False)
        main_layout.addWidget(self._license_banner)

        # PreviewPanel phải tạo TRƯỚC các tab (tab_dubbing/visuals cần truy cập nó)
        self.preview_panel = PreviewPanel(self)

        self.root_tabs = QTabWidget()

        self.tab_dubbing = DubbingTab(self)
        self.tab_visuals = VisualsTab(self)
        self.tab_api     = ApiManagementTab(self)
        self.tab_license = LicenseTab(self)

        self.root_tabs.addTab(self.tab_dubbing, "🚀 TAB 1: ĐIỀU KHIỂN & ĐỘNG CƠ")
        self.root_tabs.addTab(self.tab_visuals, "✂️ TAB 2: XƯỞNG LÁCH BẢN QUYỀN")
        self.root_tabs.addTab(self.tab_api,     "🔐 TAB 3: QUẢN LÝ API")
        self.root_tabs.addTab(self.tab_license, "🔑 TAB 4: BẢN QUYỀN & CẬP NHẬT")

        # Splitter ngang: trái = tabs, phải = preview panel cố định
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.root_tabs)
        splitter.addWidget(self.preview_panel)
        splitter.setSizes([1100, 560])
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        # Sync Tab 2 khi chuyển tab
        self.root_tabs.currentChanged.connect(self._on_tab_changed)

        # Kết nối: khi license thay đổi → cập nhật gate
        self.tab_license.license_changed.connect(self._apply_license_gate)

        # Kiểm tra license sau khi UI hoàn tất (50ms để đảm bảo paint xong)
        QTimer.singleShot(50, self._apply_license_gate)

        sys_log.info("✅ MainWindow đã khởi tạo thành công.")

    # ===================================================================
    # CALLBACK TỪ DUBBING TAB
    # ===================================================================
    def select_input(self):
        if self.tab_dubbing.radio_single.isChecked():
            path, _ = QFileDialog.getOpenFileName(self, "Chọn Video", "", "Video Files (*.mp4 *.mkv *.avi *.mov)")
            if path:
                self.tab_dubbing.txt_input.setText(path)
                self.current_folder = os.path.dirname(path)
                self.tab_dubbing.list_videos.clear()
                self.tab_dubbing.list_videos.addItem(os.path.basename(path))
                self.preview_panel.load_video(path)
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
        self.preview_panel.toggle_play()

    def play_selected_video(self, item):
        if self.current_folder:
            filepath = os.path.join(self.current_folder, item.text())
            self.preview_panel.load_video(filepath)
            sys_log.info(f"Đang xem trước: {item.text()}")

    def choose_sub_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.sub_color_hex = color.name()
            sys_log.info(f"Đã đổi màu phụ đề: {self.sub_color_hex}")

    def save_personal_settings(self):
        """Lưu toàn bộ cấu hình bao gồm voice và checkbox Demucs"""
        platform = "ollama" if self.tab_dubbing.radio_ollama.isChecked() else "gemini"
        self.selected_model = self.tab_dubbing.cb_models.currentText()

        config_dir = Path("config")
        config_dir.mkdir(exist_ok=True)

        config = {
            "ai_platform": platform,
            "default_model": self.selected_model,
            "target_lang": self.tab_dubbing.cb_target_lang.currentText(),
            "source_lang": self.tab_dubbing.cb_source_lang.currentText(),
            "vol_ai": self.tab_dubbing.sld_ai.value(),
            "vol_bg": self.tab_dubbing.sld_bg.value(),
            "vol_orig": self.tab_dubbing.sld_orig.value(),
            "use_advanced_separation": self.tab_dubbing.chk_advanced_mix.isChecked(),   # Checkbox Demucs
            "voice_profile": self.tab_dubbing.get_selected_voice(),                   # Voice profile / clone
        }

        if config["ai_platform"] == "gemini" and self.valid_apis:
            config["api_keys"] = [api["key"] for api in self.valid_apis]

        with open(config_dir / "api_config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        sys_log.info(f"💾 Đã lưu cấu hình: {platform.upper()} | Model: {self.selected_model} | Demucs: {config['use_advanced_separation']}")
        QMessageBox.information(self, "Lưu thành công", f"Đã lưu cấu hình!\nDemucs: {'Bật' if config['use_advanced_separation'] else 'Tắt'}")

    def start_pipeline(self):
        """KHỞI ĐỘNG DUBBING"""
        # Kiểm tra license trước khi khởi động
        try:
            from security.license_client import LicenseClient
            if not LicenseClient.get().is_valid():
                QMessageBox.warning(
                    self, "🔒 Chưa kích hoạt",
                    "Bạn cần kích hoạt License hoặc bắt đầu dùng thử.\n\n"
                    "Vui lòng vào Tab 4: BẢN QUYỀN & CẬP NHẬT để nhập key hoặc dùng thử 7 ngày."
                )
                self.root_tabs.setCurrentIndex(3)
                return
        except Exception:
            pass

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
                files = sorted(
                    f for f in os.listdir(folder)
                    if f.lower().endswith(valid_exts)
                )
                videos = [os.path.join(folder, f) for f in files]

        if not videos:
            QMessageBox.warning(self, "Không có video", "Không tìm thấy video nào!")
            return

        # Tab 3 (API Management) có priority cao hơn Tab 1 nếu đã kích hoạt
        if self.tab_api.active_platform:
            ai_platform   = self.tab_api.active_platform
            default_model = self.tab_api.active_model
            api_keys      = self.tab_api.get_active_keys()
        else:
            ai_platform   = "ollama" if self.tab_dubbing.radio_ollama.isChecked() else "gemini"
            default_model = self.tab_dubbing.cb_models.currentText() or "qwen2.5:14b"
            api_keys      = [api["key"] for api in self.valid_apis] if self.valid_apis else []

        config = {
            "ai_platform":           ai_platform,
            "default_model":         default_model,
            "api_keys":              api_keys,
            "target_lang":           self.tab_dubbing.cb_target_lang.currentText(),
            "source_lang":           self.tab_dubbing.cb_source_lang.currentText(),
            "vol_ai":                self.tab_dubbing.sld_ai.value(),
            "vol_bg":                self.tab_dubbing.sld_bg.value(),
            "vol_orig":              self.tab_dubbing.sld_orig.value(),
            "use_advanced_separation": self.tab_dubbing.chk_advanced_mix.isChecked(),
            "voice_profile":         self.tab_dubbing.get_selected_voice(),
        }

        self.is_running = True
        self._batch_total = len(videos)
        self.tab_dubbing.btn_run.setEnabled(False)
        self.tab_dubbing.btn_run.setText(f"⏳ ĐANG XỬ LÝ... (0/{self._batch_total})")
        self.tab_dubbing.btn_pause.setEnabled(True)
        self.tab_dubbing.btn_stop.setEnabled(True)
        self.tab_dubbing.reset_video_list_status()

        try:
            self.engine = VideoPipelineEngine(
                videos, out_dir, config,
                on_finish_callback=lambda: QTimer.singleShot(0, self.on_pipeline_done),
                on_video_progress=self._on_video_progress,
            )
            self.engine.start()
            sys_log.info(f"🚀 Khởi động dubbing: {len(videos)} video")
        except Exception as e:
            sys_log.error(f"Lỗi khởi động pipeline: {e}")
            self.on_pipeline_done()

    def toggle_pause_pipeline(self):
        """Tạm dừng / Tiếp tục pipeline."""
        if not self.is_running or not hasattr(self, 'engine'):
            return
        if self.engine.is_paused:
            self.engine.resume()
            self.tab_dubbing.btn_pause.setText("⏸️  TẠM DỪNG")
            self.tab_dubbing.btn_pause.setStyleSheet(
                "background:#f5a623; color:black; font-size:14px; font-weight:bold;"
            )
            self.tab_dubbing.btn_run.setText("⏳ ĐANG XỬ LÝ...")
        else:
            self.engine.pause()
            self.tab_dubbing.btn_pause.setText("▶️  TIẾP TỤC")
            self.tab_dubbing.btn_pause.setStyleSheet(
                "background:#43a047; color:white; font-size:14px; font-weight:bold;"
            )
            self.tab_dubbing.btn_run.setText("⏸️  ĐÃ TẠM DỪNG")

    def stop_pipeline(self):
        """Dừng pipeline hoàn toàn."""
        if not self.is_running or not hasattr(self, 'engine'):
            return
        reply = QMessageBox.question(
            self, "Xác nhận dừng",
            "Dừng pipeline? Tiến trình hiện tại sẽ bị huỷ (các file đã xuất vẫn giữ).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.engine.stop()
            self.tab_dubbing.btn_pause.setEnabled(False)
            self.tab_dubbing.btn_stop.setEnabled(False)
            self.tab_dubbing.btn_run.setText("⏳ ĐANG DỪNG...")

    def _on_video_progress(self, idx: int, total: int, name: str, status: str):
        """Callback từ pipeline thread — dùng QTimer để cập nhật UI trên main thread."""
        idx_, total_, name_, status_ = idx, total, name, status
        QTimer.singleShot(0, lambda: self._apply_video_progress(idx_, total_, name_, status_))

    def _apply_video_progress(self, idx: int, total: int, name: str, status: str):
        """Chạy trên main thread — cập nhật list và nút Run."""
        self.tab_dubbing.update_video_item(idx, status)

        if status == "start":
            short = name if len(name) <= 30 else name[:27] + "…"
            self.tab_dubbing.btn_run.setText(f"⏳ [{idx}/{total}] {short}")
        elif status in ("done", "error", "stopped"):
            done_count = sum(
                1 for i in range(self.tab_dubbing.list_videos.count())
                if self.tab_dubbing.list_videos.item(i) and
                any(self.tab_dubbing.list_videos.item(i).text().startswith(p)
                    for p in ("✅ ", "❌ ", "⏸️ "))
            )
            remaining = total - done_count
            label = "⏳ ĐANG XỬ LÝ" if remaining > 0 else "⏳ HOÀN TẤT"
            self.tab_dubbing.btn_run.setText(f"{label} ({done_count}/{total})")

    def on_pipeline_done(self):
        self.is_running = False

        # Đếm kết quả từ danh sách video (items đã được cập nhật trước callback này)
        if hasattr(self.tab_dubbing, 'list_videos'):
            lw     = self.tab_dubbing.list_videos
            total  = lw.count()
            ok_n   = sum(1 for i in range(total) if lw.item(i) and lw.item(i).text().startswith("✅ "))
            err_n  = sum(1 for i in range(total) if lw.item(i) and lw.item(i).text().startswith("❌ "))
            if err_n:
                final_label = f"✅ {ok_n} OK  ❌ {err_n} lỗi — Nhấn để chạy lại"
            else:
                final_label = f"✅ HOÀN TẤT {ok_n}/{total} — Nhấn để chạy mới"
        else:
            final_label = "🚀 KHỞI ĐỘNG DUBBING"

        if hasattr(self.tab_dubbing, 'btn_run'):
            self.tab_dubbing.btn_run.setEnabled(True)
            self.tab_dubbing.btn_run.setText(final_label)
            # Sau 5 giây tự reset về label mặc định
            QTimer.singleShot(5000, lambda: (
                self.tab_dubbing.btn_run.setText("🚀 KHỞI ĐỘNG DUBBING")
                if not self.is_running else None
            ))
        if hasattr(self.tab_dubbing, 'btn_pause'):
            self.tab_dubbing.btn_pause.setEnabled(False)
            self.tab_dubbing.btn_pause.setText("⏸️  TẠM DỪNG")
            self.tab_dubbing.btn_pause.setStyleSheet(
                "background:#f5a623; color:black; font-size:14px; font-weight:bold;"
            )
        if hasattr(self.tab_dubbing, 'btn_stop'):
            self.tab_dubbing.btn_stop.setEnabled(False)
        sys_log.info("🎉 HOÀN TẤT TOÀN BỘ CHIẾN DỊCH!")
        # Re-apply gate: nếu chưa có license thì lock lại nút Run sau khi xong
        QTimer.singleShot(100, self._apply_license_gate)

    def _on_tab_changed(self, index: int):
        """Khi chuyển sang Tab 2 (Visuals) → sync video player từ Tab 1."""
        if index == 1:
            try:
                self.tab_visuals.sync_from_dubbing_tab()
            except Exception as e:
                sys_log.warning(f"Sync Tab Visuals: {e}")

    # ===================================================================
    # LICENSE GATE — khóa/mở chức năng theo trạng thái license
    # ===================================================================
    def _apply_license_gate(self):
        """
        Kiểm tra trạng thái license và cập nhật UI:
        - Nếu hợp lệ (valid/trial/grace): bật nút Run, ẩn banner, mở Tab 1-3.
        - Nếu không hợp lệ: vô hiệu hóa nút Run, hiện banner đỏ, block Tab 1-2.
        Tab 3 (API) và Tab 4 (License) luôn truy cập được.
        """
        try:
            from security.license_client import LicenseClient
            licensed = LicenseClient.get().is_valid()
        except Exception:
            licensed = False

        self._license_banner.setVisible(not licensed)

        # ── Tab 1: Dubbing ─────────────────────────────────────────
        for attr in ('btn_run', 'btn_pause', 'btn_stop'):
            btn = getattr(self.tab_dubbing, attr, None)
            if btn is None:
                continue
            if attr == 'btn_run':
                if licensed:
                    btn.setEnabled(True)
                    if btn.text().startswith("🔒"):
                        btn.setText("🚀 KHỞI ĐỘNG DUBBING")
                else:
                    btn.setEnabled(False)
                    btn.setText("🔒 CẦN KÍCH HOẠT LICENSE")
            else:
                # pause/stop chỉ enable khi đang chạy — giữ nguyên logic cũ
                if not licensed:
                    btn.setEnabled(False)

        # ── Tab 1 & 2: dim tab title when not activated ────────────
        tab_color = QColor("#ffffff") if licensed else QColor("#aaaaaa")
        bar = self.root_tabs.tabBar()
        for tab_idx in (0, 1):
            bar.setTabTextColor(tab_idx, tab_color)
            bar.setTabEnabled(tab_idx, licensed)

        sys_log.info(f"🔐 License gate: {'OPEN' if licensed else 'LOCKED'}")


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())