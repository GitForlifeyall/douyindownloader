#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spread_evenly_dubber.py
=======================
Evenly spreads spoken words across each subtitle block's visual duration.
- Dynamically computes Sarvam Bulbul v3 speaking pace per block to fill its scene window.
- Eliminates awkward dead silence / gaps between blocks (maintains tight 120ms natural breath pauses).
- Uses pristine rubberband tempo micro-alignment to lock words across the exact scene interval.
- Maintains strict SRT timestamp synchronization: Block 1 starts at 0.00s, Block 3 at 12.66s, etc.
"""

import os
import sys
import time
import io
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts_engine import load_srt_blocks
from dubbing_studio.tts import generate_sarvam_tts


def trim_silence(audio: np.ndarray, threshold: float = 0.004, pad_samples: int = 480) -> np.ndarray:
    """Trim digital zero-padding from start and end."""
    mask = np.abs(audio) > threshold
    if not np.any(mask):
        return audio
    first = max(0, int(np.argmax(mask) - pad_samples))
    last = min(len(audio), int(len(mask) - np.argmax(mask[::-1]) + pad_samples))
    return audio[first:last]


def adjust_audio_rubberband(audio: np.ndarray, sample_rate: int, target_duration: float) -> np.ndarray:
    """Precisely stretch or compress audio using high-quality rubberband tempo filter."""
    current_duration = len(audio) / sample_rate
    if current_duration <= 0.1 or target_duration <= 0.1:
        return audio

    ratio = current_duration / target_duration
    if abs(ratio - 1.0) < 0.02:
        return audio

    temp_in = io.BytesIO()
    sf.write(temp_in, audio, sample_rate, format="WAV")
    wav_bytes = temp_in.getvalue()

    safe_tempo = max(0.5, min(ratio, 2.0))
    cmd = [
        "ffmpeg", "-y",
        "-f", "wav", "-i", "pipe:0",
        "-filter:a", f"rubberband=tempo={safe_tempo:.4f}",
        "-f", "wav", "pipe:1"
    ]
    proc = subprocess.run(cmd, input=wav_bytes, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.returncode == 0 and len(proc.stdout) > 44:
        adj_audio, _ = sf.read(io.BytesIO(proc.stdout))
        return adj_audio
    return audio


def main():
    srt_file = Path(r"output/2026-08-19 08.59.00-Video-熊猫观影-#电影解说 #影视解说_hindi.srt")
    vid_file = Path(r"output/2026-08-19 08.59.00-Video-熊猫观影-#电影解说 #影视解说.mp4")
    out_vid = Path(r"output/2026-08-19_movie_hindi_spread_evenly.mp4")

    blocks = load_srt_blocks(srt_file)
    print(f"Loaded {len(blocks)} subtitle blocks from {srt_file.name}")

    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(vid_file)]
    vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())
    print(f"Target Video Runtime: {vid_dur:.2f}s")

    sample_rate = 48000
    cache_dir = Path("output/sarvam_spread_blocks")
    cache_dir.mkdir(parents=True, exist_ok=True)

    master_buffer = np.zeros(int((vid_dur + 2.0) * sample_rate), dtype=np.float32)

    print("\n" + "=" * 65)
    print("  Synthesizing & Spreading Words Evenly Across Each Scene")
    print("=" * 65)

    for i, b in enumerate(blocks):
        idx = b["index"]
        t_start = b["start"]
        t_end = b["end"]

        # Scene interval until next block starts
        if i + 1 < len(blocks):
            next_start = blocks[i + 1]["start"]
            window_dur = next_start - t_start
        else:
            window_dur = vid_dur - t_start

        # Desired speech duration leaves only 100ms-140ms breath room so words fill the scene
        breath_pause = 0.12 if window_dur > 2.0 else 0.05
        target_speech_dur = max(window_dur - breath_pause, 0.6)

        words = len(b["text"].split())
        # Estimate natural pace (Sarvam baseline ~2.8 words/sec at pace 1.0)
        est_dur_1x = words / 2.8
        computed_pace = round(est_dur_1x / target_speech_dur, 2)
        safe_pace = max(0.68, min(computed_pace, 1.15))

        cache_file = cache_dir / f"block_{idx:02d}_pace_{int(safe_pace*100)}.mp3"

        if not cache_file.exists() or cache_file.stat().st_size < 1000:
            generate_sarvam_tts(
                text=b["text"],
                output_path=str(cache_file),
                speaker="shubh",
                pace=safe_pace,
                model="bulbul:v3"
            )

        raw_audio, sr = sf.read(str(cache_file))
        clean_audio = trim_silence(raw_audio)
        raw_dur = len(clean_audio) / sr

        # Micro-alignment with rubberband to lock speech exactly to target_speech_dur
        fitted_audio = adjust_audio_rubberband(clean_audio, sr, target_speech_dur)
        fitted_dur = len(fitted_audio) / sr

        # Place onto master timeline strictly at block's start second
        start_sample = int(t_start * sample_rate)
        end_sample = start_sample + len(fitted_audio)

        if end_sample > len(master_buffer):
            master_buffer = np.pad(master_buffer, (0, end_sample - len(master_buffer) + sample_rate * 2))

        master_buffer[start_sample:end_sample] += fitted_audio

        print(f"  [#{idx:02d}] Window: {window_dur:5.2f}s | Pace: {safe_pace:.2f}x | Spoken: {fitted_dur:5.2f}s | Gap left: {window_dur - fitted_dur:4.2f}s")

    # Peak normalization
    peak = np.max(np.abs(master_buffer[:int(vid_dur * sample_rate)]))
    if peak > 0:
        master_buffer = master_buffer / peak * 0.95

    master_wav = Path("output/master_sarvam_spread_evenly.wav")
    sf.write(str(master_wav), master_buffer[:int(vid_dur * sample_rate)], sample_rate)
    print(f"\n[Master] Saved spread-out voiceover: {master_wav.name} ({vid_dur:.2f}s)")

    # Mux with YouTube Shorts broadcast mix and ducked SFX
    print(f"[Mastering] Muxing broadcast audio into {out_vid.name}...")
    cmd_mux = [
        "ffmpeg", "-y",
        "-i", str(vid_file),
        "-i", str(master_wav),
        "-filter_complex",
        "[1:a]highpass=f=80,treble=g=3:f=3000,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,loudnorm=I=-14:TP=-1.5:LRA=7[voice];"
        "[0:a]volume=0.18[bg];"
        "[voice][bg]amix=inputs=2:duration=first:dropout_transition=1[aout]",
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(out_vid)
    ]
    res = subprocess.run(cmd_mux, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"\n[SUCCESS] Final Video Created: {out_vid.resolve()}")
    else:
        print(f"[Error] FFmpeg failed: {res.stderr[:400]}")


if __name__ == "__main__":
    main()
