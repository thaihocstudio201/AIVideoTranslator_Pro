"""
ui/preview_panel.py
Panel xem trước video persistent — hiển thị xuyên suốt mọi tab.
Bao gồm: PreviewCanvas (overlay blur/sub/logo), player, timeline.
"""
from __future__ import annotations
import os
import subprocess
import tempfile
from typing import Optional

from PySide6.QtCore import Qt, QPoint, QRect, QSize, QUrl, Signal, QThread
from PySide6.QtGui import (QColor, QFont, QPainter, QPen, QBrush, QPixmap)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QSizePolicy, QStackedWidget,
    QFileDialog,
)


# ─────────────────────────────────────────────────────────────────────────────
# Thread trích xuất thumbnail
# ─────────────────────────────────────────────────────────────────────────────
class ThumbExtractThread(QThread):
    thumb_ready = Signal(str)
    video_size_ready = Signal(int, int)

    def __init__(self, video_path: str):
        super().__init__()
        self._path = video_path

    def run(self):
        fd, tmp = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        try:
            subprocess.run(
                ['ffmpeg', '-ss', '00:00:01', '-i', self._path,
                 '-vframes', '1', '-q:v', '2', '-y', tmp],
                capture_output=True, timeout=15
            )
            if os.path.getsize(tmp) > 0:
                self.thumb_ready.emit(tmp)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass

        # Probe video dimensions
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height',
                 '-of', 'csv=p=0', self._path],
                capture_output=True, text=True, timeout=10
            )
            parts = probe.stdout.strip().split(',')
            if len(parts) == 2:
                self.video_size_ready.emit(int(parts[0]), int(parts[1]))
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# PreviewCanvas — Overlay blur / sub / logo có kéo-thả
# ─────────────────────────────────────────────────────────────────────────────
class PreviewCanvas(QWidget):
    """Vẽ overlay blur/sub/logo lên thumbnail. Hỗ trợ kéo + resize."""

    blur_moved   = Signal(int, int)
    blur_resized = Signal(int, int, int, int)
    logo_moved   = Signal(int, int)
    sub_moved    = Signal(str, float, float)   # (anchor, margin_y_pct, margin_x_pct)

    _HANDLE = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ar = (16, 9)   # (width_ratio, height_ratio) default 16:9
        self.setMinimumSize(480, 270)
        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setStyleSheet("background:#111; border:2px solid #00f2ff;")
        self.setMouseTracking(True)

        self.blur_enabled = False
        self.blur_rect    = QRect(0, 0, 200, 40)
        # Zoom: 1.0=100%, center-crop simulation
        self._video_w  = 1920
        self._video_h  = 1080
        self._zoom     = 1.0

        self.sub_enabled       = False
        self.sub_text          = "Đây là phụ đề mẫu"
        self.sub_font_name     = "Arial"
        self.sub_size          = 18
        self.sub_color         = QColor("#FFFFFF")
        self.sub_border_color  = QColor("#000000")
        self.sub_border_w      = 2
        # Anchor-based positioning (replaces sub_custom_x/y + sub_position + sub_margin_v)
        self.sub_anchor        = "bottom-center"   # "top/middle/bottom-left/center/right"
        self.sub_margin_y_pct  = 0.10              # fraction from edge (0.0-0.5)
        self.sub_margin_x_pct  = 0.03
        self._sub_rect_cache   = QRect()
        self.logo_enabled  = False
        self.logo_pixmap: Optional[QPixmap] = None
        self.logo_rect     = QRect(10, 10, 80, 40)
        self.logo_opacity  = 0.8
        self.logo_custom_x = -1   # -1 = dùng position combo
        self.logo_custom_y = -1
        self._drag_target   = None
        self._drag_offset   = QPoint()
        self._resize_handle = None
        self._resize_origin      = QRect()
        self._resize_mouse_start = QPoint()
        self._thumb: Optional[QPixmap] = None

    def set_aspect(self, w: int, h: int):
        self._ar = (w, h)
        if w > 0 and h > 0:
            self._video_w = w
            self._video_h = h
        self.updateGeometry()
        self.update()

    def set_zoom(self, factor: float):
        self._zoom = max(1.0, min(5.0, factor))
        self.update()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return width * self._ar[1] // self._ar[0]

    def sizeHint(self) -> QSize:
        return QSize(640, self.heightForWidth(640))

    def minimumSizeHint(self) -> QSize:
        return QSize(320, self.heightForWidth(320))

    def set_thumb(self, pixmap: QPixmap):
        self._thumb = pixmap
        self.update()

    def update_blur(self, enabled, x, y, w, h):
        self.blur_enabled = enabled
        sw, sh = self._scale()
        self.blur_rect = QRect(int(x*sw), int(y*sh), int(w*sw), int(h*sh))
        self.update()

    def update_sub(self, enabled, text, font, size, color_hex, border_hex,
                   border_w, anchor="bottom-center", margin_y_pct=0.10, margin_x_pct=0.03):
        self.sub_enabled       = enabled
        self.sub_text          = text or "Đây là phụ đề mẫu"
        self.sub_font_name     = font
        self.sub_size          = max(8, int(size * self._scale()[1] * 1.2))
        self.sub_color         = QColor(color_hex)
        self.sub_border_color  = QColor(border_hex)
        self.sub_border_w      = border_w
        self.sub_anchor        = anchor
        self.sub_margin_y_pct  = margin_y_pct
        self.sub_margin_x_pct  = margin_x_pct
        self.update()

    def update_logo(self, enabled, path, position, opacity, logo_w=0, logo_h=0):
        self.logo_enabled = enabled
        self.logo_opacity = opacity / 100.0
        if path and os.path.isfile(path):
            target_w = logo_w if logo_w > 0 else 120
            target_h = logo_h if logo_h > 0 else -1
            if target_h > 0:
                self.logo_pixmap = QPixmap(path).scaled(
                    target_w, target_h,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
            else:
                self.logo_pixmap = QPixmap(path).scaledToWidth(
                    target_w, Qt.TransformationMode.SmoothTransformation)
        else:
            self.logo_pixmap = None
        w, h = self.width() or 480, self.height() or 270
        lw = self.logo_pixmap.width()  if self.logo_pixmap else 80
        lh = self.logo_pixmap.height() if self.logo_pixmap else 40
        if self.logo_custom_x >= 0 and self.logo_custom_y >= 0:
            pt = QPoint(self.logo_custom_x, self.logo_custom_y)
        else:
            pad = 10
            pos_map = {
                "Góc trên trái": QPoint(pad, pad),
                "Góc trên phải": QPoint(w-lw-pad, pad),
                "Góc dưới trái": QPoint(pad, h-lh-pad),
                "Góc dưới phải": QPoint(w-lw-pad, h-lh-pad),
                "Giữa":          QPoint((w-lw)//2, (h-lh)//2),
            }
            pt = pos_map.get(position, QPoint(10, 10))
        self.logo_rect = QRect(pt.x(), pt.y(), lw, lh)
        self.update()

    def _scale(self):
        return (
            (self.width()  or self._video_w) / self._video_w,
            (self.height() or self._video_h) / self._video_h,
        )

    def _get_blur_handles(self) -> dict:
        r = self.blur_rect
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        s, hf = self._HANDLE, self._HANDLE//2
        return {
            "tl": QRect(x-hf,   y-hf,   s, s),
            "tr": QRect(x+w-hf, y-hf,   s, s),
            "bl": QRect(x-hf,   y+h-hf, s, s),
            "br": QRect(x+w-hf, y+h-hf, s, s),
        }

    def _do_blur_resize(self, pos: QPoint):
        dx, dy = pos.x()-self._resize_mouse_start.x(), pos.y()-self._resize_mouse_start.y()
        orig = self._resize_origin
        h = self._resize_handle or ""
        nr = QRect(orig)
        if "l" in h: nr.setLeft(min(orig.x()+dx, orig.right()-20))
        elif "r" in h: nr.setRight(max(orig.right()+dx, orig.x()+20))
        if "t" in h: nr.setTop(min(orig.y()+dy, orig.bottom()-20))
        elif "b" in h: nr.setBottom(max(orig.bottom()+dy, orig.y()+20))
        self.blur_rect = nr
        sw, sh = self._scale()
        self.blur_resized.emit(int(nr.x()/sw), int(nr.y()/sh),
                               int(nr.width()/sw), int(nr.height()/sh))

    def _compute_sub_canvas_xy(self, text_w: int, text_h: int):
        """Canvas pixel position for subtitle based on anchor + percentage margins."""
        W, H = self.width() or 640, self.height() or 360
        parts = self.sub_anchor.split("-")
        v_part = parts[0] if len(parts) >= 1 else "bottom"
        h_part = parts[1] if len(parts) >= 2 else "center"
        my, mx = self.sub_margin_y_pct, self.sub_margin_x_pct
        if h_part == "left":
            cx = int(W * mx)
        elif h_part == "right":
            cx = max(0, int(W - text_w - W * mx))
        else:
            cx = (W - text_w) // 2
        if v_part == "top":
            cy = int(H * my) + text_h
        elif v_part == "middle":
            cy = H // 2 + text_h // 2
        else:
            cy = H - int(H * my)
        return cx, cy

    def _drag_pos_to_anchor(self, canvas_x: int, canvas_y: int,
                             text_w: int, text_h: int):
        """Convert drag canvas position to (anchor, margin_y_pct, margin_x_pct)."""
        W, H = max(1, self.width()), max(1, self.height())
        rx = canvas_x / W
        ry = canvas_y / H
        if rx < 0.33:
            h_part, mx = "left",   max(0.0, min(0.45, rx))
        elif rx > 0.67:
            h_part, mx = "right",  max(0.0, min(0.45, 1.0 - rx - text_w / W))
        else:
            h_part, mx = "center", 0.0
        if ry < 0.33:
            v_part, my = "top",    max(0.0, min(0.45, ry - text_h / H))
        elif ry > 0.67:
            v_part, my = "bottom", max(0.0, min(0.45, 1.0 - ry))
        else:
            v_part, my = "middle", 0.0
        return f"{v_part}-{h_part}", my, mx

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._thumb:
            if self._zoom > 1.001:
                tw, th = self._thumb.width(), self._thumb.height()
                cw, ch = int(tw / self._zoom), int(th / self._zoom)
                sx, sy = (tw - cw) // 2, (th - ch) // 2
                p.drawPixmap(self.rect(), self._thumb, QRect(sx, sy, cw, ch))
            else:
                p.drawPixmap(self.rect(), self._thumb)
        else:
            p.fillRect(self.rect(), QColor("#1a1a2e"))
            p.setPen(QColor("#444"))
            p.setFont(QFont("Arial", 11))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "📂 Chọn video để xem trước\n(hoặc chỉnh thông số bên phải)")

        if self.blur_enabled and not self.blur_rect.isEmpty():
            p.fillRect(self.blur_rect, QColor(0, 0, 0, 130))
            p.setPen(QPen(QColor("#00f2ff"), 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.blur_rect)
            p.setPen(QColor("#00f2ff"))
            p.setFont(QFont("Arial", 8))
            p.drawText(self.blur_rect.topLeft()+QPoint(4,12), "BLUR")
            p.setBrush(QBrush(QColor("#00f2ff")))
            p.setPen(QPen(QColor("#003344"), 1))
            for hr in self._get_blur_handles().values():
                p.drawRect(hr)

        if self.sub_enabled:
            font = QFont(self.sub_font_name, self.sub_size)
            p.setFont(font)
            fm = p.fontMetrics()
            text_w = fm.horizontalAdvance(self.sub_text)
            text_h = fm.height()
            cx, cy = self._compute_sub_canvas_xy(text_w, text_h)
            self._sub_rect_cache = QRect(cx - 4, cy - text_h, text_w + 8, text_h + 4)
            if self.sub_border_w > 0:
                p.setPen(self.sub_border_color)
                for ddx in range(-self.sub_border_w, self.sub_border_w+1):
                    for ddy in range(-self.sub_border_w, self.sub_border_w+1):
                        if ddx or ddy: p.drawText(cx+ddx, cy+ddy, self.sub_text)
            p.setPen(self.sub_color)
            p.drawText(cx, cy, self.sub_text)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#ffff00"), 1, Qt.PenStyle.DashLine))
            p.drawRect(self._sub_rect_cache)

        if self.logo_enabled and self.logo_pixmap:
            p.setOpacity(self.logo_opacity)
            p.drawPixmap(self.logo_rect, self.logo_pixmap)
            p.setOpacity(1.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#ffff00"), 1, Qt.PenStyle.DashLine))
            p.drawRect(self.logo_rect)
        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton: return
        pos = event.pos()
        if self.blur_enabled:
            for hname, hrect in self._get_blur_handles().items():
                if hrect.contains(pos):
                    self._drag_target        = "blur_resize"
                    self._resize_handle      = hname
                    self._resize_origin      = QRect(self.blur_rect)
                    self._resize_mouse_start = pos
                    return
            if self.blur_rect.contains(pos):
                self._drag_target = "blur"
                self._drag_offset = pos - self.blur_rect.topLeft()
                return
        if self.sub_enabled and not self._sub_rect_cache.isEmpty():
            if self._sub_rect_cache.contains(pos):
                self._drag_target = "sub"
                self._drag_offset = pos - self._sub_rect_cache.topLeft()
                return
        if self.logo_enabled and self.logo_rect.contains(pos):
            self._drag_target = "logo"
            self._drag_offset = pos - self.logo_rect.topLeft()

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if self._drag_target == "blur":
            self.blur_rect.moveTo(pos - self._drag_offset)
            sw, sh = self._scale()
            self.blur_moved.emit(int(self.blur_rect.x()/sw), int(self.blur_rect.y()/sh))
            self.update()
        elif self._drag_target == "blur_resize":
            self._do_blur_resize(pos); self.update()
        elif self._drag_target == "logo":
            self.logo_rect.moveTo(pos - self._drag_offset)
            self.logo_moved.emit(self.logo_rect.x(), self.logo_rect.y())
            self.update()
        elif self._drag_target == "sub":
            new_tl = pos - self._drag_offset
            cx = new_tl.x() + 4
            cy = new_tl.y() + self._sub_rect_cache.height() - 4
            text_w = self._sub_rect_cache.width() - 8
            text_h = self._sub_rect_cache.height() - 4
            anchor, my, mx = self._drag_pos_to_anchor(cx, cy, text_w, text_h)
            self.sub_anchor       = anchor
            self.sub_margin_y_pct = my
            self.sub_margin_x_pct = mx
            self.sub_moved.emit(anchor, my, mx)
            self.update()
        else:
            self._update_cursor(pos)

    def mouseReleaseEvent(self, event):
        self._drag_target = None; self._resize_handle = None

    def _update_cursor(self, pos: QPoint):
        if self.blur_enabled:
            for hname, hrect in self._get_blur_handles().items():
                if hrect.contains(pos):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor
                                   if hname in ("tl","br") else Qt.CursorShape.SizeBDiagCursor)
                    return
            if self.blur_rect.contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor); return
        if self.sub_enabled and not self._sub_rect_cache.isEmpty():
            if self._sub_rect_cache.contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor); return
        self.setCursor(Qt.CursorShape.ArrowCursor)


# ─────────────────────────────────────────────────────────────────────────────
# TimelineWidget — thanh timeline đơn giản
# ─────────────────────────────────────────────────────────────────────────────
class TimelineWidget(QWidget):
    seek_to = Signal(int)  # ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(88)
        self.setStyleSheet("background:#0d1117; border-top:1px solid #30363d;")
        self._duration = 0
        self._position = 0
        self._LABEL_W  = 48

    def set_duration(self, ms: int):
        self._duration = ms; self.update()

    def set_position(self, ms: int):
        self._position = ms; self.update()

    def _time_str(self, ms: int) -> str:
        s = ms // 1000
        return f"{s//60:02d}:{s%60:02d}"

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#0d1117"))

        if self._duration <= 0:
            p.setPen(QColor("#444"))
            p.setFont(QFont("Arial", 10))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "— Chưa có video —")
            p.end(); return

        W  = self.width()
        lw = self._LABEL_W
        tw = W - lw - 8
        ratio = self._position / self._duration if self._duration else 0

        TRACKS = [
            ("VIDEO", "#1a73e8"),
            ("VOICE", "#00c875"),
        ]
        TRACK_H = 22
        Y0 = 8

        for i, (label, color) in enumerate(TRACKS):
            y = Y0 + i * (TRACK_H + 8)
            # Label
            p.setPen(QColor("#6e7681"))
            p.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            p.drawText(2, y + TRACK_H - 4, label)
            # Track BG
            p.fillRect(lw, y, tw, TRACK_H, QColor("#161b22"))
            # Filled portion (video = full, voice = estimated)
            fill_w = int(tw * (ratio if i == 0 else min(ratio * 1.1, 1.0)))
            p.fillRect(lw, y, fill_w, TRACK_H, QColor(color).darker(160))
            # Border
            p.setPen(QPen(QColor(color).darker(120), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(lw, y, tw, TRACK_H)

        # Position marker
        x_marker = lw + int(tw * ratio)
        p.setPen(QPen(QColor("#ff4444"), 2))
        p.drawLine(x_marker, 4, x_marker, self.height() - 4)

        # Time labels
        p.setPen(QColor("#c9d1d9"))
        p.setFont(QFont("Arial", 9))
        time_y = Y0 + 2 * (TRACK_H + 8) + 12
        p.drawText(lw, time_y,
                   f"{self._time_str(self._position)}  /  {self._time_str(self._duration)}")

        p.end()

    def mousePressEvent(self, event):
        if self._duration > 0:
            x = event.pos().x() - self._LABEL_W
            ratio = max(0.0, min(1.0, x / (self.width() - self._LABEL_W - 8)))
            self.seek_to.emit(int(ratio * self._duration))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.mousePressEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# PreviewPanel — Màn hình xem trước persistent
# ─────────────────────────────────────────────────────────────────────────────
class PreviewPanel(QWidget):
    """
    Panel cố định bên phải cửa sổ chính.
    Hiển thị canvas overlay (blur/sub/logo) và video playback.
    Không ẩn khi chuyển tab.
    """

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self._thumb_thread: Optional[ThumbExtractThread] = None
        self._current_video = ""
        self._speed = 1.0

        # Media player
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)

        # Video widget (playback)
        self.video_widget = QVideoWidget()
        self.media_player.setVideoOutput(self.video_widget)

        # Canvas (thumbnail + overlay editing)
        self.canvas = PreviewCanvas()

        # Timeline
        self.timeline = TimelineWidget()

        # Connect media signals
        self.media_player.positionChanged.connect(self._on_position)
        self.media_player.durationChanged.connect(self._on_duration)
        self.media_player.playbackStateChanged.connect(self._on_state_changed)

        # Connect timeline seek
        self.timeline.seek_to.connect(self.media_player.setPosition)

        self._build_ui()

    # ── Build UI ─────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Header
        hdr = QLabel("🖥️  XEM TRƯỚC TRỰC TIẾP")
        hdr.setStyleSheet(
            "color:#00f2ff; font-weight:bold; font-size:12px; "
            "padding:4px 6px; background:#0d1117; border-bottom:1px solid #30363d;"
        )
        root.addWidget(hdr)

        # Stacked: page 0 = video, page 1 = canvas
        self._stack = QStackedWidget()
        self._stack.addWidget(self.video_widget)  # 0
        self._stack.addWidget(self.canvas)         # 1
        self._stack.setCurrentIndex(1)             # default: canvas (thumbnail mode)
        root.addWidget(self._stack, 1)

        # Zoom slider
        zoom_row = QHBoxLayout()
        zoom_lbl = QLabel("Zoom:")
        zoom_lbl.setStyleSheet("color:#aaa; font-size:11px; min-width:36px;")
        zoom_row.addWidget(zoom_lbl)
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(100, 300)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedHeight(20)
        self._zoom_slider.setToolTip("Zoom xem trước (100%=gốc, 300%=phóng to 3x)")
        self._zoom_val_lbl = QLabel("100%")
        self._zoom_val_lbl.setStyleSheet("color:#00f2ff; font-size:11px; min-width:38px;")
        self._zoom_slider.valueChanged.connect(self._on_zoom_changed)
        zoom_row.addWidget(self._zoom_slider, 1)
        zoom_row.addWidget(self._zoom_val_lbl)
        root.addLayout(zoom_row)

        # Aspect ratio + mode toggle
        mode_row = QHBoxLayout()
        ar_lbl = QLabel("AR:")
        ar_lbl.setStyleSheet("color:#888; font-size:11px;")
        mode_row.addWidget(ar_lbl)
        for ar_label, (aw, ah) in [("16:9", (16, 9)), ("9:16", (9, 16))]:
            btn = QPushButton(ar_label)
            btn.setFixedHeight(26)
            btn.setFixedWidth(46)
            btn.clicked.connect(lambda _=False, w=aw, h=ah: self._set_aspect(w, h))
            mode_row.addWidget(btn)
        mode_row.addSpacing(8)
        self._btn_edit_mode = QPushButton("✏️ Edit Overlay")
        self._btn_play_mode = QPushButton("▶ Xem Video")
        self._btn_edit_mode.setStyleSheet("background:#1a73e8; color:white; font-weight:bold;")
        self._btn_play_mode.setStyleSheet("background:#21262d;")
        self._btn_edit_mode.setFixedHeight(28)
        self._btn_play_mode.setFixedHeight(28)
        self._btn_edit_mode.clicked.connect(lambda: self._set_mode("edit"))
        self._btn_play_mode.clicked.connect(lambda: self._set_mode("play"))
        mode_row.addWidget(self._btn_edit_mode)
        mode_row.addWidget(self._btn_play_mode)
        root.addLayout(mode_row)

        # Playback controls
        ctrl = QHBoxLayout()
        self._btn_play_pause = QPushButton("▶")
        self._btn_play_pause.setFixedSize(44, 36)
        self._btn_play_pause.setStyleSheet("font-size:16px; font-weight:bold;")
        self._btn_play_pause.clicked.connect(self.toggle_play)

        self._btn_stop = QPushButton("■")
        self._btn_stop.setFixedSize(36, 36)
        self._btn_stop.clicked.connect(self.stop)

        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self._seek_slider.sliderReleased.connect(self._on_slider_released)
        self._seek_slider.sliderMoved.connect(self._on_slider_moved)
        self._is_seeking = False

        self._lbl_time = QLabel("00:00 / 00:00")
        self._lbl_time.setStyleSheet("color:#aaa; font-size:11px; min-width:90px;")

        ctrl.addWidget(self._btn_play_pause)
        ctrl.addWidget(self._btn_stop)
        ctrl.addWidget(self._seek_slider, 1)
        ctrl.addWidget(self._lbl_time)
        root.addLayout(ctrl)

        # Speed buttons
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Tốc độ:"))
        for sp in (0.5, 1.0, 1.25, 1.5, 2.0):
            btn = QPushButton(f"{sp}×")
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda _=False, s=sp: self._set_speed(s))
            speed_row.addWidget(btn)

        # Open video button
        btn_open = QPushButton("📂 Mở video")
        btn_open.setFixedHeight(26)
        btn_open.clicked.connect(self._open_video_dialog)
        speed_row.addStretch()
        speed_row.addWidget(btn_open)
        root.addLayout(speed_row)

        # Timeline
        root.addWidget(self.timeline)

        # Hint
        hint = QLabel("💡 Drag BLUR để di chuyển | Drag góc để resize | Drag TEXT để đổi vị trí")
        hint.setStyleSheet("color:#555; font-size:10px; padding:2px;")
        root.addWidget(hint)

    # ── Mode switch ──────────────────────────────────────────────

    def _set_aspect(self, w: int, h: int):
        self.canvas.set_aspect(w, h)
        self._stack.updateGeometry()

    def _on_zoom_changed(self, val: int):
        self._zoom_val_lbl.setText(f"{val}%")
        self.canvas.set_zoom(val / 100.0)

    def _set_mode(self, mode: str):
        if mode == "play":
            self._stack.setCurrentIndex(0)
            self._btn_play_mode.setStyleSheet("background:#1a73e8; color:white; font-weight:bold;")
            self._btn_edit_mode.setStyleSheet("background:#21262d;")
        else:
            self._stack.setCurrentIndex(1)
            self._btn_edit_mode.setStyleSheet("background:#1a73e8; color:white; font-weight:bold;")
            self._btn_play_mode.setStyleSheet("background:#21262d;")

    # ── Video loading ────────────────────────────────────────────

    def load_video(self, path: str):
        if not path or not os.path.isfile(path):
            return
        self._current_video = path
        self.media_player.setSource(QUrl.fromLocalFile(path))
        self._extract_thumbnail(path)

    def _extract_thumbnail(self, path: str):
        self._thumb_thread = ThumbExtractThread(path)
        self._thumb_thread.thumb_ready.connect(self._on_thumb_ready)
        self._thumb_thread.video_size_ready.connect(self._on_video_size)
        self._thumb_thread.start()

    def _on_thumb_ready(self, tmp_path: str):
        pix = QPixmap(tmp_path)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        if not pix.isNull():
            self.canvas.set_thumb(pix)

    def _on_video_size(self, w: int, h: int):
        if w > 0 and h > 0:
            self.canvas.set_aspect(w, h)
            self._stack.updateGeometry()

    def _open_video_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn Video", "", "Video (*.mp4 *.mkv *.avi *.mov)")
        if path:
            self.load_video(path)
            # Sync về dubbing tab
            try:
                self.main.tab_dubbing.txt_input.setText(path)
            except Exception:
                pass

    # ── Playback controls ────────────────────────────────────────

    def toggle_play(self):
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self._set_mode("play")
            self.media_player.play()

    def stop(self):
        self.media_player.stop()
        self._set_mode("edit")

    def _set_speed(self, speed: float):
        self._speed = speed
        self.media_player.setPlaybackRate(speed)

    # ── Slider helpers ───────────────────────────────────────────

    def _on_slider_pressed(self): self._is_seeking = True
    def _on_slider_released(self):
        self._is_seeking = False
        if self.media_player.duration():
            self.media_player.setPosition(
                int(self._seek_slider.value() / 1000 * self.media_player.duration()))

    def _on_slider_moved(self, val: int):
        if self.media_player.duration():
            self.media_player.setPosition(
                int(val / 1000 * self.media_player.duration()))

    # ── Media events ─────────────────────────────────────────────

    def _on_position(self, pos_ms: int):
        self.timeline.set_position(pos_ms)
        if not self._is_seeking and self.media_player.duration():
            self._seek_slider.setValue(
                int(pos_ms / self.media_player.duration() * 1000))
        pos_s = pos_ms // 1000
        dur_s = self.media_player.duration() // 1000
        self._lbl_time.setText(
            f"{pos_s//60:02d}:{pos_s%60:02d} / {dur_s//60:02d}:{dur_s%60:02d}")

    def _on_duration(self, dur_ms: int):
        self.timeline.set_duration(dur_ms)

    def _on_state_changed(self, state):
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._btn_play_pause.setText("⏸" if is_playing else "▶")
        if not is_playing and self._stack.currentIndex() == 0:
            self._set_mode("edit")
