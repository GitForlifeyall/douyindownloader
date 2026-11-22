#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_bunty_clone_dub.py
===========================
Generates Hindi video dub using Google AI Studio API Key and the "Bunty Clone" persona
(youthful, witty, high-energy 22-year-old North Indian viral shorts creator) on gemini-3.8-flash.
Places final output strictly in output/final_videos/.
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
from google import genai
from google.genai import types

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts_google import parse_gemini_audio_response, adjust_audio_speed, trim_audio_silence
from dubbing_studio.tts_engine import load_srt_blocks

BUNTY_SYSTEM_INSTRUCTION = """# PERSONA: BUNTY (YOUTHFUL, WITTY HINDI SHORTS CREATOR)
You are Bunty — a 22-year-old high-energy, witty North Indian storyteller narrating viral video clips for Instagram Reels and YouTube Shorts. 

# VOCAL CHARACTER & TEXTURE
- Vocal Age: 20–24 years old.
- Tone: Playful, street-smart, slightly mischievous, with an audible smirk or grin in your voice.
- Energy: High-octane, conversational, hooking the audience immediately.
- Pitch & Inflection: Highly dynamic — pitch jumps on punchlines, dramatic moments, and sarcastic remarks.
- Accent: Colloquial Delhi/UP conversational Hindi. Sounds like an expressive real person chatting excitedly, NOT a robot.

# CADENCE
- Keep pacing rapid, crisp, and snappy to match quick visual jump cuts.
- Speak with natural breathing and clear articulation.

# OUTPUT INSTRUCTION
- Speak ONLY the exact Hindi text provided. Do not add introductory conversational filler."""


def main():
    api_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    client = genai.Client(api_key=api_key)

    root = Path.cwd()
    clean_video = root / "output/clean_videos/道可道 - 恭喜你成功制作出桂花蜜_clean.mp4"
    bgm_stem = root / "output/audio_stems/stems_道可道 - 恭喜你成功制作出桂花蜜/no_vocals.wav"
    hindi_srt = root / "output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hindi.srt"

    final_dir = root / "output/final_videos"
    stems_dir = root / "output/audio_stems"
    cache_dir = stems_dir / "google_tts_cache_bunty_clone_hindi"
    cache_dir.mkdir(parents=True, exist_ok=True)

    final_video = final_dir / "道可道 - 恭喜你成功制作出桂花蜜_hindi_bunty_clone_dubbed.mp4"

    print("==================================================")
    print(" [Bunty Clone TTS] Starting Video Dubbing")
    print(f" API Key Prefix : {api_key[:12]}...")
    print(f" Voice Persona  : Bunty Clone (Puck + System Instruction)")
    print(f" Subtitles      : {hindi_srt.name}")
    print(f" Clean Video    : {clean_video.name}")
    print(f" Foley BGM Stem : {bgm_stem.name}")
    print(f" Target Video   : {final_video.name}")
    print("==================================================")

    blocks = load_srt_blocks(hindi_srt)
    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(clean_video)]
    vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())

    sample_rate = 24000
    block_audios = []

    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": "Puck"}}}
    )

    models_to_try = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview"]

    from dubbing_studio.autotagger import autotag_srt_blocks
    blocks = autotag_srt_blocks(blocks)
    print(f"\n[Autotag] Injected dynamic vocal tags & speech metadata across all {len(blocks)} blocks.")

    # Set up key pool
    env_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
    if not env_keys and api_key:
        env_keys = [api_key]
    all_keys = env_keys
    key_idx = 0

    t0_all = time.time()
    for i, b in enumerate(blocks, 1):
        idx = b["index"]
        c_file = cache_dir / f"block_{idx:02d}.wav"
        t0 = time.time()
        if c_file.exists() and c_file.stat().st_size > 500:
            raw_audio, sr = sf.read(str(c_file))
            print(f"  [{i:02d}/{len(blocks):02d}] Loaded from cache: Block #{idx:02d} ({len(raw_audio)/sr:.2f}s)")
        else:
            tag_style = b.get("style", "")
            print(f"  [{i:02d}/{len(blocks):02d}] Synthesizing Block #{idx:02d} [{tag_style}] (Puck)...")
            success = False
            for attempt in range(10):
                curr_key = all_keys[key_idx % len(all_keys)]
                m = models_to_try[attempt % len(models_to_try)]
                client = genai.Client(api_key=curr_key)
                try:
                    res = client.models.generate_content(
                        model=m,
                        contents=[b["part"]],
                        config=config
                    )
                    part = res.candidates[0].content.parts[0]
                    raw_bytes = part.inline_data.data
                    mime_type = getattr(part.inline_data, "mime_type", "audio/L16")
                    raw_audio, sr = parse_gemini_audio_response(raw_bytes, mime_type=mime_type, sample_rate=sample_rate)
                    sf.write(str(c_file), raw_audio, sr)
                    success = True
                    print(f"        ✓ Synthesized in {time.time() - t0:.2f}s ({len(raw_audio)/sr:.2f}s audio via {m})")
                    key_idx = (key_idx + 1) % len(all_keys)
                    time.sleep(0.4)
                    break
                except Exception as e:
                    print(f"        [Retry {attempt+1}/10 on Key #{key_idx+1} ({m})] Error: {e}. Rotating...")
                    key_idx = (key_idx + 1) % len(all_keys)
                    time.sleep(2.0)

            if not success:
                raise RuntimeError(f"Failed to synthesize Block #{idx:02d}")

        block_audios.append({
            "block": b,
            "audio": raw_audio,
            "sr": sr
        })

    print(f"\n[Bunty Clone] All {len(blocks)} speech blocks ready in {time.time() - t0_all:.1f}s.")

    # -------------------------------------------------------------
    # Step 2: Waterfall Anti-Overlap Assembly
    # -------------------------------------------------------------
    master_buffer = np.zeros(int((vid_dur + 5.0) * sample_rate), dtype=np.float32)
    timeline_sample = 0

    min_gap_samples = int(0.08 * sample_rate)
    max_gap_samples = int(0.18 * sample_rate)

    print("[Bunty Clone] Aligning speech blocks with zero-silence continuous flow...")
    for i, item in enumerate(block_audios):
        b = item["block"]
        raw = item["audio"]
        sr = item["sr"]

        trimmed = trim_audio_silence(raw)
        target_dur = max(0.5, b["end"] - b["start"])
        raw_dur = len(trimmed) / sr

        # Tight fit: smoothly compress if speech exceeds the available window
        if raw_dur > (target_dur * 1.05):
            compression = min(1.30, raw_dur / target_dur)
            trimmed = adjust_audio_speed(trimmed, sr, compression)
            print(f"  [Block #{b['index']:02d}] Compressed {compression:.2f}x to fit {target_dur:.2f}s scene window ({len(trimmed)/sr:.2f}s)")

        orig_start_sample = int(b["start"] * sample_rate)
        if i == 0:
            act_start = int(0.02 * sample_rate)
        else:
            earliest_start = timeline_sample + min_gap_samples
            latest_start = timeline_sample + max_gap_samples
            if orig_start_sample > latest_start:
                act_start = latest_start
            else:
                act_start = max(earliest_start, orig_start_sample)

        act_end = act_start + len(trimmed)
        if act_end > len(master_buffer):
            master_buffer = np.pad(master_buffer, (0, act_end - len(master_buffer) + sample_rate * 5))

        master_buffer[act_start:act_end] += trimmed
        timeline_sample = act_end
        print(f"  [Block #{b['index']:02d}] Placed at {act_start/sample_rate:.2f}s -> {act_end/sample_rate:.2f}s (Target slot: {b['start']:.2f}s - {b['end']:.2f}s)")

    peak_dur_samples = min(len(master_buffer), int(vid_dur * sample_rate))
    peak = np.max(np.abs(master_buffer[:peak_dur_samples]))
    if peak > 0:
        master_buffer = master_buffer / peak * 0.95

    master_wav = stems_dir / "master_bunty_clone_hindi.wav"
    sf.write(str(master_wav), master_buffer[:int(vid_dur * sample_rate)], sample_rate)
    print(f"✓ Master voiceover saved: {master_wav.name}")

    # -------------------------------------------------------------
    # Step 3: FFmpeg Muxing with Sidechain Ducking
    # -------------------------------------------------------------
    print(f"\n[Bunty Clone] Mastering video with Foley SFX into {final_video.name}...")
    filter_complex = (
        "[1:a]volume=1.05[bgm];"
        "[2:a]volume=1.35,loudnorm=I=-13:TP=-0.5:LRA=7,asplit=2[voice_sc][voice_mix];"
        "[bgm][voice_sc]sidechaincompress=threshold=0.10:ratio=3.5:attack=15:release=250[ducked_bgm];"
        "[ducked_bgm][voice_mix]amix=inputs=2:weights=1.0 1.0:normalize=0[mixed];"
        "[mixed]alimiter=limit=0.98:attack=5:release=50[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clean_video),
        "-i", str(bgm_stem),
        "-i", str(master_wav),
        "-filter_complex", filter_complex,
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "320k",
        "-movflags", "+faststart",
        str(final_video)
    ]

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    print(f"\n✓ SUCCESS! Rendered Bunty Clone Dubbed Video: {final_video.name} ({final_video.stat().st_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
