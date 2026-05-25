"""
ui/tabs/visuals_tab.py — Với màn hình xem trước trực tiếp
  ✅ Preview video player với overlay blur/sub/logo trực quan
  ✅ Drag để di chuyển vùng blur và logo
  ✅ Blur & Sub settings
  ✅ Intro/Outro & Viền video
  ✅ Lách bản quyền đầy đủ
  ✅ Lưu/tải config/visuals_config.json
"""

import os
import json
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox,
    QPushButton, QComboBox, QLabel, QSlider, QCheckBox,
    QLineEdit, QSpinBox, QTabWidget, QScrollArea,
    QColorDialog, QFileDialog, QMessageBox,
    QDoubleSpinBox, QHBoxLayout, QGridLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

VISUALS_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "visuals_config.json"
)


def _row(label: str, widget: Optional[QWidget], layout: QVBoxLayout):
    layout.addWidget(QLabel(label))
    if widget is not None:
        layout.addWidget(widget)


# ═══════════════════════════════════════════════════════════════
# VISUALS TAB CHÍNH
# ═══════════════════════════════════════════════════════════════
class VisualsTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._sub_color_hex     = "#FFFFFF"
        self._border_color_hex  = "#000000"
        self._vborder_color_hex = "#000000"
        self._sub_anchor        = "bottom-center"   # anchor key e.g. "top-left"
        self._sub_margin_y_pct  = 0.10              # 0.0–0.5
        self._sub_margin_x_pct  = 0.03
        self._anchor_btns: dict[str, QPushButton] = {}

        # Khai báo tường minh để Pylance nhận diện attribute tạo qua setattr()
        self.chk_blur:          QCheckBox  = QCheckBox()
        self.spn_blur_x:        QSpinBox   = QSpinBox()
        self.spn_blur_y:        QSpinBox   = QSpinBox()
        self.spn_blur_w:        QSpinBox   = QSpinBox()
        self.spn_blur_h:        QSpinBox   = QSpinBox()
        self.lbl_blur_str:      QLabel     = QLabel()
        self.sld_blur_strength: QSlider    = QSlider()
        self.chk_sub:           QCheckBox  = QCheckBox()
        self.txt_sub_preview:   QLineEdit  = QLineEdit()
        self.cb_sub_font:       QComboBox  = QComboBox()
        self.spn_sub_size:      QSpinBox   = QSpinBox()
        self.lbl_sub_color:     QLabel     = QLabel()
        self.lbl_border_color:  QLabel     = QLabel()
        self.spn_border_w:      QSpinBox   = QSpinBox()
        self.cb_border_style:   QComboBox  = QComboBox()
        self.sld_margin_y:      QSlider    = QSlider()
        self.sld_margin_x:      QSlider    = QSlider()
        self.txt_intro:         QLineEdit  = QLineEdit()
        self.txt_outro:         QLineEdit  = QLineEdit()
        self.chk_logo:          QCheckBox  = QCheckBox()
        self.txt_logo:          QLineEdit  = QLineEdit()
        self.cb_logo_pos:       QComboBox  = QComboBox()
        self.spn_logo_opacity:  QSpinBox   = QSpinBox()
        self.spn_logo_w:        QSpinBox   = QSpinBox()
        self.spn_logo_h:        QSpinBox   = QSpinBox()
        self.chk_vborder:       QCheckBox  = QCheckBox()
        self.spn_vborder_w:     QSpinBox   = QSpinBox()
        self.lbl_vborder_color: QLabel     = QLabel()
        self.cb_aspect:         QComboBox  = QComboBox()
        self.chk_exif:          QCheckBox  = QCheckBox()
        self.chk_md5:           QCheckBox  = QCheckBox()
        self.chk_meta_inject:   QCheckBox  = QCheckBox()
        self.txt_meta_title:    QLineEdit  = QLineEdit()
        self.chk_flip_h:        QCheckBox  = QCheckBox()
        self.chk_flip_v:        QCheckBox  = QCheckBox()
        self.chk_zoom:          QCheckBox  = QCheckBox()
        self.spn_zoom:          QDoubleSpinBox = QDoubleSpinBox()
        self.chk_pan:           QCheckBox  = QCheckBox()
        self.cb_pan:            QComboBox  = QComboBox()
        self.chk_crop:          QCheckBox  = QCheckBox()
        self.spn_crop:          QSpinBox   = QSpinBox()
        self.cb_color_preset:   QComboBox  = QComboBox()
        self.spn_bright:        QSpinBox   = QSpinBox()
        self.spn_sat:           QDoubleSpinBox = QDoubleSpinBox()
        self.spn_contrast:      QDoubleSpinBox = QDoubleSpinBox()
        self.chk_fps:           QCheckBox  = QCheckBox()
        self.cb_fps:            QComboBox  = QComboBox()
        self.chk_res:           QCheckBox  = QCheckBox()
        self.cb_res:            QComboBox  = QComboBox()
        self.chk_noise:         QCheckBox  = QCheckBox()
        self.spn_noise:         QSpinBox   = QSpinBox()
        self.chk_gop:           QCheckBox  = QCheckBox()
        self.chk_codec:         QCheckBox  = QCheckBox()

        self.init_ui()
        # Canvas nằm trong PreviewPanel — kết nối signal sau khi init
        self.canvas.blur_moved.connect(self._on_blur_dragged)
        self.canvas.blur_resized.connect(self._on_blur_resized)
        self.canvas.sub_moved.connect(self._on_sub_dragged)
        self.canvas.logo_moved.connect(self._on_logo_dragged)
        self.load_settings()

    @property
    def canvas(self):
        return self.main.preview_panel.canvas

    def init_ui(self):
        self.setStyleSheet("""
            QWidget { background:#0b0e14; color:#c9d1d9; }
            QGroupBox {
                color:#00f2ff; font-weight:bold;
                border:1px solid #30363d; border-radius:6px;
                margin-top:8px; padding-top:6px;
            }
            QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }
            QCheckBox { color:#c9d1d9; spacing:5px; }
            QCheckBox::indicator { width:14px; height:14px; border:1px solid #30363d; border-radius:3px; background:#161b22; }
            QCheckBox::indicator:checked { background:#00f2ff; border:1px solid #00f2ff; }
            QLabel { color:#c9d1d9; }
            QLineEdit { background:#161b22; color:#c9d1d9; border:1px solid #30363d; border-radius:4px; padding:4px 6px; }
            QLineEdit:focus { border:1px solid #00f2ff; }
            QSpinBox, QDoubleSpinBox { background:#161b22; color:#c9d1d9; border:1px solid #30363d; border-radius:4px; padding:3px; }
            QComboBox { background:#161b22; color:#c9d1d9; border:1px solid #30363d; border-radius:4px; padding:3px 6px; }
            QComboBox::drop-down { border:none; }
            QComboBox QAbstractItemView { background:#161b22; color:#c9d1d9; selection-background-color:#1a73e8; }
            QSlider::groove:horizontal { background:#161b22; height:4px; border-radius:2px; }
            QSlider::handle:horizontal { background:#00f2ff; width:14px; height:14px; border-radius:7px; margin:-5px 0; }
            QSlider::sub-page:horizontal { background:#1a73e8; border-radius:2px; }
            QTabWidget::pane { border:1px solid #30363d; background:#0b0e14; }
            QTabBar::tab { background:#161b22; color:#8b949e; padding:6px 12px; border:1px solid #30363d; border-bottom:none; }
            QTabBar::tab:selected { background:#0b0e14; color:#00f2ff; font-weight:bold; }
            QTabBar::tab:hover { color:#c9d1d9; }
            QPushButton { background:#21262d; color:#c9d1d9; border:1px solid #30363d; border-radius:4px; padding:5px 10px; }
            QPushButton:hover { background:#30363d; color:#e6edf3; }
            QPushButton:pressed { background:#1a73e8; }
            QScrollArea { background:#0b0e14; border:none; }
            QScrollBar:vertical { background:#0d1117; width:8px; }
            QScrollBar::handle:vertical { background:#30363d; border-radius:4px; }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)

        self.inner_tabs = QTabWidget()
        self.inner_tabs.addTab(self._build_blur_sub_tab(),   "🔲 Blur & Sub")
        self.inner_tabs.addTab(self._build_media_tab(),      "🎬 Media & Viền")
        self.inner_tabs.addTab(self._build_copyright_tab(),  "🛡️ Lách Bản Quyền")
        outer.addWidget(self.inner_tabs, 1)

        # Save bar
        bar = QHBoxLayout()
        btn_save = QPushButton("💾 LƯU TOÀN BỘ CẤU HÌNH VISUALS")
        btn_save.setMinimumHeight(44)
        btn_save.setStyleSheet(
            "background:#1a73e8; color:white; font-size:13px; font-weight:bold;"
            "border:none; border-radius:5px;"
        )
        btn_save.clicked.connect(self.save_settings)
        btn_reset = QPushButton("🔄 Mặc định")
        btn_reset.setMinimumHeight(44)
        btn_reset.clicked.connect(self.reset_settings)
        bar.addWidget(btn_save, 4)
        bar.addWidget(btn_reset, 1)
        outer.addLayout(bar)

    # ── Preview controls ──────────────────────────────────────
    def sync_from_dubbing_tab(self):
        """Gọi từ MainWindow khi chuyển sang Tab 2 — load video vào PreviewPanel."""
        src = self.main.preview_panel._current_video
        if not src:
            src = self.main.tab_dubbing.txt_input.text().strip()
        if src and os.path.isfile(src):
            self.main.preview_panel.load_video(src)
        self._refresh_preview()
        from utils.custom_logger import sys_log
        sys_log.info("🖥️ Tab Visuals: sync từ Tab 1")

    def _refresh_preview(self):
        """Cập nhật canvas overlay sau khi thay đổi settings."""
        if self.chk_blur.isChecked():
            self.canvas.update_blur(
                True,
                self.spn_blur_x.value(), self.spn_blur_y.value(),
                self.spn_blur_w.value(), self.spn_blur_h.value()
            )
        else:
            self.canvas.blur_enabled = False

        if self.chk_sub.isChecked():
            self.canvas.update_sub(
                True, self.txt_sub_preview.text(),
                self.cb_sub_font.currentText(),
                self.spn_sub_size.value(),
                self._sub_color_hex, self._border_color_hex,
                self.spn_border_w.value(),
                self._sub_anchor,
                self._sub_margin_y_pct,
                self._sub_margin_x_pct,
            )
        else:
            self.canvas.sub_enabled = False

        if self.chk_logo.isChecked():
            self.canvas.update_logo(
                True, self.txt_logo.text(),
                self.cb_logo_pos.currentText(),
                self.spn_logo_opacity.value(),
                self.spn_logo_w.value(),
                self.spn_logo_h.value(),
            )
        else:
            self.canvas.logo_enabled = False

        self.canvas.update()

    def _on_blur_dragged(self, x, y):
        """Cập nhật spinbox khi drag blur box trên canvas."""
        self.spn_blur_x.blockSignals(True)
        self.spn_blur_y.blockSignals(True)
        self.spn_blur_x.setValue(x)
        self.spn_blur_y.setValue(y)
        self.spn_blur_x.blockSignals(False)
        self.spn_blur_y.blockSignals(False)

    def _on_blur_resized(self, x, y, w, h):
        """Cập nhật tất cả spinboxes khi resize blur box trên canvas."""
        for spn, val in [(self.spn_blur_x, x), (self.spn_blur_y, y),
                         (self.spn_blur_w, w), (self.spn_blur_h, h)]:
            spn.blockSignals(True)
            spn.setValue(val)
            spn.blockSignals(False)

    def _on_sub_dragged(self, anchor: str, margin_y: float, margin_x: float):
        """Cập nhật anchor + margin khi kéo text trên canvas."""
        self._sub_anchor       = anchor
        self._sub_margin_y_pct = margin_y
        self._sub_margin_x_pct = margin_x
        # Sync sliders without triggering refresh loop
        self.sld_margin_y.blockSignals(True)
        self.sld_margin_x.blockSignals(True)
        self.sld_margin_y.setValue(int(margin_y * 100))
        self.sld_margin_x.setValue(int(margin_x * 100))
        self.sld_margin_y.blockSignals(False)
        self.sld_margin_x.blockSignals(False)
        self._update_anchor_btn_styles()

    def _on_logo_dragged(self, x, y):
        """Giữ tọa độ logo khi kéo trên canvas (ngăn bị reset bởi _refresh_preview)."""
        self.canvas.logo_custom_x = x
        self.canvas.logo_custom_y = y

    def _reset_sub_position(self):
        """Reset về vị trí mặc định bottom-center."""
        self._sub_anchor       = "bottom-center"
        self._sub_margin_y_pct = 0.10
        self._sub_margin_x_pct = 0.03
        self.sld_margin_y.setValue(10)
        self.sld_margin_x.setValue(3)
        self._update_anchor_btn_styles()
        self._refresh_preview()

    def _update_anchor_btn_styles(self):
        for key, btn in self._anchor_btns.items():
            btn.setStyleSheet(
                "background:#1a73e8; color:white; font-weight:bold; border-radius:3px;"
                if key == self._sub_anchor else
                "background:#21262d; color:#aaa; border-radius:3px;"
            )

    def _set_anchor(self, key: str):
        self._sub_anchor = key
        self._update_anchor_btn_styles()
        self._refresh_preview()

    # ═══════════════════════════════════════════════════════════
    # TAB 1: BLUR & SUB
    # ═══════════════════════════════════════════════════════════
    def _build_blur_sub_tab(self) -> QWidget:
        w  = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(10)

        # ── Blur ─────────────────────────────────────────────
        g_blur = QGroupBox("🔲 Vùng Làm Mờ (Che Hardsub Cũ)")
        l_blur = QVBoxLayout(g_blur)

        self.chk_blur = QCheckBox("Bật hộp mờ")
        self.chk_blur.setStyleSheet("font-weight:bold;color:#00f2ff;")
        self.chk_blur.toggled.connect(self._refresh_preview)
        l_blur.addWidget(self.chk_blur)

        grid = QHBoxLayout()
        for attr, lbl, rng, default in [
            ("spn_blur_x","X",  (0,3840), 0),
            ("spn_blur_y","Y",  (0,2160), 900),
            ("spn_blur_w","W",  (10,3840),400),
            ("spn_blur_h","H",  (10,2160),60),
        ]:
            col = QVBoxLayout(); col.addWidget(QLabel(lbl+":"))
            spn = QSpinBox(); spn.setRange(*rng); spn.setValue(default)
            spn.valueChanged.connect(self._refresh_preview)
            setattr(self, attr, spn); col.addWidget(spn); grid.addLayout(col)
        l_blur.addLayout(grid)

        self.lbl_blur_str = QLabel("Cường độ (10):")
        self.sld_blur_strength = QSlider(Qt.Orientation.Horizontal)
        self.sld_blur_strength.setRange(1,30); self.sld_blur_strength.setValue(10)
        self.sld_blur_strength.valueChanged.connect(lambda v: self.lbl_blur_str.setText(f"Cường độ ({v}):"))
        l_blur.addWidget(self.lbl_blur_str); l_blur.addWidget(self.sld_blur_strength)
        lo.addWidget(g_blur)

        # ── Sub ──────────────────────────────────────────────
        g_sub = QGroupBox("📝 Phụ Đề Mới (Sub Overlay)")
        l_sub = QVBoxLayout(g_sub)

        self.chk_sub = QCheckBox("Bật phụ đề mới")
        self.chk_sub.setStyleSheet("font-weight:bold;color:#00f2ff;")
        self.chk_sub.toggled.connect(self._refresh_preview)
        l_sub.addWidget(self.chk_sub)

        h_prev = QHBoxLayout()
        h_prev.addWidget(QLabel("Nội dung mẫu:"))
        self.txt_sub_preview = QLineEdit("Đây là phụ đề mẫu tiếng Việt")
        self.txt_sub_preview.textChanged.connect(self._refresh_preview)
        h_prev.addWidget(self.txt_sub_preview)
        l_sub.addLayout(h_prev)

        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Font:"))
        self.cb_sub_font = QComboBox()
        self.cb_sub_font.addItems(["Arial","Impact","Tahoma","Verdana","Times New Roman","Segoe UI"])
        self.cb_sub_font.currentTextChanged.connect(self._refresh_preview)
        h1.addWidget(self.cb_sub_font)
        h1.addWidget(QLabel("Cỡ:"))
        self.spn_sub_size = QSpinBox(); self.spn_sub_size.setRange(12,80); self.spn_sub_size.setValue(24)
        self.spn_sub_size.valueChanged.connect(self._refresh_preview)
        h1.addWidget(self.spn_sub_size)
        l_sub.addLayout(h1)

        h2 = QHBoxLayout()
        self.lbl_sub_color = QLabel("Chữ: #FFFFFF")
        btn_sc = QPushButton("🎨"); btn_sc.setMaximumWidth(36)
        btn_sc.clicked.connect(self._pick_sub_color)
        self.lbl_border_color = QLabel("Viền: #000000")
        btn_bc = QPushButton("🎨"); btn_bc.setMaximumWidth(36)
        btn_bc.clicked.connect(self._pick_border_color)
        h2.addWidget(self.lbl_sub_color); h2.addWidget(btn_sc)
        h2.addWidget(self.lbl_border_color); h2.addWidget(btn_bc)
        h2.addWidget(QLabel("Dày:"))
        self.spn_border_w = QSpinBox(); self.spn_border_w.setRange(0,10); self.spn_border_w.setValue(2)
        self.spn_border_w.valueChanged.connect(self._refresh_preview)
        h2.addWidget(self.spn_border_w)
        l_sub.addLayout(h2)

        h3 = QHBoxLayout()
        h3.addWidget(QLabel("Kiểu viền:"))
        self.cb_border_style = QComboBox()
        self.cb_border_style.addItems(["Outline","Box","Shadow","Outline+Shadow"])
        h3.addWidget(self.cb_border_style)
        l_sub.addLayout(h3)

        # ── Anchor Grid 3×3 ──────────────────────────────────────
        anchor_grp = QGroupBox("📍 Vị trí Phụ Đề (kéo text trên canvas hoặc chọn neo)")
        anchor_grp.setStyleSheet("QGroupBox{font-size:11px;}")
        anchor_lo = QVBoxLayout(anchor_grp)

        ANCHORS = [
            ("↖", "top-left"),    ("↑", "top-center"),    ("↗", "top-right"),
            ("←", "middle-left"), ("·", "middle-center"), ("→", "middle-right"),
            ("↙", "bottom-left"), ("↓", "bottom-center"), ("↘", "bottom-right"),
        ]
        grid_w = QWidget()
        grid   = QGridLayout(grid_w)
        grid.setSpacing(3)
        grid.setContentsMargins(0, 0, 0, 0)
        for i, (symbol, key) in enumerate(ANCHORS):
            btn = QPushButton(symbol)
            btn.setFixedSize(32, 28)
            btn.setToolTip(key)
            is_default = (key == self._sub_anchor)
            btn.setStyleSheet(
                "background:#1a73e8;color:white;font-weight:bold;border-radius:3px;"
                if is_default else
                "background:#21262d;color:#aaa;border-radius:3px;"
            )
            btn.clicked.connect(lambda _=False, k=key: self._set_anchor(k))
            self._anchor_btns[key] = btn
            grid.addWidget(btn, i // 3, i % 3)
        anchor_lo.addWidget(grid_w)

        # Margin sliders
        h_my = QHBoxLayout()
        h_my.addWidget(QLabel("Margin Y (%):"))
        self.sld_margin_y = QSlider(Qt.Orientation.Horizontal)
        self.sld_margin_y.setRange(0, 50); self.sld_margin_y.setValue(10)
        self._lbl_margin_y = QLabel("10%")
        self._lbl_margin_y.setFixedWidth(32)
        def _upd_my(v): self._sub_margin_y_pct = v / 100.0; self._lbl_margin_y.setText(f"{v}%"); self._refresh_preview()
        self.sld_margin_y.valueChanged.connect(_upd_my)
        h_my.addWidget(self.sld_margin_y, 1); h_my.addWidget(self._lbl_margin_y)
        anchor_lo.addLayout(h_my)

        h_mx = QHBoxLayout()
        h_mx.addWidget(QLabel("Margin X (%):"))
        self.sld_margin_x = QSlider(Qt.Orientation.Horizontal)
        self.sld_margin_x.setRange(0, 50); self.sld_margin_x.setValue(3)
        self._lbl_margin_x = QLabel("3%")
        self._lbl_margin_x.setFixedWidth(32)
        def _upd_mx(v): self._sub_margin_x_pct = v / 100.0; self._lbl_margin_x.setText(f"{v}%"); self._refresh_preview()
        self.sld_margin_x.valueChanged.connect(_upd_mx)
        h_mx.addWidget(self.sld_margin_x, 1); h_mx.addWidget(self._lbl_margin_x)
        anchor_lo.addLayout(h_mx)

        btn_reset_pos = QPushButton("🔄 Reset về Bottom-Center")
        btn_reset_pos.setStyleSheet("color:#aaa; font-size:11px;")
        btn_reset_pos.clicked.connect(self._reset_sub_position)
        anchor_lo.addWidget(btn_reset_pos)
        l_sub.addWidget(anchor_grp)

        lo.addWidget(g_sub)
        lo.addStretch()
        return w

    # ═══════════════════════════════════════════════════════════
    # TAB 2: MEDIA & VIỀN
    # ═══════════════════════════════════════════════════════════
    def _build_media_tab(self) -> QWidget:
        w  = QWidget()
        lo = QVBoxLayout(w); lo.setSpacing(10)

        for title, attr in [("🎬 Video Intro","txt_intro"),("🎬 Video Outro","txt_outro")]:
            grp = QGroupBox(title); l = QVBoxLayout(grp)
            h = QHBoxLayout()
            txt = QLineEdit(); txt.setPlaceholderText("Chưa chọn...")
            setattr(self, attr, txt)
            btn = QPushButton("📂"); btn.setMaximumWidth(36)
            btn.clicked.connect(lambda _, t=txt: self._browse_video(t))
            clr = QPushButton("✖"); clr.setMaximumWidth(28)
            clr.clicked.connect(lambda _, t=txt: t.clear())
            h.addWidget(txt); h.addWidget(btn); h.addWidget(clr)
            l.addLayout(h); lo.addWidget(grp)

        # Logo
        g_logo = QGroupBox("🖼️ Logo / Watermark")
        l_logo = QVBoxLayout(g_logo)
        self.chk_logo = QCheckBox("Bật logo")
        self.chk_logo.toggled.connect(self._refresh_preview)
        l_logo.addWidget(self.chk_logo)
        h_logo = QHBoxLayout()
        self.txt_logo = QLineEdit(); self.txt_logo.setPlaceholderText("File ảnh (.png/.jpg)...")
        btn_logo = QPushButton("📂"); btn_logo.setMaximumWidth(36)
        btn_logo.clicked.connect(lambda: self._browse_image(self.txt_logo))
        h_logo.addWidget(self.txt_logo); h_logo.addWidget(btn_logo)
        l_logo.addLayout(h_logo)
        h_lp = QHBoxLayout()
        h_lp.addWidget(QLabel("Vị trí:"))
        self.cb_logo_pos = QComboBox()
        self.cb_logo_pos.addItems(["Góc trên trái","Góc trên phải","Góc dưới trái","Góc dưới phải","Giữa"])
        self.cb_logo_pos.currentTextChanged.connect(self._refresh_preview)
        h_lp.addWidget(self.cb_logo_pos)
        h_lp.addWidget(QLabel("Opacity:"))
        self.spn_logo_opacity = QSpinBox(); self.spn_logo_opacity.setRange(10,100); self.spn_logo_opacity.setValue(80)
        self.spn_logo_opacity.valueChanged.connect(self._refresh_preview)
        h_lp.addWidget(self.spn_logo_opacity)
        l_logo.addLayout(h_lp)
        h_lsz = QHBoxLayout()
        h_lsz.addWidget(QLabel("Kích thước (px):"))
        h_lsz.addWidget(QLabel("W:"))
        self.spn_logo_w = QSpinBox(); self.spn_logo_w.setRange(0, 1920); self.spn_logo_w.setValue(0)
        self.spn_logo_w.setSpecialValueText("Tự động")
        self.spn_logo_w.valueChanged.connect(self._refresh_preview)
        h_lsz.addWidget(self.spn_logo_w)
        h_lsz.addWidget(QLabel("H:"))
        self.spn_logo_h = QSpinBox(); self.spn_logo_h.setRange(0, 1080); self.spn_logo_h.setValue(0)
        self.spn_logo_h.setSpecialValueText("Tự động")
        self.spn_logo_h.valueChanged.connect(self._refresh_preview)
        h_lsz.addWidget(self.spn_logo_h)
        l_logo.addLayout(h_lsz)
        # Load logo preview
        btn_load_logo = QPushButton("🔄 Cập nhật Preview Logo")
        btn_load_logo.clicked.connect(self._refresh_preview)
        l_logo.addWidget(btn_load_logo)
        lo.addWidget(g_logo)

        # Viền video
        g_bdr = QGroupBox("🖼️ Viền Video")
        l_bdr = QVBoxLayout(g_bdr)
        self.chk_vborder = QCheckBox("Bật viền video")
        l_bdr.addWidget(self.chk_vborder)
        h_bdr = QHBoxLayout()
        h_bdr.addWidget(QLabel("Dày (px):"))
        self.spn_vborder_w = QSpinBox(); self.spn_vborder_w.setRange(1,50); self.spn_vborder_w.setValue(5)
        h_bdr.addWidget(self.spn_vborder_w)
        self.lbl_vborder_color = QLabel("Màu: #000000")
        btn_vbc = QPushButton("🎨"); btn_vbc.setMaximumWidth(36)
        btn_vbc.clicked.connect(self._pick_vborder_color)
        h_bdr.addWidget(self.lbl_vborder_color); h_bdr.addWidget(btn_vbc)
        l_bdr.addLayout(h_bdr)

        # Tỉ lệ khung hình
        h_ar = QHBoxLayout()
        h_ar.addWidget(QLabel("Tỉ lệ khung hình:"))
        self.cb_aspect = QComboBox()
        self.cb_aspect.addItems(["Gốc","16:9","9:16 (Reels/TikTok)","4:3","1:1 (Vuông)","21:9 (Cinematic)"])
        self.cb_aspect.currentTextChanged.connect(self._on_aspect_changed)
        h_ar.addWidget(self.cb_aspect)
        l_bdr.addLayout(h_ar)
        lo.addWidget(g_bdr)

        lo.addStretch()
        return w

    # ═══════════════════════════════════════════════════════════
    # TAB 3: LÁCH BẢN QUYỀN
    # ═══════════════════════════════════════════════════════════
    def _build_copyright_tab(self) -> QWidget:
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner  = QWidget(); lo = QVBoxLayout(inner); lo.setSpacing(10)

        g_meta = QGroupBox("📋 Metadata & Fingerprint")
        l_meta = QVBoxLayout(g_meta)
        self.chk_exif        = QCheckBox("Tẩy trắng EXIF / Metadata gốc")
        self.chk_md5         = QCheckBox("Tạo lại mã MD5")
        self.chk_meta_inject = QCheckBox("Chèn metadata mới")
        for c in [self.chk_exif, self.chk_md5, self.chk_meta_inject]: l_meta.addWidget(c)
        h_mt = QHBoxLayout(); h_mt.addWidget(QLabel("Title mới:"))
        self.txt_meta_title = QLineEdit(); h_mt.addWidget(self.txt_meta_title)
        l_meta.addLayout(h_mt); lo.addWidget(g_meta)

        g_vid = QGroupBox("🎥 Biến đổi Hình Ảnh")
        l_vid = QVBoxLayout(g_vid)
        self.chk_flip_h = QCheckBox("Lật ngang (Mirror H)")
        self.chk_flip_v = QCheckBox("Lật dọc (Mirror V)")
        l_vid.addWidget(self.chk_flip_h); l_vid.addWidget(self.chk_flip_v)
        h_zoom = QHBoxLayout()
        self.chk_zoom = QCheckBox("Zoom nhẹ")
        self.spn_zoom = QDoubleSpinBox(); self.spn_zoom.setRange(1.01,1.20); self.spn_zoom.setValue(1.03); self.spn_zoom.setSingleStep(0.01)
        h_zoom.addWidget(self.chk_zoom); h_zoom.addWidget(QLabel("Hệ số:")); h_zoom.addWidget(self.spn_zoom)
        l_vid.addLayout(h_zoom)
        h_pan = QHBoxLayout()
        self.chk_pan = QCheckBox("Lia máy (Pan)")
        self.cb_pan  = QComboBox(); self.cb_pan.addItems(["Phải→Trái","Trái→Phải","Lên→Xuống","Xuống→Lên"])
        h_pan.addWidget(self.chk_pan); h_pan.addWidget(self.cb_pan)
        l_vid.addLayout(h_pan)
        h_crop = QHBoxLayout()
        self.chk_crop = QCheckBox("Cắt cạnh (Crop)")
        self.spn_crop = QSpinBox(); self.spn_crop.setRange(1,50); self.spn_crop.setValue(5)
        h_crop.addWidget(self.chk_crop); h_crop.addWidget(QLabel("px:")); h_crop.addWidget(self.spn_crop)
        l_vid.addLayout(h_crop)
        lo.addWidget(g_vid)

        g_color = QGroupBox("🎨 Bộ Lọc Màu")
        l_color = QVBoxLayout(g_color)
        self.cb_color_preset = QComboBox()
        self.cb_color_preset.addItems(["Gốc","Cinematic","Vivid","B&W","Warm","Cool","Vintage"])
        l_color.addWidget(self.cb_color_preset)
        for attr, lbl, is_float in [("spn_bright","Brightness",False),("spn_sat","Saturation",True),("spn_contrast","Contrast",True)]:
            h = QHBoxLayout(); h.addWidget(QLabel(f"{lbl}:"))
            if is_float:
                spn = QDoubleSpinBox(); spn.setRange(0.0,3.0); spn.setValue(1.0); spn.setSingleStep(0.1)
            else:
                spn = QSpinBox(); spn.setRange(-50,50); spn.setValue(0)  # type: ignore[assignment]
            setattr(self, attr, spn); h.addWidget(spn); l_color.addLayout(h)
        lo.addWidget(g_color)

        g_tech = QGroupBox("⚙️ Kỹ Thuật Video")
        l_tech = QVBoxLayout(g_tech)
        h_fps = QHBoxLayout()
        self.chk_fps = QCheckBox("Đổi FPS")
        self.cb_fps  = QComboBox(); self.cb_fps.addItems(["Gốc","23.976","24","25","29.97","30","60"])
        h_fps.addWidget(self.chk_fps); h_fps.addWidget(self.cb_fps); l_tech.addLayout(h_fps)
        h_res = QHBoxLayout()
        self.chk_res = QCheckBox("Đổi Resolution")
        self.cb_res  = QComboBox(); self.cb_res.addItems(["Gốc","3840x2160","1920x1080","1280x720","854x480"])
        h_res.addWidget(self.chk_res); h_res.addWidget(self.cb_res); l_tech.addLayout(h_res)
        h_noise = QHBoxLayout()
        self.chk_noise = QCheckBox("Thêm noise nhẹ")
        self.spn_noise = QSpinBox(); self.spn_noise.setRange(1,15); self.spn_noise.setValue(3)
        h_noise.addWidget(self.chk_noise); h_noise.addWidget(QLabel("Str:")); h_noise.addWidget(self.spn_noise)
        l_tech.addLayout(h_noise)
        self.chk_gop   = QCheckBox("Tái mã hóa GOP")
        self.chk_codec = QCheckBox("Re-encode H.265 (HEVC)")
        l_tech.addWidget(self.chk_gop); l_tech.addWidget(self.chk_codec)
        lo.addWidget(g_tech)

        lo.addStretch(); scroll.setWidget(inner)
        return scroll

    # ── Aspect ratio preview sync ─────────────────────────────
    _AR_MAP = {
        "16:9":              (16, 9),
        "9:16 (Reels/TikTok)": (9, 16),
        "4:3":               (4, 3),
        "1:1 (Vuông)":       (1, 1),
        "21:9 (Cinematic)":  (21, 9),
    }

    def _on_aspect_changed(self, text: str):
        ar = self._AR_MAP.get(text)
        if ar:
            self.canvas.set_aspect(*ar)
        else:
            # "Gốc" — restore native video dimensions
            w, h = self.canvas._video_w, self.canvas._video_h
            if w > 0 and h > 0:
                self.canvas.set_aspect(w, h)
        self.main.preview_panel._stack.updateGeometry()

    # ── Color pickers ─────────────────────────────────────────
    def _pick_sub_color(self):
        c = QColorDialog.getColor(QColor(self._sub_color_hex), self)
        if c.isValid():
            self._sub_color_hex = c.name().upper()
            self.lbl_sub_color.setText(f"Chữ: {self._sub_color_hex}")
            self._refresh_preview()

    def _pick_border_color(self):
        c = QColorDialog.getColor(QColor(self._border_color_hex), self)
        if c.isValid():
            self._border_color_hex = c.name().upper()
            self.lbl_border_color.setText(f"Viền: {self._border_color_hex}")
            self._refresh_preview()

    def _pick_vborder_color(self):
        c = QColorDialog.getColor(QColor(self._vborder_color_hex), self)
        if c.isValid():
            self._vborder_color_hex = c.name().upper()
            self.lbl_vborder_color.setText(f"Màu: {self._vborder_color_hex}")

    def _browse_video(self, t: QLineEdit):
        p, _ = QFileDialog.getOpenFileName(self,"Chọn Video","","Video (*.mp4 *.mkv *.avi *.mov)")
        if p: t.setText(p)

    def _browse_image(self, t: QLineEdit):
        p, _ = QFileDialog.getOpenFileName(self,"Chọn Logo","","Images (*.png *.jpg *.jpeg)")
        if p: t.setText(p); self._refresh_preview()

    # ═══════════════════════════════════════════════════════════
    # SAVE / LOAD
    # ═══════════════════════════════════════════════════════════
    def _hex_to_ass(self, h: str) -> str:
        h = h.lstrip("#")
        if len(h) == 6:
            r,g,b = h[:2],h[2:4],h[4:]
            return f"&H00{b}{g}{r}"
        return "&H00FFFFFF"

    def save_settings(self):
        border_map = {"Outline":"outline","Box":"box","Shadow":"shadow","Outline+Shadow":"outline+shadow"}
        cfg = {
            "blur_enabled":  self.chk_blur.isChecked(),
            "blur_x": self.spn_blur_x.value(), "blur_y": self.spn_blur_y.value(),
            "blur_w": self.spn_blur_w.value(), "blur_h": self.spn_blur_h.value(),
            "blur_strength": self.sld_blur_strength.value(),
            "sub_enabled":   self.chk_sub.isChecked(),
            "sub_font":      self.cb_sub_font.currentText(),
            "sub_size":      self.spn_sub_size.value(),
            "sub_color":     self._hex_to_ass(self._sub_color_hex),
            "sub_color_hex": self._sub_color_hex,
            "sub_border_color":     self._hex_to_ass(self._border_color_hex),
            "sub_border_color_hex": self._border_color_hex,
            "sub_border_width":     self.spn_border_w.value(),
            "sub_border_style":     border_map.get(self.cb_border_style.currentText(),"outline"),
            "sub_anchor":      self._sub_anchor,
            "sub_margin_y_pct": self._sub_margin_y_pct,
            "sub_margin_x_pct": self._sub_margin_x_pct,
            "border_enabled":self.chk_vborder.isChecked(),
            "border_width":  self.spn_vborder_w.value(),
            "border_color":  self._vborder_color_hex,
            "aspect_ratio":  self.cb_aspect.currentText(),
            "intro_path":    self.txt_intro.text().strip(),
            "outro_path":    self.txt_outro.text().strip(),
            "logo_enabled":  self.chk_logo.isChecked(),
            "logo_path":     self.txt_logo.text().strip(),
            "logo_position": self.cb_logo_pos.currentText(),
            "logo_opacity":  self.spn_logo_opacity.value(),
            "logo_w":        self.spn_logo_w.value(),
            "logo_h":        self.spn_logo_h.value(),
            "exif_clear":    self.chk_exif.isChecked(),
            "md5_rehash":    self.chk_md5.isChecked(),
            "meta_inject":   self.chk_meta_inject.isChecked(),
            "meta_title":    self.txt_meta_title.text().strip(),
            "flip_h": self.chk_flip_h.isChecked(), "flip_v": self.chk_flip_v.isChecked(),
            "zoom_enabled":  self.chk_zoom.isChecked(), "zoom_factor": self.spn_zoom.value(),
            "pan_enabled":   self.chk_pan.isChecked(),  "pan_direction": self.cb_pan.currentText(),
            "crop_enabled":  self.chk_crop.isChecked(), "crop_px": self.spn_crop.value(),
            "color_preset":  self.cb_color_preset.currentText(),
            "brightness":    self.spn_bright.value(),
            "saturation":    self.spn_sat.value(),
            "contrast":      self.spn_contrast.value(),
            "fps_enabled":   self.chk_fps.isChecked(),  "fps_value": self.cb_fps.currentText(),
            "res_enabled":   self.chk_res.isChecked(),  "res_value": self.cb_res.currentText(),
            "noise_enabled": self.chk_noise.isChecked(),"noise_strength": self.spn_noise.value(),
            "gop_reencode":  self.chk_gop.isChecked(),
            "codec_h265":    self.chk_codec.isChecked(),
        }
        os.makedirs(os.path.dirname(VISUALS_CONFIG), exist_ok=True)
        with open(VISUALS_CONFIG,"w",encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self,"✅ Đã lưu","Cấu hình Visuals đã lưu!")
        from utils.custom_logger import sys_log
        sys_log.info("💾 Visuals config saved")

    def load_settings(self):
        if not os.path.exists(VISUALS_CONFIG): return
        try:
            with open(VISUALS_CONFIG,"r",encoding="utf-8") as f: c = json.load(f)
        except Exception: return

        self.chk_blur.setChecked(c.get("blur_enabled",False))
        self.spn_blur_x.setValue(c.get("blur_x",0));     self.spn_blur_y.setValue(c.get("blur_y",900))
        self.spn_blur_w.setValue(c.get("blur_w",400));    self.spn_blur_h.setValue(c.get("blur_h",60))
        self.sld_blur_strength.setValue(c.get("blur_strength",10))
        self.chk_sub.setChecked(c.get("sub_enabled",False))
        self._sub_color_hex = c.get("sub_color_hex","#FFFFFF")
        self.lbl_sub_color.setText(f"Chữ: {self._sub_color_hex}")
        self._border_color_hex = c.get("sub_border_color_hex","#000000")
        self.lbl_border_color.setText(f"Viền: {self._border_color_hex}")
        fi = self.cb_sub_font.findText(c.get("sub_font","Arial"))
        if fi>=0: self.cb_sub_font.setCurrentIndex(fi)
        self.spn_sub_size.setValue(c.get("sub_size",24))
        self.spn_border_w.setValue(c.get("sub_border_width",2))
        # Backward compat: map old sub_position → anchor if no sub_anchor saved
        if "sub_anchor" in c:
            self._sub_anchor = c["sub_anchor"]
        elif "sub_position" in c:
            old_pos = c.get("sub_position", "bottom")
            self._sub_anchor = {"top": "top-center", "center": "middle-center",
                                 "bottom": "bottom-center"}.get(old_pos, "bottom-center")
        self._sub_margin_y_pct = c.get("sub_margin_y_pct", 0.10)
        self._sub_margin_x_pct = c.get("sub_margin_x_pct", 0.03)
        self.sld_margin_y.setValue(int(self._sub_margin_y_pct * 100))
        self.sld_margin_x.setValue(int(self._sub_margin_x_pct * 100))
        self._update_anchor_btn_styles()
        self.chk_vborder.setChecked(c.get("border_enabled",False))
        self.spn_vborder_w.setValue(c.get("border_width",5))
        self._vborder_color_hex = c.get("border_color","#000000")
        self.lbl_vborder_color.setText(f"Màu: {self._vborder_color_hex}")
        ai = self.cb_aspect.findText(c.get("aspect_ratio","Gốc"))
        if ai>=0: self.cb_aspect.setCurrentIndex(ai)
        self.txt_intro.setText(c.get("intro_path",""))
        self.txt_outro.setText(c.get("outro_path",""))
        self.chk_logo.setChecked(c.get("logo_enabled",False))
        self.txt_logo.setText(c.get("logo_path",""))
        self.spn_logo_opacity.setValue(c.get("logo_opacity",80))
        self.spn_logo_w.setValue(c.get("logo_w", 0))
        self.spn_logo_h.setValue(c.get("logo_h", 0))
        self.chk_exif.setChecked(c.get("exif_clear",False))
        self.chk_md5.setChecked(c.get("md5_rehash",False))
        self.chk_meta_inject.setChecked(c.get("meta_inject",False))
        self.txt_meta_title.setText(c.get("meta_title",""))
        self.chk_flip_h.setChecked(c.get("flip_h",False))
        self.chk_flip_v.setChecked(c.get("flip_v",False))
        self.chk_zoom.setChecked(c.get("zoom_enabled",False)); self.spn_zoom.setValue(c.get("zoom_factor",1.03))
        self.chk_pan.setChecked(c.get("pan_enabled",False))
        pi = self.cb_pan.findText(c.get("pan_direction","Phải→Trái"))
        if pi >= 0: self.cb_pan.setCurrentIndex(pi)
        self.chk_crop.setChecked(c.get("crop_enabled",False)); self.spn_crop.setValue(c.get("crop_px",5))
        self.chk_noise.setChecked(c.get("noise_enabled",False)); self.spn_noise.setValue(c.get("noise_strength",3))
        self.chk_fps.setChecked(c.get("fps_enabled",False))
        fi2 = self.cb_fps.findText(c.get("fps_value","Gốc"))
        if fi2 >= 0: self.cb_fps.setCurrentIndex(fi2)
        self.chk_res.setChecked(c.get("res_enabled",False))
        ri = self.cb_res.findText(c.get("res_value","Gốc"))
        if ri >= 0: self.cb_res.setCurrentIndex(ri)
        self.chk_gop.setChecked(c.get("gop_reencode",False)); self.chk_codec.setChecked(c.get("codec_h265",False))
        self.spn_bright.setValue(c.get("brightness",0))
        self.spn_sat.setValue(c.get("saturation",1.0)); self.spn_contrast.setValue(c.get("contrast",1.0))
        ci = self.cb_color_preset.findText(c.get("color_preset","Gốc"))
        if ci>=0: self.cb_color_preset.setCurrentIndex(ci)
        # Border style (stored lowercase → displayed Titlecase)
        _bs_rev = {"outline":"Outline","box":"Box","shadow":"Shadow","outline+shadow":"Outline+Shadow"}
        bsi = self.cb_border_style.findText(_bs_rev.get(c.get("sub_border_style","outline"),"Outline"))
        if bsi >= 0: self.cb_border_style.setCurrentIndex(bsi)
        # Logo position
        lpi = self.cb_logo_pos.findText(c.get("logo_position","Góc trên phải"))
        if lpi >= 0: self.cb_logo_pos.setCurrentIndex(lpi)
        self._refresh_preview()

    def reset_settings(self):
        r = QMessageBox.question(self,"Xác nhận","Khôi phục về mặc định?",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            if os.path.exists(VISUALS_CONFIG): os.remove(VISUALS_CONFIG)
            for chk in [self.chk_blur,self.chk_sub,self.chk_vborder,self.chk_logo,
                        self.chk_exif,self.chk_md5,self.chk_flip_h,self.chk_flip_v]:
                chk.setChecked(False)
            self.txt_intro.clear(); self.txt_outro.clear(); self.txt_logo.clear()
            self._refresh_preview()
            QMessageBox.information(self,"OK","Đã khôi phục mặc định!")