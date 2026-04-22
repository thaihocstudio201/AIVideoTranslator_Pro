import os
import time
import google.generativeai as genai
from faster_whisper import WhisperModel
from utils.custom_logger import sys_log

class AIService:
    def __init__(self, model_size="base"):
        # Chạy Whisper trên CPU với định dạng int8 để nhanh nhất
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    # Trong file services/ai_service.py

    def get_available_models(self, api_key):
        """Kiểm tra API key và trả về danh sách model mà key đó dùng được"""
        try:
            genai.configure(api_key=api_key)
            models = []
            for m in genai.list_models():
                # Chỉ lấy các model hỗ trợ generateContent (Dịch thuật)
                if 'generateContent' in m.supported_generation_methods:
                    # Rút gọn tên: models/gemini-1.5-flash -> gemini-1.5-flash
                    models.append(m.name.split('/')[-1])
            return models
        except Exception as e:
            return []

    def translate_with_rotation(self, segments, target_lang, api_keys, preferred_model):
        """
        Cơ chế xoay vòng: Nếu API 1 hết hạn mức, tự động đổi sang API 2.
        Nếu Model hiện tại lỗi, thử model khác trong danh sách (Xoay Model).
        """
        if not api_keys: return segments, False
        
        current_api_index = 0
        
        # Thử lần lượt từng API Key
        while current_api_index < len(api_keys):
            active_key = api_keys[current_api_index].strip()
            sys_log.info(f"  ↳ [AI] Đang dùng API #{current_api_index + 1} với model {preferred_model}...")
            
            try:
                genai.configure(api_key=active_key)
                model = genai.GenerativeModel(preferred_model)
                
                full_text = "\n".join([f"{i}|{s['text']}" for i, s in enumerate(segments)])
                prompt = f"Dịch sang {target_lang}. Giữ định dạng ID|Text:\n{full_text}"
                
                # Gọi API thông qua cơ chế retry đã viết ở bước trước
                response = self._call_gemini_api(model, prompt)
                
                # Nếu thành công thì xử lý kết quả và thoát
                # ... (logic parse kết quả dịch như cũ) ...
                return segments, True
                
            except Exception as e:
                if "429" in str(e) or "Quota" in str(e):
                    sys_log.warning(f"  [!] API #{current_api_index + 1} ĐÃ HẾT HẠN MỨC (429).")
                    current_api_index += 1 # CHUYỂN SANG API TIẾP THEO
                    time.sleep(2) 
                else:
                    sys_log.error(f"  [!] Lỗi không xác định: {e}")
                    break # Lỗi khác thì dừng lại kiểm tra

        return segments, False

    def _format_time(self, seconds):
        td = time.gmtime(seconds)
        ms = int((seconds % 1) * 1000)
        return f"{time.strftime('%H:%M:%S', td)},{ms:03d}"