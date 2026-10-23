#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dub_gemini_enzo.py
==================
Synthesizes speech using Gemini 3.8 Flash TTS with speaker 'Enzo' and dubs
the target video with frame-accurate SRT timeline synchronization.
Features automatic multi-key rotation to bypass Free Tier rate limits.
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
from google.genai.errors import ClientError

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts_engine import load_srt_blocks


def trim_audio_silence(audio: np.ndarray, threshold: float = 0.005, pad_samples: int = 480) -> np.ndarray:
    """Trim digital zero-padding and dead silence from start and end."""
    mask = np.abs(audio) > threshold
    if not np.any(mask):
        return audio
    first = max(0, int(np.argmax(mask) - pad_samples))
    last = min(len(audio), int(len(mask) - np.argmax(mask[::-1]) + pad_samples))
    return audio[first:last]


def adjust_audio_speed(audio: np.ndarray, sample_rate: int, speed: float) -> np.ndarray:
    """Speed up or slow down audio using ffmpeg atempo filter."""
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


class GeminiTTSManager:
    def __init__(self, api_keys: list[str], model: str = "gemini-3.8-flash-tts", voice: str = "Enzo"):
        self.api_keys = api_keys
        self.key_idx = 0
        self.model = model
        self.voice = voice

    def get_client(self):
        key = self.api_keys[self.key_idx % len(self.api_keys)]
        return genai.Client(api_key=key)

    def rotate_key(self):
        self.key_idx = (self.key_idx + 1) % len(self.api_keys)
        print(f"  [Key Rotation] Switched to Key #{self.key_idx + 1}/{len(self.api_keys)}")

    def synthesize_text(self, text: str, max_retries: int = 10) -> tuple[np.ndarray, int]:
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": self.voice}}}
        )

        for attempt in range(max_retries):
            client = self.get_client()
            try:
                res = client.models.generate_content(
                    model=self.model,
                    contents=text,
                    config=config
                )
                raw_bytes = res.candidates[0].content.parts[0].inline_data.data
                audio_data, sr = sf.read(io.BytesIO(raw_bytes))
                # Rotate key round-robin after successful call to distribute RPM quota
                self.rotate_key()
                return audio_data, sr
            except ClientError as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    print(f"  [429 Quota Hit on Key #{self.key_idx + 1}] Rotating key and retrying...")
                    self.rotate_key()
                    time.sleep(1.0)
                else:
                    raise
            except Exception as e:
                print(f"  [Error] {e}. Retrying in 2s...")
                time.sleep(2.0)

        raise RuntimeError(f"Failed to synthesize text after {max_retries} attempts: {text[:30]}...")


def main():
    srt_file = Path(r"output/2026-08-19 08.59.00-Video-熊猫观影-#电影解说 #影视解说_hindi.srt")
    vid_file = Path(r"output/2026-08-19 08.59.00-Video-熊猫观影-#电影解说 #影视解说.mp4")
    out_synced = Path(r"output/2026-08-19 08.59.00-Video-熊猫观影-#电影解说 #影视解说_hindi_gemini_enzo.mp4")
    out_flow = Path(r"output/2026-08-19 08.59.00-Video-熊猫观影-#电影解说 #影视解说_hindi_gemini_enzo_flow.mp4")

    print("==================================================")
    print("  Gemini TTS Dubbing Studio (Speaker: Enzo)")
    print(f"  Subtitles   : {srt_file.name}")
    print(f"  Source Video: {vid_file.name}")
    print(f"  Output Video: {out_synced.name}")
    print("==================================================")

    # 1. Parse SRT
    blocks = load_srt_blocks(srt_file)
    print(f"[Gemini TTS] Loaded {len(blocks)} subtitle blocks from SRT.")

    # 2. Setup Gemini keys & manager
    env_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
    single_key = os.getenv("GEMINI_API_KEY")
    if single_key and single_key not in env_keys:
        env_keys.insert(0, single_key)

    if not env_keys:
        raise ValueError("No GEMINI_API_KEY or GEMINI_API_KEYS found in environment.")

    print(f"[Gemini TTS] Active Key Pool: {len(env_keys)} keys available for round-robin rotation.")
    tts_mgr = GeminiTTSManager(api_keys=env_keys, model="gemini-3.8-flash-tts", voice="Enzo")

    # 3. Synthesize each block
    sample_rate = 24000
    block_audios = []

    print("\n[Gemini TTS] Synthesizing speech blocks...")
    t_start = time.time()
    for i, b in enumerate(blocks, 1):
        t0 = time.time()
        print(f"[{i:02d}/{len(blocks):02d}] Synthesizing Block #{b['index']} ({b['start']:.2f}s -> {b['end']:.2f}s)...")
        audio, sr = tts_mgr.synthesize_text(b["text"])
        if sr != sample_rate:
            # Resample if needed
            audio = adjust_audio_speed(audio, sr, 1.0)
        block_audios.append({
            "block": b,
            "audio": audio,
            "sr": sample_rate,
            "raw_dur": len(audio) / sample_rate,
            "target_dur": b["end"] - b["start"],
            "elapsed": time.time() - t0
        })
        print(f"      Synthesized in {time.time() - t0:.2f}s | Audio duration: {len(audio)/sample_rate:.2f}s (Target: {b['end']-b['start']:.2f}s)")
        time.sleep(0.5)  # small courtesy pause between calls

    print(f"[Gemini TTS] All {len(blocks)} blocks synthesized in {time.time() - t_start:.1f}s.")

    # 4. Master Timeline Assembly (Time-anchored alignment)
    last_end = max(b["end"] for b in blocks)
    total_sec = last_end + 10.0
    master_buffer = np.zeros(int(total_sec * sample_rate), dtype=np.float32)

    timeline_sample = int(blocks[0]["start"] * sample_rate)

    print("\n[Gemini TTS] Aligning speech blocks onto master timeline...")
    for i, item in enumerate(block_audios):
        b = item["block"]
        audio = item["audio"]
        trimmed = trim_audio_silence(audio, pad_samples=int(0.02 * sample_rate))
        raw_dur = len(trimmed) / sample_rate

        orig_start_sample = int(b["start"] * sample_rate)
        # Determine available window until next block
        if i + 1 < len(block_audios):
            next_start = block_audios[i + 1]["block"]["start"]
            avail_dur = max(next_start - b["start"], 0.8)
        else:
            avail_dur = max(b["end"] - b["start"] + 1.5, 1.5)

        # Smooth tempo compression if line exceeds available scene window
        if raw_dur > avail_dur * 1.04:
            speed_factor = min(raw_dur / avail_dur, 1.35)
            trimmed = adjust_audio_speed(trimmed, sample_rate, speed_factor)
            print(f"  [Block #{b['index']:02d}] Compressed {speed_factor:.2f}x to fit {avail_dur:.2f}s scene window")

        # Natural breathing pause between blocks
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

    # Peak normalization
    peak = np.max(np.abs(master_buffer[:timeline_sample]))
    if peak > 0:
        master_buffer = master_buffer / peak * 0.96

    master_wav = Path("output/master_gemini_enzo_synced.wav")
    master_mp3 = Path("output/master_gemini_enzo_synced.mp3")

    sf.write(str(master_wav), master_buffer[:timeline_sample + int(0.5 * sample_rate)], sample_rate)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(master_wav), "-b:a", "192k", str(master_mp3)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print(f"\n[Gemini TTS] Synced master voiceover exported: {master_mp3.name} ({timeline_sample/sample_rate:.1f}s)")

    # 5. Mux frame-synced master into video
    print(f"[Gemini TTS] Muxing audio into {out_synced.name}...")
    cmd_mux = [
        "ffmpeg", "-y",
        "-i", str(vid_file),
        "-i", str(master_mp3),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(out_synced)
    ]
    res_mux = subprocess.run(cmd_mux, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res_mux.returncode == 0:
        print(f"\n==================================================")
        print(f" [SUCCESS] Frame-Synchronized Dubbed Video Created:")
        print(f" {out_synced.resolve()}")
        print(f"==================================================")
    else:
        print(f"[Error] Muxing failed: {res_mux.stderr.decode('utf-8', errors='replace')}")

    # 6. Also create continuous flow version from existing stream if present
    stream_wav = Path("output/gemini_enzo_full_stream.wav")
    if stream_wav.exists():
        cmd_flow = [
            "ffmpeg", "-y",
            "-i", str(vid_file),
            "-i", str(stream_wav),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            str(out_flow)
        ]
        res_flow = subprocess.run(cmd_flow, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res_flow.returncode == 0:
            print(f" [SUCCESS] Continuous Flow Video Created:")
            print(f" {out_flow.resolve()}")


if __name__ == "__main__":
    main()
