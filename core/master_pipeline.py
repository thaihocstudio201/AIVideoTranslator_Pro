import os
import time
import shutil
import threading
import subprocess
import re
from pydub import AudioSegment
from services.ai_service import AIService
from services.voice_service import VoiceService
from utils.custom_logger import sys_log

class VideoPipelineEngine:
    def __init__(self, video_list, out_dir, settings, on_finish_callback=None):
        self.video_list = video_list
        self.out_dir = os.path.normpath(out_dir)
        self.settings = settings
        self.on_finish = on_finish_callback
        self.ai = AIService()
        self.voice = VoiceService()

    def start(self):
        sys_log.info("="*50)
        sys_log.info(f"🚀 CHIẾN DỊCH BẮT ĐẦU: Xử lý {len(self.video_list)} Video")
        threading.Thread(target=self._run_engine, daemon=True).start()

    def _run_hidden_cmd(self, cmd_string, error_msg="Lỗi"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        proc = subprocess.run(cmd_string, shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace', startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode != 0:
            sys_log.error(f"{error_msg}: {proc.stderr[-100:]}")
            return False
        return True

    def _run_engine(self):
        try:
            for idx, vid_path in enumerate(self.video_list, start=1):
                vid_path = os.path.normpath(vid_path)
                name_clean = re.sub(r'[^\w\s-]', '', os.path.splitext(os.path.basename(vid_path))[0]).strip()
                temp_dir = os.path.join(self.out_dir, f"temp_{idx}_{name_clean}")
                os.makedirs(temp_dir, exist_ok=True)

                sys_log.info(f"▶️ TIẾN TRÌNH [{idx}/{len(self.video_list)}]: {os.path.basename(vid_path)}")

                # BƯỚC 1: Tách âm
                audio_goc_path = os.path.join(temp_dir, "goc.wav")
                cmd_extract = f'ffmpeg -i "{vid_path}" -vn -acodec pcm_s16le -ar 44100 -ac 2 -y "{audio_goc_path}"'
                if not self._run_hidden_cmd(cmd_extract, "Lỗi tách âm"): continue

                # BƯỚC 2: Whisper (Dịch vụ đã có Log chi tiết)
                srt_orig = os.path.join(temp_dir, "sub_orig.srt")
                segments = self.ai.transcribe_and_get_segments(audio_goc_path, srt_orig)
                
                # BƯỚC 3: Gemini (Dịch vụ đã có Log chi tiết)
                api_keys = self.settings.get('api_key', '').split('\n')
                chosen_model = self.settings.get('chosen_model')

                # Gọi hàm dịch có cơ chế xoay vòng
                segments, success = self.ai.translate_with_rotation(
                    segments, "Vietnamese", api_keys, chosen_model
                )
                if not success:
                    sys_log.error("❌ TẤT CẢ API ĐÃ HẾT HẠN MỨC HOẶC LỖI. Dừng tiến trình.")
                    # ... (xử lý dừng) ...
                    
                # BƯỚC 4: Edge-TTS (Lồng tiếng)
                sys_log.info(f"  ↳ [4] ĐANG TẠO BẢN LỒNG TIẾNG VIỆT (GIỌNG: {self.settings['ai_voice']})...")
                
                audio_goc = AudioSegment.from_file(audio_goc_path)
                dub_canvas = AudioSegment.silent(duration=len(audio_goc))

                for i, seg in enumerate(segments):
                    text = seg['text'].strip()
                    if not text or len(re.sub(r'[^\w\s]', '', text)) == 0: continue
                    
                    start_ms = int(seg['start'] * 1000)
                    temp_line = os.path.join(temp_dir, f"line_{i}.mp3")
                    
                    # Gọi lồng tiếng
                    success = self.voice.run_tts(text, self.settings['ai_voice'], temp_line)
                    time.sleep(0.5) # Chống spam Microsoft

                    if success and os.path.exists(temp_line) and os.path.getsize(temp_line) > 0:
                        line_audio = AudioSegment.from_file(temp_line)
                        dub_canvas = dub_canvas.overlay(line_audio, position=start_ms)

                audio_dub_path = os.path.join(temp_dir, "dub_final.wav")
                dub_canvas.export(audio_dub_path, format="wav")

                # BƯỚC 5: Mix & Render
                vol_ai = self.settings.get('vol_ai', 120) / 100
                vol_orig = self.settings.get('vol_orig', 5) / 100
                final_out = os.path.join(self.out_dir, f"DUBBED_{name_clean}.mp4")
                
                mix_cmd = (
                    f'ffmpeg -i "{vid_path}" -i "{audio_goc_path}" -i "{audio_dub_path}" -filter_complex '
                    f'"[1:a]volume={vol_orig}[a1]; [2:a]volume={vol_ai}[a2]; '
                    f'[a1][a2]amix=inputs=2:duration=first" '
                    f'-c:v copy -c:a aac -shortest -y "{final_out}"'
                )
                
                if self._run_hidden_cmd(mix_cmd, "Lỗi Render"):
                    sys_log.info(f"✅ THÀNH CÔNG: {os.path.basename(final_out)}")

                shutil.rmtree(temp_dir, ignore_errors=True)

            sys_log.info("="*50)
            sys_log.info("🎉 HOÀN TẤT TOÀN BỘ DANH SÁCH!")
        except Exception as e:
            sys_log.error(f"CRASH PIPELINE: {e}")
        finally:
            if self.on_finish: self.on_finish()