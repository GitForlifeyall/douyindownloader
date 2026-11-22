#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_4_comparison_videos.py
================================
Produces 4 high-fidelity, 1-minute comparison videos:
  1. OmniVoice (k2-fsa / Indian Accent)
  2. Google Cloud Chirp (hi-IN-Chirp3-HD-Orus)
  3. Google Flash 3.8 TTS (gemini-3.8-flash-tts / Orus)
  4. Sarvam AI (Bulbul v3 / Shubh)

Each video includes:
  - Exact 60.0s timeline synchronization
  - Waterfall Anti-Overlap speech alignment for blocks 1-7
  - Preserved welding SFX & BGM from Demucs stem
  - Professional sidechain ducking compression
  - Elegant on-screen model identification badge
"""

import os
import sys
import time
import io
import subprocess
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

import numpy as np
import soundfile as sf
from dubbing_studio.tts_engine import load_srt_blocks

BASE_DIR = Path(r"c:\Users\rudra\PycharmProjects\douyindownloader")
OUTPUT_DIR = BASE_DIR / "output"

VIDEO_PATH = OUTPUT_DIR / "2026-09-03 16.39.11-Video-机械之眼-两个大小不同的圆钢管该如何焊接？ ...焊接 #电焊 #劳动人民的智慧 #技巧.mp4"
SRT_PATH = OUTPUT_DIR / "2026-09-03 16.39.11-Video-机械之眼-两个大小不同的圆钢管该如何焊接？ ...焊接 #电焊 #劳动人民的智慧 #技巧_hindi.srt"
BGM_PATH = OUTPUT_DIR / "stems_2026-09-03 16.39.11-Video-机械之眼-两个大小不同的圆钢管该如何焊接？ ...焊接 #电焊 #劳动人民的智慧 #技巧" / "no_vocals.wav"

TARGET_DURATION = 60.0  # Exactly 1 minute
SAMPLE_RATE = 24000

MODELS = [
    {
        "id": "omnivoice",
        "name": "OmniVoice (k2-fsa)",
        "badge": "OmniVoice (k2-fsa) | Hindi Voice Design",
        "cache_dir": OUTPUT_DIR / "cache_omnivoice",
        "output_video": OUTPUT_DIR / "comparison_1min_omnivoice.mp4",
        "master_wav": OUTPUT_DIR / "master_1min_omnivoice.wav",
    },
    {
        "id": "google_chirp",
        "name": "Google Cloud Chirp",
        "badge": "Google Cloud Chirp | Chirp3-HD (Orus)",
        "cache_dir": OUTPUT_DIR / "cache_comparison_gcloud_orus",
        "output_video": OUTPUT_DIR / "comparison_1min_google_chirp.mp4",
        "master_wav": OUTPUT_DIR / "master_1min_google_chirp.wav",
    },
    {
        "id": "google_flash",
        "name": "Google Flash 3.8 TTS",
        "badge": "Google Flash 3.8 TTS | Gemini Audio (Orus)",
        "cache_dir": OUTPUT_DIR / "cache_comparison_gemini_orus",
        "output_video": OUTPUT_DIR / "comparison_1min_gemini_flash.mp4",
        "master_wav": OUTPUT_DIR / "master_1min_gemini_flash.wav",
    },
    {
        "id": "sarvam_ai",
        "name": "Sarvam AI (Bulbul v3)",
        "badge": "Sarvam AI | Bulbul v3 (Shubh)",
        "cache_dir": OUTPUT_DIR / "cache_comparison_sarvam_shubh",
        "output_video": OUTPUT_DIR / "comparison_1min_sarvam_ai.mp4",
        "master_wav": OUTPUT_DIR / "master_1min_sarvam_ai.wav",
    },
]


def trim_silence(audio: np.ndarray, threshold: float = 0.005, pad_samples: int = 480) -> np.ndarray:
    mask = np.abs(audio) > threshold
    if not np.any(mask):
        return audio
    first = max(0, int(np.argmax(mask) - pad_samples))
    last = min(len(audio), int(len(mask) - np.argmax(mask[::-1]) + pad_samples))
    return audio[first:last]


def adjust_audio_speed(audio: np.ndarray, sample_rate: int, speed: float) -> np.ndarray:
    if abs(speed - 1.0) < 0.03:
        return audio
    temp_in = io.BytesIO()
    sf.write(temp_in, audio, sample_rate, format="WAV")
    wav_bytes = temp_in.getvalue()

    safe_speed = max(0.85, min(speed, 1.30))
    cmd = [
        "ffmpeg", "-y",
        "-f", "wav", "-i", "pipe:0",
        "-filter:a", f"atempo={safe_speed:.3f}",
        "-f", "wav", "pipe:1"
    ]
    proc = subprocess.run(cmd, input=wav_bytes, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.returncode == 0 and len(proc.stdout) > 44:
        adj_audio, _ = sf.read(io.BytesIO(proc.stdout))
        return adj_audio
    return audio


def build_master_speech_track(blocks: list, cache_dir: Path, out_wav: Path) -> Path:
    target_sr = SAMPLE_RATE
    master_buffer = np.zeros(int((TARGET_DURATION + 5.0) * target_sr), dtype=np.float32)
    timeline_sample = int(blocks[0]["start"] * target_sr)

    for i, b in enumerate(blocks):
        idx = b["index"]
        c_wav = cache_dir / f"block_{idx:02d}.wav"
        if not c_wav.exists():
            raise FileNotFoundError(f"Missing cached audio: {c_wav}")

        audio_data, sr = sf.read(str(c_wav))
        if audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=1)

        if sr != target_sr:
            temp_in = io.BytesIO()
            sf.write(temp_in, audio_data, sr, format="WAV")
            proc = subprocess.run(
                ["ffmpeg", "-y", "-f", "wav", "-i", "pipe:0", "-ar", str(target_sr), "-f", "wav", "pipe:1"],
                input=temp_in.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            audio_data, _ = sf.read(io.BytesIO(proc.stdout))
            sr = target_sr

        trimmed = trim_silence(audio_data, pad_samples=int(0.02 * target_sr))
        raw_dur = len(trimmed) / target_sr

        orig_start_sample = int(b["start"] * target_sr)
        if i + 1 < len(blocks):
            next_start = blocks[i + 1]["start"]
            avail_dur = max(next_start - b["start"], 0.8)
        else:
            avail_dur = max(TARGET_DURATION - b["start"], 1.5)

        if raw_dur > avail_dur * 1.04:
            speed_factor = min(raw_dur / avail_dur, 1.30)
            trimmed = adjust_audio_speed(trimmed, target_sr, speed_factor)

        # Waterfall placement
        gap_sec = b["start"] - (timeline_sample / target_sr)
        if gap_sec < 0.04:
            act_start = max(timeline_sample + int(0.04 * target_sr), orig_start_sample - int(0.12 * target_sr))
        else:
            act_start = max(orig_start_sample, timeline_sample + int(0.02 * target_sr))

        act_end = act_start + len(trimmed)
        if act_end > len(master_buffer):
            master_buffer = np.pad(master_buffer, (0, act_end - len(master_buffer) + target_sr * 5))

        master_buffer[act_start:act_end] += trimmed
        timeline_sample = act_end

    max_samples = int(TARGET_DURATION * target_sr)
    clipped_buffer = master_buffer[:max_samples]
    peak = np.max(np.abs(clipped_buffer))
    if peak > 0:
        clipped_buffer = clipped_buffer / peak * 0.95

    sf.write(str(out_wav), clipped_buffer, target_sr)
    return out_wav


def render_comparison_video(model_info: dict, srt_blocks: list) -> Path:
    print(f"\n[{model_info['name']}] Building 60s master speech track...")
    out_wav = build_master_speech_track(srt_blocks, model_info["cache_dir"], model_info["master_wav"])
    print(f"[{model_info['name']}] Speech track ready: {out_wav.name}")

    out_video = model_info["output_video"]
    badge_text = model_info["badge"].replace("'", "\\'").replace(":", "\\:")

    video_filter = (
        f"[0:v]trim=0:60,setpts=PTS-STARTPTS,"
        f"drawbox=x=(w-840)/2:y=100:w=840:h=90:color=black@0.75:t=fill,"
        f"drawbox=x=(w-840)/2:y=100:w=840:h=90:color=white@0.25:t=2,"
        f"drawtext=text='{badge_text}':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=128[vout]"
    )

    audio_filter = (
        "[1:a]atrim=0:60,asetpts=PTS-STARTPTS,volume=0.75[bgm];"
        "[2:a]atrim=0:60,asetpts=PTS-STARTPTS,highpass=f=80,treble=g=3:f=3000,"
        "acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,"
        "loudnorm=I=-12:TP=-0.5:LRA=6,asplit=2[voice_sc][voice_mix];"
        "[bgm][voice_sc]sidechaincompress=threshold=0.08:ratio=5:attack=20:release=250[ducked_bgm];"
        "[ducked_bgm][voice_mix]amix=inputs=2:weights=0.85 1.35:normalize=0[mixed];"
        "[mixed]alimiter=limit=0.99:attack=5:release=50[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(VIDEO_PATH),
        "-i", str(BGM_PATH),
        "-i", str(out_wav),
        "-filter_complex", f"{video_filter};{audio_filter}",
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "256k",
        "-t", "60",
        str(out_video)
    ]

    print(f"[{model_info['name']}] Rendering final 1-minute video...")
    t0 = time.time()
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        print(f"Error rendering {model_info['name']}:\n{res.stderr.decode('utf-8', errors='ignore')}")
        raise RuntimeError(f"FFmpeg failed for {model_info['name']}")

    dur = time.time() - t0
    file_size_mb = out_video.stat().st_size / (1024 * 1024)
    print(f"[{model_info['name']}] Rendered successfully in {dur:.1f}s ({file_size_mb:.2f} MB)")
    return out_video


def main():
    print("=" * 70)
    print(" 4-Model 1-Minute TTS Comparison Video Generator")
    print(" 1. OmniVoice (k2-fsa)")
    print(" 2. Google Cloud Chirp (Chirp3-HD)")
    print(" 3. Google Flash 3.8 TTS (Gemini Audio)")
    print(" 4. Sarvam AI (Bulbul v3)")
    print("=" * 70)

    all_blocks = load_srt_blocks(SRT_PATH)
    # Target exactly the first 7 blocks spanning up to ~59.4 seconds
    target_blocks = [b for b in all_blocks if b["index"] <= 7]
    print(f"Loaded {len(target_blocks)} blocks covering 0:00 -> 0:59.4s.")

    results = []
    t_start = time.time()
    for m in MODELS:
        v_path = render_comparison_video(m, target_blocks)
        results.append((m["name"], v_path))

    print("\n" + "=" * 70)
    print(f" ALL 4 COMPARISON VIDEOS CREATED SUCCESSFULLY in {time.time() - t_start:.1f}s!")
    print("=" * 70)
    for name, path in results:
        size = path.stat().st_size / (1024 * 1024)
        print(f" - {name:28s} : {path.name} ({size:.2f} MB)")
    print("=" * 70)


if __name__ == "__main__":
    main()
