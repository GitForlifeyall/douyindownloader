#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dub_line_by_line_mms.py
========================
Line-by-Line Video Dubber powered by Meta MMS-TTS (facebook/mms-tts-hin).
Features:
  - 100% Local & Offline (Runs via Hugging Face Transformers)
  - Native Devanagari Hindi pronunciation trained by Meta AI
  - Waterfall anti-overlap timeline assembly (Zero voice collision)
  - Preserved BGM sidechain ducking or clean voice muxing
"""

import os
import sys
import time
import io
import subprocess
from pathlib import Path
from typing import List, Dict, Any

import torch
import numpy as np
import soundfile as sf
from transformers import VitsModel, AutoTokenizer

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts_engine import load_srt_blocks


def trim_audio_silence(audio: np.ndarray, threshold: float = 0.005, pad_samples: int = 480) -> np.ndarray:
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


def main():
    srt_path = Path("output/latest_hindi.srt")
    vid_path = Path("output/latest_original.mp4")
    out_vid = Path("output/line_by_line_mms_dubbed.mp4")

    if not srt_path.exists():
        srt_candidates = list(Path("output").glob("*_hindi.srt"))
        if srt_candidates:
            srt_path = srt_candidates[0]

    if not vid_path.exists():
        vid_candidates = [f for f in Path("output").glob("*.mp4") if not f.name.endswith("_dubbed.mp4")]
        if vid_candidates:
            vid_path = vid_candidates[0]

    stem_dirs = [d for d in Path("output").iterdir() if d.is_dir() and "stems_" in d.name]
    bgm_path = stem_dirs[0] / "no_vocals.wav" if stem_dirs and (stem_dirs[0] / "no_vocals.wav").exists() else None

    print("==================================================")
    print(" [Line-by-Line Studio] Meta MMS-TTS Hindi Narrator")
    print(f" Model            : facebook/mms-tts-hin (Local)")
    print(f" Target Subtitles : {srt_path.name}")
    print(f" Source Video     : {vid_path.name}")
    print(f" Preserved BGM    : {bgm_path.name if bgm_path else 'None'}")
    print(f" Final Output     : {out_vid.name}")
    print("==================================================")

    blocks = load_srt_blocks(srt_path)
    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(vid_path)]
    vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())

    print("\n[Meta MMS-TTS] Loading tokenizer and model (facebook/mms-tts-hin)...")
    model_id = "facebook/mms-tts-hin"
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = VitsModel.from_pretrained(model_id)
    model.eval()
    sample_rate = model.config.sampling_rate  # 16000 Hz

    cache_dir = Path("output/mms_tts_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. Synthesize all blocks individually
    print(f"\n[Meta MMS-TTS] Synthesizing all {len(blocks)} blocks individually...")
    block_audios = []
    t_start = time.time()

    for i, b in enumerate(blocks, 1):
        idx = b["index"]
        c_wav = cache_dir / f"block_{idx:02d}.wav"

        if not c_wav.exists():
            text = b["text"].strip()
            inputs = tokenizer(text, return_tensors="pt")
            with torch.no_grad():
                output = model(**inputs).waveform
            audio_np = output.squeeze().cpu().numpy()
            sf.write(str(c_wav), audio_np, sample_rate)

        raw_audio, sr = sf.read(str(c_wav))
        block_audios.append({
            "block": b,
            "audio": raw_audio,
            "sr": sample_rate
        })
        print(f"  [{i:02d}/{len(blocks):02d}] Block #{idx:02d} ready: {len(raw_audio)/sample_rate:.2f}s audio (Target window: {b['end']-b['start']:.2f}s)")

    print(f"[Meta MMS-TTS] All {len(blocks)} blocks synthesized in {time.time() - t_start:.2f}s.")

    # 2. Assemble Master Timeline using Waterfall Anti-Overlap
    master_buffer = np.zeros(int((vid_dur + 5.0) * sample_rate), dtype=np.float32)
    timeline_sample = int(blocks[0]["start"] * sample_rate)

    print("\n[Mastering] Aligning blocks with Waterfall Anti-Overlap...")
    for i, item in enumerate(block_audios):
        b = item["block"]
        audio = item["audio"]
        trimmed = trim_audio_silence(audio, pad_samples=int(0.02 * sample_rate))
        raw_dur = len(trimmed) / sample_rate

        orig_start_sample = int(b["start"] * sample_rate)

        if i + 1 < len(block_audios):
            next_start = block_audios[i + 1]["block"]["start"]
            avail_dur = max(next_start - b["start"], 0.8)
        else:
            avail_dur = max(vid_dur - b["start"], 1.5)

        # Smooth tempo compression if speech exceeds window
        if raw_dur > avail_dur * 1.04:
            speed_factor = min(raw_dur / avail_dur, 1.25)
            trimmed = adjust_audio_speed(trimmed, sample_rate, speed_factor)
            print(f"  [Block #{b['index']:02d}] Compressed {speed_factor:.2f}x to fit {avail_dur:.2f}s window")

        gap_sec = b["start"] - (timeline_sample / sample_rate)
        if gap_sec < 0.04:
            act_start = max(timeline_sample + int(0.04 * sample_rate), orig_start_sample - int(0.12 * sample_rate))
        else:
            act_start = max(orig_start_sample, timeline_sample + int(0.02 * sample_rate))

        act_end = act_start + len(trimmed)
        if act_end > len(master_buffer):
            master_buffer = np.pad(master_buffer, (0, act_end - len(master_buffer) + sample_rate * 5))

        master_buffer[act_start:act_end] += trimmed
        timeline_sample = act_end
        print(f"  Block #{b['index']:02d} placed at {act_start/sample_rate:5.2f}s -> {act_end/sample_rate:5.2f}s (Visual cut: {b['start']:5.2f}s)")

    # Peak normalize
    peak = np.max(np.abs(master_buffer))
    if peak > 0:
        master_buffer = master_buffer / peak * 0.95

    master_wav = Path("output/master_mms_hin.wav")
    sf.write(str(master_wav), master_buffer[:int(vid_dur * sample_rate)], sample_rate)

    # 3. Video Muxing
    if bgm_path and bgm_path.exists():
        print(f"\n[Mastering] FFmpeg muxing with sidechain BGM ducking into {out_vid.name}...")
        cmd_mux = [
            "ffmpeg", "-y",
            "-i", str(vid_path),
            "-i", str(bgm_path),
            "-i", str(master_wav),
            "-filter_complex",
            "[1:a]volume=0.75[bgm];[2:a]highpass=f=80,treble=g=3:f=3000,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,loudnorm=I=-12:TP=-0.5:LRA=6,asplit=2[voice_sc][voice_mix];[bgm][voice_sc]sidechaincompress=threshold=0.08:ratio=5:attack=20:release=250[ducked_bgm];[ducked_bgm][voice_mix]amix=inputs=2:weights=0.85 1.35:normalize=0[mixed];[mixed]alimiter=limit=0.99:attack=5:release=50[aout]",
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(out_vid)
        ]
    else:
        print(f"\n[Mastering] FFmpeg muxing clean voiceover into {out_vid.name}...")
        cmd_mux = [
            "ffmpeg", "-y",
            "-i", str(vid_path),
            "-i", str(master_wav),
            "-filter_complex",
            "[1:a]highpass=f=80,treble=g=3:f=3000,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,loudnorm=I=-12:TP=-0.5:LRA=6,alimiter=limit=0.99:attack=5:release=50[voice]",
            "-map", "0:v:0",
            "-map", "[voice]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(out_vid)
        ]

    res = subprocess.run(cmd_mux, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if res.returncode == 0:
        print("\n==================================================")
        print(" [SUCCESS] Meta MMS-TTS Dubbed Video Created:")
        print(f" Path: {out_vid.resolve()}")
        print("==================================================")
    else:
        print(f"[Error] Muxing failed: {res.stderr.decode('utf-8', errors='replace')}")


if __name__ == "__main__":
    main()
