"""
test_voice_service.py - Dat o thu muc goc D:/AIVideoTranslator_Pro/
"""
import os, sys, time, torch

project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

from services.voice_service import VoiceService

SAMPLE_WAV = os.path.join(project_root, "sample.wav")
OUTPUT_DIR = os.path.join(project_root, "test_outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TEXT_SHORT  = "Xin chao, toi la tro ly giong noi AI cua he thong."
TEXT_MEDIUM = ("He thong AI Video Translator Pro 2026 dang hoat dong binh thuong. "
               "Giong doc nay duoc tong hop hoan toan bang tri tue nhan tao offline.")

def sep(t=""):
    print("\n" + "─"*65)
    if t: print(f"  {t}"); print("─"*65)

def chk(path, label):
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        kb = os.path.getsize(path)//1024
        print(f"  ✅  {label}  [{kb} KB]")
        return True
    print(f"  ❌  {label}  — file khong ton tai hoac rong!")
    return False

def init_service():
    sep("KHOI TAO VOICE SERVICE")
    dev = "CUDA ✅" if torch.cuda.is_available() else "CPU ⚠️"
    print(f"  🖥️   Thiet bi: {dev}")
    t0 = time.time()
    svc = VoiceService()
    print(f"  ⏱️   Load time: {time.time()-t0:.1f}s")
    status = "✅ San sang" if svc.tts_model else "⚠️  Fallback pyttsx3"
    print(f"  {status}")
    return svc

def test_list_voices(svc):
    sep("TEST 1 — Liet ke Preset Voices")
    voices = svc.list_voices()
    if not voices:
        print("  ⚠️  Khong lay duoc danh sach (model chua load?)")
        return []
    print(f"  Tim thay {len(voices)} voices:\n")
    print(f"  {'STT':<4} {'Mo ta':<30} {'Voice ID'}")
    print(f"  {'─'*4} {'─'*30} {'─'*20}")
    for i,(desc,vid) in enumerate(voices,1):
        print(f"  {i:<4} {desc:<30} {vid}")
    return voices

def test_preset_voices(svc, voices):
    sep("TEST 2 — TTS voi tung Preset Voice")
    if not voices:
        print("  ⚠️  Bo qua")
        return
    results = []
    for desc, vid in voices:
        out = os.path.join(OUTPUT_DIR, f"preset_{vid}.wav")
        t0 = time.time()
        ok = svc.run_tts(text=TEXT_SHORT, voice=vid, output_path=out)
        elapsed = time.time()-t0
        label = f"{desc} | {vid} ({elapsed:.1f}s)"
        results.append(chk(out, label) if ok else (print(f"  ❌  {label} → run_tts=False") or False))
    print(f"\n  📊  {sum(results)}/{len(voices)} preset voices hoat dong")

def test_clone_voice(svc):
    sep("TEST 3 — Clone Voice (Zero-shot tu sample.wav)")
    if not os.path.exists(SAMPLE_WAV):
        print(f"  ⚠️  Bo qua — khong tim thay: {SAMPLE_WAV}")
        return None
    kb = os.path.getsize(SAMPLE_WAV)//1024
    print(f"  📂  sample.wav ({kb} KB)\n")
    results = []
    for text, fname in [(TEXT_SHORT,"clone_short.wav"),(TEXT_MEDIUM,"clone_medium.wav")]:
        out = os.path.join(OUTPUT_DIR, fname)
        print(f"  📝  {text[:55]}...")
        t0 = time.time()
        ok = svc.run_tts(text=text, voice=SAMPLE_WAV, output_path=out)
        elapsed = time.time()-t0
        results.append(chk(out, f"{fname} ({elapsed:.1f}s)") if ok else False)
    p = sum(results)
    print(f"\n  📊  {p}/{len(results)} clone voice thanh cong")
    return p == len(results)

def test_fallback(svc):
    sep("TEST 4 — Fallback pyttsx3")
    backup = svc.tts_model
    svc.tts_model = None
    out = os.path.join(OUTPUT_DIR, "fallback_pyttsx3.wav")
    t0 = time.time()
    ok = svc.run_tts(text=TEXT_SHORT, output_path=out)
    elapsed = time.time()-t0
    result = chk(out, f"pyttsx3 ({elapsed:.1f}s)") if ok else False
    svc.tts_model = backup
    return result

def test_edge_cases(svc):
    sep("TEST 5 — Edge Cases")
    cases = [
        ("",    None,               "edge_empty.wav",   False, "Text rong -> False"),
        ("   ", None,               "edge_space.wav",   False, "Toan space -> False"),
        (TEXT_SHORT, None,          "edge_no_voice.wav", True,  "voice=None -> default"),
        (TEXT_SHORT, "id_sai_xyz",  "edge_bad_id.wav",  True,  "voice ID sai -> fallback default"),
    ]
    for text, voice, fname, expect, desc in cases:
        out = os.path.join(OUTPUT_DIR, fname)
        ok = svc.run_tts(text=text, voice=voice, output_path=out)
        status = "✅ PASS" if (ok==expect) else "❌ FAIL"
        print(f"  {status}  {desc}")

def main():
    print("="*65)
    print("  🧪  TEST SUITE — VoiceService v2 (VieNeu-TTS Fixed API)")
    print("="*65)
    print(f"  📁  Output: {OUTPUT_DIR}")
    svc    = init_service()
    voices = test_list_voices(svc)
    test_preset_voices(svc, voices)
    r3     = test_clone_voice(svc)
    r4     = test_fallback(svc)
    test_edge_cases(svc)
    sep("TONG KET")
    print(f"  Test 1 - List Voices   : {'✅' if voices else '⚠️ '} {len(voices)} voices")
    print(f"  Test 2 - Preset Voices : ✅ Da chay")
    clone_s = '✅ PASS' if r3 else ('⚠️  Bo qua (khong co sample.wav)' if r3 is None else '❌ FAIL')
    print(f"  Test 3 - Clone Voice   : {clone_s}")
    print(f"  Test 4 - Fallback TTS  : {'✅ PASS' if r4 else '❌ FAIL'}")
    print(f"  Test 5 - Edge Cases    : ✅ Da chay")
    print(f"\n  📁  Tat ca output tai: {OUTPUT_DIR}")
    print("="*65)

if __name__ == "__main__":
    main()