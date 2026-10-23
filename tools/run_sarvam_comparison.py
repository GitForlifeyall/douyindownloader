#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_sarvam_comparison.py
========================
Generates a Sarvam AI Bulbul v3 dubbed video for the downloaded Douyin welding video.
Uses:
  - Sarvam AI Bulbul v3 (speaker: shubh)
  - Waterfall anti-overlap timeline alignment
  - Preserved background welding SFX & BGM via Demucs sidechain ducking
"""

import os
import sys
import time
import io
import base64
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

import numpy as np
import soundfile as sf
from sarvamai import SarvamAI

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


def synthesize_sarvam(client: SarvamAI, text: str, speaker: str = "shubh", pace: float = 1.10) -> np.ndarray:
    response = client.text_to_speech.convert(
        text=text,
        language_code="hi-IN",
        model="bulbul:v3",
        speaker=speaker,
        pace=float(pace),
        speech_sample_rate=24000
    )
    raw_audio = response.audios[0] if hasattr(response, "audios") and response.audios else response
    if isinstance(raw_audio, str):
        audio_bytes = base64.b64decode(raw_audio)
    elif isinstance(raw_audio, bytes):
        audio_bytes = raw_audio
    else:
        audio_bytes = bytes(raw_audio)

    data, sr = sf.read(io.BytesIO(audio_bytes))
    if len(data.shape) > 1:
        data = np.mean(data, axis=1)
    return data.astype(np.float32)


def main():
    target_vids = [p for p in Path("output").glob("*.mp4") if "2026-09-03" in p.name and not p.name.endswith("_dubbed.mp4")]
    if not target_vids:
        raise FileNotFoundError("Target video not found in output folder.")
    vid_path = target_vids[0]

    hindi_srts = [p for p in Path("output").glob("*.srt") if "2026-09-03" in p.name and "_hindi" in p.name]
    if not hindi_srts:
        raise FileNotFoundError("Target Hindi SRT not found in output folder.")
    srt_path = hindi_srts[0]

    stem_dirs = [d for d in Path("output").iterdir() if d.is_dir() and "stems_2026-09-03" in d.name]
    bgm_path = stem_dirs[0] / "no_vocals.wav" if stem_dirs and (stem_dirs[0] / "no_vocals.wav").exists() else None

    out_vid = Path("output/comparison_sarvam_shubh.mp4")

    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(vid_path)]
    vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())

    print("==================================================")
    print(" [Sarvam AI Dubbing] Bulbul v3 Native Hindi Voice")
    print(f" Source Video     : {vid_path.name}")
    print(f" Target Subtitles : {srt_path.name}")
    print(f" Preserved BGM    : {bgm_path.name if bgm_path else 'None'}")
    print(f" Final Output     : {out_vid.name}")
    print("==================================================")

    blocks = load_srt_blocks(srt_path)
    sample_rate = 24000

    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise ValueError("SARVAM_API_KEY is not set.")
    client = SarvamAI(api_subscription_key=api_key)

    cache_dir = Path("output/cache_comparison_sarvam_shubh")
    cache_dir.mkdir(parents=True, exist_ok=True)

    block_audios = []
    t0 = time.time()
    print(f"\n[Sarvam AI] Synthesizing all {len(blocks)} blocks individually...")

    for i, b in enumerate(blocks, 1):
        idx = b["index"]
        c_wav = cache_dir / f"block_{idx:02d}.wav"

        if not c_wav.exists():
            text = b["text"].strip()
            # Calculate dynamic pace for natural fit
            target_dur = max(b["duration"], 0.8)
            est_dur = len(text.split()) / 2.85
            ideal_pace = round(est_dur / target_dur, 2)
            pace = max(0.90, min(ideal_pace, 1.25))

            audio_data = synthesize_sarvam(client, text, speaker="shubh", pace=pace)
            sf.write(str(c_wav), audio_data, sample_rate)

        raw_audio, sr = sf.read(str(c_wav))
        block_audios.append({"block": b, "audio": raw_audio, "sr": sample_rate})
        if i % 5 == 0 or i == len(blocks):
            print(f"  [Sarvam AI] [{i:02d}/{len(blocks):02d}] blocks ready")

    print(f"[Sarvam AI] All {len(blocks)} blocks ready in {time.time() - t0:.1f}s.")

    # Waterfall assembly
    master_buffer = np.zeros(int((vid_dur + 5.0) * sample_rate), dtype=np.float32)
    timeline_sample = int(block_audios[0]["block"]["start"] * sample_rate)

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

        if raw_dur > avail_dur * 1.04:
            speed_factor = min(raw_dur / avail_dur, 1.25)
            trimmed = adjust_audio_speed(trimmed, sample_rate, speed_factor)

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

    peak = np.max(np.abs(master_buffer))
    if peak > 0:
        master_buffer = master_buffer / peak * 0.95

    master_wav = out_vid.parent / f"master_{out_vid.stem}.wav"
    sf.write(str(master_wav), master_buffer[:int(vid_dur * sample_rate)], sample_rate)

    print("\n[Mastering] FFmpeg muxing with sidechain BGM ducking...")
    if bgm_path and bgm_path.exists():
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
        print(" [SUCCESS] Sarvam AI Dubbed Video Created:")
        print(f" Path: {out_vid.resolve()}")
        print("==================================================")
    else:
        raise RuntimeError(f"FFmpeg error remuxing video: {res.stderr.decode('utf-8', errors='replace')}")


if __name__ == "__main__":
    main()
