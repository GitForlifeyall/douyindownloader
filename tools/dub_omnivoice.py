#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dub_omnivoice.py
================
Dubbing script using k2-fsa/OmniVoice Hugging Face Space.
- Synthesizes Hindi narration blocks with OmniVoice voice design / voice clone
- Employs disk caching in output/cache_omnivoice
- Assembles master timeline with waterfall anti-overlap alignment
- Blends Demucs preserved background/welding SFX with sidechain ducking
- Muxes into final output video: output/comparison_omnivoice.mp4
"""

import os
import sys
import time
import io
import shutil
import subprocess
from pathlib import Path

# Ensure UTF-8 console output on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

import numpy as np
import soundfile as sf
import gradio_client

from dubbing_studio.tts_engine import load_srt_blocks
from dubbing_studio.tts_google import trim_audio_silence, adjust_audio_speed

BASE_DIR = Path(r"c:\Users\rudra\PycharmProjects\douyindownloader")
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR = OUTPUT_DIR / "cache_omnivoice"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# File paths
VIDEO_PATH = OUTPUT_DIR / "2026-09-03 16.39.11-Video-机械之眼-两个大小不同的圆钢管该如何焊接？ ...焊接 #电焊 #劳动人民的智慧 #技巧.mp4"
SRT_PATH = OUTPUT_DIR / "2026-09-03 16.39.11-Video-机械之眼-两个大小不同的圆钢管该如何焊接？ ...焊接 #电焊 #劳动人民的智慧 #技巧_hindi.srt"
BGM_PATH = OUTPUT_DIR / "stems_2026-09-03 16.39.11-Video-机械之眼-两个大小不同的圆钢管该如何焊接？ ...焊接 #电焊 #劳动人民的智慧 #技巧" / "no_vocals.wav"
FINAL_VIDEO = OUTPUT_DIR / "comparison_omnivoice.mp4"


def get_video_duration(video_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return float(res.stdout.strip())


def synthesize_block_omnivoice(client: gradio_client.Client, text: str, cache_file: Path) -> tuple:
    if cache_file.exists():
        data, sr = sf.read(str(cache_file))
        return data, sr

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            # Voice Design endpoint parameters:
            # text, lang='Hindi', ns=32, gs=2.0, dn=True, sp=1.0, du=0, pp=True, po=True,
            # gender='Male / 男', age='Young Adult / 青年', pitch='Moderate Pitch / 中音调',
            # style='Auto', accent='Indian Accent / 印度口音', dialect='Auto'
            res = client.predict(
                text,
                'Hindi',
                32,    # ns (number of steps)
                2.0,   # gs (guidance scale)
                True,  # dn (denoise)
                1.0,   # sp (speed)
                0,     # du (duration)
                True,  # pp (post-process)
                True,  # po
                'Male / 男',
                'Young Adult / 青年',
                'Moderate Pitch / 中音调',
                'Auto',
                'Indian Accent / 印度口音',
                'Auto',
                api_name='/_design_fn'
            )
            temp_wav_path, status = res
            if not temp_wav_path or not Path(temp_wav_path).exists():
                raise RuntimeError(f"OmniVoice returned empty audio path: {res}")

            # Copy to cache
            shutil.copy(temp_wav_path, str(cache_file))
            data, sr = sf.read(str(cache_file))
            return data, sr

        except Exception as e:
            print(f"      [Retry {attempt}/{max_retries}] OmniVoice synthesis failed: {e}")
            if attempt == max_retries:
                raise
            time.sleep(2)


def main():
    print("=" * 70)
    print(" OmniVoice (k2-fsa/OmniVoice) Hindi Video Dubbing Pipeline")
    print("=" * 70)

    if not VIDEO_PATH.exists():
        print(f"Error: Video file not found at {VIDEO_PATH}")
        sys.exit(1)
    if not SRT_PATH.exists():
        print(f"Error: Hindi SRT file not found at {SRT_PATH}")
        sys.exit(1)

    vid_dur = get_video_duration(VIDEO_PATH)
    print(f"Video Duration: {vid_dur:.2f} seconds")

    blocks = load_srt_blocks(SRT_PATH)
    print(f"Loaded {len(blocks)} subtitle blocks from SRT.")

    print("\nConnecting to k2-fsa/OmniVoice Gradio Client...")
    client = gradio_client.Client("k2-fsa/OmniVoice")
    print("Connected successfully!")

    # Step 1: Synthesize all blocks
    block_audios = []
    target_sr = 24000
    t_start = time.time()

    print("\nSynthesizing Hindi speech blocks via OmniVoice...")
    for idx, b in enumerate(blocks, start=1):
        cache_wav = CACHE_DIR / f"block_{b['index']:02d}.wav"
        t0 = time.time()
        audio_data, sr = synthesize_block_omnivoice(client, b["text"], cache_wav)
        dur = len(audio_data) / sr
        print(f"  [{idx:02d}/{len(blocks):02d}] Block #{b['index']:02d} ({dur:.2f}s) in {time.time() - t0:.2f}s | {b['text'][:40]}...")

        # Standardize sample rate & channels
        if audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=1)
        if sr != target_sr:
            # Resample via temp wav & ffmpeg
            temp_in = io.BytesIO()
            sf.write(temp_in, audio_data, sr, format="WAV")
            proc = subprocess.run(
                ["ffmpeg", "-y", "-f", "wav", "-i", "pipe:0", "-ar", str(target_sr), "-f", "wav", "pipe:1"],
                input=temp_in.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            audio_data, _ = sf.read(io.BytesIO(proc.stdout))
            sr = target_sr

        block_audios.append({
            "block": b,
            "audio": audio_data,
            "sr": target_sr
        })

    print(f"\nAll {len(blocks)} speech blocks ready in {time.time() - t_start:.1f}s.")

    # Step 2: Assemble master timeline with Waterfall Anti-Overlap
    print("\nAligning speech blocks onto master timeline (Waterfall Anti-Overlap)...")
    master_buffer = np.zeros(int((vid_dur + 5.0) * target_sr), dtype=np.float32)
    timeline_sample = int(blocks[0]["start"] * target_sr)

    for i, item in enumerate(block_audios):
        b = item["block"]
        audio = item["audio"]
        trimmed = trim_audio_silence(audio, pad_samples=int(0.02 * target_sr))
        raw_dur = len(trimmed) / target_sr

        orig_start_sample = int(b["start"] * target_sr)

        # Available duration window
        if i + 1 < len(block_audios):
            next_start = block_audios[i + 1]["block"]["start"]
            avail_dur = max(next_start - b["start"], 0.8)
        else:
            avail_dur = max(vid_dur - b["start"], 1.5)

        # Adjust speed if necessary to prevent crowding
        if raw_dur > avail_dur * 1.04:
            speed_factor = min(raw_dur / avail_dur, 1.35)
            trimmed = adjust_audio_speed(trimmed, target_sr, speed_factor)
            print(f"  [Block #{b['index']:02d}] Compressed {speed_factor:.2f}x to fit {avail_dur:.2f}s scene window")

        # Waterfall placement: Speech NEVER overlaps previous block
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

    # Peak normalization
    peak_dur_samples = min(len(master_buffer), int(vid_dur * target_sr))
    peak = np.max(np.abs(master_buffer[:peak_dur_samples]))
    if peak > 0:
        master_buffer = master_buffer / peak * 0.95

    master_wav = OUTPUT_DIR / "master_omnivoice.wav"
    sf.write(str(master_wav), master_buffer[:int(vid_dur * target_sr)], target_sr)
    print(f"Master voice track written to: {master_wav}")

    # Step 3: Video Muxing (with BGM Sidechain Ducking)
    print(f"\nMuxing final video with preserved welding audio & ducking...")
    if BGM_PATH.exists():
        cmd_mux = [
            "ffmpeg", "-y",
            "-i", str(VIDEO_PATH),
            "-i", str(BGM_PATH),
            "-i", str(master_wav),
            "-filter_complex",
            "[1:a]volume=0.75[bgm];[2:a]highpass=f=80,treble=g=3:f=3000,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,loudnorm=I=-12:TP=-0.5:LRA=6,asplit=2[voice_sc][voice_mix];[bgm][voice_sc]sidechaincompress=threshold=0.08:ratio=5:attack=20:release=250[ducked_bgm];[ducked_bgm][voice_mix]amix=inputs=2:weights=0.85 1.35:normalize=0[mixed];[mixed]alimiter=limit=0.99:attack=5:release=50[aout]",
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(FINAL_VIDEO)
        ]
    else:
        cmd_mux = [
            "ffmpeg", "-y",
            "-i", str(VIDEO_PATH),
            "-i", str(master_wav),
            "-filter_complex",
            "[1:a]highpass=f=80,treble=g=3:f=3000,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,loudnorm=I=-12:TP=-0.5:LRA=6,alimiter=limit=0.99:attack=5:release=50[voice]",
            "-map", "0:v:0",
            "-map", "[voice]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(FINAL_VIDEO)
        ]

    res = subprocess.run(cmd_mux, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode == 0:
        print("\n" + "=" * 70)
        print(f" SUCCESS! OmniVoice dubbed video created at:\n {FINAL_VIDEO}")
        print("=" * 70)
    else:
        print(f"FFmpeg Error:\n{res.stderr.decode('utf-8', errors='ignore')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
