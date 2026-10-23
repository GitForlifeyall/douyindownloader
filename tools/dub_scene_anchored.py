#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dub_scene_anchored.py
=====================
Scene-Anchored Batching Video Dubber with Smart Visual Sub-Anchor Spacing.
Synthesizes each visual chapter in 1 API call (4 requests total), then uses
local CUDA Faster-Whisper to detect sentence boundaries within each chapter
and distributes them to match the exact on-screen visual cuts without outrunning
the video or leaving dead gaps.
"""

import os
import sys
import time
import io
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Tuple

import numpy as np
import soundfile as sf
from google import genai
from google.genai import types
from google.genai.errors import ClientError

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts_engine import load_srt_blocks
from faster_whisper import WhisperModel


def trim_audio_silence(audio: np.ndarray, threshold: float = 0.005, pad_samples: int = 480) -> np.ndarray:
    mask = np.abs(audio) > threshold
    if not np.any(mask):
        return audio
    first = max(0, int(np.argmax(mask) - pad_samples))
    last = min(len(audio), int(len(mask) - np.argmax(mask[::-1]) + pad_samples))
    return audio[first:last]


def adjust_audio_rubberband(audio: np.ndarray, sample_rate: int, target_duration: float) -> np.ndarray:
    current_duration = len(audio) / sample_rate
    if current_duration <= 0.1 or target_duration <= 0.1:
        return audio

    ratio = current_duration / target_duration
    if ratio <= 1.02:
        return audio

    temp_in = io.BytesIO()
    sf.write(temp_in, audio, sample_rate, format="WAV")
    wav_bytes = temp_in.getvalue()

    safe_tempo = min(ratio, 1.25)
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


def slice_scene_audio_by_whisper(
    audio: np.ndarray,
    sr: int,
    blocks: List[Dict[str, Any]],
    whisper_model: WhisperModel,
    temp_path: Path
) -> List[np.ndarray]:
    """Uses local CUDA Whisper word timestamps to split scene audio into individual block slices."""
    if len(blocks) <= 1:
        return [audio]

    sf.write(str(temp_path), audio, sr)
    segments, _ = whisper_model.transcribe(str(temp_path), language="hi", word_timestamps=True)
    all_words = []
    for s in segments:
        if s.words:
            all_words.extend(s.words)

    if temp_path.exists():
        try: temp_path.unlink()
        except Exception: pass

    if not all_words or len(all_words) < len(blocks):
        # Fallback to proportional slicing if words couldn't be detected
        chunk_len = len(audio) // len(blocks)
        return [audio[i * chunk_len : (i + 1) * chunk_len if i + 1 < len(blocks) else len(audio)] for i in range(len(blocks))]

    target_counts = [len(b["text"].split()) for b in blocks]
    cum_target = np.cumsum(target_counts)
    total_target = cum_target[-1]

    slices = []
    prev_sample = 0
    total_samples = len(audio)

    for i in range(len(blocks)):
        if i == len(blocks) - 1:
            end_sample = total_samples
        else:
            ratio = cum_target[i] / total_target
            approx_w_idx = int(round(ratio * len(all_words))) - 1
            approx_w_idx = max(0, min(approx_w_idx, len(all_words) - 2))

            # Look for the cleanest inter-word pause gap around the expected word position
            best_idx = approx_w_idx
            best_gap = -1.0
            for k in range(max(0, approx_w_idx - 4), min(len(all_words) - 1, approx_w_idx + 5)):
                gap = all_words[k+1].start - all_words[k].end
                if gap > best_gap:
                    best_gap = gap
                    best_idx = k

            split_time = (all_words[best_idx].end + all_words[best_idx + 1].start) / 2.0
            end_sample = int(split_time * sr)

        slice_data = audio[prev_sample:end_sample]
        slices.append(slice_data)
        prev_sample = end_sample

    return slices


def main():
    srt_path = Path("output/latest_hindi.srt")
    vid_path = Path("output/latest_original.mp4")
    out_vid = Path("output/scene_anchored_dubbed.mp4")

    # Locate BGM stem
    stem_dirs = [d for d in Path("output").iterdir() if d.is_dir() and "stems_" in d.name and "2026-10-10" in d.name]
    bgm_path = stem_dirs[0] / "no_vocals.wav" if stem_dirs and (stem_dirs[0] / "no_vocals.wav").exists() else None

    # Load API keys
    env_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
    single_key = os.getenv("GEMINI_API_KEY")
    if single_key and single_key not in env_keys:
        env_keys.insert(0, single_key)

    print("==================================================")
    print(" [Scene-Anchored Dubbing] Smart Visual Sub-Anchor Spacing")
    print(f" Target Subtitles : {srt_path.name}")
    print(f" Source Video     : {vid_path.name}")
    print(f" Active Key Pool  : {len(env_keys)} keys loaded from .env")
    print(f" Preserved BGM    : {bgm_path.name if bgm_path else 'None'}")
    print(f" Final Output     : {out_vid.name}")
    print("==================================================")

    blocks = load_srt_blocks(srt_path)
    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(vid_path)]
    vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())

    acts = [
        {
            "act_num": 1,
            "title": "Setup & Ingredient Prep",
            "blocks": blocks[0:5],
            "start_time": 0.00,
            "end_time": blocks[5]["start"]
        },
        {
            "act_num": 2,
            "title": "Steaming Rice & Yeast Mixture",
            "blocks": blocks[5:9],
            "start_time": blocks[5]["start"],
            "end_time": blocks[9]["start"]
        },
        {
            "act_num": 3,
            "title": "Fermentation & Stirring",
            "blocks": blocks[9:14],
            "start_time": blocks[9]["start"],
            "end_time": blocks[14]["start"]
        },
        {
            "act_num": 4,
            "title": "Unsealing, Distillation & Tasting",
            "blocks": blocks[14:19],
            "start_time": blocks[14]["start"],
            "end_time": vid_dur
        }
    ]

    cache_dir = Path("output/scene_cache_orus")
    cache_dir.mkdir(parents=True, exist_ok=True)

    sample_rate = 24000
    model_name = "gemini-3.8-flash-tts"
    speaker = "Orus"

    # Step 1: Synthesize or load cached act audio (4 requests max)
    print(f"\n[Gemini TTS] Loading/Synthesizing {len(acts)} Visual Chapters...")
    act_audios = []
    for i, act in enumerate(acts, 1):
        window_dur = act["end_time"] - act["start_time"]
        text_body = " ".join(b["text"].strip() for b in act["blocks"])
        c_file = cache_dir / f"scene_{act['act_num']:02d}.wav"

        if c_file.exists() and c_file.stat().st_size > 1000:
            raw_audio, sr = sf.read(str(c_file))
            print(f"  ✓ Loaded Act {act['act_num']}: {len(raw_audio)/sr:.2f}s audio (Cache hit, 0 API calls)")
        else:
            config = types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": speaker}}}
            )
            prompt = (
                f"[Tone: High-energy dramatic action recap narrator for YouTube Shorts. Speak naturally in one continuous take without awkward pauses.]\n\n"
                f"{text_body}"
            )
            raw_audio = None
            sr = 24000
            for key_attempt in range(len(env_keys)):
                k_idx = (i - 1 + key_attempt) % len(env_keys)
                key = env_keys[k_idx]
                print(f"  Requesting Gemini TTS for Act {act['act_num']} (Key #{k_idx + 1}/{len(env_keys)})...")
                client = genai.Client(api_key=key)
                try:
                    t0 = time.time()
                    res = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config
                    )
                    part = res.candidates[0].content.parts[0]
                    raw_bytes = part.inline_data.data
                    audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                    sf.write(str(c_file), audio_array, sr)
                    raw_audio = audio_array
                    print(f"  ✓ Synthesized Act {act['act_num']} in {time.time() - t0:.2f}s ({len(raw_audio)/sr:.2f}s audio)")
                    time.sleep(1.0)
                    break
                except ClientError as e:
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        print(f"    [429 Quota Exceeded on Key #{k_idx + 1}] Rotating to next key...")
                        time.sleep(1.0)
                    else:
                        raise
            if raw_audio is None:
                raise RuntimeError(f"All keys exhausted for Act {act['act_num']}")

        act_audios.append({
            "act": act,
            "audio": raw_audio,
            "sr": sr
        })

    # Step 2: Slice each act using Local CUDA Whisper word timestamps
    print("\n[Local CUDA Whisper] Aligning sentence boundaries inside each chapter (0 API calls)...")
    whisper_model = WhisperModel("base", device="cuda", compute_type="int8_float16")

    master_buffer = np.zeros(int((vid_dur + 5.0) * sample_rate), dtype=np.float32)
    prev_end_time = 0.0

    for item in act_audios:
        act = item["act"]
        raw_act_audio = item["audio"]
        sr = item["sr"]
        act_blocks = act["blocks"]

        temp_slice_wav = cache_dir / f"_temp_slice_{act['act_num']:02d}.wav"
        slices = slice_scene_audio_by_whisper(raw_act_audio, sr, act_blocks, whisper_model, temp_slice_wav)

        print(f"\n--- Act {act['act_num']}: {act['title']} ---")
        for j, b in enumerate(act_blocks):
            slice_data = slices[j]
            clean = trim_audio_silence(slice_data, pad_samples=int(0.02 * sr))
            slice_dur = len(clean) / sr

            # Available visual window for this individual sentence
            if j + 1 < len(act_blocks):
                next_visual_start = act_blocks[j + 1]["start"]
            elif act["act_num"] < len(acts):
                next_visual_start = acts[act["act_num"]]["start_time"]
            else:
                next_visual_start = vid_dur

            window_dur = max(next_visual_start - b["start"], 0.8)

            # Micro-compress only if this sentence exceeds its on-screen visual cut
            if slice_dur > window_dur * 1.04:
                clean = adjust_audio_rubberband(clean, sr, window_dur)
                slice_dur = len(clean) / sr

            # Waterfall anchor: locked to visual cut, but never overlaps previous speech
            target_start = b["start"]
            act_start_time = max(target_start, prev_end_time + 0.04)

            start_sample = int(act_start_time * sample_rate)
            end_sample = start_sample + len(clean)

            if end_sample > len(master_buffer):
                master_buffer = np.pad(master_buffer, (0, end_sample - len(master_buffer) + sample_rate * 5))

            master_buffer[start_sample:end_sample] += clean
            prev_end_time = end_sample / sample_rate

            pause_before = act_start_time - target_start if act_start_time > target_start else 0.0
            print(f"  Block #{b['index']:02d} placed at {act_start_time:5.2f}s -> {prev_end_time:5.2f}s (Visual cut: {b['start']:5.2f}s, dur: {slice_dur:4.2f}s)")

    # Peak normalization
    peak = np.max(np.abs(master_buffer[:int(vid_dur * sample_rate)]))
    if peak > 0:
        master_buffer = master_buffer / peak * 0.95

    master_wav = Path("output/scene_anchored_master.wav")
    sf.write(str(master_wav), master_buffer[:int(vid_dur * sample_rate)], sample_rate)

    # Video Muxing with preserved BGM ducking
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
        print(" [SUCCESS] Smart Visual Sub-Anchored Video Created:")
        print(f" Path: {out_vid.resolve()}")
        print("==================================================")
    else:
        print(f"[Error] Muxing failed: {res.stderr.decode('utf-8', errors='replace')}")


if __name__ == "__main__":
    main()
