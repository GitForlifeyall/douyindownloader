import os
import sys
import re
import time
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf

# Setup UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
sys.path.append(str(CURRENT_DIR))

# Setup CUDA DLL paths for GPU
VENV_SITE = CURRENT_DIR / ".venv" / "Lib" / "site-packages"
DLL_DIRS = [
    str(VENV_SITE / p)
    for p in [
        "nvidia/cublas/bin",
        "nvidia/cudnn/bin",
        "nvidia/cuda_nvrtc/bin",
        "nvidia/cuda_runtime/bin",
        "nvidia/cufft/bin",
        "nvidia/curand/bin",
        "nvidia/cusparse/bin",
        "nvidia/nvjitlink/bin",
        "onnxruntime/capi",
    ]
    if (VENV_SITE / p).exists()
]
for p in DLL_DIRS:
    os.add_dll_directory(p)
os.environ["PATH"] = ";".join(DLL_DIRS) + ";" + os.environ.get("PATH", "")

import onnxruntime as ort
from kokoro_onnx import Kokoro
from google import genai
from google.genai import types
from translator import load_srt

# File paths
download_dir = CURRENT_DIR / "Volume" / "Download"
chinese_srt = download_dir / "2026-10-05 14.31.00-Video-鲸鱼影视-一次意外，让女人从凡人逆袭成宇宙霸主 #好剧推荐 #电影解说 #科幻.srt"
hindi_srt = download_dir / "dubbed_hindi_first_half.srt"
half_video = download_dir / "original_video_first_half.mp4"
final_hindi_video = download_dir / "dubbed_first_half_hindi.mp4"

model_path = os.environ.get("KOKORO_MODEL_PATH", "models/kokoro-v1.0.onnx")
voices_path = os.environ.get("KOKORO_VOICES_PATH", "models/voices-v1.0.bin")

API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not API_KEY:
    raise SystemExit("Set GEMINI_API_KEY env var before running this script.")

print("==========================================================")
print("=== Hindi Dubbing Automation Pipeline (First Half) ===")
print("==========================================================")

# 1. Load and slice first half (blocks <= 463s)
all_blocks = load_srt(str(chinese_srt))
first_half_blocks = [b for b in all_blocks if b["start"] <= 463.0]
print(f"Total blocks in first half: {len(first_half_blocks)} (up to 07:43)")

# 2. Translate to Hindi using Gemini with Time-Fitting Constraints
if not hindi_srt.exists() or hindi_srt.stat().st_size < 100:
    print(f"\n[Step 1/3] Translating {len(first_half_blocks)} blocks to Hindi via Gemini...")
    client = genai.Client(api_key=API_KEY)
    
    system_instruction = (
        "You are an expert Hindi movie recap dubbing director (like popular Hindi movie explanation YouTube channels).\n"
        "Your task is to translate timestamped subtitle blocks into dramatic, punchy, spoken Hindi (Devanagari script).\n\n"
        "CRITICAL DUBBING TIME-FITTING RULES:\n"
        "1. Each subtitle block has a duration in seconds [Dur: X.Xs].\n"
        "2. Keep each Hindi sentence concise and punchy so it can be spoken in the given seconds without rushing.\n"
        "3. Use natural spoken Hindi / dramatic recap vocabulary (e.g., 'ऑपरेशन थियेटर', 'गोलियों की बौछार', 'दिमागी ताकत').\n"
        "4. Output the EXACT SAME number of blocks in valid SRT format (Index, Timestamp, Hindi Text).\n"
        "5. Output valid SRT text only without markdown backticks."
    )

    batch_size = 25
    translated_srt_chunks = []
    
    for i in range(0, len(first_half_blocks), batch_size):
        batch = first_half_blocks[i : i + batch_size]
        print(f"  Translating blocks {batch[0]['index']} to {batch[-1]['index']}...")
        
        prompt_lines = [f"Translate these {len(batch)} blocks into punchy Hindi for voiceover dubbing:\n"]
        for b in batch:
            max_w = max(int(b["duration"] * 2.5), 4)
            prompt_lines.append(f"{b['index']}\n{b['start_str']} --> {b['end_str']} [Max words: {max_w}]\n{b['text']}\n")
            
        prompt = "\n".join(prompt_lines)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
        )
        resp = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=config
        )
        cleaned = re.sub(r"^```[a-zA-Z]*\n", "", resp.text.strip())
        cleaned = re.sub(r"\n```$", "", cleaned)
        translated_srt_chunks.append(cleaned.strip())
        time.sleep(1)

    hindi_srt.write_text("\n\n".join(translated_srt_chunks) + "\n", encoding="utf-8")
    print(f"Hindi SRT successfully saved to: {hindi_srt.name}")
else:
    print(f"Existing Hindi SRT found: {hindi_srt.name}")

# 3. Kokoro Hindi TTS on GPU
print(f"\n[Step 2/3] Synthesizing Hindi voiceover (Voice: hm_omega, Lang: hi)...")
sess_opts = ort.SessionOptions()
sess_opts.log_severity_level = 3
providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if "CUDAExecutionProvider" in ort.get_available_providers() else ["CPUExecutionProvider"]
session = ort.InferenceSession(model_path, sess_options=sess_opts, providers=providers)
active_ep = session.get_providers()[0]
print(f"Active Provider: {active_ep} ({'NVIDIA RTX GPU' if 'CUDA' in active_ep else 'CPU'})")

kokoro = Kokoro.from_session(session, voices_path)
sample_rate = 24000
total_samples = int(465.0 * sample_rate)
synced_buffer = np.zeros(total_samples, dtype=np.float32)

hindi_blocks = load_srt(str(hindi_srt))
cursor_sample = 0
voice_name = "hm_omega" # Male Hindi Voice

start_t = time.time()
for i, b in enumerate(hindi_blocks, start=1):
    text = b["text"]
    t_start = b["start"]
    t_end = b["end"]
    target_dur = max(t_end - t_start, 1.0)

    # Dynamic speed calculation
    word_count = len(text.split())
    est_dur = word_count * 0.38
    if est_dur > target_dur * 1.25:
        speed = 1.20
    elif est_dur > target_dur * 1.1:
        speed = 1.12
    else:
        speed = 1.02

    try:
        samples, _ = kokoro.create(text, voice=voice_name, speed=speed, lang="hi")
    except Exception as e:
        print(f"  [{i}/{len(hindi_blocks)}] Error on block {b['index']}: {e}")
        continue

    audio_len = len(samples)

    # STRICT SINGLE-VOICE PLACEMENT (No Overlap)
    start_idx = max(int(t_start * sample_rate), cursor_sample)
    end_idx = start_idx + audio_len

    if end_idx > len(synced_buffer):
        synced_buffer = np.pad(synced_buffer, (0, end_idx - len(synced_buffer)))

    synced_buffer[start_idx:end_idx] = samples
    cursor_sample = end_idx + int(0.06 * sample_rate)

    if i % 10 == 0 or i == len(hindi_blocks):
        print(f"  [{i}/{len(hindi_blocks)}] [{b['start_str'][:8]}] Hindi audio generated: {text[:40]}...", flush=True)

elapsed = time.time() - start_t
print(f"Synthesized all {len(hindi_blocks)} Hindi blocks in {elapsed:.1f}s!")

# Normalize audio
max_amp = np.max(np.abs(synced_buffer))
if max_amp > 1.0:
    synced_buffer = synced_buffer / max_amp * 0.98

# Trim buffer to exact first half duration
synced_buffer = synced_buffer[:int(463.0 * sample_rate)]

temp_wav = download_dir / "first_half_hindi.wav"
temp_mp3 = download_dir / "first_half_hindi.mp3"
sf.write(str(temp_wav), synced_buffer, sample_rate)
subprocess.run(["ffmpeg", "-y", "-i", str(temp_wav), "-b:a", "192k", str(temp_mp3)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# 4. Mux with FFmpeg into final video
print(f"\n[Step 3/3] Merging Hindi audio into video -> {final_hindi_video.name}...")
cmd = [
    "ffmpeg", "-y",
    "-i", str(half_video),
    "-i", str(temp_mp3),
    "-c:v", "copy",
    "-c:a", "aac",
    "-b:a", "192k",
    "-map", "0:v:0",
    "-map", "1:a:0",
    "-shortest",
    str(final_hindi_video)
]
res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if res.returncode == 0:
    print(f"\n SUCCESS! Hindi Dubbed Video created: {final_hindi_video}")
    print(f"Size: {final_hindi_video.stat().st_size / 1024 / 1024:.1f} MB")
else:
    print("\n Error muxing Hindi video.")
