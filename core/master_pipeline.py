"""
core/master_pipeline.py
FIX 1: Sau khi dịch lần 1, tự động kiểm tra SRT còn sót ngôn ngữ gốc
        → dịch lại các đoạn bị sót → lặp tối đa 3 lần cho đến khi sạch.
FIX 2: Sau khi tạo TTS, tự động retry các đoạn bị lỗi (tối đa 3 lần).
"""

import os
import sys
import json
import time
import shutil
import threading
import subprocess
import re
import torch
from typing import Optional, Tuple
from pydub import AudioSegment

from services.ai_service import AIService
from services.voice_service import VoiceService
from utils.custom_logger import sys_log
from core.checkpoint_mgr import CheckpointManager

# Video > 30 phút → dùng Block Pipeline (chia nhỏ 10 phút/block)
BLOCK_THRESHOLD_SEC = 1800
BLOCK_DURATION_SEC  = 600


# ── Danh sách Unicode range để phát hiện ngôn ngữ gốc còn sót ──────────
LANG_CHAR_PATTERNS = {
    "Chinese":  re.compile(
        r'[\u4e00-\u9fff'   # CJK Unified Ideographs (main block)
        r'\u3400-\u4dbf'    # CJK Extension A
        r'\uf900-\ufaff'    # CJK Compatibility Ideographs
        r'\u2e80-\u2fdf'    # CJK Radicals Supplement + Kangxi Radicals
        r'\u3000-\u303f'    # CJK Symbols & Punctuation (\u3002\uff0c\uff01\uff1f\u2026)
        r'\ufe30-\ufe4f'    # CJK Compatibility Forms
        r'\uff00-\uffef]'   # Fullwidth/Halfwidth (\uff0c\u3002\uff01\uff1f\uff1a\uff1b)
    ),
    "Japanese": re.compile(r'[\u3040-\u309f\u30a0-\u30ff]'),
    "Korean":   re.compile(r'[\uac00-\ud7af\u1100-\u11ff]'),
    "English":  re.compile(r'[a-zA-Z]{4,}'),  # ≥4 ký tự Latin liên tiếp
    "Thai":     re.compile(r'[\u0e00-\u0e7f]'),
}


def _has_source_lang(text: str, source_lang: str, original_text: str = "") -> bool:
    """
    Kiểm tra xem text còn chứa ký tự của ngôn ngữ nguồn không.
    Với tiếng Anh (Latin script), không thể dùng ký tự để phát hiện vì ngôn ngữ
    đích (Việt, Thái, v.v.) cũng dùng hoặc có loanword Latin → kiểm tra bằng
    cách so sánh với văn bản gốc: nếu text KHÔNG đổi thì coi là chưa dịch.
    """
    if source_lang == "English":
        return bool(original_text and text.strip() == original_text.strip())
    pattern = LANG_CHAR_PATTERNS.get(source_lang)
    if pattern is None:
        return False
    return bool(pattern.search(text))


def _mk_si():
    """Trả về STARTUPINFO ẩn cửa sổ console trên Windows; None trên Linux/Mac."""
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def _mk_cflags() -> int:
    """Trả về CREATE_NO_WINDOW trên Windows; 0 trên Linux/Mac."""
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class _PipelineStopRequest(BaseException):
    """Raised khi người dùng nhấn Stop — thoát khỏi pipeline sạch."""


class VideoPipelineEngine:
    MAX_TRANSLATE_RETRIES = 3   # Số lần tối đa kiểm tra & dịch lại
    MAX_TTS_RETRIES       = 3   # Số lần retry mỗi đoạn TTS lỗi

    # Cache kết quả detect GPU encoder (None = chưa detect)
    _HW_ENCODER: Optional[str] = None
    _HW_ENCODER_CHECKED: bool = False

    @classmethod
    def _get_video_encoder(cls) -> str:
        """Trả về codec tốt nhất: h264_nvenc (NVIDIA) → h264_amf (AMD) → libx264 (CPU)."""
        if cls._HW_ENCODER_CHECKED:
            return cls._HW_ENCODER or "libx264"
        cls._HW_ENCODER_CHECKED = True
        for codec in ("h264_nvenc", "h264_amf"):
            try:
                r = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-f", "lavfi",
                     "-i", "color=c=black:s=128x128:r=25:d=0.5",
                     "-c:v", codec, "-f", "null", os.devnull],
                    capture_output=True, timeout=15,
                    startupinfo=_mk_si(), creationflags=_mk_cflags()
                )
                if r.returncode == 0:
                    cls._HW_ENCODER = codec
                    sys_log.info(f"  ✅ GPU encoder: {codec}")
                    return codec
            except Exception:
                pass
        sys_log.info("  ℹ️ GPU encoder không khả dụng → dùng libx264 (CPU)")
        return "libx264"

    def __init__(self, video_list, out_dir, settings,
                 on_finish_callback=None, ui_callback=None,
                 on_video_progress=None):
        self.video_list  = video_list
        self.out_dir     = os.path.normpath(out_dir)
        self.settings    = settings
        self.on_finish   = on_finish_callback
        self.ui_callback = ui_callback
        # Callback per-video: fn(idx, total, video_name, status)
        # status: "start" | "done" | "error"
        self.on_video_progress = on_video_progress

        # ── Điều khiển pipeline (Pause / Stop) ────────────────
        self._stop_event  = threading.Event()   # set() = yêu cầu dừng hẳn
        self._pause_event = threading.Event()   # set() = đang tạm dừng

        whisper_device = "cuda" if torch.cuda.is_available() else "cpu"
        whisper_model  = settings.get("whisper_model", "base")
        self.ai    = AIService(model_size=whisper_model, device=whisper_device)
        self.voice = VoiceService()

    # ── Điều khiển từ UI ───────────────────────────────────────
    def pause(self):
        """Tạm dừng pipeline sau checkpoint hiện tại."""
        if not self._stop_event.is_set():
            self._pause_event.set()
            sys_log.info("⏸️  Pipeline: TẠM DỪNG")

    def resume(self):
        """Tiếp tục sau khi tạm dừng."""
        self._pause_event.clear()
        sys_log.info("▶️  Pipeline: TIẾP TỤC")

    def stop(self):
        """Dừng pipeline hoàn toàn — không thể resume."""
        self._stop_event.set()
        self._pause_event.clear()   # unblock nếu đang pause
        sys_log.info("⏹️  Pipeline: ĐANG DỪNG...")

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def _check_control(self):
        """
        Checkpoint kiểm tra Pause/Stop. Gọi tại các điểm an toàn trong pipeline.
        - Nếu đang Pause: block cho đến khi Resume hoặc Stop.
        - Nếu Stop: raise _PipelineStopRequest → pipeline thoát sạch.
        """
        while self._pause_event.is_set() and not self._stop_event.is_set():
            time.sleep(0.3)
        if self._stop_event.is_set():
            raise _PipelineStopRequest()

    def start(self):
        sys_log.info("=" * 70)
        sys_log.info(f"🚀 BẮT ĐẦU XỬ LÝ {len(self.video_list)} VIDEO")
        threading.Thread(target=self._run_engine, daemon=True).start()

    # ── helpers ────────────────────────────────────────────────
    def _run_cmd_list(self, cmd: list, error_msg: str = "Lỗi") -> bool:
        """Chạy FFmpeg với danh sách tham số (không qua shell) — tránh lỗi escape trên Windows."""
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            startupinfo=_mk_si(), creationflags=_mk_cflags()
        )
        if proc.returncode != 0:
            sys_log.error(f"{error_msg}: {proc.stderr[-400:]}")
            return False
        return True

    def _get_voice_param(self) -> Optional[str]:
        return self.settings.get("voice_profile")

    # ══════════════════════════════════════════════════════════════
    # FIX 1: DỊCH VỚI KIỂM TRA & RETRY LOOP
    # ══════════════════════════════════════════════════════════════
    def _translate_with_verification(
        self,
        segments: list,
        target_lang: str,
        source_lang: str,
        ai_platform: str,
        global_ctx: str = "",
    ) -> Tuple[list, bool]:
        """
        Dịch toàn bộ segments, sau đó kiểm tra các đoạn còn sót ngôn ngữ gốc.
        Lặp tối đa MAX_TRANSLATE_RETRIES lần cho đến khi sạch hoàn toàn.
        """
        # ── Lần dịch đầu tiên (toàn bộ) ──────────────────────────
        segments, success = self._do_translate(
            segments, target_lang, ai_platform,
            is_full=True, source_lang=source_lang, global_ctx=global_ctx
        )
        if not success:
            return segments, False

        # ── Vòng kiểm tra & dịch lại ──────────────────────────────
        for attempt in range(1, self.MAX_TRANSLATE_RETRIES + 1):
            # Tìm các đoạn còn sót ngôn ngữ gốc
            dirty_indices = [
                i for i, seg in enumerate(segments)
                if _has_source_lang(
                    seg.get('text', ''), source_lang,
                    seg.get('original_text', '')
                )
            ]

            if not dirty_indices:
                sys_log.info(f"  ✅ Kiểm tra lần {attempt}: Toàn bộ đã dịch sạch sang {target_lang}!")
                break

            sys_log.warning(
                f"  🔁 Kiểm tra lần {attempt}: Còn {len(dirty_indices)} đoạn sót "
                f"ngôn ngữ [{source_lang}] → IDs: {[segments[i]['id'] for i in dirty_indices]}"
            )

            # Chỉ gửi các đoạn bị sót để dịch lại
            dirty_segs = [segments[i] for i in dirty_indices]
            retranslated, ok = self._do_translate(
                dirty_segs, target_lang, ai_platform,
                is_full=False, source_lang=source_lang, global_ctx=global_ctx
            )

            if ok:
                # Ghi kết quả dịch lại vào danh sách gốc
                for dirty_i, new_seg in zip(dirty_indices, retranslated):
                    segments[dirty_i]['text'] = new_seg['text']
                    sys_log.info(
                        f"    ↳ Đoạn {segments[dirty_i]['id']}: "
                        f"[{new_seg.get('original_text','')[:30]}] → [{new_seg['text'][:40]}]"
                    )
            else:
                sys_log.warning(f"  ⚠️ Dịch lại lần {attempt} thất bại — bỏ qua.")
        else:
            # Hết số lần retry nhưng vẫn còn dirty
            remaining = sum(
                1 for seg in segments
                if _has_source_lang(seg.get('text', ''), source_lang, seg.get('original_text', ''))
            )
            if remaining:
                sys_log.warning(f"  ⚠️ Còn {remaining} đoạn chưa dịch được sau {self.MAX_TRANSLATE_RETRIES} lần kiểm tra.")

        return segments, True

    _OPENAI_COMPAT_PLATFORMS = frozenset({"openai", "groq", "deepseek", "openrouter"})

    def _do_translate(self, segs: list, target_lang: str, ai_platform: str,
                      is_full: bool, source_lang: str = "",
                      global_ctx: str = "") -> Tuple[list, bool]:
        """Gọi AI service thực tế để dịch — hỗ trợ đa nền tảng."""
        prefix = "Toàn bộ" if is_full else f"{len(segs)} đoạn sót"
        model  = self.settings.get("default_model", "")
        keys   = self.settings.get("api_keys", [])
        sys_log.info(f"  ↳ Dịch {prefix} → {target_lang} [{ai_platform.upper()}] {model}")

        if ai_platform == "ollama":
            return self.ai.translate_with_ollama(segs, target_lang, model, source_lang, global_ctx)

        if ai_platform in self._OPENAI_COMPAT_PLATFORMS:
            return self.ai.translate_with_openai_compat(
                segs, target_lang, keys, model, ai_platform, source_lang
            )

        # Mặc định: Gemini với xoay vòng key
        return self.ai.translate_with_rotation(segs, target_lang, keys, model, source_lang)

    # ══════════════════════════════════════════════════════════════
    # FIX 2: TẠO TTS VỚI RETRY CÁC ĐOẠN LỖI
    # ══════════════════════════════════════════════════════════════
    def _create_tts_with_retry(
        self,
        segments: list,
        audio_goc_seg: AudioSegment,
        temp_dir: str,
        voice_param: Optional[str],
    ) -> AudioSegment:
        """
        Tạo TTS cho tất cả segments với CÙNG MỘT giọng (strict=True).
        Khi 1 đoạn lỗi → đánh dấu, tiếp tục đoạn kế tiếp (KHÔNG đổi engine/giọng).
        Sau khi hết tất cả → rà soát danh sách lỗi, retry từng đoạn với cùng giọng đó.
        """
        dub_canvas = AudioSegment.silent(duration=len(audio_goc_seg))
        results: dict = {}       # seg_index → path file wav thành công
        failed_indices: list = []

        total_non_empty = sum(1 for s in segments if s.get('text', '').strip())
        sys_log.info(f"  ↳ TTS batch: {total_non_empty} đoạn | giọng={voice_param or 'default'}")

        # ── Lần chạy đầu: toàn bộ segments, strict=True ───────
        for i, seg in enumerate(segments):
            text = seg.get('text', '').strip()
            if not text:
                continue
            voice_file = os.path.join(temp_dir, f"line_{i}.wav")
            ok_tts = self.voice.run_tts(
                text, voice=voice_param, output_path=voice_file, strict=True
            )
            if ok_tts and os.path.exists(voice_file) and os.path.getsize(voice_file) > 1024:
                results[i] = voice_file
            else:
                sys_log.warning(
                    f"  [!] TTS lỗi đoạn {i} (ID={seg.get('id','?')}) "
                    f"[{text[:35]}...] → đưa vào hàng rà soát"
                )
                failed_indices.append(i)

        # ── Rà soát & retry đoạn lỗi — CÙNG GIỌNG ────────────
        if failed_indices:
            sys_log.info(
                f"  🔁 Rà soát {len(failed_indices)} đoạn lỗi "
                f"(IDs: {[segments[i].get('id','?') for i in failed_indices]})..."
            )
            for retry in range(1, self.MAX_TTS_RETRIES + 1):
                if not failed_indices:
                    break
                still_failed = []
                for i in failed_indices:
                    seg  = segments[i]
                    text = seg.get('text', '').strip()
                    if not text:
                        continue
                    voice_file = os.path.join(temp_dir, f"line_{i}_r{retry}.wav")
                    sys_log.info(
                        f"    ↳ Retry {retry}/{self.MAX_TTS_RETRIES} "
                        f"đoạn {i} (ID={seg.get('id','?')}) [{text[:35]}]"
                    )
                    ok_tts = self.voice.run_tts(
                        text, voice=voice_param, output_path=voice_file, strict=True
                    )
                    if ok_tts and os.path.exists(voice_file) and os.path.getsize(voice_file) > 0:
                        results[i] = voice_file
                        sys_log.info(f"    ✅ Retry OK đoạn {i}")
                    else:
                        still_failed.append(i)
                failed_indices = still_failed

            if failed_indices:
                failed_info = [
                    f"  đoạn {i} ID={segments[i].get('id','?')}: "
                    f"[{segments[i].get('text','')[:40]}]"
                    for i in failed_indices
                ]
                sys_log.warning(
                    f"  ⚠️ {len(failed_indices)} đoạn vẫn lỗi sau "
                    f"{self.MAX_TTS_RETRIES} lần retry — bỏ qua (giọng KHÔNG thay đổi):\n"
                    + "\n".join(failed_info)
                )
            else:
                sys_log.info("  ✅ Tất cả đoạn lỗi đã retry thành công")

        # ── Ghép tất cả audio thành công vào canvas ───────────
        ok_count = 0
        for i, voice_file in sorted(results.items()):
            seg = segments[i]
            try:
                line_audio      = AudioSegment.from_file(voice_file)
                seg_duration_ms = int((seg['end'] - seg['start']) * 1000)
                line_audio      = self._fit_audio_to_segment(line_audio, seg_duration_ms, i, temp_dir)
                start_ms        = int(seg['start'] * 1000)
                dub_canvas      = dub_canvas.overlay(line_audio, position=start_ms)
                ok_count       += 1
            except Exception as e:
                sys_log.warning(f"  [!] Ghép đoạn {i}: {e}")

        sys_log.info(f"  ↳ Voice OK: {ok_count}/{len([s for s in segments if s.get('text','').strip()])} đoạn")
        return dub_canvas

    # ── SPEEDUP ────────────────────────────────────────────────
    @staticmethod
    def _build_atempo_chain(ratio: float) -> str:
        """
        Xây chuỗi atempo cho FFmpeg.
        Mỗi bước atempo chỉ cho phép 0.5–2.0, nên ratio > 2.0 phải chain.
        Ví dụ: 3.0x → "atempo=2.0,atempo=1.5"
                3.5x → "atempo=2.0,atempo=1.75"
                4.0x → "atempo=2.0,atempo=2.0"
        """
        filters = []
        r = ratio
        while r > 2.0:
            filters.append("atempo=2.0")
            r /= 2.0
        if r > 1.001:
            filters.append(f"atempo={r:.4f}")
        return ",".join(filters) if filters else "atempo=1.0"

    def _fit_audio_to_segment(
        self, audio: AudioSegment, seg_duration_ms: int,
        seg_idx: int, temp_dir: str
    ) -> AudioSegment:
        audio_ms = len(audio)
        if audio_ms <= seg_duration_ms:
            return audio

        # Không cap ở 2.0 nữa — dùng chained atempo để đủ tốc độ
        # Cap ở 4.0x để tránh giọng quá méo, không thể nghe được
        ratio = min(audio_ms / seg_duration_ms, 4.0)
        sys_log.info(
            f"  ⚡ Đoạn {seg_idx}: TTS={audio_ms}ms > Seg={seg_duration_ms}ms "
            f"→ speedup {ratio:.2f}x"
        )

        in_path  = os.path.join(temp_dir, f"spd_in_{seg_idx}.wav")
        out_path = os.path.join(temp_dir, f"spd_out_{seg_idx}.wav")
        audio.export(in_path, format="wav")

        atempo = self._build_atempo_chain(ratio)
        ok  = self._run_cmd_list(
            ["ffmpeg", "-i", in_path, "-filter:a", atempo, "-y", out_path],
            f"Speedup đoạn {seg_idx}"
        )

        if ok and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            sped: AudioSegment = AudioSegment.from_file(out_path)
            actual_ms = len(sped)
            # Nếu vẫn thừa (do làm tròn ratio), fade-out 80ms rồi trim nhẹ
            if actual_ms > seg_duration_ms + 200:
                sped = sped[:seg_duration_ms]          # type: ignore[assignment]
            elif actual_ms > seg_duration_ms:
                sped = sped.fade_out(min(80, actual_ms - seg_duration_ms + 20))  # type: ignore[attr-defined]
            sys_log.info(f"  ✅ Sau speedup: {len(sped)}ms (target {seg_duration_ms}ms)")
            return sped

        # Speedup thất bại → truncate audio gốc cho an toàn
        sys_log.warning(f"  ⚠️ Speedup thất bại đoạn {seg_idx} → truncate")
        truncated: AudioSegment = audio[:seg_duration_ms]  # type: ignore[assignment]
        return truncated

    # ── DEMUCS ─────────────────────────────────────────────────
    # Lỗi torchaudio save: torchaudio thiếu backend WAV trên một số môi trường
    # → thử lần lượt: mp3 → flac → wav (mp3/flac dùng backend khác, không bị lỗi)
    # Sau khi Demucs xong, convert sang WAV bằng pydub để các bước sau dùng bình thường.

    _DEMUCS_FORMATS = [
        ("mp3",  "--mp3",   ".mp3"),   # ưu tiên: mp3 backend luôn có
        ("flac", "--flac",  ".flac"),  # fallback 1: flac backend luôn có
        ("wav",  "",        ".wav"),   # fallback 2: wav (nếu môi trường đủ)
    ]

    # Danh sách stderr pattern không phải lỗi thật
    _STDERR_IGNORE = [
        "torchcodec", "libtorchcodec", "load_torchcodec",
        "load_library", "Could not load this library",
        "torchcodec loading traceback",
    ]

    def _separate_with_demucs(self, audio_path: str, temp_dir: str) -> Tuple[Optional[str], Optional[str]]:
        sys_log.info("  ↳ Tách nhạc nền bằng Demucs...")
        device     = "cuda" if torch.cuda.is_available() else "cpu"
        output_dir = os.path.join(temp_dir, "demucs")
        os.makedirs(output_dir, exist_ok=True)
        base       = os.path.splitext(os.path.basename(audio_path))[0]

        for fmt_name, fmt_flag, fmt_ext in self._DEMUCS_FORMATS:
            sys_log.info(f"  ↳ Demucs thử format [{fmt_name.upper()}] trên {device.upper()}...")
            cmd_list = [
                sys.executable, '-m', 'demucs',
                '--two-stems=vocals', '-n', 'htdemucs',
                '--device', device, '-o', output_dir, audio_path,
            ]
            if fmt_flag:
                cmd_list.insert(cmd_list.index('-o'), fmt_flag)

            try:
                result = subprocess.run(
                    cmd_list, capture_output=True, text=True,
                    timeout=600,
                    encoding="utf-8", errors="replace",
                    startupinfo=_mk_si(), creationflags=_mk_cflags(),
                    env={**os.environ,
                         "TORCHAUDIO_USE_BACKEND_DISPATCHER": "1",
                         "PYTHONUTF8": "1",
                         "PYTHONIOENCODING": "utf-8"}
                )

                # Lọc stderr noise (torchcodec, v.v.)
                stderr_lines = result.stderr.splitlines() if result.stderr else []
                real_errors  = [
                    ln for ln in stderr_lines
                    if not any(p in ln for p in self._STDERR_IGNORE)
                ]

                if real_errors:
                    # Kiểm tra xem lỗi có liên quan torchaudio save không
                    has_save_err = any("save" in ln or "ImportError" in ln or "raise" in ln
                                       for ln in real_errors)
                    if has_save_err and fmt_name != "wav":
                        sys_log.warning(f"  ↳ Format {fmt_name} lỗi save → thử format tiếp theo...")
                        continue
                    sys_log.warning(f"Demucs [{fmt_name}] stderr: {chr(10).join(real_errors[-8:])}")

                # Tìm file output — Demucs chuẩn lưu tại: output_dir/htdemucs/{base}/
                music_raw  = None
                vocals_raw = None
                folder = os.path.join(output_dir, "htdemucs", base)
                m = os.path.join(folder, f"no_vocals{fmt_ext}")
                v = os.path.join(folder, f"vocals{fmt_ext}")
                if not os.path.exists(m):
                    m = os.path.join(folder, "no_vocals.wav")
                if not os.path.exists(v):
                    v = os.path.join(folder, "vocals.wav")
                if os.path.exists(m) and os.path.exists(v):
                    music_raw, vocals_raw = m, v

                if not music_raw or not vocals_raw:
                    sys_log.warning(f"  ↳ Không tìm thấy output [{fmt_name}] → thử format tiếp...")
                    continue

                # Convert sang WAV chuẩn bằng pydub (không phụ thuộc torchaudio)
                music_wav  = os.path.join(output_dir, "no_vocals_final.wav")
                vocals_wav = os.path.join(output_dir, "vocals_final.wav")
                AudioSegment.from_file(music_raw).export(music_wav,  format="wav")
                AudioSegment.from_file(vocals_raw).export(vocals_wav, format="wav")

                sys_log.info(f"✅ Demucs OK! (format={fmt_name}, device={device})")
                return music_wav, vocals_wav

            except subprocess.TimeoutExpired:
                sys_log.error(f"Demucs timeout [{fmt_name}] (>10 phút)")
                break
            except FileNotFoundError:
                sys_log.warning("Demucs chưa cài: pip install demucs")
                break
            except Exception as e:
                sys_log.warning(f"Demucs [{fmt_name}] exception: {e}")
                continue

        sys_log.info("⚠️ Fallback: dùng FFmpeg highpass filter thay thế Demucs")
        return self._ffmpeg_vocal_separation(audio_path, output_dir)

    # ── VISUALS CONFIG ─────────────────────────────────────────
    def _load_visuals_config(self) -> dict:
        """Đọc visuals_config.json (intro/outro paths, v.v.)."""
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "visuals_config.json"
        )
        try:
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            sys_log.warning(f"Không đọc visuals_config: {e}")
        return {}

    def _probe_video_size(self, video_path: str) -> tuple:
        """Trả về (width, height) của video bằng ffprobe. Mặc định 1920x1080."""
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height', '-of', 'csv=p=0', video_path],
                capture_output=True, text=True, timeout=10,
                startupinfo=_mk_si(), creationflags=_mk_cflags()
            )
            parts = result.stdout.strip().split(',')
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
        except Exception as e:
            sys_log.warning(f"ffprobe lỗi: {e}")
        return 1920, 1080

    def _apply_intro_outro(self, main_video: str, intro_path: str, outro_path: str):
        """
        Ghép intro + main_video + outro bằng FFmpeg filter_complex.
        Chuẩn hóa scale/fps/audio từng clip → concat → re-encode an toàn.
        Tránh màn hình đen và thời lượng sai do codec/resolution khác nhau.
        """
        parts = []
        if intro_path and os.path.isfile(intro_path):
            parts.append(intro_path)
        parts.append(main_video)
        if outro_path and os.path.isfile(outro_path):
            parts.append(outro_path)

        if len(parts) == 1:
            return  # Không có intro/outro

        out_dir = os.path.dirname(main_video)
        tmp_out = os.path.join(out_dir, "_tmp_concat_out.mp4")

        w, h = self._probe_video_size(main_video)
        fps  = 30
        n    = len(parts)

        # Mỗi clip: scale → pad → setsar → fps / aformat
        vf_parts = []
        af_parts = []
        for i in range(n):
            vf_parts.append(
                f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}]"
            )
            af_parts.append(
                f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}]"
            )

        concat_in = "".join(f"[v{i}][a{i}]" for i in range(n))
        filter_complex = (
            ";".join(vf_parts) + ";" +
            ";".join(af_parts) + ";" +
            f"{concat_in}concat=n={n}:v=1:a=1[outv][outa]"
        )

        # Build as list to avoid shell injection from paths with special characters
        cmd_list = ["ffmpeg"]
        for p in parts:
            cmd_list += ["-i", p]
        cmd_list += [
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-y", tmp_out,
        ]

        ok = self._run_cmd_list(cmd_list, "Ghép intro/outro (filter_complex)")

        if ok and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 1024:
            os.replace(tmp_out, main_video)
            sys_log.info(f"✅ Intro/Outro ghép OK ({n} đoạn, {w}×{h})")
        else:
            try:
                if os.path.exists(tmp_out):
                    os.remove(tmp_out)
            except OSError:
                pass
            sys_log.warning("⚠️ Ghép intro/outro thất bại — giữ nguyên video chính")

    # ── VISUALS: Orchestrator → GPU fast path → OpenCV fallback ────
    def _apply_visuals(self, video_path: str, visuals: dict,
                       srt_path: str) -> None:
        """
        Orchestrator: thử GPU fast path trước (FFmpeg+NVENC/AMF),
        fallback về OpenCV+PIL nếu GPU thất bại (đảm bảo tiếng Việt).
        Khi không có GPU encoder (libx264 CPU), bỏ qua filter_complex
        và dùng OpenCV ngay — tránh lỗi -22 (Invalid argument) trên FFmpeg CPU.
        """
        blur_on = visuals.get("blur_enabled", False)
        sub_on  = os.path.isfile(srt_path)
        if not blur_on and not sub_on:
            self._ensure_h264_compat(video_path)
            return

        enc = self._get_video_encoder()
        if enc == "libx264":
            # Không có GPU encoder → filter_complex path không đáng tin cậy trên
            # Windows FFmpeg CPU build → dùng OpenCV+PIL ngay (chất lượng như nhau)
            sys_log.info("  ↳ Không có GPU encoder → OpenCV path trực tiếp")
            self._apply_visuals_opencv(video_path, visuals, srt_path)
            return

        gpu_ok, sub_handled = self._apply_visuals_gpu(video_path, visuals, srt_path)
        if gpu_ok and sub_handled:
            return
        if gpu_ok and not sub_handled and sub_on:
            # GPU xử lý blur OK nhưng subtitle filter lỗi (thiếu libass)
            # → OpenCV chỉ hardsub, không blur lại
            sys_log.info("  ↳ GPU không xử lý subtitle (thiếu libass) → OpenCV hardsub only")
            no_blur = {**visuals, "blur_enabled": False}
            self._apply_visuals_opencv(video_path, no_blur, srt_path)
            return
        sys_log.warning("  ⚠️ GPU render thất bại → fallback OpenCV+PIL")
        self._apply_visuals_opencv(video_path, visuals, srt_path)

    def _ensure_h264_compat(self, video_path: str) -> None:
        """Re-encode sang H.264/yuv420p để đảm bảo tương thích mọi player.
        Luôn chạy khi không có visuals — preset ultrafast nên rất nhanh."""
        # Kiểm tra codec trước; nếu đã là H.264/yuv420p thì bỏ qua để tiết kiệm thời gian
        try:
            r = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=codec_name,pix_fmt', '-of', 'csv=p=0', video_path],
                capture_output=True, text=True, timeout=10,
                startupinfo=_mk_si(), creationflags=_mk_cflags()
            )
            info = r.stdout.strip().lower()
        except Exception:
            info = ""

        # Bỏ qua nếu đã là H.264 yuv420p (tương thích hoàn toàn)
        if 'h264' in info and 'yuv420p' in info:
            return

        sys_log.info(f"  ↳ Compat encode: {codec.upper()} → H.264 (tương thích Windows)...")
        enc = self._get_video_encoder()
        if enc == "h264_nvenc":
            enc_args = ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '22', '-pix_fmt', 'yuv420p']
        elif enc == "h264_amf":
            enc_args = ['-c:v', 'h264_amf', '-quality', 'balanced',
                        '-rc', 'cqp', '-qp_i', '22', '-qp_p', '22', '-pix_fmt', 'yuv420p']
        else:
            enc_args = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-pix_fmt', 'yuv420p']

        tmp_out = video_path + ".tmp_compat.mp4"
        ok = self._run_cmd_list(
            ['ffmpeg', '-i', video_path, '-map', '0:v', '-map', '0:a?',
             *enc_args, '-c:a', 'copy', '-y', tmp_out],
            "Compat encode H.264"
        )
        if ok and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 1024:
            os.replace(tmp_out, video_path)
            sys_log.info("  ✅ Compat encode OK → H.264/yuv420p")
        else:
            try:
                if os.path.exists(tmp_out):
                    os.remove(tmp_out)
            except OSError:
                pass

    def _apply_visuals_gpu(self, video_path: str, visuals: dict,
                           srt_path: str) -> "tuple[bool, bool]":
        """
        Fast path: FFmpeg + ASS subtitle filter + GPU encoder chain.
        Thử h264_nvenc → h264_amf → libx264.
        Trả về (gpu_ok, sub_handled):
          (True,  True)  → blur + subtitle đều xong
          (True,  False) → chỉ blur xong, subtitle chưa render (thiếu libass)
          (False, False) → hoàn toàn thất bại, cần fallback OpenCV
        """
        blur_on = visuals.get("blur_enabled", False)
        sub_on  = os.path.isfile(srt_path)
        if not blur_on and not sub_on:
            return True, True

        tmp_dir  = os.path.dirname(video_path)
        ass_path = os.path.join(tmp_dir, "_tmp_sub.ass")

        vw, vh = self._probe_video_size(video_path)
        if sub_on:
            self._generate_ass(srt_path, ass_path, visuals, vw, vh)
            if not os.path.exists(ass_path):
                sub_on = False

        def _blur_params():
            bx = max(0.0,  visuals.get("blur_x", 0)   / 1920)
            by = max(0.0,  visuals.get("blur_y", 900)  / 1080)
            bw = max(0.01, visuals.get("blur_w", 400)  / 1920)
            bh = max(0.01, visuals.get("blur_h",  60)  / 1080)
            bs = int(visuals.get("blur_strength", 20))
            bx = min(bx, 1.0 - bw); by = min(by, 1.0 - bh)
            # boxblur radius phải < crop_dimension/2, không thì FFmpeg trả -22
            crop_w_px = max(4, int(bw * vw))
            crop_h_px = max(4, int(bh * vh))
            max_r = max(1, min(crop_w_px, crop_h_px) // 2 - 1)
            bs = min(bs, max_r)
            return bx, by, bw, bh, bs

        # Escape Windows path for ASS filter: C:\path → C\:/path
        def _esc_ass(p: str) -> str:
            return p.replace("\\", "/").replace(":", "\\:")

        enc = self._get_video_encoder()
        if enc == "h264_nvenc":
            enc_args = ['-c:v', 'h264_nvenc', '-preset', 'p6', '-tune', 'hq',
                        '-rc', 'vbr', '-cq', '22', '-pix_fmt', 'yuv420p']
            hw_args  = ['-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda']
        elif enc == "h264_amf":
            enc_args = ['-c:v', 'h264_amf', '-quality', 'balanced',
                        '-rc', 'cqp', '-qp_i', '22', '-qp_p', '22',
                        '-pix_fmt', 'yuv420p']
            hw_args  = []
        else:
            enc_args = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                        '-pix_fmt', 'yuv420p']
            hw_args  = []

        def _run_gpu(fc: str, label: str) -> bool:
            tmp_out = video_path + ".tmp_gpu.mp4"
            sys_log.info(f"  ↳ GPU render [{enc}] {label}...")
            ok = self._run_cmd_list(
                ['ffmpeg', *hw_args, '-i', video_path,
                 '-filter_complex', fc,
                 '-map', '[v_final]', '-map', '0:a?',
                 *enc_args, '-c:a', 'copy',
                 '-movflags', '+faststart', '-y', tmp_out],
                f"GPU {label}"
            )
            if ok and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 1024:
                os.replace(tmp_out, video_path)
                sys_log.info(f"  ✅ GPU {label} OK [{enc}]")
                return True
            try:
                if os.path.exists(tmp_out):
                    os.remove(tmp_out)
            except OSError:
                pass
            sys_log.warning(f"  ⚠️ GPU {label} thất bại [{enc}]")
            return False

        def _blur_fc() -> str:
            bx, by, bw, bh, bs = _blur_params()
            return (
                f"[0:v]split[v_main][v_blur_src];"
                f"[v_blur_src]crop=iw*{bw:.4f}:ih*{bh:.4f}:iw*{bx:.4f}:ih*{by:.4f},"
                f"boxblur={bs}:10[v_b_only];"
                f"[v_main][v_b_only]overlay=W*{bx:.4f}:H*{by:.4f},format=yuv420p[v_final]"
            )

        def _cleanup_ass():
            if os.path.exists(ass_path):
                try:
                    os.remove(ass_path)
                except OSError:
                    pass

        if blur_on and sub_on:
            bx, by, bw, bh, bs = _blur_params()
            ass_fwd = _esc_ass(ass_path)
            fc_full = (
                f"[0:v]split[v_main][v_blur_src];"
                f"[v_blur_src]crop=iw*{bw:.4f}:ih*{bh:.4f}:iw*{bx:.4f}:ih*{by:.4f},"
                f"boxblur={bs}:10[v_b_only];"
                f"[v_main][v_b_only]overlay=W*{bx:.4f}:H*{by:.4f}[v_blurred];"
                f"[v_blurred]subtitles='{ass_fwd}',format=yuv420p[v_final]"
            )
            if _run_gpu(fc_full, "Blur+ASS"):
                _cleanup_ass()
                return True, True
            # subtitles filter thất bại (thường do thiếu libass) → thử blur-only
            sys_log.info("  ↳ Blur+ASS thất bại → thử GPU Blur-only, subtitle sẽ do OpenCV xử lý")
            _cleanup_ass()
            if _run_gpu(_blur_fc(), "Blur"):
                return True, False  # blur OK, subtitle chưa xử lý
            return False, False

        elif blur_on:
            ok = _run_gpu(_blur_fc(), "Blur")
            return ok, True  # không có subtitle nên sub_handled=True

        else:  # sub_on only
            ass_fwd = _esc_ass(ass_path)
            fc_sub = f"[0:v]subtitles='{ass_fwd}',format=yuv420p[v_final]"
            ok = _run_gpu(fc_sub, "ASS")
            _cleanup_ass()
            if ok:
                return True, True
            # subtitle filter thất bại (thiếu libass) → báo caller dùng OpenCV
            return False, False

    # ── VISUALS: OpenCV frame-by-frame + PIL (fallback) ────────────
    def _apply_visuals_opencv(self, video_path: str, visuals: dict,
                              srt_path: str) -> None:
        """
        Fallback: Xử lý blur + hardsub frame-by-frame bằng OpenCV + PIL.
        Dùng PIL → tiếng Việt hiển thị đúng (không bị lỗi font/encoding).
        Fallback về FFmpeg filter_complex nếu cv2 chưa cài.
        """
        blur_on = visuals.get("blur_enabled", False)
        sub_on  = os.path.isfile(srt_path)
        if not blur_on and not sub_on:
            return

        try:
            import cv2
        except ImportError:
            sys_log.warning("⚠️ opencv-python chưa cài → fallback FFmpeg filter_complex")
            self._apply_visuals_ffmpeg(video_path, visuals, srt_path)
            return

        try:
            import importlib
            importlib.import_module("PIL")
            PIL_OK = True
        except ImportError:
            PIL_OK = False
            sys_log.warning("⚠️ Pillow chưa cài → text có thể bị vỡ ký tự tiếng Việt")

        # Parse SRT
        srt_segs = self._parse_srt_file(srt_path) if sub_on else []

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            sys_log.error(f"❌ Không mở được video: {video_path}")
            return

        W  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Compute blur ROI in pixels
        blur_roi = None
        if blur_on:
            bx = max(0, int(visuals.get("blur_x", 0)   * W / 1920))
            by = max(0, int(visuals.get("blur_y", 900)  * H / 1080))
            bw = max(1, int(visuals.get("blur_w", 400)  * W / 1920))
            bh = max(1, int(visuals.get("blur_h",  60)  * H / 1080))
            bw = min(bw, W - bx);  bh = min(bh, H - by)
            ks = visuals.get("blur_strength", 20) * 2 + 1  # odd kernel
            blur_roi = (bx, by, bw, bh, ks)

        label   = "Blur+Hardsub" if blur_on and sub_on else ("Blur" if blur_on else "Hardsub")
        tmp_out = video_path + ".tmp_vis.mp4"
        sys_log.info(f"  ↳ [OpenCV] {label} | {W}x{H} @{fps:.2f}fps | {total} frames")

        # Pipe frames → FFmpeg (H.264 encode + audio copy from original)
        enc = self._get_video_encoder()
        if enc == "h264_nvenc":
            enc_args = ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '22',
                        '-pix_fmt', 'yuv420p']
        elif enc == "h264_amf":
            enc_args = ['-c:v', 'h264_amf', '-quality', 'balanced',
                        '-rc', 'cqp', '-qp_i', '22', '-qp_p', '22',
                        '-pix_fmt', 'yuv420p']
        else:
            enc_args = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                        '-pix_fmt', 'yuv420p']
        ff_cmd = [
            'ffmpeg',
            '-f', 'rawvideo', '-pixel_format', 'bgr24',
            '-video_size', f'{W}x{H}', '-framerate', str(fps),
            '-i', 'pipe:0',
            '-i', video_path,
            *enc_args,
            '-c:a', 'copy',
            '-map', '0:v:0', '-map', '1:a?',
            '-movflags', '+faststart',
            '-shortest',
            '-y', tmp_out,
        ]
        proc = subprocess.Popen(ff_cmd, stdin=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                startupinfo=_mk_si(), creationflags=_mk_cflags())
        if proc.stdin is None or proc.stderr is None:
            raise RuntimeError("Không mở được pipe stdin/stderr cho FFmpeg OpenCV render")

        frame_idx = 0
        pipe_ok   = True
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                t_sec = frame_idx / fps

                # Blur
                if blur_roi:
                    bx, by, bw, bh, ks = blur_roi
                    roi = frame[by:by+bh, bx:bx+bw]
                    frame[by:by+bh, bx:bx+bw] = cv2.GaussianBlur(roi, (ks, ks), 0)

                # Subtitle text
                if srt_segs:
                    text = self._get_sub_at_time(srt_segs, t_sec)
                    if text:
                        if PIL_OK:
                            frame = self._draw_sub_pil(frame, text, visuals, W, H)
                        else:
                            frame = self._draw_sub_cv2(frame, text, visuals, W, H)

                try:
                    proc.stdin.write(frame.tobytes())
                except (BrokenPipeError, OSError) as e:
                    sys_log.error(f"  [!] FFmpeg pipe broke: {e}")
                    pipe_ok = False
                    break

                frame_idx += 1
                if frame_idx % 500 == 0:
                    pct = frame_idx / total * 100 if total else 0
                    sys_log.info(f"    → {frame_idx}/{total} frames ({pct:.0f}%)")
        finally:
            cap.release()

        # Close stdin (signals EOF to FFmpeg), then drain stderr, then wait
        try:
            proc.stdin.close()
        except OSError:
            pass
        stderr_b = proc.stderr.read()
        proc.wait()
        ok = (proc.returncode == 0) and pipe_ok
        if not ok:
            sys_log.error(f"  [!] FFmpeg encode lỗi: {stderr_b[-400:].decode('utf-8','replace')}")

        if ok and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 1024:
            os.replace(tmp_out, video_path)
            sys_log.info(f"  ✅ OpenCV {label} OK ({frame_idx} frames)")
        else:
            try:
                if os.path.exists(tmp_out):
                    os.remove(tmp_out)
            except OSError:
                pass
            sys_log.warning(f"  ⚠️ OpenCV {label} thất bại — bỏ qua")

    def _apply_visuals_ffmpeg(self, video_path: str, visuals: dict,
                              srt_path: str) -> None:
        """Fallback: FFmpeg filter_complex (dùng khi không có cv2)."""
        blur_on = visuals.get("blur_enabled", False)
        sub_on  = os.path.isfile(srt_path)
        if not blur_on and not sub_on:
            return
        tmp_out = video_path + ".tmp_vis.mp4"

        bx = by = bw = bh = bs = 0.0
        if blur_on:
            bx = max(0.0, visuals.get("blur_x", 0)    / 1920)
            by = max(0.0, visuals.get("blur_y", 900)   / 1080)
            bw = max(0.01, visuals.get("blur_w", 400)  / 1920)
            bh = max(0.01, visuals.get("blur_h",  60)  / 1080)
            bs = visuals.get("blur_strength", 20)
            bx = min(bx, 1.0 - bw);  by = min(by, 1.0 - bh)

        sub_filter = ""
        if sub_on:
            def _hex_bgr(h: str, a: str = "00") -> str:
                h = h.lstrip("#")
                return f"&H{a}{h[4:6]}{h[2:4]}{h[0:2]}" if len(h) == 6 else f"&H{a}FFFFFF"
            font    = visuals.get("sub_font", "Arial")
            font_sz = max(10, int(visuals.get("sub_size", 18) * 288 / 1080))
            bstyle  = {"outline":1,"box":3,"shadow":1,"outline+shadow":4}.get(
                          visuals.get("sub_border_style", "outline"), 1)
            outline_w = visuals.get("sub_border_width", 2)
            shadow_v  = 1 if "shadow" in visuals.get("sub_border_style", "") else 0
            custom_y  = visuals.get("sub_custom_y", -1)
            if custom_y >= 0:
                margin_v = max(5, int((1080 - custom_y) * 288 / 1080)); align = 2
            else:
                margin_v = max(5, int(visuals.get("sub_margin_v", 30) * 288 / 1080))
                align = {"top":8,"center":5,"bottom":2}.get(visuals.get("sub_position","bottom"),2)
            force_style = (f"Fontname={font},FontSize={font_sz},"
                           f"PrimaryColour={_hex_bgr(visuals.get('sub_color_hex','#FFFFFF'))},"
                           f"OutlineColour={_hex_bgr(visuals.get('sub_border_color_hex','#000000'))},"
                           f"BorderStyle={bstyle},Outline={outline_w},Shadow={shadow_v},"
                           f"Alignment={align},MarginV={margin_v}")
            # FFmpeg subtitles filter: escape backslash trước, rồi escape single-quote
            srt_filt   = srt_path.replace("\\", "/").replace("'", "\\'")
            sub_filter = f"subtitles='{srt_filt}':force_style='{force_style}'"

        if blur_on and sub_on:
            fc = (f"[0:v]split[v_main][v_blur_src];"
                  f"[v_blur_src]crop=iw*{bw:.4f}:ih*{bh:.4f}:iw*{bx:.4f}:ih*{by:.4f},"
                  f"boxblur={bs}:10[v_b_only];"
                  f"[v_main][v_b_only]overlay=W*{bx:.4f}:H*{by:.4f}[v_blurred];"
                  f"[v_blurred]{sub_filter}[v_final]"); label = "Blur+Hardsub"
        elif blur_on:
            fc = (f"[0:v]split[v_main][v_blur_src];"
                  f"[v_blur_src]crop=iw*{bw:.4f}:ih*{bh:.4f}:iw*{bx:.4f}:ih*{by:.4f},"
                  f"boxblur={bs}:10[v_b_only];"
                  f"[v_main][v_b_only]overlay=W*{bx:.4f}:H*{by:.4f}[v_final]"); label = "Blur"
        else:
            fc = f"[0:v]{sub_filter}[v_final]"; label = "Hardsub"

        ok = self._run_cmd_list(
            ['ffmpeg', '-i', video_path, '-filter_complex', fc,
             '-map', '[v_final]', '-map', '0:a?',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
             '-c:a', 'copy', '-y', tmp_out], f"Áp dụng {label} (FFmpeg)")
        if ok and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 1024:
            os.replace(tmp_out, video_path)
        else:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            sys_log.warning(f"  ⚠️ FFmpeg {label} thất bại — bỏ qua")

    # ── Subtitle helpers ─────────────────────────────────────────

    @staticmethod
    def _get_sub_at_time(segs: list, t_sec: float) -> str:
        for seg in segs:
            if seg["start"] <= t_sec <= seg["end"]:
                return seg["text"].replace("\n", " ").strip()
        return ""

    @staticmethod
    def _find_font_pil(font_name: str, size: int):
        from PIL import ImageFont
        import glob

        # Tên file thông dụng từ font_name (ví dụ "Arial" → arial.ttf, arialuni.ttf...)
        base = font_name.replace(" ", "")
        candidates = [
            f"{font_name}.ttf", f"{font_name}.TTF",
            f"{base}.ttf",      f"{base}.TTF",
            f"{base.lower()}.ttf",
            f"{base}bd.ttf",    f"{base}b.ttf",   # bold variants
            f"{base}uni.ttf",                      # unicode variant
        ]

        dirs = [
            "C:/Windows/Fonts",
            os.path.expanduser("~/AppData/Local/Microsoft/Windows/Fonts"),
            "/usr/share/fonts/truetype",
            "/usr/share/fonts",
            "/System/Library/Fonts",
            "/Library/Fonts",
        ]

        for d in dirs:
            if not os.path.isdir(d):
                continue
            for c in candidates:
                p = os.path.join(d, c)
                if os.path.isfile(p):
                    try:
                        return ImageFont.truetype(p, size)
                    except Exception:
                        pass
            # Tìm bằng glob (case-insensitive trên Windows)
            for pat in (f"{base}*.ttf", f"{base.lower()}*.ttf"):
                for p in glob.glob(os.path.join(d, pat)):
                    try:
                        return ImageFont.truetype(p, size)
                    except Exception:
                        pass

        # Thử load trực tiếp (hệ thống có thể tìm được)
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            pass

        # Fallback: tìm bất kỳ .ttf trong Windows Fonts
        for p in glob.glob("C:/Windows/Fonts/arial*.ttf") + glob.glob("C:/Windows/Fonts/Arial*.ttf"):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass

        # Last resort: bitmap default (rất nhỏ — chỉ khi không có font nào)
        try:
            return ImageFont.load_default(size=size)   # Pillow ≥ 10.1
        except TypeError:
            return ImageFont.load_default()

    @staticmethod
    def _anchor_sub_pos(anchor: str, margin_y: float, margin_x: float,
                        tw: int, th: int, W: int, H: int) -> Tuple[int, int]:
        """Tính (cx, cy) vẽ text từ anchor string + % margin."""
        parts  = anchor.split("-")
        v_part = parts[0] if len(parts) >= 1 else "bottom"
        h_part = parts[1] if len(parts) >= 2 else "center"
        if h_part == "left":
            cx = int(W * margin_x)
        elif h_part == "right":
            cx = max(0, int(W - tw - W * margin_x))
        else:
            cx = (W - tw) // 2
        if v_part == "top":
            cy = int(H * margin_y)
        elif v_part == "middle":
            cy = (H - th) // 2
        else:  # bottom
            cy = H - int(H * margin_y) - th
        return cx, cy

    @staticmethod
    def _measure_text_pil(draw, text: str, font) -> "tuple[int, int]":
        """Đo kích thước text (tw, th) tương thích Pillow 8–11."""
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            return draw.textsize(text, font=font)  # type: ignore[attr-defined]

    def _wrap_text_pil(self, draw, text: str, font, max_width: int) -> str:
        """Ngắt dòng text cho vừa max_width pixel."""
        words = text.split()
        if not words:
            return text
        lines: list = []
        current: list = []
        for word in words:
            test = " ".join(current + [word])
            w, _ = self._measure_text_pil(draw, test, font)
            if w <= max_width or not current:
                current.append(word)
            else:
                lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
        return "\n".join(lines)

    def _draw_sub_pil(self, frame, text: str, visuals: dict, W: int, H: int):
        """Vẽ phụ đề bằng PIL — hỗ trợ Unicode tiếng Việt đầy đủ."""
        import numpy as np
        import cv2
        from PIL import Image, ImageDraw

        font_name    = visuals.get("sub_font", "Arial")
        # Scale font giống _generate_ass: sub_size * H/1080 * 1.4
        raw_size     = visuals.get("sub_size", 24)
        font_size    = max(14, int(raw_size * H / 1080 * 1.4))
        color_hex    = visuals.get("sub_color_hex", "#FFFFFF")
        border_hex   = visuals.get("sub_border_color_hex", "#000000")
        border_w     = int(visuals.get("sub_border_width", 2))
        anchor       = visuals.get("sub_anchor", "bottom-center")
        margin_y_pct = float(visuals.get("sub_margin_y_pct", 0.10))
        margin_x_pct = float(visuals.get("sub_margin_x_pct", 0.03))
        max_text_w   = int(W * (1.0 - 2 * margin_x_pct))

        font = self._find_font_pil(font_name, font_size)
        img  = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img)

        # Wrap text để không tràn frame
        text = self._wrap_text_pil(draw, text, font, max_text_w)

        tw, th = self._measure_text_pil(draw, text, font)

        cx, cy = self._anchor_sub_pos(anchor, margin_y_pct, margin_x_pct, int(tw), int(th), W, H)
        # Clamp vào vùng an toàn
        cx = max(0, min(cx, W - tw))
        cy = max(0, min(cy, H - th))

        # Vẽ viền bằng offset — 8 hướng thay vì vòng lặp O(4w²)
        if border_w > 0:
            for ddx, ddy in [(-border_w, 0), (border_w, 0),
                             (0, -border_w), (0, border_w),
                             (-border_w, -border_w), (border_w, -border_w),
                             (-border_w, border_w), (border_w, border_w)]:
                draw.text((cx + ddx, cy + ddy), text, font=font, fill=border_hex)
        draw.text((cx, cy), text, font=font, fill=color_hex)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    @staticmethod
    def _draw_sub_cv2(frame, text: str, visuals: dict, W: int, H: int):
        """Fallback: vẽ phụ đề bằng cv2.putText (ASCII only)."""
        import cv2

        def _hex_bgr(h: str):
            h = h.lstrip("#")
            return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))

        scale   = max(0.5, visuals.get("sub_size", 24) / 36.0)
        thick   = max(1, visuals.get("sub_border_width", 2))
        color   = _hex_bgr(visuals.get("sub_color_hex", "#FFFFFF"))
        border  = _hex_bgr(visuals.get("sub_border_color_hex", "#000000"))
        margin  = visuals.get("sub_margin_v", 30)
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, thick)
        cx = (W - tw) // 2; cy = H - margin
        cv2.putText(frame, text, (cx, cy), cv2.FONT_HERSHEY_DUPLEX, scale, border, thick + 2, cv2.LINE_AA)
        cv2.putText(frame, text, (cx, cy), cv2.FONT_HERSHEY_DUPLEX, scale, color,  thick,     cv2.LINE_AA)
        return frame

    # ASS alignment: 7=↖ 8=↑ 9=↗ / 4=← 5=· 6=→ / 1=↙ 2=↓ 3=↘
    _ANCHOR_TO_ALIGN = {
        "top-left": 7,    "top-center": 8,    "top-right": 9,
        "middle-left": 4, "middle-center": 5, "middle-right": 6,
        "bottom-left": 1, "bottom-center": 2, "bottom-right": 3,
    }

    def _generate_ass(self, srt_path: str, ass_path: str,
                      visuals: dict, vw: int, vh: int) -> None:
        """Tạo file ASS từ SRT + styling từ visuals_config (anchor-based)."""
        font    = visuals.get("sub_font", "Arial")
        pt_size = visuals.get("sub_size", 24)
        px_size = max(12, int(pt_size * vh / 1080 * 1.4))

        def to_ass(hex_str: str, alpha: str = "00") -> str:
            h = hex_str.lstrip("#")
            if len(h) == 6:
                return f"&H{alpha}{h[4:6]}{h[2:4]}{h[0:2]}"
            return f"&H{alpha}FFFFFF"

        prim    = to_ass(visuals.get("sub_color_hex",        "#FFFFFF"))
        outline = to_ass(visuals.get("sub_border_color_hex", "#000000"))
        back    = to_ass("#000000", "80")
        bw      = visuals.get("sub_border_width", 2)
        bstyle  = {"outline":1,"box":3,"shadow":1,"outline+shadow":4}.get(
                      visuals.get("sub_border_style", "outline"), 1)
        shadow  = 1 if "shadow" in visuals.get("sub_border_style", "") else 0

        anchor       = visuals.get("sub_anchor", "bottom-center")
        margin_y_pct = float(visuals.get("sub_margin_y_pct", 0.10))
        margin_x_pct = float(visuals.get("sub_margin_x_pct", 0.03))
        alignment    = self._ANCHOR_TO_ALIGN.get(anchor, 2)
        margin_v     = max(10, int(vh * margin_y_pct))
        margin_lr    = max(10, int(vw * margin_x_pct))

        header = (
            "[Script Info]\nScriptType: v4.00+\n"
            f"PlayResX: {vw}\nPlayResY: {vh}\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{font},{px_size},"
            f"{prim},&H000000FF,{outline},{back},"
            f"0,0,0,0,100,100,0,0,{bstyle},{bw},{shadow},"
            f"{alignment},{margin_lr},{margin_lr},{margin_v},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text\n"
        )
        segs = self._parse_srt_file(srt_path)
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header)
            for seg in segs:
                s = self._to_ass_time(seg["start"])
                e = self._to_ass_time(seg["end"])
                t = seg["text"].replace("\n", "\\N").strip()
                f.write(f"Dialogue: 0,{s},{e},Default,,0,0,0,,{t}\n")
        sys_log.info(f"  ↳ ASS: {len(segs)} dòng → {os.path.basename(ass_path)}")

    def _parse_srt_file(self, srt_path: str) -> list:
        segs = []
        try:
            with open(srt_path, "r", encoding="utf-8") as f:
                content = f.read()
            for block in content.strip().split("\n\n"):
                lines = block.strip().splitlines()
                if len(lines) < 3:
                    continue
                try:
                    s, e = lines[1].split(" --> ")
                    segs.append({
                        "start": self._srt_ts_to_sec(s.strip()),
                        "end":   self._srt_ts_to_sec(e.strip()),
                        "text":  "\n".join(lines[2:]),
                    })
                except (ValueError, IndexError):
                    continue
        except Exception as ex:
            sys_log.warning(f"Parse SRT: {ex}")
        return segs

    @staticmethod
    def _srt_ts_to_sec(ts: str) -> float:
        ts = ts.replace(",", ".")
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    @staticmethod
    def _to_ass_time(sec: float) -> str:
        h  = int(sec // 3600)
        m  = int((sec % 3600) // 60)
        s  = sec % 60
        cs = int((s % 1) * 100)
        return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"

    def _ffmpeg_vocal_separation(self, audio_path: str, output_dir: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Fallback khi Demucs thất bại: tách nhạc nền / giọng bằng FFmpeg filter.
        Chất lượng thấp hơn Demucs nhưng không cần torchaudio.
        """
        music_out  = os.path.join(output_dir, "no_vocals_final.wav")
        vocals_out = os.path.join(output_dir, "vocals_final.wav")
        try:
            ok1 = self._run_cmd_list(
                ['ffmpeg', '-i', audio_path,
                 '-af', 'pan=stereo|c0=0.5*c0-0.5*c1|c1=0.5*c1-0.5*c0',
                 '-y', music_out],
                "FFmpeg music separation"
            )
            ok2 = self._run_cmd_list(
                ['ffmpeg', '-i', audio_path,
                 '-af', 'highpass=f=200,lowpass=f=3400',
                 '-y', vocals_out],
                "FFmpeg vocal separation"
            )
            if ok1 and ok2 and os.path.exists(music_out) and os.path.exists(vocals_out):
                sys_log.info("✅ FFmpeg fallback separation OK")
                return music_out, vocals_out
        except Exception as e:
            sys_log.warning(f"FFmpeg fallback lỗi: {e}")
        return None, None

    def _apply_copyright_bypass(self, video_path: str, visuals: dict) -> None:
        """Áp dụng các bộ lọc lách bản quyền: flip/zoom/crop/color/noise/fps/res/logo."""
        flip_h       = visuals.get("flip_h", False)
        flip_v       = visuals.get("flip_v", False)
        zoom_on      = visuals.get("zoom_enabled", False)
        zoom_f       = float(visuals.get("zoom_factor", 1.03))
        crop_on      = visuals.get("crop_enabled", False)
        crop_px      = int(visuals.get("crop_px", 5))
        color_preset = visuals.get("color_preset", "Gốc")
        bright       = int(visuals.get("brightness", 0))
        sat          = float(visuals.get("saturation", 1.0))
        contrast     = float(visuals.get("contrast", 1.0))
        fps_on       = visuals.get("fps_enabled", False)
        fps_val      = visuals.get("fps_value", "Gốc")
        res_on       = visuals.get("res_enabled", False)
        res_val      = visuals.get("res_value", "Gốc")
        noise_on     = visuals.get("noise_enabled", False)
        noise_str    = int(visuals.get("noise_strength", 3))
        gop_on       = visuals.get("gop_reencode", False)
        h265_on      = visuals.get("codec_h265", False)
        exif_on      = visuals.get("exif_clear", False)
        meta_on      = visuals.get("meta_inject", False)
        meta_title   = visuals.get("meta_title", "")
        border_on    = visuals.get("border_enabled", False)
        border_w_px  = int(visuals.get("border_width", 5))
        border_col   = visuals.get("border_color", "#000000").lstrip("#")
        logo_on      = visuals.get("logo_enabled", False)
        logo_path    = visuals.get("logo_path", "")
        logo_pos     = visuals.get("logo_position", "Góc trên phải")
        logo_op      = visuals.get("logo_opacity", 80) / 100.0
        logo_w       = int(visuals.get("logo_w", 0))
        logo_h       = int(visuals.get("logo_h", 0))

        COLOR_PRESETS = {
            "Cinematic": "eq=brightness=0.05:saturation=0.8:contrast=1.1,curves=r='0/0 0.5/0.48 1/1':b='0/0 0.5/0.52 1/1'",
            "Vivid":     "eq=brightness=0.05:saturation=1.5:contrast=1.15",
            "B&W":       "hue=s=0,eq=contrast=1.1:brightness=0.02",
            "Warm":      "curves=r='0/0 0.5/0.53 1/1':g='0/0 0.5/0.5 1/1':b='0/0 0.5/0.47 1/1',eq=saturation=1.1",
            "Cool":      "curves=r='0/0 0.5/0.47 1/1':g='0/0 0.5/0.5 1/1':b='0/0 0.5/0.53 1/1',eq=saturation=0.95",
            "Vintage":   "curves=r='0/0.05 1/0.95':g='0/0.02 1/0.9':b='0/0.08 1/0.85',hue=s=0.75,vignette",
        }
        LOGO_POS_MAP = {
            "Góc trên trái":  "10:10",
            "Góc trên phải":  "main_w-overlay_w-10:10",
            "Góc dưới trái":  "10:main_h-overlay_h-10",
            "Góc dưới phải":  "main_w-overlay_w-10:main_h-overlay_h-10",
            "Giữa":           "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        }

        vf_parts = []
        if flip_h:        vf_parts.append("hflip")
        if flip_v:        vf_parts.append("vflip")
        if zoom_on:
            vf_parts.append(f"scale=iw*{zoom_f:.3f}:ih*{zoom_f:.3f}")
            vf_parts.append(f"crop=iw/{zoom_f:.3f}:ih/{zoom_f:.3f}")
        if crop_on:
            vf_parts.append(f"crop=iw-{2*crop_px}:ih-{2*crop_px}:{crop_px}:{crop_px}")
        if color_preset in COLOR_PRESETS:
            vf_parts.append(COLOR_PRESETS[color_preset])
        elif bright != 0 or sat != 1.0 or contrast != 1.0:
            b_norm = bright / 100.0
            vf_parts.append(f"eq=brightness={b_norm:.2f}:saturation={sat:.2f}:contrast={contrast:.2f}")
        if noise_on:
            vf_parts.append(f"noise=alls={noise_str}:allf=t+u")
        if fps_on and fps_val not in ("Gốc", ""):
            vf_parts.append(f"fps={fps_val}")
        if res_on and res_val not in ("Gốc", ""):
            vf_parts.append(f"scale={res_val.replace('x', ':')}:flags=lanczos")
        if border_on:
            bc = border_col
            vf_parts.append(
                f"drawbox=x=0:y=0:w=iw:h={border_w_px}:color=0x{bc}:t=fill,"
                f"drawbox=x=0:y=ih-{border_w_px}:w=iw:h={border_w_px}:color=0x{bc}:t=fill,"
                f"drawbox=x=0:y=0:w={border_w_px}:h=ih:color=0x{bc}:t=fill,"
                f"drawbox=x=iw-{border_w_px}:y=0:w={border_w_px}:h=ih:color=0x{bc}:t=fill"
            )

        has_filter  = bool(vf_parts) or logo_on
        has_meta    = exif_on or (meta_on and meta_title)
        has_reenc   = gop_on or h265_on
        if not has_filter and not has_meta and not has_reenc:
            return

        tmp_out = video_path + ".tmp_cr.mp4"

        if h265_on:
            codec_v_args = ['-c:v', 'libx265', '-preset', 'fast', '-crf', '23',
                            '-pix_fmt', 'yuv420p']
        elif has_filter or gop_on:
            codec_v_args = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                            '-pix_fmt', 'yuv420p']
            if gop_on:
                codec_v_args += ['-g', '30']
        else:
            codec_v_args = ['-c:v', 'copy']

        meta_args: list = []
        if exif_on:
            meta_args += ['-map_metadata', '-1']
        if meta_on and meta_title:
            meta_args += ['-metadata', f'title={meta_title}']

        use_logo = logo_on and logo_path and os.path.isfile(logo_path)

        if use_logo:
            lw = logo_w if logo_w > 0 else 120
            lh_flag = f":{logo_h}" if logo_h > 0 else ":-1"
            scale_logo = f"scale={lw}{lh_flag}"
            overlay_pos = LOGO_POS_MAP.get(logo_pos, "main_w-overlay_w-10:10")
            base_vf = f"[0:v]{','.join(vf_parts)}[vbase];" if vf_parts else "[0:v]null[vbase];"
            logo_flt = (f"[1:v]{scale_logo},format=rgba,"
                        f"colorchannelmixer=aa={logo_op:.2f}[logo];")
            overlay_flt = f"[vbase][logo]overlay={overlay_pos}[vout]"
            fc = base_vf + logo_flt + overlay_flt
            cmd_list = (
                ['ffmpeg', '-i', video_path, '-i', logo_path,
                 '-filter_complex', fc, '-map', '[vout]', '-map', '0:a?']
                + codec_v_args + ['-c:a', 'copy'] + meta_args + ['-y', tmp_out]
            )
        elif vf_parts:
            cmd_list = (
                ['ffmpeg', '-i', video_path, '-vf', ','.join(vf_parts),
                 '-map', '0:v', '-map', '0:a?']
                + codec_v_args + ['-c:a', 'copy'] + meta_args + ['-y', tmp_out]
            )
        else:
            cmd_list = (
                ['ffmpeg', '-i', video_path, '-map', '0', '-c', 'copy']
                + meta_args + ['-y', tmp_out]
            )

        ok = self._run_cmd_list(cmd_list, "Lách bản quyền")
        if ok and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 1024:
            os.replace(tmp_out, video_path)
            sys_log.info("✅ Lách bản quyền OK")
        else:
            try:
                if os.path.exists(tmp_out): os.remove(tmp_out)
            except OSError:
                pass
            sys_log.warning("⚠️ Lách bản quyền thất bại — giữ nguyên video")

    # ── BLOCK PIPELINE (video > 30 phút) ──────────────────────
    @staticmethod
    def _probe_video_duration(video_path: str) -> float:
        """Trả về thời lượng video (giây) bằng ffprobe."""
        try:
            r = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'csv=p=0', video_path],
                capture_output=True, text=True, timeout=10,
                startupinfo=_mk_si(), creationflags=_mk_cflags()
            )
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    def _split_video_to_blocks(self, video_path: str, block_dir: str,
                                block_dur: int = BLOCK_DURATION_SEC) -> list:
        """Chia video thành block ~10 phút bằng FFmpeg stream-copy (không mất chất lượng)."""
        os.makedirs(block_dir, exist_ok=True)
        pattern = os.path.join(block_dir, "block_%04d.mp4")
        ok = self._run_cmd_list(
            ['ffmpeg', '-i', video_path, '-c', 'copy', '-map', '0',
             '-segment_time', str(block_dur), '-f', 'segment',
             '-reset_timestamps', '1', '-y', pattern],
            "Chia video thành blocks"
        )
        if not ok:
            return []
        blocks = sorted([
            os.path.join(block_dir, f) for f in os.listdir(block_dir)
            if f.startswith('block_') and f.endswith('.mp4')
        ])
        sys_log.info(f"  ✅ Chia thành {len(blocks)} blocks × {block_dur // 60} phút")
        return blocks

    @staticmethod
    def _concat_done_blocks(done_blocks: list, output_path: str) -> bool:
        """Nối blocks đã hoàn thiện bằng FFmpeg concat stream-copy (không re-encode)."""
        if not done_blocks:
            return False
        concat_lst = output_path + ".concat.txt"
        try:
            with open(concat_lst, 'w', encoding='utf-8') as f:
                for p in done_blocks:
                    # forward slash + escape single quotes for concat demuxer format
                    escaped = p.replace(chr(92), '/').replace("'", "\\'")
                    f.write(f"file '{escaped}'\n")
            r = subprocess.run(
                ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_lst,
                 '-c', 'copy', '-movflags', '+faststart', '-y', output_path],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                startupinfo=_mk_si(), creationflags=_mk_cflags()
            )
            if r.returncode != 0:
                sys_log.error(f"  Concat lỗi: {r.stderr[-300:]}")
            return r.returncode == 0
        finally:
            try:
                os.remove(concat_lst)
            except OSError:
                pass

    def _build_global_ctx_from_blocks(self, blocks: list, work_dir: str) -> str:
        """
        Whisper 2 phút đầu của 3 block mẫu (đầu/giữa/cuối) → LLM tạo Global Context.
        Load model một lần duy nhất cho cả 3 block để tránh CUDA teardown/reinit crash.
        """
        n           = len(blocks)
        sample_idx  = sorted({0, n // 2, n - 1})
        whisper_dev = "cuda" if torch.cuda.is_available() else "cpu"
        whisper_sz  = self.settings.get("whisper_model", "base")
        all_segs: list = []
        os.makedirs(work_dir, exist_ok=True)

        # Load Whisper một lần → chạy cả 3 block → unload một lần
        # Giảm CUDA teardown/reinit từ 3× xuống 1× → tránh CUDA destructor crash
        self.ai.reload_model(model_size=whisper_sz, device=whisper_dev)
        try:
            for bi in sample_idx:
                audio_tmp = os.path.join(work_dir, f"ctx_a{bi}.wav")
                srt_tmp   = os.path.join(work_dir, f"ctx_{bi}.srt")
                ok = self._run_cmd_list(
                    ['ffmpeg', '-i', blocks[bi], '-vn', '-acodec', 'pcm_s16le',
                     '-ar', '44100', '-ac', '2', '-t', '120', '-y', audio_tmp],
                    f"Context audio block {bi}"
                )
                if not ok or not os.path.exists(audio_tmp):
                    continue
                segs = self.ai.transcribe_and_get_segments(audio_tmp, srt_tmp)
                if segs:
                    offset = len(all_segs)
                    for j, s in enumerate(segs):
                        all_segs.append({**s, 'id': offset + j + 1})
                try:
                    os.remove(audio_tmp)
                except OSError:
                    pass
        finally:
            self.ai.unload_model()   # unload một lần duy nhất dù có lỗi hay không

        if not all_segs:
            return ""
        if self.settings.get('ai_platform', 'ollama') != 'ollama':
            return ""
        src = self.settings.get('source_lang', 'Chinese')
        tgt = self.settings.get('target_lang', 'Vietnamese')
        mdl = self.settings.get('default_model', 'qwen2.5:14b')
        return self.ai._extract_global_context(all_segs, src, tgt, mdl)

    def _process_single_block(
        self,
        blk_path: str, blk_temp: str, blk_done: str,
        target_lang: str, source_lang: str, ai_platform: str,
        voice_param: Optional[str], visuals_data: dict,
        global_ctx: str, blk_idx: int,
    ) -> bool:
        """Chạy đầy đủ Trạm 1 (tách/nhận dạng) → Trạm 2 (dịch/TTS/mix) → Trạm 3 (GPU render)."""

        # Trạm 1a: Tách audio
        audio_goc = os.path.join(blk_temp, "goc.wav")
        if not self._run_cmd_list(
            ['ffmpeg', '-i', blk_path, '-vn', '-acodec', 'pcm_s16le',
             '-ar', '44100', '-ac', '2', '-y', audio_goc],
            f"Tách audio block {blk_idx}"
        ) or not os.path.exists(audio_goc):
            return False

        # Trạm 1b: Demucs (subprocess riêng → không giữ VRAM)
        use_advanced = self.settings.get('use_advanced_separation', True)
        music_path = vocals_path = None
        if use_advanced:
            music_path, vocals_path = self._separate_with_demucs(audio_goc, blk_temp)

        # Trạm 1c: Whisper → giải phóng VRAM ngay
        whisper_dev   = "cuda" if torch.cuda.is_available() else "cpu"
        whisper_model = self.settings.get("whisper_model", "base")
        self.ai.reload_model(model_size=whisper_model, device=whisper_dev)
        srt_orig = os.path.join(blk_temp, "sub_orig.srt")
        segments = self.ai.transcribe_and_get_segments(audio_goc, srt_orig)
        self.ai.unload_model()

        if not segments:
            sys_log.warning(f"  ⚠️ Block {blk_idx}: không có lời thoại — bỏ qua dịch/TTS")
            # Không có sub → giữ audio gốc, render visual-only
            shutil.copy2(blk_path, blk_done)
            self._apply_visuals(blk_done, visuals_data, "")
            return os.path.exists(blk_done)

        for i, seg in enumerate(segments):
            seg['id'] = i + 1
            seg['original_text'] = seg['text']

        self._check_control()   # checkpoint sau Whisper

        # Trạm 2a: Dịch (với global_ctx từ Phase 1)
        segments, ok = self._translate_with_verification(
            segments, target_lang, source_lang, ai_platform, global_ctx
        )
        if not ok:
            return False
        srt_vi = os.path.join(blk_temp, "sub_vi.srt")
        self._save_translated_srt(segments, srt_vi)

        self._check_control()   # checkpoint sau dịch

        # Trạm 2b: TTS
        audio_goc_seg = AudioSegment.from_file(audio_goc)
        dub_canvas    = self._create_tts_with_retry(segments, audio_goc_seg, blk_temp, voice_param)
        audio_dub     = os.path.join(blk_temp, "dub_final.wav")
        dub_canvas.export(audio_dub, format="wav")

        self._check_control()   # checkpoint sau TTS

        # Trạm 2c: Mix audio + ghép video
        vol_ai   = self.settings.get('vol_ai',  120) / 100.0
        vol_bg   = self.settings.get('vol_bg',   70) / 100.0
        vol_orig = self.settings.get('vol_orig',  15) / 100.0
        blk_mixed = os.path.join(blk_temp, "mixed.mp4")

        if use_advanced and music_path and vocals_path:
            mix_cmd = [
                'ffmpeg', '-i', blk_path, '-i', music_path, '-i', vocals_path, '-i', audio_dub,
                '-filter_complex',
                f'[1:a]volume={vol_bg}[music];[2:a]volume={vol_orig}[orig_voc];'
                f'[music][orig_voc]amix=inputs=2:duration=first:normalize=0[bg];'
                f'[3:a]volume={vol_ai}[dub];'
                f'[bg][dub]amix=inputs=2:duration=first:normalize=0[final]',
                '-map', '0:v', '-map', '[final]',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-shortest', '-y', blk_mixed,
            ]
        else:
            mix_cmd = [
                'ffmpeg', '-i', blk_path, '-i', audio_goc, '-i', audio_dub,
                '-filter_complex',
                f'[1:a]volume={vol_orig}[orig];[2:a]volume={vol_ai}[dub];'
                f'[orig][dub]amix=inputs=2:duration=first:normalize=0[mix]',
                '-map', '0:v', '-map', '[mix]',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-shortest', '-y', blk_mixed,
            ]
        if not self._run_cmd_list(mix_cmd, f"Mix audio block {blk_idx}"):
            return False

        # Trạm 3: GPU Render (ASS + NVENC/AMF/libx264)
        shutil.copy2(blk_mixed, blk_done)
        self._apply_visuals(blk_done, visuals_data, srt_vi)
        return os.path.exists(blk_done) and os.path.getsize(blk_done) > 1024

    def _run_block_pipeline(self, vid_path: str, vid_idx: int):
        """
        Block Pipeline cho video dài (> BLOCK_THRESHOLD_SEC).
        Phase 0: Split (stream-copy) → Phase 1: Global Context →
        Phase 2: Assembly Line (với checkpoint kháng lỗi) → Phase 3: Grand Assembly (concat).
        """
        name_clean = re.sub(r'[^\w\s-]', '', os.path.splitext(os.path.basename(vid_path))[0]).strip()
        work_dir   = os.path.join(self.out_dir, f"blocks_{vid_idx}_{name_clean}")
        ckpt       = CheckpointManager(vid_path, self.out_dir)

        # Phase 0: Split ────────────────────────────────────────────────
        blocks_dir  = os.path.join(work_dir, "split")
        blocks_json = ckpt.get_temp_file("blocks_list")

        if blocks_json:
            blocks = [b for b in json.loads(blocks_json) if os.path.exists(b)]
            sys_log.info(f"  📂 Resume: {len(blocks)} blocks đã split")
        else:
            sys_log.info("  ↳ Phase 0: Chia video thành blocks (stream-copy)...")
            blocks = self._split_video_to_blocks(vid_path, blocks_dir)
            if not blocks:
                sys_log.error("❌ Không chia được video — bỏ qua")
                return
            ckpt.register_temp_file("blocks_list", json.dumps(blocks))

        n = len(blocks)
        sys_log.info(f"  📦 {n} blocks × {BLOCK_DURATION_SEC // 60} phút")

        # Phase 1: Global Context ───────────────────────────────────────
        ctx_path   = os.path.join(work_dir, "global_ctx.txt")
        global_ctx = ""
        if os.path.exists(ctx_path):
            with open(ctx_path, 'r', encoding='utf-8') as f:
                global_ctx = f.read().strip()
            sys_log.info("  📂 Resume: Global context đã có")
        else:
            sys_log.info("  ↳ Phase 1: Trích xuất Global Context từ 3 block mẫu...")
            os.makedirs(work_dir, exist_ok=True)
            try:
                global_ctx = self._build_global_ctx_from_blocks(blocks, work_dir)
            except Exception as e:
                sys_log.warning(f"  ⚠️ Phase 1 lỗi: {e} → bỏ qua global context, tiếp tục")
                global_ctx = ""
            if global_ctx:
                with open(ctx_path, 'w', encoding='utf-8') as f:
                    f.write(global_ctx)
                sys_log.info(f"  ✅ Global context lưu ({len(global_ctx)} chars)")
            else:
                sys_log.warning("  ⚠️ Không tạo được global context — dịch không có ngữ cảnh")

        # Phase 2: Assembly Line ────────────────────────────────────────
        target_lang  = self.settings.get('target_lang', 'Vietnamese')
        source_lang  = self.settings.get('source_lang', 'Chinese')
        ai_platform  = self.settings.get('ai_platform', 'gemini')
        voice_param  = self._get_voice_param()
        visuals_data = self._load_visuals_config()
        done_blocks: list = []

        sys_log.info(f"\n  ↳ Phase 2: Băng chuyền xử lý {n} blocks...")
        for bi, blk_path in enumerate(blocks):
            blk_name = f"block_{bi:04d}"
            blk_done = os.path.join(work_dir, f"{blk_name}_done.mp4")
            ckpt_key = f"done_{blk_name}"

            if ckpt.get_temp_file(ckpt_key) and os.path.exists(blk_done):
                sys_log.info(f"  ⏭️  [{bi+1}/{n}] {blk_name} đã xong → bỏ qua")
                done_blocks.append(blk_done)
                continue

            sys_log.info(f"\n  🔨 [{bi+1}/{n}] {blk_name}...")
            blk_temp = os.path.join(work_dir, f"{blk_name}_tmp")
            os.makedirs(blk_temp, exist_ok=True)

            ok = self._process_single_block(
                blk_path, blk_temp, blk_done,
                target_lang, source_lang, ai_platform,
                voice_param, visuals_data, global_ctx, bi
            )
            if ok:
                done_blocks.append(blk_done)
                ckpt.register_temp_file(ckpt_key, blk_done)
                shutil.rmtree(blk_temp, ignore_errors=True)
                sys_log.info(f"  ✅ [{bi+1}/{n}] {blk_name} DONE")
            else:
                sys_log.warning(f"  ⚠️ [{bi+1}/{n}] {blk_name} FAILED — tiếp tục block tiếp")

        if not done_blocks:
            sys_log.error("❌ Không có block nào thành công")
            return

        # Phase 3: Grand Assembly ───────────────────────────────────────
        sys_log.info(f"\n  ↳ Phase 3: Nối {len(done_blocks)}/{n} blocks (stream-copy)...")
        final_out = os.path.join(self.out_dir, f"DUBBED_{name_clean}.mp4")
        if not self._concat_done_blocks(done_blocks, final_out):
            sys_log.error("❌ Concat blocks thất bại")
            return

        size_mb = os.path.getsize(final_out) // (1024 * 1024) if os.path.exists(final_out) else 0
        sys_log.info(f"✅ HOÀN THÀNH: {os.path.basename(final_out)} ({size_mb} MB)")

        intro_p = visuals_data.get("intro_path", "").strip()
        outro_p = visuals_data.get("outro_path", "").strip()
        if intro_p or outro_p:
            sys_log.info("  ↳ Ghép intro/outro...")
            self._apply_intro_outro(final_out, intro_p, outro_p)
        sys_log.info("  ↳ Áp dụng lách bản quyền...")
        self._apply_copyright_bypass(final_out, visuals_data)

        ckpt.advance_stage("completed")
        ckpt.delete()
        shutil.rmtree(work_dir, ignore_errors=True)

    def _emit_video_progress(self, idx: int, name: str, status: str):
        """Gọi on_video_progress thread-safe (fire-and-forget)."""
        if self.on_video_progress:
            try:
                self.on_video_progress(idx, len(self.video_list), name, status)
            except Exception:
                pass

    # ── ENGINE CHÍNH ───────────────────────────────────────────
    def _run_engine(self):
        try:
            total = len(self.video_list)
            for idx, vid_path in enumerate(self.video_list, start=1):
                self._check_control()   # Pause/Stop trước mỗi video
                vid_path  = os.path.normpath(vid_path)
                base_name = os.path.basename(vid_path)
                sys_log.info(f"▶️  [{idx}/{total}]: {base_name}")

                self._emit_video_progress(idx, base_name, "start")
                try:
                    duration = self._probe_video_duration(vid_path)
                    if duration > BLOCK_THRESHOLD_SEC:
                        h = duration / 3600
                        sys_log.info(f"  📏 Video dài {h:.1f}h → Block Pipeline")
                        self._run_block_pipeline(vid_path, idx)
                    else:
                        self._run_single_video(vid_path, idx)
                    self._emit_video_progress(idx, base_name, "done")
                except _PipelineStopRequest:
                    self._emit_video_progress(idx, base_name, "stopped")
                    raise
                except BaseException as e:
                    import traceback as _tb
                    sys_log.error(
                        f"  ❌ Lỗi xử lý {base_name}: {type(e).__name__}: {e}\n"
                        + _tb.format_exc()
                    )
                    self._emit_video_progress(idx, base_name, "error")
                    if not isinstance(e, Exception):
                        raise  # re-raise SystemExit / KeyboardInterrupt

            sys_log.info("=" * 70)
            sys_log.info("🎉 HOÀN TẤT TOÀN BỘ QUÁ TRÌNH!")

        except _PipelineStopRequest:
            sys_log.info("⏹️  Pipeline đã dừng theo yêu cầu người dùng.")
        except BaseException as e:
            import traceback as _tb
            sys_log.error(f"PIPELINE CRASH: {type(e).__name__}: {e}\n{_tb.format_exc()}")
        finally:
            if self.on_finish:
                self.on_finish()

    def _run_single_video(self, vid_path: str, idx: int):
        """Pipeline cho video ngắn (≤ BLOCK_THRESHOLD_SEC) với CheckpointManager."""
        base_name  = os.path.basename(vid_path)
        name_clean = re.sub(r'[^\w\s-]', '', os.path.splitext(base_name)[0]).strip()
        temp_dir   = os.path.join(self.out_dir, f"temp_{idx}_{name_clean}")
        os.makedirs(temp_dir, exist_ok=True)
        ckpt       = CheckpointManager(vid_path, self.out_dir)

        # Bước 1: Tách audio gốc
        # Luôn dùng path trong temp_dir hiện tại (không dùng path lưu trong checkpoint vì
        # output dir có thể thay đổi giữa các lần chạy)
        audio_goc_path = os.path.join(temp_dir, "goc.wav")
        if not ckpt.is_stage_done("audio_extracted") or not os.path.exists(audio_goc_path):
            if ckpt.is_stage_done("audio_extracted") and not os.path.exists(audio_goc_path):
                sys_log.warning("  ⚠️ Audio gốc không còn tồn tại → tách lại từ video gốc")
            ok = self._run_cmd_list(
                ['ffmpeg', '-i', vid_path, '-vn', '-acodec', 'pcm_s16le',
                 '-ar', '44100', '-ac', '2', '-y', audio_goc_path],
                "Lỗi tách audio gốc"
            )
            if not ok or not os.path.exists(audio_goc_path):
                sys_log.error(f"❌ Không tách được audio: {base_name}")
                return
            ckpt.register_temp_file("audio_goc", audio_goc_path)
            ckpt.advance_stage("audio_extracted")
        else:
            sys_log.info("  ⏭️  Bỏ qua tách audio (checkpoint)")

        self._check_control()   # checkpoint sau tách audio

        # Bước 2: Whisper (load → run → unload VRAM)
        srt_orig = ckpt.get_temp_file("srt_orig") or os.path.join(temp_dir, "sub_orig.srt")
        if not ckpt.is_stage_done("transcribed") or not ckpt.segments:
            whisper_dev   = "cuda" if torch.cuda.is_available() else "cpu"
            whisper_model = self.settings.get("whisper_model", "base")
            self.ai.reload_model(model_size=whisper_model, device=whisper_dev)
            segments = self.ai.transcribe_and_get_segments(audio_goc_path, srt_orig)
            self.ai.unload_model()
            if not segments:
                sys_log.warning("  [!] Không phát hiện lời thoại.")
                return
            for i, seg in enumerate(segments):
                seg['id'] = i + 1
                seg['original_text'] = seg['text']
            ckpt.register_temp_file("srt_orig", srt_orig)
            ckpt.set_segments(segments)
            ckpt.advance_stage("transcribed")
        else:
            segments = ckpt.segments
            sys_log.info(f"  ⏭️  Bỏ qua Whisper ({len(segments)} đoạn từ checkpoint)")

        self._check_control()   # checkpoint sau Whisper

        # Bước 3: Dịch + Kiểm tra + Retry
        target_lang = self.settings.get('target_lang', 'Vietnamese')
        source_lang = self.settings.get('source_lang', 'Chinese')
        ai_platform = self.settings.get('ai_platform', 'gemini')

        if not ckpt.is_stage_done("translated"):
            segments, success = self._translate_with_verification(
                segments, target_lang, source_lang, ai_platform
            )
            if not success:
                sys_log.error("❌ Dịch thất bại.")
                ckpt.record_error("translation_failed")
                return
            ckpt.set_segments(segments)
            ckpt.advance_stage("translated")
        else:
            segments = ckpt.segments
            sys_log.info("  ⏭️  Bỏ qua dịch (checkpoint)")

        self._log_srt_comparison(segments, idx)
        srt_translated = os.path.join(self.out_dir, f"{name_clean}_translated.srt")
        self._save_translated_srt(segments, srt_translated)
        if self.ui_callback:
            self.ui_callback(segments)

        self._check_control()   # checkpoint sau dịch

        # Bước 4: TTS + Retry
        if not ckpt.is_stage_done("tts_done"):
            sys_log.info(f"  ↳ Tạo voice ({target_lang})...")
            if not os.path.exists(audio_goc_path):
                sys_log.warning("  ⚠️ Audio gốc mất trước bước TTS → tách lại")
                self._run_cmd_list(
                    ['ffmpeg', '-i', vid_path, '-vn', '-acodec', 'pcm_s16le',
                     '-ar', '44100', '-ac', '2', '-y', audio_goc_path],
                    "Tách lại audio gốc (TTS)"
                )
            audio_goc_seg  = AudioSegment.from_file(audio_goc_path)
            voice_param    = self._get_voice_param()
            dub_canvas     = self._create_tts_with_retry(segments, audio_goc_seg, temp_dir, voice_param)
            audio_dub_path = os.path.join(temp_dir, "dub_final.wav")
            dub_canvas.export(audio_dub_path, format="wav")
            ckpt.register_temp_file("audio_dub", audio_dub_path)
            ckpt.advance_stage("tts_done")
        else:
            audio_dub_path = os.path.join(temp_dir, "dub_final.wav")
            if not os.path.exists(audio_dub_path):
                # Stale checkpoint — dub file was deleted, re-run TTS
                sys_log.warning("  ⚠️ dub_final.wav không còn tồn tại → thực hiện lại TTS")
                if not os.path.exists(audio_goc_path):
                    self._run_cmd_list(
                        ['ffmpeg', '-i', vid_path, '-vn', '-acodec', 'pcm_s16le',
                         '-ar', '44100', '-ac', '2', '-y', audio_goc_path],
                        "Tách lại audio gốc (TTS fallback)"
                    )
                audio_goc_seg  = AudioSegment.from_file(audio_goc_path)
                voice_param    = self._get_voice_param()
                dub_canvas     = self._create_tts_with_retry(segments, audio_goc_seg, temp_dir, voice_param)
                dub_canvas.export(audio_dub_path, format="wav")
                ckpt.register_temp_file("audio_dub", audio_dub_path)
            else:
                voice_param = self._get_voice_param()
            sys_log.info("  ⏭️  Bỏ qua TTS (checkpoint)")

        self._check_control()   # checkpoint sau TTS

        # Bước 5: Demucs
        use_advanced = self.settings.get('use_advanced_separation', True)
        if use_advanced:
            music_path, vocals_path = self._separate_with_demucs(audio_goc_path, temp_dir)
        else:
            music_path = vocals_path = None
            sys_log.info("  ↳ Mix đơn giản (Demucs OFF)")

        # Bước 6: Render + mix audio
        final_out = os.path.join(self.out_dir, f"DUBBED_{name_clean}.mp4")
        vol_ai    = self.settings.get('vol_ai',  120) / 100.0
        vol_bg    = self.settings.get('vol_bg',   70) / 100.0
        vol_orig  = self.settings.get('vol_orig',  15) / 100.0
        sys_log.info(
            f"  ↳ Mix AI={vol_ai*100:.0f}% BG={vol_bg*100:.0f}% "
            f"Orig={vol_orig*100:.0f}% Demucs={'ON' if use_advanced and music_path else 'OFF'}"
        )

        if use_advanced and music_path and vocals_path:
            mix_cmd = [
                'ffmpeg', '-i', vid_path, '-i', music_path, '-i', vocals_path, '-i', audio_dub_path,
                '-filter_complex',
                f'[1:a]volume={vol_bg}[music];[2:a]volume={vol_orig}[orig_voc];'
                f'[music][orig_voc]amix=inputs=2:duration=first:normalize=0[bg];'
                f'[3:a]volume={vol_ai}[dub_vol];'
                f'[bg][dub_vol]amix=inputs=2:duration=first:normalize=0[final]',
                '-map', '0:v', '-map', '[final]',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-shortest', '-y', final_out,
            ]
        else:
            mix_cmd = [
                'ffmpeg', '-i', vid_path, '-i', audio_goc_path, '-i', audio_dub_path,
                '-filter_complex',
                f'[1:a]volume={vol_orig}[orig];[2:a]volume={vol_ai}[dub];'
                f'[orig][dub]amix=inputs=2:duration=first:normalize=0[mix]',
                '-map', '0:v', '-map', '[mix]',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-shortest', '-y', final_out,
            ]

        if self._run_cmd_list(mix_cmd, "Lỗi Render cuối"):
            size_mb = os.path.getsize(final_out) // (1024*1024) if os.path.exists(final_out) else 0
            sys_log.info(f"✅ HOÀN THÀNH: {os.path.basename(final_out)} ({size_mb} MB)")

            visuals_data = self._load_visuals_config()

            sys_log.info("  ↳ Áp dụng visuals (blur/hardsub)...")
            self._apply_visuals(final_out, visuals_data, srt_translated)

            intro_p = visuals_data.get("intro_path", "").strip()
            outro_p = visuals_data.get("outro_path", "").strip()
            if intro_p or outro_p:
                sys_log.info("  ↳ Ghép intro/outro...")
                self._apply_intro_outro(final_out, intro_p, outro_p)

            sys_log.info("  ↳ Áp dụng lách bản quyền...")
            self._apply_copyright_bypass(final_out, visuals_data)

            ckpt.advance_stage("completed")
            ckpt.delete()

        shutil.rmtree(temp_dir, ignore_errors=True)

    # ── SRT helpers ────────────────────────────────────────────
    def _save_translated_srt(self, segments, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                for i, seg in enumerate(segments, 1):
                    f.write(
                        f"{i}\n"
                        f"{self._format_time(seg['start'])} --> {self._format_time(seg['end'])}\n"
                        f"{seg['text']}\n\n"
                    )
            sys_log.info(f"💾 SRT: {os.path.basename(path)}")
        except Exception as e:
            sys_log.error(f"❌ Lỗi lưu SRT: {e}")

    def _log_srt_comparison(self, segments, video_idx):
        def _trunc(s: str, n: int) -> str:
            return s[:n - 1] + '…' if len(s) > n else s

        sys_log.info(f"\n{'='*140}")
        sys_log.info(f"📋 SO SÁNH SRT — VIDEO {video_idx}")
        sys_log.info(f"{'ID':<5} {'THỜI GIAN':<26} {'GỐC':<60} | {'ĐÃ DỊCH':<60}")
        sys_log.info("-" * 140)
        for seg in segments[:50]:
            orig  = _trunc(seg.get('original_text') or '', 60)
            trans = _trunc(seg.get('text', ''), 60)
            tstr  = f"{self._format_time(seg['start'])} → {self._format_time(seg['end'])}"
            sys_log.info(f"{seg.get('id','-'):<5} {tstr:<26} {orig:<61} | {trans:<61}")
        sys_log.info("=" * 140 + "\n")

    def _format_time(self, seconds: float) -> str:
        td = time.gmtime(seconds)
        ms = int((seconds % 1) * 1000)
        return f"{time.strftime('%H:%M:%S', td)},{ms:03d}"