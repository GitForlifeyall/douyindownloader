#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_blocks_dubber.py
=====================
Strict block-to-block timestamp-synchronized dubbing engine.
Guarantees zero cumulative drift by anchoring every speech line directly
to its exact start second from the original SRT file.
"""

import os
import sys
import time
import io
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from google import genai
from google.genai import types

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts_engine import load_srt_blocks
from dubbing_studio.tts import generate_sarvam_tts


def trim_silence(audio: np.ndarray, threshold: float = 0.005, pad_samples: int = 480) -> np.ndarray:
    """Trim dead silence from start and end so speech starts crisply."""
    mask = np.abs(audio) > threshold
    if not np.any(mask):
        return audio
    first = max(0, int(np.argmax(mask) - pad_samples))
    last = min(len(audio), int(len(mask) - np.argmax(mask[::-1]) + pad_samples))
    return audio[first:last]


def adjust_audio_speed(audio: np.ndarray, sample_rate: int, speed: float) -> np.ndarray:
    """Change tempo without changing pitch using ffmpeg atempo."""
    if abs(speed - 1.0) < 0.03:
        return audio

    temp_in = io.BytesIO()
    sf.write(temp_in, audio, sample_rate, format="WAV")
    wav_bytes = temp_in.getvalue()

    safe_speed = max(0.5, min(speed, 2.0))
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


def synthesize_gemini_block(client, text: str, voice: str = "Enzo", cache_path: Path = None) -> tuple[np.ndarray, int]:
    if cache_path and cache_path.exists() and cache_path.stat().st_size > 1000:
        audio, sr = sf.read(str(cache_path))
        return audio, sr

    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": voice}}}
    )

    styled_text = f"[Tone: High-energy dramatic action movie recap narrator for YouTube Shorts] {text}"

    for attempt in range(6):
        try:
            res = client.models.generate_content(
                model="gemini-3.8-flash-lite-tts",
                contents=styled_text,
                config=config
            )
            raw_bytes = res.candidates[0].content.parts[0].inline_data.data
            audio, sr = sf.read(io.BytesIO(raw_bytes))
            if cache_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(str(cache_path), audio, sr)
            return audio, sr
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                print(f"      [429 Quota] Waiting 15s before retry (attempt {attempt+1}/6)...")
                time.sleep(15)
            else:
                print(f"      [Error] {e}. Retrying in 3s...")
                time.sleep(3)

    raise RuntimeError(f"Failed to generate Gemini block: {text}")


def synthesize_sarvam_block(text: str, speaker: str = "shubh", cache_path: Path = None) -> tuple[np.ndarray, int]:
    if cache_path and cache_path.exists() and cache_path.stat().st_size > 1000:
        audio, sr = sf.read(str(cache_path))
        return audio, sr

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    generate_sarvam_tts(
        text=text,
        output_path=str(cache_path),
        speaker=speaker,
        pace=1.18,
        model="bulbul:v3"
    )
    audio, sr = sf.read(str(cache_path))
    return audio, sr


def build_timestamp_synced_audio(
    blocks: list[dict],
    synth_fn,
    total_video_duration: float,
    sample_rate: int = 24000
) -> np.ndarray:
    """
    Builds master audio buffer where every speech block is anchored strictly
    to its exact start timestamp in the SRT file.
    """
    master_buffer = np.zeros(int((total_video_duration + 5.0) * sample_rate), dtype=np.float32)

    for i, b in enumerate(blocks, 1):
        idx = b["index"]
        t_start = b["start"]
        t_end = b["end"]
        target_dur = max(t_end - t_start, 0.8)

        # Available window before next block starts
        if i < len(blocks):
            avail_dur = max(blocks[i]["start"] - t_start, 0.8)
        else:
            avail_dur = max(t_end - t_start + 1.5, 1.5)

        print(f"  [{i:02d}/{len(blocks):02d}] Block #{idx:02d} ({t_start:.2f}s -> {t_end:.2f}s | Window: {avail_dur:.2f}s)...")
        raw_audio, sr = synth_fn(b)
        
        # Trim silence
        clean_audio = trim_silence(raw_audio)
        actual_dur = len(clean_audio) / sr

        # Micro-pace line if it overflows the available window
        if actual_dur > avail_dur * 1.02:
            speed = min(actual_dur / avail_dur, 1.40)
            clean_audio = adjust_audio_speed(clean_audio, sr, speed)
            print(f"         Micro-paced {speed:.2f}x ({actual_dur:.2f}s -> {len(clean_audio)/sr:.2f}s)")

        # Exact SRT start anchor
        anchor_sample = int(t_start * sample_rate)
        end_sample = anchor_sample + len(clean_audio)

        if end_sample > len(master_buffer):
            master_buffer = np.pad(master_buffer, (0, end_sample - len(master_buffer) + sample_rate * 5))

        master_buffer[anchor_sample:end_sample] += clean_audio

    # Normalization
    peak = np.max(np.abs(master_buffer))
    if peak > 0:
        master_buffer = master_buffer / peak * 0.95

    return master_buffer


def mux_video_with_yt_shorts_mastering(
    raw_video_path: Path,
    voice_wav_path: Path,
    out_video_path: Path
):
    print(f"\n[Mastering] Creating YouTube Shorts broadcast mix for: {out_video_path.name}")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(raw_video_path),
        "-i", str(voice_wav_path),
        "-filter_complex",
        "[1:a]highpass=f=80,treble=g=3:f=3000,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,loudnorm=I=-14:TP=-1.5:LRA=7[voice];"
        "[0:a]volume=0.18[bg];"
        "[voice][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        str(out_video_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"[SUCCESS] Video successfully dubbed: {out_video_path.name}")
    else:
        print(f"[Error] FFmpeg error: {res.stderr[:400]}")


def main():
    srt_file = Path(r"output/2026-08-19 08.59.00-Video-熊猫观影-#电影解说 #影视解说_hindi.srt")
    vid_file = Path(r"output/2026-08-19 08.59.00-Video-熊猫观影-#电影解说 #影视解说.mp4")

    blocks = load_srt_blocks(srt_file)
    print(f"Loaded {len(blocks)} subtitle blocks from {srt_file.name}")

    # Video duration
    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(vid_file)]
    vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())
    print(f"Target Video Duration: {vid_dur:.2f}s")

    # -------------------------------------------------------------
    # 1. Sarvam AI (Shubh) - Block-by-Block Exact Timed Dub
    # -------------------------------------------------------------
    print("\n" + "=" * 50)
    print(" 1. Generating Sarvam AI (Shubh) Block-by-Block")
    print("=" * 50)
    cache_dir_sarvam = Path("output/sarvam_shubh_blocks")

    def synth_sarvam(b):
        idx = b["index"]
        cache_p = cache_dir_sarvam / f"block_{idx:02d}.mp3"
        audio, sr = synthesize_sarvam_block(b["text"], speaker="shubh", cache_path=cache_p)
        return audio, sr

    master_sarvam = build_timestamp_synced_audio(blocks, synth_sarvam, vid_dur, sample_rate=48000)
    wav_sarvam = Path("output/master_sarvam_shubh_exact_synced.wav")
    sf.write(str(wav_sarvam), master_sarvam, 48000)

    out_sarvam = Path("output/2026-08-19_movie_hindi_sarvam_shubh_synced.mp4")
    mux_video_with_yt_shorts_mastering(vid_file, wav_sarvam, out_sarvam)
    print(f"\n[DONE] Frame-accurate dubbed video created:\n  -> {out_sarvam.resolve()}")

if __name__ == "__main__":
    main()
