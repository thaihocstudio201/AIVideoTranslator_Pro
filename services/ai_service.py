import os
import time
import requests
import google.generativeai as genai
from faster_whisper import WhisperModel
from utils.custom_logger import sys_log
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class AIService:
    def __init__(self, model_size="base"):
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def get_available_models(self, api_key):
        """Kiểm tra API và CHỈ LOAD các model Gemini 2.0 trở lên"""
        try:
            genai.configure(api_key=api_key)
            models = []
            for m in genai.list_models():
                if 'gemini-2' in m.name.lower() and 'generateContent' in m.supported_generation_methods:
                    models.append(m.name.split('/')[-1])
            return models
        except Exception as e:
            sys_log.error(f"Lỗi kiểm tra API: {e}")
            return []

    def transcribe_and_get_segments(self, audio_path, srt_path):
        """Bóc tách kịch bản gốc bằng Whisper"""
        sys_log.info("  ↳ [AI] Whisper đang bóc tách kịch bản gốc...")
        segments, info = self.model.transcribe(audio_path, beam_size=5)
        results = []
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(segments, start=1):
                start_str = self._format_time(segment.start)
                end_str = self._format_time(segment.end)
                f.write(f"{i}\n{start_str} --> {end_str}\n{segment.text.strip()}\n\n")
                results.append({"start": segment.start, "end": segment.end, "text": segment.text.strip()})
        return results

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=20),
        retry=retry_if_exception_type(Exception)
    )
    def _call_gemini_api(self, model, prompt):
        return model.generate_content(prompt)

    def translate_with_rotation(self, segments, target_lang, api_keys, preferred_model):
        """Dịch thuật bằng Gemini (Online) với cơ chế xoay vòng Key"""
        if not api_keys: return segments, False
        current_api_index = 0
        
        while current_api_index < len(api_keys):
            active_key = api_keys[current_api_index].strip()
            if not active_key: 
                current_api_index += 1
                continue
                
            sys_log.info(f"  ↳ [AI] Đang dùng API Key #{current_api_index + 1} (Model: {preferred_model})...")
            try:
                genai.configure(api_key=active_key)
                model = genai.GenerativeModel(preferred_model)
                full_text = "\n".join([f"{i}|{s['text']}" for i, s in enumerate(segments)])
                prompt = f"Dịch các câu sau sang {target_lang}. Giữ định dạng ID|Văn bản:\n{full_text}"
                
                response = self._call_gemini_api(model, prompt)
                translated_lines = response.text.strip().split('\n')
                
                for line in translated_lines:
                    if '|' in line:
                        try:
                            idx, txt = line.split('|', 1)
                            segments[int(idx)]['text'] = txt.strip()
                        except: continue
                return segments, True
            except Exception as e:
                if "429" in str(e) or "Quota" in str(e):
                    sys_log.warning(f"  [!] API Key #{current_api_index + 1} HẾT TOKEN. Đang chuyển sang Key tiếp theo...")
                    current_api_index += 1
                else:
                    sys_log.error(f"  [!] Lỗi API: {e}")
                    break
        return segments, False

    def translate_with_ollama(self, segments, target_lang, model_name="translategema:12b"):
        """Dịch thuật bằng Ollama Local - Prompt tối ưu & bao quát nhiều thể loại"""
        sys_log.info(f"  ↳ [AI] Đang dịch bằng Ollama Local (Model: {model_name})...")
        if not segments: 
            return segments, False
        
        full_text = "\n".join([f"{i}|{s['text']}" for i, s in enumerate(segments)])

        prompt = f"""Bạn là chuyên gia dịch phụ đề Trung-Việt chuyên nghiệp, am hiểu sâu slang, meme, hài hước, và ngữ cảnh phim ảnh Trung Quốc ở **mọi thể loại** (hài hước, troll, meme, drama, cổ trang, hiện đại, hoạt hình, tài liệu...).

**Quy tắc dịch quan trọng:**
- Xác định rõ thể loại và bối cảnh nội dung để dịch đúng phong cách và ý nghĩa.
- Dịch **tự nhiên, mượt mà**, như người Việt bản xứ nói chuyện.
- Giữ nguyên ý nghĩa gốc, cảm xúc, tone (hài hước, troll, mỉa mai, nghiêm túc, cảm xúc...).
- Với slang, meme, cách nói troll: Dịch sát ý, giữ được sự hài hước và ý đồ gốc.
- Sử dụng từ ngữ Hán Việt hợp lý khi cần, nhưng ưu tiên tiếng Việt tự nhiên và dễ hiểu.
- Giữ đúng số lượng đoạn, đúng thứ tự ID, không gộp hay tách đoạn.
- Giữ nguyên mốc thời gian, chỉ dịch phần nội dung.

**Nội dung cần dịch:**

{full_text}

Hãy dịch sang tiếng Việt, trả về **đúng định dạng**:
ID|Nội dung đã dịch

Không thêm bất kỳ giải thích, chú thích hay dòng thừa nào.
"""

        try:
            payload = {
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.65,
                    "top_p": 0.9,
                    "num_ctx": 8192
                }
            }
            
            response = requests.post("http://localhost:11434/api/generate", json=payload, timeout=300)
            
            if response.status_code == 200:
                result_text = response.json().get("response", "")
                translated_lines = result_text.strip().split('\n')
                
                for line in translated_lines:
                    if '|' in line:
                        try:
                            idx, txt = line.split('|', 1)
                            segments[int(idx)]['text'] = txt.strip()
                        except: 
                            continue
                return segments, True
            else:
                sys_log.error(f"  [!] Ollama báo lỗi: {response.text}")
                return segments, False
                
        except requests.exceptions.ConnectionError:
            sys_log.error("  [!] Không thể kết nối Ollama. Hãy chạy 'ollama serve' trước!")
            return segments, False
        except Exception as e:
            sys_log.error(f"  [!] Lỗi xử lý Ollama Local: {e}")
            return segments, False

    def _format_time(self, seconds):
        td = time.gmtime(seconds)
        ms = int((seconds % 1) * 1000)
        return f"{time.strftime('%H:%M:%S', td)},{ms:03d}"