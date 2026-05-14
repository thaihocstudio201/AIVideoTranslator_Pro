"""
services/ai_service.py
Hỗ trợ đa nền tảng: Gemini, OpenAI, Groq, DeepSeek, OpenRouter, Ollama.
"""
import os
import re
import time
import requests
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed
from faster_whisper import WhisperModel
from utils.custom_logger import sys_log
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ── Endpoint gốc cho các nền tảng OpenAI-compatible ──────────────────────────
PLATFORM_BASE_URLS: dict[str, str] = {
    "openai":     "https://api.openai.com/v1",
    "groq":       "https://api.groq.com/openai/v1",
    "deepseek":   "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# Models mặc định gợi ý cho từng nền tảng
PLATFORM_DEFAULTS: dict[str, str] = {
    "gemini":     "gemini-2.0-flash",
    "openai":     "gpt-4o-mini",
    "groq":       "llama-3.3-70b-versatile",
    "deepseek":   "deepseek-chat",
    "openrouter": "google/gemini-flash-1.5",
    "ollama":     "qwen2.5:14b",
}

# Models DeepSeek cố định (không có list API)
DEEPSEEK_MODELS = ["deepseek-chat", "deepseek-reasoner"]

# Models Groq phổ biến cho dịch thuật
GROQ_TRANSLATION_PREFERRED = {
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
}


class AIService:
    def __init__(self, model_size: str = "base", device: str = "cpu"):
        compute_type = "float16" if device == "cuda" else "int8"
        sys_log.info(f"🔄 Whisper [{model_size}] trên {device.upper()} ({compute_type})")
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
            sys_log.info("✅ Whisper load thành công")
        except Exception as e:
            sys_log.warning(f"⚠️ Không load Whisper trên {device}: {e} → thử CPU")
            self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    # ── Model listing ─────────────────────────────────────────────────────────

    def get_gemini_models(self, api_key: str) -> list[str]:
        """Lấy tất cả Gemini models hỗ trợ generateContent (không lọc version)."""
        try:
            genai.configure(api_key=api_key)
            skip_kw = ("embedding", "aqa", "gemini-1.0")
            models = []
            for m in genai.list_models():
                if "generateContent" not in m.supported_generation_methods:
                    continue
                name = m.name.split("/")[-1]
                if any(k in name for k in skip_kw):
                    continue
                models.append(name)
            return sorted(models, reverse=True)
        except Exception as e:
            sys_log.error(f"Lỗi kiểm tra Gemini API: {e}")
            return []

    # backward compat alias
    def get_available_models(self, api_key: str) -> list[str]:
        return self.get_gemini_models(api_key)

    def get_openai_compat_models(self, platform: str, api_key: str) -> list[str]:
        """Lấy danh sách models từ endpoint OpenAI-compatible."""
        if platform == "deepseek":
            return list(DEEPSEEK_MODELS)

        base_url = PLATFORM_BASE_URLS.get(platform, "")
        if not base_url or not api_key.strip():
            return []
        try:
            resp = requests.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key.strip()}"},
                timeout=15,
            )
            if resp.status_code != 200:
                sys_log.error(f"[{platform.upper()}] /models HTTP {resp.status_code}")
                return []

            data = resp.json().get("data", [])
            ids: list[str] = [m["id"] for m in data]

            if platform == "openai":
                kw = ("gpt-4", "gpt-3.5", "o1", "o3", "o4")
                return sorted([m for m in ids if any(m.startswith(k) for k in kw)])
            if platform == "groq":
                preferred = [m for m in ids if m in GROQ_TRANSLATION_PREFERRED]
                others    = [m for m in ids if m not in GROQ_TRANSLATION_PREFERRED]
                return preferred + sorted(others)
            if platform == "openrouter":
                kw = ("gemini", "gpt-4", "claude", "llama-3", "qwen", "deepseek", "mistral")
                filtered = [m for m in ids if any(k in m.lower() for k in kw)]
                return sorted(filtered)[:40]
            return sorted(ids)
        except Exception as e:
            sys_log.error(f"Lỗi load models {platform}: {e}")
            return []

    def get_ollama_models(self) -> list[str]:
        """Lấy danh sách models đã cài trên Ollama local."""
        try:
            resp = requests.get("http://localhost:11434/api/tags", timeout=5)
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []

    # ── Whisper transcription ─────────────────────────────────────────────────

    def transcribe_and_get_segments(self, audio_path: str, srt_path: str) -> list:
        if self.model is None:
            sys_log.error("❌ Whisper model chưa được nạp — gọi reload_model() trước")
            return []
        sys_log.info("  ↳ [Whisper] Bóc tách kịch bản gốc...")
        try:
            segments_iter, info = self.model.transcribe(audio_path, beam_size=5)
            sys_log.info(f"  ↳ Ngôn ngữ: {info.language} ({info.language_probability:.0%})")
            results = []
            with open(srt_path, "w", encoding="utf-8") as f:
                for i, seg in enumerate(segments_iter, start=1):
                    s = self._format_time(seg.start)
                    e = self._format_time(seg.end)
                    t = seg.text.strip()
                    f.write(f"{i}\n{s} --> {e}\n{t}\n\n")
                    results.append({"id": i, "start": seg.start, "end": seg.end, "text": t})
            sys_log.info(f"  ↳ [Whisper] {len(results)} đoạn thoại")
            return results
        except Exception as e:
            sys_log.error(f"❌ Whisper lỗi: {e}")
            return []

    # ── Gemini translation (xoay vòng key) ───────────────────────────────────

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=5, max=30),
        retry=retry_if_exception_type(Exception),
    )
    def _call_gemini_api(self, model, prompt: str):
        return model.generate_content(prompt)

    def translate_with_rotation(self, segments: list, target_lang: str,
                                api_keys: list, preferred_model: str,
                                source_lang: str = "") -> tuple:
        """Dịch bằng Gemini với xoay vòng API key."""
        if not api_keys:
            sys_log.error("❌ Không có Gemini API key")
            return segments, False

        sys_prompt, user_prompt = self._build_prompt(segments, target_lang, source_lang)
        for idx, key in enumerate(api_keys, 1):
            key = key.strip()
            if not key:
                continue
            sys_log.info(f"  ↳ [Gemini] Key #{idx} | {preferred_model}")
            try:
                genai.configure(api_key=key)
                mdl = genai.GenerativeModel(preferred_model)
                resp = self._call_gemini_api(mdl, f"{sys_prompt}\n\n{user_prompt}")
                self._parse_translation(resp.text, segments)
                sys_log.info(f"  ✅ Dịch thành công Key #{idx}")
                return segments, True
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
                    sys_log.warning(f"  [!] Key #{idx} hết quota → thử tiếp")
                else:
                    sys_log.error(f"  [!] Gemini Key #{idx}: {e}")
                    break
        return segments, False

    # ── OpenAI-compatible translation (OpenAI / Groq / DeepSeek / OpenRouter) ─

    def translate_with_openai_compat(self, segments: list, target_lang: str,
                                     api_keys: list, model: str,
                                     platform: str, source_lang: str = "") -> tuple:
        """
        Dịch qua OpenAI-compatible API.
        Hỗ trợ xoay vòng nhiều key, tự retry khi rate-limit.
        """
        base_url = PLATFORM_BASE_URLS.get(platform)
        if not base_url:
            sys_log.error(f"Platform không hỗ trợ: {platform}")
            return segments, False
        if not api_keys:
            sys_log.error(f"Không có {platform} API key")
            return segments, False

        sys_prompt, user_msg = self._build_prompt(segments, target_lang, source_lang)

        for idx, key in enumerate(api_keys, 1):
            key = key.strip()
            if not key:
                continue
            sys_log.info(f"  ↳ [{platform.upper()}] Key #{idx} | {model}")
            try:
                headers: dict = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type":  "application/json",
                }
                if platform == "openrouter":
                    headers["HTTP-Referer"] = "https://aivideotranslator.local"
                    headers["X-Title"] = "AIVideoTranslator Pro"

                payload = {
                    "model":    model,
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user",   "content": user_msg},
                    ],
                    "temperature": 0.5,
                    "max_tokens":  4096,
                }
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers=headers, json=payload, timeout=120,
                )
                if resp.status_code == 200:
                    result = resp.json()["choices"][0]["message"]["content"]
                    self._parse_translation(result, segments)
                    sys_log.info(f"  ✅ [{platform.upper()}] dịch thành công")
                    return segments, True
                if resp.status_code in (429, 503):
                    sys_log.warning(f"  [!] {platform} Key #{idx} rate-limit → thử tiếp")
                else:
                    sys_log.error(f"  [!] {platform} Key #{idx} HTTP {resp.status_code}: {resp.text[:200]}")
                    break
            except Exception as e:
                sys_log.error(f"  [!] {platform} Key #{idx} lỗi: {e}")
        return segments, False

    # ── Ollama local ──────────────────────────────────────────────────────────

    # ── Ollama MAP-REDUCE config ──────────────────────────────────────────────
    _OLLAMA_CHUNK_SIZE    = 20   # dòng/chunk
    _OLLAMA_CHUNK_RETRIES = 3    # retry mỗi chunk nếu validation fail
    _OLLAMA_WORKERS       = 2    # luồng song song (khớp OLLAMA_NUM_PARALLEL)
    _OLLAMA_SAMPLE_SIZE   = 20   # dòng lấy mỗi vùng (đầu/giữa/cuối) khi sampling
    # num_ctx đủ cho system (~900t) + global_ctx (~200t) + input (~700t) + output (~700t)
    _OLLAMA_NUM_CTX       = 4096
    # Chỉ giữ dòng khớp pattern "số|text", loại bỏ AI preamble/postamble
    _RE_TRANS_LINE        = re.compile(r'^\d+\s*\|')

    # ── STAGE 2: MAP — Trích xuất Global Context ──────────────────────────────

    def _sample_for_context(self, segments: list) -> list:
        """Lấy mẫu thông minh: toàn bộ nếu ≤50, hoặc đầu/giữa/cuối nếu dài."""
        n = len(segments)
        if n <= 50:
            return segments
        sz = self._OLLAMA_SAMPLE_SIZE
        mid_start = max(sz, (n // 2) - sz // 2)
        head = segments[:sz]
        mid  = segments[mid_start:mid_start + sz]
        tail = segments[max(n - sz, mid_start + sz):]
        seen, result = set(), []
        for s in head + mid + tail:
            if s["id"] not in seen:
                seen.add(s["id"])
                result.append(s)
        return result

    def _extract_global_context(self, segments: list, source_lang: str,
                                 target_lang: str, model_name: str) -> str:
        """
        STAGE 2 (MAP): Gửi mẫu lên LLM để nhận diện thể loại, nhân vật,
        quy tắc xưng hô. Kết quả là 'Sổ tay quy tắc' bơm vào mọi chunk dịch.
        """
        sample = self._sample_for_context(segments)
        lines  = "\n".join(f"{s['id']}|{s['text']}" for s in sample)
        sys_log.info(f"  ↳ [MAP] Phân tích {len(sample)} mẫu câu...")

        system = (
            "Bạn là đạo diễn phim phân tích kịch bản. "
            "Trả lời NGẮN GỌN theo ĐÚNG định dạng yêu cầu. KHÔNG giải thích."
        )
        user = (
            f"Đọc đoạn thoại {source_lang} sau và lập hồ sơ để hỗ trợ dịch sang {target_lang}.\n\n"
            f"{lines}\n\n"
            "Trả về ĐÚNG 3 dòng:\n"
            "THỂ LOẠI: [phim hành động / tình cảm / hài / kinh dị / vlog / show...]\n"
            "NHÂN VẬT: [Tên & vai trò chính, VD: A - thủ lĩnh; B - học sinh]\n"
            "XƯNG HÔ & GIỌNG: [VD: anh/em ngọt ngào | mày/tao gắt | tôi/bạn lịch sự]"
        )
        try:
            resp = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.1, "top_p": 0.9, "num_ctx": 4096},
                },
                timeout=(15, 120),
            )
            if resp.status_code == 200:
                ctx = resp.json().get("message", {}).get("content", "").strip()
                sys_log.info(f"  ✅ Global context:\n{ctx}")
                return ctx
            sys_log.warning(f"  ⚠️ MAP HTTP {resp.status_code} → dịch không có global context")
        except Exception as e:
            sys_log.warning(f"  ⚠️ MAP lỗi ({e}) → tiếp tục không có global context")
        return ""

    # ── STAGE 3: REDUCE — Multi-threaded Self-Healing Translation ─────────────

    def unload_model(self):
        """Giải phóng Whisper model khỏi VRAM/RAM ngay sau khi dùng xong."""
        if self.model is not None:
            import gc
            del self.model
            self.model = None
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
            gc.collect()
            sys_log.info("  🗑️ Whisper: đã giải phóng VRAM")

    def reload_model(self, model_size: str = "base", device: str = "cpu"):
        """Nạp lại Whisper sau khi unload (dùng trong block pipeline)."""
        if self.model is not None:
            return
        compute_type = "float16" if device == "cuda" else "int8"
        sys_log.info(f"  🔄 Whisper reload [{model_size}] {device.upper()}...")
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
            sys_log.info(f"  ✅ Whisper [{model_size}] sẵn sàng")
        except Exception as e:
            sys_log.warning(f"  ⚠️ Whisper reload fallback CPU: {e}")
            self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def translate_with_ollama(self, segments: list, target_lang: str,
                              model_name: str = "qwen2.5:14b",
                              source_lang: str = "",
                              global_ctx: str = "") -> tuple:
        total = len(segments)
        sys_log.info(f"  ↳ [Ollama] {model_name} | {total} đoạn")
        if not segments:
            return segments, False

        # Stage 2 — MAP: trích xuất global context (bỏ qua nếu đã được cung cấp từ bên ngoài)
        if not global_ctx and total > 5:
            global_ctx = self._extract_global_context(
                segments, source_lang, target_lang, model_name
            )

        # Build system prompt một lần, dùng chung cho tất cả worker
        system_prompt, _ = self._build_prompt(segments[:1], target_lang, source_lang)

        # Stage 3 — REDUCE: chia chunk + đa luồng
        chunk_size = self._OLLAMA_CHUNK_SIZE
        chunks     = [segments[i:i + chunk_size] for i in range(0, total, chunk_size)]
        n_chunks   = len(chunks)
        workers    = min(self._OLLAMA_WORKERS, n_chunks)
        sys_log.info(f"  ↳ [REDUCE] {n_chunks} chunks | {workers} workers song song")

        errors = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(
                    self._worker_translate_chunk,
                    chunk, system_prompt, global_ctx, target_lang, model_name,
                    f"Chunk {i + 1}/{n_chunks}", source_lang
                ): i
                for i, chunk in enumerate(chunks)
            }
            for future in as_completed(future_map):
                try:
                    if not future.result():
                        errors += 1
                except requests.exceptions.ConnectionError:
                    sys_log.error("  [!] Ollama offline — dừng toàn bộ!")
                    pool.shutdown(wait=False, cancel_futures=True)
                    return segments, False
                except Exception as e:
                    sys_log.error(f"  [!] Worker exception: {e}")
                    errors += 1

        status = "✅" if errors == 0 else f"⚠️ ({errors}/{n_chunks} chunk lỗi)"
        sys_log.info(f"  {status} Ollama dịch xong {total} đoạn")
        return segments, errors == 0

    def _worker_translate_chunk(self, chunk: list, system_prompt: str,
                                 global_ctx: str, target_lang: str,
                                 model_name: str, label: str,
                                 source_lang: str = "") -> bool:
        """
        STAGE 3 worker: Sandwich Prompt + 3-checkpoint validation + self-healing.
        Thread-safe: mỗi chunk thao tác trên tập segment ID riêng biệt.
        Fallback về text gốc nếu hết retry → đảm bảo timeline SRT không bị mất.
        """
        expected = len(chunk)
        min_ok   = max(1, expected - 1)   # cho phép thiếu ≤1 dòng

        for attempt in range(1, self._OLLAMA_CHUNK_RETRIES + 1):
            # Mỗi retry tăng thêm num_ctx để tránh truncate
            num_ctx     = self._OLLAMA_NUM_CTX + (attempt - 1) * 1024
            user_prompt = self._build_sandwich_prompt(chunk, target_lang, global_ctx, source_lang)
            sys_log.info(f"    → {label} ({expected} đoạn) attempt={attempt} num_ctx={num_ctx}")

            try:
                resp = requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user",   "content": user_prompt},
                        ],
                        "stream": False,
                        "options": {
                            "temperature": 0.4,
                            "top_p": 0.85,
                            "num_ctx": num_ctx,
                        },
                    },
                    timeout=(15, 360),
                )
            except requests.exceptions.ConnectionError:
                raise   # propagate — caller sẽ shutdown pool
            except requests.exceptions.Timeout:
                sys_log.warning(f"  ⏱ {label} timeout attempt={attempt}")
                continue
            except Exception as e:
                sys_log.error(f"  [!] {label} request lỗi: {e}")
                if attempt == self._OLLAMA_CHUNK_RETRIES:
                    return False
                continue

            if resp.status_code != 200:
                sys_log.error(f"  [!] Ollama HTTP {resp.status_code}: {resp.text[:200]}")
                if attempt == self._OLLAMA_CHUNK_RETRIES:
                    return False
                continue

            raw_text = resp.json().get("message", {}).get("content", "")

            # ── Checkpoint 3: loại bỏ noise (AI preamble/postamble) ──────────
            clean_text = self._strip_noise(raw_text)

            # ── Checkpoint 1+2: định dạng & toàn vẹn ID ──────────────────────
            parsed = self._parse_translation(clean_text, chunk)

            if parsed >= min_ok:
                if parsed < expected:
                    missing = expected - parsed
                    sys_log.warning(f"  ⚠️ {label}: thiếu {missing} đoạn (chấp nhận được)")
                return True

            sys_log.warning(
                f"  ⚠️ {label} attempt={attempt}: parse {parsed}/{expected} đoạn "
                f"→ retry num_ctx={num_ctx + 1024}"
            )

        # Hết retry — fallback: giữ nguyên text gốc (không làm hỏng timeline)
        sys_log.error(
            f"  [!] {label}: thất bại sau {self._OLLAMA_CHUNK_RETRIES} lần "
            "→ giữ nguyên text gốc"
        )
        return False

    def _build_sandwich_prompt(self, chunk: list, target_lang: str,
                                global_ctx: str, source_lang: str = "") -> str:
        """
        Sandwich Prompt (3 lớp):
          Lớp 1 (Sổ tay ngữ cảnh): Global context từ Stage 2 MAP
          Lớp 2 (Quy tắc bản địa): Nhắc lại quy tắc cốt lõi cho chunk này
          Lớp 3 (Dữ liệu):         Các dòng SRT cần dịch
        """
        is_zh_vi = (
            any(k in source_lang.lower() for k in ("chinese", "zh", "mandarin"))
            and any(k in target_lang.lower() for k in ("vietnamese", "vi", "viet"))
        )

        parts = []

        # Lớp 1: Global context
        if global_ctx:
            parts.append(
                f"[SỔ TAY NGỮ CẢNH — áp dụng nhất quán]\n{global_ctx}\n"
            )

        # Lớp 2: Quy tắc cốt lõi (luôn có, đặc biệt với Zh→Vi)
        if is_zh_vi:
            parts.append(
                "[QUY TẮC DỊCH TRUNG→VIỆT]\n"
                "1. Output PHẢI hoàn toàn tiếng Việt — KHÔNG để lại ký tự Hán nào.\n"
                "2. Đại từ linh hoạt: đánh nhau→tao/mày, tình cảm→anh/em, trang trọng→tôi.\n"
                "3. Thành ngữ 4 chữ: dịch theo NGHĨA & CẢM XÚC, không dịch mặt chữ.\n"
                "4. Trợ từ (啊/呢/嘛/吧): lược bỏ hoặc đổi sang từ Việt (à/nhỉ/vậy/chứ).\n"
                "5. Thán từ mạnh (卧槽/妈的): dùng tương đương Việt mạnh (vãi/mẹ kiếp/đéo).\n"
                "6. Slang mạng TQ: tìm từ giới trẻ Việt tương đương, không dịch thẳng.\n"
                "7. TUYỆT ĐỐI không dịch máy móc — đọc ngữ cảnh trước khi dịch.\n"
            )
        else:
            parts.append(
                f"[QUY TẮC DỊCH sang {target_lang}]\n"
                "Dịch tự nhiên như người bản ngữ. KHÔNG dịch từng chữ. "
                "Giữ cảm xúc, ngữ điệu và văn phong phù hợp ngữ cảnh.\n"
            )

        # Lớp 3: Dữ liệu
        data_lines = "\n".join(f"{s['id']}|{s['text']}" for s in chunk)
        parts.append(
            f"Dịch sang {target_lang}. Giữ nguyên ID. Chỉ trả về kết quả dạng ID|nội dung.\n\n"
            f"{data_lines}"
        )
        return "\n\n".join(parts)

    def _strip_noise(self, text: str) -> str:
        """Loại bỏ dòng không phải ID|text (AI commentary, preamble, postamble)."""
        clean = []
        for line in text.strip().splitlines():
            stripped = line.strip()
            if stripped and self._RE_TRANS_LINE.match(stripped):
                clean.append(stripped)
        return "\n".join(clean)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_prompt(self, segments: list, target_lang: str,
                      source_lang: str = "") -> tuple:
        """
        Trả về (system_prompt, user_prompt) để tối ưu cho các Instruct Models.
        System = vai trò + quy tắc tư duy.
        User   = dữ liệu thô + yêu cầu định dạng.
        """
        lines = "\n".join(f"{s['id']}|{s['text']}" for s in segments)
        is_zh_vi = (
            any(k in source_lang.lower() for k in ("chinese", "zh", "mandarin", "cantonese"))
            and any(k in target_lang.lower() for k in ("vietnamese", "vi", "viet"))
        )

        system_prompt = (
            f"Bạn là chuyên gia 'Bản địa hóa' (Localization) phụ đề phim xuất sắc từ "
            f"{source_lang or 'ngôn ngữ gốc'} sang {target_lang}. "
            "Nhiệm vụ của bạn KHÔNG phải dịch từng chữ mà là truyền đạt ý nghĩa, cảm xúc "
            "và văn phong sao cho người bản ngữ nghe TỰ NHIÊN NHẤT.\n\n"
            "QUY TẮC BẮT BUỘC:\n"
            "- Đọc hiểu toàn bộ ngữ cảnh trước khi dịch từng câu.\n"
            "- Dịch tự nhiên như người bản ngữ — dùng từ lóng, thành ngữ, cách nói hàng ngày "
            "phù hợp ngữ cảnh. KHÔNG dịch máy móc.\n"
            "- Giữ ĐÚNG số lượng đoạn và ID — KHÔNG gộp, KHÔNG tách, KHÔNG bỏ sót.\n"
            "- Định dạng output bắt buộc: ID|Nội dung đã dịch\n"
            "- KHÔNG thêm bình luận, chú thích, hay bất kỳ nội dung nào ngoài định dạng trên."
        )

        if is_zh_vi:
            system_prompt += (
                "\n\nLƯU Ý ĐẶC BIỆT KHI DỊCH TRUNG → VIỆT:\n"
                "- Output PHẢI hoàn toàn bằng tiếng Việt. KHÔNG để lại BẤT KỲ ký tự Hán nào "
                "(kể cả dấu câu fullwidth ，。！？：；). Nếu không chắc nghĩa → dịch thoáng, "
                "KHÔNG để nguyên chữ Hán.\n"
                "- Đại từ nhân xưng: LINH HOẠT theo sắc thái cảm xúc — đánh nhau/căng thẳng "
                "→ tao/mày; tình cảm/thân thiết → anh/em/bé/cưng; trang trọng → tôi/ông/bà. "
                "KHÔNG bám vào từ gốc 我/你/他.\n"
                "- Thành ngữ 4 chữ (成语): dịch theo NGHĨA & CẢM XÚC, KHÔNG dịch mặt chữ. "
                "VD: 马到成功→thành công rực rỡ, 一石二鸟→một công đôi việc, "
                "心有余悸→tim còn đập loạn, 如虎添翼→mạnh như hổ thêm cánh.\n"
                "- Tên riêng: giữ phiên âm quen thuộc (Lý Tiểu Long, Hàng Châu). "
                "Tên ít biết → đọc âm Hán-Việt hoặc giữ nguyên, KHÔNG tự ý tạo tên mới.\n"
                "- Trợ từ cảm thán (啊/呢/嘛/吧/哦/喂/哎): lược bỏ hoặc thay bằng "
                "từ Việt tương đương (nhỉ/à/vậy/chứ/ừ/ê/ôi).\n"
                "- Thán từ mạnh (卧槽/我操/我靠/妈的/他妈): dùng tương đương Việt mạnh "
                "theo ngữ cảnh (vãi/đéo/mẹ kiếp/éo/chết tiệt).\n"
                "- Slang mạng TQ (绝了/牛/笑死/裂开/离谱/服了/躺平/内卷): tìm tương đương "
                "giới trẻ Việt hiện đại (đỉnh/chill/cảnh bà/troll/xịn xò/chấm/thả thính).\n"
                "- Thoại hành động/võ thuật: dùng ngôn ngữ khí thế mạnh, không dịch nhạt.\n"
                "- Hài hước/mỉa mai: GIỮ NGUYÊN tông, dùng từ Việt có 'vị' tương đương.\n"
                "- Giữ tối đa 2 dòng/đoạn, không tự xuống dòng thêm."
            )

        user_prompt = (
            f"Hãy dịch toàn bộ các đoạn thoại sau sang {target_lang}. "
            "Giữ nguyên ID ở đầu mỗi dòng.\n\n"
            f"{lines}"
        )

        return system_prompt, user_prompt

    def _parse_translation(self, response_text: str, segments: list) -> int:
        """Parse kết quả dịch, trả về số đoạn được cập nhật thành công."""
        id_map  = {seg["id"]: i for i, seg in enumerate(segments)}
        updated = 0
        for line in response_text.strip().split("\n"):
            line = line.strip()
            if "|" not in line:
                continue
            try:
                raw_id, txt = line.split("|", 1)
                seg_id = int(raw_id.strip())
                if seg_id in id_map:
                    segments[id_map[seg_id]]["text"] = txt.strip()
                    updated += 1
            except (ValueError, KeyError):
                continue
        return updated

    def _format_time(self, seconds: float) -> str:
        td = time.gmtime(seconds)
        ms = int((seconds % 1) * 1000)
        return f"{time.strftime('%H:%M:%S', td)},{ms:03d}"
