# ui/style_sheets.py
MAIN_STYLE = """
    QMainWindow { background-color: #0b0e14; }
    QWidget { color: #c9d1d9; font-family: Arial; }
    QGroupBox {
        border: 1px solid #30363d; border-radius: 8px; margin-top: 3ex;
        font-weight: bold; color: #00f2ff;
    }
    QGroupBox::title {
        subcontrol-origin: margin; subcontrol-position: top left;
        left: 15px; padding: 0 5px; background-color: #0b0e14;
    }
    QLineEdit, QComboBox, QListWidget, QTextEdit {
        background-color: #161b22; border: 1px solid #30363d;
        padding: 5px; border-radius: 4px;
    }
    QPushButton {
        background-color: #21262d; border: 1px solid #30363d;
        padding: 8px; border-radius: 5px; font-weight: bold;
    }
    QPushButton:hover { background-color: #30363d; border-color: #ff00ff; }
    QTabWidget::pane { border: 1px solid #30363d; background-color: #0b0e14; }
    QTabBar::tab {
        background-color: #161b22; color: gray; padding: 12px 25px; font-weight: bold;
    }
    QTabBar::tab:selected {
        background-color: #ff00ff; color: white; border-bottom: 2px solid white;
    }
    QListWidget::item { padding: 8px; border-bottom: 1px solid #21262d; }
    QListWidget::item:selected { background-color: #1a73e8; color: white; }
    QSlider::handle:horizontal {
        background: #00f2ff; border: 1px solid #fff; width: 14px;
        margin: -5px 0; border-radius: 7px;
    }
"""