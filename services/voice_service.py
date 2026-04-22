import os
import asyncio
import edge_tts
from utils.custom_logger import sys_log

class VoiceService:
    async def _generate(self, text, voice, output, rate, pitch):
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(output)

    def run_tts(self, text, voice, output_path, rate="+0%", pitch="+0Hz"):
        try:
            asyncio.run(self._generate(text, voice, output_path, rate, pitch))
            # Kiểm tra nếu file tồn tại và có dung lượng > 0
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return True
            else:
                sys_log.error(f"  [!] File TTS tạo ra bị rỗng: {output_path}")
                return False
        except Exception as e:
            sys_log.error(f"  [!] Lỗi Edge-TTS: {e}")
            return False