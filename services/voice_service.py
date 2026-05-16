"""
services/voice_service.py
Fix giọng không tự nhiên:
  - Thêm Edge-TTS làm ENGINE PRIMARY cho Vietnamese (giọng native chuẩn)
  - VieNeu-TTS làm LOCAL ENGINE (offline, clone voice)
  - Auto fallback: Edge-TTS → VieNeu → pyttsx3
  - Trim speed để giọng tự nhiên hơn
"""

import os
import sys
import json
import asyncio
import torch
from typing import Optional, Any, List, Dict, Tuple

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from utils.custom_logger import sys_log

HF_TOKEN      = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
PROFILES_PATH = os.path.join(project_root, "config", "voice_profiles.json")

FEMALE_HINTS = ["ngọc", "lý", "nữ", "female", "woman", "girl", "hoài", "my", "lan", "hoa"]

# Edge-TTS: giọng tiếng Việt chuẩn (native quality)
EDGE_TTS_VOICES = {
    "Vietnamese": [
        ("vi-VN-HoaiMyNeural",  "Hoài My (Nữ - Chuẩn)"),    # ⭐ Tốt nhất
        ("vi-VN-NamMinhNeural", "Nam Minh (Nam - Chuẩn)"),
    ],
    "English":  [("en-US-AvaNeural",      "Ava (Female)")],
    "Japanese": [("ja-JP-NanamiNeural",   "Nanami (Female)")],
    "Korean":   [("ko-KR-SunHiNeural",    "SunHi (Female)")],
    "Thai":     [("th-TH-PremwadeeNeural","Premwadee (Female)")],
}


_instance: "Optional[VoiceService]" = None


class VoiceService:
    """Singleton — gọi VoiceService() nhiều lần vẫn trả về cùng 1 instance."""

    def __new__(cls):
        global _instance
        if _instance is None:
            _instance = super().__new__(cls)
            _instance._initialized = False
        return _instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.tts_model: Any    = None
        self.current_voice_data: Any = None
        self.current_voice_name: str = "default"

        # Cache & state
        self._preset_cache: Dict[str, Any]              = {}
        self._preset_list:  List[Tuple[str, str]]       = []
        self._profiles:     Dict[str, Dict[str, Any]]   = {}

        # Engine mode: "edge_tts" | "vieneu" | "pyttsx3"
        self._engine = "edge_tts"

        sys_log.info("🔄 Đang khởi tạo VoiceService...")
        self._init_edge_tts()
        self._init_vieneu()
        self._load_profiles_from_disk()
        sys_log.info(f"✅ Engine chính: {self._engine.upper()}")

    # ═══════════════════════════════════════════════════════════
    # INIT ENGINES
    # ═══════════════════════════════════════════════════════════
    def _init_edge_tts(self):
        """Edge-TTS: giọng Việt chuẩn nhất, online."""
        try:
            import edge_tts  # type: ignore
            self._engine = "edge_tts"
            sys_log.info("✅ Edge-TTS sẵn sàng (giọng Việt chuẩn)")
        except ImportError:
            sys_log.warning("⚠️ edge-tts chưa cài. Chạy: pip install edge-tts")
            self._engine = "vieneu"

    def _init_vieneu(self):
        """VieNeu-TTS: offline, hỗ trợ clone voice."""
        try:
            from vieneu import Vieneu  # type: ignore
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.tts_model = Vieneu(
                model_name="vienneu/vienneu-2.4.3",
                device=device,
                hf_token=HF_TOKEN
            )
            sys_log.info(f"✅ VieNeu-TTS sẵn sàng ({device.upper()}) — dùng cho clone voice")
            self._load_preset_voices()
            self._set_default_female_voice()
        except ImportError:
            sys_log.warning("⚠️ vieneu chưa cài. Clone voice không khả dụng.")
            self.tts_model = None
        except Exception as e:
            sys_log.warning(f"⚠️ VieNeu load lỗi: {e}")
            self.tts_model = None

    # ═══════════════════════════════════════════════════════════
    # PRESET VOICES (VieNeu)
    # ═══════════════════════════════════════════════════════════
    def _load_preset_voices(self):
        if not self.tts_model:
            return
        try:
            voices = self.tts_model.list_preset_voices()
            self._preset_list = voices if voices else []
            for desc, vid in self._preset_list:
                data = self.tts_model.get_preset_voice(vid)
                self._preset_cache[vid]  = data
                self._preset_cache[desc] = data
            sys_log.info(f"  VieNeu presets: {[d for d,_ in self._preset_list]}")
        except Exception as e:
            sys_log.warning(f"Không load VieNeu presets: {e}")

    def _set_default_female_voice(self):
        for desc, vid in self._preset_list:
            if any(h in desc.lower() for h in FEMALE_HINTS):
                self.current_voice_data = self._preset_cache.get(vid)
                self.current_voice_name = desc
                return
        if self._preset_list:
            desc, vid = self._preset_list[0]
            self.current_voice_data = self._preset_cache.get(vid)
            self.current_voice_name = desc

    def list_voices(self) -> List[Tuple[str, str]]:
        """Trả về danh sách voices: Edge-TTS (ưu tiên) + VieNeu presets."""
        result = []
        # Edge-TTS voices
        for lang, vlist in EDGE_TTS_VOICES.items():
            for vid, label in vlist:
                result.append((f"[Edge] {label}", vid))
        # VieNeu presets
        female = [(f"[VieNeu] {d}", v) for d,v in self._preset_list if any(h in d.lower() for h in FEMALE_HINTS)]
        other  = [(f"[VieNeu] {d}", v) for d,v in self._preset_list if not any(h in d.lower() for h in FEMALE_HINTS)]
        return result + female + other

    # ═══════════════════════════════════════════════════════════
    # VOICE PROFILES
    # ═══════════════════════════════════════════════════════════
    def _load_profiles_from_disk(self):
        try:
            if os.path.exists(PROFILES_PATH):
                with open(PROFILES_PATH, "r", encoding="utf-8") as f:
                    self._profiles = json.load(f)
                sys_log.info(f"✅ {len(self._profiles)} voice profiles đã tải")
        except Exception as e:
            sys_log.warning(f"Không tải voice profiles: {e}")
            self._profiles = {}

    def _save_profiles_to_disk(self):
        try:
            os.makedirs(os.path.dirname(PROFILES_PATH), exist_ok=True)
            with open(PROFILES_PATH, "w", encoding="utf-8") as f:
                json.dump(self._profiles, f, ensure_ascii=False, indent=2)
        except Exception as e:
            sys_log.error(f"Không lưu voice profiles: {e}")

    def save_clone_profile(self, name: str, wav_path: str) -> bool:
        if not os.path.isfile(wav_path):
            return False
        self._profiles[name] = {"type": "clone", "value": wav_path}
        self._save_profiles_to_disk()
        sys_log.info(f"💾 Profile clone '{name}' → {wav_path}")
        return True

    def save_preset_profile(self, name: str, voice_id: str) -> bool:
        self._profiles[name] = {"type": "preset", "value": voice_id}
        self._save_profiles_to_disk()
        return True

    def delete_profile(self, name: str) -> bool:
        if name in self._profiles:
            del self._profiles[name]
            self._save_profiles_to_disk()
            return True
        return False

    def list_profiles(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._profiles)

    # ═══════════════════════════════════════════════════════════
    # RUN TTS — ĐIỂM VÀO CHÍNH
    # ═══════════════════════════════════════════════════════════
    def run_tts(self, text: str, voice: Optional[str] = None,
                output_path: str = "temp_voice.wav",
                strict: bool = False) -> bool:
        """
        voice=None                → Edge-TTS giọng nữ VN (HoaiMyNeural) — tự nhiên nhất
        voice="vi-VN-HoaiMyNeural"→ Edge-TTS giọng cụ thể
        voice="path/to/file.wav"  → Clone voice (VieNeu)
        voice="tên profile"       → Profile đã lưu
        voice="Ngọc"              → VieNeu preset

        strict=True: KHÔNG fallback sang engine khác khi lỗi — đảm bảo đồng nhất giọng.
                     Dùng khi tạo hàng loạt (batch TTS) để tránh lẫn giọng.
        """
        if not text or not text.strip():
            return False

        text = self._clean_tts_text(text)
        if not text:
            return False

        # ── Phân giải loại voice ──────────────────────────────
        is_clone   = voice and os.path.isfile(voice) and voice.lower().endswith(('.wav','.mp3','.flac'))
        is_profile = voice and voice in self._profiles
        is_edge    = voice and voice.startswith("vi-VN-") or voice and "-Neural" in (voice or "")
        is_edge_default = voice is None and self._engine == "edge_tts"

        # Clone voice → bắt buộc dùng VieNeu
        if is_clone or (is_profile and self._profiles.get(voice or "", {}).get("type") == "clone"):
            return self._run_vieneu(text, voice, output_path, strict=strict)

        # Edge-TTS: default hoặc chỉ định Edge voice
        if is_edge_default or is_edge:
            edge_voice = voice or "vi-VN-HoaiMyNeural"
            return self._run_edge_tts(text, edge_voice, output_path, strict=strict)

        # Profile preset
        if is_profile:
            profile = self._profiles[voice]  # type: ignore
            if profile["type"] == "preset":
                vid = profile["value"]
                # Edge-TTS preset
                if "-Neural" in vid:
                    return self._run_edge_tts(text, vid, output_path, strict=strict)
                # VieNeu preset
                return self._run_vieneu(text, vid, output_path, strict=strict)

        # VieNeu preset name/id
        if self.tts_model:
            return self._run_vieneu(text, voice, output_path, strict=strict)

        # Last resort (chỉ khi không strict)
        if strict:
            sys_log.warning("  ⚠️ TTS strict: không tìm thấy engine phù hợp → bỏ qua đoạn này")
            return False
        return self._fallback_pyttsx3(text, output_path)

    def _clean_tts_text(self, text: str) -> str:
        """Làm sạch text trước khi TTS: loại ký tự lạ, chuẩn hóa khoảng trắng."""
        import re
        # Loại bỏ ký tự không phải Latin/tiếng Việt/dấu câu thông thường
        text = re.sub(r"[^\w\sÀ-ɏḀ-ỿ̀-ͯ,.!?;:\-'\"()‘’“”…]", ' ', text)
        # Chuẩn hóa khoảng trắng
        text = re.sub(r'\s+', ' ', text)
        # Đảm bảo kết thúc bằng dấu câu để TTS ngắt giọng tự nhiên
        text = text.strip()
        if text and text[-1] not in '.!?…':
            text += '.'
        return text

    # ═══════════════════════════════════════════════════════════
    # ENGINE: Edge-TTS (giọng Việt chuẩn, tự nhiên nhất)
    # ═══════════════════════════════════════════════════════════
    def _run_edge_tts(self, text: str, voice_id: str, output_path: str,
                      strict: bool = False) -> bool:
        try:
            import edge_tts  # type: ignore

            async def _synthesize():
                communicate = edge_tts.Communicate(text=text.strip(), voice=voice_id, rate="-5%")
                await communicate.save(output_path)

            # Chạy async trong sync context
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(asyncio.run, _synthesize())
                        future.result(timeout=30)
                else:
                    loop.run_until_complete(_synthesize())
            except RuntimeError:
                asyncio.run(_synthesize())

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                self.current_voice_name = voice_id
                sys_log.info(f"  ✅ Edge-TTS [{voice_id}] → {os.path.basename(output_path)}")
                return True
            return False

        except Exception as e:
            if strict:
                sys_log.warning(f"  ⚠️ Edge-TTS lỗi (strict): {e} → đánh dấu thất bại, giữ nguyên giọng")
                return False
            sys_log.warning(f"  ⚠️ Edge-TTS lỗi: {e} → thử VieNeu")
            return self._run_vieneu(text, None, output_path)

    # ═══════════════════════════════════════════════════════════
    # ENGINE: VieNeu-TTS (offline, clone voice)
    # ═══════════════════════════════════════════════════════════
    def _run_vieneu(self, text: str, voice: Optional[str], output_path: str,
                    strict: bool = False) -> bool:
        if not self.tts_model:
            if strict:
                sys_log.warning("  ⚠️ VieNeu strict: model chưa load → đánh dấu thất bại")
                return False
            return self._fallback_pyttsx3(text, output_path)
        try:
            voice_data = self._resolve_vieneu_voice(voice)
            audio = self.tts_model.infer(text=text.strip(), voice=voice_data)
            self.tts_model.save(audio, output_path)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                sys_log.info(f"  ✅ VieNeu [{self.current_voice_name}] → {os.path.basename(output_path)}")
                return True
            return False
        except Exception as e:
            if strict:
                sys_log.error(f"  ❌ VieNeu lỗi (strict): {e} → đánh dấu thất bại, giữ nguyên giọng")
                return False
            sys_log.error(f"  ❌ VieNeu lỗi: {e}")
            return self._fallback_pyttsx3(text, output_path)

    def _resolve_vieneu_voice(self, voice: Optional[str]) -> Any:
        if voice is None:
            return self.current_voice_data

        # File .wav → clone
        if os.path.isfile(voice) and voice.lower().endswith(('.wav','.mp3','.flac')):
            return self._encode_ref(voice, os.path.basename(voice))

        # Profile clone
        if voice in self._profiles and self._profiles[voice].get("type") == "clone":
            return self._encode_ref(self._profiles[voice]["value"], voice)

        # Preset cache
        if voice in self._preset_cache:
            self.current_voice_data = self._preset_cache[voice]
            self.current_voice_name = voice
            return self.current_voice_data

        # Thử get_preset_voice
        try:
            data = self.tts_model.get_preset_voice(voice)
            self._preset_cache[voice] = data
            self.current_voice_data   = data
            self.current_voice_name   = voice
            return data
        except Exception:
            sys_log.warning(f"  ⚠️ Không nhận diện voice '{voice}' → default")
            return self.current_voice_data

    def _encode_ref(self, wav_path: str, label: str) -> Any:
        if wav_path in self._preset_cache:
            self.current_voice_name = label
            return self._preset_cache[wav_path]
        try:
            sys_log.info(f"  🎙️ Encoding: {os.path.basename(wav_path)}")
            data = self.tts_model.encode_reference(wav_path)
            self._preset_cache[wav_path] = data
            self.current_voice_data      = data
            self.current_voice_name      = label
            return data
        except Exception as e:
            sys_log.error(f"  ❌ encode_reference: {e}")
            return self.current_voice_data

    # ═══════════════════════════════════════════════════════════
    # FALLBACK: pyttsx3
    # ═══════════════════════════════════════════════════════════
    def _fallback_pyttsx3(self, text: str, output_path: str) -> bool:
        sys_log.warning("⚠️ Fallback pyttsx3")
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', 155)
            for v in engine.getProperty('voices'):  # type: ignore[attr-defined]
                name_lower = getattr(v, 'name', '').lower()
                if 'female' in name_lower or 'zira' in name_lower:
                    engine.setProperty('voice', v.id)
                    break
            engine.save_to_file(text, output_path)
            engine.runAndWait()
            ok = os.path.exists(output_path) and os.path.getsize(output_path) > 1024
            if ok:
                sys_log.info(f"  ✅ pyttsx3 → {os.path.basename(output_path)}")
            return ok
        except Exception as e:
            sys_log.error(f"  ❌ pyttsx3 lỗi: {e}")
            return False