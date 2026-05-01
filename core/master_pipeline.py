import os
import time
import shutil
import threading
import subprocess
import re
import torch
from pydub import AudioSegment

from services.ai_service import AIService
from services.voice_service import VoiceService
from utils.custom_logger import sys_log


class VideoPipelineEngine:
    def __init__(self, video_list, out_dir, settings, on_finish_callback=None, ui_callback=None):
        self.video_list = video_list
        self.out_dir = os.path.normpath(out_dir)
        self.settings = settings
        self.on_finish = on_finish_callback
        self.ui_callback = ui_callback

        self.ai = AIService()
        self.voice = VoiceService()

    def start(self):
        sys_log.info("=" * 70)
        sys_log.info(f"🚀 BẮT ĐẦU XỬ LÝ {len(self.video_list)} VIDEO")
        threading.Thread(target=self._run_engine, daemon=True).start()

    def _run_hidden_cmd(self, cmd_string, error_msg="Lỗi"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        proc = subprocess.run(cmd_string, shell=True, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', startupinfo=si,
                            creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode != 0:
            sys_log.error(f"{error_msg}: {proc.stderr[-200:]}")
            return False
        return True

    def _get_voice_for_lang(self, target_lang):
        voice_map = {
            "Vietnamese": "vi-VN-HoaiMyNeural",
            "English": "en-US-AvaNeural",
            "Japanese": "ja-JP-NanamiNeural",
            "Korean": "ko-KR-SunHiNeural",
            "Thai": "th-TH-PremwadeeNeural"
        }
        return voice_map.get(target_lang, "vi-VN-HoaiMyNeural")

    def _separate_with_demucs(self, audio_path, temp_dir):
        sys_log.info("  ↳ Đang tách nhạc nền bằng Demucs...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        sys_log.info(f"  ↳ Demucs chạy trên **{device.upper()}**")

        output_dir = os.path.join(temp_dir, "demucs")
        os.makedirs(output_dir, exist_ok=True)

        cmd = f'demucs --two-stems=vocals --device {device} -o "{output_dir}" "{audio_path}"'

        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                base = os.path.splitext(os.path.basename(audio_path))[0]
                music_path = os.path.join(output_dir, "htdemucs", base, "no_vocals.wav")
                vocals_path = os.path.join(output_dir, "htdemucs", base, "vocals.wav")
                if os.path.exists(music_path) and os.path.exists(vocals_path):
                    sys_log.info("✅ Demucs tách thành công!")
                    return music_path, vocals_path
        except Exception as e:
            sys_log.warning(f"Demucs lỗi: {e}")

        sys_log.info("⚠️ Chuyển sang filter FFmpeg")
        return None, None

    def _run_engine(self):
        try:
            for idx, vid_path in enumerate(self.video_list, start=1):
                vid_path = os.path.normpath(vid_path)
                base_name = os.path.basename(vid_path)
                name_clean = re.sub(r'[^\w\s-]', '', os.path.splitext(base_name)[0]).strip()

                temp_dir = os.path.join(self.out_dir, f"temp_{idx}_{name_clean}")
                os.makedirs(temp_dir, exist_ok=True)

                sys_log.info(f"▶️ ĐANG XỬ LÝ [{idx}/{len(self.video_list)}]: {base_name}")

                # 1. Tách âm thanh gốc
                audio_goc_path = os.path.join(temp_dir, "goc.wav")
                self._run_hidden_cmd(
                    f'ffmpeg -i "{vid_path}" -vn -acodec pcm_s16le -ar 44100 -ac 2 -y "{audio_goc_path}"',
                    "Lỗi tách âm thanh gốc"
                )

                # 2. Whisper
                srt_orig = os.path.join(temp_dir, "sub_orig.srt")
                segments = self.ai.transcribe_and_get_segments(audio_goc_path, srt_orig)

                if not segments:
                    sys_log.warning("  [!] Không có lời thoại.")
                    continue

                for seg in segments:
                    seg['original_text'] = seg['text']

                # 3. Dịch thuật
                target_lang = self.settings.get('target_lang', 'Vietnamese')
                ai_platform = self.settings.get('ai_platform', 'gemini')

                sys_log.info(f"  ↳ Đang dịch sang {target_lang}...")

                if ai_platform == 'ollama':
                    segments, success = self.ai.translate_with_ollama(
                        segments, target_lang, self.settings.get('default_model')
                    )
                else:
                    segments, success = self.ai.translate_with_rotation(
                        segments, target_lang, self.settings.get('api_keys', []), self.settings.get('default_model')
                    )

                if not success:
                    sys_log.error("❌ Dịch thuật thất bại.")
                    continue

                self._log_srt_comparison(segments, idx)
                srt_translated = os.path.join(self.out_dir, f"{name_clean}_translated.srt")
                self._save_translated_srt(segments, srt_translated)

                if self.ui_callback:
                    self.ui_callback(segments)

                # 4. Tạo voice
                sys_log.info(f"  ↳ Đang tạo voice cho {target_lang}...")

                audio_goc = AudioSegment.from_file(audio_goc_path)
                dub_canvas = AudioSegment.silent(duration=len(audio_goc))

                for i, seg in enumerate(segments):
                    text = seg['text'].strip()
                    if not text:
                        continue

                    voice_file = os.path.join(temp_dir, f"line_{i}.wav")
                    voice_name = self._get_voice_for_lang(target_lang)

                    success_tts = self.voice.run_tts(text, voice=voice_name, output_path=voice_file)

                    if success_tts and os.path.exists(voice_file) and os.path.getsize(voice_file) > 0:
                        try:
                            line_audio = AudioSegment.from_file(voice_file)
                            start_ms = int(seg['start'] * 1000)
                            dub_canvas = dub_canvas.overlay(line_audio, position=start_ms)
                        except Exception as e:
                            sys_log.warning(f"  [!] Ghép voice đoạn {i} lỗi: {e}")
                    else:
                        sys_log.warning(f"  [!] TTS lỗi đoạn {i} (bỏ qua)")

                audio_dub_path = os.path.join(temp_dir, "dub_final.wav")
                dub_canvas.export(audio_dub_path, format="wav")

                # 5. Tách nhạc nền bằng Demucs
                music_path, vocals_path = self._separate_with_demucs(audio_goc_path, temp_dir)

                # 6. Render video cuối
                final_out = os.path.join(self.out_dir, f"DUBBED_{name_clean}.mp4")

                vol_ai = self.settings.get('vol_ai', 120) / 100.0
                vol_bg = self.settings.get('vol_bg', 30) / 100.0
                vol_orig = self.settings.get('vol_orig', 5) / 100.0

                sys_log.info(f"  ↳ Mix âm thanh: AI={vol_ai*100:.0f}%, Nhạc nền={vol_bg*100:.0f}%, Gốc={vol_orig*100:.0f}%")

                if music_path and vocals_path:
                    # Demucs OK
                    mix_cmd = (
                        f'ffmpeg -i "{vid_path}" -i "{music_path}" -i "{vocals_path}" -i "{audio_dub_path}" '
                        f'-filter_complex '
                        f'"[1:a]volume={vol_bg}[music]; '
                        f'[2:a]volume={vol_orig}[orig_voc]; '
                        f'[music][orig_voc]amix=inputs=2:duration=first[bg]; '
                        f'[bg][3:a]volume={vol_ai}[final]" '
                        f'-map 0:v -map "[final]" -c:v copy -c:a aac -shortest -y "{final_out}"'
                    )
                else:
                    # Fallback FFmpeg - ĐÃ SỬA LỖI "2 > 1"
                    mix_cmd = (
                        f'ffmpeg -i "{vid_path}" -i "{audio_goc_path}" -i "{audio_dub_path}" '
                        f'-filter_complex '
                        f'"[1:a]volume={vol_orig}[orig]; '
                        f'[1:a]highpass=f=300,volume={vol_bg}[bg]; '
                        f'[orig][bg]amix=inputs=2:duration=first[mix]; '
                        f'[mix][2:a]volume={vol_ai}[final]" '
                        f'-map 0:v -map "[final]" -c:v copy -c:a aac -shortest -y "{final_out}"'
                    )

                if self._run_hidden_cmd(mix_cmd, "Lỗi Render cuối"):
                    sys_log.info(f"✅ HOÀN THÀNH: {os.path.basename(final_out)}")

                shutil.rmtree(temp_dir, ignore_errors=True)

            sys_log.info("=" * 70)
            sys_log.info("🎉 HOÀN TẤT TOÀN BỘ QUÁ TRÌNH!")

        except Exception as e:
            sys_log.error(f"PIPELINE CRASH: {e}")
        finally:
            if self.on_finish:
                self.on_finish()

    # Các hàm phụ (giữ nguyên)
    def _save_translated_srt(self, segments, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                for i, seg in enumerate(segments, 1):
                    start = self._format_time(seg['start'])
                    end = self._format_time(seg['end'])
                    f.write(f"{i}\n{start} --> {end}\n{seg['text']}\n\n")
            sys_log.info(f"💾 ĐÃ LƯU SRT ĐÃ DỊCH: {os.path.basename(path)}")
        except Exception as e:
            sys_log.error(f"❌ Lỗi lưu SRT: {e}")

    def _log_srt_comparison(self, segments, video_idx):
        sys_log.info(f"\n{'='*120}")
        sys_log.info(f"📋 BẢNG SO SÁNH SRT - VIDEO {video_idx}")
        sys_log.info(f"{'STT':<4} {'THỜI GIAN':<25} {'NỘI DUNG GỐC':<50} | {'NỘI DUNG ĐÃ DỊCH':<50}")
        sys_log.info("-" * 120)

        for seg in segments[:50]:
            orig = (seg.get('original_text', '') or seg.get('text', ''))[:48]
            trans = seg.get('text', '')[:48]
            time_str = f"{self._format_time(seg['start'])} → {self._format_time(seg['end'])}"
            sys_log.info(f"{seg.get('id', 0):<4} {time_str:<25} {orig:<50} | {trans:<50}")

        sys_log.info("=" * 120 + "\n")

    def _format_time(self, seconds):
        td = time.gmtime(seconds)
        ms = int((seconds % 1) * 1000)
        return f"{time.strftime('%H:%M:%S', td)},{ms:03d}"