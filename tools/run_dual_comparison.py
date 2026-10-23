#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_dual_comparison.py
======================
Generates two comparison dubbed videos for the downloaded Douyin video:
  - Video 1: Google Cloud Text-to-Speech (hi-IN-Chirp3-HD-Orus)
  - Video 2: Gemini Audio TTS (gemini-2.5-flash-preview-tts / Orus)
Preserves background ambient sound effects via Demucs stem separation.
"""

import os
import sys
import time
import io
import json
import base64
import requests
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import soundfile as sf
from google import genai
from google.genai import types

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.transcriber import Transcriber
from dubbing_studio.translator import SRTDubTranslator
from dubbing_studio.separator import AudioStemSeparator
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


def synthesize_google_cloud(text: str, api_key: str, voice_name: str = "hi-IN-Chirp3-HD-Orus", speaking_rate: float = 1.12) -> bytes:
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    payload = {
        "input": {"text": text},
        "voice": {"languageCode": "hi-IN", "name": voice_name},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": speaking_rate}
    }
    resp = requests.post(url, json=payload, timeout=25)
    if resp.status_code == 200:
        return base64.b64decode(resp.json()["audioContent"])
    raise RuntimeError(f"Google Cloud TTS API Error ({resp.status_code}): {resp.text}")


class GeminiAudioSynthesizer:
    def __init__(self, keys: List[str], voice: str = "Orus", model: str = "gemini-3.8-flash-tts"):
        self.keys = keys
        self.key_idx = 0
        self.voice = voice
        self.model = model
        self.models_to_try = [model, "gemini-2.5-flash-preview-tts"] if model != "gemini-2.5-flash-preview-tts" else [model]

    def synthesize(self, text: str) -> np.ndarray:
        for model_name in self.models_to_try:
            for attempt in range(len(self.keys) * 2):
                key = self.keys[self.key_idx % len(self.keys)]
                client = genai.Client(api_key=key)
                try:
                    config = types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
                            )
                        )
                    )
                    prompt = (
                        "Read the following Hindi narration naturally, clearly, and expressively for a video voiceover. "
                        "Do not add any greetings or conversational intro, speak only the text.\n\n"
                        f"{text}"
                    )
                    response = client.models.generate_content(model=model_name, contents=prompt, config=config)

                    for part in response.candidates[0].content.parts:
                        if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
                            raw_bytes = part.inline_data.data
                            if isinstance(raw_bytes, str):
                                raw_bytes = base64.b64decode(raw_bytes)
                            audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                            return audio_array
                    raise ValueError("No audio content found in Gemini response parts.")
                except Exception as e:
                    print(f"      [Gemini {model_name} Key #{self.key_idx + 1} Error]: {e}. Rotating...")
                    self.key_idx = (self.key_idx + 1) % len(self.keys)
                    time.sleep(1.0)
        raise RuntimeError("All Gemini API keys and models failed.")


def build_and_mux_track(
    block_audios: List[Dict[str, Any]],
    vid_dur: float,
    vid_path: Path,
    bgm_path: Optional[Path],
    out_vid: Path,
    sample_rate: int = 24000
) -> Path:
    master_buffer = np.zeros(int((vid_dur + 5.0) * sample_rate), dtype=np.float32)
    timeline_sample = int(block_audios[0]["block"]["start"] * sample_rate)

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
        print(f"  ✓ Successfully created: {out_vid.name}")
        return out_vid
    else:
        raise RuntimeError(f"FFmpeg error remuxing video: {res.stderr.decode('utf-8', errors='replace')}")


def main():
    target_vids = [p for p in Path("output").glob("*.mp4") if "2026-09-03" in p.name and not p.name.endswith("_dubbed.mp4")]
    if not target_vids:
        raise FileNotFoundError("Target video not found in output folder.")
    vid_path = target_vids[0]

    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(vid_path)]
    vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())

    print("==================================================")
    print(" [Dual Comparison] Google Cloud TTS vs Gemini TTS")
    print(f" Source Video: {vid_path.name}")
    print(f" Duration    : {vid_dur:.2f}s")
    print("==================================================")

    # Step 1: Transcribe
    raw_srt = vid_path.parent / f"{vid_path.stem}.srt"
    transcriber = Transcriber(model_size="large-v3-turbo")
    transcriber.transcribe(vid_path, output_srt=raw_srt, force=False)

    # Step 2: Translate to Hindi
    hindi_srt = vid_path.parent / f"{vid_path.stem}_hindi.srt"
    if not hindi_srt.exists() or hindi_srt.stat().st_size < 100:
        translator = SRTDubTranslator(model="gemini-3.8-flash")
        trans_text, _ = translator.translate_and_rewrite_srt(raw_srt, target_language="Hindi")
        hindi_srt.write_text(trans_text, encoding="utf-8")
        print(f"[Translator] Saved Hindi SRT: {hindi_srt.name}")
    else:
        print(f"[Translator] Found existing Hindi SRT: {hindi_srt.name}")

    blocks = load_srt_blocks(hindi_srt)
    print(f"[Pipeline] Processing {len(blocks)} subtitle blocks...")

    # Step 3: Separate Stems (BGM)
    stem_separator = AudioStemSeparator(model="htdemucs")
    stems = stem_separator.separate_audio(vid_path, force=False)
    bgm_path = stems.get("no_vocals")
    print(f"[StemSeparator] Ambient BGM track: {bgm_path.name if bgm_path else 'None'}")

    sample_rate = 24000

    # -------------------------------------------------------------
    # Version 1: Google Cloud Text-to-Speech (hi-IN-Chirp3-HD-Orus)
    # -------------------------------------------------------------
    print("\n--------------------------------------------------")
    print(" [1/2] Generating Version 1: Google Cloud TTS (Chirp3-HD-Orus)")
    print("--------------------------------------------------")
    gcloud_key = os.getenv("GOOGLE_TTS_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    gc_cache_dir = Path("output/cache_comparison_gcloud_orus")
    gc_cache_dir.mkdir(parents=True, exist_ok=True)

    gc_block_audios = []
    t0 = time.time()
    for i, b in enumerate(blocks, 1):
        idx = b["index"]
        c_wav = gc_cache_dir / f"block_{idx:02d}.wav"
        c_mp3 = gc_cache_dir / f"block_{idx:02d}.mp3"

        if not c_wav.exists():
            mp3_bytes = synthesize_google_cloud(b["text"].strip(), gcloud_key, voice_name="hi-IN-Chirp3-HD-Orus", speaking_rate=1.12)
            c_mp3.write_bytes(mp3_bytes)
            subprocess.run(["ffmpeg", "-y", "-i", str(c_mp3), "-ar", str(sample_rate), "-ac", "1", str(c_wav)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if c_mp3.exists():
                try: c_mp3.unlink()
                except Exception: pass

        raw_audio, sr = sf.read(str(c_wav))
        gc_block_audios.append({"block": b, "audio": raw_audio, "sr": sample_rate})
        if i % 5 == 0 or i == len(blocks):
            print(f"  [Google Cloud TTS] [{i:02d}/{len(blocks):02d}] blocks ready")

    out_gc_vid = Path("output/comparison_google_cloud_orus.mp4")
    build_and_mux_track(gc_block_audios, vid_dur, vid_path, bgm_path, out_gc_vid, sample_rate)
    print(f"  Done in {time.time() - t0:.1f}s -> {out_gc_vid.name}")

    # -------------------------------------------------------------
    # Version 2: Gemini Audio TTS (gemini-2.5-flash-preview-tts / Orus)
    # -------------------------------------------------------------
    print("\n--------------------------------------------------")
    print(" [2/2] Generating Version 2: Gemini Audio TTS (Orus)")
    print("--------------------------------------------------")
    gemini_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
    single_key = os.getenv("GEMINI_API_KEY")
    if single_key and single_key not in gemini_keys:
        gemini_keys.insert(0, single_key)

    gemini_synthesizer = GeminiAudioSynthesizer(keys=gemini_keys, voice="Orus", model="gemini-3.8-flash-tts")
    gemini_cache_dir = Path("output/cache_comparison_gemini_orus")
    gemini_cache_dir.mkdir(parents=True, exist_ok=True)

    gemini_block_audios = []
    t1 = time.time()
    for i, b in enumerate(blocks, 1):
        idx = b["index"]
        c_wav = gemini_cache_dir / f"block_{idx:02d}.wav"

        if not c_wav.exists():
            audio_data = gemini_synthesizer.synthesize(b["text"].strip())
            sf.write(str(c_wav), audio_data, sample_rate)

        raw_audio, sr = sf.read(str(c_wav))
        gemini_block_audios.append({"block": b, "audio": raw_audio, "sr": sample_rate})
        if i % 5 == 0 or i == len(blocks):
            print(f"  [Gemini Audio TTS] [{i:02d}/{len(blocks):02d}] blocks ready")

    out_gemini_vid = Path("output/comparison_gemini_orus.mp4")
    build_and_mux_track(gemini_block_audios, vid_dur, vid_path, bgm_path, out_gemini_vid, sample_rate)
    print(f"  Done in {time.time() - t1:.1f}s -> {out_gemini_vid.name}")

    print("\n==================================================")
    print(" [SUCCESS] Both Comparison Dubbed Videos Created!")
    print(f" 1. Google Cloud TTS: {out_gc_vid.resolve()}")
    print(f" 2. Gemini Audio TTS: {out_gemini_vid.resolve()}")
    print("==================================================")


if __name__ == "__main__":
    main()
