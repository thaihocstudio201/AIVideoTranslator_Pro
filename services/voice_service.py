import os
import sys
import torch
from typing import Optional, Any

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from utils.custom_logger import sys_log

HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


class VoiceService:
    def __init__(self):
        self.tts_model: Any = None
        self.current_voice_data: Any = None
        self.current_voice_name: str = "default"
        self._preset_cache: dict = {}

        sys_log.info("🔄 Đang khởi tạo VieNeu-TTS...")
        try:
            from vieneu import Vieneu  # type: ignore
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.tts_model = Vieneu(
                model_name="vienneu/vienneu-2.4.3",
                device=device,
                hf_token=HF_TOKEN
            )
            sys_log.info(f"✅ VieNeu-TTS load thành công trên {device.upper()}")
            self._load_preset_voices()
        except ImportError:
            sys_log.error("❌ Package 'vieneu' chưa được cài. Chạy: pip install vieneu")
            self.tts_model = None
        except Exception as e:
            sys_log.error(f"❌ Lỗi khởi tạo VieNeu-TTS: {e}")
            self.tts_model = None

    def _load_preset_voices(self):
        if not self.tts_model:
            return
        try:
            voices = self.tts_model.list_preset_voices()
            for desc, voice_id in voices:
                voice_data = self.tts_model.get_preset_voice(voice_id)
                self._preset_cache[voice_id] = voice_data
                self._preset_cache[desc] = voice_data
            names = [d for d, _ in voices]
            sys_log.info(f"✅ Đã load {len(voices)} preset voices: {names}")
        except Exception as e:
            sys_log.warning(f"⚠️ Không load được preset voices: {e}")

    def list_voices(self) -> list:
        if not self.tts_model:
            return []
        try:
            return self.tts_model.list_preset_voices()
        except Exception as e:
            sys_log.error(f"Lỗi list_voices: {e}")
            return []

    def run_tts(self, text: str, voice: Optional[str] = None,
                output_path: str = "temp_voice.wav") -> bool:
        """
        voice=None          -> default Xuan Vinh
        voice="Ngoc"        -> preset voice theo ten
        voice="path/to.wav" -> clone voice tu file audio
        """
        if not text or not text.strip():
            return False
        if not self.tts_model:
            sys_log.warning("⚠️ VieNeu model khong kha dung -> fallback pyttsx3")
            return self._fallback_pyttsx3(text, output_path)
        try:
            voice_data = self._resolve_voice(voice)
            audio = self.tts_model.infer(text=text.strip(), voice=voice_data)
            self.tts_model.save(audio, output_path)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                sys_log.info(f"  ✅ TTS OK [{self.current_voice_name}] -> {os.path.basename(output_path)}")
                return True
            sys_log.warning(f"  ⚠️ File output rong: {output_path}")
            return False
        except Exception as e:
            sys_log.error(f"  ❌ Loi VieNeu-TTS: {e}")
            return self._fallback_pyttsx3(text, output_path)

    def _resolve_voice(self, voice: Optional[str]) -> Any:
        if voice is None:
            return self.current_voice_data
        if os.path.isfile(voice) and voice.lower().endswith(('.wav', '.mp3', '.flac')):
            sys_log.info(f"  🎙️ Clone voice tu: {os.path.basename(voice)}")
            try:
                voice_data = self.tts_model.encode_reference(voice)
                self.current_voice_data = voice_data
                self.current_voice_name = os.path.basename(voice)
                return voice_data
            except Exception as e:
                sys_log.error(f"  ❌ encode_reference that bai: {e}")
                return None
        if voice in self._preset_cache:
            sys_log.info(f"  🎙️ Dung preset: {voice}")
            self.current_voice_data = self._preset_cache[voice]
            self.current_voice_name = voice
            return self.current_voice_data
        try:
            voice_data = self.tts_model.get_preset_voice(voice)
            self._preset_cache[voice] = voice_data
            self.current_voice_data = voice_data
            self.current_voice_name = voice
            sys_log.info(f"  🎙️ Loaded preset: {voice}")
            return voice_data
        except Exception:
            sys_log.warning(f"  ⚠️ Khong nhan dien voice '{voice}' -> dung default")
            return None

    def _fallback_pyttsx3(self, text: str, output_path: str) -> bool:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', 160)
            engine.save_to_file(text, output_path)
            engine.runAndWait()
            ok = os.path.exists(output_path) and os.path.getsize(output_path) > 1024
            if ok:
                sys_log.info(f"  ✅ Fallback pyttsx3 OK -> {os.path.basename(output_path)}")
            return ok
        except Exception as e:
            sys_log.error(f"  ❌ Fallback pyttsx3 loi: {e}")
            return False