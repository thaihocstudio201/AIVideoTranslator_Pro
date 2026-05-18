#!/usr/bin/env python3
"""
core/whisper_worker.py
Standalone Whisper worker — gọi bởi subprocess.Popen từ master_pipeline.
Tránh hoàn toàn multiprocessing.Queue / Qt lock inheritance.

Usage:
    python whisper_worker.py <audio_path> <srt_path> <model_size> <device>
                             <result_json> [language_code]
Exit code: 0 = ok, 1 = transcription error (result JSON still written)
"""

import sys
import os
import json
import traceback

# Ensure project root is importable
_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main():
    if len(sys.argv) < 6:
        print("Usage: whisper_worker.py audio srt model_size device result_json [lang]",
              file=sys.stderr)
        sys.exit(2)

    audio_path  = sys.argv[1]
    srt_path    = sys.argv[2]
    model_size  = sys.argv[3]
    device      = sys.argv[4]
    result_json = sys.argv[5]
    language    = sys.argv[6] if len(sys.argv) > 6 else None

    result: dict = {"status": "error", "segments": [], "error": ""}

    try:
        from services.ai_service import AIService
        _ai = AIService(model_size=model_size, device=device)
        segs = _ai.transcribe_and_get_segments(audio_path, srt_path, language=language)
        result = {"status": "ok", "segments": segs or []}
    except Exception as exc:
        result = {
            "status": "error",
            "segments": [],
            "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        }

    try:
        with open(result_json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False)
    except Exception as write_exc:
        print(f"[whisper_worker] Cannot write result: {write_exc}", file=sys.stderr)
        sys.exit(3)

    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
