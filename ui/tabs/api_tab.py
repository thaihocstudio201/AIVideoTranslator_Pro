"""ui/tabs/api_tab.py — Quản lý đa nền tảng AI cho dịch thuật phụ đề."""
from __future__ import annotations

import json
import os
import requests
from pathlib import Path

import google.generativeai as genai
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QTextEdit, QPushButton, QComboBox, QTabWidget,
    QMessageBox, QSizePolicy,
)
from utils.custom_logger import sys_log

# ── Metadata từng nền tảng ────────────────────────────────────────────────────
PLATFORM_META: dict[str, dict] = {
    "gemini": {
        "label":   "🌟 Gemini",
        "hint":    "aistudio.google.com  →  Get API Key  (miễn phí)",
        "ph":      "Paste Gemini API Keys — mỗi dòng 1 key (hỗ trợ xoay vòng)...",
        "has_key": True,
    },
    "openai": {
        "label":   "🤖 OpenAI",
        "hint":    "platform.openai.com/api-keys",
        "ph":      "sk-...",
        "has_key": True,
    },
    "groq": {
        "label":   "⚡ Groq (Free)",
        "hint":    "console.groq.com  —  miễn phí, rất nhanh",
        "ph":      "gsk_...",
        "has_key": True,
    },
    "deepseek": {
        "label":   "🐋 DeepSeek",
        "hint":    "platform.deepseek.com  —  rất tốt cho Trung→Việt",
        "ph":      "sk-...",
        "has_key": True,
    },
    "openrouter": {
        "label":   "🌐 OpenRouter",
        "hint":    "openrouter.ai/keys  —  truy cập 200+ models qua 1 key",
        "ph":      "sk-or-...",
        "has_key": True,
    },
    "ollama": {
        "label":   "🏠 Ollama (Local)",
        "hint":    "Chạy:  ollama serve   (port 11434, không cần key)",
        "ph":      "",
        "has_key": False,
    },
}

PLATFORM_ORDER = ["gemini", "openai", "groq", "deepseek", "openrouter", "ollama"]

PLATFORM_BASE_URLS: dict[str, str] = {
    "openai":     "https://api.openai.com/v1",
    "groq":       "https://api.groq.com/openai/v1",
    "deepseek":   "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

_DEEPSEEK_MODELS = ["deepseek-chat", "deepseek-reasoner"]


# ── Background thread để load models không block UI ──────────────────────────
class _ModelLoader(QThread):
    done = Signal(list)  # list[str]

    def __init__(self, platform: str, api_key: str):
        super().__init__()
        self._platform = platform
        self._key = api_key.strip()

    def run(self) -> None:
        try:
            self.done.emit(self._fetch())
        except Exception as e:
            sys_log.error(f"ModelLoader {self._platform}: {e}")
            self.done.emit([])

    def _fetch(self) -> list[str]:
        p = self._platform
        k = self._key

        if p == "gemini":
            if not k:
                return []
            genai.configure(api_key=k)
            skip = ("embedding", "aqa", "gemini-1.0")
            out = []
            for m in genai.list_models():
                if "generateContent" not in m.supported_generation_methods:
                    continue
                name = m.name.split("/")[-1]
                if any(s in name for s in skip):
                    continue
                out.append(name)
            return sorted(out, reverse=True)

        if p == "ollama":
            try:
                r = requests.get("http://localhost:11434/api/tags", timeout=5)
                if r.status_code == 200:
                    return [m["name"] for m in r.json().get("models", [])]
            except Exception:
                pass
            return []

        if p == "deepseek":
            return list(_DEEPSEEK_MODELS)

        base = PLATFORM_BASE_URLS.get(p, "")
        if not base or not k:
            return []
        r = requests.get(f"{base}/models",
                         headers={"Authorization": f"Bearer {k}"}, timeout=15)
        if r.status_code != 200:
            return []
        ids: list[str] = [m["id"] for m in r.json().get("data", [])]
        if p == "openai":
            kw = ("gpt-4", "gpt-3.5", "o1", "o3", "o4")
            return sorted(i for i in ids if any(i.startswith(k2) for k2 in kw))
        if p == "groq":
            pref = {"llama-3.3-70b-versatile", "llama-3.1-70b-versatile",
                    "llama3-70b-8192", "mixtral-8x7b-32768", "gemma2-9b-it"}
            return [i for i in ids if i in pref] + sorted(i for i in ids if i not in pref)
        if p == "openrouter":
            kw2 = ("gemini", "gpt-4", "claude", "llama-3", "qwen", "deepseek", "mistral")
            return sorted(i for i in ids if any(k3 in i.lower() for k3 in kw2))[:40]
        return sorted(ids)


# ── Main Tab ──────────────────────────────────────────────────────────────────
class ApiManagementTab(QWidget):
    """Tab quản lý API keys và models cho tất cả nền tảng AI."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.active_platform: str = ""
        self.active_model: str = ""

        # Widgets theo platform
        self._key_inputs:  dict[str, QTextEdit] = {}
        self._model_cbs:   dict[str, QComboBox] = {}
        self._status_lbls: dict[str, QLabel]    = {}
        self._loaders:     dict[str, _ModelLoader] = {}

        self._build_ui()
        self._load_saved_config()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(12, 12, 12, 12)

        hdr = QLabel("🔐  QUẢN LÝ API ĐA NỀN TẢNG  —  DỊCH THUẬT AI")
        hdr.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#00f2ff; "
            "padding:8px 4px; border-bottom:1px solid #30363d;"
        )
        root.addWidget(hdr)

        self._tabs = QTabWidget()
        for pid in PLATFORM_ORDER:
            meta = PLATFORM_META[pid]
            panel = self._make_panel(pid, meta)
            self._tabs.addTab(panel, meta["label"])
        root.addWidget(self._tabs, 1)

        # Active status
        act_grp = QGroupBox("📡 ĐANG KÍCH HOẠT")
        act_lo = QHBoxLayout(act_grp)
        self._lbl_active = QLabel("—  Chưa kích hoạt  —")
        self._lbl_active.setStyleSheet("color:#ff9500; font-weight:bold; font-size:13px;")
        act_lo.addWidget(self._lbl_active)
        root.addWidget(act_grp)

        # Buttons row
        btn_row = QHBoxLayout()
        self._btn_activate = QPushButton("✅  KÍCH HOẠT PLATFORM NÀY & LƯU")
        self._btn_activate.setStyleSheet(
            "background:#00ff88; color:#000; font-size:14px; "
            "padding:10px; font-weight:bold; border-radius:6px;"
        )
        self._btn_activate.clicked.connect(self._activate_current)

        btn_info = QPushButton("ℹ️  Gợi ý models cho từng nền tảng")
        btn_info.setStyleSheet("font-size:12px; padding:8px;")
        btn_info.clicked.connect(self._show_platform_info)

        btn_row.addWidget(self._btn_activate, 2)
        btn_row.addWidget(btn_info, 1)
        root.addLayout(btn_row)

    def _make_panel(self, pid: str, meta: dict) -> QWidget:
        panel = QWidget()
        lo = QVBoxLayout(panel)
        lo.setSpacing(8)
        lo.setContentsMargins(10, 10, 10, 10)

        # Hint link
        hint = QLabel(f"🔗  {meta['hint']}")
        hint.setStyleSheet("color:#6e7681; font-size:12px;")
        lo.addWidget(hint)

        # API key input
        if meta["has_key"]:
            key_grp = QGroupBox("🔑 API Keys  (mỗi dòng 1 key — hỗ trợ xoay vòng)")
            key_lo = QVBoxLayout(key_grp)
            txt = QTextEdit()
            txt.setMaximumHeight(90)
            txt.setPlaceholderText(meta["ph"])
            key_lo.addWidget(txt)
            lo.addWidget(key_grp)
            self._key_inputs[pid] = txt
        else:
            info = QLabel("✅  Không cần API key — kết nối qua localhost:11434")
            info.setStyleSheet("color:#00ff88; padding:8px;")
            lo.addWidget(info)

        # Load models
        mdl_grp = QGroupBox("🤖 Models")
        mdl_lo = QVBoxLayout(mdl_grp)

        h_load = QHBoxLayout()
        btn_load = QPushButton("🔍  Load danh sách models")
        btn_load.clicked.connect(lambda _=False, p=pid: self._load_models(p))

        status = QLabel("— chưa load —")
        status.setStyleSheet("color:#6e7681; font-size:12px;")
        status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h_load.addWidget(btn_load)
        h_load.addWidget(status)
        mdl_lo.addLayout(h_load)

        cb = QComboBox()
        cb.setMinimumHeight(30)
        cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        mdl_lo.addWidget(cb)
        lo.addWidget(mdl_grp)

        self._model_cbs[pid]   = cb
        self._status_lbls[pid] = status

        lo.addStretch()
        return panel

    # ── Load models ─────────────────────────────────────────────────────────

    def _load_models(self, pid: str) -> None:
        key = self._get_first_key(pid)
        status = self._status_lbls[pid]
        status.setText("⏳  Đang load...")
        status.setStyleSheet("color:#aaa; font-size:12px;")

        loader = _ModelLoader(pid, key)
        loader.done.connect(lambda models, p=pid: self._on_models_loaded(p, models))
        self._loaders[pid] = loader  # prevent GC
        loader.start()

    def _on_models_loaded(self, pid: str, models: list[str]) -> None:
        cb     = self._model_cbs[pid]
        status = self._status_lbls[pid]
        cb.clear()
        if models:
            cb.addItems(models)
            status.setText(f"✅  {len(models)} models")
            status.setStyleSheet("color:#00ff88; font-size:12px;")
        else:
            status.setText("❌  Không load được — kiểm tra key / kết nối")
            status.setStyleSheet("color:#ff4444; font-size:12px;")

    # ── Activate & Save ──────────────────────────────────────────────────────

    def _activate_current(self) -> None:
        pid = PLATFORM_ORDER[self._tabs.currentIndex()]
        model = self._model_cbs[pid].currentText().strip()
        if not model:
            QMessageBox.warning(self, "Chưa chọn model",
                                "Hãy bấm 'Load models' và chọn model trước!")
            return

        keys = self._get_keys_list(pid)
        if PLATFORM_META[pid]["has_key"] and not keys:
            QMessageBox.warning(self, "Thiếu API key",
                                "Vui lòng nhập API key trước khi kích hoạt!")
            return

        self.active_platform = pid
        self.active_model    = model
        label = PLATFORM_META[pid]["label"]
        self._lbl_active.setText(f"{label}  ›  {model}  ({len(keys)} key(s))")
        self._lbl_active.setStyleSheet("color:#00ff88; font-weight:bold; font-size:13px;")

        self._save_to_config(pid, model, keys)
        sys_log.info(f"✅ API kích hoạt: [{pid.upper()}] {model} ({len(keys)} keys)")
        QMessageBox.information(
            self, "Kích hoạt thành công",
            f"Đã kích hoạt:\n  Nền tảng: {label}\n  Model: {model}\n  Keys: {len(keys)}"
        )

    def _save_to_config(self, pid: str, model: str, keys: list[str]) -> None:
        """Lưu vào api_config.json và sync lên MainWindow."""
        cfg_path = Path("config") / "api_config.json"
        try:
            existing: dict = {}
            if cfg_path.exists():
                with open(cfg_path, encoding="utf-8") as f:
                    existing = json.load(f)
        except Exception:
            existing = {}

        existing["ai_platform"]    = pid
        existing["default_model"]  = model
        existing["api_keys"]       = keys  # backward compat với pipeline

        # Lưu keys theo nền tảng (để khôi phục sau)
        pkeys: dict = existing.get("platform_keys", {})
        pkeys[pid]  = keys
        existing["platform_keys"] = pkeys

        Path("config").mkdir(exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        # Sync lên MainWindow
        self.main.valid_apis     = [{"key": k} for k in keys]
        self.main.selected_model = model

    # ── Config persistence ───────────────────────────────────────────────────

    def _load_saved_config(self) -> None:
        """Khôi phục keys và model đã lưu từ api_config.json."""
        cfg_path = Path("config") / "api_config.json"
        if not cfg_path.exists():
            return
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            return

        pkeys: dict = cfg.get("platform_keys", {})
        active_pid  = cfg.get("ai_platform", "")
        active_mdl  = cfg.get("default_model", "")

        for pid, keys in pkeys.items():
            if pid in self._key_inputs and isinstance(keys, list):
                self._key_inputs[pid].setPlainText("\n".join(keys))

        # Khôi phục platform đang active
        if active_pid and active_pid in PLATFORM_ORDER:
            idx = PLATFORM_ORDER.index(active_pid)
            self._tabs.setCurrentIndex(idx)
            self.active_platform = active_pid
            self.active_model    = active_mdl

            # Load models và pre-select model đã lưu
            if active_mdl:
                cb = self._model_cbs[active_pid]
                cb.addItem(active_mdl)
                label = PLATFORM_META[active_pid]["label"]
                keys_count = len(pkeys.get(active_pid, []))
                self._lbl_active.setText(f"{label}  ›  {active_mdl}  ({keys_count} key(s))")
                self._lbl_active.setStyleSheet(
                    "color:#00ff88; font-weight:bold; font-size:13px;"
                )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_first_key(self, pid: str) -> str:
        keys = self._get_keys_list(pid)
        return keys[0] if keys else ""

    def _get_keys_list(self, pid: str) -> list[str]:
        if pid not in self._key_inputs:
            return []
        raw = self._key_inputs[pid].toPlainText()
        return [k.strip() for k in raw.splitlines() if k.strip()]

    def get_active_keys(self) -> list[str]:
        """Trả về keys của platform đang active (gọi từ MainWindow)."""
        return self._get_keys_list(self.active_platform)

    # ── Info dialog ──────────────────────────────────────────────────────────

    def _show_platform_info(self) -> None:
        info = (
            "📋  GỢI Ý MODELS TỐT NHẤT CHO DỊCH PHỤ ĐỀ\n"
            "═══════════════════════════════════════\n\n"
            "🌟 GEMINI  (Khuyên dùng)\n"
            "  • gemini-2.0-flash          → Nhanh, rẻ, chất lượng cao\n"
            "  • gemini-1.5-flash          → Ổn định, context dài\n"
            "  • gemini-1.5-pro            → Chất lượng cao nhất\n\n"
            "⚡ GROQ  (Miễn phí, rất nhanh)\n"
            "  • llama-3.3-70b-versatile   → Tốt nhất trên Groq\n"
            "  • mixtral-8x7b-32768        → Context 32k, tiết kiệm\n\n"
            "🐋 DEEPSEEK  (Tốt cho Trung→Việt)\n"
            "  • deepseek-chat             → Nhanh, rẻ, hiểu tiếng Trung sâu\n"
            "  • deepseek-reasoner         → Chất lượng cao hơn (chậm hơn)\n\n"
            "🤖 OPENAI\n"
            "  • gpt-4o-mini               → Cân bằng tốt giữa giá và chất lượng\n"
            "  • gpt-4o                    → Chất lượng cao nhất, tốn token\n\n"
            "🌐 OPENROUTER  (Aggregator)\n"
            "  • google/gemini-flash-1.5   → Cheap, nhanh\n"
            "  • meta-llama/llama-3.3-70b-instruct → Free tier\n\n"
            "🏠 OLLAMA  (Local, miễn phí)\n"
            "  • qwen2.5:14b               → Tốt nhất cho Trung→Việt local\n"
            "  • qwen2.5:7b                → Nhẹ hơn, vẫn ổn\n"
        )
        msg = QMessageBox(self)
        msg.setWindowTitle("Gợi ý Models")
        msg.setText(info)
        msg.setStyleSheet("QLabel { font-family: Consolas, monospace; font-size: 12px; }")
        msg.exec()
