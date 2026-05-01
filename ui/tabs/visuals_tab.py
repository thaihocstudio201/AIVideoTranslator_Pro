from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QPushButton, QComboBox, QLabel, QSlider, QCheckBox, QLineEdit
from PySide6.QtCore import Qt


class VisualsTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(15)

        # Cột 1: Phụ đề
        c1 = QVBoxLayout()
        g1 = QGroupBox("🖼️ HÌNH ẢNH & TIÊU ĐỀ")
        l1 = QVBoxLayout(g1)
        l1.setSpacing(12)

        btn_color = QPushButton("🎨 CHỌN MÀU PHỤ ĐỀ")
        btn_color.clicked.connect(self.main.choose_sub_color)
        l1.addWidget(btn_color)

        self.cb_font = QComboBox()
        self.cb_font.addItems(["Arial", "Impact", "Tahoma", "Verdana"])
        l1.addWidget(QLabel("Font chữ:"))
        l1.addWidget(self.cb_font)

        self.sld_sub_size = QSlider(Qt.Orientation.Horizontal)
        l1.addWidget(QLabel("Cỡ chữ Sub:"))
        l1.addWidget(self.sld_sub_size)

        self.chk_blur = QCheckBox("Bật Hộp Mờ Che Sub Cũ")
        l1.addWidget(self.chk_blur)

        self.txt_top = QLineEdit()
        self.txt_top.setPlaceholderText("Tiêu đề Viền Trên...")
        self.txt_bot = QLineEdit()
        self.txt_bot.setPlaceholderText("Tiêu đề Viền Dưới...")
        l1.addWidget(self.txt_top)
        l1.addWidget(self.txt_bot)

        c1.addWidget(g1)
        c1.addStretch()
        layout.addLayout(c1)

        # Cột 2: Lách bản quyền
        c2 = QVBoxLayout()
        g2 = QGroupBox("⚙️ LÁCH BẢN QUYỀN CHUYÊN SÂU")
        l2 = QVBoxLayout(g2)
        l2.setSpacing(12)

        self.chk_exif = QCheckBox("Tẩy trắng thông tin EXIF (Metadata)")
        self.chk_md5 = QCheckBox("Băm lại mã hiệu MD5 chống quét")
        l2.addWidget(self.chk_exif)
        l2.addWidget(self.chk_md5)

        self.cb_fps = QComboBox()
        self.cb_fps.addItems(["Gốc", "24 fps", "30 fps", "60 fps"])
        l2.addWidget(QLabel("Ép khung hình FPS:"))
        l2.addWidget(self.cb_fps)

        self.cb_pan = QComboBox()
        self.cb_pan.addItems(["Tắt", "Lia máy (Pan x1)", "Lia máy (Pan x2)"])
        l2.addWidget(QLabel("Lia máy (Bản quyền nặng):"))
        l2.addWidget(self.cb_pan)

        self.cb_color = QComboBox()
        self.cb_color.addItems(["Gốc", "Rạp phim", "Đậm đà", "Trắng đen"])
        l2.addWidget(QLabel("Bộ lọc màu (Filter):"))
        l2.addWidget(self.cb_color)

        c2.addWidget(g2)
        c2.addStretch()
        layout.addLayout(c2)

        # Cột 3: Extra & Render
        c3 = QVBoxLayout()
        g3 = QGroupBox("🔊 ÂM THANH & RENDER")
        l3 = QVBoxLayout(g3)
        l3.setSpacing(12)

        l3.addWidget(QPushButton("📂 Chọn Video Intro"))
        l3.addWidget(QPushButton("📂 Chọn Video Outro"))
        l3.addWidget(QPushButton("📂 CHÈN LOGO KÉO THẢ"))

        self.sld_pitch = QSlider(Qt.Orientation.Horizontal)
        l3.addWidget(QLabel("Tone Nhạc Nền (Pitch):"))
        l3.addWidget(self.sld_pitch)

        self.cb_res = QComboBox()
        self.cb_res.addItems(["Gốc", "1080p", "720p", "480p"])
        l3.addWidget(QLabel("Chất lượng Render:"))
        l3.addWidget(self.cb_res)

        btn_save_fx = QPushButton("💾 LƯU CẤU HÌNH LÁCH")
        btn_save_fx.setStyleSheet("background-color: #1a73e8; color: white;")
        l3.addWidget(btn_save_fx)

        c3.addWidget(g3)
        c3.addStretch()
        layout.addLayout(c3)