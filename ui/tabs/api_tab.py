# ui/tabs/api_tab.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel, QTextEdit, QHBoxLayout, QPushButton, QComboBox

class ApiManagementTab(QWidget):
    def __init__(self, ai_service, log_callback):
        super().__init__()
        self.ai = ai_service
        self.log = log_callback
        self.valid_apis = []

        lo = QVBoxLayout(self)
        lo.setContentsMargins(50, 40, 50, 40)
        
        grp = QGroupBox("🔐 QUẢN LÝ TOKEN & XOAY VÒNG API (GEMINI 2.0+ ONLY)")
        l_grp = QVBoxLayout(grp)
        l_grp.setContentsMargins(30, 40, 30, 30)
        l_grp.setSpacing(15)

        l_grp.addWidget(QLabel("Danh sách Gemini API Keys (Dán mỗi dòng 1 Key):"))
        self.txt_api_list = QTextEdit()
        self.txt_api_list.setPlaceholderText("Paste danh sách API Keys tại đây...")
        self.txt_api_list.setStyleSheet("background-color: #0b0e14; color: #00ff88; font-size: 14px;")
        l_grp.addWidget(self.txt_api_list)

        h_ctrl = QHBoxLayout()
        self.btn_test = QPushButton("🔍 KIỂM TRA & LOAD MODELS 2.0+")
        self.btn_test.clicked.connect(self.check_api_rotation)
        
        self.cb_models = QComboBox()
        self.cb_models.setMinimumWidth(350)
        h_ctrl.addWidget(self.btn_test, 1); h_ctrl.addWidget(self.cb_models, 2)
        l_grp.addLayout(h_ctrl)

        self.btn_save = QPushButton("💾 KÍCH HOẠT HỆ THỐNG XOAY VÒNG API")
        self.btn_save.setStyleSheet("background: #00ff88; color: black; font-weight: bold;")
        l_grp.addWidget(self.btn_save)
        
        lo.addWidget(grp); lo.addStretch()

    def check_api_rotation(self):
        # (Logic kiểm tra API Gemini 2.0+ đã viết ở các lượt trước)
        pass