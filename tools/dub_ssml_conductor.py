#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dub_ssml_conductor.py
======================
Method 1: The "SSML Conductor" Dubbing Engine.
Uses Gemini 3.8 Flash as an acoustic sound designer to inject fine-grained
W3C SSML tags (<prosody rate/pitch>, <emphasis>, <break>) into the Hindi script,
which are executed with high-fidelity studio quality by Google Cloud Text-to-Speech.
"""

import os
import sys
import time
import io
import base64
import requests
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

import numpy as np
import soundfile as sf
from google import genai
from google.genai import types

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


SSML_SYSTEM_PROMPT = """You are an elite YouTube Shorts / viral video audio director and SSML sound designer.
Your task is to take Chinese video subtitle blocks and transcreate them into high-energy, engaging Hindi narration, AND inject fine-grained W3C SSML tags so that Google Cloud Text-to-Speech delivers a dynamic, emotional vocal performance.

CRITICAL SSML RULES:
1. Every translated block MUST be enclosed in `<speak> ... </speak>`.
2. Use `<prosody rate="..." pitch="...">` to control the urgency, excitement, and gravity of each thought:
   - For viral hooks, surprising reveals, or energetic actions: use `rate="1.15"` to `1.20"` and `pitch="+1st"` or `pitch="+2st"`.
   - For steady technical explanations or precision steps: use `rate="1.05"` and `pitch="0st"` or `pitch="-1st"`.
   - For concluding remarks or tips: use `rate="1.12"` and `pitch="+1st"`.
3. Use `<emphasis level="strong">` on key dramatic words (e.g. <emphasis level="strong">वेल्डिंग</emphasis>, <emphasis level="strong">परफेक्ट</emphasis>, <emphasis level="strong">एक झटके में</emphasis>).
4. Use natural micro-pauses between clauses: `<break time="150ms"/>` or `<break time="200ms"/>`.
5. Keep the Hindi translation natural, punchy, and conversational (colloquial Hindi/Hinglish).
6. Isochrony: Ensure the spoken length fits the block duration. Do not write oversized text.

OUTPUT FORMAT:
Return ONLY the standard SRT blocks. The text inside each subtitle block must be the complete `<speak>...</speak>` tag string.
Do not output markdown code blocks or explanations. Output pure SRT text.
"""


def generate_ssml_script(raw_srt_path: Path, out_ssml_path: Path) -> str:
    if out_ssml_path.exists() and out_ssml_path.stat().st_size > 200:
        print(f"[SSML Conductor] Found existing cached SSML script: {out_ssml_path.name}")
        return out_ssml_path.read_text(encoding="utf-8")

    print(f"\n[SSML Conductor] Prompting Gemini 3.8 Flash to compose SSML vocal choreography...")
    keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
    single_key = os.getenv("GEMINI_API_KEY")
    if single_key and single_key not in keys:
        keys.insert(0, single_key)

    raw_content = raw_srt_path.read_text(encoding="utf-8")
    user_prompt = f"Here is the raw Chinese SRT subtitle file. Transcreate it into SSML-conducted Hindi for Google Cloud TTS:\n\n{raw_content}"

    for attempt, key in enumerate(keys):
        try:
            client = genai.Client(api_key=key)
            config = types.GenerateContentConfig(
                system_instruction=SSML_SYSTEM_PROMPT,
                temperature=0.35
            )
            response = None
            for m in ["gemini-3-flash-preview", "gemini-3.8-flash", "gemini-flash-latest"]:
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=user_prompt,
                        config=config
                    )
                    break
                except Exception as model_err:
                    print(f"      [Model {m} Error]: {model_err}")
            if not response:
                raise RuntimeError("All models failed for current key.")
            text = response.text.strip()
            # Clean possible markdown wrap
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"): lines = lines[1:]
                if lines and lines[-1].startswith("```"): lines = lines[:-1]
                text = "\n".join(lines).strip()

            out_ssml_path.write_text(text, encoding="utf-8")
            print(f"[SSML Conductor] Successfully generated SSML script -> {out_ssml_path.name}")
            return text
        except Exception as e:
            print(f"[SSML Conductor] Key #{attempt+1} error: {e}. Rotating...")
            time.sleep(1.0)

    raise RuntimeError("Failed to generate SSML script with all Gemini keys.")


def synthesize_google_cloud_ssml(ssml_text: str, api_key: str, voice_name: str = "hi-IN-Chirp3-HD-Orus") -> bytes:
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    payload = {
        "input": {"ssml": ssml_text},
        "voice": {"languageCode": "hi-IN", "name": voice_name},
        "audioConfig": {"audioEncoding": "MP3"}
    }
    resp = requests.post(url, json=payload, timeout=25)
    if resp.status_code == 200:
        return base64.b64decode(resp.json()["audioContent"])
    raise RuntimeError(f"Google Cloud TTS SSML Error ({resp.status_code}): {resp.text}")


def main():
    target_vids = [p for p in Path("output").glob("*.mp4") if "2026-09-03" in p.name and not p.name.endswith("_dubbed.mp4")]
    if not target_vids:
        raise FileNotFoundError("Target video not found in output folder.")
    vid_path = target_vids[0]

    raw_srts = [p for p in Path("output").glob("*.srt") if "2026-09-03" in p.name and not "_hindi" in p.name]
    if not raw_srts:
        raise FileNotFoundError("Raw Chinese SRT not found in output folder.")
    raw_srt_path = raw_srts[0]

    stem_dirs = [d for d in Path("output").iterdir() if d.is_dir() and "stems_2026-09-03" in d.name]
    bgm_path = stem_dirs[0] / "no_vocals.wav" if stem_dirs and (stem_dirs[0] / "no_vocals.wav").exists() else None

    out_ssml_path = vid_path.parent / f"{vid_path.stem}_hindi_ssml.srt"
    out_vid = Path("output/comparison_google_cloud_ssml_conductor.mp4")

    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(vid_path)]
    vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())

    print("==================================================")
    print(" [Method 1] The SSML Conductor Engine")
    print(f" Source Video     : {vid_path.name}")
    print(f" Duration         : {vid_dur:.2f}s")
    print(f" Voice Model      : hi-IN-Chirp3-HD-Orus (SSML Controlled)")
    print(f" Output Video     : {out_vid.name}")
    print("==================================================")

    # 1. Generate SSML-infused script via Gemini 3.8 Flash
    generate_ssml_script(raw_srt_path, out_ssml_path)

    blocks = load_srt_blocks(out_ssml_path)
    print(f"[SSML Conductor] Loaded {len(blocks)} conducted blocks.")

    sample_rate = 24000
    gcloud_key = os.getenv("GOOGLE_TTS_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    cache_dir = Path("output/cache_ssml_conductor_orus")
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 2. Synthesize each block via Google Cloud TTS with SSML input
    print("\n[Google Cloud TTS] Synthesizing SSML-conducted audio blocks...")
    block_audios = []
    t0 = time.time()

    for i, b in enumerate(blocks, 1):
        idx = b["index"]
        c_wav = cache_dir / f"block_{idx:02d}.wav"
        c_mp3 = cache_dir / f"block_{idx:02d}.mp3"

        if not c_wav.exists():
            ssml_content = b["text"].strip()
            if not ssml_content.startswith("<speak>"):
                ssml_content = f"<speak>{ssml_content}</speak>"

            mp3_bytes = synthesize_google_cloud_ssml(ssml_content, gcloud_key, voice_name="hi-IN-Chirp3-HD-Orus")
            c_mp3.write_bytes(mp3_bytes)
            subprocess.run(["ffmpeg", "-y", "-i", str(c_mp3), "-ar", str(sample_rate), "-ac", "1", str(c_wav)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if c_mp3.exists():
                try: c_mp3.unlink()
                except Exception: pass

        raw_audio, sr = sf.read(str(c_wav))
        block_audios.append({"block": b, "audio": raw_audio, "sr": sample_rate})
        if i % 5 == 0 or i == len(blocks):
            print(f"  [SSML Conductor] [{i:02d}/{len(blocks):02d}] blocks synthesized")

    print(f"[Google Cloud TTS] All blocks synthesized in {time.time() - t0:.1f}s.")

    # 3. Assemble timeline with Waterfall Anti-Overlap
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

    # 4. Mux with preserved BGM sidechain ducking
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
        print(" [SUCCESS] Method 1 SSML Conductor Video Created:")
        print(f" Path: {out_vid.resolve()}")
        print("==================================================")
    else:
        raise RuntimeError(f"FFmpeg error remuxing video: {res.stderr.decode('utf-8', errors='replace')}")


if __name__ == "__main__":
    main()
